"""The memory check every model load goes through.

Two ways to answer, chosen by the settings file:

  * A governor script ([memory] governor names it). It is run as
    `governor_python governor preflight <GB or name>` and its VERDICT line is the answer. On
    the Studio this is model_governor.py, which knows the two text models by name and counts
    cached files the way Activity Monitor does. When a governor is named and cannot be found, the
    answer is no: nothing loads around it.

  * The simple check, when no governor is named. It reads vm_stat and sysctl hw.memsize and counts
    only what is plainly available: free pages, speculative pages and purgeable pages. Cached files
    and idle program memory are not counted, so this check says no sooner than the governor would.
    The reserve from the settings file is kept on top of what the model needs.

Both return the same shape, and the report text uses the governor's own lines so anything that
reads a report can read either:

  {"go": bool, "answered": bool, "need_gb": float, "available_gb": float, "safety_gb": float,
   "resident": bool, "method": "governor" or "simple", "report": str}

Nothing here loads a model. Standard library only.
"""
import os
import re
import subprocess
from pathlib import Path

from . import settings as _settings

# What the simple check asks for when a job names a text model instead of a figure. These are the
# measured peaks from STUDIO_PLAN.md. The governor answers names from what is really in memory.
NAMED_GB = {"9b": 10.0, "27b": 38.0}
PAGE_RE = re.compile(r"page size of (\d+) bytes")
LINE_RE = re.compile(r"^(.+?):\s+(\d+)\.?\s*$")
_REPORT_RE = re.compile(r"Need ~([\d.]+) GB\s+\|\s+reclaimable ([\d.]+) GB\s+\|\s+"
                        r"margin ([+-][\d.]+) GB \(safety ([\d.]+)\)")

SIMPLE_WORDS = ("Before anything loads, this Mac's own count of free memory is checked, with a reserve kept on top. "
                "That count leaves out files the system is holding in memory, so it says no a little sooner than it needs to.")
GOVERNOR_WORDS = "Before anything loads, a memory check on this Mac says whether it will fit, with a reserve kept on top."


def preflight_args(need):
    """The governor's arguments for one memory ask: a number of GB, an officer name, or for a model LM Studio holds
    a dict {"gb", "lms", "ctx"}: the fallback figure plus the model key and context, so the governor can size that
    load with LM Studio's own estimate without loading it."""
    if isinstance(need, dict):
        return [str(need.get("gb") or 0), "--model", str(need.get("lms") or ""), "--ctx", str(int(need.get("ctx") or 8192))]
    return [str(need)]


def need_words(need):
    """The same ask, as words for a job's error line."""
    if isinstance(need, dict):
        return f"about {need.get('gb')} GB ({need.get('lms')} in LM Studio)"
    return f"{need} GB" if isinstance(need, (int, float)) else str(need)


def method(s=None):
    """'governor' or 'simple', from the settings."""
    s = s or _settings.load()
    return "governor" if s.governor else "simple"


def method_words(s=None):
    return GOVERNOR_WORDS if method(s) == "governor" else SIMPLE_WORDS


def parse_report(text):
    """Turn a report into the answer shape. No VERDICT line means no permission."""
    verdicts = [ln for ln in text.splitlines() if ln.startswith("VERDICT:")]
    value = verdicts[-1].split(":", 1)[1].strip() if verdicts else ""
    out = {"go": value.startswith("GO"), "need_gb": None, "available_gb": None, "safety_gb": None,
           "resident": "already resident" in value, "answered": bool(verdicts)}
    m = _REPORT_RE.search(text)
    if m:
        out.update(need_gb=float(m.group(1)), available_gb=float(m.group(2)), safety_gb=float(m.group(4)))
    return out


def preflight(need, s=None, timeout=120, governor=None):
    """May a load of `need` GB (or the text model called `need`) start right now? Fails closed.
    governor names a script to ask instead of the one in the settings; '' means the simple check."""
    s = s or _settings.load()
    governor = s.governor if governor is None else governor
    if governor:
        return _governor(need, s, timeout, governor)
    return _simple(need, s)


# ------------------------------------------------------------------ the governor
def _governor(need, s, timeout, governor):
    if not Path(governor).is_file():
        return _no_answer("The memory check could not be found, so nothing was run.", "governor")
    try:
        # The governor shells out to /usr/sbin/sysctl; a launchd PATH can leave that folder out,
        # and without it the governor under-reports free memory by roughly half.
        env = dict(os.environ, PATH=os.environ.get("PATH", "") + ":/usr/sbin:/sbin")
        r = subprocess.run([s.governor_python, governor, "preflight"] + preflight_args(need),
                           capture_output=True, text=True, timeout=timeout, env=env)
    except (OSError, subprocess.TimeoutExpired) as e:
        return _no_answer(f"governor did not answer: {e}", "governor")
    report = ((r.stdout or "") + (r.stderr or "")).strip()
    out = parse_report(report)
    out.update(method="governor", report=report[-800:])
    return out


