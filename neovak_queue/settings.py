"""Everything about this machine, in one file.

NeoVak reads /Users/<you>/.config/neovak/settings.toml, or the file named by the NEOVAK_SETTINGS
environment variable. Nothing else in the code names a folder, a drive, an outside tool, a memory
check, a nightly window or a network address: they all come from here. Standard library only, so
the screen, the engine and the doctor can import it without any model code.

Every value has a default that suits a Mac that has never seen NeoVak, so a missing file is not an
error: the doctor says what the defaults are and where they point. An environment variable that
the start scripts already use (NEOVAK_OUTPUT_DIR, NEOVAK_STATE_DIR, PS_OUTPUT_DIR, PS_STATE_DIR,
PS_BACKEND, MFLUX_CACHE_DIR, NEOVAK_GOVERNOR, PS_GOVERNOR, NEOVAK_EXTRA_HOSTS) still wins over the
file, so a test copy can run beside the real thing with the same settings file.

The groups, with the keys each one takes:

  [folders]   output, state, screen_state
  [models]    roots (a list), mflux, video, added
  [tools]     music_python, ltx, face_python, gfpgan, vision, ffmpeg, ffprobe, swiftc
  [memory]    governor, governor_python, reserve_gb
  [hold]      start, end, zone        (empty start means no nightly window)
  [hosts]     engine (a list), screen (a list)
  [writers]   quick, careful          (addresses of the local text models; empty means none)

Run this file to see the values in use and where each came from:
  python3 -m neovak_queue.settings
  python3 -m neovak_queue.settings write-example /tmp/settings.toml
"""
import os
import shutil
import sys
from datetime import time as dtime
from pathlib import Path

try:
    import tomllib  # Python 3.11 and later
except ImportError:  # pragma: no cover
    tomllib = None

DEFAULT_PATH = Path.home() / ".config" / "neovak" / "settings.toml"
REPO = Path(__file__).resolve().parent.parent
_HOME = str(Path.home())

# Each key: (group, name, default, environment variables that override it, in order, what it is for).
KEYS = [
    ("folders", "output", _HOME + "/Documents/NeoVak", ("NEOVAK_OUTPUT_DIR", "PS_OUTPUT_DIR"),
     "Where finished pictures, clips, sounds and writing are saved."),
    ("folders", "state", str(REPO / "state"), ("NEOVAK_STATE_DIR",),
     "Where the engine keeps its line of jobs and its run history."),
    ("folders", "screen_state", str(REPO / "people_screen" / "state"), ("PS_STATE_DIR",),
     "Where the screen keeps its own records, thumbnails and logs."),
    ("models", "roots", [], (),
     "Every folder that holds model weights. The doctor and the Models page look here."),
    ("models", "mflux", _HOME + "/.cache", ("MFLUX_CACHE_DIR",),
     "The picture models' folder. Its huggingface subfolder is the Hugging Face cache (HF_HOME)."),
    ("models", "video", "", (),
     "The folder that holds the LTX video packs (ltx-2.5-mlx-q8, ltx-2.3-mlx-q8)."),
    ("models", "added", _HOME + "/.cache/neovak-added", (),
     "Where models added from the Models page are kept."),
    ("tools", "music_python", "", (),
     "The python3 of the mlx-audio environment that runs the music model."),
    ("tools", "ltx", "", (),
     "The ltx-2-mlx command, from its own environment, for video clips."),
    ("tools", "face_python", "", (),
     "A python3 with torch and spandrel, for face repair."),
    ("tools", "gfpgan", "", (),
     "The GFPGANv1.4.pth weights, for face repair."),
    ("tools", "vision", "", (),
     "The compiled Vision helper. Empty means build it from tools/vision_tool.swift when first needed."),
    ("tools", "ffmpeg", shutil.which("ffmpeg") or "/opt/homebrew/bin/ffmpeg", (),
     "ffmpeg, for sound, clips and the timeline."),
    ("tools", "ffprobe", shutil.which("ffprobe") or "/opt/homebrew/bin/ffprobe", (),
     "ffprobe, to measure finished sound and clips."),
    ("tools", "swiftc", "/usr/bin/swiftc", (),
     "The Swift compiler, to build the Vision helper once."),
    ("memory", "governor", "", ("NEOVAK_GOVERNOR", "PS_GOVERNOR"),
     "A memory check script that answers 'preflight <GB>'. Empty means the built-in simple check."),
    ("memory", "governor_python", "/opt/homebrew/bin/python3", (),
     "The python3 that runs the memory check script."),
    ("memory", "reserve_gb", 4.0, (),
     "Memory always kept free, on top of what a model needs."),
    ("hold", "start", "", (),
     "Start of a daily window when no model may load, as HH:MM. Empty means no window."),
    ("hold", "end", "", (),
     "End of that window, as HH:MM."),
    ("hold", "zone", "America/Chicago", (),
     "The time zone of that window."),
    ("hosts", "engine", ["127.0.0.1", "localhost"], (),
     "The names and addresses the engine answers to. Anything else is refused."),
    ("hosts", "screen", ["127.0.0.1"], (),
     "The addresses the screen listens on and answers to."),
    ("writers", "quick", "", (),
     "Address of a running local text model for the Writing lane. Empty means none."),
    ("writers", "careful", "", (),
     "Address of a larger local text model. Empty means none."),
]
_INDEX = {(g, k): (d, envs, why) for g, k, d, envs, why in KEYS}
_cache = {}


