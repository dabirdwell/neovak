#!/usr/bin/env python3
"""Tests that load no models and touch nothing outside a temporary folder.
Run: venv/bin/python3 people_screen/test_people_screen.py
"""
import os
import stat
import sys
import tempfile
import threading
import time
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

TMP = tempfile.mkdtemp(prefix="people_screen_test_")
OUT = Path(TMP) / "out"
OUT.mkdir()
OUTSIDE = Path(TMP) / "secret.png"
OUTSIDE.write_bytes(b"secret")
(OUT / "good.png").write_bytes(b"\x89PNG not really")
(OUT / "notes.txt").write_text("not media")
(OUT / "escape.png").symlink_to(OUTSIDE)
FAKE_GOV = Path(TMP) / "gov.py"
# A settings file of this test's own, so the rules tested here do not depend on the machine's.
SETTINGS_FILE = Path(TMP) / "settings.toml"
SETTINGS_FILE.write_text('[hold]\nstart = "21:25"\nend = "22:15"\nzone = "America/Chicago"\n'
                         '[writers]\nquick = "http://127.0.0.1:9"\ncareful = "http://127.0.0.1:9"\n')
os.environ.update(PS_STATE_DIR=str(Path(TMP) / "state"), PS_OUTPUT_DIR=str(OUT), PS_GOVERNOR=str(FAKE_GOV),
                  PS_BACKEND="http://127.0.0.1:9", PS_HELPER="http://127.0.0.1:9", NEOVAK_SETTINGS=str(SETTINGS_FILE))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import core  # noqa: E402
import app as screen  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402

NO_GO = ('print("Need ~16.0 GB  |  reclaimable 9.2 GB  |  margin -6.8 GB (safety 4.0)")\n'
         'print("VERDICT: NO-GO \\u2014 free memory first (see `free <GiB>`).")\n'
         'raise SystemExit(1)\n')
GO = 'print("Need ~16.0 GB  |  reclaimable 42.0 GB  |  margin +26.0 GB (safety 4.0)")\nprint("VERDICT: GO")\n'


def governor_says(text):
    core._busy_cache.update(value=False, last_true=0.0, at=time.time())  # a test before this one may have left the queue "just busy"
    FAKE_GOV.write_text(text)
    FAKE_GOV.chmod(FAKE_GOV.stat().st_mode | stat.S_IXUSR)


orig_run = core.run_process
client = TestClient(screen.app, base_url="http://127.0.0.1:8102")
# Every route needs a session now (test_sign_in.py covers the door itself); this client is signed in as a tester.
TESTER, _ = screen.PEOPLE.add("Tester")
SESSION = screen.SESSIONS.create(TESTER)
client.cookies.set(screen.auth.COOKIE, SESSION)
screen.SAME_PRESS_SECONDS = -1  # these tests send the same body again on purpose
HEADERS = {"Content-Type": "application/json"}
IMAGE = {"lane": "image", "prompt": "a test"}


class PathTraversal(unittest.TestCase):
    def test_helper(self):
        self.assertIsNotNone(core.safe_media_path("good.png"))
        for bad in ("../secret.png", "../../etc/passwd", "/etc/passwd", "a/../../secret.png", "..\\secret.png",
                    "good.png\x00.png", "", "notes.txt", "escape.png", "nope.png", None, 7):
            self.assertIsNone(core.safe_media_path(bad), repr(bad))

    def test_routes(self):
        self.assertEqual(client.get("/media/good.png").status_code, 200)
        for bad in ("/media/../secret.png", "/media/%2e%2e/secret.png", "/media/..%2fsecret.png",
                    "/media/%2fetc%2fpasswd", "/media/escape.png", "/media/notes.txt",
                    "/thumb/..%2fsecret.png"):
            r = client.get(bad)
            self.assertNotEqual(r.status_code, 200, bad)
            self.assertNotIn(b"secret", r.content, bad)


