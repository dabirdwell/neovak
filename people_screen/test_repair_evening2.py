#!/usr/bin/env python3
"""Repair round 2 of the evening pass (Nov 9 2026, night): the screen's server side, with no model loaded.
The job list never carries a gap while a new job trims the store; the nightly pause says what can still be made; writing
by a model kept in LM Studio is named plainly; a recipe can always be lined up; the Models page and the lanes time a
model from one function.
Run: venv/bin/python3 people_screen/test_repair_evening2.py"""
import threading
import time
import unittest
from unittest import mock

import test_people_screen as base  # noqa: E402,F401  sets the environment and signs the client in
from test_people_screen import core  # noqa: E402


class JobListWhileTrimming(unittest.TestCase):
    """GENERATION.views() while begin() trims the oldest finished job: no None in the list, no 500."""

    def test_views_never_hold_a_gap(self):
        jobs = core.Jobs(limit=10_000)
        now = time.time()
        for i in range(40):  # a full store of finished work, as on the test screen
            jid = f"20200101-0000{i:02d}-aaaaaa"
            jobs.jobs[jid] = {"id": jid, "lane": "animation", "params": {"prompt": "x"}, "state": "done", "started": now - 1000 + i,
                              "finished": now - 999 + i, "estimate": 5, "result": {}, "message": "", "person": None}
        stop, bad = threading.Event(), []

        def starter():
            while not stop.is_set():
                jobs.begin("animation", {"prompt": "y"}, lambda job: {}, 5)

        t = threading.Thread(target=starter, daemon=True)
        t.start()
        try:
            for _ in range(400):
                try:
                    views = jobs.views()
                except RuntimeError as e:  # dictionary changed size during iteration
                    bad.append(repr(e)); break
                if any(v is None for v in views):
                    bad.append("None in views"); break
        finally:
            stop.set(); t.join(5)
        self.assertEqual(bad, [])


class NightlyPause(unittest.TestCase):
    def test_the_words_say_what_can_still_be_made(self):
        with mock.patch.object(core.SETTINGS, "hold_state", return_value="inside"):
            h = core.hold_status()
        self.assertTrue(h["active"])
        self.assertIn("Animations and films can still be made", h["message"])
        self.assertIn("Animations and films", h["short"])
        self.assertIn("Animations and films can still be made", h["band"])
        self.assertNotIn("Creating is paused", h["message"])
        self.assertNotIn("\u2014", h["message"] + h["short"])


class PlainMaker(unittest.TestCase):
    def test_writing_by_a_model_in_lm_studio_is_named_plainly(self):
        # Since Nov 10 2026 by the writer's own plain name, the name it was chosen by, never by the app that keeps it
        self.assertEqual(core.plain_maker("Qwen3.5 4B", "text"), "Qwen3.5 4B")
        self.assertEqual(core.plain_maker("Gemma 4 E2B", "text"), "Gemma 4 E2B")
        self.assertEqual(core.plain_maker("lms:gemma-4-e2b-it-qat", "text"), "Gemma 4 E2B")  # a writer LM Studio no longer lists
        self.assertNotIn("LM Studio", core.plain_maker("gemma-4-12b-it-qat", "text"))
        self.assertEqual(core.plain_maker("Quick writer", "text"), "Quick writer")
        self.assertEqual(core.plain_maker("Quick", "image"), "Quick")
        self.assertIsNone(core.plain_maker(None, "text"))


class RecipesWait(unittest.TestCase):
    def test_a_recipe_too_big_for_now_can_still_be_lined_up(self):
        book = [{"id": "big", "name": "Big", "builtin": True, "inputs": [], "plan": {"memory_gb": 60, "estimate_seconds": 300, "steps": []}},
                {"id": "mine", "name": "Mine", "builtin": False, "inputs": [], "plan": {"memory_gb": 1, "estimate_seconds": 30, "steps": []}}]
        with mock.patch.object(core, "recipes", return_value=list(reversed(book))):
            cat = core.catalog({"available_gb": 12.0, "safety_gb": 4})
        rows = cat["recipes"]
        self.assertEqual([r["id"] for r in rows], ["big", "mine"])  # the ones that come with NeoVak first
        big = rows[0]
        self.assertTrue(big["runnable"]); self.assertTrue(big["waits"])
        self.assertIn("waits for memory by itself", big["badge_text"])


class OneTimeFunction(unittest.TestCase):
    def test_models_page_times_come_from_the_estimate_function(self):
        import studio
        studio._usual.update(at=0.0, seconds={})
        with mock.patch.object(core, "engine_estimate", side_effect=lambda adapter, params: 123.0):
            usual = studio.usual_seconds()
        self.assertEqual(usual.get("flux2-klein-4b"), 123.0)
        self.assertEqual(usual.get("music"), 123.0)
        self.assertEqual(usual.get("ltx-2.5-q8"), 123.0)
        studio._usual.update(at=0.0, seconds={})

    def test_a_watched_picture_has_a_plain_figure_too(self):
        def fake(adapter, params):
            return 140.0 if params.get("live") else 100.0
        with mock.patch.object(core, "engine_estimate", side_effect=fake):
            out = core.estimate_options("image", {"model": "z-image-turbo", "live": True})
        self.assertEqual(out["options"]["z-image-turbo"], 140.0)
        self.assertEqual(out["plain"]["z-image-turbo"], 100.0)
        self.assertEqual(out["plain"]["flux2-klein-4b"], out["options"]["flux2-klein-4b"])  # a model that cannot be watched


if __name__ == "__main__":
    unittest.main()
