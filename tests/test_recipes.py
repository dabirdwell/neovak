"""Recipes, chained runs, and provenance sidecars, with stand-in engines. No models.
Run: venv/bin/python3 tests/test_recipes.py
"""
import json
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_settings_file  # noqa: E402,F401  the tests' own settings file, before any neovak_queue import

from neovak_queue import JobQueue, provenance                       # noqa: E402
from neovak_queue.adapters.base import Adapter, AdapterError        # noqa: E402
from neovak_queue.adapters.join_sound import JoinSound              # noqa: E402
from neovak_queue.recipes import RecipeBook, RecipeError, check_recipe, hold_reason, substitute, _clean_values  # noqa: E402

PY = sys.executable
FFMPEG = "/opt/homebrew/bin/ffmpeg"


class FakeAdapter(Adapter):
    name = "fake-image"
    lane = "image"
    params = {"prompt": {"type": "str"}, "seed": {"type": "int", "default": 7}, "model": {"type": "str", "default": "m1"},
              "source": {"type": "str", "default": None}}
    gb = 0

    def memory_gb(self, params):
        return self.gb

    def plan(self, job):
        return {"outputs": [str(Path(self.config["output_dir"]) / f"out_{job['id'][-6:]}.png")]}

    def run(self, job, ctx):
        r = ctx.spawn([PY, "-c", f"import time; time.sleep({self.config.get('delay', 0.05)})"])
        if ctx.cancel_requested:
            return None
        out = job["outputs"][0]
        Path(out).write_bytes(b"made from " + job["params"]["prompt"].encode())
        return {"files": [out], "path": out, "seed": job["params"]["seed"], "model": job["params"]["model"], "time_seconds": 0}


class FakeWriter(FakeAdapter):
    name = "fake-writer"
    lane = "text"

    def run(self, job, ctx):
        return {"text": "Written words about " + job["params"]["prompt"], "files": []}


def recipe(**over):
    base = {"schema": 1, "name": "Two steps", "inputs": [{"name": "idea", "label": "Idea", "type": "text", "required": True},
                                                          {"name": "seed", "label": "Seed", "type": "seed", "tier": "advanced"}],
            "steps": [{"id": "one", "label": "First", "adapter": "fake-image", "params": {"prompt": "{{idea}}", "seed": "{{seed}}"}},
                      {"id": "two", "label": "Second", "adapter": "fake-image",
                       "params": {"prompt": "again {{idea}}", "source": "{{steps.one.file}}", "seed": "{{steps.one.seed}}"}}]}
    base.update(over)
    return base


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="neovak_recipes_"))
        self.out = self.tmp / "out"
        self.out.mkdir()
        self.builtin = self.tmp / "builtin"
        self.builtin.mkdir()
        config = {"output_dir": str(self.out)}
        self.adapter = FakeAdapter(config)
        self.queue = JobQueue(self.tmp / "state", [self.adapter, FakeWriter(config)], governor=None, poll_seconds=0.05)
        self.now = [1000.0]
        self.book = RecipeBook(self.queue, self.builtin, start=False, clock=lambda: self.now[0], hold=lambda *a: None, memory_wait=100, memory_retry=10)

    def tearDown(self):
        self.queue.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def drive(self, run, until=("done", "failed", "cancelled"), timeout=20):
        end = time.time() + timeout
        while time.time() < end:
            self.book.tick()
            view = self.book.status(run["id"])
            if view["state"] in until:
                return view
            time.sleep(0.02)
        self.fail(f"run stuck: {self.book.status(run['id'])}")


