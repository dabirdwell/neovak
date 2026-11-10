"""Image lane: mflux 0.19.1 (MLX native).

ENGINE_MODELS is the one table: each model name maps to the command that really serves it, the
arguments that really select it, and the weights on this machine. Before this table every model
went to mflux-generate-flux2 with --base-model, which that command ignores, so every "model"
came out as FLUX.2 klein 4B (or crashed, for schnell's q8 folder). See STUDIO_PLAN.md section 2.

mode "standard" is generate_image, mode "fast" is generate_image_fast (klein 4B, 4 steps, the
exact command line the S1 parity run proved pixel-identical). generate_image uses the table
too, through engine_command(), so the switched-off path cannot go back to the old bug.

The gb figures are measured peak memory footprints from real runs at 1024 by 1024, the number
the governor must be asked for. STUDIO_PLAN.md has the runs.
"""
import glob
import math
import os
import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path

from .base import Adapter, AdapterError

# --low-ram: measured on Z-Image Turbo at 1024 by 1024, it cuts the peak footprint from 42.5 GB to
# 27.9 GB and costs no time. Klein does not use it: measured at 29.4 GB with it and 28.2 GB
# without, so it stays on the exact command the S1 parity run proved pixel-identical.
# meta: at least one of these must appear in the "model" field mflux writes into the file.
# not_meta: none of these may appear (Z-Image's name is inside Z-Image-Turbo's).
ENGINE_MODELS = {
    "flux2-klein-4b": {"bin": "mflux-generate-flux2", "head": ["--base-model", "flux2-klein-4b"],
                       "steps": 4, "gb": 30, "label": "FLUX.2 klein 4B",
                       "meta": ["flux.2-klein-4b"]},
    "z-image-turbo": {"bin": "mflux-generate-z-image-turbo", "head": ["--model", "z-image-turbo", "--low-ram"],
                      "steps": 9, "gb": 30, "label": "Z-Image Turbo",
                      "meta": ["z-image-turbo"], "live_gb": 4},
    "z-image": {"bin": "mflux-generate-z-image", "head": ["--model", "z-image", "--low-ram"],
                "steps": 28, "gb": 18, "label": "Z-Image",
                "meta": ["z-image"], "not_meta": ["turbo"], "live_gb": 4},
    "schnell": {"bin": "mflux-generate", "head": ["--model", "schnell", "--low-ram"],
                "saved": "flux-schnell-q8", "saved_base": "schnell",
                "steps": 4, "gb": 18, "label": "FLUX.1 schnell",
                "meta": ["flux.1-schnell", "flux-schnell-q8"]},
    "dev": {"bin": "mflux-generate", "head": ["--model", "dev", "--low-ram"],
            "steps": 20, "gb": 29, "label": "FLUX.1 dev",
            "meta": ["flux.1-dev"], "live_gb": 4},
    "krea-dev": {"bin": "mflux-generate", "head": ["--model", "krea-dev", "--low-ram"],
                 "steps": 20, "gb": 29, "label": "FLUX.1 Krea dev",
                 "meta": ["flux.1-krea-dev"], "live_gb": 4},
    "qwen": {"bin": "mflux-generate-qwen", "head": ["--model", "Qwen/Qwen-Image", "--base-model", "qwen-image", "--low-ram", "--quantize", "8"],
             "steps": 20, "gb": 40, "label": "Qwen-Image",
             "meta": ["qwen-image"]},
    "fibo": {"bin": "mflux-generate-fibo", "head": ["--model", "fibo", "--low-ram"],
             "steps": 30, "gb": 32, "label": "FIBO",
             "meta": ["fibo"]},
}
DEFAULT_MODEL = "z-image-turbo"
# A starting picture costs memory on top of the model: klein at 1024 by 1024 peaked at 35.4 GB against 29.4 GB
# without one (Nov 9 2026). Only klein has been measured; the same figure is asked for every model.
SOURCE_GB = 6
# Watch it arrive writes every step's picture out, which makes a run slower. Measured Nov 9 2026 on Polished at
# 1152 by 896: two watched runs took 126.6 and 126.8 s against about 88 s for the plain runs at the same settings.
LIVE_SLOWER = 1.4
LONGEST_SIDE = 1536
MOST_STRETCHED = 4.0  # a picture longer and thinner than this has no sensible size for the models
# What mflux says when a model's weights are not on this machine, with the connection deliberately off.
MISSING_WEIGHTS = ("LocalEntryNotFoundError", "cannot find the requested files", "Cannot find an appropriate cached snapshot",
                   "snapshot folder", "offline mode", "HF_HUB_OFFLINE", "RepositoryNotFoundError", "is not a local folder")

