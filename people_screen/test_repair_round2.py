#!/usr/bin/env python3
"""Repair round 2: the server side of the findings, with no model loaded and nothing outside a temporary folder.
Run: venv/bin/python3 people_screen/test_repair_round2.py
Shares its temporary screen with test_people_screen (it imports that module's setup)."""
import time
import unittest
from unittest import mock

import test_people_screen as base  # noqa: E402  sets the environment and signs the client in
from test_people_screen import HEADERS, OUT, client, core, governor_says, GO, screen  # noqa: E402


class LongNames(unittest.TestCase):
    """A name longer than the file system allows is a name that is not there: 404 or 400, never 500."""

    def test_file_routes(self):
        long = "a" * 3000 + ".png"
        for route in ("/media/", "/thumb/", "/lift/", "/peaks/", "/strip/", "/api/info/", "/api/item/", "/starters/"):
            with self.subTest(route):
                self.assertEqual(client.get(route + long).status_code, 404)
        self.assertEqual(client.get("/ui/" + "a" * 3000 + ".js").status_code, 404)

    def test_json_bodies(self):
        long = "a" * 3000 + ".png"
        self.assertEqual(client.post("/api/favorite", json={"name": long, "on": True}, headers=HEADERS).status_code, 400)
        self.assertEqual(client.post("/api/hide", json={"name": long, "on": True}, headers=HEADERS).status_code, 400)
        self.assertIsNone(core.safe_media_path(long))
        self.assertIsNone(core.safe_media_path("b/" + "a" * 300 + ".png"))
        self.assertTrue(core.too_long_name("a" * 256))
        self.assertFalse(core.too_long_name("a" * 255))


class StopBeforeTheEngineAnswers(unittest.TestCase):
    """Stop in the first moments, before the job has an engine id, is kept and acted on."""

    def test_stop_is_kept_and_the_job_never_reaches_the_engine(self):
        job = {"id": "j1", "state": "running", "lane": "animation", "params": {}, "estimate": 20, "started": time.time(), "finished": None, "result": None, "message": ""}
        with mock.patch.dict(core.GENERATION.jobs, {"j1": job}):
            self.assertTrue(core.cancel_job("j1"))
            self.assertTrue(job["stop_asked"])
            view_ok = core.GENERATION.view("j1")
            self.assertFalse(view_ok["can_stop"])
            self.assertEqual(view_ok["stage"], "Stopping")
            with mock.patch.object(core, "backend_post") as post, self.assertRaises(core.FriendlyError) as held:
                core._on_the_queue(job, "motion", {}, 60, "fallback", "the animation")
            post.assert_not_called()
            self.assertTrue(str(held.exception).startswith("Stopped"))

    def test_stop_during_the_submit_is_sent_on_to_the_engine(self):
        job = {"id": "j2", "state": "running", "lane": "animation", "params": {}}
        calls = []

        def post(route, body, timeout):
            calls.append(route)
            if route == "/api/jobs":
                job["stop_asked"] = True  # the press lands while the submit is in flight
                return {"id": "e9"}
            return {}
        with mock.patch.dict(core.GENERATION.jobs, {"j2": job}), mock.patch.object(core, "backend_post", side_effect=post), \
                mock.patch.object(core, "_follow", return_value={"state": "cancelled"}), self.assertRaises(core.FriendlyError):
            core._on_the_queue(job, "motion", {}, 60, "fallback", "the animation")
        self.assertEqual(calls, ["/api/jobs", "/api/jobs/e9/cancel"])

    def test_a_fresh_job_offers_stop_at_once(self):
        job = {"id": "j3", "state": "running", "lane": "image", "params": {}, "estimate": 20, "started": time.time(), "finished": None, "result": None, "message": ""}
        with mock.patch.dict(core.GENERATION.jobs, {"j3": job}):
            self.assertTrue(core.GENERATION.view("j3")["can_stop"])


class EstimateDoesNotFollowTheClock(unittest.TestCase):
    """Once the engine's own time has run out it reports elapsed plus nothing; the last real estimate is kept."""

    def test_follow_keeps_the_last_real_estimate(self):
        job = {"id": "j4", "backend_id": "e4", "estimate": 40.0, "params": {}, "lane": "edit"}
        views = iter([
            {"state": "running", "progress": {"estimate_seconds": 40.6, "eta_seconds": 30.0, "stage": "working"}},
            {"state": "running", "progress": {"estimate_seconds": 55.2, "eta_seconds": 0.0, "stage": "working"}},
            {"state": "done", "progress": {"estimate_seconds": 69.8, "eta_seconds": 0.0, "stage": "done"}, "result": {}},
        ])
        with mock.patch.object(core, "backend_get", side_effect=lambda *a, **k: next(views)), mock.patch.object(core.time, "sleep"):
            core._follow(job, "seedvr2", {}, 600, "the picture")
        self.assertEqual(job["estimate"], 40.6)


