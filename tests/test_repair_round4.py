"""Unit checks for the fourth repair round. The real runs are in STUDIO_PLAN.md."""
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "people_screen"))
os.environ.setdefault("PS_STATE_DIR", tempfile.mkdtemp())
import core  # noqa: E402
from neovak_queue import queue as queue_module  # noqa: E402
from neovak_queue.adapters import local_text  # noqa: E402
from neovak_queue.adapters.base import Adapter, AdapterError  # noqa: E402
from neovak_queue.adapters.mflux_image import MfluxImage  # noqa: E402
from neovak_queue.queue import JobQueue  # noqa: E402


class Names(unittest.TestCase):
    def test_same_second_same_seed_get_their_own_files(self):
        a = MfluxImage({"output_dir": "/tmp/x", "sizes": {"square": (1024, 1024)}, "styles": {}, "model_dir": "/tmp", "venv_bin": "/tmp"})
        params = {"seed": 90001, "mode": "standard"}
        one = a.plan({"id": "20261109-100714-aaaaaa", "params": params})["outputs"][0]
        two = a.plan({"id": "20261109-100714-bbbbbb", "params": params})["outputs"][0]
        self.assertNotEqual(one, two)
        self.assertRegex(Path(one).name, core._NAME_RE)
        self.assertEqual(core._NAME_RE.match(Path(one).name).group(3), "90001")


class Flaky(Adapter):
    name, lane = "flaky", "image"
    params = {}

    def __init__(self, fails):
        super().__init__({})
        self.fails, self.runs = fails, 0

    def run(self, job, ctx):
        self.runs += 1
        if self.runs <= self.fails:
            raise AdapterError("libc++abi: [METAL] Command buffer execution failed: kIOGPUCommandBufferCallbackErrorImpactingInteractivity")
        return {"files": [], "ok": True}


class Requests(unittest.TestCase):
    def setUp(self):
        self.q = JobQueue(tempfile.mkdtemp(), [Flaky(0)], start_worker=False)

    def tearDown(self):
        self.q.stop()

    def test_a_nul_in_a_job_id_is_not_a_crash(self):
        self.assertEqual(self.q.status("x\x00.png")["state"], "not_found")

    def test_an_adapter_list_or_params_string_is_refused_plainly(self):
        with self.assertRaises(AdapterError):
            self.q.submit(["x"], {})
        with self.assertRaises(AdapterError):
            self.q.submit("flaky", "x")


class GpuInterrupted(unittest.TestCase):
    def run_with(self, fails):
        queue_module.GPU_RETRY_SECONDS = 0.1
        adapter = Flaky(fails)
        q = JobQueue(tempfile.mkdtemp(), [adapter], poll_seconds=0.05)
        try:
            job = q.submit("flaky", {})
            view = q.wait(job["id"], timeout=15, interval=0.05)
        finally:
            q.stop()
        return view, adapter

    def test_tries_once_more_by_itself(self):
        view, adapter = self.run_with(1)
        self.assertEqual((view["state"], adapter.runs), ("done", 2))

    def test_says_so_plainly_when_it_happens_again(self):
        view, adapter = self.run_with(5)
        self.assertEqual((view["state"], adapter.runs), ("failed", 2))
        self.assertEqual(view["error"], queue_module.GPU_MESSAGE)
        self.assertTrue(any("Command buffer" in n for n in view["notes"]))


class FakeWriter(BaseHTTPRequestHandler):
    """Streams thinking for ever unless told not to think."""
    bodies = []

    def log_message(self, *a):
        pass

    def do_GET(self):
        out = json.dumps({"data": [{"id": "fake"}]}).encode()
        self.send_response(200); self.send_header("Content-Length", str(len(out))); self.end_headers(); self.wfile.write(out)

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        FakeWriter.bodies.append(body)
        self.send_response(200); self.end_headers()
        try:
            if (body.get("chat_template_kwargs") or {}).get("enable_thinking") is False:
                self.wfile.write(b'data: {"choices":[{"delta":{"content":"plain words"},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n')
                return
            for _ in range(200):
                self.wfile.write(b'data: {"choices":[{"delta":{"reasoning_content":"hm "}}]}\n\n')
                self.wfile.flush()
                time.sleep(0.05)
        except OSError:
            pass


class Ctx:
    cancel_requested = False

    def progress(self, **kw):
        pass


class Writing(unittest.TestCase):
    def setUp(self):
        FakeWriter.bodies = []
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), FakeWriter)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.saved = dict(local_text.WRITERS["9b"]), dict(local_text.THINK_SECONDS)
        local_text.WRITERS["9b"]["url"] = f"http://127.0.0.1:{self.server.server_address[1]}"
        local_text.THINK_SECONDS["9b"] = 1

    def tearDown(self):
        local_text.WRITERS["9b"].update(self.saved[0])
        local_text.THINK_SECONDS.update(self.saved[1])
        self.server.shutdown()

    def job(self, task):
        return {"id": "x-aaaaaa", "outputs": [], "params": {"task": task, "brief": "bees", "model": "9b", "length": 60, "tone": "plain", "target": "voice", "about": ""}}

    def test_a_rewrite_never_thinks(self):
        out = local_text.LocalText({}).run(self.job("rewrite"), Ctx())
        self.assertEqual(out["text"], "plain words")
        self.assertEqual(FakeWriter.bodies[0]["chat_template_kwargs"], {"enable_thinking": False})
        self.assertNotIn("max_tokens", FakeWriter.bodies[0])

    def test_a_script_that_thinks_too_long_is_asked_again(self):
        started = time.time()
        out = local_text.LocalText({}).run(self.job("script"), Ctx())
        self.assertEqual(out["text"], "plain words")
        self.assertLess(time.time() - started, 5)
        self.assertEqual(len(FakeWriter.bodies), 2)
        self.assertNotIn("chat_template_kwargs", FakeWriter.bodies[0])
        self.assertTrue(all("max_tokens" not in b for b in FakeWriter.bodies))


class Memory(unittest.TestCase):
    def test_the_sentence_adds_up(self):
        text = core.badge_for(40, {"available_gb": 43.7, "safety_gb": 4.0})["text"]
        self.assertIn("about 44 GB in all", text)
        self.assertIn("43.7 GB is free", text)

    def test_a_reading_from_before_the_job_says_so(self):
        self.assertIn("once the work running now is done", core.badge_for(30, {"available_gb": 44.0, "safety_gb": 4.0, "quiet": True})["text"])

    def test_alternatives_offer_only_what_fits(self):
        offers = core.alternatives("image", {"model": "z-image-turbo", "live": True}, {"available_gb": 36.0, "safety_gb": 4.0})
        self.assertEqual(offers[0], {"kind": "live_off", "label": "Polished", "gb": 30})
        self.assertTrue(all(o["gb"] <= 32 for o in offers))

    def test_no_room_means_no_offers(self):
        self.assertEqual(core.alternatives("image", {"model": "qwen", "live": False}, {"available_gb": 10.0, "safety_gb": 4.0}), [])


class Voices(unittest.TestCase):
    def test_symbols_are_not_words(self):
        for text in ("\U0001f41d\U0001f41d", "..."):
            with self.assertRaises(core.Invalid):
                core.validate_create({"lane": "voice", "prompt": text, "voice": "kokoro"})

    def test_a_voice_that_reads_english_says_so(self):
        with self.assertRaises(core.Invalid) as e:
            core.validate_create({"lane": "voice", "prompt": "Hola amigos. 你好世界", "voice": "kokoro"})
        self.assertIn("English only", str(e.exception))


if __name__ == "__main__":
    unittest.main()
