"""Core tests for neovak_queue. Standard library only, no
models: stand-in adapters run small Python subprocesses that print tqdm-style progress.

run: venv/bin/python3 tests/test_queue_core.py
"""
import json
import os
import signal
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from neovak_queue import JobQueue                                    # noqa: E402
from neovak_queue.adapters.base import Adapter, AdapterError, parse_tqdm   # noqa: E402
from neovak_queue.adapters.mflux_image import MfluxImage            # noqa: E402
from neovak_queue.adapters.mlx_speech import MlxSpeech              # noqa: E402
from neovak_queue.adapters.mflux_image import ENGINE_MODELS, check_identity, engine_command  # noqa: E402

PY = sys.executable

# A stand-in engine: prints a tqdm bar for `steps` steps, `delay` seconds apart, writes a
# file, and appends its start and end times to a shared log (to prove one-at-a-time).
ENGINE = textwrap.dedent("""
    import sys, time
    steps, delay, out, log = int(sys.argv[1]), float(sys.argv[2]), sys.argv[3], sys.argv[4]
    t0 = time.time()
    for i in range(1, steps + 1):
        time.sleep(delay)
        left = int((steps - i) * delay)
        sys.stderr.write("\\r%3d%%|##| %d/%d [00:%02d<00:%02d, %.2fs/it]" % (i*100//steps, i, steps, int(time.time()-t0), left, delay))
        sys.stderr.flush()
    open(out, "w").write("ok")
    open(log, "a").write("%f %f\\n" % (t0, time.time()))
""")


class Fake(Adapter):
    name = "fake"
    lane = "image"
    params = {"steps": {"type": "int", "default": 3}, "delay": {"type": "float", "default": 0.2},
              "fail": {"type": "bool", "default": False}, "gb": {"type": "int", "default": 0}}

    def memory_gb(self, params):
        return params.get("gb", 0)

    def plan(self, job):
        return {"outputs": [str(Path(self.config["out"]) / f"{job['id']}.txt")]}

    def run(self, job, ctx):
        p = job["params"]
        if p["fail"]:
            raise AdapterError("asked to fail")
        out = job["outputs"][0]
        # A job that was interrupted once finishes fast the second time.
        delay = p["delay"] if job["attempts"] == 1 else 0.05
        r = ctx.spawn([PY, "-c", ENGINE, str(p["steps"]), str(delay), out, self.config["log"]])
        if ctx.cancel_requested:
            return None
        if r.returncode != 0:
            raise AdapterError(r.stderr[-300:])
        return {"files": [out]}


def alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    # A zombie still answers kill(0); ask ps for its state.
    st = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True).stdout
    return bool(st.strip()) and not st.strip().startswith("Z")


class QueueTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="neovak_q_"))
        self.cfg = {"out": str(self.tmp), "log": str(self.tmp / "runs.log")}
        self.queues = []

    def tearDown(self):
        for q in self.queues:
            q.stop()

    def q(self, worker=True, governor=None, legacy=None):
        q = JobQueue(self.tmp / "state", [Fake(self.cfg)], governor=governor,
                     legacy_jobs_file=legacy, start_worker=worker, poll_seconds=0.2)
        self.queues.append(q)
        return q

    def wait_for(self, fn, timeout=15):
        end = time.time() + timeout
        while time.time() < end:
            v = fn()
            if v:
                return v
            time.sleep(0.05)
        self.fail("timed out")

    def test_submit_runs_to_done_with_real_progress(self):
        q = self.q()
        j = q.submit("fake", {"steps": 5, "delay": 0.3})
        self.assertEqual(j["state"], "queued")
        seen = self.wait_for(lambda: (lambda v: v if v["progress"].get("step") else None)(q.status(j["id"])))
        self.assertEqual(seen["state"], "running")
        self.assertEqual(seen["progress"]["total"], 5)
        self.assertEqual(seen["progress"]["source"], "engine")
        # Since Nov 10 2026 the first run of a kind counts its steps and promises no time left (the engine's own guess
        # after one step can promise less than is left and then jump back up); it times its load and steps for the next.
        self.assertEqual((seen["progress"].get("phase"), seen["progress"].get("phase_known")), ("steps", False))
        self.assertIsNone(seen["progress"].get("eta_seconds"))
        self.assertGreater(seen["progress"]["elapsed_seconds"], 0)
        v = q.wait(j["id"], timeout=15)
        self.assertEqual(v["state"], "done", v)
        self.assertTrue(Path(v["result"]["files"][0]).exists())
        self.assertGreater(v["progress"]["elapsed_seconds"], 1.0)
        # The next job of the same kind gets a history estimate while queued.
        q2 = self.q(worker=False)
        k = q2.submit("fake", {"steps": 5, "delay": 0.3})
        self.assertEqual(q2.status(k["id"])["progress"]["source"], "history")

    def test_one_job_at_a_time(self):
        q = self.q()
        ids = [q.submit("fake", {"steps": 3, "delay": 0.15})["id"] for _ in range(4)]
        for i in ids:
            self.assertEqual(q.wait(i, timeout=20)["state"], "done")
        runs = sorted(tuple(map(float, ln.split())) for ln in Path(self.cfg["log"]).read_text().split("\n") if ln)
        self.assertEqual(len(runs), 4)
        for (s1, e1), (s2, e2) in zip(runs, runs[1:]):
            self.assertLessEqual(e1, s2 + 0.01, "two jobs overlapped")

    def test_cancel_running_kills_the_subprocess(self):
        q = self.q()
        j = q.submit("fake", {"steps": 100, "delay": 0.2})
        pid = self.wait_for(lambda: q.get(j["id"]).get("pid"))
        self.assertTrue(alive(pid))
        t0 = time.time()
        q.cancel(j["id"])
        v = q.wait(j["id"], timeout=10)
        self.assertEqual(v["state"], "cancelled")
        self.assertLess(time.time() - t0, 3)
        self.wait_for(lambda: not alive(pid), timeout=6)
        self.assertFalse(Path(v["outputs"][0]).exists())

    def test_cancel_queued_never_runs(self):
        q = self.q()
        a = q.submit("fake", {"steps": 10, "delay": 0.1})
        b = q.submit("fake", {"steps": 1, "delay": 0.1})
        self.assertEqual(q.cancel(b["id"])["state"], "cancelled")
        self.assertEqual(q.wait(a["id"], timeout=10)["state"], "done")
        time.sleep(0.6)
        self.assertEqual(q.status(b["id"])["state"], "cancelled")
        self.assertIsNone(q.get(b["id"])["started"])

    def test_cancel_from_another_process_handle(self):
        worker = self.q()
        other = self.q(worker=False)       # e.g. Claude Desktop's copy, not the worker
        j = other.submit("fake", {"steps": 100, "delay": 0.2})
        pid = self.wait_for(lambda: worker.get(j["id"]).get("pid"))
        other.cancel(j["id"])
        self.assertEqual(other.wait(j["id"], timeout=10)["state"], "cancelled")
        self.wait_for(lambda: not alive(pid), timeout=6)

    def test_queued_jobs_survive_a_restart(self):
        q1 = self.q(worker=False)          # a server that accepts jobs, then goes away
        ids = [q1.submit("fake", {"steps": 2, "delay": 0.05})["id"] for _ in range(2)]
        q1.stop()
        q2 = self.q()                      # the restarted server
        for i in ids:
            self.assertEqual(q2.wait(i, timeout=15)["state"], "done")

    def test_running_job_survives_a_worker_crash(self):
        # The worker is a separate process that we SIGKILL mid-job, like a crash or a
        # launchd restart. Its engine subprocess keeps running (own session); the next
        # worker must kill that orphan, requeue the job, and finish it.
        state = self.tmp / "state"
        script = textwrap.dedent(f"""
            import sys, time; sys.path.insert(0, {str(REPO)!r}); sys.path.insert(0, {str(Path(__file__).parent)!r})
            from test_queue_core import Fake
            from neovak_queue import JobQueue
            q = JobQueue({str(state)!r}, [Fake({self.cfg!r})], poll_seconds=0.2)
            print(q.submit("fake", {{"steps": 200, "delay": 0.2}})["id"], flush=True)
            time.sleep(120)
        """)
        crash = subprocess.Popen([PY, "-c", script], stdout=subprocess.PIPE, text=True)
        jid = crash.stdout.readline().strip()
        reader = self.q(worker=False)
        orphan = self.wait_for(lambda: reader.get(jid).get("pid"))
        os.kill(crash.pid, signal.SIGKILL)
        crash.wait()
        self.assertTrue(alive(orphan), "engine should outlive its worker")
        self.assertEqual(reader.status(jid)["state"], "running")
        q2 = self.q()
        v = q2.wait(jid, timeout=20)
        self.assertEqual(v["state"], "done", v)
        self.assertEqual(v["attempts"], 2)
        self.assertTrue(any("requeued" in n for n in v["notes"]))
        self.wait_for(lambda: not alive(orphan), timeout=6)

    def test_only_one_worker_across_handles(self):
        a, b = self.q(), self.q()
        self.wait_for(lambda: a.is_worker or b.is_worker)
        time.sleep(0.5)
        self.assertNotEqual(a.is_worker, b.is_worker)

    def test_governor_no_go_blocks_and_go_runs(self):
        nogo = self.tmp / "gov_nogo.py"
        nogo.write_text("print('Need ~9.0 GB  |  reclaimable 3.0 GB  |  margin -10.0 GB (safety 4.0)')\nprint('VERDICT: NO-GO')\n")
        go = self.tmp / "gov_go.py"
        go.write_text("import sys\nprint('Need ~%s GB' % sys.argv[2])\nprint('VERDICT: GO')\n")
        q = self.q(governor=str(nogo))
        v = q.wait(q.submit("fake", {"gb": 9})["id"], timeout=10)
        self.assertEqual(v["state"], "failed")
        self.assertIn("NO-GO", v["error"])
        self.assertIn("reclaimable 3.0", v["governor"])
        self.assertFalse(Path(self.cfg["log"]).exists(), "nothing should have run")
        q.governor = str(go)
        v = q.wait(q.submit("fake", {"gb": 9})["id"], timeout=10)
        self.assertEqual(v["state"], "done")
        self.assertIn("Need ~9", v["governor"])

    def test_failure_is_recorded(self):
        q = self.q()
        v = q.wait(q.submit("fake", {"fail": True})["id"], timeout=10)
        self.assertEqual(v["state"], "failed")
        self.assertEqual(v["error"], "asked to fail")

    def test_validation(self):
        q = self.q(worker=False)
        with self.assertRaises(AdapterError):
            q.submit("fake", {"steps": "many"})
        with self.assertRaises(AdapterError):
            q.submit("fake", {"nonsense": 1})
        with self.assertRaises(AdapterError):
            q.submit("nope", {})
        self.assertEqual(q.submit(None, {}, lane="image")["adapter"], "fake")
        with self.assertRaises(AdapterError):
            q.submit(None, {}, lane="video")

    def test_legacy_music_job_is_reported(self):
        legacy = self.tmp / "jobs.json"
        legacy.write_text(json.dumps({"960fd55d": {
            "type": "music", "status": "done", "path": "/x/neovak_music_960fd55d.wav",
            "started": "2026-10-15T23:24:16", "updated": "2026-10-15T23:31:23",
            "time_seconds": 427.0, "message": "Music written."}}))
        q = self.q(worker=False, legacy=legacy)
        v = q.status("960fd55d")
        self.assertEqual((v["state"], v["lane"]), ("done", "music"))
        self.assertEqual(v["result"]["files"], ["/x/neovak_music_960fd55d.wav"])
        self.assertIn("960fd55d", [j["id"] for j in q.list()])
        self.assertEqual(q.status("nope")["state"], "not_found")

    def test_parse_tqdm(self):
        self.assertEqual(parse_tqdm(" 50%|#####     | 2/4 [00:05<00:05,  2.50s/it]"),
                         {"step": 2, "total": 4, "eta_seconds": 5})
        self.assertEqual(parse_tqdm("100%|##| 30/30 [1:02:03<00:00, 1.0it/s]")["step"], 30)
        self.assertEqual(parse_tqdm("  0%|   | 0/4 [00:00<?, ?it/s]"), {"step": 0, "total": 4})
        self.assertIsNone(parse_tqdm("Loading weights"))


