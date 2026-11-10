"""Video adapter: engine rules, source rules, and what it tells the queue."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image

from neovak_queue.adapters import ltx_video
from neovak_queue.adapters.base import AdapterError
from neovak_queue.adapters.ltx_video import LtxVideo, frames_for


class Rules(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="neovak_video_")).resolve()
        self.out = self.dir / "out"
        self.out.mkdir()
        self.config = {"output_dir": str(self.out), "venv_bin": "/nowhere", "model_dir": "/nowhere"}
        self.pic = self.out / "a.png"
        Image.new("RGB", (1024, 1024), "red").save(self.pic)
        self.outside = self.dir / "b.png"
        Image.new("RGB", (64, 64), "red").save(self.outside)
        # Passes without weights on the machine running the tests.
        patch = mock.patch.dict(ltx_video.VIDEO_MODELS,
                                {k: dict(v, pack=self.dir) for k, v in ltx_video.VIDEO_MODELS.items()})
        patch.start(); self.addCleanup(patch.stop)
        ltx_patch = mock.patch.object(ltx_video, "LTX", self.pic)
        ltx_patch.start(); self.addCleanup(ltx_patch.stop)
        self.tool = LtxVideo(self.config)

    def test_frames_are_eight_k_plus_one(self):
        for seconds in (1, 2, 3.3, 5, 8, 10):
            n = frames_for(seconds)
            self.assertEqual((n - 1) % 8, 0, seconds)
        self.assertEqual(frames_for(5), 121)
        self.assertEqual(frames_for(2), 49)

    def test_text_only_defaults(self):
        p = self.tool.validate({"prompt": "  a cat  ", "seed": 5})
        self.assertEqual(p["prompt"], "a cat")
        self.assertIsNone(p["source"])
        self.assertEqual(self.tool.shape(p), (960, 576, 121))
        self.assertEqual(p["seed"], 5)

    def test_picture_sets_the_shape_on_the_64_grid(self):
        p = self.tool.validate({"prompt": "x", "source": str(self.pic), "seed": 1, "seconds": 2})
        w, h, f = self.tool.shape(p)
        self.assertEqual((w % 64, h % 64), (0, 0))
        self.assertEqual(w, h)
        self.assertEqual(f, 49)

    def test_refuses_outside_folder_link_and_non_pictures(self):
        link = self.out / "link.png"
        link.symlink_to(self.outside)
        fake = self.out / "fake.png"
        fake.write_text("not a picture")
        for bad in (str(self.outside), str(self.out / ".." / "b.png"), str(link), str(fake), "a.png"):
            with self.assertRaises(AdapterError):
                self.tool.validate({"prompt": "x", "source": bad})

    def test_refuses_nonsense(self):
        for bad in ({"prompt": ""}, {"prompt": "x", "seconds": 0}, {"prompt": "x", "seconds": 11},
                    {"prompt": "x", "strength": 0}, {"prompt": "x", "size": "banner"},
                    {"prompt": "x", "model": "wan"}):
            with self.assertRaises(AdapterError, msg=str(bad)):
                self.tool.validate(bad)

    def test_memory_and_estimate_come_from_measurements(self):
        p = self.tool.validate({"prompt": "x"})
        self.assertGreaterEqual(self.tool.memory_gb(p), 16)
        self.assertGreater(self.tool.default_estimate(p), 100)
        short = self.tool.validate({"prompt": "x", "seconds": 2})
        self.assertLess(self.tool.default_estimate(short), self.tool.default_estimate(p))

    def test_progress_covers_both_passes_and_never_claims_the_pass_eta(self):
        first = self.tool.parse_progress("Denoising:  38%| 3/8 [00:27<00:44,  8.97s/it]")
        self.assertEqual(first, {"step": 3, "total": 11, "stage": "first pass"})
        final = self.tool.parse_progress("Denoising:  33%| 1/3 [00:40<01:20, 40.46s/it]")
        self.assertEqual(final, {"step": 9, "total": 11, "stage": "final pass"})
        self.assertNotIn("eta_seconds", final)

    def test_output_is_new_and_mp4(self):
        job = {"id": "abc123def456", "params": {"seed": 7}}
        out = Path(self.tool.plan(job)["outputs"][0])
        self.assertEqual(out.suffix, ".mp4")
        self.assertTrue(out.name.startswith("neovak_video_"))
        self.assertIn("_jdef456", out.name)


if __name__ == "__main__":
    unittest.main()
