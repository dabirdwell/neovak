"""NeoVak people screen: everything that is not a web route.

Memory checks, the nightly hold, safe file serving, the screen's own records, the gallery
scan, and the three lanes that really run. Nothing here builds shell text: every process
is started from an argument list, and user text only ever travels as a single argument or
inside a JSON body.
"""
import hashlib
import json
import math
import os
import re
import signal
import statistics
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import wave
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from neovak_queue import lanes as _lanes  # noqa: E402  standard library only, so no model code comes with it
from neovak_queue import memory as _memory  # noqa: E402
from neovak_queue import provenance  # noqa: E402
from neovak_queue import secret  # noqa: E402  the engine's access token, from the same file the engine reads
from neovak_queue import settings as _settings  # noqa: E402
from neovak_queue.safe_text import scrub  # noqa: E402

# Every folder, tool and address of this machine comes from the settings file (neovak_queue/settings.py).
SETTINGS = _settings.load()
STATE_DIR = SETTINGS.screen_state_dir
OUTPUT_DIR = SETTINGS.output_dir
BACKEND = os.environ.get("PS_BACKEND", "http://127.0.0.1:8100")
HELPER_URL = os.environ.get("PS_HELPER", SETTINGS.writer("quick") or "http://127.0.0.1:8088")
VENV_PY = str(REPO / "venv" / "bin" / "python3")
HF_HOME = str(SETTINGS.hub_cache)
IMAGE_TIMEOUT = 1800
HELPER_TIMEOUT = 1800
MAX_PROMPT = 4000
MEDIA_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".wav", ".mp3", ".m4a", ".mp4", ".txt"}
VIDEO_SUFFIXES = {".mp4"}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}
TEXT_SUFFIXES = {".txt"}
TEXT_PREFIX = "neovak_text_"  # the only text files the screen ever lists or serves
PREVIEW_DIR = "_previews"

for sub in ("", "thumbs", "logs", "voice_tmp"):
    (STATE_DIR / sub).mkdir(parents=True, exist_ok=True)

# The memory figures are measured peak footprints from real runs (STUDIO_PLAN.md).
NOT_ROUTED = "This one did not work when it was tested on this machine, so it is switched off."
IMAGE_MODELS = {
    "flux2-klein-4b": {"label": "Quick", "engine": "FLUX.2 klein 4B", "gb": 30, "steps": 4,
                       "note": "The fastest way to see an idea.", "seconds": 45,
                       "repo": "black-forest-labs/FLUX.2-klein-4B", "routed": True},
    "z-image-turbo": {"label": "Polished", "engine": "Z-Image Turbo", "gb": 30, "steps": 9, "live": True,
                      "note": "Fast, with more finish. You can watch it arrive.", "seconds": 90,
                      "repo": "Tongyi-MAI/Z-Image-Turbo", "routed": True},
    "z-image": {"label": "Careful", "engine": "Z-Image", "gb": 18, "steps": 28, "live": True,
                "note": "Slower, for a final picture.", "seconds": 240,
                "repo": "Tongyi-MAI/Z-Image", "routed": True},
    "schnell": {"label": "Fast draft", "engine": "FLUX.1 schnell", "gb": 18, "steps": 4,
                "note": "An older fast model.", "seconds": 50,
                "repo": "black-forest-labs/FLUX.1-schnell", "routed": True},
    "dev": {"label": "Highest detail", "engine": "FLUX.1 dev", "gb": 29, "steps": 20, "live": True,
            "note": "Slow and detailed.", "seconds": 210,
            "repo": "black-forest-labs/FLUX.1-dev", "routed": True},
    "krea-dev": {"label": "Photo look", "engine": "FLUX.1 Krea dev", "gb": 29, "steps": 20, "live": True,
                 "note": "Natural, less plastic pictures.", "seconds": 210,
                 "repo": "black-forest-labs/FLUX.1-Krea-dev", "routed": True},
    "fibo": {"label": "Precise", "engine": "FIBO", "gb": 32, "steps": 30,
             "note": "Follows long, exact descriptions.", "seconds": 760,
             "repo": "briaai/FIBO", "routed": True},
    "qwen": {"label": "Words in pictures", "engine": "Qwen-Image", "gb": 40, "steps": 20,
             "note": "Best when the picture has to contain text.", "seconds": 520,
             "repo": "Qwen/Qwen-Image", "routed": True},
}
DEFAULT_IMAGE_MODEL = "flux2-klein-4b"
# The looks a first-time user is offered. The engine may also hold a household's own looks from styles.json.
PUBLIC_LOOKS = {"editorial": "Magazine", "cinematic": "Film still", "illustration": "Illustration", "documentary": "Documentary", "technical": "Diagram"}
VOICES = {
    "kokoro": {"label": "Clear narrator", "engine": "Kokoro", "gb": 4, "seconds": 30, "timeout": 180,
               "repo": "mlx-community/Kokoro-82M-bf16", "note": "Quick and even.", "own_speed": True, "english_only": True},
    "csm-1b": {"label": "Conversational", "engine": "CSM-1B", "gb": 16, "seconds": 45, "timeout": 600,
               "repo": "mlx-community/csm-1b", "note": "Sounds like talking.", "english_only": True},
    "chatterbox": {"label": "Expressive", "engine": "Chatterbox", "gb": 13, "seconds": 25, "timeout": 600,
                   "repo": "mlx-community/chatterbox-fp16", "note": "More feeling in the delivery.", "english_only": True},
    "qwen3-tts": {"label": "Described voice", "engine": "Qwen3-TTS", "gb": 23, "seconds": 25, "timeout": 600,
                  "repo": "Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign", "note": "A voice built from a description.",
                  "instruct": "A calm, clear adult narrator with a warm, even tone."},
    "soprano": {"label": "Quick and light", "engine": "Soprano 80M", "gb": 2, "seconds": 8, "timeout": 180, "added": True,
                "note": "A very small, very fast voice. Plainer than the others, and good for a quick listen.", "english_only": True,
                "needs": "voice:soprano"},
}
DEFAULT_VOICE = "kokoro"
ENGLISH_ONLY = "This voice reads English only, and these words include letters it cannot read. Please use English words, or choose Described voice."
MUSIC = {"label": "Music", "engine": "MiniMax-Music3", "gb": 11, "seconds": 270, "note": "Instrumental pieces or songs from a description.",
         "repo": "mlx-community/MiniMax-Music3-4bit", "needs": "music"}
MUSIC_LENGTHS = [15, 30, 60, 120]
# The enhance and edit lane. Each tool is one queue adapter; memory figures are measured peaks.
# The screen sends only a file name it has already checked against the output folder.
EDIT_TOOLS = {
    "change": {"label": "Change something", "engine": "FLUX.1 Kontext dev", "adapter": "kontext", "gb": 29,
               "seconds": 460, "words": True, "repo": "black-forest-labs/FLUX.1-Kontext-dev",
               "note": "Describe the change. The rest of the picture is kept as far as possible."},
    "bigger": {"label": "Make it bigger", "engine": "SeedVR2", "adapter": "seedvr2", "gb": 19, "seconds": 80,
               "repo": "numz/SeedVR2_comfyUI", "note": "Enlarges the picture and adds fine detail."},
    "cutout": {"label": "Remove the background", "engine": "Apple Vision", "adapter": "cutout", "gb": 1,
               "seconds": 3, "note": "Keeps the main subject on a transparent background.", "needs": "edit:cutout"},
    "faces": {"label": "Repair faces", "engine": "GFPGAN", "adapter": "faces", "gb": 4, "seconds": 8,
              "note": "For blurry or damaged faces. A face that is already sharp may come out smoother.",
              "needs": "edit:faces"},
}
EDIT_SCALES = [2, 3, 4]

# The video lane: one model (LTX-2.3, chosen by the measurements in STUDIO_PLAN.md), run by the
# engine's queue. Lengths and shapes offered are the ones that have run. Seconds and memory are
# measured; the engine replaces the first with its own once a clip has finished.
# What each one needs from this machine is listed once, in neovak_queue/lanes.py, shared with the doctor.
VIDEO_MODELS = {
    "ltx-2.5-q8": {"label": "Best clip", "engine": "LTX-2.5", "gb": 25,
                   "note": "Picture and sound together, with the most detail.",
                   "needs": ("video", "video:ltx-2.5-q8")},
    "ltx-2.3-q8": {"label": "Lighter on memory", "engine": "LTX-2.3", "gb": 19,
                   "note": "Picture and sound together. Uses less memory, and takes about as long.",
                   "needs": ("video", "video:ltx-2.3-q8")},
}
DEFAULT_VIDEO_MODEL = "ltx-2.5-q8"
VIDEO_ADAPTER = "ltx-video"
VIDEO_SECONDS = {2: 115, 5: 265, 8: 410}
VIDEO_SHAPES = {"landscape": "Landscape", "portrait": "Portrait", "square": "Square"}
VIDEO_TIMEOUT = 3 * 3600
MAX_WAITING = 12  # how many things may be lined up on the screen at once
MAX_BATCH = 8
WAIT_FOR_MEMORY = 1800  # a job behind others keeps asking the governor for this long, then fails plainly
ENGINE_GRACE = 900  # how long the screen keeps following a job after the engine stops answering

# The animation lane: templates over the show's motion engine. No model is loaded.
ANIMATION = {"label": "Animation", "engine": "NeoVak motion engine", "gb": 1,
             "note": "Words and pictures set in motion on this machine. Nothing is invented by a model."}
ANIM_TEMPLATES = {
    "title": {"label": "Title card", "note": "A title that rises in and settles.", "needs_words": True,
              "place": "The Long Way Home\nA film about staying", "hint": "First line is the title. The second line is smaller."},
    "move": {"label": "Slow move", "note": "A gentle move across a picture.", "needs_words": False,
             "place": "Optional words over the picture", "hint": "Choose a picture. Words are optional."},
    "strip": {"label": "Name strip", "note": "A name and role slide in at the bottom.", "needs_words": True,
              "place": "Ada Lovelace\nMathematician", "hint": "First line is the name. The second line is the role."},
    "lines": {"label": "One line at a time", "note": "Each line appears in turn.", "needs_words": True,
              "place": "First line\nSecond line\nThird line", "hint": "Each line of text gets its own moment."},
}
ANIM_LOOKS = {"night": "Night", "paper": "Paper", "studio": "Studio", "ember": "Ember"}
ANIM_FONTS = {"clean": "Clean", "tall": "Tall", "classic": "Classic"}
ANIM_SHAPES = {"landscape": "Landscape", "portrait": "Portrait", "square": "Square"}
ANIM_DIRECTIONS = {"in": "Move in", "out": "Move out", "left": "Drift left", "right": "Drift right"}
ANIM_MAX_WORDS = 600
ANIM_TIMEOUT = 1800

# The text lane: the two watch officers, through the engine's queue. No token limit is ever set.
WRITERS = {
    "9b": {"label": "Quick writer", "engine": "", "gb": 10, "governor": "9b",
           "note": "Good for most writing. Shared with other work on this machine.",
           "needs": "text:9b"},
    # The 27B ran through the queue for the first time on Nov 9 2026 (a one minute script, 4:13 end to end with 2:21 of that
    # waiting for memory), so it is offered; the memory check still decides each time, because it needs about 42 GB free.
    # "needs" names the settings key ([writers] careful): a machine with no address there has this row switched off.
    "27b": {"label": "Careful writer", "engine": "", "gb": 38, "governor": "27b",
            "note": "Writes more thoughtfully, and needs a lot of free memory. The first answer after a rest takes a few minutes.",
            "needs": "text:27b"},
}
DEFAULT_WRITER = "9b"
NOT_TESTED = "This writer has not been tested here yet, so it is switched off for now."
# Writers in LM Studio are named lms:<key>, with the key exactly as LM Studio lists it. The engine's text lane is the only
# source of those names and of each one's figure (a measured peak, or the size on disk plus 2 GB, marked as an estimate).
LMS_PREFIX = "lms:"
LMS_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/@-]{0,120}$")
LMS_CTX = 8192
LMS_SCRIPT_SECONDS, LMS_LOAD_SECONDS_PER_GB = 150, 8
_writers_cache = {"at": 0.0, "rows": None, "lmstudio": None}


def engine_writers(fresh=False):
    """The text lane's own list of writers, from the engine: the two officers with their measured or estimated figures and
    every language model LM Studio lists, with whether each is in memory now. Kept for 15 seconds. Returns (rows, lmstudio);
    rows is None when the engine did not answer, and lmstudio says whether LM Studio was running."""
    if not fresh and _writers_cache["rows"] is not None and time.time() - _writers_cache["at"] < 15:
        return _writers_cache["rows"], _writers_cache["lmstudio"]
    try:
        lane = (backend_get("/api/jobs/adapters", 6).get("adapters") or {}).get("local-text") or {}
        rows = [r for r in lane.get("models") or [] if isinstance(r, dict) and isinstance(r.get("model"), str)]
        _writers_cache.update(at=time.time(), rows=rows, lmstudio=lane.get("lmstudio") or {"running": False, "count": 0})
    except (urllib.error.URLError, OSError, TimeoutError, json.JSONDecodeError, AttributeError, KeyError):
        if _writers_cache["rows"] is None:
            return None, {"running": False, "count": 0}
    return _writers_cache["rows"], _writers_cache["lmstudio"]


def is_lms_writer(model):
    return isinstance(model, str) and model.startswith(LMS_PREFIX) and bool(LMS_KEY.match(model[len(LMS_PREFIX):]))


def writer_row(model):
    """The engine's row for one writer, or None."""
    rows, _ = engine_writers()
    return next((r for r in rows or [] if r["model"] == model), None)


def writer_label(model):
    if model in WRITERS:
        return WRITERS[model]["label"]
    row = writer_row(model) if is_lms_writer(model) else None
    return plain_writer_label(row["label"]) if row else (model[len(LMS_PREFIX):] if is_lms_writer(model) else None)


def writer_seconds(model, row=None):
    """A script by a writer in LM Studio, before any real run: the usual writing time plus the load, by size on disk."""
    row = row or writer_row(model) or {}
    load = 0 if row.get("loaded") else (row.get("disk_gb") or 0) * LMS_LOAD_SECONDS_PER_GB
    return round(LMS_SCRIPT_SECONDS + load)


TEXT_TASKS = {"script": "Script", "caption": "Captions", "rewrite": "Clearer words"}
TEXT_LENGTHS = {30: "30 seconds", 60: "1 minute", 120: "2 minutes", 300: "5 minutes"}
TEXT_TONES = {"plain": "Plain", "warm": "Warm", "serious": "Serious", "playful": "Playful"}
TEXT_TARGETS = {"image": "A picture", "video": "A video clip", "music": "Music", "voice": "Words to read aloud"}
TEXT_SECONDS = {"9b": 150, "27b": 440}  # a script; thinking is limited to 150 seconds on the 9B
TEXT_MAX = 6000
ENHANCE_LANES = ("image", "music", "video", "voice")


