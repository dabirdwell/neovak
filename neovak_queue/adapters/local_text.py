"""Text lane: scripts, captions and prompt rewriting, written by the local language models.

Three kinds of writer answer here. The two watch officers already running on this machine (the 9B
on :8088 and the 27B on :8089) are shared, and a first call after a rest pages the model back into
memory, which can take a minute or more; this lane never starts, stops or unloads them. The third
kind is any language model LM Studio has on disk (:1234). Those are loaded on purpose, by this lane,
through LM Studio's own command line tool, with a fixed context and a time to live, and only after
the queue has asked the model governor about the memory. LM Studio's own just-in-time loading is
never relied on, so no model is pulled into memory around the check.

No request here sets max_tokens: a local model gets the whole turn it wants. The only limits are on
time. The queue runs one job at a time, so a writer that thinks for ten minutes over one sentence
holds up everything behind it. Rewrites and captions are asked with the model's private thinking
switched off (about a second, measured Nov 9 2026, against runs of 1 to 9 minutes with it on). A
script may think, for THINK_SECONDS; after that the same request is asked again with thinking off.
If a model fills its context anyway, the job fails and says so plainly, so a reply cut off in the
middle can never be presented as finished work.

Memory figures: a writer's figure is the peak this lane has measured on a real run here (the serving
process at its largest), else an estimate, which is the model's size on disk plus ESTIMATE_EXTRA_GB.
Every figure says which of the two it is.

The nightly hold (the window in the settings file, if this machine has one) is checked here,
because a job can reach this lane from the chat tools or the REST route as well as the screen.
The two officers' addresses come from the settings file too ([writers] quick and careful); a
machine with neither set still offers whatever LM Studio lists, and nothing else.
"""
import http.client
import json
import os
import re
import socket
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit
from .. import settings as _settings
from .base import Adapter, AdapterError

_S = _settings.load()
_window = _S.hold_window()
CENTRAL = _window[2] if _window else __import__("zoneinfo").ZoneInfo("America/Chicago")  # the hold window's zone


def _port_of(url):
    """The port in a writer's address, which is how its serving process is told apart (see serving_rss)."""
    try:
        return urlsplit(url).port if url else None
    except ValueError:
        return None


# The two officers. Their addresses come from the settings file; an empty address means that writer is not on this machine.
WRITERS = {
    "9b": {"label": "Quick writer", "url": _S.writer("quick"), "first_seconds": 90, "tokens_per_second": 30, "gb": 10,
           "port": _port_of(_S.writer("quick")), "note": "Good for most writing. Shared with other work on this machine."},
    "27b": {"label": "Careful writer", "url": _S.writer("careful"), "first_seconds": 240, "tokens_per_second": 12, "gb": 38,
            "port": _port_of(_S.writer("careful")), "note": "Writes more thoughtfully, and needs a lot of free memory."},
}
NO_WRITER = "That writer is not set up on this machine, so nothing was written. The settings file names the local text models under [writers]."
DEFAULT_WRITER = "9b"
# Seconds a whole job may take, on top of the time the writer may need to come back into memory. No token limit is ever sent.
TASK_SECONDS = {"rewrite": 150, "caption": 210, "script": 900}
THINKS = {"script"}  # the only task the model's private thinking is allowed to spend time on
THINK_SECONDS = {"9b": 150, "27b": 300}  # thinking this long with no words means it is asked again without thinking
THINK_SECONDS_OTHER = 150  # the same limit for a writer from LM Studio
QUIET_LIMIT = 900  # no word from the model for this long means it has stopped answering
WORDS_PER_MINUTE = 150
LENGTHS = {30: 75, 60: 150, 120: 300, 300: 750}
TONES = {"plain": "plain and direct", "warm": "warm and friendly", "serious": "serious and measured", "playful": "light and playful"}
TARGETS = ("image", "music", "video", "voice")
MAX_BRIEF = 6000