# Names that older callers may send and that this machine cannot serve, each with the reason.
NOT_HERE = {
    "flux2-klein-9b": "FLUX.2 klein 9B is not on this machine in a form mflux can run.",
    "flux2-dev": "FLUX.2 dev is not on this machine in a form mflux can run.",
}


def engine_command(venv_bin, model_dir, model, quantize=0):
    """[binary, the arguments that select this model]. Raises AdapterError for an unknown name."""
    spec = ENGINE_MODELS.get(model)
    if spec is None:
        raise AdapterError(NOT_HERE.get(model) or
                           f"unknown image model {model!r}; known: {sorted(ENGINE_MODELS)}")
    binary = str(Path(venv_bin) / spec["bin"])
    if spec.get("saved"):
        saved = Path(model_dir) / spec["saved"]
        if saved.exists():
            return [binary, "--model", str(saved), "--base-model", spec["saved_base"], "--low-ram"]
    head = list(spec["head"])
    if quantize:
        head += ["--quantize", str(quantize)]
    return [binary] + head


def size_following(source_w, source_h, preset_w, preset_h):
    """(width, height) with the source's own shape and about the preset's number of pixels. mflux squeezes a
    starting picture into whatever size it is told, which distorts people, so a job with a source follows it."""
    ratio, area = source_w / source_h, preset_w * preset_h
    w, h = (area * ratio) ** 0.5, (area / ratio) ** 0.5
    over = max(w, h) / LONGEST_SIDE
    if over > 1:
        w, h = w / over, h / over
    return tuple(max(256, min(LONGEST_SIDE, math.ceil(v / 16) * 16)) for v in (w, h))


def source_size(path):
    """(width, height) of a picture. Raises AdapterError if it cannot be read as one."""
    from PIL import Image
    try:
        with Image.open(path) as im:
            return im.size
    except OSError:
        raise AdapterError("That is not a picture NeoVak can open (PNG, JPEG or WebP).")


def written_model(path):
    """The model name mflux recorded inside the picture, or None if it cannot be read."""
    try:
        import json
        from PIL import Image
        with Image.open(path) as im:
            raw = im.info.get("exif") or b""
        at = raw.find(b"ASCII\x00\x00\x00{")
        if at < 0:
            return None
        found, _ = json.JSONDecoder().raw_decode(raw[at + 8:].decode("utf-8", "ignore"))
        return found.get("model")
    except Exception:
        return None


def check_identity(model, recorded):
    """None when the file is what was asked for or cannot be read; a sentence when it is not."""
    if not recorded:
        return None
    spec, text = ENGINE_MODELS[model], str(recorded).lower()
    if not any(m in text for m in spec["meta"]) or any(m in text for m in spec.get("not_meta", [])):
        return f"asked for {spec['label']} but the file says it was made by {recorded}"
    return None