class GovernorRefusal(unittest.TestCase):
    def setUp(self):
        self.hold = mock.patch.object(core, "hold_status", return_value={"active": False, "message": ""})
        self.hold.start()
        self.addCleanup(self.hold.stop)

    def test_no_go_starts_nothing_and_says_what_is_short(self):
        governor_says(NO_GO)
        with mock.patch.object(core, "backend_post") as post, mock.patch.object(core.GENERATION, "begin") as begin:
            r = client.post("/api/create", json=IMAGE, headers=HEADERS)
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.json()["kind"], "memory")
        self.assertIn("GB short", r.json()["error"])
        self.assertIn("9.2 GB", r.json()["error"])
        # the screen may ask the engine how long the job would take (a read, /api/jobs/estimate); it must not submit one
        self.assertEqual([c for c in post.call_args_list if c.args and c.args[0] != "/api/jobs/estimate"], [])
        begin.assert_not_called()

    def test_silent_governor_fails_closed(self):
        governor_says("print('nothing useful')\n")
        with mock.patch.object(core.GENERATION, "begin") as begin:
            r = client.post("/api/create", json=IMAGE, headers=HEADERS)
        self.assertEqual(r.status_code, 409)
        begin.assert_not_called()

    def test_go_starts(self):
        governor_says(GO)
        with mock.patch.object(core, "engine_answering", return_value=True), \
                mock.patch.object(core, "run_image", return_value={"name": "good.png", "seed": 5}), \
                mock.patch.dict(core.RUNNERS, {"image": lambda job: {"name": "good.png", "seed": 5}}):
            r = client.post("/api/create", json=IMAGE, headers=HEADERS)
        self.assertEqual(r.status_code, 202)

    def test_no_go_enhance(self):
        governor_says(NO_GO)
        with mock.patch.object(core.ENHANCE, "begin") as begin:
            r = client.post("/api/enhance", json={"prompt": "a dog"}, headers=HEADERS)
        self.assertEqual(r.status_code, 409)
        begin.assert_not_called()


