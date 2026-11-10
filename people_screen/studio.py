"""The studio's own records and helpers: projects, the model shelf and installs, the starter gallery,
and the small derived files the page shows (subject cut-outs, real waveforms, filmstrips).

core.py knows the lanes; this knows the room they sit in. Nothing here builds shell text: every process
is started from an argument list, and every file is named by a checked path.
"""
import hashlib
import json
import math
import os
import re
import signal
import struct
import subprocess
import threading
import time
import uuid
from pathlib import Path

import core

FFMPEG = core.SETTINGS.tool("ffmpeg")
FFPROBE = core.SETTINGS.tool("ffprobe")
HERE = core.HERE
UI_DIR = HERE / "ui"
STARTER_DIR = HERE / "starters"
STARTER_SUFFIXES = {".jpg", ".webp", ".png", ".mp4", ".m4a"}
UI_SUFFIXES = {".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8"}
DERIVED = core.STATE_DIR / "derived"
DERIVED.mkdir(parents=True, exist_ok=True)
VISION_TOOL = Path(os.environ.get("PS_VISION_TOOL", core.REPO / "state" / "tools" / "vision_tool"))
UPLOAD_TYPES = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp", "audio/wav": ".wav", "audio/x-wav": ".wav",
                "audio/wave": ".wav", "audio/mpeg": ".mp3", "audio/mp4": ".m4a", "audio/x-m4a": ".m4a", "video/mp4": ".mp4"}
MAX_UPLOAD = 300 * 1024 * 1024


# ------------------------------------------------------------------ small safe files for the page
def named(folder, name, suffixes):
    """A file directly inside folder, or None. Bare names only; symlinks are resolved first."""
    if not isinstance(name, str) or not name or "/" in name or "\\" in name or "\x00" in name or name.startswith(".") or core.too_long_name(name):
        return None
    try:
        root, target = Path(folder).resolve(), (Path(folder) / name).resolve()
        target.relative_to(root)
        return target if target.suffix.lower() in suffixes and target.is_file() else None  # is_file() can raise too (a name too long for the disk)
    except (ValueError, OSError, RuntimeError):
        return None


def _derived_path(source, extra, suffix):
    stat = source.stat()
    key = hashlib.sha256(f"{source}:{stat.st_mtime_ns}:{stat.st_size}:{extra}".encode()).hexdigest()[:32]
    return DERIVED / (key + suffix)


def subject_layer(source, max_side=1400):
    """The main subject of a picture on transparent pixels, made once by Apple's Vision framework and
    kept. None when no subject is found or the tool is not on this machine. No model is loaded."""
    target = _derived_path(source, f"lift{max_side}", ".webp")
    none = target.with_suffix(".none")
    if target.exists():
        return target
    if none.exists() or not VISION_TOOL.exists():
        return None
    from PIL import Image
    tmp = target.with_suffix(f".{os.getpid()}.{threading.get_ident()}.png")
    try:
        done = subprocess.run([str(VISION_TOOL), "cutout", str(source), str(tmp)], capture_output=True, timeout=30)
        if done.returncode != 0 or not tmp.exists():
            none.touch()
            return None
        with Image.open(tmp) as im:
            im = im.convert("RGBA")
            alpha = im.getchannel("A")
            box = alpha.getbbox()
            covered = sum(alpha.histogram()[128:]) / max(1, im.width * im.height)
            # A subject that is nearly the whole frame, or a speck, gives nothing to lift.
            if not box or not 0.02 <= covered <= 0.8:
                none.touch()
                return None
            im.thumbnail((max_side, max_side))
            im.save(target, "WEBP", quality=88, alpha_quality=90, method=3)
        return target
    except (OSError, subprocess.TimeoutExpired):
        return None
    finally:
        tmp.unlink(missing_ok=True)


