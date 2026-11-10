"""The job queue. Standard library only.

On disk, under state_dir (the [folders] state folder from the settings file):
  jobs/<id>.json   one record per job, rewritten atomically on every change
  pending/<id>     an empty marker per queued job, so the worker never scans every record
  history.json     recent run times per estimate key, for estimates before a job starts
  queue.lock       held (flock) for every read-modify-write of a record
  worker.lock      held (flock) for life by the one process that runs jobs

Several processes may open the same queue at once (the launchd REST service, Claude
Desktop's stdio MCP server, a test server). Every one of them can submit, read and cancel.
Only the process holding worker.lock runs jobs, so one job runs at a time across all of
them. If that process dies the kernel drops its lock and another process takes over within
a few seconds; jobs it left "running" are killed if still alive and put back in the queue.

The job record (schema 1):
  id, schema, lane, adapter, params, client, state, created, started, finished, attempts,
  progress {step, total, elapsed_seconds, estimate_seconds, eta_seconds, stage, source},
  result {files: [...], ...adapter fields}, outputs (planned at submit), error, governor,
  cancel_requested, pid, pid_started, worker_pid, log_tail, notes, context (recipe and chain
  a job belongs to, copied into its sidecar), sidecars (paths of the provenance files written)
"""
import fcntl
import json
import os
import statistics
import subprocess
import threading
import time
import traceback
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from . import memory as _memory
from . import provenance
from . import settings as _settings
from .adapters.base import AdapterError, RunContext, kill_group, process_start_time

STATES = ("queued", "running", "done", "failed", "cancelled")
FINAL = ("done", "failed", "cancelled")
LANES = ("image", "speech", "music", "edit", "video", "animation", "text")
SCHEMA = 1
MAX_ATTEMPTS = 3
MAX_LINE = 40  # jobs that may be waiting at once, from every client together
# Metal drops a long job when something else, outside this queue, uses the GPU at the same moment.
GPU_INTERRUPTED = ("kIOGPUCommandBuffer", "Command buffer execution failed")
GPU_MESSAGE = ("The graphics chip was interrupted while this was being made, usually because another program was using it "
               "at the same moment. Nothing was kept. Please try again.")
GPU_RETRY_SECONDS = 20  # time for whatever else was using the GPU to finish


def _now():
    return datetime.now().isoformat(timespec="seconds")


def lean_late(runs):
    """The median of the last five runs, or of the last three when that is larger. None for no runs."""
    runs = [r for r in (runs or []) if isinstance(r, (int, float)) and not isinstance(r, bool) and r > 0]
    if not runs:
        return None
    return round(max(statistics.median(runs[-5:]), statistics.median(runs[-3:])), 1)


# One memory ask is a number of GB, an officer name, or a dict {"gb", "lms", "ctx"} for a model in LM Studio.
# The arguments the governor gets, and the words for a job's error line, live with the check itself.
preflight_args, need_words = _memory.preflight_args, _memory.need_words


class LineFull(AdapterError):
    """More work is waiting than the queue will hold. Nothing was added."""


class _Stopping(Exception):
    """This process is shutting down while a job waited to load its model."""


class _HeldForTheNight(Exception):
    """The nightly window is open (or this job would run into it). The job goes back to the line."""

    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