class Format(Base):
    def test_good_recipe_passes(self):
        out = check_recipe(recipe(), self.queue.adapters)
        self.assertEqual(out["steps"][1]["params"]["source"], "{{steps.one.file}}")

    def test_refusals_are_plain(self):
        cases = [
            (recipe(name=""), "name"),
            (recipe(steps=[]), "between"),
            (recipe(steps=[{"id": "x", "adapter": "nope", "params": {}}]), "no engine"),
            (recipe(steps=[{"id": "x", "adapter": "fake-image", "params": {"nope": 1}}]), "no setting"),
            (recipe(steps=[{"id": "x", "adapter": "fake-image", "params": {"prompt": "{{missing}}"}}]), "inputs"),
            (recipe(steps=[{"id": "x", "adapter": "fake-image", "params": {"source": "{{steps.y.file}}"}}]), "has not happened"),
            (recipe(steps=[{"id": "x", "adapter": "fake-image", "params": {"prompt": {"a": 1}}}]), "single value"),
            (recipe(inputs=[{"name": "a b"}]), "short name"),
            (recipe(inputs=[{"name": "a", "tier": "wizard"}]), "tier"),
        ]
        for raw, word in cases:
            with self.assertRaises(RecipeError) as e:
                check_recipe(raw, self.queue.adapters)
            self.assertIn(word, str(e.exception))

    def test_text_ref_needs_a_writing_step(self):
        bad = recipe(steps=[{"id": "a", "adapter": "fake-image", "params": {"prompt": "x"}},
                            {"id": "b", "adapter": "fake-image", "params": {"prompt": "{{steps.a.text}}"}}])
        with self.assertRaises(RecipeError):
            check_recipe(bad, self.queue.adapters)

    def test_typed_words_are_not_read_as_references(self):
        out = substitute("say {{idea}}", {"idea": "{{steps.secret.file}} and {{other}}"}, {})
        self.assertEqual(out, "say {{steps.secret.file}} and {{other}}")

    def test_whole_reference_keeps_its_type(self):
        self.assertEqual(substitute("{{n}}", {"n": 5}, {}), 5)

    def test_seed_chosen_and_dash_stripped(self):
        r = check_recipe(recipe(), self.queue.adapters)
        vals = _clean_values(r, {"idea": "--flag-looking words"})
        self.assertEqual(vals["idea"], "flag-looking words")
        self.assertIsInstance(vals["seed"], int)

    def test_missing_required_and_unknown(self):
        r = check_recipe(recipe(), self.queue.adapters)
        with self.assertRaises(RecipeError):
            _clean_values(r, {})
        with self.assertRaises(RecipeError):
            _clean_values(r, {"idea": "x", "bogus": 1})

    def test_bad_recipe_id_never_makes_a_path(self):
        self.assertFalse(self.book.delete("../../etc"))
        with self.assertRaises(RecipeError):
            self.book.save(dict(recipe(), id="../escape"))


class SaveAndReuse(Base):
    def test_save_list_copy_delete(self):
        saved = self.book.save(recipe(name="My Chain"))
        self.assertEqual(saved["id"], "my-chain")
        self.assertIsNotNone(self.book.get("my-chain"))
        again = self.book.save(recipe(name="My Chain"))
        self.assertEqual(again["id"], "my-chain-2")
        copy = self.book.save_copy("my-chain", "Lighthouse version", {"idea": "a lighthouse"})
        self.assertEqual(copy["based_on"], "my-chain")
        self.assertEqual(next(i for i in copy["inputs"] if i["name"] == "idea")["default"], "a lighthouse")
        self.assertTrue(self.book.delete("my-chain-2"))
        self.assertIsNone(self.book.get("my-chain-2"))
        run = self.drive(self.book.start(copy["id"], {}))
        self.assertEqual(run["state"], "done")

    def test_builtin_cannot_be_replaced_or_deleted(self):
        (self.builtin / "shipped.json").write_text(json.dumps(recipe(name="Shipped")))
        self.assertTrue(self.book.get("shipped")["builtin"])
        with self.assertRaises(RecipeError):
            self.book.delete("shipped")
        mine = self.book.save(dict(recipe(name="Mine"), id="shipped"))
        self.assertNotEqual(mine["id"], "shipped")
        self.assertEqual(self.book.get("shipped")["name"], "Shipped")