# LM Studio. Its listing is the only place a model name may come from; a name is never typed into a command by anyone else.
LMS_URL = "http://127.0.0.1:1234"
LMS_CLI = os.path.expanduser("~/.cache/lm-studio/bin/lms")
LMS_PREFIX = "lms:"
LMS_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/@-]{0,120}$")
LMS_CTX = 8192          # the context every load here is given; the governor's estimate is asked for the same figure
# A writer from LM Studio has LMS_CTX tokens for its thinking and its words together. Thinking longer than about half of
# that (at roughly four characters a token) is cut and the request is asked again without thinking, so the private
# thinking can never use up the room the words need. Measured Nov 9 2026: Qwen3.5 4B filled all 8192 tokens with thinking
# over a one sentence request in about two minutes, and the job then failed as if the person had asked for too much.
THINK_CHARS_LMS = LMS_CTX * 2
LMS_TTL = 900           # seconds after its last use that LM Studio keeps a model this lane loaded
LMS_LOAD_SECONDS = 900  # a load that takes longer than this is stopped
LMS_LIST_SECONDS = 20   # how long one listing is trusted before LM Studio is asked again
ESTIMATE_EXTRA_GB = 2.0  # on top of the size on disk, when no run has been measured
LOAD_SECONDS_PER_GB = 8  # measured Nov 9 2026: a 3.0 GB file took 23 s to load
# How much longer a script takes at each length read aloud, against one minute: the same factors the screen uses.
SCRIPT_LENGTH_FACTOR = {30: 0.8, 60: 1.0, 120: 1.4, 300: 2.5}
# Families that keep their private thinking inside <think> tags. LM Studio ignores a request's enable_thinking switch
# (measured Nov 9 2026 on Qwen3.5 4B: 6,133 characters of thinking arrived with it set), so for these an empty thinking
# block is put at the start of the reply instead, which the same measurement showed goes straight to the words in 2 s.
THINK_TAG_FAMILIES = ("qwen3", "qwen35", "qwen3_5", "qwen35moe", "deepseek", "glm4", "nemotron_h", "exaone4", "smollm3")
EMPTY_THOUGHT = "<think>\n\n</think>\n\n"
PEAKS_FILE = "writer_peaks.json"

_REWRITE = {
    "image": ("You rewrite rough ideas into one clear, vivid description for an image generator. Keep the person's subject and "
              "intent. Add concrete detail about the subject, setting, light and composition. Do not add names, brands or words "
              "to appear in the picture unless they were asked for. Reply with only the rewritten description, as one paragraph, "
              "with no preamble, no quotation marks and no notes."),
    "music": ("You rewrite rough ideas into one clear description for a music generator. Keep the person's mood and intent. Name "
              "instruments, tempo, feel and how the piece develops. Reply with only the rewritten description, as one paragraph, "
              "with no preamble, no quotation marks and no notes."),
    "video": ("You rewrite rough ideas into one clear description for a short video generator. Keep the person's subject and "
              "intent. Describe what moves and how, the setting, the light, and any sound. Keep to one continuous shot of a few "
              "seconds. Reply with only the rewritten description, as one paragraph, with no preamble, no quotation marks and no notes."),
    "voice": ("You rewrite text so it sounds natural when read aloud by a voice engine. Keep every fact and the person's meaning. "
              "Use shorter sentences, plain words and natural rhythm. Spell out numbers and abbreviations as they should be spoken. "
              "Reply with only the rewritten text, with no preamble, no quotation marks and no notes."),
}
_STYLE = "Never use an em dash. Do not invent facts, statistics, quotes or names that were not given to you."


def hold_active(now=None):
    return _settings.load().hold_state(0, now) == "inside"


def script_prompt(p):
    words = LENGTHS[p["length"]]
    return (f"You write narration to be read aloud by one voice. Write about {words} words, which is about {p['length']} seconds "
            f"when spoken. The tone is {TONES[p['tone']]}. Write only the words to be spoken: no title, no headings, no scene numbers, "
            f"no stage directions, no speaker labels, no notes. Do not deliberate over word counts; write it and stop. {_STYLE}")


def caption_prompt(p):
    return ("You write short captions for pictures and clips. Write three different captions, each one a single line, each under "
            "twenty words. Keep them specific to what was described. Put one caption on each line, with no numbering, no bullets, "
            f"no quotation marks and no notes. Do not deliberate over word counts; write them and stop. {_STYLE}")


def split_thinking(buffer):
    """Separate a model's private thinking from the words meant for the reader. Returns (words, still thinking)."""
    cleaned = re.sub(r"<think>.*?</think>", "", buffer, flags=re.S)
    if "<think>" in cleaned:
        return cleaned.split("<think>")[0], True
    return cleaned, False


def tidy(text):
    """Strip labels and wrapping quotes a model sometimes adds around its answer."""
    text = (text or "").strip()
    text = re.sub(r"^(rewritten (description|prompt|text)|prompt|description|script|caption)\s*:\s*", "", text, flags=re.I)
    return text.strip().strip('"“”').strip()


def caption_lines(text):
    """Three captions become a clean list even if a model numbered them anyway."""
    lines = []
    for ln in text.splitlines():
        ln = re.sub(r"^\s*(?:\d+[.)]|[-*•])\s*", "", ln).strip().strip('"“”').strip()
        if ln:
            lines.append(ln)
    return lines


