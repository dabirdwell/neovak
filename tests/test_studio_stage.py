"""The queue's nightly hold and memory wait, the timeline adapter, and the picture adapter's new options.
No models. run: venv/bin/python3 tests/test_studio_stage.py"""
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from neovak_queue import JobQueue                                   # noqa: E402
from neovak_queue.adapters.base import Adapter, AdapterError        # noqa: E402
from neovak_queue.adapters.mflux_image import MfluxImage            # noqa: E402
from neovak_queue.adapters.timeline import Timeline                 # noqa: E402

FFMPEG = "/opt/homebrew/bin/ffmpeg"


class NeedsMemory(Adapter):
    name, lane = "needs", "image"
    params = {}

    def memory_gb(self, params):
        return 9

    def run(self, job, ctx):
        return {"files": [], "ran": True}


class Gate(unittest.TestCase):
    def make(self, hold=None, retry=0.05):
        d = tempfile.mkdtemp()
        gov = Path(d) / "gov.py"
        q = JobQueue(d, [NeedsMemory({})], governor=str(gov), start_worker=False, hold=hold, memory_retry_seconds=retry)
        self.addCleanup(q.stop)
        return q, gov

    def test_nightly_hold_makes_a_model_job_wait_then_run(self):
        state = {"held": True}
        q, gov = self.make(hold=lambda s: "the nightly job" if state["held"] else None)
        gov.write_text('print("VERDICT: GO")\n')
        q.thread = None
        job = q.submit("needs")
        # Since Nov 10 2026 a job held for the night stays in the line instead of holding the worker, so work that loads
        # no model can run past it (tests/test_repair_evening3.py NightHold); the worker passes over it.
        self.assertIsNone(q._claim_next())
        self.assertEqual(q.status(job["id"])["state"], "queued")
        self.assertIn("nightly", q.status(job["id"])["progress"]["stage"])
        state["held"] = False
        q._execute(q._claim_next())
        self.assertEqual(q.status(job["id"])["state"], "done")

    def test_no_go_waits_when_asked_and_runs_when_memory_comes_back(self):
        q, gov = self.make()
        count = Path(gov.parent) / "n"
        gov.write_text(f'''
import pathlib
p = pathlib.Path({str(count)!r})
n = int(p.read_text()) if p.exists() else 0
p.write_text(str(n + 1))
print("VERDICT: GO" if n >= 2 else "VERDICT: NO-GO")
''')
        job = q.submit("needs", context={"wait_for_memory": 30})
        q._execute(q._claim_next())
        self.assertEqual(q.status(job["id"])["state"], "done")
        self.assertEqual(count.read_text(), "3")

    def test_no_go_fails_at_once_without_patience(self):
        q, gov = self.make()
        gov.write_text('print("VERDICT: NO-GO")\n')
        job = q.submit("needs")
        q._execute(q._claim_next())
        self.assertEqual(q.status(job["id"])["state"], "failed")
        self.assertIn("NO-GO", q.status(job["id"])["error"])


class TimelineAdapter(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.a = Timeline({"output_dir": self.d})

    def test_refuses_files_outside_and_bad_numbers(self):
        with self.assertRaises(AdapterError):
            self.a.validate({"clips": [{"file": "/etc/hosts", "seconds": 2}]})
        png = Path(self.d) / "a.png"
        png.write_bytes(b"x")
        with self.assertRaises(AdapterError):
            self.a.validate({"clips": [{"file": str(png), "seconds": -1}]})
        with self.assertRaises(AdapterError):
            self.a.validate({"clips": []})

    def test_file_names_stay_out_of_the_filter(self):
        cmd, total = Timeline.command([{"file": "/x/a;rm -rf.png", "seconds": 2.0, "trim": 0.0}], [], [{"audio": False}], "square", True, "/x/out.mp4")
        graph = cmd[cmd.index("-filter_complex") + 1]
        self.assertNotIn("rm -rf", graph)
        self.assertEqual(total, 2.0)

    @unittest.skipUnless(Path(FFMPEG).exists(), "needs ffmpeg")
    def test_joins_a_picture_and_a_sound_into_one_file(self):
        from PIL import Image
        png, wav = Path(self.d) / "pic.png", Path(self.d) / "s.wav"
        Image.new("RGB", (64, 48), (200, 30, 30)).save(png)
        subprocess.run([FFMPEG, "-nostdin", "-y", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=330:duration=1.5", str(wav)], check=True)
        p = self.a.validate({"clips": [{"file": str(png), "seconds": 2}], "sounds": [{"file": str(wav), "start": 0.2, "seconds": 1.5}], "shape": "square"})
        out = Path(self.d) / "o.mp4"

        class Ctx:
            cancel_requested = False

            def progress(self, **k):
                pass

            def spawn(self, cmd, timeout=None):
                return subprocess.run(cmd, capture_output=True, text=True)
        r = self.a.run({"params": p, "outputs": [str(out)]}, Ctx())
        self.assertTrue(out.exists())
        self.assertTrue(r["has_sound"])
        self.assertAlmostEqual(r["seconds"], 2.0, delta=0.3)


class TimelineSidecar(unittest.TestCase):
    def test_a_timeline_sidecar_names_files_and_can_be_remade(self):
        from neovak_queue import provenance
        d = Path(tempfile.mkdtemp()).resolve()
        a = d / "a.png"
        a.write_bytes(b"x")
        params = {"clips": [{"file": str(a), "seconds": 2, "trim": 0}], "sounds": [], "shape": "square", "prompt": "Film"}
        stored, sources = provenance.split_sources(params, str(d))
        self.assertEqual(stored["clips"][0]["file"], "a.png")
        self.assertEqual(sources[0]["param"], "clips.0.file")
        self.assertNotIn(str(d), json.dumps(stored))
        side = {"remake": {"adapter": "timeline", "params": stored, "file_params": [s["param"] for s in sources]}, "sources": sources}
        adapter, again = provenance.remake_request(side, str(d))
        self.assertEqual(again["clips"][0]["file"], str(a))


class PictureOptions(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.a = MfluxImage({"output_dir": self.d, "sizes": {"square": (1024, 1024)}, "styles": {}})

    def test_memory_ask_rises_for_a_live_picture(self):
        self.assertEqual(self.a.memory_gb({"model": "z-image-turbo", "live": True}), 34)
        self.assertEqual(self.a.memory_gb({"model": "z-image-turbo"}), 30)
        self.assertEqual(self.a.memory_gb({"model": "flux2-klein-4b", "live": True}), 30)

    def test_source_must_be_in_a_folder_neovak_may_read(self):
        with self.assertRaises(AdapterError):
            self.a.validate({"prompt": "x", "size": "square", "model": "schnell", "source": "/etc/hosts"})
        pic = Path(self.d) / "p.png"
        from PIL import Image
        Image.new("RGB", (64, 64)).save(pic)
        p = self.a.validate({"prompt": "x", "size": "square", "model": "schnell", "source": str(pic), "strength": 0.4})
        self.assertEqual(p["source"], str(pic.resolve()))


if __name__ == "__main__":
    unittest.main()
