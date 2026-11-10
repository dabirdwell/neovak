"""Enhance and edit lane: change a picture from an instruction, make it bigger, remove its
background, restore faces.

Four adapters, one rule: the source is only read and the result is always a new file with a name
no other job can have. A source must already be inside a folder NeoVak may read.

Measured memory (STUDIO_PLAN.md, the enhance and edit stage) is what the governor is asked for.
"""
import json
import os
import re
import subprocess
import time
from datetime import datetime
from pathlib import Path

from .base import Adapter, AdapterError
from .mflux_image import written_model

SOURCE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}
MAX_SOURCE_PIXELS = 36_000_000
from .. import settings as _settings  # noqa: E402

TOOLS = Path(__file__).resolve().parent.parent / "tools"
_S = _settings.load()
# Face repair needs the GFPGAN weights and a python3 with torch and spandrel. Both come from the settings file.
GFPGAN = Path(_S.tool("gfpgan")) if _S.tool("gfpgan") else Path("/nonexistent/GFPGANv1.4.pth")
FACE_PYTHON = Path(_S.tool("face_python")) if _S.tool("face_python") else Path("/nonexistent/python3")
SWIFTC = _S.tool("swiftc") or "/usr/bin/swiftc"
VISION_TOOL = _S.tool("vision")
NOT_SET_UP = "Face repair needs the GFPGAN weights and a Python with torch, which are not set up on this machine. The settings file names them under [tools] gfpgan and face_python."


class ImageTool(Adapter):
    lane = "edit"
    prefix = "neovak_edit"

    def _roots(self):
        extra = [d for d in os.environ.get("NEOVAK_SOURCE_DIRS", "").split(":") if d]
        return [Path(d).resolve() for d in [self.config["output_dir"], *self.config.get("source_dirs", []), *extra]]

    def checked_source(self, path):
        """The real path of a readable picture inside an allowed folder, and its size."""
        if not isinstance(path, str) or not path or "\x00" in path or not path.startswith("/"):
            raise AdapterError("Please give the full path of a picture in the output folder.")
        real = Path(path).resolve()
        if not any(real.is_relative_to(root) for root in self._roots()):
            raise AdapterError("That picture is not in a folder NeoVak may read.")
        if real.suffix.lower() not in SOURCE_SUFFIXES or not real.is_file():
            raise AdapterError("That is not a picture NeoVak can open (PNG, JPEG or WebP).")
        from PIL import Image
        try:
            with Image.open(real) as im:
                width, height = im.size
                im.verify()
        except Exception:
            raise AdapterError("That file could not be read as a picture.")
        if width * height > MAX_SOURCE_PIXELS:
            raise AdapterError("That picture is too large. Please use one under 36 megapixels.")
        return str(real), width, height

    def validate(self, params):
        p = super().validate(params)
        p["source"], _, _ = self.checked_source(p["source"])
        return p

    def plan(self, job):
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        seed = job["params"].get("seed")
        tag = f"_{seed}" if seed is not None else ""
        name = f"{self.prefix}_{stamp}{tag}_j{job['id'][-6:]}.png"
        return {"outputs": [str(Path(self.config["output_dir"]) / name)]}

    def parse_progress(self, line):
        out = super().parse_progress(line)
        if out:
            out["stage"] = "working"
        return out

    def engine_env(self):
        env = os.environ.copy()
        env["HF_HOME"] = str(Path(self.config["model_dir"]) / "huggingface")
        env["HF_HUB_OFFLINE"] = "1"  # every weight is on disk; a dead connection cannot stall the load
        return env

    def finish(self, job, ctx, r, what, **fields):
        """Shared end of a run: no partial file after a cancel, a plain error after a failure."""
        output = Path(job["outputs"][0])
        if ctx.cancel_requested:
            output.unlink(missing_ok=True)
            return None
        if getattr(r, "timed_out", False):
            output.unlink(missing_ok=True)
            raise AdapterError(f"{what} stopped responding and was stopped.")
        if r.returncode != 0 or not output.exists() or output.stat().st_size == 0:
            output.unlink(missing_ok=True)
            # measure=True appends /usr/bin/time's report; the useful part is what came before it.
            detail = re.split(r"\n\s*[\d.]+ real", r.stderr or "")[0].strip()
            raise AdapterError(detail[-500:] or f"{what} exited {r.returncode}")
        out = {"files": [str(output)], "path": str(output), "source_image": job["params"]["source"],
               "peak_gb": getattr(r, "peak_gb", None)}
        out.update(fields)
        return out


