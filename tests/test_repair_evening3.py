"""Repair round 3 of the evening pass (Nov 10 2026): the engine side of the findings, with no model loaded.
The time left while a model loads never counts down steps that have not begun; promises follow recent runs; a job held
for the nightly window goes back to the line so work that loads no model runs past it; a writer measured at one length
or state sizes the others.
Run: venv/bin/python3 tests/test_repair_evening3.py
"""
import shutil
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_settings_file  # noqa: E402,F401  the tests' own settings file, before any neovak_queue import

from neovak_queue import JobQueue  # noqa: E402
from neovak_queue.queue import lean_late  # noqa: E402
from neovak_queue.adapters.base import Adapter  # noqa: E402


class LeanLate(unittest.TestCase):
    def test_the_promise_follows_two_slower_runs_but_not_one(self):
        self.assertIsNone(lean_late([]))
        self.assertEqual(lean_late([22.3, 22.4, 22.1, 26.5, 22.7, 22.7]), 22.7)  # steady runs: their middle
        self.assertEqual(lean_late([37.9, 37.6, 49.0, 55.1]), 49.0)  # Fast draft, Nov 9: two slow runs move it at once
        self.assertEqual(lean_late([37.9, 37.6, 37.8, 37.7, 80.0]), 37.8)  # one slow run alone does not
        self.assertEqual(lean_late([None, "x", True, 10.0]), 10.0)


class Stepped(Adapter):
    """Loads for `load` seconds, then reports `steps` steps of `step` seconds each, like mflux does."""
    name = "stepped"
    lane = "image"
    params = {"prompt": {"type": "str"}, "load": {"type": "float", "default": 0.4}, "step": {"type": "float", "default": 0.2},
              "steps": {"type": "int", "default": 4}, "gb": {"type": "int", "default": 0}}

    def memory_gb(self, params):
        return params.get("gb", 0)

    def estimate_key(self, params):
        return "stepped"

    def run(self, job, ctx):
        p = job["params"]
        ctx.progress(stage="loading model", total=p["steps"])
        time.sleep(p["load"])
        for i in range(p["steps"] + 1):
            ctx.progress(step=i, total=p["steps"], stage="generating")
            time.sleep(p["step"])
            ctx.queue._last_write.pop(ctx.job_id, None)  # every step is written, whatever the throttle
        return {"files": []}


class Free(Adapter):
    """Loads no model, like an animation."""
    name = "free"
    lane = "animation"
    params = {"text": {"type": "str"}}

    def run(self, job, ctx):
        return {"files": []}


class Phases(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="neovak_e3_"))
        self.queue = JobQueue(self.tmp / "state", [Stepped(), Free()], governor=None, poll_seconds=0.05)

    def tearDown(self):
        self.queue.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _watch(self, jid, until):
        seen = []
        end = time.time() + until
        while time.time() < end:
            v = self.queue.status(jid)
            seen.append((v["state"], dict(v["progress"])))
            if v["state"] in ("done", "failed", "cancelled"):
                break
            time.sleep(0.03)
        return seen

    def test_the_first_run_promises_no_time_while_it_loads_and_records_both_parts(self):
        jid = self.queue.submit("stepped", {"prompt": "x"})["id"]
        seen = self._watch(jid, 5)
        loading = [p for s, p in seen if s == "running" and p.get("phase") == "loading"]
        self.assertTrue(loading)
        self.assertTrue(all(p.get("phase_known") is False and p.get("eta_seconds") is None for p in loading))
        stepping = [p for s, p in seen if s == "running" and p.get("phase") == "steps"]
        self.assertTrue(stepping)  # the first run of its kind counts its steps and promises no time left
        self.assertTrue(all(p.get("phase_known") is False and p.get("eta_seconds") is None for p in stepping))
        hist = self.queue._read_path(self.queue.dir / "history.json")
        self.assertIn("stepped|load", hist)
        self.assertIn("stepped|steps", hist)
        self.assertGreater(hist["stepped|load"][0], 0.3)

    def test_a_long_load_holds_the_time_left_at_the_steps_and_never_jumps_up(self):
        self._watch(self.queue.submit("stepped", {"prompt": "x"})["id"], 5)  # times the two parts
        # the second run loads three times as long as the first
        jid = self.queue.submit("stepped", {"prompt": "x", "load": 1.2})["id"]
        seen = self._watch(jid, 8)
        steps = self.queue._history_estimate("stepped|steps")
        etas = [p["eta_seconds"] for s, p in seen if s == "running" and p.get("eta_seconds") is not None and p.get("phase_known")]
        self.assertTrue(etas)
        loading = [p for s, p in seen if s == "running" and p.get("phase") == "loading" and p.get("phase_known")]
        self.assertTrue(any(p.get("load_over") for p in loading))
        self.assertTrue(all(p["eta_seconds"] >= steps - 0.05 for p in loading))  # never below the steps not yet begun
        for a, b in zip(etas, etas[1:]):
            self.assertLessEqual(b, a + 0.15)  # the time left only goes down (a breath of rounding allowed)