class Rules(unittest.TestCase):
    def test_nightly_hold(self):
        c = core.CENTRAL
        self.assertFalse(core.hold_status(datetime(2026, 11, 9, 21, 24, 59, tzinfo=c))["active"])
        self.assertTrue(core.hold_status(datetime(2026, 11, 9, 21, 25, 0, tzinfo=c))["active"])
        self.assertTrue(core.hold_status(datetime(2026, 11, 9, 22, 14, 59, tzinfo=c))["active"])
        self.assertFalse(core.hold_status(datetime(2026, 11, 9, 22, 15, 0, tzinfo=c))["active"])
        self.assertTrue(core.hold_status(datetime(2026, 11, 9, 21, 20, 0, tzinfo=c), estimate_seconds=600)["active"])

    def test_hold_blocks_create(self):
        governor_says(GO)
        with mock.patch.object(core, "hold_status", return_value={"active": True, "message": "held"}), \
                mock.patch.object(core.GENERATION, "begin") as begin:
            r = client.post("/api/create", json=IMAGE, headers=HEADERS)
        self.assertEqual(r.status_code, 423)
        begin.assert_not_called()

    def test_badges(self):
        reading = {"available_gb": 30.0, "safety_gb": 4.0}
        self.assertEqual(core.badge_for(10, reading)["badge"], "green")
        self.assertEqual(core.badge_for(18, reading)["badge"], "yellow")
        self.assertEqual(core.badge_for(24, reading)["badge"], "orange")
        red = core.badge_for(40, reading)
        self.assertEqual(red["badge"], "red")
        self.assertFalse(red["fits"])
        self.assertFalse(core.badge_for(10, {})["fits"])

    def test_unknown_or_unrouted_model_refused(self):
        r = client.post("/api/create", json=dict(IMAGE, model="flux2-klein-9b"), headers=HEADERS)
        self.assertEqual(r.status_code, 400)
        if not all(s["routed"] for s in core.IMAGE_MODELS.values()):
            off = next(k for k, s in core.IMAGE_MODELS.items() if not s["routed"])
            r = client.post("/api/create", json=dict(IMAGE, model=off), headers=HEADERS)
            self.assertEqual(r.status_code, 400)

    def test_unknown_lane_refused(self):
        r = client.post("/api/create", json={"lane": "smell", "prompt": "a test"}, headers=HEADERS)
        self.assertEqual(r.status_code, 400)
        self.assertIn("Please pick", r.json()["error"])

    def test_other_sites_cannot_post(self):
        r = client.post("/api/create", json=IMAGE, headers=dict(HEADERS, Origin="http://evil.example"))
        self.assertEqual(r.status_code, 400)
        r = client.post("/api/create", content="prompt=x", headers={"Content-Type": "text/plain"})
        self.assertEqual(r.status_code, 400)

    def test_foreign_host_refused(self):
        other = TestClient(screen.app, base_url="http://evil.example")
        other.cookies.set(screen.auth.COOKIE, SESSION)  # even signed in, a wrong Host is refused before anything else
        self.assertEqual(other.get("/").status_code, 400)

    def test_leading_dashes_removed(self):
        self.assertEqual(core.clean_prompt("  --help me"), "help me")

    def test_a_second_request_joins_the_line_until_the_line_is_full(self):
        governor_says(GO)
        release = threading.Event()

        def slow(job):
            release.wait(20)
            return {"name": "good.png", "seed": 5}

        with mock.patch.object(core, "engine_answering", return_value=True), \
                mock.patch.dict(core.RUNNERS, {"image": slow}), \
                mock.patch.object(core, "hold_status", return_value={"active": False, "message": ""}), \
                mock.patch.object(core, "MAX_WAITING", 3):
            first = client.post("/api/create", json=IMAGE, headers=HEADERS)
            second = client.post("/api/create", json=IMAGE, headers=HEADERS)
            third = client.post("/api/create", json=IMAGE, headers=HEADERS)
            fourth = client.post("/api/create", json=IMAGE, headers=HEADERS)
            release.set()
        self.assertEqual([first.status_code, second.status_code, third.status_code], [202, 202, 202])
        self.assertEqual(fourth.status_code, 409)
        self.assertIn("waiting", fourth.json()["error"])
        for _ in range(100):
            if not core.GENERATION.active():
                break
            time.sleep(0.05)

    def test_count_makes_several_jobs_each_with_its_own_seed(self):
        governor_says(GO)
        release = threading.Event()
        seen = []

        def slow(job):
            seen.append(job["params"]["seed"])
            release.wait(20)
            return {"name": "good.png", "seed": job["params"]["seed"]}

        with mock.patch.object(core, "engine_answering", return_value=True), \
                mock.patch.dict(core.RUNNERS, {"image": slow}), \
                mock.patch.object(core, "hold_status", return_value={"active": False, "message": ""}):
            r = client.post("/api/create", json=dict(IMAGE, count=4, seed=7), headers=HEADERS)
            time.sleep(0.2)
            release.set()
        self.assertEqual(r.status_code, 202)
        self.assertEqual(len(r.json()["others"]), 3)
        self.assertIn(7, seen)
        self.assertEqual(len(set(seen)), 4)
        for _ in range(100):
            if not core.GENERATION.active():
                break
            time.sleep(0.05)

    def test_helper_down_says_so(self):
        job = {"params": {"prompt": "a dog", "lane": "image"}}
        with self.assertRaises(core.FriendlyError) as e:
            core.run_enhance(job)
        self.assertIn("not running", str(e.exception))

    def test_every_lane_goes_through_the_queue(self):
        posted = []

        def fake_post(route, body, timeout):
            posted.append(body)
            return {"id": "20261109-000000-abc123", "state": "queued", "position": 1, "progress": {}}

        for runner, job, want in ((core.run_voice, {"params": {"text": "hello", "voice": "kokoro"}}, "mlx-audio"),
                                  (core.run_music, {"params": {"prompt": "x", "duration": 15, "seed": 3}}, "minimax-music"),
                                  (core.run_image, {"params": {"prompt": "x", "style": "none", "size": "square", "model": "schnell", "steps": 4, "seed": 3}}, "mflux")):
            view = {"state": "failed", "error": "No such file.", "progress": {}}
            with mock.patch.object(core, "backend_post", fake_post), mock.patch.object(core, "backend_get", return_value=view):
                with self.assertRaises(core.FriendlyError) as e:
                    runner(dict(job, id="x"))
            self.assertEqual(posted[-1]["adapter"], want)
            self.assertEqual(posted[-1]["wait_for_memory"], core.WAIT_FOR_MEMORY)
            self.assertIn("No such file.", str(e.exception))

    def test_page_has_no_dash_or_outside_links(self):
        here = Path(__file__).resolve().parent
        files = [here / "index.html"] + sorted((here / "ui").glob("*"))
        self.assertGreater(len(files), 5)
        for f in files:
            page = f.read_text()
            self.assertNotIn("\u2014", page, f.name)
            self.assertNotIn("https://", page, f.name)
            self.assertNotIn("http://", page.replace("http://www.w3.org", ""), f.name)


