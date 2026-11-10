"""Unit checks for the third repair round. The real runs are in STUDIO_PLAN.md."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from neovak_queue.adapters.base import Adapter, AdapterError, without_time_report  # noqa: E402
from neovak_queue.adapters.mflux_image import MfluxImage, size_following  # noqa: E402
from neovak_queue.adapters.mlx_speech import MlxSpeech  # noqa: E402
from neovak_queue.safe_text import ascii_json, scrub  # noqa: E402

TIME_REPORT = """
        0.04 real         0.01 user         0.01 sys
             12345  maximum resident set size
          29400000000  peak memory footprint
                  41  page reclaims
"""


class Text(unittest.TestCase):
    def test_half_an_emoji_goes_and_a_whole_one_stays(self):
        self.assertEqual(scrub("\ud83d hello \U0001F600"), " hello \U0001F600")
        self.assertEqual(scrub({"a\udfff": ["x\ud800", {"k": "\ud83d"}], "n": 3}), {"a": ["x", {"k": ""}], "n": 3})

    def test_a_response_cannot_be_crashed(self):
        self.assertEqual(ascii_json({"a": "\ud83d"}), b'{"a":"\\ud83d"}')

    def test_adapter_validate_scrubs_nested_params(self):
        class A(Adapter):
            params = {"text": {"type": "str"}, "items": {"type": "list", "default": []}}
        p = A().validate({"text": "\ud83d hi", "items": [{"file": "a\udc00"}]})
        self.assertEqual(p, {"text": " hi", "items": [{"file": "a"}]})


class Errors(unittest.TestCase):
    def test_the_real_error_survives_the_time_report(self):
        self.assertEqual(without_time_report("Traceback\nValueError: boom" + TIME_REPORT), "Traceback\nValueError: boom")

    def test_no_report_leaves_it_alone(self):
        self.assertEqual(without_time_report("just an error"), "just an error")


class StartingPicture(unittest.TestCase):
    def test_keeps_the_shape_of_the_source(self):
        self.assertEqual(size_following(1024, 1024, 1152, 896), (1024, 1024))
        w, h = size_following(1920, 1080, 1152, 896)
        self.assertAlmostEqual(w / h, 1920 / 1080, delta=0.03)
        self.assertEqual((w % 16, h % 16), (0, 0))

    def test_longest_side_is_limited(self):
        w, h = size_following(4000, 1000, 1344, 768)
        self.assertLessEqual(max(w, h), 1536)
        self.assertAlmostEqual(w / h, 4, delta=0.15)

    def test_a_starting_picture_asks_for_more_memory(self):
        a = MfluxImage({"output_dir": "/tmp", "sizes": {}, "styles": {}, "model_dir": "/tmp", "venv_bin": "/tmp"})
        self.assertEqual(a.memory_gb({"model": "flux2-klein-4b", "source": "/x.png"}), 36)
        self.assertEqual(a.memory_gb({"model": "flux2-klein-4b"}), 30)


class Speed(unittest.TestCase):
    def test_out_of_range_refused(self):
        a = MlxSpeech({"output_dir": "/tmp", "model_dir": "/tmp", "venv_bin": "/tmp"})
        for bad in (0.1, 3, float("nan")):
            with self.assertRaises(AdapterError):
                a.validate({"text": "hello", "speed": bad})


if __name__ == "__main__":
    unittest.main()