class NightHold(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="neovak_e3h_"))
        self.night = {"on": True}
        hold = lambda seconds: "the nightly job, until 10:15 PM Central" if self.night["on"] else None  # noqa: E731
        self.queue = JobQueue(self.tmp / "state", [Stepped(), Free()], governor=None, poll_seconds=0.05, hold=hold)

    def tearDown(self):
        self.queue.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_work_that_loads_no_model_runs_past_a_held_job(self):
        held = self.queue.submit("stepped", {"prompt": "a held boat", "gb": 30})["id"]
        time.sleep(0.3)
        free = self.queue.submit("free", {"text": "Made during the hold"})["id"]
        v = self.queue.wait(free, timeout=5)
        self.assertEqual(v["state"], "done")
        h = self.queue.status(held)
        self.assertEqual(h["state"], "queued")
        self.assertTrue(h["progress"]["stage"].startswith("waiting for the nightly job"))
        self.assertEqual(self.queue.status(held)["position"], 1)
        # a job held for the night is not counted ahead of anything
        third = self.queue.submit("free", {"text": "x"})
        self.assertIn(third["state"], ("queued", "running", "done"))
        self.night["on"] = False
        self.assertEqual(self.queue.wait(held, timeout=8)["state"], "done")

    def test_a_held_job_can_be_stopped_at_once(self):
        held = self.queue.submit("stepped", {"prompt": "x", "gb": 30})["id"]
        time.sleep(0.3)
        self.assertEqual(self.queue.cancel(held)["state"], "cancelled")


class WriterRelatives(unittest.TestCase):
    def test_a_writer_measured_cold_at_30_seconds_sizes_the_others(self):
        from neovak_queue.adapters import local_text
        a = local_text.LocalText({"output_dir": "/tmp"})
        p = {"task": "script", "model": "lms:gemma-4-e2b-it-qat", "length": 60, "cold": False}
        keys = a.related_keys(p)
        self.assertIn(("local-text2:lms:gemma-4-e2b-it-qat:script:60:cold", 1.0, 0.0), keys)
        self.assertIn(("local-text2:lms:gemma-4-e2b-it-qat:script:30:cold", 1.0 / 0.8, 0.0), keys)
        tmp = Path(tempfile.mkdtemp(prefix="neovak_e3w_"))
        try:
            q = JobQueue(tmp / "state", [a], governor=None, start_worker=False)
            q._record_history("local-text2:lms:gemma-4-e2b-it-qat:script:30:cold", 21.8)
            seconds, basis = q._expected(a, dict(p, length=30))
            self.assertEqual((seconds, basis), (21.8, "history"))  # found in memory: the cold run is the upper bound
            seconds, _ = q._expected(a, p)
            self.assertAlmostEqual(seconds, 27.2, places=1)  # one minute: the 30 second run scaled, not the table's 150 s
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class BurstOfWrongPasscodes(unittest.TestCase):
    def test_tries_sent_at_once_are_each_counted_before_they_are_checked(self):
        sys.path.insert(0, str(REPO / "people_screen"))
        import auth
        attempts = auth.Attempts()
        allowed, lock = [], threading.Lock()

        def one():
            wait, ticket = attempts.reserve("10.0.0.9")
            if not wait:
                with lock:
                    allowed.append(ticket)
        threads = [threading.Thread(target=one) for _ in range(60)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(len(allowed), auth.TRIES_PER_ADDRESS)
        # a right passcode gives its try back
        attempts2 = auth.Attempts()
        wait, ticket = attempts2.reserve("10.0.0.8")
        attempts2.release("10.0.0.8", ticket)
        self.assertEqual(attempts2.all, [])


if __name__ == "__main__":
    unittest.main()