class EditLane(unittest.TestCase):
    def test_refuses_what_it_should(self):
        for body in ({"lane": "edit", "tool": "nope", "source": "good.png"},
                     {"lane": "edit", "tool": "cutout", "source": "../secret.png"},
                     {"lane": "edit", "tool": "cutout", "source": "escape.png"},
                     {"lane": "edit", "tool": "cutout", "source": "notes.txt"},
                     {"lane": "edit", "tool": "cutout", "source": "/etc/hosts"},
                     {"lane": "edit", "tool": "cutout"},
                     {"lane": "edit", "tool": "change", "source": "good.png", "prompt": "   "},
                     {"lane": "edit", "tool": "bigger", "source": "good.png", "scale": 9}):
            with self.subTest(body), self.assertRaises(core.Invalid):
                core.validate_create(body)

    def test_good_requests_become_a_path_inside_the_folder(self):
        lane, p, gb, _ = core.validate_create({"lane": "edit", "tool": "cutout", "source": "good.png"})
        self.assertEqual((lane, gb), ("edit", core.EDIT_TOOLS["cutout"]["gb"]))
        self.assertEqual(Path(p["source"]).parent, OUT.resolve())
        self.assertEqual(p["parent"], "good.png")
        _, p, _, _ = core.validate_create({"lane": "edit", "tool": "bigger", "source": "good.png", "scale": 3})
        self.assertEqual(p["scale"], 3)

    def test_no_go_starts_nothing(self):
        governor_says(NO_GO)
        r = client.post("/api/create", headers=HEADERS, json={"lane": "edit", "tool": "cutout", "source": "good.png"})
        self.assertEqual(r.status_code, 409)
        self.assertIsNone(core.GENERATION.running())


class VideoLane(unittest.TestCase):
    def setUp(self):
        patch = mock.patch.dict(core.VIDEO_MODELS, {k: dict(v, needs=[]) for k, v in core.VIDEO_MODELS.items()})
        patch.start(); self.addCleanup(patch.stop)

    def test_refuses_what_it_should(self):
        for body in ({"lane": "video", "prompt": "   "},
                     {"lane": "video", "prompt": "x", "seconds": 3},
                     {"lane": "video", "prompt": "x", "shape": "banner"},
                     {"lane": "video", "prompt": "x", "source": "../secret.png"},
                     {"lane": "video", "prompt": "x", "source": "escape.png"},
                     {"lane": "video", "prompt": "x", "source": "notes.txt"},
                     {"lane": "video", "prompt": "x", "source": "/etc/hosts"}):
            with self.subTest(body), self.assertRaises(core.Invalid):
                core.validate_create(body)

    def test_good_requests(self):
        lane, p, gb, _ = core.validate_create({"lane": "video", "prompt": "a cat", "seconds": 2, "seed": 9})
        self.assertEqual((lane, gb, p["duration"], p["size"], p["seed"]), ("video", core.VIDEO_MODELS[core.DEFAULT_VIDEO_MODEL]["gb"], 2, "landscape", 9))
        self.assertIsNone(p["source"])
        _, p, _, _ = core.validate_create({"lane": "video", "prompt": "a cat", "source": "good.png"})
        self.assertEqual(Path(p["source"]).parent, OUT.resolve())
        self.assertEqual(p["parent"], "good.png")

    def test_no_go_starts_nothing(self):
        governor_says(NO_GO)
        r = client.post("/api/create", headers=HEADERS, json={"lane": "video", "prompt": "a cat"})
        self.assertEqual(r.status_code, 409)
        self.assertIsNone(core.GENERATION.running())

    def test_video_file_is_named_and_kind_is_video(self):
        clip = OUT / "neovak_video_20261109_030000_7_jabc123.mp4"
        clip.write_bytes(b"not really")
        item = core.describe_name(clip.name, {})
        self.assertEqual((item["kind"], item["lane"]), ("video", "video"))
        self.assertEqual(item["thumb"], f"/thumb/{clip.name}")
        self.assertIsNotNone(core.safe_media_path(clip.name))
        self.assertEqual(client.get(f"/media/{clip.name}", headers={"Range": "bytes=0-3"}).status_code, 206)
        clip.unlink()

    def test_stop_with_nothing_running_is_refused(self):
        self.assertEqual(client.post("/api/job/nope/stop", headers=HEADERS, json={}).status_code, 409)