class SettingsError(Exception):
    """The settings file could not be read. The message says why, in plain words."""


WILDCARD_HOSTS = ("", "0.0.0.0", "::", "[::]", "*", "0")  # addresses that mean every network at once, never allowed


def _expand(value):
    if isinstance(value, str):
        return os.path.expanduser(os.path.expandvars(value)) if value else value
    if isinstance(value, list):
        return [_expand(v) for v in value]
    return value


class Settings:
    """The values in use. Every group is a plain attribute: settings.folders['output']."""

    def __init__(self, data, path, exists):
        self.path = Path(path)
        self.exists = exists
        self.origin = {}
        self.values = {}
        for group, key, default, envs, _why in KEYS:
            value, source = default, "default"
            found = (data.get(group) or {}).get(key) if isinstance(data.get(group), dict) else None
            if found is not None:
                if type(found) is not type(default) and not (isinstance(default, float) and isinstance(found, int)):
                    raise SettingsError(f"In {path}, [{group}] {key} should be "
                                        f"{'a list' if isinstance(default, list) else 'a number' if isinstance(default, float) else 'text in quotes'}.")
                value, source = found, "file"
            for env in envs:
                if os.environ.get(env):
                    value, source = os.environ[env], "environment " + env
                    break
            self.values.setdefault(group, {})[key] = _expand(value)
            self.origin[(group, key)] = source
        self._extra_hosts()
        for which in ("screen", "engine"):
            wild = [h for h in self.values["hosts"][which] if str(h).strip() in WILDCARD_HOSTS]
            if wild:
                raise SettingsError(f"In {path}, [hosts] {which} lists {', '.join(repr(h) for h in wild)}, which would listen on "
                                    "every network this Mac is on. Name the addresses themselves instead, such as 127.0.0.1 "
                                    "and this Mac's address on your private network.")

    def _extra_hosts(self):
        extra = [h.strip() for h in os.environ.get("NEOVAK_EXTRA_HOSTS", "").split(",") if h.strip()]
        if extra:
            self.values["hosts"]["engine"] = self.values["hosts"]["engine"] + extra
            self.origin[("hosts", "engine")] += " and environment NEOVAK_EXTRA_HOSTS"

    def __getattr__(self, name):
        if name in ("folders", "models", "tools", "memory", "hold", "hosts", "writers"):
            return self.values[name]
        raise AttributeError(name)

    # -------------------------------------------------------------- the handy shapes
    @property
    def output_dir(self):
        return Path(self.folders["output"])

    @property
    def state_dir(self):
        return Path(self.folders["state"])

    @property
    def screen_state_dir(self):
        return Path(self.folders["screen_state"])

    @property
    def model_dir(self):
        return Path(self.models["mflux"])

    @property
    def hub_cache(self):
        return self.model_dir / "huggingface"

    @property
    def model_roots(self):
        """Every folder that may hold weights, without repeats, the named ones first."""
        seen, out = set(), []
        for p in [self.models["mflux"], self.models["video"], self.models["added"], *self.models["roots"]]:
            if p and p not in seen:
                seen.add(p)
                out.append(Path(p))
        return out

    @property
    def video_pack_dir(self):
        return Path(self.models["video"]) if self.models["video"] else None

    @property
    def added_dir(self):
        return Path(self.models["added"])

    def tool(self, name):
        """The path of one outside tool, or '' when this machine has none set."""
        return self.tools.get(name, "")

    @property
    def governor(self):
        return self.memory["governor"]

    @property
    def governor_python(self):
        return self.memory["governor_python"]

    @property
    def reserve_gb(self):
        return float(self.memory["reserve_gb"])

    def hold_window(self):
        """(start, end, zone) as time objects and a ZoneInfo, or None when this machine has no window."""
        start, end = self.hold["start"], self.hold["end"]
        if not start or not end:
            return None
        try:
            from zoneinfo import ZoneInfo
            return _parse_clock(start), _parse_clock(end), ZoneInfo(self.hold["zone"] or "UTC")
        except (ValueError, KeyError) as e:
            raise SettingsError(f"In {self.path}, the [hold] window could not be read: {e}")

    def hold_words(self):
        """'9:25 PM to 10:15 PM Central', or '' when there is no window."""
        window = self.hold_window()
        if not window:
            return ""
        start, end, zone = window
        return f"{_clock_words(start)} to {_clock_words(end)} {_zone_words(self.hold['zone'])}"

    def hold_end_words(self):
        window = self.hold_window()
        if not window:
            return ""
        return f"{_clock_words(window[1])} {_zone_words(self.hold['zone'])}"

    def hold_start_words(self):
        window = self.hold_window()
        if not window:
            return ""
        return f"{_clock_words(window[0])} {_zone_words(self.hold['zone'])}"

    def hold_state(self, estimate_seconds=0, now=None):
        """'inside' while the window is open, 'ahead' when a job this long would still be running when
        it opens, else None. The screen, the recipes and the text lane all ask this one place."""
        window = self.hold_window()
        if not window:
            return None
        from datetime import datetime, timedelta
        start_t, end_t, zone = window
        now = (now or datetime.now(zone)).astimezone(zone)
        start = now.replace(hour=start_t.hour, minute=start_t.minute, second=0, microsecond=0)
        end = now.replace(hour=end_t.hour, minute=end_t.minute, second=0, microsecond=0)
        if end <= start:  # a window that runs past midnight
            end = end + timedelta(days=1)
            if now < start and now < end - timedelta(days=1):
                start, end = start - timedelta(days=1), end - timedelta(days=1)
        if start <= now < end:
            return "inside"
        if estimate_seconds and now < start and now + timedelta(seconds=estimate_seconds) > start:
            return "ahead"
        return None

    def hold_reason(self, estimate_seconds=0, now=None):
        """A short reason to wait, for the queue's record, or None."""
        if self.hold_state(estimate_seconds, now):
            return f"the nightly job, until {self.hold_end_words()}"
        return None

    @property
    def engine_hosts(self):
        return list(self.hosts["engine"])

    @property
    def screen_hosts(self):
        return list(self.hosts["screen"])

    def writer(self, which):
        return self.writers.get(which, "")

    def describe(self):
        """Lines for a person: group, key, value, where it came from."""
        lines = [f"Settings file: {self.path} ({'read' if self.exists else 'not there, so defaults are in use'})"]
        for group, key, _d, _e, why in KEYS:
            value = self.values[group][key]
            shown = ", ".join(value) if isinstance(value, list) else str(value)
            lines.append(f"[{group}] {key} = {shown or '(empty)'}    from {self.origin[(group, key)]}")
        return lines