def needs_keys(spec):
    """The lanes.py keys a table row depends on: none, one, or several."""
    needs = spec.get("needs") or ()
    return (needs,) if isinstance(needs, str) else tuple(needs)


def has_needs(spec):
    """True when this machine has everything the row needs. The list itself lives in neovak_queue/lanes.py."""
    return all(_lanes.all_present(k, SETTINGS) for k in needs_keys(spec))


def why_off(spec):
    """The plain sentence for a row that is switched off because something is missing, or ''."""
    for k in needs_keys(spec):
        words = _lanes.why_off(k, SETTINGS)
        if words:
            return words
    return ""


# ------------------------------------------------------------------ memory checks
# One check for every load: neovak_queue/memory.py. It runs the governor the settings file names, or
# the built-in simple check when none is named. Either way it fails closed.
parse_preflight = _memory.parse_report
governor_args = _memory.preflight_args  # a number of GB, an officer name, or a dict {"gb", "lms", "ctx"} for a writer in LM Studio


def ask_governor(need):
    """need is a number of GB, an officer name, or a dict naming a model in LM Studio (see governor_args). Fails closed."""
    return _memory.preflight(need, timeout=30)


def memory_method():
    """'governor' or 'simple', and the sentence the Models page shows about it."""
    return {"method": _memory.method(SETTINGS), "words": _memory.method_words(SETTINGS)}


def no_go_message(check, what="this"):
    """Why a generation did not start, in plain words."""
    if not check.get("answered"):
        return ("The memory check did not answer, so nothing was started. "
                "Try again in a moment.")
    need, have, safety = check.get("need_gb"), check.get("available_gb"), check.get("safety_gb")
    if need is None or have is None:
        return f"This Mac does not have enough free memory for {what} right now, so nothing was started."
    total = need + (safety or 0)
    return (f"Not enough memory free for {what}. It needs about {total:.1f} GB in all ({need:.0f} GB for the model and "
            f"{safety:.0f} GB always kept in reserve), and {have:.1f} GB is free right now, which is {max(0.1, total - have):.1f} GB short. "
            f"Nothing was started.")


LIVE_GB, SOURCE_GB = 4, 6  # what Watch it arrive and a starting picture ask the governor for on top of the model
IMAGE_LADDER = ("z-image-turbo", "flux2-klein-4b", "z-image", "schnell")  # best first, for this machine


def alternatives(lane, params, check):
    """What would run right now, when the thing asked for will not. Only what the memory figures say fits."""
    have, safety = check.get("available_gb"), check.get("safety_gb")
    if have is None or safety is None:
        return []
    room, models = have - safety, RECORDS.backend("models")
    out = []
    if lane == "image":
        spec = IMAGE_MODELS[params["model"]]
        extra = SOURCE_GB if params.get("source") else 0
        if params.get("live") and spec["gb"] <= room:
            out.append({"kind": "live_off", "label": spec["label"], "gb": spec["gb"]})
        # closest in time to the one asked for first, so Quick gives way to Fast draft rather than to Careful
        wanted = spec.get("seconds") or 60
        for key in sorted(IMAGE_LADDER, key=lambda k: (abs(math.log((IMAGE_MODELS[k].get("seconds") or 60) / wanted)), IMAGE_MODELS[k].get("seconds") or 60)):
            s = IMAGE_MODELS[key]
            if key != params["model"] and s["routed"] and s["gb"] + extra <= room and downloaded(s["repo"], models) is not False:
                out.append({"kind": "model", "id": key, "label": s["label"], "gb": s["gb"] + extra, "field": "model"})
    elif lane == "video":
        out = [{"kind": "model", "id": k, "label": s["label"], "gb": s["gb"], "field": "videoModel"} for k, s in VIDEO_MODELS.items()
               if k != params["model"] and s["gb"] <= room and has_needs(s)]
    elif lane == "voice":
        out = [{"kind": "model", "id": k, "label": s["label"], "gb": s["gb"], "field": "voice"} for k, s in VOICES.items()
               if k != params["voice"] and s["gb"] <= room and has_needs(s)]
    elif lane == "text":
        rows, _ = engine_writers()
        out = [{"kind": "model", "id": r["model"], "label": r["label"], "gb": 0 if r.get("loaded") else r["gb"], "field": "writer"} for r in rows or []
               if r["model"] != params["model"] and (r["model"] not in WRITERS or has_needs(WRITERS[r["model"]]))
               and (r.get("loaded") or (r.get("gb") is not None and r["gb"] <= room))]
    return out[:3]


class MemoryReader:
    """One shared reading, refreshed at most every eight seconds."""

    def __init__(self, ttl=8.0):
        self.ttl, self.at, self.value = ttl, 0.0, None
        self.lock = threading.Lock()

    def read(self, ttl=None):
        """The shared reading, read again when it is older than ttl seconds (the reader's own when None). Every page
        of every person shows this one reading, so two pages looking at the same moment cannot disagree by more than
        the age of the reading; while work runs it is read every few seconds, because a model loading moves it fast."""
        with self.lock:
            if self.value is None or time.time() - self.at > (self.ttl if ttl is None else ttl):
                self.value, self.at = ask_governor(1), time.time()
            return self.value


MEMORY = MemoryReader()


def badge_for(gb, reading):
    """Green, yellow, orange or red, from the live reading. Red means the check would refuse."""
    have, safety = (reading or {}).get("available_gb"), (reading or {}).get("safety_gb")
    if (reading or {}).get("wait"):
        return {"badge": "unknown", "fits": True, "text": "Other work is running. This will be checked when its turn comes."}
    if have is None or safety is None:
        return {"badge": "unknown", "fits": False, "text": "Memory check is not answering"}
    margin = have - gb
    # While work is running the figure is the last one read when nothing was, so it is not the header's figure and says so.
    free = (f"{have:.1f} GB will be free once the work running now is done (it was the last time nothing ran)" if reading.get("quiet")
            else f"{have:.1f} GB is free")
    if margin < safety:
        return {"badge": "red", "fits": False,
                "text": f"Not enough memory free. This needs about {gb + safety:.0f} GB in all ({gb} GB for the model and {safety:.0f} GB always kept in reserve), "
                        f"and {free}. Closing a large app, or waiting for other work to finish, may free enough.",
                "short": f"Will not fit right now: about {gb + safety:.0f} GB needed with the reserve, "
                         + (f"{have:.1f} GB free when nothing else runs." if reading.get("quiet") else f"{have:.1f} GB free.")}
    if margin < safety + 4:
        return {"badge": "orange", "fits": True, "text": f"Tight fit. {free}."}
    if margin < safety + 10:
        return {"badge": "yellow", "fits": True, "text": f"Should fit. {free}."}
    return {"badge": "green", "fits": True, "text": f"Plenty of room. {free}."}


# ------------------------------------------------------------------ the nightly hold
_window = SETTINGS.hold_window()
CENTRAL = _window[2] if _window else ZoneInfo("America/Chicago")


def hold_status(now=None, estimate_seconds=0):
    """A daily window from the settings file when no model may load. Work that would run into it
    waits too. A machine with no window in its settings never pauses."""
    state = SETTINGS.hold_state(estimate_seconds, now)
    if state == "inside":
        # Animations and films load no model, so they are made during the hold; the words say so instead of
        # telling a first-time reader that nothing can be made.
        return {"active": True, "message": (f"Until {SETTINGS.hold_end_words()}, pictures, clips, voices, music and writing wait: "
                                            f"a nightly job needs this Mac's memory from {SETTINGS.hold_words()}. "
                                            "Animations and films can still be made, because they load no model."),
                "short": f"This waits until {SETTINGS.hold_end_words()} for a nightly job. Animations and films can still be made now.",
                "band": f"Pictures, clips, voices, music and writing wait until {SETTINGS.hold_end_words()} for a nightly job. Animations and films can still be made."}
    if state == "ahead":
        return {"active": True, "message": (f"This would still be running at {SETTINGS.hold_start_words()}, when a "
                                            f"nightly job needs this Mac's memory. Please try again "
                                            f"after {SETTINGS.hold_end_words()}.")}
    return {"active": False, "message": ""}


# ------------------------------------------------------------------ serving files
def safe_media_path(rel):
    """The file inside the output folder that rel names, or None. Symlinks are resolved first,
    so a link that points outside the folder is refused like any other escape."""
    if not isinstance(rel, str) or not rel or "\x00" in rel or "\\" in rel:
        return None
    if rel.startswith("/") or ".." in Path(rel).parts or too_long_name(rel):
        return None
    try:
        root = OUTPUT_DIR.resolve()
        target = (root / rel).resolve()
        target.relative_to(root)
        # is_file() touches the disk too, and a name the file system cannot hold raises there (File name too long)
        if target.suffix.lower() not in MEDIA_SUFFIXES or not target.is_file():
            return None
    except (ValueError, OSError, RuntimeError):
        return None
    if target.suffix.lower() in TEXT_SUFFIXES and not target.name.startswith(TEXT_PREFIX):
        return None
    return target


def too_long_name(rel):
    """True when any part of the name is longer than the file system allows (255 bytes), so it is refused
    before the disk is asked and answers 404 like any other name that is not there."""
    return len(rel.encode("utf-8", "surrogatepass")) > 1024 or any(len(part.encode("utf-8", "surrogatepass")) > 255 for part in Path(rel).parts)


# ------------------------------------------------------------------ the screen's own records
class Records:
    """state/records.json: what this screen knows about each file, keyed by file name."""

    def __init__(self, path=None):
        self.path = Path(path or STATE_DIR / "records.json")
        self.lock = threading.Lock()
        self.data = {"items": {}, "backend": {}}
        try:
            self.data.update(json.loads(self.path.read_text()))
        except (OSError, json.JSONDecodeError):
            pass

    def _save(self):
        tmp = self.path.with_name(f".{self.path.name}.{os.getpid()}.tmp")
        tmp.write_text(json.dumps(self.data, indent=1))
        os.replace(tmp, self.path)

    def get(self, name):
        with self.lock:
            return dict(self.data["items"].get(name, {}))

    def update(self, name, **fields):
        with self.lock:
            self.data["items"].setdefault(name, {}).update(fields)
            self._save()

    def set_backend(self, key, value):
        with self.lock:
            self.data["backend"][key] = value
            self._save()

    def backend(self, key):
        with self.lock:
            return self.data["backend"].get(key)

    def recent_seconds(self, key):
        with self.lock:
            return [r["elapsed"] for r in self.data["items"].values()
                    if r.get("estimate_key") == key and r.get("elapsed")][-5:]

    def recent_seconds_like(self, prefix):
        """The last few real runs whose estimate key starts with prefix, whatever their size or steps."""
        with self.lock:
            return [r["elapsed"] for r in self.data["items"].values()
                    if str(r.get("estimate_key", "")).startswith(prefix) and r.get("elapsed")][-5:]

    def hidden(self):
        """The files a person has hidden from the gallery. The files themselves are never touched."""
        with self.lock:
            return {name for name, r in self.data["items"].items() if r.get("hidden")}


RECORDS = Records()


# ------------------------------------------------------------------ the gallery
_NAME_RE = re.compile(r"neovak(?:_klein|_edit|_cutout|_faces|_video|_anim|_text|_upload|_speech|_music|_lora_[a-z]+|_upscaled)?_(\d{8})_(\d{6})"
                      r"(?:_(\d+))?(?:_j[0-9a-f]{6})?\.")
_exif_cache = {}


def read_file_metadata(path):
    """The settings mflux writes inside each picture, if any. Reads only; never writes."""
    key = (path.name, path.stat().st_mtime)
    if key in _exif_cache:
        return _exif_cache[key]
    meta = {}
    if path.suffix.lower() in IMAGE_SUFFIXES:
        try:
            from PIL import Image
            with Image.open(path) as im:
                raw = im.info.get("exif") or b""
                meta["width"], meta["height"] = im.size
            at = raw.find(b"ASCII\x00\x00\x00{")
            if at >= 0:
                text = raw[at + 8:].decode("utf-8", "ignore")
                found, _ = json.JSONDecoder().raw_decode(text)
                meta.update({k: found.get(k) for k in ("prompt", "seed", "steps", "model",
                                                       "generation_time_seconds")})
        except Exception:
            pass
    _exif_cache[key] = meta
    return meta


def size_name_for(width, height, sizes):
    wanted = f"{width}x{height}"
    for name, value in (sizes or {}).items():
        if value == wanted:
            return name
    return None


_ENGINE_NAMES = {"apple-vision": "Remove the background", "gfpgan": "Repair faces", "seedvr2": "Make it bigger", "kontext": "Change something",
                 "motion": "Animation", "timeline": "Film", "minimax": "Music"}


def engine_label(model):
    """The name the screen uses for whatever a file's records call its model, or None. Never an engine's own name."""
    if not model:
        return None
    def norm(name):
        return str(name).lower().replace("_", "-").replace(" ", "-")
    text = norm(model)
    if "klein" in text:
        return "Quick"
    if is_lms_writer(str(model)):
        return writer_label(str(model))
    tables = (EDIT_TOOLS, IMAGE_MODELS, VOICES, VIDEO_MODELS, WRITERS, {"music": MUSIC})
    specs = [(key, spec) for table in tables for key, spec in table.items()]
    for key, spec in specs:  # a whole name first, so that one name that contains another is not mistaken for it
        if text in (norm(key), norm(spec.get("engine", "")), norm(spec.get("repo", "")), norm(spec.get("repo", "")).split("/")[-1]):
            return spec["label"]
    for key, spec in specs:
        if any(n and n in text for n in (norm(spec.get("engine", "")), norm(spec.get("repo", "")))):
            return spec["label"]
    return next((label for key, label in _ENGINE_NAMES.items() if key in text), None)


_FILE_NAME_IN_WORDS = re.compile(r"\s*:?\s*neovak[\w.-]*\.(?:png|jpe?g|webp|wav|mp3|m4a|mp4|txt)\s*$", re.I)


def plain_words(text):
    """The words a file was made from, without a file name stuck on the end."""
    if not isinstance(text, str):
        return None
    return _FILE_NAME_IN_WORDS.sub("", text).strip() or None


def shorten(text, limit):
    """The first words of text, cut at a word and marked with three dots, never in the middle of a word.
    Line breaks are kept (a title card's two lines stay two lines); runs of other spaces close up."""
    text = "\n".join(" ".join(ln.split()) for ln in str(text or "").split("\n") if ln.strip())
    if len(text) <= limit:
        return text
    cut = text[:limit]
    if " " in cut:
        cut = cut[:cut.rfind(" ")]
    return cut.rstrip(" ,;:") + "..."


