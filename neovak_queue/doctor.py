"""The doctor: what this Mac has for NeoVak, lane by lane, in plain words.

Run it first on any machine:  venv/bin/python3 -m neovak_queue.doctor

It prints the Python in use, the settings file, ffmpeg, the memory check and what it sees, whether
the Mac has a network connection, and then each lane: the tools and weights that are here, the ones
that are missing and what each missing one is for. The list of needs is the same one the screen
uses to switch a lane off (neovak_queue/lanes.py), so what the doctor says and what the screen does
cannot drift apart.

Nothing here downloads anything, loads a model, or sends a request off this machine. Standard
library only. Exit code 0 when at least the picture lane can run, 1 otherwise.
"""
import os
import platform
import subprocess
import sys
from pathlib import Path

from . import lanes as _lanes
from . import memory as _memory
from . import settings as _settings

REPO = Path(__file__).resolve().parent.parent
VENV = REPO / "venv"
HF_LEAST_BYTES = 300 * 1024 * 1024  # a model folder smaller than this is a stub, not weights

# The models each lane can use, by the name a person sees and the Hugging Face repo whose weights it
# needs. Kept here rather than imported from the screen, so the doctor can run before anything else.
# The last figure is the size of a whole download in GB, measured on one Mac; a folder under half of it
# is a download that stopped part way, and will not load.
IMAGE_MODELS = [("Quick", "FLUX.2 klein 4B", "black-forest-labs/FLUX.2-klein-4B", 16),
                ("Polished", "Z-Image Turbo", "Tongyi-MAI/Z-Image-Turbo", 33),
                ("Careful", "Z-Image", "Tongyi-MAI/Z-Image", 20),
                ("Fast draft", "FLUX.1 schnell", "black-forest-labs/FLUX.1-schnell", 58),
                ("Highest detail", "FLUX.1 dev", "black-forest-labs/FLUX.1-dev", 34),
                ("Photo look", "FLUX.1 Krea dev", "black-forest-labs/FLUX.1-Krea-dev", 34),
                ("Precise", "FIBO", "briaai/FIBO", 26),
                ("Words in pictures", "Qwen-Image", "Qwen/Qwen-Image", 58)]
VOICES = [("Clear narrator", "Kokoro", "mlx-community/Kokoro-82M-bf16", 0.4),
          ("Conversational", "CSM-1B", "mlx-community/csm-1b", 6),
          ("Expressive", "Chatterbox", "mlx-community/chatterbox-fp16", 3),
          ("Described voice", "Qwen3-TTS", "Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign", 5)]
MUSIC = ("Music", "MiniMax-Music3", "mlx-community/MiniMax-Music3-4bit", 9)
EDIT = [("Change something", "FLUX.1 Kontext dev", "black-forest-labs/FLUX.1-Kontext-dev", 34),
        ("Make it bigger", "SeedVR2", "numz/SeedVR2_comfyUI", 7)]
SAVED_IMAGE = {"Fast draft": "flux-schnell-q8"}  # a quantized copy mflux saved, used before the repo when present


# ------------------------------------------------------------------ small checks
def python_words():
    v = sys.version_info
    ok = v >= _lanes.PYTHON_LEAST
    where = sys.executable
    return ok, f"Python {v.major}.{v.minor}.{v.micro} at {where}" + ("" if ok else f". NeoVak needs {_lanes.PYTHON_LEAST[0]}.{_lanes.PYTHON_LEAST[1]} or later.")


def apple_silicon():
    return platform.system() == "Darwin" and platform.machine() == "arm64"


def tool_version(path, flag="-version"):
    """The first line a tool prints for its version, or None when it is not there."""
    if not path or not Path(path).exists():
        return None
    try:
        r = subprocess.run([path, flag], capture_output=True, text=True, timeout=10)
        return (r.stdout or r.stderr).splitlines()[0][:80] if (r.stdout or r.stderr) else "present"
    except (OSError, subprocess.TimeoutExpired, IndexError):
        return "present"


def has_network():
    """Whether this Mac has a route out at all. Reads the routing table; sends nothing."""
    try:
        r = subprocess.run(["/sbin/route", "-n", "get", "default"], capture_output=True, text=True, timeout=5)
        return "gateway" in r.stdout or "interface" in r.stdout
    except (OSError, subprocess.TimeoutExpired):
        return False


def venv_has(module):
    """Whether NeoVak's own venv holds a Python package, without importing it."""
    for site in VENV.glob("lib/python3.*/site-packages"):
        if (site / module).is_dir() or list(site.glob(f"{module}-*.dist-info")):
            return True
    return False


def venv_bin(name):
    return (VENV / "bin" / name).exists()


