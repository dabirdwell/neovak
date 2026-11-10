"""The Writing lane's choice of writer: the two officers and the models LM Studio lists, each with a figure that says
whether it was measured or estimated, the governor asked by model and context for an LM Studio load, no token limit,
thinking kept off for short tasks, and the screen's checks on the names it is sent. LM Studio itself is never
called here: its listing is stood in for."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from neovak_queue.adapters import local_text
from neovak_queue.adapters.base import AdapterError
from neovak_queue.queue import need_words, preflight_args

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "people_screen"))
import core  # noqa: E402

LISTING = {
    "small": {"key": "small", "name": "Small Writer", "publisher": "someone", "params": "4B", "arch": "qwen35", "quant": "Q4_K_M", "bits": 4,
              "bytes": 3_000_000_000, "format": "gguf", "loaded": False, "ttl_seconds": None, "context": None, "vision": False},
    "big": {"key": "big", "name": "Big Writer", "publisher": "", "params": "31B", "arch": "gemma4", "quant": "8bit", "bits": 8,
            "bytes": 33_000_000_000, "format": "mlx", "loaded": True, "ttl_seconds": 500, "context": 8192, "vision": True},
}


class Listing(unittest.TestCase):
    def test_draft_helpers_and_embeddings_are_not_writers(self):
        for m in ({"type": "embeddings", "key": "nomic"}, {"type": "llm", "key": "mtp", "display_name": "Mtp Gemma"},
                  {"type": "llm", "key": "x", "display_name": "Mtp Qwen3.8 27B"}, {"type": "llm", "key": "y", "architecture": "gemma4-assistant"},
                  {"type": "llm", "key": "bad name;rm -rf"}):
            with self.subTest(m):
                self.assertIsNone(local_text._lms_entry(m))

    def test_a_listed_model_is_reduced_to_plain_facts(self):
        e = local_text._lms_entry({"type": "llm", "key": "qwen/qwen3.5-9b", "display_name": "Qwen3.5 9B", "publisher": "qwen", "params_string": "9B",
                                   "architecture": "qwen35", "quantization": {"name": "Q4_K_M", "bits_per_weight": 4}, "size_bytes": 5_630_000_000,
                                   "format": "gguf", "loaded_instances": [{"remaining_ttl_seconds": 42, "config": {"context_length": 8192}}],
                                   "capabilities": {"vision": False}})
        self.assertEqual((e["key"], e["loaded"], e["ttl_seconds"], e["context"], e["bits"]), ("qwen/qwen3.5-9b", True, 42, 8192, 4))
        self.assertIn("4 bits per weight", local_text.describe_model(e))
        self.assertIn("15 minutes", local_text.describe_model(e))
        self.assertTrue(local_text.thinks_in_tags(e))
        self.assertFalse(local_text.thinks_in_tags(LISTING["big"]))


class Figures(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.tool = local_text.LocalText({"output_dir": self.dir.name, "state_dir": self.dir.name})
        self.listing = mock.patch.object(local_text, "lmstudio_models", return_value=LISTING)
        self.listing.start()

    def tearDown(self):
        self.listing.stop()
        self.dir.cleanup()

    def test_estimate_is_size_on_disk_plus_two_until_measured(self):
        rows = {m["model"]: m for m in self.tool.models()}
        self.assertEqual((rows["lms:small"]["gb"], rows["lms:small"]["gb_kind"]), (5.0, "estimate"))
        self.assertEqual((rows["9b"]["gb_kind"], rows["27b"]["gb_kind"]), ("estimate", "estimate"))
        self.tool.record_peak("lms:small", 4.42, "rewrite")
        rows = {m["model"]: m for m in self.tool.models()}
        self.assertEqual((rows["lms:small"]["gb"], rows["lms:small"]["gb_kind"]), (4.4, "measured"))
        self.tool.record_peak("lms:small", 3.0, "rewrite")  # a smaller later run never lowers a figure that really happened
        self.assertEqual(self.tool.figure("lms:small")[0], 4.4)
        self.assertTrue((Path(self.dir.name) / local_text.PEAKS_FILE).is_file())

    def test_the_governor_is_told_the_model_and_context(self):
        self.assertEqual(self.tool.memory_gb({"model": "9b"}), "9b")
        self.assertEqual(self.tool.memory_gb({"model": "lms:small"}), {"gb": 5.0, "lms": "small", "ctx": local_text.LMS_CTX})
        self.assertEqual(self.tool.memory_gb({"model": "lms:big"}), 0)  # already in memory: nothing new is pulled in
        self.assertEqual(preflight_args({"gb": 5.0, "lms": "small", "ctx": 8192}), ["5.0", "--model", "small", "--ctx", "8192"])
        self.assertEqual(preflight_args("27b"), ["27b"])
        self.assertEqual(preflight_args(30), ["30"])
        self.assertIn("small in LM Studio", need_words({"gb": 5.0, "lms": "small"}))
        self.assertEqual(core.governor_args({"gb": 5.0, "lms": "small", "ctx": 8192}), ["5.0", "--model", "small", "--ctx", "8192"])

    def test_only_a_listed_name_is_accepted(self):
        self.assertEqual(self.tool.validate({"brief": "x", "model": "lms:small"})["model"], "lms:small")
        for bad in ("lms:nope", "lms:../x", "lms:a b", "gpt", "lms:"):
            with self.subTest(bad), self.assertRaises(AdapterError):
                self.tool.validate({"brief": "x", "model": bad})
        with mock.patch.object(local_text, "lmstudio_models", return_value=None), self.assertRaises(AdapterError) as got:
            self.tool.validate({"brief": "x", "model": "lms:small"})
        self.assertIn("not running", str(got.exception))

    def test_short_tasks_do_not_think_and_nothing_sets_max_tokens(self):
        p = {"task": "rewrite", "brief": "a fox", "model": "lms:small", "length": 60, "tone": "plain", "target": "image", "about": ""}
        sent = []

        def fake_converse(spec, body, ctx, state):
            sent.append(body)
            state.update(buffer="plain words", finish="stop", done=True)

        class Ctx:
            cancel_requested = False

            def progress(self, **kw):
                pass

        with mock.patch.object(self.tool, "_converse", fake_converse):
            spec = {"label": "Small Writer", "url": local_text.LMS_URL, "first_seconds": 0}
            state = self.tool._reply(spec, "small", p, Ctx(), 9e9, False, LISTING["small"])
            self.assertEqual(state["buffer"], "plain words")
            body = sent[0]
            self.assertNotIn("max_tokens", body)
            self.assertEqual(body["chat_template_kwargs"], {"enable_thinking": False})
            self.assertEqual(body["messages"][-1], {"role": "assistant", "content": local_text.EMPTY_THOUGHT})  # a Qwen family model
            self.tool._reply(spec, "big", p, Ctx(), 9e9, False, LISTING["big"])
            self.assertNotEqual(sent[1]["messages"][-1]["role"], "assistant")  # a family that does not think in tags gets no prefix
            self.tool._reply(spec, "small", dict(p, task="script"), Ctx(), 9e9, True, LISTING["small"])
            self.assertNotIn("chat_template_kwargs", sent[2])  # a script may think
            self.assertTrue(all("max_tokens" not in b for b in sent))


ROWS = [{"model": "9b", "label": "Quick writer", "source": "officer", "gb": 10, "gb_kind": "estimate", "note": "", "loaded": None, "disk_gb": None},
        {"model": "27b", "label": "Careful writer", "source": "officer", "gb": 38, "gb_kind": "estimate", "note": "", "loaded": None, "disk_gb": None},
        {"model": "lms:small", "label": "Small Writer", "source": "lmstudio", "gb": 5.0, "gb_kind": "estimate", "note": "In LM Studio, a compact copy at 4 bits per weight from someone. Loads when asked and leaves memory 15 minutes after its last use.", "loaded": False, "disk_gb": 3.0},
        {"model": "lms:big", "label": "Big Writer", "source": "lmstudio", "gb": 35.0, "gb_kind": "estimate", "note": "In LM Studio.", "loaded": True, "disk_gb": 33.0},
        {"model": "lms:nosize", "label": "No Size", "source": "lmstudio", "gb": None, "gb_kind": None, "note": "", "loaded": False, "disk_gb": None}]


class Screen(unittest.TestCase):
    def setUp(self):
        self.p = mock.patch.object(core, "engine_writers", return_value=(ROWS, {"running": True, "count": 3}))
        self.p.start()

    def tearDown(self):
        self.p.stop()

    def test_the_screen_asks_the_governor_the_same_way(self):
        lane, p, need, _ = core.validate_create({"lane": "text", "prompt": "a script", "model": "lms:small"})
        self.assertEqual((lane, p["model"], need), ("text", "lms:small", {"gb": 5.0, "lms": "small", "ctx": core.LMS_CTX}))
        self.assertEqual(core.validate_create({"lane": "text", "prompt": "a script", "model": "lms:big"})[2], 0)
        for bad in ("lms:nosize", "lms:unknown", "lms:../x", "gpt"):
            with self.subTest(bad), self.assertRaises(core.Invalid):
                core.validate_create({"lane": "text", "prompt": "a script", "model": bad})
        with mock.patch.object(core, "engine_writers", return_value=(None, {"running": False, "count": 0})), self.assertRaises(core.Invalid) as got:
            core.validate_create({"lane": "text", "prompt": "a script", "model": "lms:small"})
        self.assertIn("did not answer", str(got.exception))

    def test_the_catalog_carries_the_kind_of_figure_and_a_short_note(self):
        rows, lmstudio = core.writer_catalog({"available_gb": 40.0, "safety_gb": 4.0}, lambda k, s, routed, reason="": {"id": k, "label": s["label"], "engine": "", "note": "", "gb": s["gb"], "badge": "green", "badge_text": "", "runnable": routed, "reason": reason, "seconds": None})
        by = {r["id"]: r for r in rows}
        self.assertEqual(lmstudio["count"], 3)
        self.assertEqual(by["lms:small"]["note"], "A smaller copy that uses less memory.")  # plain words: no bit counts, no account names
        self.assertTrue(by["lms:small"]["note_full"].startswith("In LM Studio"))
        self.assertEqual((by["lms:small"]["gb_kind"], by["lms:small"]["badge"], by["lms:small"]["runnable"]), ("estimate", "green", True))
        self.assertEqual((by["lms:big"]["badge"], by["lms:big"]["runnable"], by["lms:big"]["loaded"]), ("green", True, True))  # in memory: nothing to load
        self.assertFalse(by["lms:nosize"]["runnable"])
        self.assertEqual(core.writer_label("lms:small"), "Small Writer")
        self.assertEqual(core.engine_label("lms:small"), "Small Writer")

    def test_what_would_fit_instead(self):
        offers = core.alternatives("text", {"model": "27b"}, {"available_gb": 20.0, "safety_gb": 4.0})
        self.assertEqual([o["id"] for o in offers], ["9b", "lms:small", "lms:big"])  # the loaded one needs nothing new
        self.assertTrue(all(o["field"] == "writer" for o in offers))


if __name__ == "__main__":
    unittest.main()
