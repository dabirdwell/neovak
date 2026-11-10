"""Enhance and edit adapters: where a source may come from, and that a result is always new."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image

from neovak_queue.adapters.base import AdapterError
from neovak_queue.adapters.image_tools import (BackgroundCutout, KontextEdit, SeedvrUpscale,
                                               fit_megapixel)


class SourceRules(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="neovak_edit_")).resolve()
        self.out = self.dir / "out"
        self.out.mkdir()
        self.config = {"output_dir": str(self.out), "venv_bin": "/nowhere", "model_dir": "/nowhere"}
        self.pic = self.out / "a.png"
        Image.new("RGB", (640, 480), "red").save(self.pic)
        self.outside = self.dir / "b.png"
        Image.new("RGB", (64, 64), "red").save(self.outside)

    def test_source_inside_output_folder_is_accepted(self):
        p = KontextEdit(self.config).validate({"source": str(self.pic), "prompt": "x", "seed": 5})
        self.assertEqual(p["source"], str(self.pic))

    def test_refuses_outside_folder_traversal_link_and_non_pictures(self):
        tool = BackgroundCutout(self.config)
        escape = self.out / ".." / "b.png"
        link = self.out / "link.png"
        link.symlink_to(self.outside)
        text = self.out / "note.txt"
        text.write_text("x")
        fake = self.out / "fake.png"
        fake.write_text("not a picture")
        for bad in (str(self.outside), str(escape), str(link), str(text), str(fake), "a.png", "",
                    str(self.out / "missing.png")):
            with self.subTest(bad):
                with self.assertRaises(AdapterError):
                    tool.validate({"source": bad})

    def test_an_extra_allowed_folder_is_honoured(self):
        tool = BackgroundCutout(dict(self.config, source_dirs=[str(self.dir)]))
        self.assertEqual(tool.validate({"source": str(self.outside)})["source"], str(self.outside))

    def test_blank_instruction_is_refused(self):
        with self.assertRaises(AdapterError):
            KontextEdit(self.config).validate({"source": str(self.pic), "prompt": "   "})

    def test_too_large_a_result_is_refused(self):
        wide = self.out / "wide.png"
        Image.new("RGB", (2100, 900), "red").save(wide)
        with self.assertRaises(AdapterError):
            SeedvrUpscale(self.config).validate({"source": str(wide), "scale": 2})

    def test_output_names_never_repeat_and_are_never_the_source(self):
        tool = KontextEdit(self.config)
        params = tool.validate({"source": str(self.pic), "prompt": "x", "seed": 5})
        one = tool.plan({"id": "20261109-020000-aaaaaa", "params": params})["outputs"][0]
        two = tool.plan({"id": "20261109-020000-bbbbbb", "params": params})["outputs"][0]
        self.assertNotEqual(one, two)
        self.assertNotEqual(one, str(self.pic))
        self.assertTrue(one.startswith(str(self.out)))

    def test_size_keeps_the_shape_on_the_grid(self):
        w, h = fit_megapixel(1920, 1080)
        self.assertEqual((w % 16, h % 16), (0, 0))
        self.assertAlmostEqual(w / h, 1920 / 1080, delta=0.05)
        self.assertLess(abs(w * h - 1024 * 1024), 120000)


if __name__ == "__main__":
    unittest.main()
