"""Video lane: LTX through ltx-2-mlx (its own environment, named by [tools] ltx in the settings file).

Text to video, and image to video when a source picture is given. The chosen model and its
settings come from the S2 probe (STUDIO_PLAN.md, the video stage). Engine rules live here: LTX
wants 8k+1 frames at 24 per second, and the two-stage path renders at half size first, so width
and height must be multiples of 64. A source picture must be inside a folder NeoVak may read.

Time and memory figures in MEASURED are real runs, and the time estimate is built from them.
The queue's own run history replaces it once a job with the same settings has finished.
"""
import json
import os
import re
import subprocess
import time
from datetime import datetime
from pathlib import Path

from .. import settings as _settings
from .base import Adapter, AdapterError
from .image_tools import ImageTool, _new_seed, fit_megapixel

_S = _settings.load()
# The command lives in <ltx-2-mlx>/.venv/bin, and the engine is run from the <ltx-2-mlx> folder.
LTX = Path(_S.tool("ltx")) if _S.tool("ltx") else Path("/nonexistent/ltx-2-mlx")
LTX_ROOT = LTX.parent.parent.parent if LTX.parent.name == "bin" and LTX.parent.parent.name == ".venv" else LTX.parent
WORKING = _S.video_pack_dir or Path("/nonexistent/video-packs")
FFPROBE = _S.tool("ffprobe")
NOT_SET_UP = "Video needs ltx-2-mlx and its model packs, which are not set up on this machine. The settings file names them under [tools] ltx and [models] video."
FPS = 24
SIZES = {"landscape": (960, 576), "portrait": (576, 960), "square": (768, 768)}
SECONDS = (2, 5, 8)

# --low-ram measured on LTX-2.3: 16.0 GB peak against 26.8 GB, the same time, a nearly identical clip.
VIDEO_MODELS = {
    "ltx-2.5-q8": {"label": "LTX-2.5", "pack": WORKING / "ltx-2.5-mlx-q8", "low_ram": True},
    "ltx-2.3-q8": {"label": "LTX-2.3", "pack": WORKING / "ltx-2.3-mlx-q8",
                   "gemma": WORKING / "gemma-3-12b-it-4bit", "low_ram": True},
}
DEFAULT_MODEL = "ltx-2.5-q8"
# (pixels x frames, wall seconds, peak GB): real runs through the queue.
MEASURED = {"ltx-2.5-q8": [(768 * 768 * 49, 115, 22.4), (960 * 576 * 121, 263, 22.4), (768 * 768 * 121, 304, 22.3),
                           (576 * 960 * 193, 408, 22.3)],
            "ltx-2.3-q8": [(960 * 576 * 49, 112, 15.9), (960 * 576 * 121, 239, 16.0)]}


def frames_for(seconds):
    """The nearest length LTX accepts: 8k+1 frames, at least one step."""
    return 8 * max(1, round(float(seconds) * FPS / 8)) + 1


def _time_for(points, x):
    """Seconds at x, on the line through the smallest and largest measured runs (a straight line
    fits the runs: the work scales with pixels times frames)."""
    pts = sorted(points)
    if len(pts) == 1:
        return pts[0][1] * x / pts[0][0]
    low, high = pts[0], pts[-1]
    return max(30, low[1] + (high[1] - low[1]) * (x - low[0]) / (high[0] - low[0]))


def _memory_for(points, x):
    """GB to ask for: peak does not follow length in the runs so far (22.3 GB at 2 and at 5
    seconds), so this is the highest measured peak, plus a margin for anything larger."""
    peak = max(p[2] for p in points)
    return peak + (0 if x <= max(p[0] for p in points) else 4)


