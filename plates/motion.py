#!/usr/bin/env python3
"""motion.py: a keyframe engine for the plates pipeline.

open_proof.py is one show open written by hand. This is the same idea as data:
a timeline in JSON, a stack of layers, animatable properties, ease curves,
frames on disk, H.264 out through ffmpeg. Deterministic: same JSON in, same
frames out, every run.

Run from neovak-mcp/:
    ./venv/bin/python plates/motion.py plates/examples/this_machine_open.json
    ./venv/bin/python plates/motion.py plates/examples/this_machine_open.json --max-frames 24 --no-video
    ./venv/bin/python plates/motion.py --smoke
    ./venv/bin/python plates/motion.py --schema

===========================================================================
TIMELINE SCHEMA
===========================================================================

Top level (all times in seconds unless noted):

    {
      "name":       "this_machine_open",   # used for default output names
      "width":      1216,                  # canvas width in px
      "height":     704,                   # canvas height in px
      "fps":        24,
      "duration":   8.0,                   # seconds; frame count = round(fps*duration)
      "background": "#000000",             # canvas fill under every layer
      "out":        "plates/out/x.mp4",    # optional; default plates/out/<name>.mp4
      "frames_dir": "plates/out/_x",       # optional; default plates/out/_<name>_frames
      "crf":        17,                    # optional H.264 quality (lower is better)
      "grade":      {                      # optional global grade, applied per frame
        "exposure": 1.0, "contrast": 1.0, "saturation": 1.0,
        "tint": [1.0, 1.0, 1.0], "vignette": 0.0, "grain": 0.0
      },
      "layers": [ ... ]                    # bottom of the stack first
    }

Every layer:

    {
      "name":   "plate",             # free label, shown in --verbose output
      "type":   "image" | "alpha_image" | "type" | "sequence",
      "blend":  "normal",            # normal screen add multiply overlay soft_light lighten
      "fit":      "cover",           # cover contain height width native
      "fit_size": 0.52,              # fraction of canvas for fit=height / fit=width
      "anchor": [0.5, 0.5],          # the layer point pinned to (x, y), normalized 0..1
      "subpixel": false,             # true places the layer on fractional pixels, for slow
                                     # moves that would otherwise step one whole pixel at a time
      "units":  "fraction",          # "fraction" (of canvas) or "px" for the x/y values
      "in":     0.0,                 # optional visibility window start (seconds)
      "out":    8.0,                 # optional visibility window end (seconds)
      "keys":   { ... }              # animated properties, see below
    }

Layer types and their extra fields:

  image        "src": path to a PNG/JPG. RGB is treated as fully opaque; RGBA
               uses its own alpha.
  alpha_image  "src": path to an RGBA PNG. Same as image but errors if the file
               has no alpha channel, so a silently-opaque logo cannot slip through.
  type         Rendered through plates/typeset.py at build time and cached.
               "text" (required; "\\n" splits lines), plus optional "font",
               "index", "size", "fill", "tracking", "leading", "pad",
               "shadow", "edge". Identical text specs render once and are reused.
               Note "size" here is the type point size, not a canvas fraction.
               The canvas fraction is always "fit_size", on every layer type.
  sequence     "src": a directory, a glob, or a printf pattern such as
               "mark/out/anim/frames/f_%04d.png".
               "matte": "alpha" (default) or "luma" for frames flattened onto
                        black, where luminance is the matte.
               "frame_mode": "loop" (default) | "hold" | "once"
                        loop repeats, hold clamps to the last frame, once stops
                        drawing the layer after the sequence is exhausted.
               "frame_offset": integer, added to the sequence index.
               "speed": float, sequence frames per canvas frame (default 1.0).

Animated properties, all optional, all scalars:

    x         horizontal position of the anchor point.       default 0.5
    y         vertical position of the anchor point.         default 0.5
    scale     multiplier on the size set by fit/fit_size.    default 1.0
    opacity   0..1, multiplied into the layer matte.         default 1.0
    rotation  degrees, counter-clockwise, about layer center default 0.0

A property is either a constant:

    "keys": { "opacity": 0.9 }

or a list of keyframes, each with a time and a value:

    "keys": {
      "opacity": [
        {"t": 0.5, "v": 0.0},
        {"t": 2.0, "v": 0.9, "ease": "ease_out"}
      ]
    }

  t      time in seconds. Use "f" instead for a frame number.
  v      the value at that time.
  ease   the curve used to travel FROM the previous key TO this one.
         Defaults to "linear". The first key's ease is ignored.

Before the first key the value is held at the first key's value; after the
last key it is held at the last key's value. This is why a fade that should
start dark needs a flat key at zero before it rises.

Ease curves: linear, ease_in, ease_out, ease_in_out, ease_in_quad,
ease_out_quad, smoothstep, hold.
"ease_out" is the cubic 1-(1-t)^3 that open_proof.py uses.

===========================================================================
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from composite import _blend, grade as _grade  # noqa: E402  (reuse the pipeline's math)
import typeset as _typeset                     # noqa: E402

FFMPEG = "/opt/homebrew/bin/ffmpeg"
TYPE_CACHE = Path(os.environ.get("NEOVAK_TYPE_CACHE") or REPO / "plates" / "out" / "_type_cache")


class TimelineError(ValueError):
    """A timeline that cannot be rendered. Message is safe to show a user."""


# --------------------------------------------------------------------------- #
# Ease curves.  Each maps [0,1] -> [0,1].
# --------------------------------------------------------------------------- #
def _clamp01(x):
    return max(0.0, min(1.0, x))


EASES = {
    "linear":        lambda t: t,
    "ease_in":       lambda t: t ** 3,
    "ease_out":      lambda t: 1 - (1 - t) ** 3,
    "ease_in_out":   lambda t: 4 * t ** 3 if t < 0.5 else 1 - ((-2 * t + 2) ** 3) / 2,
    "ease_in_quad":  lambda t: t ** 2,
    "ease_out_quad": lambda t: 1 - (1 - t) ** 2,
    "smoothstep":    lambda t: t * t * (3 - 2 * t),
    "hold":          lambda t: 0.0 if t < 1.0 else 1.0,
}


# --------------------------------------------------------------------------- #
# Keyframe evaluation
# --------------------------------------------------------------------------- #
def _key_time(key, fps):
    """A keyframe carries either t (seconds) or f (frames). Seconds win."""
    if "t" in key:
        return float(key["t"])
    if "f" in key:
        return float(key["f"]) / float(fps)
    raise TimelineError(f"keyframe needs 't' (seconds) or 'f' (frames): {key}")


def eval_prop(spec, t, fps, default):
    """Value of one animatable property at time t (seconds)."""
    if spec is None:
        return default
    if isinstance(spec, (int, float)):
        return float(spec)
    if not isinstance(spec, list) or not spec:
        raise TimelineError(f"property must be a number or a non-empty keyframe list, got {spec!r}")

    keys = sorted(spec, key=lambda k: _key_time(k, fps))
    t0 = _key_time(keys[0], fps)
    if t <= t0:
        return float(keys[0]["v"])
    tn = _key_time(keys[-1], fps)
    if t >= tn:
        return float(keys[-1]["v"])

    for a, b in zip(keys, keys[1:]):
        ta, tb = _key_time(a, fps), _key_time(b, fps)
        if ta <= t <= tb:
            span = tb - ta
            u = 1.0 if span <= 0 else _clamp01((t - ta) / span)
            name = b.get("ease", "linear")
            if name not in EASES:
                raise TimelineError(
                    f"unknown ease '{name}'. Known: {', '.join(sorted(EASES))}")
            e = EASES[name](u)
            return float(a["v"]) + (float(b["v"]) - float(a["v"])) * e
    return float(keys[-1]["v"])


# --------------------------------------------------------------------------- #
# Sources
# --------------------------------------------------------------------------- #
def _resolve(path_str):
    """Timeline paths are relative to the repo root (neovak-mcp/)."""
    p = Path(path_str)
    return p if p.is_absolute() else (REPO / p)


def _sequence_frames(src):
    """Expand a directory, glob, or printf pattern into a sorted frame list."""
    import glob as _glob
    import re as _re

    raw = str(src)
    p = _resolve(raw)
    if p.is_dir():
        frames = sorted(p.glob("*.png"))
    elif _re.search(r"%0?\d*d", raw):
        d = p.parent
        rx = _re.sub(r"%0?\d*d", r"\\d+", p.name)
        frames = sorted(f for f in d.glob("*.png") if _re.fullmatch(rx, f.name))
    elif any(ch in raw for ch in "*?["):
        frames = sorted(Path(x) for x in _glob.glob(str(p)))
    else:
        frames = [p] if p.exists() else []
    if not frames:
        raise TimelineError(f"sequence source matched no frames: {raw}")
    return frames


def typeset_png(layer, cache_dir=TYPE_CACHE):
    """Render a type layer through plates/typeset.py. Cached by its spec hash."""
    text = layer.get("text")
    if not text:
        raise TimelineError("type layer needs 'text'")
    spec = dict(
        text=text,
        font=layer.get("font", _typeset.DFONT),
        index=int(layer.get("index", 6)),
        size=int(layer.get("size", 160)),
        fill=layer.get("fill", "#ece6d6"),
        tracking=int(layer.get("tracking", 2)),
        leading=float(layer.get("leading", 1.25)),
        pad=int(layer.get("pad", 48)),
        shadow=bool(layer.get("shadow", True)),
        shadow_off=int(layer.get("shadow_off", 4)),
        shadow_blur=int(layer.get("shadow_blur", 3)),
        shadow_alpha=int(layer.get("shadow_alpha", 170)),
        edge=bool(layer.get("edge", True)),
    )
    digest = hashlib.sha1(json.dumps(spec, sort_keys=True).encode()).hexdigest()[:12]
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    out = cache_dir / f"type_{digest}.png"
    if not out.exists():
        ns = SimpleNamespace(out=str(out), **spec)
        _typeset.render(ns)
    return out


def load_layer_source(layer):
    """Return ('still', Image) or ('seq', [paths])."""
    kind = layer.get("type", "image")
    if kind in ("image", "alpha_image"):
        src = layer.get("src")
        if not src:
            raise TimelineError(f"{kind} layer needs 'src'")
        p = _resolve(src)
        if not p.exists():
            raise TimelineError(f"source not found: {p}")
        img = Image.open(p)
        if kind == "alpha_image" and img.mode not in ("RGBA", "LA"):
            raise TimelineError(
                f"alpha_image layer '{layer.get('name', src)}' has no alpha channel "
                f"(mode {img.mode}). Use type 'image' or supply an RGBA PNG.")
        return "still", img.convert("RGBA") if img.mode != "RGBA" else img.copy()
    if kind == "type":
        return "still", Image.open(typeset_png(layer)).convert("RGBA")
    if kind == "sequence":
        src = layer.get("src")
        if not src:
            raise TimelineError("sequence layer needs 'src'")
        return "seq", _sequence_frames(src)
    raise TimelineError(
        f"unknown layer type '{kind}'. Known: image, alpha_image, type, sequence")


def _as_rgba(img, matte):
    """Give a frame an alpha channel. matte='luma' for frames flattened on black."""
    if matte == "luma":
        rgb = img.convert("RGB")
        a = img.convert("L")
        out = rgb.convert("RGBA")
        out.putalpha(a)
        return out
    if img.mode == "RGBA":
        return img
    out = img.convert("RGBA")
    if img.mode not in ("RGBA", "LA", "PA"):
        out.putalpha(255)
    return out


# --------------------------------------------------------------------------- #
# Placement
# --------------------------------------------------------------------------- #
def _iround(v):
    """Round half up, always. Python's round() is banker's rounding, so round(-1.5)
    is -2 and round(-2.5) is -2: ties shift asymmetrically and a centred layer can
    land a pixel off in one axis and not the other."""
    return int(math.floor(v + 0.5))


def _base_ratio(fit, size, fw, fh, W, H):
    if fit == "cover":
        return max(W / fw, H / fh)
    if fit == "contain":
        return min(W / fw, H / fh)
    if fit == "height":
        return (H * size) / fh
    if fit == "width":
        return (W * size) / fw
    if fit == "native":
        return 1.0
    raise TimelineError(
        f"unknown fit '{fit}'. Known: cover, contain, height, width, native")


def place(fg, canvas_size, layer, props):
    """Scale, rotate, and position one RGBA layer onto a canvas-sized RGBA plate."""
    W, H = canvas_size
    fit = layer.get("fit", "native")
    size = float(layer.get("fit_size", 1.0))
    anchor = layer.get("anchor", [0.5, 0.5])
    units = layer.get("units", "fraction")

    r = _base_ratio(fit, size, fg.width, fg.height, W, H) * props["scale"]
    if layer.get("subpixel") and abs(props["rotation"]) <= 1e-6:
        return _place_subpixel(fg, (W, H), r, anchor, units, props)
    nw, nh = max(1, _iround(fg.width * r)), max(1, _iround(fg.height * r))
    img = fg.resize((nw, nh), Image.LANCZOS)

    if abs(props["rotation"]) > 1e-6:
        img = img.rotate(props["rotation"], resample=Image.BICUBIC,
                         expand=True, fillcolor=(0, 0, 0, 0))
        nw, nh = img.size

    if props["opacity"] < 1.0:
        a = img.split()[3].point(lambda v: int(v * props["opacity"]))
        img.putalpha(a)

    if units == "px":
        cx, cy = props["x"], props["y"]
    else:
        cx, cy = props["x"] * W, props["y"] * H
    x = _iround(cx - anchor[0] * nw)
    y = _iround(cy - anchor[1] * nh)

    layer_img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    layer_img.alpha_composite(img, dest=(max(0, x), max(0, y)),
                              source=(max(0, -x), max(0, -y)))
    return layer_img


def _place_subpixel(fg, canvas_size, r, anchor, units, props):
    """place() for a layer on fractional pixels: one affine map from canvas back to the source,
    so a slow move or zoom glides instead of stepping a whole pixel at a time."""
    W, H = canvas_size
    cx, cy = (props["x"], props["y"]) if units == "px" else (props["x"] * W, props["y"] * H)
    # The anchor lands on a whole source pixel, so a layer resting on a whole canvas pixel at
    # scale 1 is sampled exactly and stays as sharp as it was drawn.
    matrix = (1 / r, 0, _iround(anchor[0] * fg.width) - cx / r,
              0, 1 / r, _iround(anchor[1] * fg.height) - cy / r)
    out = fg.transform((W, H), Image.AFFINE, matrix, resample=Image.BICUBIC, fillcolor=(0, 0, 0, 0))
    if props["opacity"] < 1.0:
        out.putalpha(out.split()[3].point(lambda v: int(v * props["opacity"])))
    return out


def blend_onto(canvas_rgb, layer_rgba, mode):
    """Blend one placed layer onto the canvas. Arrays uint8 RGB in, uint8 RGB out."""
    bg = canvas_rgb.astype(np.float32) / 255.0
    fg = np.asarray(layer_rgba, np.float32) / 255.0
    alpha = fg[..., 3:4]
    blended = _blend(bg, fg[..., :3], mode)
    out = bg * (1 - alpha) + blended * alpha
    return np.clip(out * 255, 0, 255).astype(np.uint8)


# --------------------------------------------------------------------------- #
# Timeline validation and rendering
# --------------------------------------------------------------------------- #
PROP_DEFAULTS = {"x": 0.5, "y": 0.5, "scale": 1.0, "opacity": 1.0, "rotation": 0.0}
KNOWN_BLENDS = {"normal", "screen", "add", "linear_dodge", "multiply",
                "overlay", "soft_light", "lighten"}


def load_timeline(path):
    p = _resolve(path)
    if not p.exists():
        raise TimelineError(f"timeline not found: {p}")
    try:
        tl = json.loads(p.read_text())
    except json.JSONDecodeError as e:
        raise TimelineError(f"timeline is not valid JSON: {e}") from e
    return validate(tl)


def validate(tl):
    if not isinstance(tl, dict):
        raise TimelineError("timeline must be a JSON object")
    for field in ("width", "height", "fps", "duration"):
        if field not in tl:
            raise TimelineError(f"timeline missing required field '{field}'")
    if not isinstance(tl.get("layers"), list) or not tl["layers"]:
        raise TimelineError("timeline needs a non-empty 'layers' list")
    if int(tl["width"]) <= 0 or int(tl["height"]) <= 0:
        raise TimelineError("width and height must be positive")
    if float(tl["fps"]) <= 0 or float(tl["duration"]) <= 0:
        raise TimelineError("fps and duration must be positive")
    for i, layer in enumerate(tl["layers"]):
        if not isinstance(layer, dict):
            raise TimelineError(f"layer {i} must be an object")
        mode = layer.get("blend", "normal")
        if mode not in KNOWN_BLENDS:
            raise TimelineError(
                f"layer {i} '{layer.get('name', '')}': unknown blend '{mode}'. "
                f"Known: {', '.join(sorted(KNOWN_BLENDS))}")
        if "size" in layer and layer.get("type") != "type":
            raise TimelineError(
                f"layer {i} '{layer.get('name', '')}': 'size' is the type point size and "
                f"only applies to type layers. Use 'fit_size' for the canvas fraction.")
        for prop in layer.get("keys", {}):
            if prop not in PROP_DEFAULTS:
                raise TimelineError(
                    f"layer {i} '{layer.get('name', '')}': unknown property '{prop}'. "
                    f"Animatable: {', '.join(sorted(PROP_DEFAULTS))}")
    return tl


def _hex_rgb(s):
    s = str(s).lstrip("#")
    return tuple(int(s[j:j + 2], 16) for j in (0, 2, 4))


def render(tl, max_frames=None, make_video=True, out=None, frames_dir=None, verbose=False,
           progress=False, still_at=None):
    """Render a validated timeline. Returns a result dict. progress prints one line per frame
    for a job queue. still_at renders only the frame at that time, as a PNG at out."""
    W, H = int(tl["width"]), int(tl["height"])
    fps = float(tl["fps"])
    name = tl.get("name", "motion")
    total = int(round(fps * float(tl["duration"])))
    n = total if max_frames is None else min(total, int(max_frames))
    indices = range(n)
    if still_at is not None:
        n, make_video = 1, False
        indices = [max(0, min(total - 1, int(round(float(still_at) * fps))))]
    if n < 1:
        raise TimelineError("timeline resolves to zero frames")

    frames_dir = Path(frames_dir or _resolve(
        tl.get("frames_dir", f"plates/out/_{name}_frames")))
    out_path = Path(out or _resolve(tl.get("out", f"plates/out/{name}.mp4")))
    if frames_dir.exists():
        shutil.rmtree(frames_dir)
    frames_dir.mkdir(parents=True, exist_ok=True)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    bg = _hex_rgb(tl.get("background", "#000000"))
    grade_kw = tl.get("grade")

    # Resolve every source once, up front, so a bad path fails before frame 0.
    sources = []
    for layer in tl["layers"]:
        kind, data = load_layer_source(layer)
        sources.append((kind, data))
        if verbose:
            what = f"{len(data)} frames" if kind == "seq" else f"{data.width}x{data.height}"
            print(f"  layer '{layer.get('name', layer.get('type'))}' "
                  f"[{layer.get('type', 'image')}] {what}")

    for count, i in enumerate(indices):
        t = i / fps
        canvas = np.zeros((H, W, 3), np.uint8)
        canvas[:, :] = bg
        for layer, (kind, data) in zip(tl["layers"], sources):
            t_in = float(layer.get("in", -1e9))
            t_out = float(layer.get("out", 1e9))
            if not (t_in <= t <= t_out):
                continue
            keys = layer.get("keys", {})
            props = {k: eval_prop(keys.get(k), t, fps, v)
                     for k, v in PROP_DEFAULTS.items()}
            props["opacity"] = _clamp01(props["opacity"])
            if props["opacity"] <= 0.0 or props["scale"] <= 0.0:
                continue

            if kind == "seq":
                idx = int(i * float(layer.get("speed", 1.0))) + int(layer.get("frame_offset", 0))
                mode_seq = layer.get("frame_mode", "loop")
                if mode_seq == "loop":
                    idx %= len(data)
                elif mode_seq == "hold":
                    idx = max(0, min(len(data) - 1, idx))
                else:  # once
                    if idx < 0 or idx >= len(data):
                        continue
                fg = _as_rgba(Image.open(data[idx]), layer.get("matte", "alpha"))
            else:
                fg = data

            placed = place(fg, (W, H), layer, props)
            canvas = blend_onto(canvas, placed, layer.get("blend", "normal"))

        if grade_kw:
            canvas = _grade(canvas, seed=i, **grade_kw)
        if still_at is not None:
            Path(out_path).parent.mkdir(parents=True, exist_ok=True)
            Image.fromarray(canvas, "RGB").save(out_path)
        else:
            Image.fromarray(canvas, "RGB").save(frames_dir / f"f_{i:04d}.png", compress_level=tl.get("frame_compress", 6))
        if progress:
            print(f"motion frame {count + 1}/{n}", flush=True)

    result = {
        "frames": n,
        "total_frames": total,
        "frames_dir": str(frames_dir),
        "width": W, "height": H, "fps": fps,
        "duration_seconds": round(n / fps, 4),
        "name": name,
    }

    if still_at is not None:
        result.update(path=str(out_path), video=False)
        return result
    if not make_video:
        result["path"] = None
        result["video"] = False
        return result

    if progress:
        print("motion encoding", flush=True)
    cmd = [
        FFMPEG, "-loglevel", "error", "-y",
        "-framerate", str(fps), "-i", str(frames_dir / "f_%04d.png"),
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",
        "-crf", str(tl.get("crf", 17)), "-movflags", "+faststart",
        str(out_path),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise TimelineError("ffmpeg failed: " + (res.stderr or "")[-800:])
    result["path"] = str(out_path)
    result["video"] = True
    return result


# --------------------------------------------------------------------------- #
# Smoke test
# --------------------------------------------------------------------------- #
def smoke(max_frames=24):
    """Render the example timeline at reduced length. Exits non-zero on failure."""
    tl = load_timeline("plates/examples/this_machine_open.json")
    r = render(tl, max_frames=max_frames, make_video=True,
               out=REPO / "plates/out/_motion_smoke.mp4",
               frames_dir=REPO / "plates/out/_motion_smoke_frames",
               verbose=True)
    got = sorted(Path(r["frames_dir"]).glob("f_*.png"))
    ok = len(got) == max_frames and Path(r["path"]).exists()
    first = Image.open(got[0])
    last = Image.open(got[-1])
    d = np.abs(np.asarray(first, np.int16) - np.asarray(last, np.int16)).mean()
    print(f"motion smoke: frames={len(got)} expected={max_frames} "
          f"size={first.size} mp4={r['path']} mean_first_last_delta={d:.2f}")
    if not ok:
        print("motion smoke FAILED", file=sys.stderr)
        return 1
    if d < 0.5:
        print("motion smoke FAILED: frames are static, nothing animated",
              file=sys.stderr)
        return 1
    print("motion smoke OK")
    return 0


def main():
    ap = argparse.ArgumentParser(
        description="Render a JSON motion timeline to frames and H.264.",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("timeline", nargs="?", help="path to a timeline JSON file")
    ap.add_argument("--out", help="override the output mp4 path")
    ap.add_argument("--frames-dir", help="override the frame output directory")
    ap.add_argument("--max-frames", type=int, help="render only the first N frames")
    ap.add_argument("--no-video", action="store_true", help="write frames, skip ffmpeg")
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--schema", action="store_true", help="print the timeline schema")
    ap.add_argument("--smoke", action="store_true", help="run the built-in smoke test")
    ap.add_argument("--progress", action="store_true", help="print one line per frame, for a job queue")
    ap.add_argument("--still-at", type=float, help="render only the frame at this time, as a PNG at --out")
    a = ap.parse_args()

    if a.schema:
        print(__doc__)
        return 0
    if a.smoke:
        return smoke()
    if not a.timeline:
        ap.error("give a timeline JSON path, or use --smoke / --schema")

    try:
        tl = load_timeline(a.timeline)
        r = render(tl, max_frames=a.max_frames, make_video=not a.no_video,
                   out=a.out, frames_dir=a.frames_dir, verbose=a.verbose,
                   progress=a.progress, still_at=a.still_at)
    except TimelineError as e:
        print(f"motion error: {e}", file=sys.stderr)
        return 2
    where = r["path"] or r["frames_dir"]
    if a.still_at is not None:
        print(f"motion OK: {where}  still at {a.still_at}s")
        return 0
    print(f"motion OK: {where}  {r['frames']}/{r['total_frames']} frames "
          f"@ {r['fps']}fps, {r['width']}x{r['height']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
