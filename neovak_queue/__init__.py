"""NeoVak job queue (S1, 2026-10-28). One queue under every lane and all three clients.

Ruled 2026-09-10 (NEOVAK_RULING_2026-09-10.md section 3):
every generation is a job with an id, a state (queued, running, done, failed, cancelled),
a progress record (step, total, seconds elapsed, estimate) and a result. One job runs at a
time. Jobs persist to disk. Cancel kills the subprocess.

The core (queue.py, adapters/base.py) uses only the standard library, so it can be tested
without the model venv. Engines are adapters with three calls: describe, run, cancel.
"""
from .queue import JobQueue, STATES, LANES

__all__ = ["JobQueue", "STATES", "LANES"]
