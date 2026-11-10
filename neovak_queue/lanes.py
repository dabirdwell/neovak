"""What each lane needs from this machine, in one place.

The screen (people_screen/core.py) switches a lane or a model off when something here is missing,
and the doctor (neovak_queue/doctor.py) prints the same list, so the two can never disagree.
Every entry is a path from the settings file, or built from one, with plain words for what it is for.
Standard library only.

Keys are a lane, or lane:model for one model inside a lane.
"""
from pathlib import Path

from . import settings as _settings

PYTHON_LEAST = (3, 11)


def requirements(s=None):
    """{key: [{"path": str, "for": str, "kind": "tool" or "weights" or "address"}]}"""
    s = s or _settings.load()
    video_dir = s.video_pack_dir
    req = {
        "image": [],
        "voice": [{"path": s.tool("ffmpeg"), "for": "ffmpeg, which retimes a voice for the speed control", "kind": "tool"}],
        "voice:soprano": [{"path": str(s.added_dir / "soprano-80m" / ".neovak_installed.json"),
                           "for": "the Soprano voice's weights, added from the Models page", "kind": "weights"}],
        "music": [{"path": s.tool("music_python"), "for": "the python3 of an mlx-audio environment, which runs the music model ([tools] music_python)", "kind": "tool"},
                  {"path": s.tool("ffprobe"), "for": "ffprobe, which measures the finished piece", "kind": "tool"}],
        "edit": [],
        "edit:faces": [{"path": s.tool("gfpgan"), "for": "the GFPGAN face repair weights ([tools] gfpgan)", "kind": "weights"},
                       {"path": s.tool("face_python"), "for": "a python3 with torch and spandrel, which runs the repair ([tools] face_python)", "kind": "tool"}],
        "edit:cutout": [{"path": s.tool("swiftc"), "for": "the Swift compiler, which builds the background remover once (install Xcode command line tools)", "kind": "tool"}]
                        if not s.tool("vision") else [{"path": s.tool("vision"), "for": "the compiled background and face finder ([tools] vision)", "kind": "tool"}],
        "video": [{"path": s.tool("ltx"), "for": "the ltx-2-mlx command, from its own environment ([tools] ltx)", "kind": "tool"},
                  {"path": s.tool("ffprobe"), "for": "ffprobe, which measures the finished clip", "kind": "tool"}],
        "video:ltx-2.5-q8": [{"path": str(video_dir / "ltx-2.5-mlx-q8" / "transformer-distilled.safetensors") if video_dir else "",
                              "for": "the LTX-2.5 model pack, ltx-2.5-mlx-q8, in the video models folder ([models] video)", "kind": "weights"}],
        "video:ltx-2.3-q8": [{"path": str(video_dir / "ltx-2.3-mlx-q8" / "transformer-distilled-1.1.safetensors") if video_dir else "",
                              "for": "the LTX-2.3 model pack, ltx-2.3-mlx-q8, in the video models folder ([models] video)", "kind": "weights"},
                             {"path": str(video_dir / "gemma-3-12b-it-4bit") if video_dir else "",
                              "for": "the Gemma 3 text encoder LTX-2.3 reads prompts with, in the video models folder", "kind": "weights"}],
        "animation": [{"path": s.tool("ffmpeg"), "for": "ffmpeg, which writes the finished clip", "kind": "tool"},
                      {"path": s.tool("ffprobe"), "for": "ffprobe, which measures clips", "kind": "tool"}],
        "timeline": [{"path": s.tool("ffmpeg"), "for": "ffmpeg, which cuts the film together", "kind": "tool"},
                     {"path": s.tool("ffprobe"), "for": "ffprobe, which measures each clip", "kind": "tool"}],
        "text:9b": [{"path": s.writer("quick"), "for": "a running local text model that answers like OpenAI's chat API ([writers] quick)", "kind": "address"}],
        "text:27b": [{"path": s.writer("careful"), "for": "a larger running local text model ([writers] careful)", "kind": "address"}],
    }
    return req


def present(item):
    """True when this one requirement is met. An empty path is never present."""
    path = item["path"] if isinstance(item, dict) else item
    if not path:
        return False
    if (isinstance(item, dict) and item.get("kind") == "address"):
        return True  # whether it answers is checked when it is used; the doctor tries it
    return Path(path).exists()


def missing(key, s=None):
    """The requirements under key that this machine does not meet."""
    return [item for item in requirements(s).get(key, []) if not present(item)]


def paths(key, s=None):
    """Just the paths under key, for the screen's own tables."""
    return [item["path"] for item in requirements(s).get(key, [])]


def all_present(key, s=None):
    return not missing(key, s)


def why_off(key, s=None):
    """One plain sentence for the screen when a lane or model is switched off, or ''."""
    gone = missing(key, s)
    if not gone:
        return ""
    return "Switched off on this machine. Missing: " + "; ".join(item["for"] for item in gone) + "."
