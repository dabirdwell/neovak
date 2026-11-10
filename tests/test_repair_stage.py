#!/usr/bin/env python3
"""The repair stage's findings, as tests. No models, temporary folders only.
run: venv/bin/python3 tests/test_repair_stage.py
"""
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(REPO), str(REPO / "people_screen")]
TMP = Path(tempfile.mkdtemp(prefix="neovak_repair_test_"))
(TMP / "out").mkdir()
os.environ.update(PS_STATE_DIR=str(TMP / "ps"), PS_OUTPUT_DIR=str(TMP / "out"), PS_BACKEND="http://127.0.0.1:9", PS_GOVERNOR=str(TMP / "gov.py"),
                  NEOVAK_EXTRA_HOSTS="testserver")

from neovak_queue.queue import JobQueue, LineFull, MAX_LINE  # noqa: E402
from neovak_queue.adapters.base import Adapter  # noqa: E402
from neovak_queue.adapters.mlx_speech import speakable  # noqa: E402

import core  # noqa: E402
import app as screen  # noqa: E402
import studio  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402

client = TestClient(screen.app, base_url="http://127.0.0.1:8103", raise_server_exceptions=False)
client.cookies.set(screen.auth.COOKIE, screen.SESSIONS.create(screen.PEOPLE.add("Repair tester")[0]))  # every route needs a session
JSON = {"Content-Type": "application/json"}


class Stand(Adapter):
    name, lane = "stand", "image"
    params = {"x": {"type": "str", "default": ""}}
    ran = []

    def memory_gb(self, params):
        return 30

    def run(self, job, ctx):
        Stand.ran.append((job["id"], time.time()))
        return {"files": []}


def queue(sub, **kw):
    return JobQueue(TMP / sub, [Stand()], **kw)


class QueueRules(unittest.TestCase):
    def setUp(self):
        Stand.ran.clear()

    def wait(self, q, jid, want, seconds=10):
        end = time.time() + seconds
        while time.time() < end:
            v = q.status(jid)
            if v["state"] in want or v["progress"].get("stage") in want:
                return v
            time.sleep(0.02)
        self.fail(f"never reached {want}: {q.status(jid)}")

    def test_window_opening_during_a_memory_wait_stops_the_load(self):
        window, ok = threading.Event(), threading.Event()
        q = queue("h1", governor="/x", memory_retry_seconds=0.05, hold=lambda est=0: "the nightly job" if window.is_set() else None, poll_seconds=0.02)
        self.addCleanup(q.stop)
        q._preflight = lambda gb: (ok.is_set(), "VERDICT")
        jid = q.submit("stand", {}, context={"wait_for_memory": 60})["id"]
        self.wait(q, jid, ("waiting for memory",))
        window.set()
        ok.set()  # the governor now says yes, inside the window
        self.wait(q, jid, ("waiting for the nightly job",))
        time.sleep(0.4)
        self.assertEqual(Stand.ran, [], "a model loaded inside the window")
        window.clear()
        self.assertEqual(q.wait(jid, 5)["state"], "done")
        self.assertEqual(len(Stand.ran), 1)

    def test_window_opening_while_the_governor_answers_does_not_count(self):
        window = threading.Event()
        q = queue("h2", governor="/x", memory_retry_seconds=0.05, hold=lambda est=0: "the nightly job" if window.is_set() else None, poll_seconds=0.02)
        self.addCleanup(q.stop)

        def answer(gb):
            window.set()  # the window opens during the answer, and the answer is yes
            return True, "VERDICT: GO"
        q._preflight = answer
        jid = q.submit("stand", {})["id"]
        self.wait(q, jid, ("waiting for the nightly job",))
        self.assertEqual(Stand.ran, [])

    def test_missing_governor_runs_nothing(self):
        q = queue("g1", governor=str(TMP / "not-there.py"), memory_retry_seconds=0.05, poll_seconds=0.02)
        self.addCleanup(q.stop)
        v = q.wait(q.submit("stand", {}, context={"wait_for_memory": 60})["id"], 5)
        self.assertEqual(v["state"], "failed")
        self.assertIn("memory check could not be found", v["error"])
        self.assertEqual(Stand.ran, [])

    def test_stop_while_waiting_for_memory_is_quick(self):
        q = queue("c1", governor="/x", memory_retry_seconds=20, poll_seconds=0.02)
        self.addCleanup(q.stop)
        q._preflight = lambda gb: (False, "VERDICT: NO-GO")
        jid = q.submit("stand", {}, context={"wait_for_memory": 3600})["id"]
        self.wait(q, jid, ("waiting for memory",))
        at = time.time()
        q.cancel(jid)
        self.assertEqual(q.wait(jid, 10)["state"], "cancelled")
        self.assertLess(time.time() - at, 2)
        self.assertEqual(Stand.ran, [])

    def test_line_has_an_end_but_a_recipe_step_is_not_turned_away(self):
        q = queue("l1", start_worker=False)
        self.addCleanup(q.stop)
        for _ in range(MAX_LINE):
            q.submit("stand", {})
        with self.assertRaises(LineFull):
            q.submit("stand", {})
        q.submit("stand", {}, context={"recipe": {"run": "r-1"}})


