"""The animation and text adapters: rules, words, refusals. Loads no model."""
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_settings_file  # noqa: E402,F401  the tests' own settings file, before any neovak_queue import

from PIL import Image

from neovak_queue.adapters import local_text, motion_anim
from neovak_queue.adapters.base import AdapterError
from neovak_queue.adapters.local_text import LocalText, caption_lines, split_thinking, tidy
from neovak_queue.adapters.motion_anim import Canvas, MotionAnimation, clean_words, fit_type


class Motion(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="neovak_anim_test_")).resolve()
        self.out = self.dir / "out"
        self.out.mkdir()
        self.pic = self.out / "a.png"
        Image.new("RGB", (800, 600), "red").save(self.pic)
        self.outside = self.dir / "b.png"
        Image.new("RGB", (64, 64), "red").save(self.outside)
        self.tool = MotionAnimation({"output_dir": str(self.out), "venv_bin": "/nowhere", "model_dir": "/nowhere"})

    def test_good_title_and_defaults(self):
        p = self.tool.validate({"text": "Hello\nWorld"})
        self.assertEqual((p["template"], p["look"], p["shape"], p["seconds"], p["still"]), ("title", "night", "landscape", 5, False))
        self.assertEqual(self.tool.memory_gb({"still": True}), 0)

    def test_refuses(self):
        bad = [({"template": "title", "text": "  "}, "type the words"),
               ({"text": "x" * 700}, "too many words"),
               ({"text": "ok", "seconds": 1}, "2 to 20"),
               ({"template": "move"}, "choose a picture"),
               ({"template": "move", "source": str(self.outside)}, "may read"),
               ({"text": "ok", "source": "../a.png"}, "output folder"),
               ({"text": "ok", "source": "/etc/hosts"}, "may read"),
               ({"text": "hi \U0001F600 there"}, "no letter for"),
               ({"template": "lines", "text": "\n".join(str(i) for i in range(12)), "seconds": 20}, "at most eight"),
               ({"template": "lines", "text": "a\nb\nc\nd", "seconds": 3}, "too many lines")]
        for params, words in bad:
            with self.subTest(params):
                with self.assertRaises(AdapterError) as e:
                    self.tool.validate(params)
                self.assertIn(words, str(e.exception))
        with self.assertRaises(AdapterError):
            self.tool.validate({"text": "x", "look": "neon"})

    def test_a_person_cannot_set_a_path_or_font_in_the_words(self):
        with self.assertRaises(AdapterError):
            self.tool.validate({"text": "ok", "out": "/tmp/x.mp4"})
        with self.assertRaises(AdapterError):
            self.tool.validate({"text": "ok", "font": "/etc/passwd"})

    def test_long_words_shrink_to_fit_or_are_refused(self):
        size, lines, _ = fit_type("A title that is quite long and has to wrap over more than one line", "clean", 1400, 500, 148, smallest=40)
        self.assertLess(size, 148)
        self.assertGreater(len(lines), 1)
        with self.assertRaises(AdapterError):
            fit_type("x" * 400, "clean", 200, 100, 148, smallest=40)

    def test_words_are_cleaned(self):
        self.assertEqual(clean_words("  Hello\r\n  World \t ok\x00 "), "Hello\nWorld ok")

    def test_every_template_builds_a_timeline_the_engine_accepts(self):
        sys.path.insert(0, str(motion_anim.REPO / "plates"))
        import motion
        for template in ("title", "strip", "lines", "move"):
            with self.subTest(template), tempfile.TemporaryDirectory() as work:
                p = self.tool.validate({"template": template, "text": "One\nTwo", "source": str(self.pic)})
                canvas = Canvas(p["shape"], work)
                self.tool.prepare_picture(p, canvas, work)
                tl = self.tool.timeline(p, canvas, 5.0)
                motion.validate(tl)
                self.assertEqual((tl["width"], tl["height"], tl["fps"]), (1920, 1080, 24))

    def test_output_name_cannot_collide_and_preview_goes_aside(self):
        job = {"id": "20261109-040000-abc123", "params": {"still": False}}
        self.assertRegex(self.tool.plan(job)["outputs"][0], r"neovak_anim_[0-9_]+_jabc123\.mp4$")
        job["params"]["still"] = True
        self.assertIn("/_previews/preview_jabc123.png", self.tool.plan(job)["outputs"][0])


class Text(unittest.TestCase):
    def setUp(self):
        self.out = Path(tempfile.mkdtemp(prefix="neovak_text_test_")).resolve()
        self.tool = LocalText({"output_dir": str(self.out)})

    def test_validate_and_governor(self):
        p = self.tool.validate({"brief": "a script about rivers", "model": "27b"})
        self.assertEqual(self.tool.memory_gb(p), "27b")
        self.assertEqual(self.tool.memory_gb({}), "9b")
        with self.assertRaises(AdapterError):
            self.tool.validate({"brief": "   "})
        with self.assertRaises(AdapterError):
            self.tool.validate({"brief": "x", "length": 45})

    def test_no_request_sets_a_token_limit(self):
        for task, extra in (("script", {}), ("caption", {"about": "a boat"}), ("rewrite", {"target": "video"})):
            messages = self.tool.messages(self.tool.validate({"brief": "x", "task": task, **extra}))
            self.assertEqual([m["role"] for m in messages], ["system", "user"])
        source = Path(local_text.__file__).read_text()
        self.assertNotIn('"max_tokens"', source)

    def test_thinking_is_kept_out_of_the_words(self):
        self.assertEqual(split_thinking("<think>private</think>Hello"), ("Hello", False))
        self.assertEqual(split_thinking("<think>private and not closed"), ("", True))
        self.assertEqual(split_thinking("Hi <think>hm</think> there"), ("Hi  there", False))

    def test_tidy_and_captions(self):
        self.assertEqual(tidy('Script: "Words here."'), "Words here.")
        self.assertEqual(caption_lines('1. One\n- "Two"\n\n* Three'), ["One", "Two", "Three"])

    def test_rewrite_has_no_file_and_script_does(self):
        self.assertEqual(self.tool.plan({"id": "a-b-abc123", "params": {"task": "rewrite"}}), {})
        self.assertRegex(self.tool.plan({"id": "a-b-abc123", "params": {"task": "script"}})["outputs"][0], r"neovak_text_[0-9_]+_jabc123\.txt$")

    def test_nightly_hold(self):
        c = local_text.CENTRAL
        self.assertFalse(local_text.hold_active(datetime(2026, 11, 9, 21, 24, tzinfo=c)))
        self.assertTrue(local_text.hold_active(datetime(2026, 11, 9, 21, 25, tzinfo=c)))
        self.assertTrue(local_text.hold_active(datetime(2026, 11, 9, 22, 14, 59, tzinfo=c)))
        self.assertFalse(local_text.hold_active(datetime(2026, 11, 9, 22, 15, tzinfo=c)))
        with mock.patch.object(local_text, "hold_active", return_value=True):
            job = {"params": {"task": "script", "brief": "x", "model": "9b", "length": 30, "tone": "plain", "target": "image", "about": ""}, "outputs": []}
            with self.assertRaises(AdapterError) as e:
                self.tool.run(job, mock.Mock(cancel_requested=False))
            self.assertIn("paused", str(e.exception))


if __name__ == "__main__":
    unittest.main(verbosity=1)
