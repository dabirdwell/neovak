"""Wiring checks for neovak_server.py without the model venv: a stand-in `mcp` module records
which tools get registered. The queue worker is off and the state folder is temporary, so no
job runs and no model loads.

  switch off: exactly the 12 tools from before S1, QUEUE is None, check_job unchanged
  switch on:  the 12 plus submit_job, job_status, cancel_job, list_jobs, job_lanes;
              generate_music queues a job; check_job reads it in the old shape;
              check_job still reports the Oct 15 music job from jobs.json

run: venv/bin/python3 tests/test_server_wiring.py
"""
import importlib
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_settings_file  # noqa: E402,F401  the tests' own settings file, before neovak_server is loaded

OLD_TOOLS = ["generate_image", "generate_image_fast", "edit_image_with_prompt", "upscale_image",
             "generate_with_lora", "check_models", "open_editor", "generate_video",
             "generate_speech", "generate_music", "check_job", "list_presets"]
NEW_TOOLS = ["submit_job", "job_status", "cancel_job", "list_jobs", "job_lanes", "make_animation", "write_text",
             "list_recipes", "run_recipe", "recipe_status", "cancel_recipe"]


def stub_mcp():
    registered = []

    class FastMCP:
        def __init__(self, *a, **k):
            pass

        def tool(self):
            def deco(fn):
                registered.append(fn.__name__)
                return fn
            return deco

    for name in ("mcp", "mcp.server", "mcp.server.fastmcp"):
        sys.modules[name] = types.ModuleType(name)
    sys.modules["mcp.server.fastmcp"].FastMCP = FastMCP
    return registered


def load(env):
    for k in ("NEOVAK_QUEUE", "NEOVAK_STATE_DIR", "NEOVAK_QUEUE_WORKER"):
        os.environ.pop(k, None)
    os.environ.update(env)
    # The settings are read once per process; read them again so this test's NEOVAK_STATE_DIR is the one in use.
    # Without this, a settings object cached by an earlier test pointed the queue at the worktree's own state folder,
    # and generate_music below queued a real job on the test engine's line.
    from neovak_queue import settings as _settings
    _settings.reset()
    registered = stub_mcp()
    sys.modules.pop("neovak_server", None)
    mod = importlib.import_module("neovak_server")
    return mod, registered


class Wiring(unittest.TestCase):
    def test_files_that_need_the_venv_parse(self):
        # rest_server.py needs starlette and the parity script needs mflux; parse them at least.
        import ast
        for f in ("rest_server.py", "tests/s1_parity.py"):
            ast.parse((REPO / f).read_text(), filename=f)

    def test_switch_off_is_the_old_server(self):
        ns, tools = load({})
        self.assertIsNone(ns.QUEUE)
        self.assertEqual(tools, OLD_TOOLS)
        self.assertEqual(ns.check_job("no-such-job")["status"], "not_found")

    def test_switch_on(self):
        state = tempfile.mkdtemp(prefix="neovak_w_")
        ns, tools = load({"NEOVAK_QUEUE": "1", "NEOVAK_STATE_DIR": state, "NEOVAK_QUEUE_WORKER": "0"})
        try:
            self.assertEqual(tools, OLD_TOOLS + NEW_TOOLS)
            self.assertFalse(ns.QUEUE.is_worker)
            self.assertEqual(sorted(ns.job_lanes()["adapters"]), ["cutout", "faces", "join-sound", "kontext", "local-text", "ltx-video", "mflux", "minimax-music", "mlx-audio", "motion", "seedvr2", "timeline"])

            m = ns.generate_music("soft piano", duration=15)
            self.assertEqual(sorted(m), ["job_id", "message", "output", "status"])
            self.assertEqual(m["status"], "queued")
            self.assertTrue(m["output"].startswith(str(ns.OUTPUT_DIR)))
            old = ns.check_job(m["job_id"])
            self.assertEqual((old["type"], old["status"], old["duration"]), ("music", "queued", 15.0))
            self.assertEqual(ns.job_status(m["job_id"])["position"], 1)
            self.assertEqual(ns.cancel_job(m["job_id"])["state"], "cancelled")
            self.assertEqual(ns.check_job(m["job_id"])["status"], "cancelled")

            j = ns.submit_job(lane="image", params={"prompt": "x", "seed": 3, "mode": "fast"})
            self.assertEqual((j["state"], j["adapter"], j["params"]["model"]), ("queued", "mflux", "flux2-klein-4b"))
            self.assertIn("error", ns.submit_job(lane="video", params={}))
            self.assertIn("error", ns.submit_job(lane="speech", params={"text": "hi", "voice": "nope"}))
            listed = ns.list_jobs()
            self.assertEqual(listed["jobs"][0]["id"], j["id"])
            ns.cancel_job(j["id"])

            # The Oct 15 music job, from the real jobs.json (read only).
            if ns.JOBS_FILE.exists() and "960fd55d" in ns.load_jobs():
                self.assertEqual(ns.check_job("960fd55d")["status"], "done")
                self.assertEqual(ns.job_status("960fd55d")["state"], "done")
        finally:
            ns.QUEUE.stop()


if __name__ == "__main__":
    unittest.main(verbosity=2)