def _new_seed(seed):
    return seed if seed >= 0 else int(time.time()) % 100000


def fit_megapixel(width, height, area=1024 * 1024, step=16):
    """Same shape as the source, about one megapixel, on the grid the model needs. A source that is already on the grid
    and close to one megapixel (0.7 to 1.2) is worked on at its own size, so the result is not a few pixels off."""
    for k in range(1, 9):  # the source itself, or an exact half, third, ... of it, when that lands on the grid at about one megapixel
        if width % (k * step) == 0 and height % (k * step) == 0 and 0.7 * area <= (width // k) * (height // k) <= 1.2 * area:
            return width // k, height // k
    scale = (area / (width * height)) ** 0.5
    return (max(step, round(width * scale / step) * step), max(step, round(height * scale / step) * step))


def back_to_size(path, width, height):
    """The picture at path resized to width by height (Lanczos), keeping its text records (the model's name, the words),
    so a changed picture lines up with the one it came from. Nothing is done when it is already that size."""
    from PIL import Image, PngImagePlugin
    with Image.open(path) as im:
        if im.size == (width, height):
            return False
        info = dict(im.info or {})
        out = im.convert("RGBA" if im.mode in ("RGBA", "LA", "P") else "RGB").resize((width, height), Image.LANCZOS)
    meta = PngImagePlugin.PngInfo()
    for k, v in info.items():
        if not isinstance(k, str):
            continue
        if isinstance(v, bytes) and k == "XML:com.adobe.xmp":
            v = v.decode("utf-8", "replace")
        if isinstance(v, str):
            # the XMP packet (where the engine writes which model made the file) goes back as international text
            (meta.add_itxt if k == "XML:com.adobe.xmp" else meta.add_text)(k, v)
    tmp = str(path) + ".resize.png"
    extra = {"exif": info["exif"]} if isinstance(info.get("exif"), bytes) else {}
    out.save(tmp, pnginfo=meta, **extra)
    os.replace(tmp, path)
    return True


class KontextEdit(ImageTool):  # measured 27.5 GB peak, 450 s at 1024 by 1024, 20 steps
    name = "kontext"
    summary = "Change a picture by describing the change, with FLUX.1 Kontext dev."
    prefix = "neovak_edit"
    params = {
        "source": {"type": "str", "help": "Full path of the picture to change. It is only read."},
        "prompt": {"type": "str", "help": "The change to make, in words."},
        "steps": {"type": "int", "default": 20},
        "guidance": {"type": "float", "default": 2.5},
        "seed": {"type": "int", "default": -1},
    }

    def memory_gb(self, params):
        return 29

    def validate(self, params):
        p = super().validate(params)
        p["prompt"] = p["prompt"].strip()
        if not p["prompt"]:
            raise AdapterError("Please describe the change you want.")
        if not 1 <= p["steps"] <= 50:
            raise AdapterError("'steps' must be between 1 and 50")
        p["seed"] = _new_seed(p["seed"])
        return p

    def estimate_key(self, params):
        return f"kontext:{params['steps']}"

    def run(self, job, ctx):
        p, output = job["params"], job["outputs"][0]
        _, src_w, src_h = self.checked_source(p["source"])
        w, h = fit_megapixel(src_w, src_h)
        binary = str(Path(self.config["venv_bin"]) / "mflux-generate-kontext")
        cmd = [binary, "--model", "dev-kontext", "--low-ram", f"--prompt={p['prompt']}",
               "--image-path", p["source"], "--seed", str(p["seed"]), "--steps", str(p["steps"]),
               "--guidance", str(p["guidance"]), "--width", str(w), "--height", str(h), "--output", output]
        ctx.progress(stage="loading model", total=p["steps"])
        start = time.time()
        r = ctx.spawn(cmd, env=self.engine_env(), measure=True)
        out = self.finish(job, ctx, r, "The picture editor", seed=p["seed"], prompt=p["prompt"],
                          size=f"{w}x{h}", model="dev-kontext", steps=p["steps"],
                          time_seconds=round(time.time() - start, 1))
        if out is None:
            return None
        recorded = written_model(output)
        out["model_in_file"] = recorded
        if recorded and "kontext" not in str(recorded).lower():
            os.remove(output)
            raise AdapterError(f"asked for FLUX.1 Kontext dev but the file says it was made by {recorded}")
        # The model works on its own grid; the changed picture comes back at its source's size, so it lines up with it
        # on the Timeline and in Compare. Only a small, same shape step is made here (at most 15 percent either way).
        if (w, h) != (src_w, src_h) and 0.85 <= (w / src_w) <= 1.18 and 0.85 <= (h / src_h) <= 1.18:
            try:
                if back_to_size(output, src_w, src_h):
                    out["size"], out["model_size"] = f"{src_w}x{src_h}", f"{w}x{h}"
            except Exception:  # noqa: BLE001  the picture as the model made it is still a good picture
                pass
        return out


class SeedvrUpscale(ImageTool):  # measured 10.9 GB peak, 72 s at 2x of 1024; 17.3 GB, 291 s at 4x
    name = "seedvr2"
    summary = "Make a picture larger and sharper with SeedVR2."
    prefix = "neovak_upscaled"
    params = {
        "source": {"type": "str", "help": "Full path of the picture to enlarge. It is only read."},
        "scale": {"type": "int", "default": 2, "choices": [2, 3, 4], "help": "How many times larger."},
        "softness": {"type": "float", "default": 0.0, "help": "0 stays closest to the original, 1 is softest."},
        "seed": {"type": "int", "default": -1},
    }
    MAX_OUTPUT_SIDE = 4096

    def memory_gb(self, params):
        return {2: 13, 3: 19, 4: 19}.get(params.get("scale", 2), 19)

    def validate(self, params):
        p = super().validate(params)
        _, w, h = self.checked_source(p["source"])
        if max(w, h) * p["scale"] > self.MAX_OUTPUT_SIDE:
            raise AdapterError(f"That would be wider than {self.MAX_OUTPUT_SIDE} pixels. Please pick a smaller "
                               "enlargement or a smaller picture.")
        if not 0 <= p["softness"] <= 1:
            raise AdapterError("'softness' must be between 0 and 1")
        p["seed"] = _new_seed(p["seed"])
        return p

    def estimate_key(self, params):
        return f"seedvr2:{params['scale']}"

    def run(self, job, ctx):
        p, output = job["params"], job["outputs"][0]
        _, w, h = self.checked_source(p["source"])
        # Not the mflux-upscale-seedvr2 command itself: that fails on this machine's MLX (see the script).
        cmd = [str(Path(self.config["venv_bin"]) / "python3"), str(TOOLS / "seedvr2_run.py"), "--low-ram", "--image-path", p["source"], "--seed", str(p["seed"]),
               "--resolution", f"{p['scale']}x", "--softness", str(p["softness"]), "--output", output]
        ctx.progress(stage="enlarging")
        start = time.time()
        r = ctx.spawn(cmd, env=self.engine_env(), measure=True)
        out = self.finish(job, ctx, r, "The enlarger", seed=p["seed"], scale=p["scale"], softness=p["softness"],
                          size=f"{w * p['scale']}x{h * p['scale']}", model="seedvr2",
                          time_seconds=round(time.time() - start, 1))
        if out is None:
            return None
        out["model_in_file"] = written_model(output)
        return out


def _vision_tool():
    """The compiled Vision helper: the one the settings name, or built on first use from its source
    and again whenever that source changes."""
    if VISION_TOOL and Path(VISION_TOOL).is_file():
        return VISION_TOOL
    source = TOOLS / "vision_tool.swift"
    built = _settings.load().state_dir / "tools" / "vision_tool"
    built.parent.mkdir(parents=True, exist_ok=True)
    if not built.exists() or built.stat().st_mtime < source.stat().st_mtime:
        r = subprocess.run([SWIFTC, "-O", str(source), "-o", str(built)],
                           capture_output=True, text=True, timeout=300)
        if r.returncode != 0:
            raise AdapterError("The background and face finder could not be built on this machine: "
                               + r.stderr[-300:])
    return str(built)


class BackgroundCutout(ImageTool):
    name = "cutout"
    summary = "Remove the background, keeping the main subject, with Apple's Vision framework."
    prefix = "neovak_cutout"
    params = {"source": {"type": "str", "help": "Full path of the picture. It is only read."}}

    def memory_gb(self, params):
        return 1  # 0.1 GB measured in the process; Vision's own model is held by the system

    def run(self, job, ctx):
        p, output = job["params"], job["outputs"][0]
        tool = _vision_tool()
        ctx.progress(stage="finding the subject")
        start = time.time()
        r = ctx.spawn([tool, "cutout", p["source"], output], measure=True, timeout=300)
        if r.returncode == 3 or (r.returncode and "no subject" in (r.stderr or "")):
            raise AdapterError("No clear subject was found in this picture, so nothing was made.")
        out = self.finish(job, ctx, r, "Background removal", model="apple-vision",
                          time_seconds=round(time.time() - start, 1))
        if out is None:
            return None
        from PIL import Image
        with Image.open(output) as im:
            low, high = im.getchannel("A").getextrema() if "A" in im.getbands() else (255, 255)
            out["size"] = f"{im.size[0]}x{im.size[1]}"
        if low != 0 or high != 255:
            Path(output).unlink(missing_ok=True)
            raise AdapterError("The subject could not be separated from the background, so nothing was made.")
        return out


class FaceRestore(ImageTool):
    name = "faces"
    summary = "Sharpen and repair faces in a picture with GFPGAN. Faces are found with Apple's Vision framework."
    prefix = "neovak_faces"
    params = {
        "source": {"type": "str", "help": "Full path of the picture. It is only read."},
        "strength": {"type": "float", "default": 0.8, "help": "How much of the repair to keep, 0 to 1."},
    }

    def models(self):
        return [{"model": "gfpgan-1.4", "present": GFPGAN.exists() and FACE_PYTHON.exists()}]

    def memory_gb(self, params):
        return 4  # 3.1 GB measured

    def validate(self, params):
        if not GFPGAN.exists() or not FACE_PYTHON.exists():
            raise AdapterError(NOT_SET_UP)
        p = super().validate(params)
        if not 0 < p["strength"] <= 1:
            raise AdapterError("'strength' must be above 0 and at most 1")
        return p

    def run(self, job, ctx):
        p, output = job["params"], job["outputs"][0]
        tool = _vision_tool()
        cmd = [str(FACE_PYTHON), str(TOOLS / "restore_faces.py"), p["source"], output, str(GFPGAN), tool,
               str(p["strength"])]
        ctx.progress(stage="repairing faces")
        start = time.time()
        r = ctx.spawn(cmd, env=self.engine_env(), measure=True, timeout=900)
        if r.returncode == 3:
            raise AdapterError("No faces large enough to repair were found, so nothing was made.")
        out = self.finish(job, ctx, r, "Face repair", model="gfpgan-1.4", time_seconds=round(time.time() - start, 1))
        if out is None:
            return None
        for line in reversed((r.stdout or "").splitlines()):
            if line.startswith("{"):
                out.update(json.loads(line))
                break
        return out