class JobQueue:
    def __init__(self, state_dir, adapters, governor=None, legacy_jobs_file=None,
                 start_worker=True, poll_seconds=1.0, hold=None, memory_retry_seconds=20):
        self.dir = Path(state_dir)
        self.jobs_dir = self.dir / "jobs"
        self.pending_dir = self.dir / "pending"
        for d in (self.jobs_dir, self.pending_dir):
            d.mkdir(parents=True, exist_ok=True)
        self.adapters = {a.name: a for a in adapters}
        self.governor = governor
        self.legacy_file = Path(legacy_jobs_file) if legacy_jobs_file else None
        self.poll = poll_seconds
        self.hold = hold  # a function: seconds this job should take -> a reason to wait, or None
        self.memory_retry = memory_retry_seconds
        self._tlock = threading.Lock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._worker_fh = None
        self._last_write = {}
        self.thread = None
        if start_worker:
            self.thread = threading.Thread(target=self._worker_loop, name="neovak-queue", daemon=True)
            self.thread.start()

    # ================================================================ public API
    def describe(self):
        return {"lanes": list(LANES), "states": list(STATES),
                "adapters": {n: a.describe() for n, a in self.adapters.items()}}

    def submit(self, adapter, params=None, client="", lane=None, context=None):
        """Validate and enqueue. Returns the job view. Raises AdapterError on bad input."""
        if params is not None and not isinstance(params, dict):
            raise AdapterError("params must be an object")
        a = self._adapter_for(adapter, lane)
        clean = a.validate(dict(params or {}))
        rec = {
            "id": f"{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}",
            "schema": SCHEMA, "lane": a.lane, "adapter": a.name, "params": clean,
            "client": client, "state": "queued", "created": _now(), "created_ts": time.time(),
            "started": None, "finished": None, "attempts": 0,
            "progress": {"step": None, "total": None, "stage": "queued"},
            "result": None, "outputs": [], "error": None, "governor": None,
            "cancel_requested": False, "pid": None, "pid_started": None, "worker_pid": None,
            "log_tail": "", "notes": [], "context": context or {},
        }
        rec.update(a.plan(rec) or {})
        with self._locked():
            # A recipe's later steps were accepted when the recipe was, so they are not turned away part way through.
            if not rec["context"].get("recipe") and self.line_is_full():
                raise LineFull(f"The line is full. {MAX_LINE} things are already waiting, so nothing was added.")
            self._write(rec)
            (self.pending_dir / rec["id"]).touch()
        self._wake.set()
        return self.status(rec["id"])

    def line_is_full(self):
        return sum(1 for p in self.pending_dir.iterdir() if not p.name.startswith(".")) >= MAX_LINE

    def status(self, job_id):
        rec = self.get(job_id)
        if rec is None:
            return self._legacy_view(job_id)
        return self._view(rec)

    def list(self, state=None, lane=None, limit=50, include_legacy=True):
        recs = [r for r in (self._read_path(p) for p in self.jobs_dir.glob("*.json")) if r]
        if include_legacy:
            recs += [self._legacy_view(k) for k in self._legacy_jobs()]
        if state:
            recs = [r for r in recs if r.get("state") == state]
        if lane:
            recs = [r for r in recs if r.get("lane") == lane]
        # created has one-second resolution; created_ts breaks ties (legacy jobs lack it).
        recs.sort(key=lambda r: ((r.get("created") or "")[:19], r.get("created_ts", 0)), reverse=True)
        return [self._view(r) if r.get("schema") else r for r in recs[:max(1, int(limit))]]

    def cancel(self, job_id):
        """Queued: cancelled at once. Running: flagged; the worker kills the subprocess
        within a quarter second if it lives in this process, or within poll_seconds if the
        worker is another process. Final states are left alone."""
        found = []

        def fn(rec):
            found.append(rec["state"])
            if rec["state"] == "queued":
                rec.update(state="cancelled", finished=_now(), cancel_requested=True)
                rec["progress"]["stage"] = "cancelled"
                (self.pending_dir / job_id).unlink(missing_ok=True)
            elif rec["state"] == "running":
                rec["cancel_requested"] = True
                rec["progress"]["stage"] = "cancelling"

        if not self._mutate(job_id, fn):
            legacy = self._legacy_view(job_id)
            if legacy.get("state") != "not_found":
                legacy["error"] = "legacy jobs (jobs.json, before S1) cannot be cancelled here"
            return legacy
        return self.status(job_id)

    def get(self, job_id):
        if not job_id or "/" in job_id or "\x00" in job_id or job_id.startswith("."):
            return None
        return self._read_path(self.jobs_dir / f"{job_id}.json")

    def wait(self, job_id, timeout=None, interval=0.5):
        """Block until the job is final (for scripts and tests). Returns the view."""
        end = None if timeout is None else time.time() + timeout
        while True:
            v = self.status(job_id)
            if v.get("state") in FINAL or v.get("state") == "not_found":
                return v
            if end is not None and time.time() > end:
                return v
            time.sleep(interval)

    def stop(self):
        self._stop.set()
        self._wake.set()
        if self.thread:
            self.thread.join(10)
        if self._worker_fh:
            self._worker_fh.close()
            self._worker_fh = None

    @property
    def is_worker(self):
        return self._worker_fh is not None

    # ================================================================ adapter callbacks
    def _cancel_flag(self, job_id):
        rec = self.get(job_id)
        return bool(rec and rec.get("cancel_requested"))

    def _progress(self, job_id, fields):
        # Engines redraw progress many times a second; write when the step moves or once a second.
        key = (fields.get("step"), fields.get("stage"))
        last = self._last_write.get(job_id)
        if last and last[0] == key and time.time() - last[1] < 1.0:
            return
        self._last_write[job_id] = (key, time.time())

        def fn(rec):
            p = rec["progress"]
            p.update({k: v for k, v in fields.items() if v is not None})
            if "eta_seconds" in fields:
                p["eta_at"] = time.time()
            # The first step the engine reports ends the load. Load and steps are timed apart (history "|load" and
            # "|steps"), so the time left while a model loads never counts down the steps that have not begun.
            if (fields.get("step") is not None and fields.get("stage") != "loading model"
                    and not rec.get("first_step_ts") and rec.get("work_ts")):
                rec["first_step_ts"] = time.time()
                rec["first_step_n"] = fields["step"]
            p["source"] = "engine"
        self._mutate(job_id, fn)

    def _register_process(self, job_id, pid, started):
        self._mutate(job_id, lambda r: r.update(pid=pid, pid_started=started))

    def _tail(self, job_id, text):
        self._mutate(job_id, lambda r: r.update(log_tail=text))

    # ================================================================ worker
    def _worker_loop(self):
        while not self._stop.is_set():
            if not self.is_worker and not self._try_become_worker():
                self._stop.wait(max(2.0, self.poll))
                continue
            rec = self._claim_next()
            if rec is None:
                self._wake.wait(self.poll)
                self._wake.clear()
                continue
            self._execute(rec)

    def _try_become_worker(self):
        fh = open(self.dir / "worker.lock", "a+")
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            fh.close()
            return False
        fh.seek(0); fh.truncate(); fh.write(f"{os.getpid()}\n"); fh.flush()
        self._worker_fh = fh
        self._recover()
        return True

    def _recover(self):
        """Jobs a dead worker left running: kill the orphan if it is still alive (checked by
        pid and kernel start time, so a reused pid is never touched), then requeue, or mark
        cancelled if a cancel was pending, or failed after MAX_ATTEMPTS."""
        for path in self.jobs_dir.glob("*.json"):
            rec = self._read_path(path)
            if not rec or rec.get("state") != "running":
                continue
            pid, started = rec.get("pid"), rec.get("pid_started")
            if pid and started and process_start_time(pid) == started:
                kill_group(pid)
            jid = rec["id"]

            def fn(r):
                r.update(pid=None, pid_started=None, worker_pid=None)
                if r.get("cancel_requested"):
                    r.update(state="cancelled", finished=_now())
                    r["progress"]["stage"] = "cancelled"
                elif r.get("attempts", 0) >= MAX_ATTEMPTS:
                    r.update(state="failed", finished=_now(),
                             error=f"interrupted {r['attempts']} times by a restart; not retried again")
                    r["progress"]["stage"] = "failed"
                else:
                    r["state"] = "queued"
                    r["progress"] = {"step": None, "total": None, "stage": "queued"}
                    r["notes"].append(f"{_now()} requeued: the worker stopped while this job ran")
                    (self.pending_dir / jid).touch()
            self._mutate(jid, fn)

    def _claim_next(self):
        with self._locked():
            ids = sorted(p.name for p in self.pending_dir.iterdir() if not p.name.startswith("."))
            recs = [r for r in (self.get(i) for i in ids) if r]
            for i in ids:
                if not any(r["id"] == i for r in recs):
                    (self.pending_dir / i).unlink(missing_ok=True)
            recs.sort(key=lambda r: (r.get("created_ts", 0), r["id"]))
            for rec in recs:
                if rec["state"] != "queued":
                    (self.pending_dir / rec["id"]).unlink(missing_ok=True)
                    continue
                why = self._held_back(rec)
                if why:  # stays in the line, saying what it waits for; the next job that loads no model may run
                    stage = f"waiting for {why}"
                    if rec["progress"].get("stage") != stage:
                        rec["progress"]["stage"] = stage
                        self._write(rec)
                    continue
                (self.pending_dir / rec["id"]).unlink(missing_ok=True)
                rec.update(state="running", started=_now(), started_ts=time.time(),
                           attempts=rec.get("attempts", 0) + 1, worker_pid=os.getpid())
                rec["progress"]["stage"] = "starting"
                self._write(rec)
                return rec
        return None

    def _execute(self, rec):
        jid = rec["id"]
        adapter = self.adapters.get(rec["adapter"])
        result, error = None, None
        try:
            if adapter is None:
                raise AdapterError(f"no adapter named {rec['adapter']!r} in this server")
            gb = adapter.memory_gb(rec["params"])
            if gb:
                self._clear_to_load(jid, rec, gb)
            if not self._cancel_flag(jid):
                # the work itself starts now: time spent waiting for memory is not part of what this kind of job takes
                self._mutate(jid, lambda r: r.update(work_ts=time.time()))
                self._progress(jid, {"stage": "running"})
                result = adapter.run(self.get(jid), RunContext(self, jid, adapter))
        except _Stopping:
            self._put_back(jid)
            return
        except _HeldForTheNight as held:
            # The nightly window: the job goes back to the line and the worker moves on to work that loads no model,
            # the way a wait for memory never holds up an animation.
            self._put_back(jid, stage=f"waiting for {held.reason}")
            return
        except AdapterError as e:
            error = str(e)
        except Exception as e:
            error = f"{type(e).__name__}: {e}\n{traceback.format_exc()[-1500:]}"
        if error and any(mark in error for mark in GPU_INTERRUPTED):
            if self._retry_after_gpu_error(jid):
                return
            self._mutate(jid, lambda r: r["notes"].append(f"{_now()} {error[-400:]}"))
            error = GPU_MESSAGE
        self._finish(jid, adapter, result, error)

    def _retry_after_gpu_error(self, jid):
        """One automatic second try, at the front of the line. True if the job was put back."""
        rec = self.get(jid)
        if not rec or rec.get("cancel_requested") or rec.get("gpu_retried"):
            return False
        self._progress(jid, {"stage": "the graphics chip was interrupted, trying again"})
        try:
            self._pause(jid, GPU_RETRY_SECONDS)
        except _Stopping:
            self._put_back(jid)
            return True
        if self._cancel_flag(jid):
            return False

        def fn(r):
            r.update(state="queued", worker_pid=None, pid=None, pid_started=None, gpu_retried=True, attempts=max(0, r.get("attempts", 1) - 1))
            r["progress"] = {"step": None, "total": None, "stage": "queued"}
            r["notes"].append(f"{_now()} tried again: the graphics chip was interrupted")
            (self.pending_dir / jid).touch()
        self._mutate(jid, fn)
        self._wake.set()
        return True

    def _clear_to_load(self, jid, rec, gb):
        """Returns only when this job may load its model now, or has been cancelled. Raises if it may not.
        The nightly window and the governor are both asked in the same pass, and the window is asked
        again after every governor answer: a job can wait a long time for memory, and the window may
        have opened meanwhile."""
        # A job that asked to wait keeps being asked about, so a queue of pictures does not
        # fail just because the last model has not finished letting go of its memory.
        patience = float((rec.get("context") or {}).get("wait_for_memory") or 0)
        deadline = time.time() + patience
        while True:
            self._wait_out_hold(jid, rec)
            if self._cancel_flag(jid):
                return
            if self.governor is None:  # only a queue built without one, as the tests do
                return
            self._progress(jid, {"stage": "checking memory"})
            ok, report = self._preflight(gb)
            if self._hold_reason(rec):
                continue  # the window opened while the governor was answering, so that answer does not count
            if ok or time.time() >= deadline:
                self._mutate(jid, lambda r: r.update(governor=report))
                if not ok and not self._cancel_flag(jid):
                    raise AdapterError(f"model governor said NO-GO for {need_words(gb)}; nothing was run")
                return
            if self._cancel_flag(jid):
                return
            # the check's own figures go with the wait, so a screen can say why in numbers that agree with the check
            nums = _memory.parse_report(report or "")
            self._progress(jid, {"stage": "waiting for memory", "need_gb": nums.get("need_gb"), "free_gb": nums.get("available_gb"),
                                 "safety_gb": nums.get("safety_gb")})
            self._pause(jid, self.memory_retry)

    def _hold_reason(self, rec):
        if not self.hold:
            return None
        return self.hold((self._view(rec).get("progress") or {}).get("estimate_seconds") or 0)

    def _wait_out_hold(self, jid, rec):
        """The nightly job owns 21:25 to 22:15 Central. A job that would load a model then does not wait on the
        worker, which would keep everything behind it waiting too (an animation loads no model and may run): it goes
        back to the line, and _claim_next passes over it until the window has passed."""
        if self._stop.is_set():
            raise _Stopping()
        why = self._hold_reason(rec)
        if why and not self._cancel_flag(jid):
            raise _HeldForTheNight(why)
        return False

    def _held_back(self, rec):
        """The reason a queued job may not start now (the nightly window, for a job that loads a model), or None."""
        if not self.hold:
            return None
        a = self.adapters.get(rec.get("adapter"))
        try:
            loads = bool(a and a.memory_gb(rec.get("params") or {}))
        except Exception:  # noqa: BLE001  a job its adapter cannot size is not held back here; it fails when it runs
            loads = False
        return self._hold_reason(rec) if loads else None

    def _pause(self, jid, seconds):
        """Waits, but gives way at once to a Stop or to this process shutting down."""
        end = time.time() + seconds
        while time.time() < end:
            if self._stop.is_set():
                raise _Stopping()
            if self._cancel_flag(jid):
                return
            self._stop.wait(min(0.25, max(0.0, end - time.time())))

    def _put_back(self, jid, stage="queued"):
        """A job that never reached its model, returned to the line for the next worker."""
        def fn(r):
            r.update(state="queued", worker_pid=None, attempts=max(0, r.get("attempts", 1) - 1))
            r["progress"] = {"step": None, "total": None, "stage": stage}
            (self.pending_dir / jid).touch()
        self._mutate(jid, fn)
        self._last_write.pop(jid, None)

    def _finish(self, jid, adapter, result, error):
        elapsed, phases = None, None

        def fn(r):
            nonlocal elapsed, phases
            now = time.time()
            elapsed = round(now - r.get("started_ts", now), 1)
            # What the work itself took, without the wait for memory before it: that is what the next job of this kind
            # is promised. The load and the steps are kept apart too, when the engine reported steps.
            work = r.get("work_ts")
            if work:
                r["worked_seconds"] = round(now - work, 1)
                first = r.get("first_step_ts")
                if first and first >= work:
                    phases = (round(first - work, 1), round(now - first, 1))
            r["progress"]["elapsed_seconds"] = elapsed
            r["progress"].pop("eta_seconds", None)
            r.update(finished=_now(), pid=None, pid_started=None)
            if r.get("cancel_requested"):
                r["state"] = "cancelled"
            elif error:
                r.update(state="failed", error=error)
            else:
                r.update(state="done", result=result)
            r["progress"]["stage"] = r["state"]
        self._mutate(jid, fn)
        self._last_write.pop(jid, None)
        rec = self.get(jid)
        if rec and rec["state"] == "done" and adapter is not None:
            key = adapter.estimate_key(rec["params"])
            self._record_history(key, rec.get("worked_seconds") or elapsed)
            if phases:
                self._record_history(key + "|load", phases[0])
                self._record_history(key + "|steps", phases[1])
            self._write_sidecars(rec, adapter)

    def _write_sidecars(self, rec, adapter):
        """Say what made each output, beside the output. A failure here is noted on the job and
        does not take away a file that was made."""
        if rec["params"].get("still"):  # a preview is a throwaway, not an output
            return
        try:
            written = provenance.for_job(rec, adapter, adapter.config.get("output_dir") or "")
            self._mutate(rec["id"], lambda r: r.update(sidecars=written))
        except Exception as e:  # noqa: BLE001
            self._mutate(rec["id"], lambda r: r["notes"].append(f"{_now()} no sidecar written: {e!r}"))

    def _preflight(self, gb):
        """Ask the memory check (neovak_queue/memory.py). No answer means no model. governor is True
        for the check the settings file names, a path for one script in particular, as the tests do.
        A governor that is named and cannot be found stops the job at once, as a NO-GO does after
        any waiting: nothing ever loads around it.
        gb is a number of GB, an officer name the governor knows, or a dict {"gb", "lms", "ctx"} for a model in
        LM Studio: then the governor is told the model and context, sizes the load with LM Studio's own estimate
        (without loading anything) and falls back to the number given."""
        governor = self.governor if isinstance(self.governor, str) else _settings.load().governor
        if governor and not Path(governor).is_file():
            raise AdapterError("The memory check could not be found, so nothing was run.")
        out = _memory.preflight(gb, governor=governor)
        return out["go"], out["report"]

    # ================================================================ estimates and views
    def _record_history(self, key, seconds):
        if seconds is None:
            return
        with self._locked():
            path = self.dir / "history.json"
            hist = self._read_path(path) or {}
            hist[key] = (hist.get(key, []) + [seconds])[-10:]
            self._atomic(path, hist)

    def _history_estimate(self, key):
        """The figure promised for the next run of this kind: the middle of the recent runs, or of the last three when
        those have gone slower, so a promise follows the machine as it is now (more memory in use, a cold disk) within
        two runs instead of waiting for ten. One slow run alone does not move it."""
        hist = self._read_path(self.dir / "history.json") or {}
        return lean_late(hist.get(key))

    def estimate(self, adapter, params, lane=None):
        """What a job with these settings would be expected to take, before it is submitted: the same
        figure a queued job's view carries (this queue's own history for the settings, else the adapter's
        measured table), so a screen that asks here before a press shows the number the job will then
        show. Nothing is validated beyond what the key needs, and nothing is written."""
        a = self._adapter_for(adapter, lane)
        params = dict(params) if isinstance(params, dict) else {}
        for name, spec in getattr(a, "params", {}).items():  # the defaults validate() would fill, so the key is the job's
            if name not in params and "default" in spec:
                params[name] = spec["default"]
        try:
            key = a.estimate_key(params)
        except (KeyError, TypeError, ValueError, AttributeError, IndexError, AdapterError):
            key = None
        seconds, basis = self._expected(a, params)
        return {"adapter": a.name, "key": key, "estimate_seconds": seconds, "source": basis}

    def _expected(self, a, params):
        """(seconds, basis) for a job with these settings: this queue's history for the settings, else, for an
        adapter that times a cold start apart from a warm one (warm_key), the warm history plus the start, else
        the adapter's measured table. Never raises: a setting the adapter cannot size gives (None, "none")."""
        try:
            hist = self._history_estimate(a.estimate_key(params))
            if hist is not None:
                return hist, "history"
            warm = getattr(a, "warm_key", None)
            if warm is not None and warm(params) != a.estimate_key(params):
                warm_hist = self._history_estimate(warm(params))
                if warm_hist is not None:
                    return a.default_estimate(params, warm_seconds=warm_hist), "history"
            # Runs of the same model at another length, or loaded against not loaded, scaled by what the adapter knows
            # of the difference: a writer measured at 22 seconds is not promised the table's three minutes elsewhere.
            related = getattr(a, "related_keys", None)
            for rkey, factor, add in (related(params) if related else []):
                rhist = self._history_estimate(rkey)
                if rhist is not None:
                    return round(rhist * factor + add, 1), "history"
            seconds = a.default_estimate(params)
            if not isinstance(seconds, (int, float)) or isinstance(seconds, bool) or seconds <= 0:
                return None, "none"
            return seconds, "measured"
        except (KeyError, TypeError, ValueError, AttributeError, IndexError, AdapterError):
            return None, "none"

    def _view(self, rec):
        v = dict(rec)
        p = dict(rec.get("progress") or {})
        a = self.adapters.get(rec.get("adapter"))
        hist, basis = self._expected(a, rec["params"]) if a else (None, "none")
        now = time.time()
        phase = self._phase_view(a, rec, now) if a and rec["state"] == "running" else None
        if rec["state"] == "running" and rec.get("started_ts"):
            p["elapsed_seconds"] = round(now - rec["started_ts"], 1)
            if phase:
                p.update(phase)
                if p.get("estimate_seconds") is None and hist is not None:
                    p["estimate_seconds"] = hist  # what the whole usually takes, said as such while no time left is promised
            elif p.get("eta_seconds") is not None and p.get("eta_at"):
                remaining = max(0.0, p["eta_seconds"] - (now - p["eta_at"]))
                p["estimate_seconds"] = round(p["elapsed_seconds"] + remaining, 1)
                p["eta_seconds"] = round(remaining, 1)
            elif hist is not None:
                p["estimate_seconds"] = hist
                p["eta_seconds"] = round(max(0.0, hist - p["elapsed_seconds"]), 1)
                p.setdefault("source", basis)
        elif rec["state"] == "queued":
            p["elapsed_seconds"] = 0
            p["estimate_seconds"] = hist
            if hist is not None:
                p.setdefault("source", basis)
            v["position"] = self._position(rec)
        p.pop("eta_at", None)
        p.setdefault("source", "none")
        v["progress"] = p
        for k in ("created_ts", "started_ts"):
            v.pop(k, None)
        return v

    def _phase_view(self, a, rec, now):
        """Progress fields for a running job whose engine reports steps, timed in two parts: the load, then the steps.
        While the model loads, the time left is what is left of the usual load plus the whole of the usual steps, so it
        never counts down steps that have not begun; a load that runs long holds the figure at the steps' time instead of
        letting it run out. Once steps arrive, the time left is the steps' usual time less the time they have run.
        Without runs timed this way yet, a loading job says it is loading and promises no time left (phase_known False).
        None for a job that reports no steps, which keeps the plain estimate."""
        p = rec.get("progress") or {}
        work, started = rec.get("work_ts"), rec.get("started_ts")
        if not work or not started:
            return None
        try:
            key = a.estimate_key(rec["params"])
        except (KeyError, TypeError, ValueError, AttributeError, IndexError, AdapterError):
            return None
        load, steps = self._history_estimate(key + "|load"), self._history_estimate(key + "|steps")
        elapsed = now - started
        first = rec.get("first_step_ts")
        if first is None:
            if load is not None and steps is not None:
                load_left = max(0.0, load - (now - work))
                remaining = load_left + steps
                return {"phase": "loading", "phase_known": True, "steps_seconds": steps, "load_over": load_left <= 0,
                        "estimate_seconds": round(elapsed + remaining, 1), "eta_seconds": round(remaining, 1), "source": "history"}
            if p.get("stage") == "loading model":
                return {"phase": "loading", "phase_known": False, "eta_seconds": None}
            return None  # an engine that is not loading, or never reports steps (music), keeps the plain estimate
        if steps is None:
            # The first run of its kind: the steps have not been timed here yet, and the engine's own guess after one
            # step (or the whole estimate run down by the clock) can promise less than is left and then jump back up.
            # So the steps are counted and no time left is promised; this run times them for the next.
            return {"phase": "steps", "phase_known": False, "eta_seconds": None}
        remaining = max(0.0, steps - (now - first))
        return {"phase": "steps", "phase_known": True, "steps_seconds": steps,
                "estimate_seconds": round(elapsed + remaining, 1), "eta_seconds": round(remaining, 1), "source": "history"}

    def _position(self, rec):
        ids = sorted(p.name for p in self.pending_dir.iterdir() if not p.name.startswith("."))
        ahead = [i for i in ids if i < rec["id"]]
        # a job held back for the nightly window is not ahead of anything: the worker passes over it
        held = 0
        for i in ahead:
            other = self.get(i)
            if other and str((other.get("progress") or {}).get("stage") or "").startswith("waiting for the nightly"):
                held += 1
        return len(ahead) - held + 1

    # ---------------------------------------------------------------- legacy (jobs.json)
    def _legacy_jobs(self):
        if not self.legacy_file or not self.legacy_file.exists():
            return {}
        try:
            return json.loads(self.legacy_file.read_text())
        except (OSError, json.JSONDecodeError):
            return {}

    def _legacy_view(self, job_id):
        """Jobs from before S1 (music_job.py and the video stub wrote jobs.json). Read only."""
        old = self._legacy_jobs().get(job_id)
        if old is None:
            return {"id": job_id, "state": "not_found", "message": f"No job with ID {job_id}"}
        st = old.get("status")
        state = {"done": "done", "failed": "failed", "blocked": "failed", "queued": "running",
                 "checking_memory": "running", "generating": "running"}.get(st, "unknown")
        return {"id": job_id, "lane": old.get("type"), "adapter": "legacy-jobs.json",
                "state": state, "created": old.get("started"), "finished": old.get("updated"),
                "result": {"files": [old["path"]]} if st == "done" and old.get("path") else None,
                "error": old.get("error") or old.get("message") if state == "failed" else None,
                "progress": {"elapsed_seconds": old.get("time_seconds"), "source": "legacy"},
                "legacy": old}

    # ================================================================ storage
    def _adapter_for(self, adapter, lane):
        if adapter is not None and not isinstance(adapter, str):
            raise AdapterError("adapter must be a name")
        if isinstance(adapter, str) and adapter in self.adapters:
            return self.adapters[adapter]
        if adapter is None and lane:
            matches = [a for a in self.adapters.values() if a.lane == lane]
            if len(matches) == 1:
                return matches[0]
            if matches:
                raise AdapterError(f"lane {lane!r} has several adapters; name one: "
                                   f"{[a.name for a in matches]}")
            raise AdapterError(f"no adapter serves lane {lane!r} yet")
        raise AdapterError(f"unknown adapter {adapter!r}; known: {sorted(self.adapters)}")

    @contextmanager
    def _locked(self):
        with self._tlock:
            with open(self.dir / "queue.lock", "a") as fh:
                fcntl.flock(fh, fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    fcntl.flock(fh, fcntl.LOCK_UN)

    def _mutate(self, job_id, fn):
        with self._locked():
            rec = self.get(job_id)
            if rec is None:
                return False
            fn(rec)
            self._write(rec)
            return True

    def _write(self, rec):
        self._atomic(self.jobs_dir / f"{rec['id']}.json", rec)

    @staticmethod
    def _atomic(path, data):
        tmp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
        tmp.write_text(json.dumps(data, indent=2, default=str))
        os.replace(tmp, path)

    @staticmethod
    def _read_path(path):
        try:
            return json.loads(Path(path).read_text())
        except (OSError, json.JSONDecodeError):
            return None
