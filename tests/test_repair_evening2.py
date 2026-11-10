"""Repair round 2 of the evening pass (Nov 9 2026, night): the engine side of the findings, with no model loaded.
A changed picture comes back at its source's size; a recipe's times follow the values chosen; the recipes that come
with NeoVak are listed before the ones people saved; a recipe step says what kind of work it is.
Run: venv/bin/python3 tests/test_repair_evening2.py
"""
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_settings_file  # noqa: E402,F401  the tests' own settings file, before any neovak_queue import

from neovak_queue import JobQueue  # noqa: E402
from neovak_queue.adapters.base import Adapter  # noqa: E402
from neovak_queue.adapters.image_tools import back_to_size, fit_megapixel  # noqa: E402
from neovak_queue.recipes import RecipeBook  # noqa: E402


class ChangedPictureSize(unittest.TestCase):
    def test_a_source_near_one_megapixel_on_the_grid_keeps_its_size(self):
        self.assertEqual(fit_megapixel(1152, 896), (1152, 896))
        self.assertEqual(fit_megapixel(1024, 1024), (1024, 1024))
        self.assertEqual(fit_megapixel(2304, 1792), (1152, 896))  # a large one is still brought down to the model's size

    def test_the_result_is_brought_back_to_the_source_size_with_its_records(self):
        from PIL import Image, PngImagePlugin
        d = Path(tempfile.mkdtemp(prefix="neovak_e2_"))
        try:
            p = d / "x.png"
            meta = PngImagePlugin.PngInfo(); meta.add_text("model", "dev-kontext")
            meta.add_itxt("XML:com.adobe.xmp", "<x:xmpmeta><rdf:Description model='FLUX.1-Kontext-dev'/></x:xmpmeta>")
            Image.new("RGB", (1168, 896), (200, 40, 40)).save(p, pnginfo=meta)
            self.assertTrue(back_to_size(p, 1152, 896))
            with Image.open(p) as im:
                self.assertEqual(im.size, (1152, 896))
                self.assertEqual(im.info.get("model"), "dev-kontext")
                self.assertIn("Kontext", str(im.info.get("XML:com.adobe.xmp")))  # the model record the engine checks is kept
            self.assertFalse(back_to_size(p, 1152, 896))  # already that size: nothing is done
        finally:
            shutil.rmtree(d, ignore_errors=True)


class Timed(Adapter):
    name = "timed"
    lane = "video"
    params = {"prompt": {"type": "str"}, "seconds": {"type": "int", "default": 5}}

    def memory_gb(self, params):
        return 25

    def default_estimate(self, params):
        return 20 + params["seconds"] * 50


def clip_recipe(name="Clip", order=None):
    r = {"schema": 1, "name": name,
         "inputs": [{"name": "idea", "label": "Idea", "type": "text", "required": True},
                    {"name": "len", "label": "Length", "type": "choice", "tier": "advanced", "default": 5,
                     "choices": [{"value": 2, "label": "2 seconds"}, {"value": 5, "label": "5 seconds"}]}],
         "steps": [{"id": "clip", "label": "Set it moving", "adapter": "timed", "params": {"prompt": "{{idea}}", "seconds": "{{len}}"}}]}
    if order is not None:
        r["order"] = order
    return r


class RecipePlans(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="neovak_e2r_"))
        (self.tmp / "out").mkdir()
        self.builtin = self.tmp / "builtin"; self.builtin.mkdir()
        self.queue = JobQueue(self.tmp / "state", [Timed({"output_dir": str(self.tmp / "out")})], governor=None, poll_seconds=0.05)
        self.book = RecipeBook(self.queue, self.builtin, start=False, hold=lambda *a: None)

    def tearDown(self):
        self.queue.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_the_plan_follows_the_length_chosen(self):
        saved = self.book.save(clip_recipe())
        recipe = self.book.get(saved["id"])
        self.assertEqual(self.book.describe(recipe)["plan"]["estimate_seconds"], 270)  # the default, 5 seconds
        self.assertEqual(self.book.plan_for(recipe, {"len": 2})["estimate_seconds"], 120)
        self.assertEqual(self.book.plan_for(recipe, {"len": "2"})["estimate_seconds"], 120)
        self.assertEqual(self.book.plan_for(recipe, {"len": 9})["estimate_seconds"], 270)  # refused at the press: the default stands
        self.assertEqual(self.book.plan_for(recipe, {"len": {"x": 1}})["estimate_seconds"], 270)
        self.assertEqual(self.book.plan_for(recipe, "nonsense")["estimate_seconds"], 270)
        self.assertEqual(self.book.plan_for(recipe, {})["steps"][0]["kind"], "video")

    def test_the_recipes_that_come_with_neovak_come_first(self):
        import json
        (self.builtin / "zz.json").write_text(json.dumps(dict(clip_recipe("Zz built in", order=90), id="zz-built-in")))
        self.book.save(clip_recipe("Aa saved by someone"))
        names = [r["name"] for r in self.book.list()]
        self.assertEqual(names[0], "Zz built in")


if __name__ == "__main__":
    unittest.main()