class TheHoldLetsAnimationsThrough(unittest.TestCase):
    """The nightly hold keeps models from loading. An animation loads none, so it is not held, and a voice is."""

    def test_animation_runs_and_voice_is_held(self):
        governor_says(GO)
        with mock.patch.object(core, "hold_status", return_value={"active": True, "message": "held"}), \
                mock.patch.object(core, "engine_answering", return_value=True), \
                mock.patch.object(core.GENERATION, "begin", return_value={"id": "x"}) as begin, \
                mock.patch.object(core.GENERATION, "view", return_value={"id": "x", "state": "running"}):
            r = client.post("/api/create", json={"lane": "animation", "template": "title", "prompt": "Held title", "seconds": 2}, headers=HEADERS)
            self.assertEqual(r.status_code, 202, r.text)
            begin.assert_called_once()
            r = client.post("/api/create", json={"lane": "voice", "prompt": "Held voice"}, headers=HEADERS)
            self.assertEqual(r.status_code, 423)


class JudgedMemory(unittest.TestCase):
    """The figure fits are judged against: the larger of the live reading and the last quiet one, and the live one
    alone once nothing has run for a while."""

    def setUp(self):
        screen._quiet.update(reading=None, at=0.0, saved_at=0.0)

    def test_live_reading_wins_when_larger_while_work_runs(self):
        screen._quiet.update(reading={"available_gb": 34.7, "safety_gb": 4.0}, at=time.time())
        fit = screen._judge({"available_gb": 40.6, "safety_gb": 4.0}, {"now": True, "recent": True, "idle_for": 0.0})
        self.assertEqual(fit["available_gb"], 40.6)
        self.assertFalse(fit.get("quiet"))

    def test_quiet_reading_wins_when_larger_while_work_runs(self):
        screen._quiet.update(reading={"available_gb": 44.0, "safety_gb": 4.0}, at=time.time())
        fit = screen._judge({"available_gb": 16.8, "safety_gb": 4.0}, {"now": True, "recent": True, "idle_for": 0.0})
        self.assertEqual((fit["available_gb"], fit["quiet"]), (44.0, True))

    def test_idle_replaces_the_stored_reading(self):
        screen._quiet.update(reading={"available_gb": 44.0, "safety_gb": 4.0}, at=time.time())
        with mock.patch.object(core.RECORDS, "set_backend"):
            fit = screen._judge({"available_gb": 30.0, "safety_gb": 4.0}, {"now": False, "recent": False, "idle_for": 120.0})
        self.assertEqual(fit["available_gb"], 30.0)
        self.assertEqual(screen._quiet["reading"]["available_gb"], 30.0)

    def test_just_finished_keeps_the_larger_and_raises_it(self):
        screen._quiet.update(reading={"available_gb": 34.7, "safety_gb": 4.0}, at=time.time())
        with mock.patch.object(core.RECORDS, "set_backend"):
            fit = screen._judge({"available_gb": 20.0, "safety_gb": 4.0}, {"now": False, "recent": True, "idle_for": 5.0})
            self.assertEqual((fit["available_gb"], fit["quiet"]), (34.7, True))
            fit = screen._judge({"available_gb": 40.7, "safety_gb": 4.0}, {"now": False, "recent": True, "idle_for": 20.0})
        self.assertEqual(fit["available_gb"], 40.7)
        self.assertEqual(screen._quiet["reading"]["available_gb"], 40.7)

    def test_a_stale_reading_is_not_used(self):
        screen._quiet.update(reading={"available_gb": 44.0, "safety_gb": 4.0}, at=time.time() - 8000)
        fit = screen._judge({"available_gb": 16.8, "safety_gb": 4.0}, {"now": True, "recent": True, "idle_for": 0.0})
        self.assertEqual(fit["available_gb"], 16.8)


class FrameHeaders(unittest.TestCase):
    def test_no_other_site_may_frame_the_screen(self):
        r = client.get("/")
        self.assertIn("frame-ancestors 'none'", r.headers["content-security-policy"])
        self.assertEqual(r.headers["x-frame-options"], "DENY")
        door = base.TestClient(screen.app, base_url="http://127.0.0.1:8102").get("/")  # the sign-in page too
        self.assertEqual(door.status_code, 401)
        self.assertIn("frame-ancestors 'none'", door.headers["content-security-policy"])
        self.assertEqual(door.headers["x-frame-options"], "DENY")


class Words(unittest.TestCase):
    def test_shorten_keeps_line_breaks(self):
        self.assertEqual(core.shorten("The  Keeper's Log\nA short   film", 140), "The Keeper's Log\nA short film")

    def test_recipe_took_is_the_whole_run(self):
        how = core.how_made({"made": "x", "seconds": 0.4, "recipe": {"name": "R", "step_label": "Join"}}, {"lane": "recipe", "elapsed": 275.0})
        self.assertEqual(how["seconds"], 275.0)
        how = core.how_made({"made": "x", "seconds": 24.0}, {"lane": "image"})
        self.assertEqual(how["seconds"], 24.0)


if __name__ == "__main__":
    unittest.main(verbosity=1)