def _no_answer(why, how):
    return {"go": False, "answered": False, "need_gb": None, "available_gb": None, "safety_gb": None,
            "resident": False, "method": how, "report": why}


# ------------------------------------------------------------------ the simple check
def _run(cmd):
    env = dict(os.environ, PATH=os.environ.get("PATH", "") + ":/usr/sbin:/sbin:/usr/bin:/bin")
    return subprocess.run(cmd, capture_output=True, text=True, timeout=15, env=env).stdout


def read_vm_stat(text=None):
    """Free, speculative and purgeable memory in GB, from vm_stat's own figures."""
    text = text if text is not None else _run(["vm_stat"])
    m = PAGE_RE.search(text)
    page = int(m.group(1)) if m else 16384
    pages = {}
    for line in text.splitlines():
        lm = LINE_RE.match(line.strip())
        if lm:
            pages[lm.group(1).strip()] = int(lm.group(2))
    gb = lambda key: pages.get(key, 0) * page / 1e9  # noqa: E731
    return {"free": gb("Pages free"), "speculative": gb("Pages speculative"), "purgeable": gb("Pages purgeable"),
            "wired": gb("Pages wired down"), "active": gb("Pages active"), "inactive": gb("Pages inactive"),
            "compressor": gb("Pages occupied by compressor")}


def total_gb():
    """The Mac's memory, from sysctl hw.memsize. None when it cannot be read."""
    try:
        return int(_run(["sysctl", "-n", "hw.memsize"]).strip()) / 1e9
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None


def simple_reading(s=None):
    """What the simple check sees right now, without asking about any load."""
    s = s or _settings.load()
    try:
        vm = read_vm_stat()
    except (OSError, subprocess.TimeoutExpired) as e:
        return None
    available = vm["free"] + vm["speculative"] + vm["purgeable"]
    return {"available_gb": round(available, 1), "safety_gb": s.reserve_gb, "total_gb": total_gb(), "parts": vm}


def _simple(need, s):
    if isinstance(need, dict):  # a model in LM Studio: the simple check has only the figure the lane worked out
        need, lms = need.get("gb"), need.get("lms")
        note = f"{lms} in LM Studio is taken as {float(need or 0):.1f} GB, its size on disk plus room to run.\n"
        try:
            need_gb = float(need)
        except (TypeError, ValueError):
            return _no_answer(f"The memory check was asked for '{lms}' without a size in GB.", "simple")
    elif isinstance(need, str) and need in NAMED_GB:
        need_gb, note = NAMED_GB[need], f"{need} is taken as {NAMED_GB[need]:.0f} GB, its measured size.\n"
    else:
        try:
            need_gb, note = float(need), ""
        except (TypeError, ValueError):
            return _no_answer(f"The memory check was asked for '{need}', which is not a number of GB.", "simple")
    reading = simple_reading(s)
    if reading is None:
        return _no_answer("vm_stat did not answer, so nothing was run.", "simple")
    have, safety = reading["available_gb"], reading["safety_gb"]
    margin = have - need_gb
    go = margin >= safety
    total = reading["total_gb"]
    report = (f"{note}Simple check: free {reading['parts']['free']:.1f} + speculative {reading['parts']['speculative']:.1f} "
              f"+ purgeable {reading['parts']['purgeable']:.1f} GB, of {total:.0f} GB in this Mac.\n" if total else "")
    report += (f"Need ~{need_gb:.1f} GB  |  reclaimable {have:.1f} GB  |  margin {margin:+.1f} GB (safety {safety:.1f})\n"
               f"VERDICT: {'GO' if go else 'NO-GO'}")
    return {"go": go, "answered": True, "need_gb": need_gb, "available_gb": have, "safety_gb": safety,
            "resident": False, "method": "simple", "report": report}


def main(argv):
    """python3 -m neovak_queue.memory preflight <GB>: the same words either check prints."""
    if len(argv) >= 2 and argv[0] == "preflight":
        out = preflight(argv[1])
        print(out["report"])
        return 0 if out["go"] else 1
    r = simple_reading()
    if r is None:
        print("vm_stat did not answer.")
        return 1
    print(f"{r['available_gb']:.1f} GB plainly available of {r['total_gb']:.0f} GB, with {r['safety_gb']:.0f} GB kept in reserve. {method_words()}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main(sys.argv[1:]))