# ------------------------------------------------------------------ weights
def hub_dirs(s):
    dirs = [root / "huggingface" / "hub" for root in s.model_roots]
    dirs.append(Path.home() / ".cache" / "huggingface" / "hub")
    seen, out = set(), []
    for d in dirs:
        if str(d) not in seen:
            seen.add(str(d))
            out.append(d)
    return out


def folder_bytes(folder):
    total = 0
    for base, _dirs, files in os.walk(folder):
        for f in files:
            p = os.path.join(base, f)
            try:
                if not os.path.islink(p):
                    total += os.lstat(p).st_size
            except OSError:
                pass
    return total


def repo_weights(repo, s):
    """(present, where, GB) for one Hugging Face repo across every cache this machine names."""
    name = "models--" + repo.replace("/", "--")
    for hub in hub_dirs(s):
        blobs = hub / name / "blobs"
        if blobs.is_dir():
            size = folder_bytes(blobs)
            if size >= HF_LEAST_BYTES:
                return True, str(hub), round(size / 1e9, 1)
    return False, "", 0.0


def saved_weights(folder_name, s):
    p = s.model_dir / folder_name
    if p.is_dir():
        size = folder_bytes(p)
        if size >= HF_LEAST_BYTES:
            return True, str(p), round(size / 1e9, 1)
    return False, "", 0.0


def writer_answers(address):
    """Whether a local text model answers at this address. Only loopback addresses are tried, so the
    doctor never sends a request off this machine."""
    from urllib.parse import urlsplit
    import http.client
    u = urlsplit(address)
    if u.hostname not in ("127.0.0.1", "localhost", "::1"):
        return None
    try:
        c = http.client.HTTPConnection(u.hostname, u.port or 80, timeout=3)
        c.request("GET", "/v1/models")
        return c.getresponse().status == 200
    except (OSError, http.client.HTTPException):
        return False


def weights_row(label, engine, repo, whole_gb, s, saved=None):
    """One line about one model's weights: here, partly here, or absent."""
    present, where, gb = repo_weights(repo, s)
    if not present and saved:
        present, where, gb = saved_weights(saved, s)
    if present and gb < whole_gb * 0.5:
        return ("absent", f"{label} ({engine}): only {gb} GB of about {whole_gb} GB from {repo} is here, so the download stopped part way and it will not load", where)
    if present:
        return ("have", f"{label} ({engine}), weights from {repo}, {gb} GB", where)
    return ("absent", f"{label} ({engine}), weights from {repo}, about {whole_gb} GB", "not in any model folder")


# ------------------------------------------------------------------ the report
def lane_report(s):
    """[(lane title, on or off, lines)] in the order the screen shows them."""
    out = []

    def needs_lines(key):
        lines = []
        for item in _lanes.requirements(s).get(key, []):
            ok = _lanes.present(item)
            lines.append(("have" if ok else "missing", item["for"], item["path"]))
        return lines

    # Pictures: mflux in the venv, then each model's weights.
    lines, on = [], venv_bin("mflux-generate")
    lines.append(("have" if on else "missing", "mflux, the picture engine, in NeoVak's own venv (setup.sh installs it)", str(VENV / "bin" / "mflux-generate")))
    any_model = False
    for label, engine, repo, whole in IMAGE_MODELS:
        row = weights_row(label, engine, repo, whole, s, SAVED_IMAGE.get(label))
        any_model = any_model or row[0] == "have"
        lines.append(row)
    if on and not any_model:
        lines.append(("note", "No picture model's weights are here yet. The Models page or the README says how to fetch one when this Mac is online.", ""))
    out.append(("Pictures", on and any_model, lines))

    # Voices
    lines, on = [], venv_has("mlx_audio")
    lines.append(("have" if on else "missing", "mlx-audio, the voice engine, in NeoVak's own venv", str(VENV)))
    lines += needs_lines("voice")
    for label, engine, repo, whole in VOICES:
        lines.append(weights_row(label, engine, repo, whole, s))
    extra = needs_lines("voice:soprano")
    lines += [(k, w if k == "have" else w + " (optional)", p) for k, w, p in extra]
    out.append(("Voices", on and not _lanes.missing("voice", s), lines))

    # Music
    lines = needs_lines("music")
    row = weights_row(*MUSIC, s)
    lines.append(row)
    out.append(("Music", not _lanes.missing("music", s) and row[0] == "have", lines))

    # Picture tools
    lines = []
    for label, engine, repo, whole in EDIT:
        lines.append(weights_row(label, engine, repo, whole, s))
    cut = needs_lines("edit:cutout")
    lines += [(k, "Remove the background: " + w, p) for k, w, p in cut]
    faces = needs_lines("edit:faces")
    lines += [(k, "Repair faces: " + w, p) for k, w, p in faces]
    out.append(("Picture tools", True, lines))

    # Video
    lines = needs_lines("video")
    for key, label in (("video:ltx-2.5-q8", "Best clip"), ("video:ltx-2.3-q8", "Lighter on memory")):
        lines += [(k, f"{label}: " + w, p) for k, w, p in needs_lines(key)]
    on = not _lanes.missing("video", s) and (not _lanes.missing("video:ltx-2.5-q8", s) or not _lanes.missing("video:ltx-2.3-q8", s))
    out.append(("Video", on, lines))

    # Animation and the film timeline
    lines = needs_lines("animation")
    out.append(("Animation and the timeline", not _lanes.missing("animation", s), lines))

    # Writing
    lines = []
    any_writer = False
    for key, label in (("text:9b", "Quick writer"), ("text:27b", "Careful writer")):
        for item in _lanes.requirements(s)[key]:
            if not item["path"]:
                lines.append(("absent", f"{label}: " + item["for"] + " (optional)", "not set"))
                continue
            answers = writer_answers(item["path"])
            any_writer = any_writer or bool(answers)
            lines.append(("have" if answers else "missing", f"{label}: " + item["for"] + ("" if answers else ", set but not answering right now"), item["path"]))
    if not any_writer:
        lines.append(("note", "Without a local text model, the Writing lane and Improve my words are switched off. Everything else works.", ""))
    out.append(("Writing", any_writer, lines))
    return out