# ------------------------------------------------------------------ LM Studio's listing
_lms_cache = {"at": 0.0, "models": None}
_lms_lock = threading.Lock()


def _lms_get(path, timeout=4):
    url = urlsplit(LMS_URL)
    conn = http.client.HTTPConnection(url.hostname, url.port, timeout=timeout)
    try:
        conn.request("GET", path)
        r = conn.getresponse()
        if r.status != 200:
            return None
        return json.loads(r.read().decode("utf-8", "replace"))
    finally:
        conn.close()


def _lms_entry(m):
    """One model as LM Studio's /api/v1/models describes it, reduced to what this lane needs."""
    key = m.get("key")
    if m.get("type") != "llm" or not isinstance(key, str) or not LMS_KEY.match(key):
        return None
    name, arch = str(m.get("display_name") or key), str(m.get("architecture") or "").lower()
    # Draft helpers for speculative decoding (LM Studio lists them as "Mtp ..." or "<family>-assistant") are not writers.
    if key == "mtp" or name.lower().startswith("mtp ") or arch.endswith("-assistant"):
        return None
    loaded = m.get("loaded_instances") or []
    first = loaded[0] if loaded and isinstance(loaded[0], dict) else {}
    quant = m.get("quantization") or {}
    return {"key": key, "name": name, "publisher": m.get("publisher") or "", "params": m.get("params_string") or "",
            "arch": arch, "quant": quant.get("name") or "", "bits": quant.get("bits_per_weight"), "bytes": m.get("size_bytes"),
            "format": m.get("format") or "", "loaded": bool(loaded), "ttl_seconds": first.get("remaining_ttl_seconds"),
            "context": (first.get("config") or {}).get("context_length"), "vision": bool((m.get("capabilities") or {}).get("vision"))}


def lmstudio_models(fresh=False):
    """The language models LM Studio has on disk, by key, with what it has in memory now.
    None when LM Studio is not running or does not answer. The listing is trusted for LMS_LIST_SECONDS."""
    with _lms_lock:
        if not fresh and _lms_cache["models"] is not None and time.time() - _lms_cache["at"] < LMS_LIST_SECONDS:
            return _lms_cache["models"]
        models = None
        try:
            data = _lms_get("/api/v1/models")
            if isinstance(data, dict) and isinstance(data.get("models"), list):
                models = {}
                for m in data["models"]:
                    entry = _lms_entry(m) if isinstance(m, dict) else None
                    if entry:
                        models[entry["key"]] = entry
        except (OSError, http.client.HTTPException, ValueError):
            models = None
        if models is not None or fresh:
            _lms_cache.update(at=time.time(), models=models)
        return models


def thinks_in_tags(entry):
    return any(f in (entry or {}).get("arch", "") for f in THINK_TAG_FAMILIES)


def plain_name(entry):
    """A name a first-time user can read: the model's own display name, with its family size when the name lacks it."""
    name = entry["name"].strip()
    if entry["params"] and entry["params"].lower() not in name.lower():
        name = f"{name} ({entry['params']})"
    return name


def label_for(entry, listing):
    """The plain name, with LM Studio's own word for the file format when the same model is there in two formats."""
    label = plain_name(entry)
    if entry.get("format") and sum(1 for e in listing.values() if plain_name(e) == label) > 1:
        label = f"{label} ({entry['format'].upper()})"
    return label


def describe_model(entry):
    """One plain sentence about where a model comes from and how it is stored."""
    bits = entry.get("bits")
    copy = ("a compact copy at 4 bits per weight" if bits and bits <= 4 else f"a copy at {int(bits)} bits per weight" if bits and bits < 8
            else "a copy at 8 bits per weight, close to the original" if bits else "")
    who = f" from {entry['publisher']}" if entry["publisher"] else ""
    parts = ["In LM Studio" + (f", {copy}{who}." if copy else f"{who}.")]
    if entry["vision"]:
        parts.append("It can also look at pictures, which this lane does not use.")
    parts.append(f"Loads when asked and leaves memory {LMS_TTL // 60} minutes after its last use.")
    return " ".join(parts)