class ScreenInput(unittest.TestCase):
    def test_wrong_shapes_get_a_sentence_and_start_nothing(self):
        before = len(core.GENERATION.jobs)
        for body in ({"lane": "image", "prompt": 123}, {"lane": ["image"], "prompt": "x"}, {"lane": "image", "prompt": "x", "model": {"a": 1}},
                     {"lane": "image", "prompt": "x", "size": []}, {"lane": "image", "prompt": "x", "style": [1]},
                     {"lane": "text", "prompt": "x", "task": []}, {"lane": "edit", "tool": ["x"]},
                     {"lane": "voice", "prompt": "x", "voice": {}}, {"lane": "animation", "prompt": 1}):
            r = client.post("/api/create", json=body, headers=JSON)
            self.assertEqual(r.status_code, 400, body)
            self.assertTrue(r.json().get("error"), body)
        raw = client.post("/api/create", content='{"lane":"image","prompt":"x","steps":Infinity}', headers=JSON)
        self.assertEqual(raw.status_code, 400)
        self.assertEqual(len(core.GENERATION.jobs), before)

    def test_upload_without_a_length_is_counted_as_it_comes(self):
        def body():
            for _ in range(40):
                yield b"x" * 1024
        with mock.patch.object(studio, "MAX_UPLOAD", 4096):
            r = client.post("/api/upload", content=body(), headers={"Content-Type": "image/png"})
        self.assertEqual(r.status_code, 413)


class Restarts(unittest.TestCase):
    def test_a_running_job_is_followed_after_a_restart_and_not_sent_twice(self):
        store = TMP / "jobs_a.json"
        first = core.Jobs(limit=4, store=store)
        job = {"id": "x1", "lane": "image", "params": {"prompt": "p"}, "state": "running", "started": time.time(), "finished": None,
               "estimate": 5, "result": None, "message": "", "backend_id": "b1"}
        first.jobs["x1"] = job
        job2 = dict(job, id="x2")
        job2.pop("backend_id")
        first.jobs["x2"] = job2
        first.save()
        second = core.Jobs(limit=4, store=store)
        seen = []

        def runner(j):
            seen.append(j["backend_id"])
            return {"name": None}
        second.resume({"image": runner})
        end = time.time() + 3
        while time.time() < end and second.jobs["x1"]["state"] == "running":
            time.sleep(0.02)
        self.assertEqual(seen, ["b1"])
        self.assertEqual(second.jobs["x1"]["state"], "done")
        self.assertEqual(second.jobs["x2"]["state"], "failed")
        self.assertIn("restarted", second.jobs["x2"]["message"])
        self.assertEqual(json.loads(store.read_text())["x1"]["state"], "done")

    def test_engine_gap_is_waited_out(self):
        answers = [OSError("refused"), OSError("refused"), {"state": "done", "attempts": 2, "progress": {}, "result": {"path": ""}}]

        def fake(route, timeout=4.0):
            a = answers.pop(0)
            if isinstance(a, Exception):
                raise a
            return a
        job = {"backend_id": "b"}
        with mock.patch.object(core, "backend_get", fake), mock.patch.object(core.time, "sleep"):
            view = core._follow(job, None, {}, 3600, "the picture")
        self.assertEqual(view["state"], "done")

    def test_recipe_steps_are_not_listed_as_someone_elses_work(self):
        core.GENERATION.jobs["r1"] = {"id": "r1", "lane": "recipe", "params": {"prompt": "p"}, "state": "running", "started": time.time(), "finished": None,
                                      "estimate": 5, "result": None, "message": "", "backend_run": "run-1"}
        self.addCleanup(core.GENERATION.jobs.pop, "r1")
        listing = {"jobs": [{"id": "s", "state": "queued", "lane": "text", "client": "recipe", "progress": {}, "context": {"recipe": {"run": "run-1"}}},
                            {"id": "o", "state": "queued", "lane": "image", "client": "rest", "progress": {"stage": "queued"}, "context": {}}]}
        with mock.patch.object(core, "backend_get", lambda r, t=4.0: listing):
            view = screen._queue_view()
        self.assertEqual([o["id"] for o in view["others"]], ["o"])
        self.assertEqual(view["others"][0]["stage"], "Waiting for its turn")


class PlainWords(unittest.TestCase):
    def test_engine_names_do_not_reach_a_person(self):
        for raw, want in (("apple-vision", "Remove the background"), ("SeedVR2_comfyUI", "Make it bigger"), ("FLUX.1-Kontext-dev", "Change something"),
                          ("something unknown", None), ("Tongyi-MAI/Z-Image", "Careful"), ("z-image-turbo", "Polished")):
            self.assertEqual(core.engine_label(raw), want)
        self.assertEqual(core.plain_words("Make it bigger: neovak_20261109_070124_101.png"), "Make it bigger")
        self.assertEqual(core.caption_for(None, "image", "neovak_upload_x.png"), "A picture added from this computer")
        self.assertEqual(core.plain_stage("waiting for memory"), "Waiting for memory to free up")

    def test_private_looks_are_not_offered(self):
        with mock.patch.object(core.RECORDS, "backend", lambda k: {"presets": {"styles": {"inference": "x", "cinematic": "y", "oklahoma": "z"}}}.get(k)):
            labels = [s["label"] for s in core.catalog({"available_gb": 60, "safety_gb": 4})["styles"]]
        self.assertEqual(labels, ["None", "Film still"])

    def test_speakable_drops_emoji(self):
        self.assertEqual(speakable("Hello there \U0001F600\U0001F3FD ok ❤️"), "Hello there ok")
        self.assertEqual(speakable("\U0001F600"), "")


if __name__ == "__main__":
    unittest.main(verbosity=1)