class AnimationAndTextLanes(unittest.TestCase):
    def test_animation_refuses_what_it_should(self):
        for body in ({"lane": "animation", "template": "title"},
                     {"lane": "animation", "template": "nope", "prompt": "x"},
                     {"lane": "animation", "prompt": "x", "seconds": 40},
                     {"lane": "animation", "prompt": "x", "look": "neon"},
                     {"lane": "animation", "template": "move"},
                     {"lane": "animation", "template": "move", "source": "../secret.png"},
                     {"lane": "animation", "prompt": "x", "source": "escape.png"},
                     {"lane": "animation", "prompt": "x", "source": "/etc/hosts"},
                     {"lane": "animation", "prompt": "x" * 700}):
            with self.subTest(body), self.assertRaises(core.Invalid):
                core.validate_create(body)

    def test_animation_good_request(self):
        lane, p, gb, _ = core.validate_create({"lane": "animation", "prompt": "Hello\nWorld", "look": "paper", "seconds": 3, "source": "good.png"})
        self.assertEqual((lane, gb, p["template"], p["look"], p["seconds"]), ("animation", 0, "title", "paper", 3.0))
        self.assertEqual(p["text"], "Hello\nWorld")
        self.assertEqual(Path(p["source"]).parent, OUT.resolve())
        params = core.animation_params(p)
        self.assertEqual(sorted(params), ["direction", "font", "look", "seconds", "shape", "source", "template", "text"])

    def test_text_needs_a_writer_the_governor_knows(self):
        lane, p, need, _ = core.validate_create({"lane": "text", "prompt": "a script", "model": "9b", "length": 30})
        self.assertEqual((lane, need, p["task"]), ("text", "9b", "script"))
        # the 27B is offered since it ran here (Nov 9 2026); the governor is still asked for it by name
        self.assertEqual(core.validate_create({"lane": "text", "prompt": "a script", "model": "27b"})[2], "27b")
        for body in ({"lane": "text", "prompt": ""}, {"lane": "text", "prompt": "x", "model": "gpt"}, {"lane": "text", "prompt": "x", "length": 45},
                     {"lane": "text", "prompt": "x", "task": "poem"}):
            with self.subTest(body), self.assertRaises(core.Invalid):
                core.validate_create(body)

    def test_text_files_are_listed_only_when_this_lane_wrote_them(self):
        ours = OUT / "neovak_text_20261109_040000_j123abc.txt"
        ours.write_text("A short script.")
        try:
            self.assertIsNotNone(core.safe_media_path(ours.name))
            self.assertIsNone(core.safe_media_path("notes.txt"))
            item = core.describe_name(ours.name, {})
            self.assertEqual((item["kind"], item["lane"]), ("text", "text"))
            self.assertIn("short script", item["excerpt"])
            self.assertEqual(client.get(f"/media/{ours.name}").status_code, 200)
            self.assertEqual(client.get("/media/notes.txt").status_code, 404)
            names = [i["name"] for i in core.gallery()["items"]]
            self.assertIn(ours.name, names)
            self.assertNotIn("notes.txt", names)
        finally:
            ours.unlink()

    def test_stopping_a_text_or_animation_job_is_offered(self):
        job = {"id": "x", "lane": "text", "state": "running", "params": {}, "started": 0, "finished": None, "estimate": 1, "result": None,
               "message": "", "backend_id": "b"}
        with mock.patch.dict(core.GENERATION.jobs, {"x": job}):
            self.assertTrue(core.GENERATION.view("x")["can_stop"])