class Runs(Base):
    def setUp(self):
        super().setUp()
        self.book.save(recipe(name="Two"))

    def test_chain_passes_outputs_on_and_writes_sidecars(self):
        run = self.drive(self.book.start("two", {"idea": "a boat", "seed": 123}))
        self.assertEqual(run["state"], "done")
        first, second = run["steps"]
        self.assertEqual(second["output"]["seed"], 123)
        names = run["result"]["files"]
        self.assertEqual(len(names), 2)
        side = provenance.read(self.out, names[1])
        self.assertEqual(side["prompt"], "again a boat")
        self.assertEqual(side["seed"], 123)
        self.assertEqual(side["model"], "m1")
        self.assertTrue(side["made"])
        self.assertEqual(side["recipe"]["name"], "Two")
        self.assertEqual(side["recipe"]["step"], "two")
        self.assertEqual(side["chain"][0]["file"], names[0])
        self.assertEqual(side["sources"][0]["file"], names[0])
        self.assertEqual(side["sources"][0]["sha256"], provenance.sha256(self.out / names[0]))
        self.assertNotIn(str(self.out), json.dumps(side))  # no paths from this machine

    def test_refused_at_the_start_when_a_step_is_invalid(self):
        self.book.save(recipe(name="Bad", steps=[{"id": "x", "adapter": "fake-image", "params": {"seed": "abc"}}]))
        with self.assertRaises(RecipeError):
            self.book.start("bad", {"idea": "z"})

    def test_step_failure_keeps_earlier_files(self):
        original = FakeAdapter.run

        def boom(adapter, job, ctx):
            if job["params"]["prompt"].startswith("again"):
                raise AdapterError("That went wrong")
            return original(adapter, job, ctx)
        FakeAdapter.run = boom
        try:
            run = self.drive(self.book.start("two", {"idea": "a"}))
        finally:
            FakeAdapter.run = original
        self.assertEqual(run["state"], "failed")
        self.assertIn("That went wrong", run["error"])
        self.assertEqual(run["steps"][0]["state"], "done")
        self.assertTrue(Path(run["steps"][0]["output"]["file"]).exists())
        self.assertEqual(run["steps"][1]["state"], "failed")

    def test_cancel_stops_the_step_and_later_steps(self):
        self.adapter.config["delay"] = 5
        run = self.book.start("two", {"idea": "a"})
        end = time.time() + 10
        while self.book.status(run["id"])["steps"][0]["state"] != "running" and time.time() < end:
            self.book.tick(); time.sleep(0.02)
        while (self.queue.status(self.book.status(run["id"])["steps"][0]["job"]).get("state") != "running") and time.time() < end:
            self.book.tick(); time.sleep(0.02)
        started = time.time()
        self.book.cancel(run["id"])
        done = self.drive(run)
        self.assertLess(time.time() - started, 4)
        self.assertEqual(done["state"], "cancelled")
        self.assertEqual(done["steps"][0]["state"], "cancelled")
        self.assertEqual(done["steps"][1]["state"], "not run")
        self.assertEqual(self.queue.status(done["steps"][0]["job"])["state"], "cancelled")

    def test_holds_during_nightly_job_then_continues(self):
        self.adapter.gb = 2
        gate = {"on": True}
        self.book.hold = lambda *a: "the nightly job" if gate["on"] else None
        self.queue.governor = None
        run = self.book.start("two", {"idea": "a"})
        for _ in range(5):
            self.book.tick(); time.sleep(0.02)
        view = self.book.status(run["id"])
        self.assertEqual(view["state"], "running")
        self.assertIn("nightly", view["waiting"])
        self.assertEqual(view["steps"][0]["state"], "waiting")
        self.assertIsNone(view["steps"][0]["job"])
        gate["on"] = False
        self.assertEqual(self.drive(run)["state"], "done")

    def test_no_go_waits_and_gives_up_after_the_limit(self):
        self.adapter.gb = 2
        gov = self.tmp / "gov.py"
        gov.write_text('print("VERDICT: NO-GO")\n')
        self.queue.governor = str(gov)
        run = self.book.start("two", {"idea": "a"})
        end = time.time() + 8
        while self.book.status(run["id"])["waiting"] is None and time.time() < end:
            self.book.tick(); time.sleep(0.02)
        view = self.book.status(run["id"])
        self.assertIn("memory", view["waiting"])
        gov.write_text('print("VERDICT: GO")\n')
        self.now[0] += 11  # past the retry time
        done = self.drive(run)
        self.assertEqual(done["state"], "done")
        self.assertEqual(done["steps"][0]["state"], "done")

    def test_no_go_past_the_hour_fails(self):
        self.adapter.gb = 2
        gov = self.tmp / "gov.py"
        gov.write_text('print("VERDICT: NO-GO")\n')
        self.queue.governor = str(gov)
        run = self.book.start("two", {"idea": "a"})
        end = time.time() + 15
        while time.time() < end:
            self.book.tick(); time.sleep(0.02)
            view = self.book.status(run["id"])
            if view["state"] == "failed":
                break
            if view["waiting"]:
                self.now[0] += 11
        self.assertEqual(view["state"], "failed")
        self.assertIn("memory", view["error"])

    def test_restart_picks_up_an_unfinished_run(self):
        run = self.book.start("two", {"idea": "a"})
        self.book.tick()
        fresh = RecipeBook(self.queue, self.builtin, start=False, hold=lambda *a: None)
        end = time.time() + 15
        while time.time() < end:
            fresh.tick()
            view = fresh.status(run["id"])
            if view["state"] == "done":
                break
            time.sleep(0.02)
        self.assertEqual(view["state"], "done")

    def test_writing_step_feeds_the_next_step(self):
        self.book.save(recipe(name="Words", steps=[{"id": "w", "adapter": "fake-writer", "params": {"prompt": "{{idea}}"}},
                                                    {"id": "pic", "adapter": "fake-image", "params": {"prompt": "{{steps.w.text}}"}}]))
        done = self.drive(self.book.start("words", {"idea": "tide"}))
        self.assertEqual(done["state"], "done")
        side = provenance.read(self.out, done["result"]["name"])
        self.assertEqual(side["prompt"], "Written words about tide")