class MfluxImage(Adapter):
    name = "mflux"
    lane = "image"
    summary = "Text to image with mflux. Every listed model has its own command and its own weights here."
    params = {
        "prompt": {"type": "str", "help": "What to generate."},
        "style": {"type": "str", "default": "editorial", "help": "Style preset name, or '' for none."},
        "size": {"type": "str", "default": "landscape", "help": "Size preset name."},
        "model": {"type": "str", "default": DEFAULT_MODEL, "choices": sorted(ENGINE_MODELS),
                  "help": "Model (standard mode). Fast mode always uses flux2-klein-4b."},
        "steps": {"type": "int", "default": 0, "help": "0 means the model's usual count."},
        "seed": {"type": "int", "default": -1, "help": "-1 picks one at submit and records it."},
        "quantize": {"type": "int", "default": 0, "choices": [0, 3, 4, 5, 6, 8]},
        "mode": {"type": "str", "default": "standard", "choices": ["standard", "fast"],
                 "help": "standard = generate_image, fast = generate_image_fast."},
        "live": {"type": "bool", "default": False, "help": "Write each step's picture so a person can watch it arrive. Asks the governor for more memory."},
        "source": {"type": "str", "default": "", "help": "A picture to start from, read and never changed. Empty for none."},
        "strength": {"type": "float", "default": 0.5, "help": "With a source: 0.1 is loose, 0.9 stays very close to it."},
    }

    def models(self):
        return [{"model": k, "label": s["label"], "steps": s["steps"], "memory_gb": s["gb"]}
                for k, s in ENGINE_MODELS.items()]

    def memory_gb(self, params):
        model = "flux2-klein-4b" if params.get("mode") == "fast" else params.get("model", DEFAULT_MODEL)
        spec = ENGINE_MODELS.get(model)
        if not spec:
            return 30
        return spec["gb"] + (spec.get("live_gb", 0) if params.get("live") else 0) + (SOURCE_GB if params.get("source") else 0)

    def live_dir(self, job):
        """Where the steps of a running job are written. Removed when the job ends."""
        return Path(self.config["output_dir"]) / "_live" / job["id"][-6:]

    def validate(self, params):
        if params.get("mode") != "fast" and params.get("model") in NOT_HERE:
            raise AdapterError(NOT_HERE[params["model"]])
        p = super().validate(params)
        if p["size"] not in self.config["sizes"]:
            # The old tools fell back to 1024x1024 silently; the queue says so at submit.
            raise AdapterError(f"'size' must be one of {sorted(self.config['sizes'])}")
        if p["mode"] == "fast":
            p["model"], p["steps"], p["quantize"] = "flux2-klein-4b", 4, 0
        elif p["steps"] == 0:
            p["steps"] = ENGINE_MODELS[p["model"]]["steps"]
        if p["seed"] < 0:
            p["seed"] = int(time.time()) % 100000
        if p["source"]:
            real = Path(p["source"]).resolve()
            roots = [Path(d).resolve() for d in [self.config["output_dir"], *self.config.get("source_dirs", []),
                                                 *[e for e in os.environ.get("NEOVAK_SOURCE_DIRS", "").split(":") if e]]]
            if not any(real.is_relative_to(r) for r in roots) or real.suffix.lower() not in (".png", ".jpg", ".jpeg", ".webp") or not real.is_file():
                raise AdapterError("That picture is not in a folder NeoVak may read.")
            p["source"] = str(real)
            w, h = source_size(real)
            if max(w / h, h / w) > MOST_STRETCHED:
                raise AdapterError("That picture is too long and thin to start from. Please crop it first.")
            if not 0.05 <= p["strength"] <= 0.95:
                raise AdapterError("'strength' must be between 0.05 and 0.95")
        return p

    def plan(self, job):
        p = job["params"]
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        prefix = "neovak_klein" if p["mode"] == "fast" else "neovak"
        # The job id keeps two jobs with the same seed in the same second from being given one file.
        return {"outputs": [str(Path(self.config["output_dir"]) / f"{prefix}_{stamp}_{p['seed']}_j{job['id'][-6:]}.png")]}

    def warm_key(self, params):
        """The key for the same picture made without writing each step out."""
        sw, sh = self.config["sizes"][params["size"]]
        return f"mflux:{params['model']}:{params['steps']}:{sw}x{sh}"

    def _watched(self, params):
        return bool(params.get("live")) and bool(ENGINE_MODELS.get(params.get("model"), {}).get("live_gb"))

    def estimate_key(self, params):
        # Writing each step's picture out (Watch it arrive) makes a run slower, so those runs are timed apart.
        return self.warm_key(params) + (":live" if self._watched(params) else "")

    def default_estimate(self, params, warm_seconds=None):
        """With no history of watched runs, the plain runs' time stretched by what watching was measured to add."""
        if warm_seconds is None:
            return None
        return round(warm_seconds * (LIVE_SLOWER if self._watched(params) else 1), 1)

    def parse_progress(self, line):
        out = super().parse_progress(line)
        if out:
            out["stage"] = "generating"
        return out

    def run(self, job, ctx):
        p = job["params"]
        styles, sizes = self.config["styles"], self.config["sizes"]
        style_suffix = styles.get(p["style"], "")
        full_prompt = f"{p['prompt']}, {style_suffix}" if style_suffix else p["prompt"]
        w, h = sizes.get(p["size"], (1024, 1024))
        if p.get("source"):  # keeps the shape of the picture it starts from, whatever size was named
            w, h = size_following(*source_size(p["source"]), w, h)
        output_path = job["outputs"][0]
        model_dir = Path(self.config["model_dir"])

        # Fast mode is klein with quantize 0: the exact command S1 parity proved pixel-identical.
        head = engine_command(self.config["venv_bin"], model_dir, p["model"], p["quantize"])
        # --quantize was appended by engine_command; everything else follows it in the same order
        # the old tools used, so the fast command line is unchanged.
        # One argument, so words that start with a dash cannot be read as one of mflux's own options.
        cmd = head + [f"--prompt={full_prompt}", "--seed", str(p["seed"]),
                      "--height", str(h), "--width", str(w),
                      "--steps", str(p["steps"]), "--output", output_path]
        if p.get("source"):  # read only; mflux keeps its picture as a starting point
            cmd += ["--image-path", p["source"], "--image-strength", str(p["strength"])]
        live = self.live_dir(job) if p.get("live") and ENGINE_MODELS[p["model"]].get("live_gb") else None
        if live:
            live.mkdir(parents=True, exist_ok=True)
            cmd += ["--stepwise-image-output-dir", str(live)]

        env = os.environ.copy()
        env["HF_HOME"] = str(model_dir / "huggingface")
        # Every weight is on disk. Offline means a dead connection cannot stall the load.
        env["HF_HUB_OFFLINE"] = "1"
        ctx.progress(stage="loading model", total=p["steps"])
        start = time.time()
        try:
            r = ctx.spawn(cmd, env=env, measure=True)
        finally:
            if live:
                shutil.rmtree(live, ignore_errors=True)
        elapsed = round(time.time() - start, 1)
        if ctx.cancel_requested:
            for f in glob.glob(output_path):
                os.remove(f)
            return None
        if r.returncode != 0 or not Path(output_path).exists():
            if any(mark in (r.stderr or "") for mark in MISSING_WEIGHTS):
                raise AdapterError("That model's files are not on this machine, so nothing was made. "
                                   "Nothing was downloaded: NeoVak stays offline while it makes things.")
            raise AdapterError(r.stderr[-500:] if r.stderr else f"mflux exited {r.returncode}")

        recorded = written_model(output_path)
        wrong = check_identity(p["model"], recorded)
        if wrong:
            os.remove(output_path)
            raise AdapterError(wrong)

        out = {"files": [output_path], "path": output_path, "seed": p["seed"],
               "prompt": full_prompt, "size": f"{w}x{h}", "model": p["model"],
               "model_in_file": recorded, "peak_gb": getattr(r, "peak_gb", None),
               "time_seconds": elapsed}
        if p["mode"] == "standard":
            out["steps"] = p["steps"]
            out["thumbnail"] = self._thumbnail(output_path)
            out["files"].append(out["thumbnail"])
            if os.environ.get("NEOVAK_PREVIEW", "").lower() in ("1", "true", "yes"):
                subprocess.Popen(["open", "-a", "Preview", output_path])
        return out

    def _thumbnail(self, src, max_size=384):
        # Same result as make_thumbnail() in neovak_server.py; the path goes in argv, not code.
        thumb = src.replace(".png", "_thumb.png")
        code = ("import sys; from PIL import Image; im=Image.open(sys.argv[1]); "
                "im.thumbnail((int(sys.argv[3]),)*2); im.save(sys.argv[2])")
        subprocess.run([str(Path(self.config["venv_bin"]) / "python3"), "-c", code,
                        src, thumb, str(max_size)], capture_output=True)
        return thumb
