"""Repair round of Nov 9 evening: what the checks found, held in place by tests.
A writer's thinking that fills its room; the watched picture timed apart; settings that are refused; each person's
own project; whose job a job is; a job held at the memory check."""
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "people_screen"))  # the screen's modules import each other by their plain names
os.environ.setdefault("PS_STATE_DIR", tempfile.mkdtemp(prefix="neovak_r3_"))


class Writer(unittest.TestCase):
    def test_thinking_that_fills_the_room_is_asked_again(self):
        from neovak_queue.adapters.local_text import LocalText, THINK_CHARS_LMS
        self.assertTrue(LocalText.thought_filled({"finish": "length", "buffer": "<think>on and on"}))
        self.assertTrue(LocalText.thought_filled({"finish": "length", "buffer": ""}))
        self.assertFalse(LocalText.thought_filled({"finish": "length", "buffer": "<think>x</think>The keeper rowed"}))
        self.assertFalse(LocalText.thought_filled({"finish": "stop", "buffer": ""}))
        self.assertEqual(LocalText.thought_chars({"buffer": "<think>abcd</think>words", "thought_chars": 10}), 14)
        self.assertGreater(THINK_CHARS_LMS, 8000)


class Watched(unittest.TestCase):
    def test_a_watched_picture_is_timed_apart_and_slower(self):
        from neovak_queue.adapters import mflux_image as m
        a = m.MfluxImage.__new__(m.MfluxImage)
        a.config = {"sizes": {"landscape": (1152, 896)}}
        plain = {"model": "z-image-turbo", "steps": 9, "size": "landscape", "live": False}
        live = dict(plain, live=True)
        self.assertEqual(a.estimate_key(plain), a.warm_key(live))
        self.assertTrue(a.estimate_key(live).endswith(":live"))
        self.assertEqual(a.default_estimate(live, warm_seconds=90), round(90 * m.LIVE_SLOWER, 1))
        self.assertIsNone(a.default_estimate(live))


class SettingsRefused(unittest.TestCase):
    def test_a_named_file_that_is_missing_and_a_wildcard_address(self):
        from neovak_queue import settings
        d = tempfile.mkdtemp(prefix="neovak_r3s_")
        with mock.patch.dict(os.environ, {"NEOVAK_SETTINGS": os.path.join(d, "typo.toml")}):
            with self.assertRaises(settings.SettingsError):
                settings.load(fresh=True)
        wild = Path(d) / "wild.toml"
        wild.write_text('[hosts]\nscreen = ["0.0.0.0"]\n')
        with self.assertRaises(settings.SettingsError):
            settings.load(wild, fresh=True)
        settings.reset()


class People(unittest.TestCase):
    def test_each_person_keeps_their_own_project(self):
        import studio
        p = studio.Projects(Path(tempfile.mkdtemp(prefix="neovak_r3p_")) / "projects.json")
        first = p.listing()["active"]
        mine = p.create("Mine", person="a")["id"]
        self.assertEqual(p.listing("a")["active"], mine)
        self.assertEqual(p.listing("b")["active"], first)  # another person's choice does not move b
        p.add("x.png", person="b")
        self.assertIn("x.png", p.items(first))
        self.assertNotIn("x.png", p.items(mine))
        p.remove(mine)
        self.assertEqual(p.listing("a")["active"], first)

    def test_whose_job_and_held_for_memory(self):
        import core
        jobs = core.Jobs(limit=5)
        job = {"id": "j1", "lane": "recipe", "params": {"recipe": "r"}, "state": "running", "started": time.time(), "finished": None,
               "estimate": 60, "result": None, "message": "", "person": "a",
               "steps": [{"state": "waiting", "waiting": "memory to free up", "stage": None}]}
        jobs.jobs["j1"] = job
        with mock.patch.object(core, "recipes", return_value=[{"id": "r", "label": "A recipe"}]):
            mine, other = jobs.view("j1", viewer="a"), jobs.view("j1", viewer="b")
        self.assertTrue(mine["mine"]); self.assertFalse(mine["by_someone_else"])
        self.assertFalse(other["mine"]); self.assertTrue(other["by_someone_else"])
        self.assertTrue(mine["held"]); self.assertEqual(mine["recipe_label"], "A recipe")
        self.assertTrue(core.is_held({"state": "running", "stage": "waiting for memory"}))
        self.assertFalse(core.is_held({"state": "running", "stage": "generating"}))


if __name__ == "__main__":
    unittest.main()