def _parse_clock(text):
    hh, mm = str(text).strip().split(":")
    return dtime(int(hh), int(mm))


def _clock_words(t):
    hour = t.hour % 12 or 12
    return f"{hour}:{t.minute:02d} {'AM' if t.hour < 12 else 'PM'}"


def _zone_words(zone):
    names = {"America/Chicago": "Central", "America/New_York": "Eastern", "America/Denver": "Mountain",
             "America/Los_Angeles": "Pacific", "America/Phoenix": "Arizona", "UTC": "UTC"}
    if zone in names:
        return names[zone]
    try:
        from datetime import datetime
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo(zone)).tzname() or zone
    except Exception:  # noqa: BLE001
        return zone


def settings_path():
    return Path(os.environ.get("NEOVAK_SETTINGS") or DEFAULT_PATH).expanduser()


def load(path=None, fresh=False):
    """The settings in use. Read once per process unless fresh is asked for."""
    path = Path(path) if path else settings_path()
    key = str(path)
    if not fresh and key in _cache:
        return _cache[key]
    data, exists = {}, path.is_file()
    named = os.environ.get("NEOVAK_SETTINGS")
    if not exists and named and Path(named).expanduser() == path:
        # A file named on purpose that is not there is a mistake, not a wish for the defaults: the defaults would
        # quietly swap this machine's memory check and folders for the built-in ones.
        raise SettingsError(f"The settings file {path} named by NEOVAK_SETTINGS is not there. Nothing was started; "
                            "fix the name, or leave NEOVAK_SETTINGS unset to use the usual file.")
    if exists:
        if tomllib is None:
            raise SettingsError("Reading settings needs Python 3.11 or later.")
        try:
            data = tomllib.loads(path.read_text())
        except (OSError, tomllib.TOMLDecodeError) as e:
            raise SettingsError(f"The settings file {path} could not be read: {e}")
    s = Settings(data, path, exists)
    _cache[key] = s
    return s