def caption_for(prompt, kind, name):
    if prompt:
        return prompt
    if name.startswith("neovak_upload_"):
        return {"image": "A picture", "video": "A clip"}.get(kind, "A sound") + " added from this computer"
    return {"image": "A picture", "video": "A clip", "text": "Some writing"}.get(kind, "A sound")


_STAGES = {"generating": "Working", "running": "Working", "working": "Working", "starting": "Starting", "queued": "Waiting for its turn",
           "checking memory": "Checking there is enough memory", "waiting for memory": "Waiting for memory to free up",
           "loading model": "Getting the model ready", "cancelling": "Stopping", "cancelled": "Stopped", "failed": "Stopped", "done": "Finished"}


def plain_stage(stage):
    """What the engine says it is doing, as a person would say it."""
    if not stage:
        return None
    return _STAGES.get(stage) or stage[0].upper() + stage[1:]


def describe_file(entry, sizes=None):
    """One gallery item: this screen's record first, then the file's metadata, then its name."""
    path = Path(entry.path)
    stat = entry.stat()
    rec = RECORDS.get(path.name)
    meta = read_file_metadata(path)
    side = provenance.read(OUTPUT_DIR, path.name) or {}
    named = _NAME_RE.match(path.name)
    seed = rec.get("seed", meta.get("seed", side.get("seed")))
    made = rec.get("created")
    if seed is None and named and named.group(3):
        seed = int(named.group(3))
    if not made and named:
        try:
            made = datetime.strptime(named.group(1) + named.group(2), "%Y%m%d%H%M%S").isoformat()
        except ValueError:
            pass
    if not made:
        made = datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds")
    suffix = path.suffix.lower()
    kind = "image" if suffix in IMAGE_SUFFIXES else "video" if suffix in VIDEO_SUFFIXES else "text" if suffix in TEXT_SUFFIXES else "audio"
    lane = rec.get("lane") or ("recipe" if (side.get("recipe") and side["recipe"].get("step") == "joined") else None) or ("animation" if "_anim_" in path.name else kind if kind in ("image", "video", "text") else
                               "music" if "music" in path.name else "voice")
    excerpt = None
    if kind == "text":
        try:
            excerpt = path.read_text(encoding="utf-8", errors="replace")[:220]
        except OSError:
            pass
    size = rec.get("size") or size_name_for(meta.get("width"), meta.get("height"), sizes)
    words = plain_words(rec.get("prompt") or meta.get("prompt") or side.get("prompt") or (side.get("recipe") or {}).get("name"))
    seconds = rec.get("seconds")
    if seconds is None and kind == "video":
        seconds = clip_seconds(path)  # how long a clip runs, read once and kept, so the result line can say it like a recording's does
    elif seconds is None and kind == "audio" and lane != "music":
        seconds = sound_seconds(path)  # a voice recording says how long it is, as music and clips do
    caption = caption_for(words, kind, path.name)
    tool = rec.get("model_label") if lane == "edit" else None
    if tool and words and not words.startswith(tool + ":"):
        # every edit is captioned the same way, its tool first and then its words: "Change something: Make the boat blue"
        # reads like "Make it bigger: A red rowing boat", and the words themselves (kept in prompt) are not changed
        caption = f"{tool}: {words[:1].upper()}{words[1:]}"
    return {
        "name": path.name, "kind": kind, "lane": lane, "url": f"/media/{path.name}",
        "thumb": f"/thumb/{path.name}" if kind in ("image", "video") else None,
        "prompt": words, "caption": caption, "seed": seed, "seconds": seconds,
        "model": plain_maker(engine_label(rec.get("model_label")) or rec.get("model_label") or engine_label(meta.get("model")) or side_model(side), kind),
        "time": made, "favorite": bool(rec.get("favorite")), "hidden": bool(rec.get("hidden")),
        "elapsed": rec.get("elapsed") or side.get("seconds") or meta.get("generation_time_seconds"),
        "parent": rec.get("parent"), "remade": bool(rec.get("remade")), "excerpt": excerpt, "how": how_made(side, rec), "batch": rec.get("batch"),
        "dimensions": rec.get("dimensions") or (f"{meta['width']} by {meta['height']}"
                                                if meta.get("width") else None),
        "settings": {"model": rec.get("model"), "size": size, "style": rec.get("style", "none"),
                     "steps": rec.get("steps") or meta.get("steps"), "voice": rec.get("voice"),
                     "duration": rec.get("duration")},
    }


def plain_maker(label, kind):
    """What made a file, in the words the default screens use: the writer's own plain name (Quick writer, Gemma 4 E2B),
    the same name the person chose it by in the writer list and saw on the chip, and never the other app that keeps it."""
    if kind == "text" and label and label not in {w["label"] for w in WRITERS.values()} and " " not in label.strip():
        # a writer LM Studio no longer lists is known only by its file key (lms:gemma-4-e2b-it-qat): made readable
        words = re.sub(r"^lms:", "", label).replace("_", " ").replace("-", " ").split()
        return plain_writer_label(" ".join(w.upper() if _SIZE_TOKEN.match(w) else w[:1].upper() + w[1:] for w in words))
    return label


_clip_seconds_cache = {}