def report(s=None):
    """The whole report as lines of text."""
    s = s or _settings.load(fresh=True)
    lines = ["NeoVak doctor", ""]
    ok, words = python_words()
    lines.append(("  " if ok else "! ") + words)
    lines.append(("  " if apple_silicon() else "! ") + f"{platform.system()} {platform.mac_ver()[0] or platform.release()} on {platform.machine()}"
                 + ("" if apple_silicon() else ". NeoVak runs on Apple Silicon Macs only."))
    lines.append(f"  Settings file: {s.path}" + ("" if s.exists else " (not there, so every value is a default; write one with: python3 -m neovak_queue.settings write-example)"))
    lines.append(f"  Finished work goes to: {s.output_dir}" + ("" if s.output_dir.exists() else " (will be created)"))
    roots = [str(r) + ("" if r.exists() else " (not there)") for r in s.model_roots]
    lines.append(f"  Model folders: {'; '.join(roots)}")
    lines.append(f"  Hugging Face cache in use: {s.hub_cache}" + ("" if s.hub_cache.exists() else " (not there yet)"))
    for name in ("ffmpeg", "ffprobe"):
        v = tool_version(s.tool(name))
        lines.append(("  " if v else "! ") + (f"{name}: {v}" if v else f"{name} is not at {s.tool(name) or '(no path set)'}. Install it with: brew install ffmpeg"))
    how = _memory.method(s)
    reading = _memory.preflight(1, s, timeout=60)
    if how == "governor":
        lines.append(("  " if reading["answered"] else "! ") + f"Memory check: the governor script {s.governor}" + ("" if reading["answered"] else " did not answer"))
    else:
        lines.append("  Memory check: the built-in simple check (vm_stat and sysctl). " + _memory.SIMPLE_WORDS)
    if reading["answered"]:
        lines.append(f"  Memory right now: {reading['available_gb']:.1f} GB available, {reading['safety_gb']:.0f} GB always kept in reserve"
                     + (f", {_memory.total_gb() * 1e9 / 2 ** 30:.0f} GB in this Mac" if _memory.total_gb() else ""))
    lines.append("  Network: " + ("this Mac has a connection. NeoVak never uses it while making things; only the Models page fetches, and only when asked."
                                  if has_network() else "no connection found. Everything that is already on this Mac still works."))
    if os.environ.get("HF_HUB_OFFLINE") == "1":
        lines.append("  HF_HUB_OFFLINE=1 is set: nothing will try to download, whatever the connection.")
    lines.append("")
    pictures_on = False
    for title, on, rows in lane_report(s):
        if title == "Pictures":
            pictures_on = on
        lines.append(f"{title}: {'ready' if on else 'switched off'}")
        for kind, words, path in rows:
            mark = {"have": "  + ", "missing": "  - ", "absent": "  - ", "note": "    "}[kind]
            tail = f"  [{path}]" if path and kind != "note" else ""
            lines.append(f"{mark}{words}{tail}")
        lines.append("")
    lines.append("A lane marked switched off is shown that way in the screen too, with the same reason. "
                 "Lines starting with - say what is missing and what it is for.")
    return lines, pictures_on


def main(argv=None):
    try:
        lines, ok = report()
    except _settings.SettingsError as e:
        print(f"! {e}")
        return 1
    print("\n".join(lines))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
