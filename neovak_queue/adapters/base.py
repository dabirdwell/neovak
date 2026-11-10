"""The adapter contract. Every engine (image, speech, music, and later video, animation, text)
is one subclass with three calls:

  describe()        what it does, its parameters, the models it sees, the memory it needs
  run(job, ctx)     job in, files out; reports progress through ctx; returns a result dict
  cancel(job, ctx)  stop the work. The default kills the subprocess group ctx.spawn started

Engine rules live here, never in clients (Flux wants cfg 1.0, LTX wants 8k+1 frames).

An adapter that drives something other than a local subprocess (the Blender MCP server, an
HTTP service such as ACE-Step on :8001, LM Studio) overrides cancel() and reports progress
with ctx.progress(); the queue does not care how the work is done.
"""
import os
import re
import signal
import subprocess
import threading
import time

from ..safe_text import scrub


class AdapterError(Exception):
    """A failure the adapter can explain in one line (bad parameter, engine exit code)."""


class Adapter:
    name = "base"            # unique adapter id, e.g. "mflux"
    lane = "none"            # one of queue.LANES
    summary = ""
    params = {}              # name -> {"type", "default", "help", optional "choices"}

    def __init__(self, config=None):
        self.config = config or {}

    # --- the three calls -------------------------------------------------------------
    def describe(self):
        return {"name": self.name, "lane": self.lane, "summary": self.summary,
                "params": self.params, "models": self.models(),
                "memory_gb": self.memory_gb({})}

    def run(self, job, ctx):
        raise NotImplementedError

    def cancel(self, job, ctx):
        ctx.kill()

    # --- hooks with sensible defaults ------------------------------------------------
    def models(self):
        return []

    def memory_gb(self, params):
        """GB to ask the model governor for before this job loads a model. 0 means no load.
        params may be partial (describe() passes {}), so read it with .get()."""
        return 0

    def validate(self, params):
        """Fill defaults, check types and choices. Returns a new dict. Raises AdapterError."""
        params, out = scrub(params), {}
        for key, spec in self.params.items():
            if key in params:
                val = params[key]
            elif "default" in spec:
                val = spec["default"]
            else:
                raise AdapterError(f"'{key}' is required")
            if val is not None:
                val = _coerce(key, val, spec.get("type", "str"))
                if "choices" in spec and val not in spec["choices"]:
                    raise AdapterError(f"'{key}' must be one of {spec['choices']}, got {val!r}")
            out[key] = val
        unknown = sorted(set(params) - set(self.params))
        if unknown:
            raise AdapterError(f"unknown parameter(s) for {self.name}: {unknown}")
        return out

    def plan(self, job):
        """Called once at submit. May return {"outputs": [paths]} so a client knows where the
        file will land before it exists (generate_music has always promised this)."""
        return {}

    def estimate_key(self, params):
        """Jobs with the same key are timed together for the history-based estimate."""
        return self.name

    def default_estimate(self, params):
        """Seconds to expect before any job with this key has finished, or None."""
        return None

    def parse_progress(self, line):
        """Given one line of engine output, return a dict with any of step, total,
        eta_seconds, stage; or None. Default: tqdm bars (" 2/4 [00:05<00:05, 2.50s/it]")."""
        return parse_tqdm(line)


def _coerce(key, val, typ):
    try:
        if typ == "int":
            return int(val)
        if typ == "float":
            return float(val)
        if typ == "bool":
            return val if isinstance(val, bool) else str(val).lower() in ("1", "true", "yes")
        if typ == "str":
            return str(val)
        return val
    except (TypeError, ValueError):
        raise AdapterError(f"'{key}' must be {typ}, got {val!r}")


_TQDM = re.compile(r"(\d+)/(\d+)\s*\[(?:(\d+):)?(\d+):(\d+)<(?:(?:(\d+):)?(\d+):(\d+)|\?)")


def parse_tqdm(line):
    m = _TQDM.search(line)
    if not m:
        return None
    step, total = int(m.group(1)), int(m.group(2))
    if total <= 0:
        return None
    out = {"step": step, "total": total}
    if m.group(7) is not None:
        out["eta_seconds"] = int(m.group(6) or 0) * 3600 + int(m.group(7)) * 60 + int(m.group(8))
    return out


def peak_gb_from(stderr):
    """The peak memory footprint line /usr/bin/time -l prints, as GB, or None if absent."""
    m = re.search(r"(\d+)\s+peak memory footprint", stderr or "")
    return round(int(m.group(1)) / 1e9, 1) if m else None


_TIME_REPORT = re.compile(r"^\s*[\d.]+\s+real\s+[\d.]+\s+user\s+[\d.]+\s+sys\s*$", re.M)