def clip_seconds(path):
    """How long a clip runs, from ffprobe, read once per file and kept in this process. None when it cannot be read."""
    try:
        key = (path.name, path.stat().st_mtime)
    except OSError:
        return None
    if key not in _clip_seconds_cache:
        seconds = None
        try:
            r = subprocess.run([SETTINGS.tool("ffprobe"), "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)],
                               capture_output=True, text=True, timeout=20)
            seconds = float(json.loads(r.stdout or "{}").get("format", {}).get("duration") or 0) or None
        except (OSError, ValueError, subprocess.TimeoutExpired):
            seconds = None
        if seconds:
            seconds = round(seconds, 2)
        _clip_seconds_cache[key] = seconds
        if len(_clip_seconds_cache) > 2000:
            _clip_seconds_cache.pop(next(iter(_clip_seconds_cache)))
    return _clip_seconds_cache[key]


def side_model(side):
    """A plain name for what made a file, from its sidecar. None when there is no sidecar."""
    if not side:
        return None
    model, adapter = side.get("model"), side.get("adapter")
    if model in VOICES:
        return VOICES[model]["label"]
    if adapter == "join-sound":
        return (side.get("recipe") or {}).get("name") or "Picture and voice joined"
    if adapter == "motion":
        return "Animation"
    return engine_label(side.get("model_name")) or engine_label(model)


def how_made(side, rec):
    """The sidecar in the words the page shows, or None when a file has none."""
    if not side:
        return None
    chain = [{"label": c.get("label"), "name": c.get("file"), "thumb": _thumb_url(c.get("file"))} for c in side.get("chain") or []]
    # A recipe's joined file took the whole recipe, not the half second of its last step.
    seconds = rec.get("elapsed") if rec.get("lane") == "recipe" and rec.get("elapsed") else side.get("seconds")
    return {"made": side.get("made"), "seconds": seconds, "model": side_model(side),
            "model_in_file": side.get("model_in_file"), "prompt": side.get("prompt"), "prompt_as_sent": side.get("prompt_as_sent"),
            "seed": side.get("seed"), "settings": side.get("settings") or {}, "sources": [named_source(s) for s in side.get("sources") or [] if isinstance(s, dict)],
            "recipe": (side.get("recipe") or {}).get("name"), "step": (side.get("recipe") or {}).get("step_label"), "chain": chain,
            "can_remake": bool((side.get("remake") or {}).get("adapter")) and rec.get("lane") != "recipe"}


def named_source(source):
    """One file a piece was made from, with what How this was made needs to name it: the file's name in the output
    folder, its small picture and the words it was made from, when it is still there. A file that has gone keeps only
    what the record says."""
    out = dict(source)
    name = Path(str(source.get("file") or "")).name
    if name and safe_media_path(name):
        rec = RECORDS.get(name)
        words = plain_words(rec.get("prompt") or (provenance.read(OUTPUT_DIR, name) or {}).get("prompt"))
        out.update(name=name, thumb=_thumb_url(name), caption=shorten(words, 90) if words else None)
    return out


def _thumb_url(name):
    return f"/thumb/{name}" if isinstance(name, str) and Path(name).suffix.lower() in IMAGE_SUFFIXES | VIDEO_SUFFIXES else None


def scan_output():
    keep = []
    with os.scandir(OUTPUT_DIR) as it:
        for entry in it:
            low = entry.name.lower()
            if entry.name.startswith(".") or not entry.is_file(follow_symlinks=False):
                continue
            if Path(low).suffix not in MEDIA_SUFFIXES or "_thumb." in low or "_mask." in low:
                continue
            if Path(low).suffix in TEXT_SUFFIXES and not low.startswith(TEXT_PREFIX):
                continue
            keep.append(entry)
    keep.sort(key=lambda e: e.stat().st_mtime, reverse=True)
    return keep


def _matches_kind(name, kind):
    suffix = Path(name).suffix.lower()
    return {"image": suffix in IMAGE_SUFFIXES, "video": suffix in VIDEO_SUFFIXES, "text": suffix in TEXT_SUFFIXES,
            "sound": suffix in {".wav", ".mp3", ".m4a"}}.get(kind, True)


def gallery(offset=0, limit=48, favorites_only=False, sizes=None, names=None, kind=None, text=None, hidden=False):
    """names, when given, keeps only those files (a project's). text matches the words a file was made from.
    Hidden files are left out unless hidden is True, in which case only they are shown, so they can be brought back."""
    entries = scan_output()
    if names is not None:
        wanted = set(names)
        entries = [e for e in entries if e.name in wanted]
    away = RECORDS.hidden()
    entries = [e for e in entries if (e.name in away) == bool(hidden)]
    if favorites_only:
        entries = [e for e in entries if RECORDS.get(e.name).get("favorite")]
    if kind:
        entries = [e for e in entries if _matches_kind(e.name, kind)]
    if text:
        needle = text.lower()
        entries = [e for e in entries if needle in (describe_file(e, sizes).get("prompt") or "").lower() or needle in e.name.lower()]
    page = entries[offset:offset + limit]
    return {"total": len(entries), "offset": offset, "limit": limit,
            "items": [describe_file(e, sizes) for e in page]}


def describe_name(name, sizes=None):
    path = safe_media_path(name)
    if path is None or path.parent != OUTPUT_DIR.resolve():
        return None
    with os.scandir(OUTPUT_DIR) as it:
        for entry in it:
            if entry.name == name:
                return describe_file(entry, sizes)
    return None


def thumbnail_for(path, max_side=520):
    """A small JPEG in this screen's own state folder. The output folder is never written."""
    stat = path.stat()
    tag = ":board" if path.suffix.lower() == ".png" else ""  # the checkerboard under a cut-out is new; older PNG thumbnails are drawn again
    target = STATE_DIR / "thumbs" / f"{uuid.uuid5(uuid.NAMESPACE_URL, f'{path}:{stat.st_mtime}{tag}').hex}.jpg"
    if not target.exists() and path.suffix.lower() in VIDEO_SUFFIXES:
        # One frame, read by ffmpeg with an argument list; nothing here is shell text.
        cut = target.with_suffix(".frame.jpg")
        done = subprocess.run([SETTINGS.tool("ffmpeg"), "-nostdin", "-y", "-ss", "0.5", "-i", str(path), "-frames:v",
                               "1", "-vf", f"scale='min({max_side},iw)':-2", "-q:v", "4", str(cut)],
                              capture_output=True, timeout=60)
        if done.returncode != 0 or not cut.exists():
            raise OSError("no frame could be read from the clip")
        cut.rename(target)
    elif not target.exists():
        from PIL import Image
        with Image.open(path) as im:
            im.thumbnail((max_side, max_side))
            if "A" in im.getbands() and im.getchannel("A").getextrema()[0] < 255:
                # A picture with see-through parts (a cut-out) sits on a checkerboard, as it does on the stage, so the
                # missing background reads as missing and not as a black picture.
                im = im.convert("RGBA")
                board = Image.new("RGB", im.size, (138, 141, 148))
                light, cell = (201, 204, 210), 22
                for y in range(0, im.height, cell):
                    for x in range(0, im.width, cell):
                        if (x // cell + y // cell) % 2:
                            board.paste(light, (x, y, min(x + cell, im.width), min(y + cell, im.height)))
                board.paste(im, (0, 0), im)
                im = board
            im.convert("RGB").save(target, "JPEG", quality=82)
    return target


# ------------------------------------------------------------------ backend and processes
_busy_cache = {"at": 0.0, "value": False, "last_true": 0.0}


def queue_state():
    """{"now": something is running or waiting on the engine's queue, from this screen or any other tool;
    "recent": that was so within the last 40 seconds; "idle_for": seconds since it last was; "starved": the engine's
    running job is held at the memory check, so nothing it runs holds memory that will come back when it ends, and the
    free figure as it is now is the one that counts}."""
    now = time.time()
    if now - _busy_cache["at"] > 4:
        try:
            jobs = backend_get("/api/jobs?limit=8", 3).get("jobs", [])
            _busy_cache["value"] = any(j.get("state") in ("running", "queued") for j in jobs)
            running = [j for j in jobs if j.get("state") == "running"]
            _busy_cache["running"] = len(running)
            _busy_cache["starved"] = bool(running) and all((j.get("progress") or {}).get("stage") == "waiting for memory" for j in running)
        except (urllib.error.URLError, OSError, TimeoutError, ValueError):
            _busy_cache["value"], _busy_cache["starved"] = False, False
        _busy_cache["at"] = now
        if _busy_cache["value"]:
            _busy_cache["last_true"] = now
    # Starved too when the engine runs nothing at all while a recipe of this screen holds a step back for memory.
    starved = bool(_busy_cache.get("starved")) or (not _busy_cache.get("running") and any(is_held(j) for j in GENERATION.active()))
    if GENERATION.active():
        _busy_cache["last_true"] = now
        return {"now": True, "recent": True, "idle_for": 0.0, "starved": starved}
    idle_for = 0.0 if _busy_cache["value"] else now - _busy_cache["last_true"]
    return {"now": _busy_cache["value"], "recent": _busy_cache["value"] or idle_for < 40, "idle_for": idle_for, "starved": starved}


def is_held(job):
    """True while this screen's job, or the working step of its recipe, waits at the memory check: nothing is being made."""
    return job.get("state") == "running" and (str(job.get("stage") or "").lower().startswith("waiting for memory") or any(
        (s.get("state") in ("running", "waiting") and "memory" in f"{s.get('stage') or ''} {s.get('waiting') or ''}".lower())
        # the moment between a refused try and the next: the step's job has ended, and the recipe tries it again
        or (s.get("state") == "running" and s.get("stage") == "Stopped" and job.get("held_since"))
        for s in job.get("steps") or []))


def queue_busy():
    """Is the engine's queue running or holding anything, or has it just finished? Memory takes a little while to come
    back after a job ends, so a just-finished queue still counts here (the presses use this: the queue asks the memory
    check itself before each job it runs)."""
    return queue_state()["recent"]


def backend_request(route, body=None, method=None):
    """A request to the engine, carrying its access token when one is set. Every call goes through here."""
    data = json.dumps(body).encode() if body is not None else None
    headers = dict(secret.auth_headers(), **({"Content-Type": "application/json"} if data is not None else {}))
    return urllib.request.Request(BACKEND + route, data=data, headers=headers, method=method or ("POST" if data is not None else "GET"))


def backend_get(route, timeout=4.0):
    with urllib.request.urlopen(backend_request(route), timeout=timeout) as r:
        return json.loads(r.read().decode())


def backend_post(route, body, timeout):
    with urllib.request.urlopen(backend_request(route, body), timeout=timeout) as r:
        return json.loads(r.read().decode())


def run_process(cmd, env, timeout, log_path):
    """Run one engine in its own process group. Returns (exit code, timed out). On a timeout the
    whole group is stopped, and nothing outside that group is touched."""
    with open(log_path, "w") as log:
        proc = subprocess.Popen(cmd, env=env, stdout=log, stderr=subprocess.STDOUT,
                                stdin=subprocess.DEVNULL, start_new_session=True, cwd=str(STATE_DIR))
    try:
        return proc.wait(timeout=timeout), False
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
            try:
                proc.wait(timeout=6)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait(timeout=6)
        except ProcessLookupError:
            pass
        return None, True


def engine_env():
    env = os.environ.copy()
    env["HF_HOME"] = HF_HOME
    # Every weight these lanes use is already on disk. Staying offline avoids the stall on a
    # dead connection recorded in S1_PARITY_2026-10-28.md section 8.
    env["HF_HUB_OFFLINE"] = "1"
    return env


def new_output_name(prefix, job_id, suffix):
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{prefix}_{stamp}_{job_id[-6:]}{suffix}"


def log_tail(path, chars=1500):
    try:
        return Path(path).read_text(errors="ignore")[-chars:]
    except OSError:
        return ""


def clean_prompt(text):
    """Trim, and drop leading dashes: an engine would read those as one of its own options."""
    return scrub(text).strip().lstrip("- ").strip() if isinstance(text, str) else ""


def adapter_call(lane, p):
    """(adapter, params) as the engine's queue is asked for this lane's settings: one place, so the runner that
    starts a job and the estimate shown before the press describe exactly the same job. None for a lane that
    does not go to one adapter this way (recipes, make it again)."""
    if lane == "image":
        params = {"prompt": p["prompt"], "style": "" if p["style"] == "none" else p["style"], "size": p["size"], "model": p["model"],
                  "steps": p["steps"], "seed": p["seed"], "live": bool(p.get("live"))}
        if p.get("source"):
            params.update(source=p["source"], strength=p["strength"])
        return "mflux", params
    if lane == "voice":
        return "mlx-audio", {"text": p["text"], "voice": p["voice"], "speed": p.get("speed", 1.0), "description": p.get("description", "")}
    if lane == "music":
        return "minimax-music", {"prompt": p["prompt"], "duration": p["duration"], "genre": "", "lyrics": p.get("lyrics") or "[instrumental]", "seed": p["seed"]}
    if lane == "edit":
        spec = EDIT_TOOLS[p["tool"]]
        params = {"source": p["source"]}
        if spec["adapter"] == "kontext":
            params.update(prompt=p["prompt"], seed=p["seed"])
        elif spec["adapter"] == "seedvr2":
            params.update(scale=p["scale"], seed=p["seed"])
        return spec["adapter"], params
    if lane == "video":
        params = {"prompt": p["prompt"], "seconds": p["duration"], "size": p["size"], "seed": p["seed"], "model": p["model"]}
        if p.get("source"):
            params["source"] = p["source"]
        return VIDEO_ADAPTER, params
    if lane == "animation":
        return "motion", animation_params(p)
    if lane == "text":
        return "local-text", {"task": p["task"], "brief": p["prompt"], "model": p["model"], "length": p["length"], "tone": p["tone"],
                              "target": p["target"], "about": p["about"]}
    if lane == "film":
        return "timeline", {"clips": p["clips"], "sounds": p["sounds"], "shape": p["shape"], "keep_clip_sound": True, "prompt": p["prompt"]}
    return None


_estimate_cache = {}


def engine_estimate(adapter, params):
    """The engine's own figure for a job with these settings (its history for them, else its measured table), or None
    when it does not answer. The same figure the job will show once it is on the queue, so the chip before the press,
    the row in the panel and the working screen cannot come from different places. Kept for ten seconds per setting."""
    key = json.dumps([adapter, params], sort_keys=True, default=str)
    hit = _estimate_cache.get(key)
    if hit and time.time() - hit[0] < 10:
        return hit[1]
    try:
        view = backend_post("/api/jobs/estimate", {"adapter": adapter, "params": params}, 4)
        seconds = view.get("estimate_seconds")
        seconds = float(seconds) if isinstance(seconds, (int, float)) and seconds > 0 else None
    except (urllib.error.URLError, OSError, TimeoutError, json.JSONDecodeError, ValueError, AttributeError):
        seconds = None
    if len(_estimate_cache) > 400:
        _estimate_cache.clear()
    _estimate_cache[key] = (time.time(), seconds)
    return seconds


def estimate_for(lane, params):
    if lane == "recipe":
        return params["estimate"]
    if lane == "remake":
        return params.get("seconds") or 60
    call = adapter_call(lane, params)
    if call:
        seconds = engine_estimate(*call)
        if seconds:
            return round(seconds, 1)
    if lane == "film":
        return 5 + params["total"] * 0.6
    key = estimate_key(lane, params)
    runs = RECORDS.recent_seconds(key)
    if runs:
        return round(statistics.median(runs), 1)
    if lane == "image":
        spec = IMAGE_MODELS[params["model"]]
        extra = max(0, params["steps"] - spec["steps"]) * 7
        return spec["seconds"] + extra
    if lane == "voice":
        return VOICES[params["voice"]]["seconds"]
    if lane == "edit":
        if params["tool"] == "bigger":
            return {2: 80, 3: 170, 4: 300}.get(params.get("scale"), 80)
        return EDIT_TOOLS[params["tool"]]["seconds"]
    if lane == "video":
        return VIDEO_SECONDS[params["duration"]]
    if lane == "animation":
        return 8 + params["seconds"] * 9
    if lane == "text":
        row = writer_row(params["model"]) if params["model"] not in WRITERS else None
        load = 0 if row is None or row.get("loaded") else (row.get("disk_gb") or 0) * LMS_LOAD_SECONDS_PER_GB  # a writer in LM Studio may need loading first
        if params["task"] != "script":
            return round(12 + load)  # rewrites and captions are written without the model's private thinking
        base = TEXT_SECONDS.get(params["model"]) or LMS_SCRIPT_SECONDS
        return round(base * {30: 0.8, 60: 1.0, 120: 1.4, 300: 2.5}.get(params["length"], 1) + load)
    return 30 + params["duration"] * 8


def _loose_int(value, low, high, default):
    try:
        n = int(float(value))
    except (TypeError, ValueError, OverflowError):
        return default
    return n if low <= n <= high else default


def estimate_options(lane, body):
    """The time figures the page shows before a press, for the settings as they stand: one figure for each choice in
    the lane's list (every picture model at the chosen shape and steps, every voice for these words, both clip models at
    this length, every writer for this kind of writing), plus the figure for the choice made, each from estimate_for,
    which is what the working screen will show once the job is on the queue. Nothing here refuses: a setting that is
    not understood falls back to its default, because this only sizes the work, it does not start it."""
    b = body if isinstance(body, dict) else {}
    out = {"lane": lane, "options": {}, "alt": {}, "chosen": None, "count": 1}
    words = clean_prompt(b.get("prompt")) or "x"
    if lane == "image":
        size = b.get("size") if b.get("size") in sizes_available() else "landscape"
        steps = _loose_int(b.get("steps"), 1, 50, None)
        source = b.get("source") if isinstance(b.get("source"), str) and b.get("source") else None
        for k, spec in IMAGE_MODELS.items():
            if not spec["routed"]:
                continue
            params = {"prompt": words, "style": "none", "size": size, "model": k, "steps": steps or spec["steps"], "seed": 1,
                      "live": bool(spec.get("live")) and b.get("live") is not False and not source}
            if source:
                params.update(source=source, strength=0.5)
            out["options"][k] = estimate_for("image", params)
            # the same model without watching it arrive: what it takes when watching does not fit and is turned off
            out.setdefault("plain", {})[k] = estimate_for("image", dict(params, live=False)) if params["live"] else out["options"][k]
        out["count"] = _loose_int(b.get("count"), 1, MAX_BATCH, 1)
        out["chosen"] = out["options"].get(b.get("model") or DEFAULT_IMAGE_MODEL)
    elif lane == "voice":
        for k in VOICES:
            out["options"][k] = estimate_for("voice", {"text": words, "voice": k, "speed": 1.0, "description": ""})
        out["chosen"] = out["options"].get(b.get("voice") or DEFAULT_VOICE)
    elif lane == "music":
        duration = _loose_int(b.get("duration"), 5, 180, 30)
        for d in MUSIC_LENGTHS:
            out["alt"][str(d)] = estimate_for("music", {"prompt": words, "duration": d, "seed": -1, "lyrics": "[instrumental]"})
        out["options"]["music"] = out["chosen"] = estimate_for("music", {"prompt": words, "duration": duration, "seed": -1, "lyrics": "[instrumental]"})
        # Music runs vary a lot here (a 15 second piece has taken from 2:03 to 2:53). When recent runs went well past the
        # usual figure, the page is given the longest of them too, and promises a range instead of a time it often misses.
        runs = RECORDS.recent_seconds(f"music-full:{duration}")
        if out["chosen"] and len(runs) >= 2 and max(runs) > out["chosen"] * 1.15:
            out["upto"] = round(max(runs), 1)
    elif lane == "edit":
        source = b.get("source") if isinstance(b.get("source"), str) and b.get("source") else "x.png"
        scale = _loose_int(b.get("scale"), 2, 4, 2)
        for k in EDIT_TOOLS:
            out["options"][k] = estimate_for("edit", {"tool": k, "source": source, "prompt": words, "seed": 1, "scale": scale if scale in EDIT_SCALES else 2})
        out["chosen"] = out["options"].get(b.get("tool") or "change")
    elif lane == "video":
        length = _loose_int(b.get("seconds"), 1, 10, 5)
        length = length if length in VIDEO_SECONDS else 5
        shape = b.get("shape") if b.get("shape") in VIDEO_SHAPES else "landscape"
        source = b.get("source") if isinstance(b.get("source"), str) and b.get("source") else None
        model = b.get("model") if b.get("model") in VIDEO_MODELS else DEFAULT_VIDEO_MODEL
        base = {"prompt": words, "size": shape, "seed": 1}
        if source:
            base["source"] = source
        for k in VIDEO_MODELS:
            out["options"][k] = estimate_for("video", dict(base, duration=length, model=k))
        for d in VIDEO_SECONDS:
            out["alt"][str(d)] = estimate_for("video", dict(base, duration=d, model=model))
        out["chosen"] = out["options"].get(model)
    elif lane == "animation":
        seconds = _loose_int(b.get("seconds"), 2, 20, 5)
        params = {"template": b.get("template") if b.get("template") in ANIM_TEMPLATES else "title", "text": words,
                  "look": b.get("look") if b.get("look") in ANIM_LOOKS else "night", "font": b.get("font") if b.get("font") in ANIM_FONTS else "clean",
                  "shape": b.get("shape") if b.get("shape") in ANIM_SHAPES else "landscape", "seconds": seconds,
                  "direction": b.get("direction") if b.get("direction") in ANIM_DIRECTIONS else "in"}
        out["options"]["animation"] = out["chosen"] = estimate_for("animation", params)
    elif lane == "text":
        task = b.get("task") if b.get("task") in TEXT_TASKS else "script"
        length = _loose_int(b.get("length"), 30, 300, 60)
        rows, _ = engine_writers()
        for k in list(WRITERS) + [r["model"] for r in rows or [] if r.get("source") == "lmstudio"]:
            out["options"][k] = estimate_for("text", {"task": task, "prompt": words, "model": k, "length": length if length in TEXT_LENGTHS else 60,
                                                      "tone": "plain", "target": "image", "about": ""})
        out["chosen"] = out["options"].get(b.get("model") or DEFAULT_WRITER)
    elif lane == "recipe":
        # each step timed for the values chosen so far, so 2 seconds of clip is not shown with the time of 5
        plan = recipe_plan(b.get("recipe"), b.get("values")) if isinstance(b.get("recipe"), str) else None
        if plan:
            out["chosen"] = plan.get("estimate_seconds")
            out["recipe"] = b.get("recipe")
            out["steps"] = {s["id"]: s.get("estimate_seconds") for s in plan.get("steps") or [] if isinstance(s, dict) and s.get("id")}
    return out


def estimate_key(lane, params):
    if lane in ("recipe", "remake"):
        return f"{lane}:{params.get('recipe') or params.get('adapter')}"
    if lane == "film":
        return f"film:{int(params['total'] // 30)}"
    if lane == "image":
        return f"image:{params['model']}:{params['steps']}:{params['size']}"
    if lane == "voice":
        return f"voice:{params['voice']}:{len(params['text']) // 200}"
    if lane == "edit":
        return f"edit:{params['tool']}:{params.get('scale', '')}"
    if lane == "video":
        return f"video:{params['model']}:{params['duration']}:{params['size']}:{'picture' if params.get('source') else 'words'}"
    if lane == "animation":
        return f"animation:{params['shape']}:{round(params['seconds'])}"
    if lane == "text":
        return f"text2:{params['model']}:{params['task']}:{params['length'] if params['task'] == 'script' else ''}"  # "2": runs from before thinking was limited took minutes
    return f"music-full:{params['duration']}"  # "full": a piece of the length asked for, which earlier runs were not


class FriendlyError(Exception):
    """A failure with words a person can read. Details go to the log."""

    def __init__(self, message, detail=""):
        super().__init__(message)
        self.detail = detail


def run_image(job):
    p = job["params"]
    adapter, params = adapter_call("image", p)
    result, target = _on_the_queue(job, adapter, params, IMAGE_TIMEOUT,
                                   "The picture could not be made. Trying again or changing the size may help.", "the picture")
    return {"name": target.name, "seed": result.get("seed", p["seed"]), "full_prompt": result.get("prompt"),
            "dimensions": (result.get("size") or "").replace("x", " by ")}


def _plain_engine_error(error, fallback=None):
    """Engine text is shown only when it is already a sentence meant for a person."""
    text = (error or "").strip()
    if "NO-GO" in text:
        return "There was not enough free memory, so nothing was run. Please try again in a moment."
    if text and len(text) < 200 and "\n" not in text and re.match(r"(No |The |There |That |Please |This |Those |Writing |An )", text):
        return text
    return fallback or "The picture could not be finished, and the original was left as it was. Please try again."


def _remember(job):
    """Writes down what a restart of this screen would need in order to find this job again."""
    for store in (GENERATION, ENHANCE):
        if job.get("id") in store.jobs:
            store.save()


def _engine_gone(job, lost_at, patience, what, error):
    """The engine did not answer. It may be restarting, in which case it picks the job up again, so the
    screen keeps following it for a while instead of telling a person to do the work a second time."""
    if time.time() - lost_at > patience:
        raise FriendlyError(f"The engine stopped answering and has not come back, so the screen stopped waiting for {what}. "
                            "If it restarts, the work may still finish and appear in the gallery, so please look there before trying again.", repr(error))
    job["stage"] = "waiting for the engine to come back"
    time.sleep(2)


def _follow(job, adapter, params, timeout, what):
    """Watches one engine job until it ends, keeping the job's record current. Returns the engine's last view."""
    deadline, lost_at = time.time() + timeout, None
    while True:
        try:
            view = backend_get(f"/api/jobs/{job['backend_id']}", 15)
        except urllib.error.HTTPError:
            raise
        except (urllib.error.URLError, OSError, TimeoutError, json.JSONDecodeError) as e:
            lost_at = lost_at or time.time()
            _engine_gone(job, lost_at, min(ENGINE_GRACE, timeout), what, e)
            continue
        lost_at = None
        progress = view.get("progress") or {}
        if view.get("attempts") and view["attempts"] != job.get("attempt"):
            if job.get("attempt"):  # the engine restarted and is doing this over, so the clock starts over too
                job.pop("began", None)
                job["restarted"] = True
            job["attempt"] = view["attempts"]
        if progress.get("estimate_seconds") and (progress.get("eta_seconds") is None or progress["eta_seconds"] > 0):
            # The engine's figure is taken while it still says something. Once its own time has run out it reports
            # elapsed plus nothing, a figure that climbs with the clock; the last real estimate is kept instead, so
            # the page can say honestly that this is taking longer than usual.
            job["estimate"] = progress["estimate_seconds"]
        if progress.get("stage"):
            job["stage"] = "starting again after the engine restarted" if job.get("restarted") and progress.get("step") is None else progress["stage"]
        if progress.get("partial"):
            job["partial"] = progress["partial"]
        if adapter == "mflux" and params.get("live") and view.get("state") == "running":
            frame = live_frame(job["backend_id"])
            if frame:
                job["live_at"], job["live_path"] = frame
        if view.get("state") == "running" and not job.get("began"):
            job["began"] = time.time()  # the clock on the page starts when the work does, not when it joined the line
            _remember(job)
        job["position"] = view.get("position") if view.get("state") == "queued" else None
        job["waiting"] = view.get("state") == "queued"
        job["step"], job["total"] = progress.get("step"), progress.get("total")
        # The engine times a model's load apart from its steps. While it loads, the page must not count down steps that
        # have not begun, and with no load timed yet it promises no time left at all; these say which case this is.
        job["phase"], job["phase_known"] = progress.get("phase"), bool(progress.get("phase_known"))
        job["load_over"], job["steps_seconds"] = bool(progress.get("load_over")), progress.get("steps_seconds")
        # while it waits for memory: what the engine's own check asked for and found, so the page's reason agrees with it
        job["mem"] = ({k: progress.get(k) for k in ("need_gb", "free_gb", "safety_gb")}
                      if progress.get("stage") == "waiting for memory" and progress.get("free_gb") is not None else None)
        if progress.get("phase") == "loading" and progress.get("estimate_seconds"):
            job["estimate"] = progress["estimate_seconds"]
        if view.get("state") in ("done", "failed", "cancelled"):
            return view
        if time.time() > deadline:
            raise FriendlyError("This is taking far longer than it should, so the screen stopped waiting. "
                                "Check the gallery in a few minutes.")
        time.sleep(0.8)  # a four step picture reports a step every five seconds or so; the page should not be a step behind


def _on_the_queue(job, adapter, params, timeout, fallback, what, file=True, preview=False, route=None, body=None):
    """One job on the engine's queue, waited for here so the page polls this screen as usual.
    Returns the finished job's result and its file. file=False is a job with no file. A person sees
    only sentences meant for them. A job that already has an engine id is one this screen is picking
    up again after a restart, so it is followed and not sent a second time."""
    try:
        if not job.get("backend_id"):
            if job.get("stop_asked"):  # Stop was pressed before this was sent, so it is never sent
                raise FriendlyError("Stopped. Nothing was kept.")
            submitted = backend_post(route or "/api/jobs", body if route else {"adapter": adapter, "params": params, "client": "people-screen",
                                                                              "wait_for_memory": WAIT_FOR_MEMORY}, 20)
            job["backend_id"] = submitted["id"]
            _remember(job)
            if job.get("stop_asked"):  # Stop was pressed while the submit was in flight; the engine has it now, so it is told
                try:
                    backend_post(f"/api/jobs/{job['backend_id']}/cancel", {}, 15)
                except (urllib.error.URLError, OSError, TimeoutError):
                    pass
        view = _follow(job, adapter, params, timeout, what)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "ignore")
        raise FriendlyError(_plain_engine_error(body.split('"error":"')[-1].rstrip('"}'), fallback), body)
    except (urllib.error.URLError, OSError, TimeoutError, json.JSONDecodeError, KeyError) as e:
        raise FriendlyError(f"The engine stopped answering before {what} was finished. "
                            "Check the gallery in a few minutes, then try again.", repr(e))
    if view["state"] == "cancelled":
        raise FriendlyError("Stopped. Nothing was kept.")
    if view["state"] != "done":
        raise FriendlyError(_plain_engine_error(view.get("error"), fallback), str(view.get("error")))
    result = view.get("result") or {}
    if not file:
        return result, None
    target = safe_media_path(f"{PREVIEW_DIR}/{Path(result.get('path') or '').name}" if preview else Path(result.get("path") or "").name)
    if target is None or target.stat().st_size == 0:
        raise FriendlyError(f"The engine finished, but {what} did not arrive in the output folder.",
                            json.dumps(result)[:500])
    return result, target


_LIVE_STEP = re.compile(r"_step(\d+)of(\d+)\.png$")


def live_frame(backend_id):
    """(step, path) for the newest frame the engine has written for this job, or None."""
    folder = OUTPUT_DIR / "_live" / str(backend_id)[-6:]
    newest = None
    try:
        for entry in os.scandir(folder):
            m = _LIVE_STEP.search(entry.name)
            if m and (newest is None or int(m.group(1)) > newest[0]):
                newest = (int(m.group(1)), entry.path)
    except OSError:
        return None
    return newest


def run_edit(job):
    p = job["params"]
    adapter, params = adapter_call("edit", p)
    result, target = _on_the_queue(job, adapter, params, IMAGE_TIMEOUT, None, "the picture")
    return {"name": target.name, "seed": result.get("seed"), "full_prompt": p["prompt"],
            "dimensions": (result.get("size") or "").replace("x", " by ")}


def run_video(job):
    p = job["params"]
    adapter, params = adapter_call("video", p)
    result, target = _on_the_queue(job, adapter, params, VIDEO_TIMEOUT,
                                   "The clip could not be finished. Please try again.", "the clip")
    return {"name": target.name, "seed": result.get("seed"), "full_prompt": p["prompt"],
            "dimensions": (result.get("size") or "").replace("x", " by ")}


def animation_params(p):
    """What the motion adapter is told. Only checked names and a checked file path reach it."""
    out = {k: p[k] for k in ("template", "text", "look", "font", "shape", "seconds", "direction")}
    if p.get("source"):
        out["source"] = p["source"]
    return out


def run_animation(job):
    p = job["params"]
    adapter, params = adapter_call("animation", p)
    result, target = _on_the_queue(job, adapter, params, ANIM_TIMEOUT,
                                   "The animation could not be finished. Please try again.", "the animation")
    return {"name": target.name, "seed": None, "full_prompt": p["prompt"],
            "dimensions": (result.get("size") or "").replace("x", " by ")}


def run_preview(params):
    """One small still of an animation, as a queue job with no memory check because no model loads."""
    holder = {}
    try:
        result, target = _on_the_queue(holder, "motion", dict(animation_params(params), still=True), 25,
                                       "The preview could not be made.", "the preview", preview=True)
    except FriendlyError:
        if holder.get("backend_id"):  # a preview that cannot wait is taken back off the queue
            try:
                backend_post(f"/api/jobs/{holder['backend_id']}/cancel", {}, 10)
            except (urllib.error.URLError, OSError, TimeoutError):
                pass
        raise
    return {"url": f"/media/{PREVIEW_DIR}/{target.name}", "size": result.get("size")}


def run_text(job):
    p = job["params"]
    adapter, params = adapter_call("text", p)
    fallback = "The writing helper could not finish. Please try again."
    result, target = _on_the_queue(job, adapter, params, TEXT_LIMIT, fallback, "the writing", file=p["task"] != "rewrite")
    return {"name": target.name if target else None, "seed": None, "text": result.get("text"), "full_prompt": p["prompt"]}


def cancel_job(job_id):
    """Asks the engine to stop a job it is running. True if the request went through."""
    job = GENERATION.jobs.get(job_id) or ENHANCE.jobs.get(job_id)
    if not job or job["state"] != "running":
        return False
    if not (job.get("backend_id") or job.get("backend_run")):
        # The press came in the first moments, while this job is still on its way to the engine. The wish is
        # kept, and the runner acts on it the moment the engine has answered (or never sends it at all).
        job["stop_asked"] = True
        return True
    try:
        backend_post(f"/api/recipe-runs/{job['backend_run']}/cancel" if job.get("backend_run") else f"/api/jobs/{job['backend_id']}/cancel", {}, 15)
    except (urllib.error.URLError, OSError, TimeoutError):
        return False
    return True


RECIPE_LIMIT = 8 * 3600  # steps may wait for memory or the nightly job, so this is deliberately long
_recipe_cache = {"at": 0.0, "items": []}


def recipes(fresh=False):
    """The engine's recipe book, kept for a few seconds so a status poll does not ask every time."""
    if fresh or time.time() - _recipe_cache["at"] > 5 or not _recipe_cache["items"]:
        try:
            _recipe_cache.update(items=backend_get("/api/recipes", 5)["recipes"], at=time.time())
        except (urllib.error.URLError, OSError, TimeoutError, json.JSONDecodeError, KeyError):
            pass
    return _recipe_cache["items"]


def recipe_plan(rid, values):
    """The engine's plan for this recipe with the values typed so far (a 2 second clip timed as one), or the plan for its
    defaults when the engine does not answer. None for a recipe that is not in the book."""
    known = next((r for r in recipes() if r.get("id") == rid), None)
    if known is None:
        return None
    try:
        plan = backend_post(f"/api/recipes/{urllib.parse.quote(rid, safe='')}/plan", {"values": values if isinstance(values, dict) else {}}, 8).get("plan")
    except (urllib.error.URLError, OSError, TimeoutError, json.JSONDecodeError, AttributeError):
        plan = None
    return plan if isinstance(plan, dict) else (known.get("plan") or {})


def _step_view(step):
    """One step of a run in the shape the page draws, with links for what it has already made."""
    out = step.get("output") or {}
    name = Path(out["file"]).name if out.get("file") else None
    suffix = Path(name).suffix.lower() if name else ""
    kind = "image" if suffix in IMAGE_SUFFIXES else "video" if suffix in VIDEO_SUFFIXES else "text" if suffix in TEXT_SUFFIXES else "audio" if name else None
    excerpt = ""
    if kind == "text":  # the first words of what was written, for the step's card on the board
        target = safe_media_path(name)
        try:
            excerpt = shorten(target.read_text(encoding="utf-8", errors="ignore"), 160) if target else ""
        except OSError:
            excerpt = ""
    progress = step.get("progress") or {}
    # A step the engine has accepted but not reached is waiting, whatever the recipe calls it.
    queued = step.get("state") == "running" and progress.get("stage") == "queued"
    return {"id": step.get("id"), "label": step.get("label"), "state": "waiting" if queued else step.get("state"), "queued": queued, "job": step.get("job"),
            "stage": plain_stage(progress.get("stage")), "step": progress.get("step"), "total": progress.get("total"), "elapsed": progress.get("elapsed_seconds"),
            "estimate": progress.get("estimate_seconds") or step.get("estimate_seconds"),
            "waiting": "its turn" if queued else step.get("waiting"), "name": name, "kind": kind, "excerpt": excerpt, "url": f"/media/{name}" if name else None, "thumb": _thumb_url(name)}


def run_recipe(job):
    p = job["params"]
    if not job.get("backend_run"):
        try:
            run = backend_post(f"/api/recipes/{p['recipe']}/run", {"values": p["values"], "client": "people-screen"}, 20)
        except urllib.error.HTTPError as e:
            try:
                message = json.loads(e.read().decode("utf-8", "ignore")).get("error")
            except json.JSONDecodeError:
                message = None
            raise FriendlyError(message or "That recipe could not start.", repr(e))
        except (urllib.error.URLError, OSError, TimeoutError, json.JSONDecodeError) as e:
            raise FriendlyError("The engine stopped answering, so the recipe did not start.", repr(e))
        job["backend_run"] = run["id"]
        _remember(job)
        if job.get("stop_asked"):  # Stop was pressed while the recipe was on its way to the engine
            try:
                backend_post(f"/api/recipe-runs/{job['backend_run']}/cancel", {}, 15)
            except (urllib.error.URLError, OSError, TimeoutError):
                pass
    deadline, lost_at = time.time() + RECIPE_LIMIT, None
    while True:
        try:
            view = backend_get(f"/api/recipe-runs/{job['backend_run']}", 15)
        except urllib.error.HTTPError as e:
            raise FriendlyError("The engine no longer knows about this recipe. Finished steps are in the gallery.", repr(e))
        except (urllib.error.URLError, OSError, TimeoutError, json.JSONDecodeError) as e:
            lost_at = lost_at or time.time()
            _engine_gone(job, lost_at, ENGINE_GRACE, "the recipe", e)
            continue
        lost_at = None
        steps = [_step_view(s) for s in view.get("steps") or []]
        job["steps"] = steps
        job["estimate"] = view.get("estimate_seconds") or job["estimate"]
        active = next((s for s in steps if s["state"] in ("running", "waiting")), None)
        job["stage"] = (f"waiting for {view['waiting']}" if view.get("waiting") else
                        ("queued" if active and active["queued"] else f"{active['label']}" if active else None))
        job["waiting"] = bool(active and active["queued"])
        job["position"] = None
        if job["waiting"] and active["job"]:
            try:
                job["position"] = backend_get(f"/api/jobs/{active['job']}", 5).get("position")
            except (urllib.error.URLError, OSError, TimeoutError, json.JSONDecodeError):
                pass
        if not job.get("began") and any(s["state"] == "done" or (s["state"] == "running" and s["job"]) for s in steps):
            job["began"] = time.time()
            _remember(job)
        job["worked"] = view.get("elapsed_seconds") or 0  # time the steps have really run, not time spent in line
        if view.get("state") in ("done", "failed", "cancelled"):
            break
        if time.time() > deadline:
            raise FriendlyError("This is taking far longer than it should, so the screen stopped waiting. Check the gallery.")
        time.sleep(1.5)
    if view["state"] == "cancelled":
        raise FriendlyError("Stopped. The steps that had finished are in the gallery.")
    if view["state"] != "done":
        raise FriendlyError(_plain_engine_error(view.get("error"), "One step could not be finished. The steps before it are in the gallery."),
                            str(view.get("error")))
    return {"name": view["result"]["name"], "seed": view["result"].get("seed"), "full_prompt": p["prompt"], "dimensions": None}


def run_remake(job):
    """The same adapter and settings the sidecar records, as a new file. Nothing is overwritten."""
    p = job["params"]
    fallback = "It could not be made again. The original was left as it was."
    result, target = _on_the_queue(job, None, None, VIDEO_TIMEOUT, fallback, "the new copy",
                                   route=f"/api/provenance/{p['name']}/remake", body={"client": "people-screen"})
    return {"name": target.name, "seed": result.get("seed"), "full_prompt": p.get("prompt"),
            "dimensions": (result.get("size") or "").replace("x", " by ") or None}


def run_voice(job):
    p = job["params"]
    adapter, params = adapter_call("voice", p)
    result, target = _on_the_queue(job, adapter, params, 3600,
                                   "The voice engine could not read this text aloud. Try a shorter passage or another voice.", "the recording")
    return {"name": target.name, "seed": None, "seconds": sound_seconds(target)}


def sound_seconds(path):
    """How long a finished recording runs, read from the file itself, so its line can say how long it is."""
    try:
        with wave.open(str(path), "rb") as w:
            return round(w.getnframes() / float(w.getframerate()), 2) if w.getframerate() else None
    except (OSError, EOFError, wave.Error):
        return None  # not a plain wave file: the line simply leaves the length out


def run_music(job):
    p = job["params"]
    adapter, params = adapter_call("music", p)
    result, target = _on_the_queue(job, adapter, params, max(3600, int(p["duration"] * 60)),
                                   "The music engine could not finish this piece.", "the music")
    seconds = result.get("duration")
    out = {"name": target.name, "seed": result.get("seed", p["seed"]), "seconds": seconds}
    if seconds and seconds < p["duration"] * 0.85:  # the file's real length, and a person is told when it is not what they asked for
        out["note"] = f"You asked for {p['duration']:.0f} seconds. The music model ended this piece at {seconds:.0f} seconds."
    return out


def run_film(job):
    """A project's timeline, joined on the queue by the timeline adapter. No model is loaded."""
    p = job["params"]
    adapter, params = adapter_call("film", p)
    result, target = _on_the_queue(job, adapter, params, 3600, "The film could not be joined. Please try again.", "the film")
    return {"name": target.name, "seed": None, "full_prompt": p["prompt"], "dimensions": (result.get("size") or "").replace("x", " by "),
            "seconds": result.get("seconds")}


# ------------------------------------------------------------------ jobs
class Busy(Exception):
    pass


AFTER_RECORD = []  # app.py adds "put this file in its project" here


class Jobs:
    """Work the page has asked for, each on its own thread so the page never waits on it. Each job is
    one job on the engine's queue, and the queue runs them one at a time. limit caps how many may
    be lined up; 1 means a second request is refused while the first runs."""

    def __init__(self, limit=1, store=None):
        self.lock = threading.Lock()
        self.save_lock = threading.Lock()
        self.jobs, self.limit, self.store = {}, limit, store
        if store:
            try:
                self.jobs = json.loads(Path(store).read_text())
            except (OSError, json.JSONDecodeError):
                pass

    def save(self):
        """The list as it stands, on disk, so a restart of this screen does not lose sight of anything."""
        if not self.store:
            return
        with self.save_lock:
            with self.lock:
                text = json.dumps(self.jobs, indent=1, default=str)
            tmp = Path(self.store).with_name(f".{Path(self.store).name}.{os.getpid()}.tmp")
            tmp.write_text(text)
            os.replace(tmp, self.store)

    def resume(self, runners):
        """After a restart: go back to following whatever the engine was doing for this screen. A job
        that never reached the engine cannot have made anything, and is marked so."""
        for job in list(self.jobs.values()):
            if job["state"] != "running":
                continue
            if job.get("backend_id") or job.get("backend_run"):
                threading.Thread(target=self._run, args=(job, runners[job["lane"]]), daemon=True).start()
            else:
                job.update(state="failed", finished=time.time(), message="The screen restarted before this reached the engine, so nothing was made. Please try again.")
        self.save()

    def active(self):
        return [j for j in list(self.jobs.values()) if j["state"] == "running"]

    def line_seconds(self):
        """Roughly how long everything already lined up still has to run."""
        return sum(max(5, (j["estimate"] or 60) - (time.time() - j["started"] if not j.get("waiting") else 0)) for j in self.active())

    def begin(self, lane, params, runner, estimate, person=None):
        with self.lock:
            if len(self.active()) >= self.limit:
                raise Busy()
            job = {"id": f"{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}", "lane": lane,
                   "params": params, "state": "running", "started": time.time(), "finished": None,
                   "estimate": estimate, "result": None, "message": "", "person": person}
            self.jobs[job["id"]] = job
            for old in sorted(self.jobs)[:-40]:
                if self.jobs[old]["state"] != "running":
                    self.jobs.pop(old, None)
        self.save()
        threading.Thread(target=self._run, args=(job, runner), daemon=True).start()
        return job

    def _run(self, job, runner):
        try:
            result = runner(job)
            job["result"] = result
            if result and result.get("name"):
                # The file is recorded and put in its project before the job says it is done, so a page that sees "done"
                # and reads the project at once (the Timeline's bin, the strip) already finds the new file there.
                job["finished"] = time.time()
                try:
                    self._record(job)
                    for fn in AFTER_RECORD:
                        fn(job)
                except Exception as e:  # noqa: BLE001  a record that could not be written does not take away a file that was made
                    self._note(job, f"record: {e!r}")
                job["recorded"] = True
            job["state"] = "done"
        except FriendlyError as e:
            job.update(state="cancelled" if str(e).startswith("Stopped") else "failed", message=str(e))
            if job["state"] == "failed":
                self._note(job, e.detail)
        except Exception as e:  # noqa: BLE001  a person must get an answer whatever happens
            job.update(state="failed", message="Something went wrong and nothing was made. Please try again.")
            self._note(job, repr(e))
        job["finished"] = job["finished"] if job.get("recorded") else time.time()
        MEMORY.at = 0.0  # the engine just let go of its memory; do not show the reading from mid-run
        self.save()

    @staticmethod
    def _note(job, detail):
        with open(STATE_DIR / "logs" / "failures.log", "a") as f:
            f.write(f"{datetime.now().isoformat(timespec='seconds')} {job['id']} {job['lane']}\n{detail}\n\n")

    @staticmethod
    def _record(job):
        p, r = job["params"], job["result"]
        if job["lane"] in ("recipe", "remake"):
            RECORDS.update(r["name"], lane=job["lane"] if job["lane"] == "recipe" else p.get("lane"), prompt=p.get("prompt"), seed=r.get("seed"),
                           model_label=p.get("label"), parent=p.get("name"), remade=job["lane"] == "remake", dimensions=r.get("dimensions"),
                           # a recipe took the time its steps really ran (the engine's own count), not the time it spent in
                           # line behind other people's work, the way every other lane's "took" is the run alone
                           elapsed=round(job.get("worked") or (job["finished"] - job.get("began", job["started"])), 1),
                           created=datetime.fromtimestamp(job["finished"]).isoformat(timespec="seconds"),
                           estimate_key=estimate_key(job["lane"], p))
            return
        spec = IMAGE_MODELS.get(p.get("model"), {}) if job["lane"] == "image" else (
            VOICES.get(p.get("voice"), {}) if job["lane"] == "voice" else
            EDIT_TOOLS.get(p.get("tool"), {}) if job["lane"] == "edit" else
            VIDEO_MODELS.get(p.get("model"), {}) if job["lane"] == "video" else
            ANIM_TEMPLATES.get(p.get("template"), {}) if job["lane"] == "animation" else
            {"label": "Film"} if job["lane"] == "film" else
            {"label": writer_label(p.get("model"))} if job["lane"] == "text" else MUSIC)
        RECORDS.update(r["name"], lane=job["lane"], prompt=p.get("prompt") or p.get("text"),
                       full_prompt=r.get("full_prompt"), seed=r.get("seed"), model=p.get("model"),
                       model_label=spec.get("label"), size=p.get("size"), style=p.get("style"),
                       steps=p.get("steps"), voice=p.get("voice"), duration=p.get("duration"),
                       dimensions=r.get("dimensions"), parent=p.get("parent"), seconds=r.get("seconds"),
                       elapsed=round(job["finished"] - job.get("began", job["started"]), 1), batch=p.get("batch"),
                       created=datetime.fromtimestamp(job["finished"]).isoformat(timespec="seconds"),
                       estimate_key=estimate_key(job["lane"], p))

    def view(self, job_id, sizes=None, viewer=None):
        job = self.jobs.get(job_id)
        if job is None:
            return None
        return self._view(job, sizes, viewer)

    def _view(self, job, sizes=None, viewer=None):
        end = job["finished"] or time.time()
        out = {k: job[k] for k in ("id", "lane", "state", "estimate", "message")}
        out["stage"] = "Stopping" if job.get("stop_asked") and job["state"] == "running" else plain_stage(job.get("stage"))
        # mine: this person started it, on this page or any other of theirs, so any of their pages may stop it
        out["mine"] = bool(viewer) and job.get("person") == viewer
        out["by_someone_else"] = bool(job.get("person")) and not out["mine"]
        out["can_stop"] = job["state"] == "running" and not job.get("stop_asked")  # from the first moment: a press before the engine has answered is kept
        out["steps"] = job.get("steps")
        out["partial"] = job.get("partial")
        if job["lane"] == "recipe" and (job["state"] == "running" or job.get("worked")):
            out["elapsed"] = job.get("worked") or 0
        else:
            out["elapsed"] = round(max(0, end - job.get("began", job["started"])), 1) if job.get("began") or job["state"] != "running" else 0
        out["waiting"], out["position"], out["step"], out["total"] = bool(job.get("waiting")), job.get("position"), job.get("step"), job.get("total")
        out["phase"], out["phase_known"], out["load_over"], out["steps_seconds"] = job.get("phase"), bool(job.get("phase_known")), bool(job.get("load_over")), job.get("steps_seconds")
        # waiting for the nightly job rather than for its turn: the page says so and does not count it as next in line
        out["night"] = bool(job.get("waiting")) and str(job.get("stage") or "").startswith("waiting for the nightly")
        out["batch"] = job["params"].get("batch")
        if job["lane"] == "image":
            # the picture model and the words, so a picture held for memory can be offered again with a model that fits now
            out["model"] = job["params"].get("model")
            out["mem"] = job.get("mem")
            if out["mine"]:
                out["words"] = job["params"].get("prompt")
        out["planned"] = job["params"].get("steps") if job["lane"] == "image" else None  # known before the first step is reported
        out["title"] = shorten(plain_words(job["params"].get("prompt") or job["params"].get("text")) or "", 140)
        out["live"] = bool(job["params"].get("live"))
        out["size"] = job["params"].get("size")
        out["source_ratio"] = job["params"].get("source_ratio")
        out["task"], out["target"] = job["params"].get("task"), job["params"].get("target")
        out["peek"] = job.get("live_at")
        # held: the engine has this job (or a recipe's working step) waiting at the memory check. It is not being made,
        # so the page says so and promises no time left; held_for is how long it has waited.
        held = is_held(job)
        if held:
            job["held_since"] = job.get("held_since") or time.time()
            job["held_last"] = time.time()
        elif time.time() - job.get("held_last", 0) > 30:
            job.pop("held_since", None)  # a retry that is refused again within half a minute is still the same wait
        out["held"], out["held_for"] = held, round(time.time() - job["held_since"], 1) if held else None
        if job["lane"] == "recipe":
            out["recipe"] = job["params"].get("recipe")
            known = next((r for r in recipes() if r.get("id") == out["recipe"]), None)
            out["recipe_label"] = (known or {}).get("label") or (known or {}).get("name")
        result = job["result"] or {}
        if job["state"] == "done":
            out["item"] = describe_name(result["name"], sizes) if result.get("name") else None
            out["text"] = result.get("text")
            out["note"] = result.get("note")
        return out

    def running(self):
        """The job on screen: what is really running, or the one next in line."""
        with self.lock:
            active = sorted(self.active(), key=lambda j: j["started"])
        if not active:
            return None
        return next((j["id"] for j in active if not j.get("waiting")), active[0]["id"])

    def views(self, sizes=None, viewer=None):
        """Every job, newest first. The list is copied under the lock and each view is made from the copied job itself,
        not looked up again by id: a new job started meanwhile may trim the oldest finished one from the store, and a
        lookup by id would then give None, which the page cannot read."""
        with self.lock:
            jobs = sorted(self.jobs.values(), key=lambda j: j["started"], reverse=True)
        return [self._view(j, sizes, viewer) for j in jobs]


GENERATION = Jobs(limit=MAX_WAITING, store=STATE_DIR / "jobs.json")
ENHANCE = Jobs(store=STATE_DIR / "rewrites.json")
RUNNERS = {"film": run_film, "image": run_image, "voice": run_voice, "music": run_music, "edit": run_edit, "video": run_video,
           "animation": run_animation, "text": run_text, "recipe": run_recipe, "remake": run_remake}
TEXT_LIMIT = 3700  # the engine's own limit for a writing job is 3600 seconds


# ------------------------------------------------------------------ the prompt helper
def run_enhance(job):
    """A rewrite on the engine's queue, by the 9B. The queue never sets a token limit."""
    p = job["params"]
    down = "The writing helper is not running right now, so your words were left as they are."
    params = {"task": "rewrite", "brief": p["prompt"], "target": p["lane"], "model": DEFAULT_WRITER}
    try:
        result, _ = _on_the_queue(job, "local-text", params, HELPER_TIMEOUT, down, "the rewrite", file=False)
    except FriendlyError as e:
        if "stopped answering" in str(e):
            raise FriendlyError(down, e.detail)
        raise
    text = (result.get("text") or "").strip()
    if not text:
        raise FriendlyError("The writing helper did not suggest anything, so your words were left as they are.")
    return {"text": text}


# ------------------------------------------------------------------ what the screen offers
_NOT_READY = {}
_FALLBACK_SIZES = {"square": "1024x1024", "wide": "1344x768", "tall": "768x1344",
                   "portrait": "896x1152", "landscape": "1152x896", "banner": "1536x512"}


def downloaded(repo, models):
    """True or False from the engine's model list; None when that list is not available yet."""
    if not models or not repo:
        return None
    entry = (models.get("models") or {}).get(repo)
    return bool(entry and entry.get("size_mb", 0) >= 300)


def refresh_backend():
    """Keep a copy of the engine's lists, because :8100 cannot answer while it is generating."""
    if GENERATION.running():
        return
    for key, route, wait in (("presets", "/api/presets", 4), ("models", "/api/models", 25)):
        try:
            RECORDS.set_backend(key, backend_get(route, wait))
        except (urllib.error.URLError, OSError, TimeoutError, json.JSONDecodeError):
            pass


def engine_answering():
    try:
        return backend_get("/health", 3.0).get("status") == "ok"
    except (urllib.error.URLError, OSError, TimeoutError, json.JSONDecodeError):
        return False


def sizes_available():
    return (RECORDS.backend("presets") or {}).get("sizes") or _FALLBACK_SIZES


def typical_seconds(key, spec):
    """How long one of these usually takes here: the median of real runs when there are any, else the measured figure.
    The same source the working screen's estimate uses, so the two never disagree."""
    prefix = {"music": "music-full:"}.get(key)
    if prefix is None:
        lane = ("image" if key in IMAGE_MODELS else "voice" if key in VOICES else "edit" if key in EDIT_TOOLS else "video" if key in VIDEO_MODELS
                else "text2" if key in WRITERS or is_lms_writer(key) else None)
        prefix = f"{lane}:{key}:" if lane else None
    runs = RECORDS.recent_seconds_like(prefix) if prefix else []
    if runs:
        return round(statistics.median(runs))
    return spec.get("seconds")


def catalog(reading):
    presets, models = RECORDS.backend("presets") or {}, RECORDS.backend("models")

    def row(key, spec, routed, reason=""):
        have = downloaded(spec["repo"], models) if spec.get("repo") else None
        b = badge_for(spec["gb"], reading)
        runnable, why = routed and b["fits"], reason
        if not has_needs(spec):
            runnable, why = False, why_off(spec)
        elif have is False:
            runnable, why = False, "Not on this Mac yet, so it cannot be used."
        elif routed and not b["fits"]:
            why = b["text"]
        return {"id": key, "label": spec["label"], "engine": spec["engine"], "note": spec.get("note", ""),
                "gb": spec["gb"], "badge": b["badge"], "badge_text": b["text"], "badge_short": b.get("short", ""), "runnable": runnable,
                "reason": why, "reason_short": b.get("short", "") if why == b["text"] else "", "seconds": typical_seconds(key, spec)}

    def ask(gb):
        b = badge_for(gb, reading)
        return {"gb": gb, "badge": b["badge"], "badge_text": b["text"], "badge_short": b.get("short", ""), "fits": b["fits"]}

    image = [dict(row(k, s, s["routed"], "" if s["routed"] else NOT_ROUTED), steps=s["steps"], live=bool(s.get("live")),
                  asks={"source": ask(s["gb"] + SOURCE_GB), **({"live": ask(s["gb"] + LIVE_GB)} if s.get("live") else {})})
             for k, s in IMAGE_MODELS.items()]
    voices = [dict(row(k, s, True), own_speed=bool(s.get("own_speed")), english_only=bool(s.get("english_only"))) for k, s in VOICES.items() if not s.get("added") or has_needs(s)]
    edit_tools = [dict(row(k, s, True), words=bool(s.get("words"))) for k, s in EDIT_TOOLS.items()]
    styles = [{"id": "none", "label": "None", "text": ""}]
    known_styles = presets.get("styles") or {}
    styles += [{"id": k, "label": label, "text": known_styles[k]} for k, label in PUBLIC_LOOKS.items() if k in known_styles]
    recipe_rows = []
    for r in recipes():
        plan = r.get("plan") or {}
        gb = plan.get("memory_gb") or 0
        b = badge_for(gb, reading) if gb else {"badge": "green", "fits": True, "text": "Uses very little memory."}
        # A recipe is built to wait: each step asks the memory check when it starts and waits for room by itself. So one
        # can always be lined up; when its largest step does not fit right now, it says so and that it will wait.
        text = b["text"] if b["fits"] else (f"Its largest step needs about {gb} GB, more than is free right now. You can still start it: "
                                            "each step waits for memory by itself and starts when there is room.")
        recipe_rows.append({"id": r["id"], "label": r["name"], "description": r.get("description", ""), "builtin": bool(r.get("builtin")),
                            "based_on": r.get("based_on"), "inputs": r.get("inputs", []), "steps": plan.get("steps", []), "estimate": plan.get("estimate_seconds"),
                            "gb": gb, "badge": b["badge"], "badge_text": text, "runnable": True, "reason": "", "waits": not b["fits"]})
    recipe_rows.sort(key=lambda x: not x["builtin"])  # the recipes that come with NeoVak first, then the ones people saved
    writers, lmstudio = writer_catalog(reading, row)
    return {"recipes": recipe_rows, "image_models": image, "voices": voices, "music": row("music", MUSIC, True),
            "music_lengths": MUSIC_LENGTHS, "sizes": sizes_available(), "styles": styles,
            "edit_tools": edit_tools, "edit_scales": EDIT_SCALES,
            "video_models": [row(k, s, True) for k, s in VIDEO_MODELS.items()], "video_lengths": sorted(VIDEO_SECONDS),
            "video_shapes": VIDEO_SHAPES,
            "animation": dict(row("animation", ANIMATION, True), runnable=True, badge="green", badge_text="Uses no model, and very little memory.", reason="", templates=[{"id": k, **v} for k, v in ANIM_TEMPLATES.items()],
                              looks=ANIM_LOOKS, fonts=ANIM_FONTS, shapes=ANIM_SHAPES, directions=ANIM_DIRECTIONS),
            "writers": writers, "lmstudio": lmstudio, "text_tasks": TEXT_TASKS,
            "text_lengths": TEXT_LENGTHS, "text_tones": TEXT_TONES, "text_targets": TEXT_TARGETS,
            "not_ready": _NOT_READY}


_SIZE_TOKEN = re.compile(r"^(?:e\d+b|\d+(?:\.\d+)?b)$", re.I)
_MODIFIED_WORDS = {"abliterated", "heretic", "uncensored", "uncnr", "defiant", "fable", "fablevibes", "neo", "max", "norm", "preserved",
                   "biprojected", "dolphin", "nsfw", "jailbreak", "unlocked", "liberated", "heretical"}


def plain_writer_label(label):
    """LM Studio's display name in plain words: the family and its size, and no more. 'Qwen3.5 9B The Defiant Fable
    Uncnr Heretic NEO MAX' is 'Qwen3.5 9B, a modified copy'; 'Gemma 4 12B Instruct Qat' is 'Gemma 4 12B'; 'Qwen Qwen3.5
    4B' is 'Qwen3.5 4B'. The full name stays on the Models page and in the row's title."""
    text = re.sub(r"\s*\((GGUF|MLX)\)\s*$", "", label or "").strip()
    paren = re.search(r"\(([^)]*)\)\s*$", text)
    size_in_paren = paren.group(1).strip() if paren and re.match(r"^\d+(?:\.\d+)?B(?:-A\d+B)?$", paren.group(1).strip(), re.I) else ""
    text = re.sub(r"\s*\([^)]*\)\s*$", "", text).strip()
    words = text.split()
    if len(words) > 1 and words[0].lower() == words[1].lower()[:len(words[0])]:
        words = words[1:]  # "Qwen Qwen3.5 4B": the publisher's name doubled onto the family's
    cut = next((i for i, w in enumerate(words) if _SIZE_TOKEN.match(w)), None)
    head, tail = (words[:cut + 1], words[cut + 1:]) if cut is not None else (words, [])
    name = " ".join(head)
    if cut is None and size_in_paren:
        name += f" {size_in_paren.split('-')[0].upper()}"
    modified = any(w.lower().strip(",.") in _MODIFIED_WORDS for w in tail + head[:-1]) if cut is not None else any(w.lower() in _MODIFIED_WORDS for w in tail)
    return name + (", a modified copy" if modified else "")


def plain_writer_note(note):
    """The engine's sentence about a writer in LM Studio, with the maker's account name and the bit counts taken out."""
    text = re.sub(r"^In LM Studio(, |\.\s*)", "", note or "")
    text = re.sub(r"\s*Loads when asked and leaves memory .*?\.\s*$", "", text).strip()
    text = re.sub(r"a compact copy at \d+(?:\.\d+)? bits per weight(?: from [\w.-]+)?", "A smaller copy that uses less memory", text)
    text = re.sub(r"a copy at \d+(?:\.\d+)? bits per weight, close to the original(?: from [\w.-]+)?", "A full copy, close to the original", text)
    text = re.sub(r"a copy at \d+(?:\.\d+)? bits per weight(?: from [\w.-]+)?", "A copy that uses less memory than the original", text)
    text = re.sub(r"\s+from [\w.-]+(?=[.,]|$)", "", text)
    text = text.replace("It can also look at pictures, which this lane does not use.", "")
    text = " ".join(text.split())
    if text and text[-1] not in ".!?":
        text += "."
    return (text[:1].upper() + text[1:]) if text else ""


def writer_catalog(reading, row):
    """The Writing lane's choice: the two officers, then every writer LM Studio lists, each with its figure (measured on a
    real run here, or an estimate from the size on disk, and the row says which), the same fit badge the picture models
    have, and whether it is in memory now. Returns (rows, lmstudio)."""
    engine_rows, lmstudio = engine_writers()
    by_id = {r["model"]: r for r in engine_rows or []}
    out = []
    for k, s in WRITERS.items():
        eng = by_id.get(k) or {}
        spec = dict(s, gb=eng.get("gb") or s["gb"])
        r = row(k, spec, s.get("tested", True), "" if s.get("tested", True) else NOT_TESTED)
        r.update(gb_kind=eng.get("gb_kind") or "estimate", source="officer", loaded=None, disk_gb=None)
        out.append(r)
    for eng in engine_rows or []:
        if eng.get("source") != "lmstudio":
            continue
        gb = eng.get("gb")
        if eng.get("loaded"):
            b = {"badge": "green", "fits": True, "text": "In memory now, so nothing new has to be loaded."}
        elif gb is None:
            b = {"badge": "unknown", "fits": False, "text": "LM Studio did not say how big this is, so it is not offered."}
        else:
            b = badge_for(gb, reading)
        key = eng["model"]
        # The lane's row sits under an "In LM Studio" heading with one line about loading, so it keeps only what is particular to
        # this model; the Models page, where a row stands alone, shows the engine's whole note (note_full).
        full = eng.get("note", "")
        short = plain_writer_note(full)
        label = plain_writer_label(eng["label"])
        taken = [r["label"] for r in out]
        if label in taken:  # two copies of the same model: the second is said to be the second
            label = f"{label} (another copy)" if f"{label} (another copy)" not in taken else f"{label} (a third copy)"
        out.append({"id": key, "label": label, "full_name": eng["label"], "engine": "LM Studio", "note": short, "note_full": full, "gb": gb, "gb_kind": eng.get("gb_kind"),
                    "badge": b["badge"], "badge_text": b["text"], "badge_short": b.get("short", ""), "runnable": b["fits"], "reason": "" if b["fits"] else b["text"],
                    "reason_short": "" if b["fits"] else b.get("short", ""),
                    "seconds": typical_seconds(key, {"seconds": writer_seconds(key, eng)}), "source": "lmstudio",
                    "loaded": bool(eng.get("loaded")), "ttl_seconds": eng.get("ttl_seconds"), "disk_gb": eng.get("disk_gb")})
    return out, lmstudio


class Invalid(Exception):
    pass


def _bounded_int(value, low, high, default, name):
    if value in (None, ""):
        return default
    try:
        number = int(value)
    except (TypeError, ValueError, OverflowError):
        raise Invalid(f"{name} has to be a whole number.")
    if not low <= number <= high:
        raise Invalid(f"{name} has to be between {low} and {high}.")
    return number


def _validate_edit(body):
    """The source is named only by a file name inside the output folder."""
    tool = body.get("tool") or "change"
    spec = EDIT_TOOLS.get(tool)
    if spec is None:
        raise Invalid("Please pick one of the listed tools.")
    name = body.get("source")
    target = safe_media_path(name) if isinstance(name, str) else None
    if target is None or target.suffix.lower() not in IMAGE_SUFFIXES or target.parent != OUTPUT_DIR.resolve():
        raise Invalid("Please pick a picture from the gallery first.")
    if downloaded(spec["repo"], RECORDS.backend("models")) is False if spec.get("repo") else False:
        raise Invalid("That tool's files are not on this Mac yet.")
    if not has_needs(spec):
        raise Invalid(why_off(spec))
    params = {"tool": tool, "source": str(target), "parent": target.name}
    if spec.get("words"):
        text = clean_prompt(body.get("prompt"))
        if not text:
            raise Invalid("Please describe the change you want.")
        if len(text) > MAX_PROMPT:
            raise Invalid(f"That is too long. Please keep it under {MAX_PROMPT} characters.")
        params["prompt"] = text
    else:
        # captioned with what the picture is, after the tool: two enlargements of two pictures are told apart by their words
        about = plain_words(RECORDS.get(target.name).get("prompt")) or ""
        params["prompt"] = f"{spec['label']}: {shorten(about, 160)}" if about else spec["label"]
    if tool == "bigger":
        scale = _bounded_int(body.get("scale"), 2, 4, 2, "Enlargement")
        if scale not in EDIT_SCALES:
            raise Invalid("Please pick one of the listed sizes.")
        params["scale"] = scale
    seed = _bounded_int(body.get("seed"), 0, 2 ** 32 - 1, None, "Seed")
    params["seed"] = seed if seed is not None else int.from_bytes(os.urandom(4), "big") % 2 ** 31
    return "edit", params, spec["gb"], "this tool"


def _validate_video(body):
    """A picture to start from is named only by a file name inside the output folder."""
    text = clean_prompt(body.get("prompt"))
    if not text:
        raise Invalid("Please describe what happens in the clip.")
    if len(text) > MAX_PROMPT:
        raise Invalid(f"That is too long. Please keep it under {MAX_PROMPT} characters.")
    model = body.get("model") or DEFAULT_VIDEO_MODEL
    spec = VIDEO_MODELS.get(model)
    if spec is None:
        raise Invalid("That video model is not one this Mac knows.")
    if not has_needs(spec):
        raise Invalid(why_off(spec))
    length = _bounded_int(body.get("seconds"), 1, 10, 5, "Length")
    if length not in VIDEO_SECONDS:
        raise Invalid("Please pick one of the listed lengths.")
    shape = body.get("shape") or "landscape"
    if shape not in VIDEO_SHAPES:
        raise Invalid("Please pick one of the listed shapes.")
    params = {"prompt": text, "duration": length, "size": shape, "parent": None, "source": None, "model": model}
    name = body.get("source")
    if name:
        target = safe_media_path(name) if isinstance(name, str) else None
        if target is None or target.suffix.lower() not in IMAGE_SUFFIXES or target.parent != OUTPUT_DIR.resolve():
            raise Invalid("Please pick a picture from the gallery first.")
        params.update(source=str(target), parent=target.name)
    seed = _bounded_int(body.get("seed"), 0, 2 ** 32 - 1, None, "Seed")
    params["seed"] = seed if seed is not None else int.from_bytes(os.urandom(4), "big") % 2 ** 31
    return "video", params, spec["gb"], "this clip"


def _pick(body, key, allowed, default, what):
    value = default if body.get(key) in (None, "") else body.get(key)
    if value not in allowed:
        raise Invalid(f"Please pick one of the listed {what}.")
    return value


def _validate_animation(body):
    """Words only ever become data in a timeline; a background is named by a file name in the output folder."""
    template = _pick(body, "template", ANIM_TEMPLATES, "title", "kinds of animation")
    text = (body.get("prompt") or "").strip()
    if ANIM_TEMPLATES[template]["needs_words"] and not text:
        raise Invalid("Please type the words for this animation.")
    if len(text) > ANIM_MAX_WORDS:
        raise Invalid(f"That is too many words for an animation. Please keep it under {ANIM_MAX_WORDS} characters.")
    seconds = body.get("seconds") if body.get("seconds") not in (None, "") else 5
    try:
        seconds = float(seconds)
    except (TypeError, ValueError):
        raise Invalid("Length has to be a number of seconds.")
    if not 2 <= seconds <= 20:
        raise Invalid("Length has to be between 2 and 20 seconds.")
    params = {"prompt": text or ANIM_TEMPLATES[template]["label"], "text": text, "template": template, "seconds": seconds,
              "look": _pick(body, "look", ANIM_LOOKS, "night", "looks"), "font": _pick(body, "font", ANIM_FONTS, "clean", "typefaces"),
              "shape": _pick(body, "shape", ANIM_SHAPES, "landscape", "shapes"),
              "direction": _pick(body, "direction", ANIM_DIRECTIONS, "in", "moves"), "parent": None, "source": None}
    name = body.get("source")
    if name:
        target = safe_media_path(name) if isinstance(name, str) else None
        allowed = IMAGE_SUFFIXES if template == "move" else IMAGE_SUFFIXES | VIDEO_SUFFIXES
        if target is None or target.suffix.lower() not in allowed or target.parent != OUTPUT_DIR.resolve():
            raise Invalid("Please pick a picture from the gallery." if template == "move" else "Please pick a picture or clip from the gallery.")
        params.update(source=str(target), parent=target.name)
    elif template == "move":
        raise Invalid("Please choose a picture for the slow move.")
    return "animation", params, 0, "this animation"  # no model is loaded, so there is nothing to ask the governor


def _validate_text(body):
    text = (body.get("prompt") or "").strip()
    task = _pick(body, "task", TEXT_TASKS, "script", "kinds of writing")
    if not text:
        raise Invalid("Please say what to write about.")
    if len(text) > TEXT_MAX:
        raise Invalid(f"That is too long. Please keep it under {TEXT_MAX} characters.")
    model = DEFAULT_WRITER if body.get("model") in (None, "") else body.get("model")
    if model in WRITERS:
        if not WRITERS[model].get("tested", True):
            raise Invalid(NOT_TESTED)
        if not has_needs(WRITERS[model]):  # no address for it in the settings file
            raise Invalid(why_off(WRITERS[model]))
        need = WRITERS[model]["governor"]
    elif is_lms_writer(model):
        # A name may only be one LM Studio lists right now; the engine's listing is asked afresh, not the 15 second copy.
        rows, lmstudio = engine_writers(fresh=True)
        row = next((r for r in rows or [] if r["model"] == model), None)
        if rows is None:
            raise Invalid("The engine did not answer, so the list of writers could not be checked. Please try again in a moment.")
        if row is None:
            raise Invalid("LM Studio does not list that writer right now. Please pick another." if (lmstudio or {}).get("running")
                          else "LM Studio is not running, so its writers cannot be used right now.")
        if row.get("gb") is None:
            raise Invalid("LM Studio did not say how big that writer is, so it cannot be used safely.")
        need = 0 if row.get("loaded") else {"gb": row["gb"], "lms": model[len(LMS_PREFIX):], "ctx": LMS_CTX}
    else:
        raise Invalid("Please pick one of the listed writers.")
    length = _bounded_int(body.get("length"), 30, 300, 60, "Length")
    if length not in TEXT_LENGTHS:
        raise Invalid("Please pick one of the listed lengths.")
    about = body.get("about") if isinstance(body.get("about"), str) else ""
    params = {"prompt": text, "task": task, "model": model, "length": length, "tone": _pick(body, "tone", TEXT_TONES, "plain", "tones"),
              "target": _pick(body, "target", TEXT_TARGETS, "image", "kinds"), "about": about[:TEXT_MAX], "parent": None}
    return "text", params, need, "this writing"


def _validate_recipe(body):
    """The recipe is named by its id in the engine's book. The engine checks the values."""
    rid = body.get("recipe")
    recipe = next((r for r in recipes(fresh=True) if r["id"] == rid), None)
    if recipe is None:
        raise Invalid("Please pick one of the listed recipes.")
    values = body.get("values")
    if not isinstance(values, dict):
        raise Invalid("That request was not understood.")
    plan = recipe_plan(rid, values) or recipe.get("plan") or {}  # timed for these values, as the engine will time the run
    first_words = next((str(values.get(i["name"])) for i in recipe.get("inputs", []) if i["type"] in ("text", "long_text") and values.get(i["name"])), recipe["name"])
    params = {"recipe": rid, "values": values, "prompt": first_words, "label": recipe["name"], "parent": None,
              "estimate": plan.get("estimate_seconds") or 300}
    return "recipe", params, plan.get("memory_gb") or 0, "this recipe"


def _validate_remake(body):
    """A file named in the output folder, with a sidecar saying how to make it again."""
    name = body.get("name")
    if safe_media_path(name) is None or "/" in name:
        raise Invalid("Please pick a file from the gallery.")
    side = provenance.read(OUTPUT_DIR, name)
    if not side or not (side.get("remake") or {}).get("adapter"):
        raise Invalid("There is no record of how this was made, so it cannot be made again.")
    try:
        adapter, _ = provenance.remake_request(side, OUTPUT_DIR)
    except ValueError as e:
        raise Invalid(str(e))
    lane = RECORDS.get(name).get("lane") or side.get("lane") or "image"
    params = {"name": name, "prompt": plain_words(side.get("prompt")) or "Made again", "adapter": adapter, "lane": lane, "label": side.get("model_name"),
              "seconds": side.get("seconds"), "parent": name}
    return "remake", params, 0, "making this again"


def _validate_film(body):
    """A project's timeline, reduced to checked names and bounded numbers before the queue sees it."""
    from studio import clean_timeline
    tl = clean_timeline(body.get("timeline"))
    if not tl["clips"]:
        raise Invalid("Please put at least one picture or clip on the timeline first.")
    clips = [{"file": str(OUTPUT_DIR / c["name"]), "seconds": c["seconds"], "trim": c["trim"]} for c in tl["clips"]]
    sounds = [{"file": str(OUTPUT_DIR / s["name"]), "start": s["start"], "seconds": s["seconds"], "trim": s["trim"], "gain": s["gain"]} for s in tl["sounds"]]
    name = clean_prompt(body.get("name")) or "Film"
    return "film", {"clips": clips, "sounds": sounds, "shape": tl["shape"], "total": sum(c["seconds"] for c in clips), "prompt": name[:80], "parent": None}, 0, "this film"


_TEXT_FIELDS = ("lane", "prompt", "model", "size", "style", "voice", "tool", "template", "look", "font", "shape", "direction",
                "task", "tone", "target", "recipe", "source", "name", "parent", "lyrics", "description", "about")


def validate_create(body):
    """Returns (lane, params, memory needed in GB, what to call it). Raises Invalid in plain words."""
    for key in _TEXT_FIELDS:
        if body.get(key) is not None and not isinstance(body[key], str):
            raise Invalid("That request was not understood.")
    lane = body.get("lane")
    if lane == "film":
        return _validate_film(body)
    if lane == "recipe":
        return _validate_recipe(body)
    if lane == "remake":
        return _validate_remake(body)
    if lane in _NOT_READY:
        raise Invalid(_NOT_READY[lane])
    if lane == "edit":
        return _validate_edit(body)
    if lane == "video":
        return _validate_video(body)
    if lane == "animation":
        return _validate_animation(body)
    if lane == "text":
        return _validate_text(body)
    if lane not in RUNNERS:
        raise Invalid("Please pick one of the kinds of thing to make.")
    text = clean_prompt(body.get("prompt"))
    if not text:
        raise Invalid("Please describe what you want first.")
    if len(text) > MAX_PROMPT:
        raise Invalid(f"That is too long. Please keep it under {MAX_PROMPT} characters.")
    models = RECORDS.backend("models")
    parent = body.get("parent") if isinstance(body.get("parent"), str) else None
    if lane == "image":
        model = body.get("model") or DEFAULT_IMAGE_MODEL
        spec = IMAGE_MODELS.get(model)
        if spec is None:
            raise Invalid("That model is not one this Mac knows.")
        if not spec["routed"]:
            raise Invalid(NOT_ROUTED)
        if downloaded(spec["repo"], models) is False:
            raise Invalid("That model is not on this Mac yet.")
        size = body.get("size") or "landscape"
        if size not in sizes_available():
            raise Invalid("Please pick one of the listed sizes.")
        style = body.get("style") or "none"
        known = (RECORDS.backend("presets") or {}).get("styles") or {}
        if style != "none" and known and style not in known:
            raise Invalid("Please pick one of the listed looks.")
        steps = _bounded_int(body.get("steps"), 1, 50, spec["steps"], "Steps") or spec["steps"]
        seed = _bounded_int(body.get("seed"), 0, 2 ** 32 - 1, None, "Seed")
        if seed is None:
            seed = int.from_bytes(os.urandom(4), "big") % 2 ** 31
        params = {"prompt": text, "model": model, "size": size, "style": style, "steps": steps,
                  "seed": seed, "parent": parent, "live": bool(spec.get("live")) and body.get("live") is not False}
        gb = spec["gb"] + (LIVE_GB if params["live"] else 0)
        name = body.get("source")
        if name:
            source = safe_media_path(name) if isinstance(name, str) else None
            if source is None or source.suffix.lower() not in IMAGE_SUFFIXES or source.parent != OUTPUT_DIR.resolve():
                raise Invalid("Please pick a picture from the gallery first.")
            strength = body.get("strength")
            try:
                strength = float(0.5 if strength in (None, "") else strength)
            except (TypeError, ValueError):
                raise Invalid("Please use the slider to say how close to stay.")
            if not 0.1 <= strength <= 0.9:
                raise Invalid("Please use the slider to say how close to stay.")
            params.update(source=str(source), strength=round(strength, 2), parent=source.name, live=False)
            # A starting picture costs about 6 GB more (measured on Quick), and watching it arrive would cost 4 more.
            gb = spec["gb"] + SOURCE_GB
            meta = read_file_metadata(source)
            if meta.get("width") and meta.get("height"):
                params["source_ratio"] = f"{meta['width']}/{meta['height']}"
        return lane, params, gb, "this picture"
    if lane == "voice":
        voice = body.get("voice") or DEFAULT_VOICE
        spec = VOICES.get(voice)
        if spec is None:
            raise Invalid("That voice is not one this Mac knows.")
        if downloaded(spec.get("repo"), models) is False:
            raise Invalid("That voice is not on this Mac yet.")
        if spec.get("added") and not has_needs(spec):
            raise Invalid("That voice is not on this Mac yet. It can be added from the Models page.")
        if not any(c.isalnum() for c in text):
            raise Invalid("There are no words to read aloud here. Please type some words.")
        if spec.get("english_only") and any(c.isalpha() and ord(c) > 0x24F for c in text):
            raise Invalid(ENGLISH_ONLY)
        try:
            speed = float(body.get("speed") or 1)
        except (TypeError, ValueError):
            raise Invalid("Speed has to be a number.")
        if not 0.5 <= speed <= 2:
            raise Invalid("Speed has to be between half and double.")
        description = body.get("description") if isinstance(body.get("description"), str) else ""
        return lane, {"text": text, "voice": voice, "parent": parent, "speed": speed,
                      "description": description.strip()[:500]}, spec["gb"], "this voice"
    if downloaded(MUSIC["repo"], models) is False:
        raise Invalid("The music model is not on this Mac yet.")
    duration = _bounded_int(body.get("duration"), 5, 180, 30, "Length")
    lyrics = body.get("lyrics") if isinstance(body.get("lyrics"), str) else ""
    seed = _bounded_int(body.get("seed"), 0, 2 ** 31 - 1, -1, "Seed")
    return lane, {"prompt": text, "duration": duration, "parent": parent, "seed": seed,
                  "lyrics": lyrics.strip()[:3000] or "[instrumental]"}, MUSIC["gb"], "this music"