class Remake(Base):
    def test_remake_from_sidecar_and_guard_changed_source(self):
        self.book.save(recipe(name="Two"))
        run = self.drive(self.book.start("two", {"idea": "a", "seed": 11}))
        name = run["result"]["name"]
        side = provenance.read(self.out, name)
        adapter, params = provenance.remake_request(side, self.out)
        self.assertEqual(adapter, "fake-image")
        self.assertEqual(params["seed"], 11)
        self.assertEqual(params["source"], str((self.out / run["result"]["files"][0]).resolve()))
        with open(self.out / run["result"]["files"][0], "ab") as f:
            f.write(b"changed")
        with self.assertRaises(ValueError):
            provenance.remake_request(side, self.out)

    def test_sidecar_read_refuses_paths(self):
        for bad in ("../x", "a/b", "", ".hidden", "x\x00y"):
            self.assertIsNone(provenance.read(self.out, bad))


class JoinSoundRules(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="neovak_join_"))
        self.adapter = JoinSound({"output_dir": str(self.tmp)})

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_hold_only_when_the_words_run_longer(self):
        cmd, total, hold = JoinSound.command("v", "a", "p", {"seconds": 2.0, "audio": False}, {"seconds": 5.0}, 0)
        self.assertAlmostEqual(hold, 3.6, places=2)
        self.assertIn("tpad", " ".join(cmd))
        self.assertIn("libx264", cmd)
        cmd, total, hold = JoinSound.command("v", "a", "p", {"seconds": 8.0, "audio": False}, {"seconds": 5.0}, 0)
        self.assertEqual(hold, 0)
        self.assertIn("copy", cmd)

    def test_files_outside_the_folder_are_refused(self):
        outside = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
        outside.close()
        with self.assertRaises(AdapterError):
            self.adapter.validate({"video": outside.name, "audio": outside.name})
        Path(outside.name).unlink()
        with self.assertRaises(AdapterError):
            self.adapter.validate({"video": "../x.mp4", "audio": "y.wav"})

    @unittest.skipUnless(Path(FFMPEG).exists(), "no ffmpeg")
    def test_really_joins(self):
        video, audio = self.tmp / "v.mp4", self.tmp / "a.wav"
        subprocess.run([FFMPEG, "-nostdin", "-y", "-f", "lavfi", "-i", "color=red:s=64x64:r=24:d=1", str(video)], capture_output=True, check=True)
        subprocess.run([FFMPEG, "-nostdin", "-y", "-f", "lavfi", "-i", "sine=f=440:d=2.5", str(audio)], capture_output=True, check=True)

        class Ctx:
            cancel_requested = False

            def progress(self, **k):
                pass

            def spawn(self, cmd, timeout=None):
                return subprocess.run(cmd, capture_output=True, text=True)
        out = self.adapter.run({"params": self.adapter.validate({"video": str(video), "audio": str(audio)}),
                                "outputs": [str(self.tmp / "joined.mp4")]}, Ctx())
        self.assertAlmostEqual(out["seconds"], 3.1, delta=0.2)
        self.assertAlmostEqual(out["held_last_frame_seconds"], 2.1, delta=0.1)
        self.assertEqual(sorted(p.name for p in self.tmp.iterdir() if p.name.startswith(".part")), [])


class NightlyHold(unittest.TestCase):
    C = ZoneInfo("America/Chicago")

    def at(self, h, m):
        return datetime(2026, 11, 9, h, m, tzinfo=self.C)

    def test_window(self):
        self.assertIsNotNone(hold_reason(0, self.at(21, 30)))
        self.assertIsNone(hold_reason(0, self.at(22, 15)))
        self.assertIsNone(hold_reason(0, self.at(20, 0)))

    def test_would_run_into_it(self):
        self.assertIsNotNone(hold_reason(600, self.at(21, 20)))
        self.assertIsNone(hold_reason(60, self.at(21, 20)))


if __name__ == "__main__":
    unittest.main(verbosity=1)