def serving_rss(port=None, lmstudio=False):
    """Resident memory, in GB by process id, of what serves a writer: the llama-server on a port, or LM Studio's engine
    processes (the ones under its .internal folder; LM Studio gives each loaded model a process of its own).
    ps is run with fixed arguments. None when ps did not answer."""
    try:
        out = subprocess.run(["/bin/ps", "-axo", "pid=,rss=,command="], capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None
    found = {}
    for line in out.splitlines():
        parts = line.strip().split(None, 2)
        if len(parts) < 3:
            continue
        pid, rss, command = parts
        if port is not None and ("llama-server" in command and f"--port {port}" in command):
            pass
        elif lmstudio and ("/.cache/lm-studio/.internal/" in command and "/bin/lms" not in command):
            pass
        else:
            continue
        try:
            found[int(pid)] = int(rss) * 1024 / 1e9
        except ValueError:
            pass
    return found


def graphics_in_use_gb():
    """Memory the graphics chip has in use right now, in GB, from the system's own report (ioreg, fixed arguments).
    A llama-server with Metal keeps its weights here and almost nothing in its own resident set, so this, not RSS,
    is where an officer's footprint shows (measured Nov 9 2026: the 27B at work was 0.5 GB of RSS and 22 GB more here).
    None when the report is missing."""
    try:
        out = subprocess.run(["/usr/sbin/ioreg", "-r", "-c", "AGXAccelerator", "-d", "1"], capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None
    m = re.search(r'"In use system memory"=(\d+)', out)
    return int(m.group(1)) / 1e9 if m else None


def wired_gb():
    """Memory the system has wired down (it cannot be paged out), in GB, from vm_stat. A model on the graphics chip is wired."""
    try:
        out = subprocess.run(["/usr/bin/vm_stat"], capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None
    page = re.search(r"page size of (\d+) bytes", out)
    wired = re.search(r"Pages wired down:\s+(\d+)", out)
    return int(wired.group(1)) * int(page.group(1) if page else 16384) / 1e9 if wired else None


class PeakWatch:
    """Watches memory while a writer works and reports the largest footprint that can be pinned on it.

    Two readings run side by side. Process memory: the serving processes' resident sets (for LM Studio, where every
    loaded model is a process of its own, the writer's process is the one that appeared after the watch began, else
    the only engine process there is; with two already loaded and nothing to tell them apart, none is claimed).
    Graphics memory: the rise in what the graphics chip has in use, and in wired memory, since the watch began, which
    is where a Metal server's weights really sit. The figure reported is the larger of the two, and a rise of less
    than a gigabyte is not a load, so a writer that was already in memory gets no figure from that run."""

    def __init__(self, port=None, lmstudio=False):
        self.port, self.lmstudio, self.stop = port, lmstudio, threading.Event()
        first = serving_rss(port, lmstudio) or {}
        self.before = set(first)
        self.peaks = dict(first)
        self.gpu0, self.wired0 = graphics_in_use_gb(), wired_gb()
        self.gpu_peak, self.wired_peak = self.gpu0, self.wired0
        threading.Thread(target=self._run, daemon=True).start()

    def _sample(self):
        now = serving_rss(self.port, self.lmstudio)
        for pid, gb in (now or {}).items():
            if gb > self.peaks.get(pid, 0):
                self.peaks[pid] = gb
        g, w = graphics_in_use_gb(), wired_gb()
        if g is not None and (self.gpu_peak is None or g > self.gpu_peak):
            self.gpu_peak = g
        if w is not None and (self.wired_peak is None or w > self.wired_peak):
            self.wired_peak = w

    def _run(self):
        while not self.stop.is_set():
            self._sample()
            self.stop.wait(2.0)

    def process_gb(self):
        if not self.lmstudio:
            return max(self.peaks.values()) if self.peaks else None
        engines = {pid: gb for pid, gb in self.peaks.items() if gb >= 0.3}  # LM Studio's small base process is not a model
        new = {pid: gb for pid, gb in engines.items() if pid not in self.before}
        if new:
            return max(new.values())
        return next(iter(engines.values())) if len(engines) == 1 else None

    def graphics_gb(self):
        rises = [peak - base for peak, base in ((self.gpu_peak, self.gpu0), (self.wired_peak, self.wired0)) if peak is not None and base is not None]
        rise = max(rises) if rises else None
        return rise if rise is not None and rise >= 1.0 else None

    def finish(self):
        """(GB, how) where how says which reading it was, or (None, None) when nothing can be pinned on this writer."""
        self.stop.set()
        self._sample()
        process, graphics = self.process_gb(), self.graphics_gb()
        if self.lmstudio and process is not None and process >= 0.3 and (graphics is None or process >= graphics):
            return round(process, 2), "process memory"
        if graphics is not None:
            return round(graphics, 2), "graphics memory"
        if self.lmstudio and process is not None and process >= 0.3:
            return round(process, 2), "process memory"
        return None, None


class LocalText(Adapter):
    name = "local-text"
    lane = "text"
    summary = "Write a script or captions, or improve a prompt, with a local language model."
    params = {
        "task": {"type": "str", "default": "script", "choices": ["script", "caption", "rewrite"]},
        "brief": {"type": "str", "help": "What to write about, or the prompt to improve."},
        "model": {"type": "str", "default": DEFAULT_WRITER,
                  "help": "9b or 27b for the two writers always on this machine, or lms:<key> for a model LM Studio lists."},
        "length": {"type": "int", "default": 60, "choices": list(LENGTHS), "help": "For a script: spoken length in seconds."},
        "tone": {"type": "str", "default": "plain", "choices": list(TONES), "help": "For a script: the tone."},
        "target": {"type": "str", "default": "image", "choices": list(TARGETS), "help": "For a rewrite: what the prompt is for."},
        "about": {"type": "str", "default": "", "help": "For captions: a description of the picture or clip."},
    }

    # ------------------------------------------------------------------ what is here, and what it costs
    def describe(self):
        out = super().describe()
        listing = lmstudio_models()
        out["lmstudio"] = {"running": listing is not None, "count": len(listing or {})}
        return out

    def _peaks_path(self):
        d = self.config.get("state_dir")
        return Path(d) / PEAKS_FILE if d else None

    def peaks(self):
        """Peaks measured on real runs here, by writer id."""
        path = self._peaks_path()
        try:
            data = json.loads(path.read_text(encoding="utf-8")) if path and path.is_file() else {}
        except (OSError, ValueError):
            data = {}
        return data if isinstance(data, dict) else {}

    def record_peak(self, model, gb, task, how=None):
        """Keeps the largest peak seen for a writer, so a figure never shrinks below something that really happened."""
        path = self._peaks_path()
        if not path or gb is None or gb <= 0:
            return
        data = self.peaks()
        old = (data.get(model) or {}).get("peak_gb") or 0
        data[model] = {"peak_gb": round(max(old, gb), 1), "measured": datetime.now().astimezone().isoformat(timespec="seconds"), "task": task, "how": how}
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
            tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
            os.replace(tmp, path)
        except OSError:
            pass

    def figure(self, model, entry=None, peaks=None):
        """(GB, 'measured' or 'estimate') for a writer, or (None, None) when there is nothing to go on."""
        peaks = self.peaks() if peaks is None else peaks
        if (peaks.get(model) or {}).get("peak_gb"):
            return peaks[model]["peak_gb"], "measured"
        if model in WRITERS:
            return WRITERS[model]["gb"], "estimate"
        if entry and entry.get("bytes"):
            return round(entry["bytes"] / 1e9 + ESTIMATE_EXTRA_GB, 1), "estimate"
        return None, None

    def models(self):
        peaks, out = self.peaks(), []
        for k, v in WRITERS.items():
            gb, kind = self.figure(k, peaks=peaks)
            out.append({"model": k, "label": v["label"], "present": bool(v["url"]), "source": "officer", "gb": gb, "gb_kind": kind, "note": v["note"],
                        "loaded": None, "disk_gb": None, "thinks": True})
        listing = lmstudio_models() or {}
        for entry in sorted(listing.values(), key=lambda e: (e.get("bytes") or 0, e["name"])):
            gb, kind = self.figure(LMS_PREFIX + entry["key"], entry, peaks)
            out.append({"model": LMS_PREFIX + entry["key"], "label": label_for(entry, listing), "present": True, "source": "lmstudio",
                        "gb": gb, "gb_kind": kind, "note": describe_model(entry), "loaded": entry["loaded"], "ttl_seconds": entry["ttl_seconds"],
                        "disk_gb": round(entry["bytes"] / 1e9, 1) if entry.get("bytes") else None, "thinks": thinks_in_tags(entry),
                        "publisher": entry["publisher"], "params": entry["params"]})
        return out

    def memory_gb(self, params):
        """The governor knows both officers by name and answers from what is really in memory. An LM Studio model that is
        already loaded needs nothing new; one that is not is asked for by its estimate, and the governor is told which
        model and context so it can size the load itself."""
        model = params.get("model") or DEFAULT_WRITER
        if model in WRITERS:
            return model
        key = self._lms_key(model)
        entry = (lmstudio_models(fresh=True) or {}).get(key)
        if entry and entry["loaded"]:
            return 0
        gb, _ = self.figure(model, entry)
        if gb is None:
            raise AdapterError("LM Studio did not say how big that writer is, so it was not loaded.")
        return {"gb": gb, "lms": key, "ctx": LMS_CTX}

    @staticmethod
    def _lms_key(model):
        key = model[len(LMS_PREFIX):] if isinstance(model, str) and model.startswith(LMS_PREFIX) else ""
        if not key or not LMS_KEY.match(key):
            raise AdapterError("Please pick one of the listed writers.")
        return key

    def validate(self, params):
        p = super().validate(params)
        p["brief"] = p["brief"].strip()
        if not p["brief"]:
            raise AdapterError("Please say what to write about.")
        if len(p["brief"]) > MAX_BRIEF:
            raise AdapterError(f"That is too long. Please keep it under {MAX_BRIEF} characters.")
        p["about"] = (p["about"] or "").strip()[:MAX_BRIEF]
        if p["model"] in WRITERS:
            if not WRITERS[p["model"]]["url"]:
                raise AdapterError(NO_WRITER)
        else:
            key = self._lms_key(p["model"])
            listing = lmstudio_models(fresh=True)
            if listing is None:
                raise AdapterError("LM Studio is not running, so its writers cannot be used right now.")
            if key not in listing:
                raise AdapterError("LM Studio does not list that writer any more. Please pick another.")
            # A writer that has to be loaded first takes longer, so its runs are timed apart from warm ones (estimate_key).
            p["cold"] = not listing[key].get("loaded")
        return p

    def _cold(self, params):
        """True when this is a writer in LM Studio that is not in memory, so a load comes before the writing."""
        if "cold" in params:
            return bool(params["cold"])
        model = params.get("model") or ""
        if not model.startswith(LMS_PREFIX):
            return False
        entry = (lmstudio_models() or {}).get(model[len(LMS_PREFIX):])
        return bool(entry) and not entry.get("loaded")

    def plan(self, job):
        if job["params"]["task"] == "rewrite":
            return {}
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return {"outputs": [str(Path(self.config["output_dir"]) / f"neovak_text_{stamp}_j{job['id'][-6:]}.txt")]}

    def warm_key(self, params):
        # "2": runs from before thinking was limited took minutes, and must not set the estimate for these
        return f"local-text2:{params.get('model')}:{params.get('task')}:{params.get('length') if params.get('task') == 'script' else ''}"

    def estimate_key(self, params):
        # A run that had to load the writer first is timed apart from one that found it in memory.
        return self.warm_key(params) + (":cold" if self._cold(params) else "")

    def related_keys(self, params):
        """[(key, factor, seconds added)] of runs of the same writer that can size this one when it has no runs of its
        own: the same kind of writing with the writer loaded against not loaded (a run that loaded it first is an
        upper bound for one that finds it in memory; one that found it in memory plus the load for one that does not),
        then a script of another length, scaled by how much longer a longer script takes."""
        task = params.get("task") or "script"
        cold = self._cold(params)
        warm = self.warm_key(params)
        out = [(warm + ":cold", 1.0, 0.0)] if not cold else []
        if task == "script":
            mine = SCRIPT_LENGTH_FACTOR.get(params.get("length"), 1.0)
            for length, factor in SCRIPT_LENGTH_FACTOR.items():
                if length == params.get("length"):
                    continue
                other = self.warm_key(dict(params, length=length))
                out.append((other + (":cold" if cold else ""), mine / factor, 0.0))
                if not cold:
                    out.append((other + ":cold", mine / factor, 0.0))
        return out

    def load_seconds(self, params):
        """The load before the writing, for a writer in LM Studio that is not in memory: by its size on disk."""
        model = params.get("model") or ""
        if not self._cold(params):
            return 0
        entry = (lmstudio_models() or {}).get(model[len(LMS_PREFIX):]) if model.startswith(LMS_PREFIX) else None
        return 0 if entry is None else (entry.get("bytes") or 0) / 1e9 * LOAD_SECONDS_PER_GB

    def default_estimate(self, params, warm_seconds=None):
        # Rewrites and captions run without thinking; a script may think for up to THINK_SECONDS. A writer in LM Studio
        # that is not in memory adds its load; warm_seconds, when the queue knows a warm run time, replaces the table.
        model = params.get("model") or DEFAULT_WRITER
        seconds = {"script": 150, "caption": 12, "rewrite": 8}[params.get("task") or "script"]
        if model in WRITERS:
            return seconds if model != "27b" else seconds + WRITERS["27b"]["first_seconds"]
        return round((warm_seconds if warm_seconds is not None else seconds) + self.load_seconds(params))

    def messages(self, p):
        if p["task"] == "rewrite":
            return [{"role": "system", "content": _REWRITE[p["target"]]}, {"role": "user", "content": p["brief"]}]
        if p["task"] == "caption":
            user = p["brief"]
            if p["about"]:
                user = f"The picture or clip shows: {p['about']}\n\nWhat the captions should do: {p['brief']}"
            return [{"role": "system", "content": caption_prompt(p)}, {"role": "user", "content": user}]
        return [{"role": "system", "content": script_prompt(p)}, {"role": "user", "content": p["brief"]}]

    # ------------------------------------------------------------------ talking to the model
    def _converse(self, spec, body, ctx, state):
        """Streams one reply. Runs on its own thread so a cancel can cut the connection at any moment."""
        url = urlsplit(spec["url"])
        conn = http.client.HTTPConnection(url.hostname, url.port, timeout=QUIET_LIMIT)
        state["conn"] = conn
        try:
            conn.request("POST", "/v1/chat/completions", body=json.dumps(body), headers={"Content-Type": "application/json"})
            r = conn.getresponse()
            if r.status != 200:
                state["error"] = f"HTTP {r.status}"
                return
            for raw in r:
                line = raw.decode("utf-8", "replace").strip()
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    obj = json.loads(data)
                except ValueError:
                    continue
                choices = obj.get("choices") or []
                if not choices:
                    continue
                delta = choices[0].get("delta") or {}
                thought = delta.get("reasoning_content") or delta.get("reasoning")  # LM Studio and llama-server name the field differently
                if thought:
                    state["thinking"] = True
                    state["thought_chars"] = state.get("thought_chars", 0) + len(thought)
                if delta.get("content"):
                    state["buffer"] += delta["content"]
                    state["thinking"] = False
                state["finish"] = choices[0].get("finish_reason") or state.get("finish")
        except (OSError, http.client.HTTPException) as e:
            state["error"] = repr(e)
        finally:
            state["done"] = True

    def _officer_ready(self, spec, down):
        """The officer's own name for its model, from its listing. It is already running; nothing is loaded here."""
        if not spec["url"]:
            raise AdapterError(NO_WRITER)
        try:
            url = urlsplit(spec["url"])
            conn = http.client.HTTPConnection(url.hostname, url.port, timeout=15)
            conn.request("GET", "/v1/models")
            listing = json.loads(conn.getresponse().read().decode())
            return (listing.get("data") or [{}])[0].get("id")
        except (OSError, http.client.HTTPException, ValueError, IndexError):
            raise AdapterError(down)

    def _lms_ready(self, model, ctx):
        """An LM Studio model in memory, loaded here on purpose when it is not. Returns (spec, entry), or (None, None)
        when the job was cancelled during the load. The queue has already had the governor's GO for this load."""
        key = self._lms_key(model)
        listing = lmstudio_models(fresh=True)
        if listing is None:
            raise AdapterError("LM Studio is not running right now, so nothing was written.")
        entry = listing.get(key)
        if entry is None:
            raise AdapterError("LM Studio does not list that writer any more, so nothing was written.")
        if not entry["loaded"]:
            if not os.path.isfile(LMS_CLI):
                raise AdapterError("LM Studio's command line tool was not found, so this writer could not be loaded in a "
                                   "controlled way. Nothing was loaded.")
            ctx.progress(stage="loading the writer")
            r = ctx.spawn([LMS_CLI, "load", key, "--context-length", str(LMS_CTX), "--gpu", "max", "--ttl", str(LMS_TTL), "-y"],
                          timeout=LMS_LOAD_SECONDS)
            if ctx.cancel_requested:
                return None, None
            if getattr(r, "timed_out", False) or r.returncode != 0:
                raise AdapterError("LM Studio could not load this writer, so nothing was written.")
            entry = (lmstudio_models(fresh=True) or {}).get(key) or dict(entry, loaded=True)
        spec = {"label": label_for(entry, listing), "url": LMS_URL, "first_seconds": 0}
        return spec, entry

    def run(self, job, ctx):
        p = job["params"]
        if hold_active():
            s = _settings.load()
            raise AdapterError(f"Writing is paused until {s.hold_end_words()}. A nightly job needs this Mac's memory from {s.hold_words()}.")
        down = "The writing helper is not running right now, so nothing was written."
        ctx.progress(stage="waking the writer")
        officer = p["model"] in WRITERS
        watch = PeakWatch(port=WRITERS[p["model"]]["port"] if officer else None, lmstudio=not officer)  # before any load, so a new process is known as this writer's
        try:
            if officer:
                spec, entry = WRITERS[p["model"]], None
                model = self._officer_ready(spec, down)
            else:
                spec, entry = self._lms_ready(p["model"], ctx)
                if spec is None:
                    return None
                model = entry["key"]
            start = time.time()
            limit = start + TASK_SECONDS[p["task"]] + spec["first_seconds"]
            think = p["task"] in THINKS
            state = self._reply(spec, model, p, ctx, limit, think, entry)
            if state is not None and think and self.thought_filled(state):
                state["thought_too_long"] = True  # its thinking used the room the words needed
            if state is not None and state.get("thought_too_long"):  # the same request, answered straight away
                ctx.progress(stage="writing")
                state = self._reply(spec, model, p, ctx, limit, False, entry)
        finally:
            peak, how = watch.finish()
        if state is None:
            return None
        if state["error"]:
            raise AdapterError(down)
        if state["finish"] == "length":
            raise AdapterError("The writer used up all the room it has before it finished, so nothing was kept. "
                               "A shorter length may fit.")
        text = tidy(split_thinking(state["buffer"])[0])
        if not text:
            raise AdapterError("The writing helper did not write anything. Please try again.")
        out = {"text": text, "task": p["task"], "model": p["model"], "writer": spec["label"], "served_by": "LM Studio" if entry else "officer",
               "words": len(text.split()), "time_seconds": round(time.time() - start, 1), "peak_gb": peak, "peak_kind": "measured" if peak else None, "peak_how": how}
        if peak:
            self.record_peak(p["model"], peak, p["task"], how)
        if p["task"] == "caption":
            out["captions"] = caption_lines(text)
            text = "\n".join(out["captions"])
            out["text"] = text
        if p["task"] == "script":
            out["spoken_seconds"] = round(out["words"] / WORDS_PER_MINUTE * 60)
        if job["outputs"]:
            path = Path(job["outputs"][0])
            path.write_text(text + "\n", encoding="utf-8")
            out["files"], out["path"] = [str(path)], str(path)
        return out

    def _reply(self, spec, model, p, ctx, limit, think, entry=None):
        """One reply from the model. Returns its state, or None if the job was cancelled."""
        # Deliberately no max_tokens. See the note at the top of this file.
        body = {"model": model, "temperature": 0.7, "stream": True, "messages": self.messages(p)}
        if not think:
            body["chat_template_kwargs"] = {"enable_thinking": False}
            if entry is not None and thinks_in_tags(entry):  # LM Studio ignores the switch above; see THINK_TAG_FAMILIES
                body["messages"].append({"role": "assistant", "content": EMPTY_THOUGHT})
        state = {"buffer": "", "thinking": False, "done": False, "finish": None, "error": None, "conn": None}
        threading.Thread(target=self._converse, args=(spec, body, ctx, state), daemon=True).start()
        began, last_shown = time.time(), ""
        think_limit = THINK_SECONDS.get(p["model"], THINK_SECONDS_OTHER)
        while not state["done"]:
            if ctx.cancel_requested:
                self._cut(state)
                return None
            if time.time() > limit:
                self._cut(state)
                raise AdapterError("The writing helper took far too long, so it was stopped and nothing was kept.")
            words, thinking = split_thinking(state["buffer"])
            if thinking or (state["thinking"] and not words):
                if think and (time.time() - began > think_limit or (entry is not None and self.thought_chars(state) > THINK_CHARS_LMS)):
                    self._cut(state)
                    state["thought_too_long"] = True
                    return state
                ctx.progress(stage="thinking it over")
            elif words and words != last_shown:
                last_shown = words
                ctx.progress(stage="writing", partial=words[-6000:], words=len(words.split()))
            time.sleep(0.3)
        return None if ctx.cancel_requested else state

    @staticmethod
    def thought_chars(state):
        """How much private thinking has arrived so far: the separate thinking field plus anything inside <think> tags."""
        tagged = sum(len(t) for t in re.findall(r"<think>(.*?)(?:</think>|$)", state.get("buffer") or "", flags=re.S))
        return (state.get("thought_chars") or 0) + tagged

    @staticmethod
    def thought_filled(state):
        """True when a reply ended for lack of room while it had written no words yet: its thinking filled the context."""
        if state.get("finish") != "length":
            return False
        words, still_thinking = split_thinking(state.get("buffer") or "")
        return still_thinking or not words.strip()

    @staticmethod
    def _cut(state):
        """Closing the socket makes the model's server stop writing this reply."""
        conn = state.get("conn")
        sock = getattr(conn, "sock", None)
        if sock is None:
            return
        try:
            sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            conn.close()
        except OSError:
            pass