def reset():
    """Forget what was read, so the next load reads the file again. For tests."""
    _cache.clear()


EXAMPLE = '''# NeoVak settings. Plain paths for this Mac. Lines that start with # are notes.
# A key that is left out keeps its default; run python3 -m neovak_queue.settings to see them all.

[folders]
output = "~/Documents/NeoVak"          # finished work goes here
# state = ""                            # the engine's own records; the default is the code's state folder
# screen_state = ""                     # the screen's own records

[models]
mflux = "~/.cache"                      # its huggingface subfolder is the Hugging Face cache
video = ""                              # folder holding ltx-2.5-mlx-q8 and ltx-2.3-mlx-q8, if you have them
added = "~/.cache/neovak-added"         # models added from the Models page
roots = []                              # any other folders that hold weights

[tools]
music_python = ""                       # python3 of an mlx-audio environment, for music
ltx = ""                                # the ltx-2-mlx command, for video clips
face_python = ""                        # a python3 with torch and spandrel, for face repair
gfpgan = ""                             # GFPGANv1.4.pth, for face repair
vision = ""                             # leave empty: built from tools/vision_tool.swift when first needed
ffmpeg = "/opt/homebrew/bin/ffmpeg"
ffprobe = "/opt/homebrew/bin/ffprobe"

[memory]
governor = ""                           # a memory check script, or empty for the built-in simple check
governor_python = "/opt/homebrew/bin/python3"
reserve_gb = 4.0                        # always kept free on top of what a model needs

[hold]
start = ""                              # a daily window when no model may load, as "21:25"; empty for none
end = ""
zone = "America/Chicago"

[hosts]
engine = ["127.0.0.1", "localhost"]     # names the engine answers to; add a Tailscale address to reach it from other devices
screen = ["127.0.0.1"]                  # addresses the screen listens on

[writers]
quick = ""                              # address of a running local text model, such as "http://127.0.0.1:8088"
careful = ""
'''


def main(argv):
    if argv[:1] == ["write-example"]:
        target = Path(argv[1]) if len(argv) > 1 else settings_path()
        if target.exists():
            print(f"{target} already exists. Nothing was written.")
            return 1
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(EXAMPLE)
        print(f"Wrote an example settings file to {target}. Open it and fill in the paths for this Mac.")
        return 0
    try:
        for line in load(fresh=True).describe():
            print(line)
    except SettingsError as e:
        print(e)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
