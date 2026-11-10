"""Music lane: MiniMax-Music3 (4-bit, MLX), moved onto the queue from
music_job.py (Oct 15). Same engine, same separate mlx-audio environment (named by [tools]
music_python in the settings file; NeoVak's own venv is never touched), same 11 GB governor ask,
same 30 steps. What changes: the queue runs the governor check, tracks the job, and can
cancel it; nothing writes jobs.json any more. The seed is now chosen at submit and recorded
(music_job.py used the start time and did not record it).
"""
import json
import os
import subprocess
import time
from datetime import datetime
from pathlib import Path

from .. import settings as _settings
from .base import Adapter, AdapterError

_S = _settings.load()
PYTHON = _S.tool("music_python")
RUNNER = Path(__file__).resolve().parent.parent / "tools" / "music_run.py"
FFPROBE = _S.tool("ffprobe")
NOT_SET_UP = "Music needs the mlx-audio environment, which is not set up on this machine. The settings file names it under [tools] music_python."
MODEL = "mlx-community/MiniMax-Music3-4bit"
INSTRUMENTAL = "[instrumental]"  # the tag the model knows; anything shorter is read as a very short song
FLOOR = 0.9  # a piece may not end before this share of the length that was asked for


def real_seconds(path):
    """How long the file really is, or None."""
    try:
        r = subprocess.run([FFPROBE, "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)],
                           capture_output=True, text=True, timeout=30)
        return round(float(json.loads(r.stdout)["format"]["duration"]), 1)
    except (OSError, ValueError, KeyError, subprocess.TimeoutExpired):
        return None


class MinimaxMusic(Adapter):
    name = "minimax-music"
    lane = "music"
    summary = "Text to music with MiniMax-Music3 (4-bit, MLX). A 30-second piece takes a few minutes."
    params = {
        "prompt": {"type": "str", "help": "Instruments, mood, tempo."},
        "duration": {"type": "float", "default": 30.0, "help": "Seconds, 5 to 180."},
        "genre": {"type": "str", "default": "ambient", "help": "Style hint added to the caption."},
        "lyrics": {"type": "str", "default": INSTRUMENTAL, "help": "Words to sing, or '[instrumental]'."},
        "seed": {"type": "int", "default": -1, "help": "-1 picks one at submit and records it."},
    }

    def models(self):
        return [MODEL]

    def memory_gb(self, params):
        return 11

    def validate(self, params):
        p = super().validate(params)
        if not Path(self.config.get("music_python", PYTHON) or "/nonexistent").is_file():
            raise AdapterError(NOT_SET_UP)
        p["duration"] = max(5.0, min(p["duration"], 180.0))
        if p["seed"] < 0:
            p["seed"] = int(time.time()) % 100000
        return p

    def estimate_key(self, params):
        return f"minimax-music-full:{int(params['duration'] // 15) * 15}"  # "full": runs from before the length was honoured do not count

    def default_estimate(self, params):
        return 30 + params["duration"] * 8  # measured: a 30 second piece takes about 275 seconds, model load included

    def plan(self, job):
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out = Path(self.config["output_dir"]) / f"neovak_music_{stamp}_{job['id'][-6:]}.wav"
        return {"outputs": [str(out)]}

    def run(self, job, ctx):
        p = job["params"]
        out = job["outputs"][0]
        caption = f"{p['genre']} music. {p['prompt']}" if p["genre"] else p["prompt"]
        lyrics = INSTRUMENTAL if p["lyrics"].strip() in ("", "[inst]") else p["lyrics"]
        # Words travel as --name=value, so words that begin with dashes are read as words.
        cmd = [self.config.get("music_python", PYTHON), str(self.config.get("music_runner", RUNNER)), "--model", MODEL,
               f"--caption={caption}", f"--lyrics={lyrics}", "--duration", str(int(p["duration"])),
               "--min-seconds", str(round(p["duration"] * FLOOR, 1)), "--steps", "30",
               "--seed", str(p["seed"]), "--output", out]
        ctx.progress(stage="generating", total=30)
        start = time.time()
        r = ctx.spawn(cmd)
        elapsed = round(time.time() - start, 1)
        if ctx.cancel_requested:
            if os.path.exists(out):
                os.remove(out)
            return None
        if r.returncode != 0 or not Path(out).exists():
            raise AdapterError((r.stderr or r.stdout or "no output")[-800:])
        seconds = real_seconds(out)
        return {"files": [out], "path": out, "seed": p["seed"], "caption": caption,
                "duration": seconds if seconds is not None else p["duration"], "requested_duration": p["duration"],
                "time_seconds": elapsed, "message": f"Music written, {seconds} seconds long." if seconds else "Music written."}