def without_time_report(stderr):
    """/usr/bin/time -l prints its statistics last, so the end of stderr is them and not the engine's error."""
    found = list(_TIME_REPORT.finditer(stderr or ""))
    return stderr[:found[-1].start()].rstrip() if found else stderr


def process_start_time(pid):
    """The kernel's start time for a pid, so a recorded pid is never confused with a reused one."""
    try:
        r = subprocess.run(["ps", "-o", "lstart=", "-p", str(pid)], capture_output=True, text=True)
        return r.stdout.strip() or None
    except OSError:
        return None


class RunContext:
    """What the queue hands an adapter's run(): a subprocess launcher that registers the
    process for cancel and streams its output into progress, plus direct progress calls."""

    def __init__(self, queue, job_id, adapter):
        self.queue = queue
        self.job_id = job_id
        self.adapter = adapter
        self.proc = None
        self.started = time.time()
        self._lock = threading.Lock()
        self._tail = []

    @property
    def cancel_requested(self):
        return self.queue._cancel_flag(self.job_id)

    def progress(self, **fields):
        self.queue._progress(self.job_id, fields)

    def spawn(self, cmd, env=None, cwd=None, timeout=None, measure=False):
        """Run cmd to completion. Returns subprocess.CompletedProcess with text stdout and
        stderr, the same shape subprocess.run(capture_output=True, text=True) gives, so an
        adapter can keep the exact command and error handling the old tool had.

        timeout: seconds after which the whole process group is stopped; the result then has
        timed_out = True. measure: run under /usr/bin/time -l, so the result carries peak_gb,
        the process's real peak memory footprint (MLX memory included). It is what the governor
        should be asked for next time."""
        if self.cancel_requested:
            return subprocess.CompletedProcess(cmd, -signal.SIGTERM, "", "cancelled before start")
        if measure and os.path.exists("/usr/bin/time"):
            cmd = ["/usr/bin/time", "-l"] + list(cmd)
        else:
            measure = False
        deadline = time.time() + timeout if timeout else None
        timed_out = False
        with self._lock:
            self.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                         env=env, cwd=cwd, start_new_session=True)
        self.queue._register_process(self.job_id, self.proc.pid, process_start_time(self.proc.pid))
        out_chunks, err_chunks = [], []
        t_out = threading.Thread(target=self._pump, args=(self.proc.stdout, out_chunks), daemon=True)
        t_err = threading.Thread(target=self._pump, args=(self.proc.stderr, err_chunks), daemon=True)
        t_out.start(); t_err.start()
        while self.proc.poll() is None:
            if self.cancel_requested:
                self.adapter.cancel(self.queue.get(self.job_id), self)
                break
            if deadline is not None and time.time() > deadline:
                timed_out = True
                self.kill()
                break
            time.sleep(0.25)
        self.proc.wait()
        t_out.join(5); t_err.join(5)
        self.proc.stdout.close(); self.proc.stderr.close()
        self.queue._register_process(self.job_id, None, None)
        self.queue._tail(self.job_id, "".join(self._tail)[-2000:])
        done = subprocess.CompletedProcess(cmd, self.proc.returncode,
                                           b"".join(out_chunks).decode("utf-8", "replace"),
                                           b"".join(err_chunks).decode("utf-8", "replace"))
        done.timed_out = timed_out
        if measure:
            done.peak_gb = peak_gb_from(done.stderr)
            done.stderr = without_time_report(done.stderr)
        return done

    def _pump(self, stream, sink):
        buf = b""
        while True:
            chunk = stream.read1(4096) if hasattr(stream, "read1") else stream.read(4096)
            if not chunk:
                break
            sink.append(chunk)
            buf += chunk
            # tqdm redraws with \r; a line ends at either \r or \n.
            parts = re.split(rb"[\r\n]", buf)
            buf = parts.pop()
            for raw in parts:
                self._line(raw.decode("utf-8", "replace"))
        if buf:
            self._line(buf.decode("utf-8", "replace"))

    def _line(self, line):
        if not line.strip():
            return
        with self._lock:
            self._tail.append(line + "\n")
            if len(self._tail) > 200:
                del self._tail[:100]
        p = self.adapter.parse_progress(line)
        if p:
            self.progress(**p)

    def kill(self, grace=5.0):
        """SIGTERM the whole process group, then SIGKILL after grace seconds."""
        with self._lock:
            proc = self.proc
        if proc is None or proc.poll() is not None:
            return
        kill_group(proc.pid, grace, proc)


def kill_group(pid, grace=5.0, proc=None):
    try:
        os.killpg(pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        return
    deadline = time.time() + grace
    while time.time() < deadline:
        if proc is not None:
            if proc.poll() is not None:
                return
        else:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                return
        time.sleep(0.1)
    try:
        os.killpg(pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass
