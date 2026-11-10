"""Repair round 1 of round 2: the time before a press comes from the engine's own history, a writer that must be
loaded first is timed apart from one in memory, and the words on the screen are plain."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
os.environ.setdefault("PS_STATE_DIR", tempfile.mkdtemp(prefix="neovak_r1_"))

from neovak_queue.adapters.base import Adapter  # noqa: E402
from neovak_queue.queue import JobQueue  # noqa: E402


class Sized(Adapter):
    name, lane = "sized", "test"
    params = {"n": {"type": "int", "default": 3}, "words": {"type": "str", "default": ""}}

    def __init__(self):
        super().__init__({})

    def estimate_key(self, params):
        return f"sized:{params['n']}"

    def default_estimate(self, params):
        return 10 * params["n"]

    def run(self, job, ctx):
        return {}


class ColdWarm(Adapter):
    name, lane = "coldwarm", "test"
    params = {"cold": {"type": "bool", "default": False}}

    def __init__(self):
        super().__init__({})

    def warm_key(self, params):
        return "coldwarm:warm"

    def estimate_key(self, params):
        return self.warm_key(params) + (":cold" if params.get("cold") else "")

    def default_estimate(self, params, warm_seconds=None):
        return (warm_seconds if warm_seconds is not None else 12) + (20 if params.get("cold") else 0)

    def run(self, job, ctx):
        return {}


class EngineEstimate(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="neovak_q_")
        self.q = JobQueue(self.dir, [Sized(), ColdWarm()], start_worker=False)

    def tearDown(self):
        self.q.stop()

    def test_the_figure_before_a_press_is_the_table_then_the_history_for_those_settings(self):
        self.assertEqual(self.q.estimate("sized", {"n": 2})["estimate_seconds"], 20)
        self.assertEqual(self.q.estimate("sized", {})["key"], "sized:3")  # the defaults validate() would fill
        self.q._record_history("sized:2", 7.0)
        self.q._record_history("sized:2", 9.0)
        view = self.q.estimate("sized", {"n": 2})
        self.assertEqual((view["estimate_seconds"], view["source"]), (8.0, "history"))
        self.assertEqual(self.q.estimate("sized", {"n": 5})["estimate_seconds"], 50)  # other settings keep the table

    def test_a_cold_start_is_timed_apart_and_borrows_the_warm_history_plus_the_load(self):
        self.q._record_history("coldwarm:warm", 3.0)
        self.assertEqual(self.q.estimate("coldwarm", {"cold": False})["estimate_seconds"], 3.0)
        cold = self.q.estimate("coldwarm", {"cold": True})
        self.assertEqual((cold["estimate_seconds"], cold["key"]), (23, "coldwarm:warm:cold"))
        self.q._record_history("coldwarm:warm:cold", 30.0)
        self.assertEqual(self.q.estimate("coldwarm", {"cold": True})["estimate_seconds"], 30.0)

    def test_a_setting_the_adapter_cannot_size_gives_no_figure_and_no_error(self):
        view = self.q.estimate("sized", {"n": "many"})
        self.assertIsNone(view["estimate_seconds"])
        self.assertEqual(view["source"], "none")


class PlainWords(unittest.TestCase):
    def test_lm_studio_names_become_a_family_and_a_size(self):
        from people_screen import core
        cases = {"Qwen Qwen3.5 4B": "Qwen3.5 4B", "Qwen3.5 9B (GGUF)": "Qwen3.5 9B", "Gemma 4 12B Instruct Qat": "Gemma 4 12B",
                 "Qwen3.5 9B The Defiant Fable Uncnr Heretic NEO MAX": "Qwen3.5 9B, a modified copy",
                 "Gemma 3 12B Instruct Norm Preserved Biprojected Abliterated": "Gemma 3 12B, a modified copy",
                 "Minicpm5 1B Agentic Tooluse (1.1B)": "Minicpm5 1B", "Dory (4.0B)": "Dory 4.0B"}
        for raw, plain in cases.items():
            self.assertEqual(core.plain_writer_label(raw), plain, raw)

    def test_the_note_loses_bit_counts_and_account_names(self):
        from people_screen import core
        self.assertEqual(core.plain_writer_note("In LM Studio, a copy at 8 bits per weight, close to the original from someone. Loads when asked and leaves memory 15 minutes after its last use."),
                         "A full copy, close to the original.")
        self.assertEqual(core.plain_writer_note("In LM Studio, a compact copy at 4 bits per weight from google. It can also look at pictures, which this lane does not use. Loads when asked and leaves memory 15 minutes after its last use."),
                         "A smaller copy that uses less memory.")

    def test_words_are_cut_at_a_word_with_three_dots(self):
        from people_screen import core
        self.assertEqual(core.shorten("read aloud on the stage, with a pause", 30), "read aloud on the stage, with...")
        self.assertEqual(core.shorten("short", 30), "short")

    def test_the_figures_before_a_press_follow_the_settings(self):
        from people_screen import core
        def engine(adapter, params):
            return {2: 110, 5: 260, 8: 400}[params["seconds"]] if adapter == "ltx-video" else 20 if adapter == "mflux" else None
        with mock.patch.object(core, "engine_estimate", side_effect=engine):
            v = core.estimate_options("video", {"seconds": 8, "model": "ltx-2.5-q8"})
            self.assertEqual(v["chosen"], 400)
            self.assertEqual(v["alt"], {"2": 110, "5": 260, "8": 400})
            i = core.estimate_options("image", {"model": "flux2-klein-4b", "count": 4})
            self.assertEqual((i["chosen"], i["count"]), (20, 4))


if __name__ == "__main__":
    unittest.main()