class AdapterCommandTest(unittest.TestCase):
    """The adapters must hand the engines the same argv the old tools did. A fake venv bin
    records argv and writes a stand-in output file."""

    STYLES = {"editorial": "professional editorial photography, clean composition, natural lighting, magazine quality"}
    SIZES = {"landscape": (1152, 896), "square": (1024, 1024)}

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="neovak_a_"))
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        rec = (f"import json, sys, os\nopen(os.path.join({str(self.tmp)!r}, "
               "'argv_' + os.path.basename(sys.argv[0]) + '.json'), 'w').write(json.dumps(sys.argv[1:]))\n")
        (self.bin / "mflux-generate-flux2").write_text(
            f"#!{PY}\n{rec}a = sys.argv\nopen(a[a.index('--output') + 1], 'wb').write(b'png')\n")
        for name in ("mflux-generate", "mflux-generate-z-image-turbo", "mflux-generate-z-image",
                     "mflux-generate-qwen", "mflux-generate-fibo"):
            (self.bin / name).write_text((self.bin / "mflux-generate-flux2").read_text())
        (self.bin / "python3").write_text(
            f"#!{PY}\n{rec}a = sys.argv\n"
            "if '-m' in a:\n"
            "    d = a[a.index('--output_path') + 1]; os.makedirs(d, exist_ok=True)\n"
            "    open(os.path.join(d, 'audio_000.wav'), 'wb').write(b'wav')\n")
        for f in self.bin.iterdir():
            f.chmod(0o755)
        self.cfg = {"venv_bin": str(self.bin), "output_dir": str(self.tmp), "model_dir": str(self.tmp / "models"),
                    "styles": self.STYLES, "sizes": self.SIZES}
        self.q = JobQueue(self.tmp / "state", [MfluxImage(self.cfg), MlxSpeech(self.cfg)], poll_seconds=0.2)

    def tearDown(self):
        self.q.stop()

    def argv(self, binary):
        return json.loads((self.tmp / f"argv_{binary}.json").read_text())

    def test_fast_image_argv_matches_generate_image_fast(self):
        j = self.q.submit("mflux", {"prompt": "a lighthouse", "seed": 20261028, "mode": "fast"})
        v = self.q.wait(j["id"], timeout=10)
        self.assertEqual(v["state"], "done", v)
        out = v["outputs"][0]
        self.assertRegex(Path(out).name, r"^neovak_klein_\d{8}_\d{6}_20261028_j[0-9a-f]{6}\.png$")
        # Built by hand from generate_image_fast in neovak_server.py (lines 224 to 226 before S1).
        expected = ["--base-model", "flux2-klein-4b",
                    "--prompt=a lighthouse, " + self.STYLES["editorial"], "--seed", "20261028",
                    "--height", "896", "--width", "1152", "--steps", "4", "--output", out]
        self.assertEqual(self.argv("mflux-generate-flux2"), expected)
        self.assertEqual(v["result"]["size"], "1152x896")
        self.assertNotIn("thumbnail", v["result"])

    def test_standard_image_argv_matches_generate_image(self):
        j = self.q.submit("mflux", {"prompt": "p", "style": "", "size": "square", "seed": 5,
                                    "model": "schnell", "quantize": 8})
        v = self.q.wait(j["id"], timeout=10)
        self.assertEqual(v["state"], "done", v)
        out = v["outputs"][0]
        self.assertRegex(Path(out).name, r"^neovak_\d{8}_\d{6}_5_j[0-9a-f]{6}\.png$")
        # schnell belongs to mflux-generate; there is no saved q8 folder in this temp tree.
        self.assertEqual(self.argv("mflux-generate"),
                         ["--model", "schnell", "--low-ram", "--quantize", "8", "--prompt=p", "--seed", "5",
                          "--height", "1024", "--width", "1024", "--steps", "4", "--output", out])
        thumb = self.argv("python3")       # make_thumbnail's job, through the venv python
        self.assertEqual(thumb[0], "-c")
        self.assertEqual(thumb[2:], [out, out.replace(".png", "_thumb.png"), "384"])

    def test_saved_q8_weights_used_in_standard_mode_only(self):
        (self.tmp / "models" / "flux-schnell-q8").mkdir(parents=True)
        v = self.q.wait(self.q.submit("mflux", {"prompt": "p", "model": "schnell"})["id"], timeout=10)
        self.assertEqual(v["state"], "done", v)
        self.assertEqual(self.argv("mflux-generate")[:5], ["--model", str(self.tmp / "models" / "flux-schnell-q8"),
                                                          "--base-model", "schnell", "--low-ram"])
        v = self.q.wait(self.q.submit("mflux", {"prompt": "p", "mode": "fast"})["id"], timeout=10)
        self.assertEqual(v["state"], "done")
        self.assertEqual(self.argv("mflux-generate-flux2")[:2], ["--base-model", "flux2-klein-4b"])

    def test_speech_argv_matches_generate_speech(self):
        j = self.q.submit("mlx-audio", {"text": "Hello from the queue."})
        v = self.q.wait(j["id"], timeout=10)
        self.assertEqual(v["state"], "done", v)
        argv = self.argv("python3")
        self.assertEqual(argv[:5], ["-m", "mlx_audio.tts.generate", "--model",
                                    "mlx-community/Kokoro-82M-bf16", "--text=Hello from the queue."])
        self.assertEqual(argv[5], "--output_path")
        self.assertEqual(argv[7:], ["--join_audio"], "speed 1.0 must add no flag")
        self.assertTrue(Path(v["result"]["path"]).exists())
        self.assertFalse(Path(argv[6]).exists(), "temp folder removed")

    def test_each_model_goes_to_its_own_command(self):
        wanted = {"flux2-klein-4b": "mflux-generate-flux2", "z-image-turbo": "mflux-generate-z-image-turbo",
                  "z-image": "mflux-generate-z-image", "schnell": "mflux-generate", "dev": "mflux-generate",
                  "krea-dev": "mflux-generate", "qwen": "mflux-generate-qwen", "fibo": "mflux-generate-fibo"}
        self.assertEqual(sorted(wanted), sorted(ENGINE_MODELS))
        for model, binary in wanted.items():
            head = engine_command(self.bin, self.tmp / "models", model)
            self.assertEqual(Path(head[0]).name, binary, model)
            self.assertIn(model if model != "qwen" else "Qwen/Qwen-Image", head, model)

    def test_a_model_not_on_this_machine_is_refused_with_a_reason(self):
        with self.assertRaises(AdapterError) as c:
            self.q.submit("mflux", {"prompt": "p", "model": "flux2-klein-9b"})
        self.assertIn("not on this machine", str(c.exception))
        with self.assertRaises(AdapterError) as c:
            self.q.submit("mlx-audio", {"text": "p", "voice": "fish-s2-pro"})
        self.assertIn("not on this machine", str(c.exception))

    def test_identity_check(self):
        self.assertIsNone(check_identity("z-image-turbo", "Tongyi-MAI/Z-Image-Turbo"))
        self.assertIsNone(check_identity("dev", "black-forest-labs/FLUX.1-dev"))
        self.assertIsNone(check_identity("schnell", None), "unreadable metadata is not a failure")
        self.assertIn("FLUX.2-klein", check_identity("z-image-turbo", "black-forest-labs/FLUX.2-klein-4B"))
        self.assertIn("Z-Image Turbo".split()[0], check_identity("z-image", "Tongyi-MAI/Z-Image-Turbo"))

    def test_hung_voice_is_stopped_at_its_time_limit(self):
        # A stand-in engine that never finishes, exactly the failure in S1 section 8.
        (self.bin / "python3").write_text(f"#!{PY}\nimport time\ntime.sleep(600)\n")
        self.q.adapters["mlx-audio"].config["speech_timeout_seconds"] = 1.5
        t0 = time.time()
        v = self.q.wait(self.q.submit("mlx-audio", {"text": "Hello"})["id"], timeout=30)
        self.q.adapters["mlx-audio"].config.pop("speech_timeout_seconds", None)
        self.assertEqual(v["state"], "failed", v)
        self.assertIn("stopped responding", v["error"])
        self.assertLess(time.time() - t0, 20)
        self.assertFalse(Path(v["outputs"][0]).exists())

    def test_speech_description_reaches_only_the_voice_built_from_one(self):
        j = self.q.submit("mlx-audio", {"text": "Hi", "voice": "qwen3-tts", "description": "A tired old sailor."})
        self.assertEqual(self.q.wait(j["id"], timeout=10)["state"], "done")
        self.assertIn("--instruct=A tired old sailor.", self.argv("python3"))
        j = self.q.submit("mlx-audio", {"text": "Hi", "voice": "kokoro"})
        self.assertEqual(self.q.wait(j["id"], timeout=10)["state"], "done")
        self.assertFalse(any(a.startswith("--instruct") for a in self.argv("python3")))


if __name__ == "__main__":
    unittest.main(verbosity=2)