class LtxVideo(ImageTool):
    name = "ltx-video"
    lane = "video"
    summary = "Make a short video from a description, or from a picture and a description, with LTX."
    prefix = "neovak_video"
    params = {
        "prompt": {"type": "str", "help": "What happens in the clip."},
        "seconds": {"type": "float", "default": 5, "help": "Length in seconds, 1 to 10."},
        "size": {"type": "str", "default": "landscape", "choices": list(SIZES),
                 "help": "Shape of the clip. Ignored when a source picture sets the shape."},
        "source": {"type": "str", "default": None, "help": "Optional picture to start from. It is only read."},
        "strength": {"type": "float", "default": 1.0, "help": "How closely the start follows the picture, 0 to 1."},
        "audio": {"type": "bool", "default": True, "help": "Also make sound for the clip."},
        "model": {"type": "str", "default": DEFAULT_MODEL, "choices": list(VIDEO_MODELS)},
        "seed": {"type": "int", "default": -1},
    }

    def models(self):
        return [{"model": k, "label": v["label"], "present": v["pack"].exists() and LTX.exists()}
                for k, v in VIDEO_MODELS.items()]

    def shape(self, p):
        """(width, height, frames): source picture's shape when there is one."""
        if p.get("source"):
            _, w, h = self.checked_source(p["source"])
            width, height = fit_megapixel(w, h, area=960 * 576, step=64)
            if max(width, height) > 1280:
                scale = 1280 / max(width, height)
                width, height = max(64, int(width * scale) // 64 * 64), max(64, int(height * scale) // 64 * 64)
        else:
            width, height = SIZES[p.get("size") or "landscape"]
        return width, height, frames_for(p.get("seconds", 5))

    def memory_gb(self, params):
        model, (w, h, f) = params.get("model") or DEFAULT_MODEL, self.shape(params)
        return int(_memory_for(MEASURED[model], w * h * f)) + 3

    def default_estimate(self, params):
        model, (w, h, f) = params.get("model") or DEFAULT_MODEL, self.shape(params)
        return round(_time_for(MEASURED[model], w * h * f))

    def estimate_key(self, params):
        w, h, f = self.shape(params)
        return f"ltx-video:{params.get('model')}:{w}x{h}:{f}"

    def validate(self, params):
        p = Adapter.validate(self, params)
        p["prompt"] = p["prompt"].strip()
        if not p["prompt"]:
            raise AdapterError("Please describe what happens in the clip.")
        if not 1 <= p["seconds"] <= 10:
            raise AdapterError("Clips can be 1 to 10 seconds long.")
        if not 0 < p["strength"] <= 1:
            raise AdapterError("'strength' must be above 0 and at most 1")
        spec = VIDEO_MODELS[p["model"]]
        if not LTX.exists():
            raise AdapterError(NOT_SET_UP)
        if not spec["pack"].exists():
            raise AdapterError(f"The {spec['label']} model pack is not in the video models folder ({WORKING}), so nothing was started.")
        if p["source"]:
            p["source"], _, _ = self.checked_source(p["source"])
        p["seed"] = _new_seed(p["seed"])
        return p

    def plan(self, job):
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        name = f"{self.prefix}_{stamp}_{job['params']['seed']}_j{job['id'][-6:]}.mp4"
        return {"outputs": [str(Path(self.config["output_dir"]) / name)]}

    def parse_progress(self, line):
        # tqdm's own "time left" covers one pass only, so it is left out on purpose: the estimate
        # for the whole job comes from measured runs.
        if "Loading" in line and "transformer" in line:
            return {"stage": "loading model"}
        if "Encoding prompt" in line:
            return {"stage": "reading the description"}
        if re.search(r"(?i)decod", line):
            return {"stage": "writing the clip"}
        m = re.search(r"(\d+)/(\d+) \[", line)
        if m and "Denoising" in line:
            step, total = int(m.group(1)), int(m.group(2))
            if total == 8:
                return {"step": step, "total": 11, "stage": "first pass"}
            if total == 3:
                return {"step": 8 + step, "total": 11, "stage": "final pass"}
        return None

    def engine_env(self):
        env = os.environ.copy()
        env["PATH"] = "/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"  # the engine streams frames to ffmpeg
        env["HF_HUB_OFFLINE"] = "1"
        env["PYTHONUNBUFFERED"] = "1"
        env["LTX2_VAE_DECODE_BUDGET_GB"] = "12"  # its default is half of memory, 32 GB
        # While the display is awake, macOS can kill long GPU work with "Impacting Interactivity" (two runs
        # failed that way within eight seconds on Nov 9). This relaxes that watchdog for the engine's process
        # only; the engine's own error text names it as the mitigation.
        env["AGX_RELAX_CDM_CTXSTORE_TIMEOUT"] = "1"
        return env

    def run(self, job, ctx):
        p, output = job["params"], job["outputs"][0]
        spec = VIDEO_MODELS[p["model"]]
        width, height, frames = self.shape(p)
        cmd = [str(LTX), "generate", "--distilled", "--model", str(spec["pack"])]
        if spec.get("gemma"):
            cmd += ["--gemma", str(spec["gemma"])]
        cmd += [f"--prompt={p['prompt']}", "--height", str(height), "--width", str(width), "--frames", str(frames),
                "--frame-rate", str(FPS), "--seed", str(p["seed"]), "--output", output]
        if spec.get("low_ram"):
            cmd.append("--low-ram")
        if p["source"]:
            cmd += ["--image", p["source"], "0", str(p["strength"])]
        if not p["audio"]:
            cmd.append("--no-audio")
        ctx.progress(stage="loading model", step=0, total=11)
        start = time.time()
        estimate = self.default_estimate(p)
        r = ctx.spawn(cmd, env=self.engine_env(), cwd=str(LTX_ROOT), measure=True, timeout=max(1800, estimate * 6))
        out = self.finish(job, ctx, r, "The video engine", seed=p["seed"], prompt=p["prompt"],
                          model=p["model"], time_seconds=round(time.time() - start, 1))
        if out is None:
            return None
        got = self.probe(output)
        problem = None
        if got["video"] is None or got["frames"] != frames or (got["width"], got["height"]) != (width, height):
            problem = (f"The clip came out different from what was asked for "
                       f"({got['width']} by {got['height']}, {got['frames']} frames), so it was not kept.")
        elif p["audio"] and not got["audio"]:
            problem = "The clip came out with no sound although sound was asked for, so it was not kept."
        if problem:
            Path(output).unlink(missing_ok=True)
            raise AdapterError(problem)
        out.update(size=f"{width}x{height}", frames=frames, seconds=round(frames / FPS, 2), has_audio=got["audio"])
        return out

    @staticmethod
    def probe(path):
        r = subprocess.run([FFPROBE, "-v", "error", "-count_packets", "-show_entries",
                            "stream=codec_type,width,height,nb_read_packets", "-of", "json", path],
                           capture_output=True, text=True, timeout=60)
        streams = json.loads(r.stdout or "{}").get("streams") or []
        v = next((s for s in streams if s.get("codec_type") == "video"), None)
        a = next((s for s in streams if s.get("codec_type") == "audio"), None)
        return {"video": v, "audio": a is not None, "width": v and v.get("width"), "height": v and v.get("height"),
                "frames": int(v.get("nb_read_packets") or 0) if v else 0}