def media_seconds(path):
    """How long a clip or sound runs, in seconds, or None. Kept beside the other derived files."""
    target = _derived_path(path, "dur", ".json")
    try:
        return json.loads(target.read_text())["seconds"]
    except (OSError, ValueError, KeyError):
        pass
    try:
        r = subprocess.run([FFPROBE, "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)],
                           capture_output=True, text=True, timeout=30)
        seconds = float(json.loads(r.stdout or "{}").get("format", {}).get("duration") or 0) or None
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None
    if seconds:
        target.write_text(json.dumps({"seconds": seconds}))
    return seconds


def waveform(path, points=240):
    """The real shape of a sound as points from 0 to 1, read from its samples with ffmpeg."""
    target = _derived_path(path, f"peaks{points}", ".json")
    try:
        return json.loads(target.read_text())
    except (OSError, ValueError):
        pass
    try:
        r = subprocess.run([FFMPEG, "-nostdin", "-v", "error", "-i", str(path), "-map", "0:a:0", "-ac", "1", "-ar", "4000", "-f", "f32le", "-"],
                           capture_output=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired):
        return None
    raw = r.stdout
    if r.returncode != 0 or len(raw) < 8:
        return None
    count = len(raw) // 4
    step = max(1, count // points)
    samples = struct.unpack(f"<{count}f", raw[:count * 4])
    peaks = [max(abs(x) for x in samples[i:i + step] or [0]) for i in range(0, count, step)]
    top = max(peaks) or 1.0
    # A square root keeps quiet speech visible beside loud peaks, which is how waveform displays read.
    result = {"peaks": [round(math.sqrt(p / top), 3) for p in peaks[:points]], "seconds": count / 4000}
    target.write_text(json.dumps(result))
    return result


def film_strip(path, frames=10):
    """Evenly spaced frames from a clip, side by side in one JPEG, so a timeline shows what is really in it."""
    target = _derived_path(path, f"strip{frames}", ".jpg")
    if target.exists():
        return target
    seconds = media_seconds(path) or 1
    tmp = target.with_suffix(f".{os.getpid()}.jpg")
    try:
        r = subprocess.run([FFMPEG, "-nostdin", "-y", "-v", "error", "-i", str(path), "-vf",
                            f"fps={frames / max(seconds, 0.1):.4f},scale=160:90:force_original_aspect_ratio=increase,crop=160:90,tile={frames}x1",
                            "-frames:v", "1", "-q:v", "5", str(tmp)], capture_output=True, timeout=120)
        if r.returncode != 0 or not tmp.exists():
            return None
        tmp.rename(target)
        return target
    except (OSError, subprocess.TimeoutExpired):
        return None
    finally:
        tmp.unlink(missing_ok=True)


def peek_frame(job_id):
    """The newest frame the engine has written for a job that is still running, or None."""
    return None


# ------------------------------------------------------------------ taking in a file from outside
def take_upload(content_type, data):
    """A file a person dropped in becomes a new file in the output folder, checked for what it claims
    to be. The name is always ours. Returns its gallery name, or raises core.Invalid in plain words."""
    suffix = UPLOAD_TYPES.get((content_type or "").split(";")[0].strip().lower())
    if suffix is None:
        raise core.Invalid("That kind of file cannot be used here. Pictures, MP4 clips and sound files can.")
    if not data:
        raise core.Invalid("That file was empty.")
    if len(data) > MAX_UPLOAD:
        raise core.Invalid("That file is too large. Please use one under 300 MB.")
    name = core.new_output_name("neovak_upload", uuid.uuid4().hex, suffix if suffix in core.VIDEO_SUFFIXES | {".wav", ".mp3", ".m4a"} else ".png")
    part = core.OUTPUT_DIR / f".part_{name}"
    try:
        if suffix in core.IMAGE_SUFFIXES:
            from io import BytesIO

            from PIL import Image, ImageOps
            try:
                with Image.open(BytesIO(data)) as im:
                    im.load()
                    if im.width * im.height > 36_000_000:
                        raise core.Invalid("That picture is too large. Please use one under 36 megapixels.")
                    # Saving through the decoder keeps only pixels, so nothing hidden in the file comes along.
                    ImageOps.exif_transpose(im).convert("RGBA" if "A" in im.getbands() else "RGB").save(part, "PNG")
            except core.Invalid:
                raise
            except Image.DecompressionBombError:  # the library refuses very large pictures before our own count
                raise core.Invalid("That picture is too large. Please use one under 36 megapixels.")
            except Exception:
                raise core.Invalid("That file could not be read as a picture.")
        else:
            part.write_bytes(data)
            r = subprocess.run([FFPROBE, "-v", "error", "-show_entries", "stream=codec_type:format=duration", "-of", "json", str(part)],
                               capture_output=True, text=True, timeout=60)
            try:
                info = json.loads(r.stdout or "{}")
                kinds = {s.get("codec_type") for s in info.get("streams") or []}
                seconds = float((info.get("format") or {}).get("duration") or 0)
            except (ValueError, TypeError):
                kinds, seconds = set(), 0
            wanted = "video" if suffix in core.VIDEO_SUFFIXES else "audio"
            if r.returncode != 0 or wanted not in kinds or seconds <= 0:
                raise core.Invalid("That file could not be read.")
        os.replace(part, core.OUTPUT_DIR / name)
    finally:
        part.unlink(missing_ok=True)
    core.RECORDS.update(name, lane="upload", model_label="Added by you", created=time.strftime("%Y-%m-%dT%H:%M:%S"))
    return name


# ------------------------------------------------------------------ projects
class Projects:
    """state/projects.json. A project is a named set of files plus one timeline, so its gallery and
    its timeline are two views of the same thing. Only file names are stored."""

    def __init__(self, path=None):
        self.path = Path(path or core.STATE_DIR / "projects.json")
        self.lock = threading.Lock()
        self.data = {"active": None, "projects": {}}
        try:
            self.data.update(json.loads(self.path.read_text()))
        except (OSError, json.JSONDecodeError):
            pass
        with self.lock:
            if not self.data["projects"]:
                self._create("First project")

    def _save(self):
        tmp = self.path.with_name(f".{self.path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
        tmp.write_text(json.dumps(self.data, indent=1))
        os.replace(tmp, self.path)

    # Each person has their own open project ("chosen", by person id); "active" is the one for anyone who has not
    # chosen yet, and for work that arrives without a person (the chat tools). One person switching projects never
    # moves another person's work into it.
    def _create(self, name, person=None):
        pid = uuid.uuid4().hex[:10]
        self.data["projects"][pid] = {"id": pid, "name": name, "created": time.time(), "items": [], "timeline": {"clips": [], "sounds": [], "shape": "landscape"}}
        if person:
            self.data.setdefault("chosen", {})[person] = pid
        else:
            self.data["active"] = pid
        self._save()
        return self.data["projects"][pid]

    def _open_for(self, person):
        pid = (self.data.get("chosen") or {}).get(person) if person else None
        if pid in self.data["projects"]:
            return pid
        return self.data["active"] if self.data["active"] in self.data["projects"] else next(iter(self.data["projects"]), None)

    def _view(self, p):
        # the count the Gallery shows for this project: pieces still on disk and not hidden, not every name ever added
        hidden = core.RECORDS.hidden()
        def listed(n):  # the same rule the Gallery's scan uses
            low = n.lower(); suffix = Path(low).suffix
            return (suffix in core.MEDIA_SUFFIXES and "_thumb." not in low and "_mask." not in low and not n.startswith(".")
                    and (suffix not in core.TEXT_SUFFIXES or low.startswith(core.TEXT_PREFIX)))
        count = sum(1 for n in p["items"] if n not in hidden and listed(n) and (core.OUTPUT_DIR / n).is_file())
        return {"id": p["id"], "name": p["name"], "count": count, "created": p["created"], "timeline": p["timeline"]}

    def open_for(self, person=None):
        with self.lock:
            return self._open_for(person)

    def listing(self, person=None):
        with self.lock:
            return {"active": self._open_for(person), "projects": sorted((self._view(p) for p in self.data["projects"].values()), key=lambda x: x["created"])}

    def create(self, name, person=None):
        with self.lock:
            return self._view(self._create(name, person))

    def rename(self, pid, name):
        with self.lock:
            p = self.data["projects"].get(pid)
            if p is None:
                return None
            p["name"] = name
            self._save()
            return self._view(p)

    def activate(self, pid, person=None):
        with self.lock:
            if pid not in self.data["projects"]:
                return False
            if person:
                self.data.setdefault("chosen", {})[person] = pid
            else:
                self.data["active"] = pid
            self._save()
            return True

    def remove(self, pid):
        """Takes away the project and its timeline. The files themselves are never removed."""
        with self.lock:
            if pid not in self.data["projects"] or len(self.data["projects"]) == 1:
                return False
            del self.data["projects"][pid]
            if self.data["active"] == pid:
                self.data["active"] = max(self.data["projects"].values(), key=lambda p: p["created"])["id"]
            chosen = self.data.get("chosen") or {}
            for who in [w for w, p in chosen.items() if p == pid]:
                del chosen[who]  # they go back to the shared one
            self._save()
            return True

    def items(self, pid):
        with self.lock:
            p = self.data["projects"].get(pid)
            return list(p["items"]) if p else None

    def add(self, name, pid=None, person=None):
        with self.lock:
            p = self.data["projects"].get(pid or self._open_for(person))
            if p is None:
                return False
            if name not in p["items"]:
                p["items"].append(name)
                self._save()
            return True

    def drop(self, pid, name):
        with self.lock:
            p = self.data["projects"].get(pid)
            if p is None or name not in p["items"]:
                return False
            p["items"].remove(name)
            p["timeline"]["clips"] = [c for c in p["timeline"]["clips"] if c["name"] != name]
            p["timeline"]["sounds"] = [s for s in p["timeline"]["sounds"] if s["name"] != name]
            self._save()
            return True

    def get(self, pid):
        with self.lock:
            p = self.data["projects"].get(pid)
            return json.loads(json.dumps(p)) if p else None

    def set_timeline(self, pid, timeline):
        with self.lock:
            p = self.data["projects"].get(pid)
            if p is None:
                return False
            p["timeline"] = timeline
            for name in [c["name"] for c in timeline["clips"]] + [s["name"] for s in timeline["sounds"]]:
                if name not in p["items"]:
                    p["items"].append(name)
            self._save()
            return True


def _seconds_of(value, low, high, what):
    try:
        n = float(value)
    except (TypeError, ValueError):
        raise core.Invalid(f"{what} has to be a number.")
    if not (low <= n <= high) or math.isnan(n):
        raise core.Invalid(f"{what} has to be between {low} and {high}.")
    return round(n, 3)


def clean_timeline(body):
    """What the page sent, reduced to checked names and bounded numbers. Raises core.Invalid."""
    if not isinstance(body, dict):
        raise core.Invalid("That request was not understood.")
    clips, sounds = [], []
    if not isinstance(body.get("clips", []), list) or not isinstance(body.get("sounds", []), list):
        raise core.Invalid("That request was not understood.")
    if len(body.get("clips", [])) > 60 or len(body.get("sounds", [])) > 24:
        raise core.Invalid("A timeline holds up to 60 pictures or clips and 24 sounds.")
    for c in body.get("clips", []):
        path = core.safe_media_path(c.get("name")) if isinstance(c, dict) else None
        if path is None or path.parent != core.OUTPUT_DIR.resolve() or path.suffix.lower() not in core.IMAGE_SUFFIXES | core.VIDEO_SUFFIXES:
            raise core.Invalid("One of the items on the timeline is not a picture or clip in the output folder.")
        clips.append({"name": path.name, "seconds": _seconds_of(c.get("seconds"), 0.2, 300, "Length"), "trim": _seconds_of(c.get("trim") or 0, 0, 3600, "Trim")})
    audio = {".wav", ".mp3", ".m4a"}
    for s in body.get("sounds", []):
        path = core.safe_media_path(s.get("name")) if isinstance(s, dict) else None
        if path is None or path.parent != core.OUTPUT_DIR.resolve() or path.suffix.lower() not in audio:
            raise core.Invalid("One of the sounds on the timeline is not a sound in the output folder.")
        sounds.append({"name": path.name, "start": _seconds_of(s.get("start") or 0, 0, 900, "Start"), "seconds": _seconds_of(s.get("seconds"), 0.1, 900, "Length"),
                       "trim": _seconds_of(s.get("trim") or 0, 0, 3600, "Trim"), "gain": _seconds_of(1 if s.get("gain") is None else s.get("gain"), 0, 2, "Volume")})
    shape = body.get("shape") if body.get("shape") in ("landscape", "portrait", "square") else "landscape"
    return {"clips": clips, "sounds": sounds, "shape": shape}


# ------------------------------------------------------------------ the frames of a picture still being made
def peek_image(path, max_side=760):
    """A small JPEG of one step's frame, so a phone is not sent a full size picture every few seconds."""
    from PIL import Image
    source = Path(path)
    target = _derived_path(source, f"peek{max_side}", ".jpg")
    if not target.exists():
        with Image.open(source) as im:
            im.load()
            im.thumbnail((max_side, max_side))
            im.convert("RGB").save(target, "JPEG", quality=70)
    return target


# ------------------------------------------------------------------ the model shelf
# Every folder that may hold weights comes from the settings file.
HF_HUBS = [str(root / "huggingface" / "hub") for root in core.SETTINGS.model_roots] + [str(Path.home() / ".cache/huggingface/hub")]
_VIDEO_DIR = core.SETTINGS.video_pack_dir
FOLDERS = {
    "schnell": str(core.SETTINGS.model_dir / "flux-schnell-q8"),
}
if _VIDEO_DIR:
    FOLDERS.update({"ltx-2.5-q8": str(_VIDEO_DIR / "ltx-2.5-mlx-q8"), "ltx-2.3-q8": str(_VIDEO_DIR / "ltx-2.3-mlx-q8")})
_shelf = {"at": 0.0, "sizes": {}, "running": False}


def _folder_bytes(folder):
    total = 0
    for base, _dirs, files in os.walk(folder):
        for f in files:
            try:
                st = os.lstat(os.path.join(base, f))
                if not os.path.islink(os.path.join(base, f)):
                    total += st.st_size
            except OSError:
                pass
    return total


def repo_bytes(repo):
    """Real bytes of one model in the Hugging Face caches. Blobs only: the snapshot folder is links."""
    best = 0
    for hub in HF_HUBS:
        blobs = Path(hub) / ("models--" + repo.replace("/", "--")) / "blobs"
        if blobs.is_dir():
            best = max(best, _folder_bytes(blobs))
    return best


def refresh_shelf():
    if _shelf["running"]:
        return
    _shelf["running"] = True

    def work():
        sizes = {}
        try:
            specs = [*core.IMAGE_MODELS.items(), *core.VOICES.items(), *core.EDIT_TOOLS.items(), ("music", core.MUSIC)]
            for key, spec in specs:
                if spec.get("repo"):
                    sizes[spec["repo"]] = repo_bytes(spec["repo"])
            for key, folder in FOLDERS.items():
                if Path(folder).is_dir():
                    sizes[folder] = _folder_bytes(folder)
            for offer in OFFERS:
                d = Path(offer["dest"])
                if d.is_dir():
                    sizes[str(d)] = _folder_bytes(d)
            _shelf.update(sizes=sizes, at=time.time())
        finally:
            _shelf["running"] = False
    threading.Thread(target=work, daemon=True).start()


def shelf_size(key):
    return round(_shelf["sizes"].get(key, 0) / 1e9, 1)


# Every entry here has been read by a person: an open licence, a size under the limit, and a run on this Mac.
INSTALL_ROOT = str(core.SETTINGS.added_dir)
LIMIT_BYTES = 10_000_000_000
OPEN_LICENCES = "apache-2.0,mit"
OFFERS = [
    {"id": "soprano-80m", "label": "Quick and light", "lane": "voice", "engine": "Soprano 80M", "repo": "mlx-community/Soprano-80M-bf16",
     "revision": "b7da048eff3dfd556409a44b78b9c61a9dd4ccfa", "gb_download": 0.22, "gb_memory": 2, "licence": "Apache 2.0",
     "note": "A very small, quick voice. Adds one more choice to the Voice lane.", "dest": INSTALL_ROOT + "/soprano-80m"},
]
NOT_OFFERED = [
    {"label": "Fish S2 Pro", "lane": "voice", "why": "An 11 GB download with a licence that limits use. It is over the size this page will fetch."},
    {"label": "Z-Image Union ControlNet", "lane": "image", "why": "A 53 GB download, which is over the size this page will fetch."},
    {"label": "FLUX.1 Fill dev", "lane": "image", "why": "Its licence restricts use, and it is a very large download."},
    {"label": "FLUX.2 dev", "lane": "image", "why": "Not available in a form this Mac can run."},
]
_installs = {}


def _offer(oid):
    return next((o for o in OFFERS if o["id"] == oid), None)


def offer_view(offer):
    dest = Path(offer["dest"])
    installed = (dest / ".neovak_installed.json").is_file()
    run = _installs.get(offer["id"])
    state = "installed" if installed else (run["state"] if run else "available")
    view = {k: offer[k] for k in ("id", "label", "lane", "engine", "gb_download", "gb_memory", "licence", "note")}
    view.update(state=state, message=(run or {}).get("message", ""), done_gb=None)
    if run and run["state"] == "running":
        view["done_gb"] = round(_folder_bytes(dest) / 1e9, 3) if dest.is_dir() else 0
    if installed:
        view["size_gb"] = round(_folder_bytes(dest) / 1e9, 2)
    return view


_usual = {"at": 0.0, "seconds": {}}

# What each group's times on the Models page are for: the settings each lane opens with. Said on the page, so a figure in
# a lane that differs (a longer clip, a picture watched as it arrives) differs for a reason the person can read.
USUAL_BASIS = {
    "image": "Times are for one landscape picture at the usual number of steps, without watching it arrive. Watching it arrive asks for 4 GB more memory and takes longer.",
    "voice": "Times are for one short sentence. Longer words take longer.",
    "music": "The time is for a 30 second piece. Longer pieces take longer.",
    "edit": "Make it bigger is timed at 2 times larger.",
    "video": "Times are for a 5 second clip. Shorter clips take less time, longer ones more.",
    "text": "Times are for a one minute script.",
}


def usual_seconds():
    """Each model's time for the settings its lane opens with, from core.estimate_options, the same function the Studio's
    cards, chip and working screen use, so the Models page and a lane on its usual settings show the same figure, rounded
    the same way. Kept for 20 seconds."""
    if time.time() - _usual["at"] < 20 and _usual["seconds"]:
        return _usual["seconds"]
    out = {}
    try:
        out.update(core.estimate_options("image", {"size": "landscape", "live": False})["options"])
        out.update(core.estimate_options("voice", {})["options"])
        out["music"] = core.estimate_options("music", {"duration": 30})["chosen"]
        out.update(core.estimate_options("edit", {"scale": 2})["options"])
        out.update(core.estimate_options("video", {"seconds": 5, "shape": "landscape"})["options"])
        out.update(core.estimate_options("text", {"task": "script", "length": 60})["options"])
    except Exception:  # noqa: BLE001  the page still draws, with each model's own figure
        return _usual["seconds"]
    _usual.update(at=time.time(), seconds=out)
    return out


def models_page(reading, fit=None, running=False):
    cat = core.catalog(fit or reading)
    if time.time() - _shelf["at"] > 600:
        refresh_shelf()
    speed = {k: s.get("seconds") for k, s in {**core.IMAGE_MODELS, **core.VOICES}.items()}
    usual = usual_seconds()
    def shelf_row(row, spec, key):
        size_key = spec.get("repo") or FOLDERS.get(key, "")
        disk = row.get("disk_gb") if row.get("disk_gb") is not None else shelf_size(size_key)  # a writer in LM Studio brings its own size
        return dict(row, disk_gb=disk, seconds=usual.get(key) or row.get("seconds") or speed.get(key) or spec.get("seconds"), use=key, note=row.get("note_full") or row.get("note", ""))
    groups = [
        {"lane": "image", "title": "Pictures", "rows": [shelf_row(r, core.IMAGE_MODELS[r["id"]], r["id"]) for r in cat["image_models"]]},
        {"lane": "voice", "title": "Voices", "rows": [shelf_row(r, core.VOICES[r["id"]], r["id"]) for r in cat["voices"]]},
        {"lane": "music", "title": "Music", "rows": [shelf_row(cat["music"], core.MUSIC, "music")]},
        {"lane": "edit", "title": "Picture tools", "rows": [shelf_row(r, core.EDIT_TOOLS[r["id"]], r["id"]) for r in cat["edit_tools"]]},
        {"lane": "video", "title": "Video", "rows": [shelf_row(r, core.VIDEO_MODELS[r["id"]], r["id"]) for r in cat["video_models"]]},
        {"lane": "text", "title": "Writing helpers", "rows": [shelf_row(r, core.WRITERS.get(r["id"], {}), r["id"]) for r in cat["writers"]]},
    ]
    for g in groups:
        g["basis"] = USUAL_BASIS.get(g["lane"], "")
    try:
        out = subprocess.run(["/bin/df", "-k", _nearest_existing(INSTALL_ROOT)], capture_output=True, text=True, timeout=5).stdout.splitlines()[-1].split()
        free_gb = round(int(out[3]) * 1024 / 1e9)
    except (OSError, IndexError, ValueError, subprocess.TimeoutExpired):
        free_gb = None
    judged = fit or reading  # the figure every fit badge on this page was judged against, so the page can say so in one place
    check = core.memory_method()
    return {"memory": {"available_gb": reading.get("available_gb"), "safety_gb": reading.get("safety_gb"), "total_gb": total_memory_gb(),
                       "judged_gb": judged.get("available_gb"), "quiet": bool(judged.get("quiet")), "wait": bool(judged.get("wait")), "running": bool(running),
                       "method": check["method"], "method_words": check["words"]},
            "groups": groups, "offers": [offer_view(o) for o in OFFERS], "not_offered": NOT_OFFERED, "disk_free_gb": free_gb,
            "added_dir": INSTALL_ROOT}


def _nearest_existing(path):
    """The folder itself, or the closest parent that exists, so df can answer before the folder is made."""
    p = Path(path)
    while not p.exists() and p != p.parent:
        p = p.parent
    return str(p)


_total = {"gb": None}


def total_memory_gb():
    """The Mac's memory in whole GB (as Apple writes it), read once from sysctl."""
    if _total["gb"] is None:
        try:
            r = subprocess.run(["/usr/sbin/sysctl", "-n", "hw.memsize"], capture_output=True, text=True, timeout=5)
            _total["gb"] = round(int(r.stdout.strip()) / 2 ** 30)
        except (OSError, ValueError, subprocess.TimeoutExpired):
            _total["gb"] = 64
    return _total["gb"]


def start_install(oid):
    offer = _offer(oid)
    if offer is None:
        raise core.Invalid("That is not one of the models offered here.")
    if (Path(offer["dest"]) / ".neovak_installed.json").is_file():
        return offer_view(offer)
    if _installs.get(oid, {}).get("state") == "running":
        return offer_view(offer)
    Path(offer["dest"]).parent.mkdir(parents=True, exist_ok=True)
    log = core.STATE_DIR / "logs" / f"install_{oid}.log"
    cmd = [core.VENV_PY, str(HERE / "install_runner.py"), offer["repo"], offer["revision"], offer["dest"], str(LIMIT_BYTES), OPEN_LICENCES]
    with open(log, "w") as fh:
        proc = subprocess.Popen(cmd, stdout=fh, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, start_new_session=True, env={k: v for k, v in os.environ.items() if k != "HF_HUB_OFFLINE"})
    run = {"state": "running", "proc": proc, "message": ""}
    _installs[oid] = run

    def wait():
        code = proc.wait()
        import shutil as _shutil
        if run.get("stopping"):
            run.update(state="available", message="Stopped. Nothing was kept.")
            _shutil.rmtree(offer["dest"], ignore_errors=True)
        elif code == 3:
            run.update(state="available", message="Its licence or size has changed since this page was written, so it was not downloaded.")
            _shutil.rmtree(offer["dest"], ignore_errors=True)
        elif code != 0:
            run.update(state="available", message="The download did not finish. Nothing was kept. Please try again.")
            _shutil.rmtree(offer["dest"], ignore_errors=True)
        else:
            run.update(state="installed", message="")
            refresh_shelf()
    threading.Thread(target=wait, daemon=True).start()
    return offer_view(offer)


def stop_install(oid):
    run = _installs.get(oid) if isinstance(oid, str) else None
    if not run or run["state"] != "running":
        return False
    run["stopping"] = True
    try:
        os.killpg(run["proc"].pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    return True


# ------------------------------------------------------------------ the starter gallery
def starter_manifest():
    try:
        return json.loads((STARTER_DIR / "manifest.json").read_text())
    except (OSError, json.JSONDecodeError):
        return {"images": [], "looks": [], "voices": [], "music": [], "video": [], "animation": [], "writing": [], "edit": []}