class RecipesAndSidecars(unittest.TestCase):
    RECIPE = {"id": "two", "name": "Two", "builtin": True, "inputs": [{"name": "idea", "type": "text", "tier": "basic", "label": "Idea", "required": True}],
              "plan": {"estimate_seconds": 300, "memory_gb": 25, "steps": [{"id": "a", "label": "First", "memory_gb": 25, "estimate_seconds": 300}]}}

    def test_recipe_validated_against_the_engines_book(self):
        with mock.patch.object(core, "recipes", return_value=[self.RECIPE]):
            with self.assertRaises(core.Invalid):
                core.validate_create({"lane": "recipe", "recipe": "../etc", "values": {}})
            with self.assertRaises(core.Invalid):
                core.validate_create({"lane": "recipe", "recipe": "two", "values": "not a dict"})
            lane, params, gb, _ = core.validate_create({"lane": "recipe", "recipe": "two", "values": {"idea": "a boat"}})
        self.assertEqual((lane, params["recipe"], params["prompt"], gb), ("recipe", "two", "a boat", 25))
        self.assertEqual(core.estimate_for("recipe", params), 300)

    def test_run_recipe_follows_the_run_to_a_file(self):
        name = "neovak_video_20261109_045053_j9880b7.mp4"
        (OUT / name).write_bytes(b"movie")
        done = {"state": "done", "waiting": None, "estimate_seconds": 120, "result": {"name": name, "seed": 5},
                "steps": [{"id": "a", "label": "First", "state": "done", "output": {"file": str(OUT / name)}, "progress": {"stage": "done"}}]}
        job = {"id": "x", "params": {"recipe": "two", "values": {}, "prompt": "p"}, "estimate": 300}
        with mock.patch.object(core, "backend_post", return_value={"id": "r-20261109-000000-aaaaaa"}) as post, \
             mock.patch.object(core, "backend_get", return_value=done):
            result = core.run_recipe(job)
        self.assertEqual(post.call_args[0][0], "/api/recipes/two/run")
        self.assertEqual(job["steps"][0]["kind"], "video")
        self.assertEqual(job["steps"][0]["url"], f"/media/{name}")
        self.assertEqual(result["name"], name)
        self.assertEqual(result["seed"], 5)

    def test_run_recipe_failure_is_a_sentence(self):
        run = {"state": "failed", "waiting": None, "estimate_seconds": 1, "error": "Traceback (most recent call last)\n boom", "steps": [], "result": None}
        job = {"id": "x", "params": {"recipe": "two", "values": {}, "prompt": "p"}, "estimate": 1}
        with mock.patch.object(core, "backend_post", return_value={"id": "r-20261109-000000-aaaaaa"}), mock.patch.object(core, "backend_get", return_value=run):
            with self.assertRaises(core.FriendlyError) as e:
                core.run_recipe(job)
        self.assertNotIn("Traceback", str(e.exception))

    def test_stop_goes_to_the_run(self):
        core.GENERATION.jobs["stopme"] = {"state": "running", "backend_run": "r-20261109-000000-bbbbbb"}
        with mock.patch.object(core, "backend_post", return_value={}) as post:
            self.assertTrue(core.cancel_job("stopme"))
        self.assertEqual(post.call_args[0][0], "/api/recipe-runs/r-20261109-000000-bbbbbb/cancel")
        core.GENERATION.jobs.pop("stopme")

    def test_gallery_reads_the_sidecar(self):
        from neovak_queue import provenance
        name = "neovak_20261109_044612_424242.png"
        (OUT / name).write_bytes(b"\x89PNG not really")
        provenance.write(OUT / name, {"made": "2026-11-09T04:46:38-06:00", "prompt": "a boat", "seed": 424242, "model": "flux2-klein-4b", "model_name": "FLUX.2 klein 4B",
                                       "recipe": {"name": "Two", "step_label": "Make it", "step": "picture"}, "chain": [{"label": "Before", "file": "x.png"}],
                                       "remake": {"adapter": "mflux", "params": {"prompt": "a boat"}}})
        item = core.describe_name(name)
        self.assertEqual(item["prompt"], "a boat")
        self.assertEqual(item["seed"], 424242)
        self.assertEqual(item["how"]["recipe"], "Two")
        self.assertEqual(item["how"]["chain"][0]["name"], "x.png")
        self.assertTrue(item["how"]["can_remake"])

    def test_remake_refuses_names_and_files_without_a_record(self):
        for bad in ("../secret.png", "a/b.png", ""):
            with self.assertRaises(core.Invalid):
                core.validate_create({"lane": "remake", "name": bad})
        with self.assertRaises(core.Invalid):
            core.validate_create({"lane": "remake", "name": "good.png"})


class Studio(unittest.TestCase):
    def test_ui_files_only_from_the_folder_and_only_js_or_css(self):
        self.assertEqual(client.get("/ui/studio.css").status_code, 200)
        self.assertEqual(client.get("/ui/boot.js").status_code, 200)
        for bad in ("/ui/..%2Fapp.py", "/ui/%2e%2e%2Fcore.py", "/ui/nothing.js"):
            self.assertEqual(client.get(bad).status_code, 404, bad)

    def test_starters_and_derived_routes_refuse_traversal(self):
        for bad in ("/starters/..%2Fapp.py", "/lift/..%2Fsecret.png", "/peaks/..%2Fsecret.png", "/strip/..%2Fsecret.png"):
            self.assertEqual(client.get(bad).status_code, 404, bad)

    def test_upload_keeps_only_pixels_and_gives_its_own_name(self):
        from io import BytesIO

        from PIL import Image
        raw = BytesIO()
        Image.new("RGB", (32, 24), (10, 20, 30)).save(raw, "JPEG")
        before = set(os.listdir(OUT))
        r = client.post("/api/upload", content=raw.getvalue(), headers={"Content-Type": "image/jpeg"})
        self.assertEqual(r.status_code, 201)
        new = set(os.listdir(OUT)) - before
        self.assertEqual(len(new), 1)
        name = new.pop()
        self.assertTrue(name.startswith("neovak_upload_") and name.endswith(".png"))
        with Image.open(OUT / name) as im:
            self.assertEqual(im.size, (32, 24))
        (OUT / name).unlink()

    def test_upload_refuses_what_it_is_not(self):
        self.assertEqual(client.post("/api/upload", content=b"not a picture", headers={"Content-Type": "image/png"}).status_code, 400)
        self.assertEqual(client.post("/api/upload", content=b"x", headers={"Content-Type": "application/x-sh"}).status_code, 400)
        self.assertEqual(client.post("/api/upload", content=b"x", headers={"Content-Type": "image/png", "Origin": "http://evil.example"}).status_code, 400)

    def test_projects_hold_names_only(self):
        r = client.post("/api/projects", json={"name": "A test project"}, headers=HEADERS)
        self.assertEqual(r.status_code, 201)
        pid = r.json()["id"]
        self.assertEqual(client.post(f"/api/projects/{pid}", json={"add": "../secret.png"}, headers=HEADERS).status_code, 400)
        self.assertEqual(client.post(f"/api/projects/{pid}", json={"add": "good.png"}, headers=HEADERS).status_code, 200)
        names = core.gallery(names=screen.PROJECTS.items(pid))["items"]
        self.assertEqual([x["name"] for x in names], ["good.png"])
        self.assertEqual(client.request("DELETE", f"/api/projects/{pid}").status_code, 200)
        self.assertTrue((OUT / "good.png").exists())

    def test_timeline_is_checked(self):
        pid = screen.PROJECTS.listing()["active"]
        ok = {"clips": [{"name": "good.png", "seconds": 3}], "sounds": [], "shape": "square"}
        self.assertEqual(client.post(f"/api/projects/{pid}/timeline", json=ok, headers=HEADERS).status_code, 200)
        for bad in ({"clips": [{"name": "../secret.png", "seconds": 3}]}, {"clips": [{"name": "good.png", "seconds": -1}]},
                    {"clips": [{"name": "good.png", "seconds": "x"}]}, {"sounds": [{"name": "good.png", "seconds": 2}]}):
            self.assertEqual(client.post(f"/api/projects/{pid}/timeline", json=bad, headers=HEADERS).status_code, 400, bad)

    def test_film_needs_something_on_the_timeline(self):
        r = client.post("/api/create", json={"lane": "film", "timeline": {"clips": [], "sounds": []}}, headers=HEADERS)
        self.assertEqual(r.status_code, 400)
        self.assertIn("timeline", r.json()["error"])

    def test_install_only_what_is_offered(self):
        self.assertEqual(client.post("/api/models/install", json={"id": "../../etc"}, headers=HEADERS).status_code, 400)
        import studio
        for o in studio.OFFERS:
            self.assertLessEqual(o["gb_download"], 10)
            self.assertTrue(o["dest"].startswith(str(core.SETTINGS.added_dir) + "/"))
            self.assertIn(o["licence"], ("Apache 2.0", "MIT"))

    def test_runner_sends_no_token_and_rechecks_size_and_licence(self):
        text = (Path(__file__).resolve().parent / "install_runner.py").read_text()
        self.assertIn("token=False", text)
        self.assertIn("largest", text)
        self.assertIn("licences", text)


if __name__ == "__main__":
    unittest.main(verbosity=1)
