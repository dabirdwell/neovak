#!/usr/bin/env python3
"""
composite.py: composite a foreground over a background PLATE with blend modes
and a colour grade. Outputs a PNG (still) or an mp4 (frame sequence).

Foreground may be:
  * a single alpha PNG  (e.g. the phoenix mark, a title card)
  * a frame sequence    (a directory or a printf/glob pattern of PNGs)

Background plate may be a still PNG/JPG. If the foreground is a frame sequence
and the plate is a still, the plate is held under the moving foreground and the
result is encoded to mp4 via ffmpeg.

Blend modes: normal screen add multiply overlay soft_light lighten
Grade:       exposure, contrast, saturation, tint, vignette, grain

Examples:
  # still mark over a still plate, screen blend, warm grade
  ./venv/bin/python plates/composite.py \
      --plate plates/out/amber_dusk_proc_s7.png \
      --fg mark/out/lockup/mark_1024_alpha.png \
      --mode screen --fit center --scale 0.78 \
      --out plates/out/composite_mark_over_dusk.png

  # phoenix animation frames over a plate -> mp4
  ./venv/bin/python plates/composite.py \
      --plate plates/out/cyan_data_proc_s7.png \
      --fg "mark/out/anim/frames/f_%04d.png" \
      --mode screen --fit center --scale 0.8 --fps 24 \
      --out plates/out/composite_phoenix.mp4
"""

from __future__ import annotations

import argparse
import glob
import re
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
FFMPEG = "/opt/homebrew/bin/ffmpeg"


# --------------------------------------------------------------------------- #
# Blend modes  (arrays in [0,1])
# --------------------------------------------------------------------------- #
def _blend(base, top, mode):
    a, b = base, top
    if mode == "normal":
        return b
    if mode == "multiply":
        return a * b
    if mode == "screen":
        return 1 - (1 - a) * (1 - b)
    if mode in ("add", "linear_dodge"):
        return np.clip(a + b, 0, 1)
    if mode == "lighten":
        return np.maximum(a, b)
    if mode == "overlay":
        return np.where(a < 0.5, 2 * a * b, 1 - 2 * (1 - a) * (1 - b))
    if mode == "soft_light":           # pegtop
        return (1 - 2 * b) * a ** 2 + 2 * b * a
    raise ValueError(f"unknown blend mode: {mode}")


# --------------------------------------------------------------------------- #
# Placement
# --------------------------------------------------------------------------- #
def _place(fg: Image.Image, plate_size, fit, scale):
    """Return an RGBA layer the size of the plate with fg placed into it."""
    W, H = plate_size
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    fg = fg.convert("RGBA")
    fw, fh = fg.size
    if fit == "fill":          # cover the whole plate
        r = max(W / fw, H / fh)
    elif fit == "contain":
        r = min(W / fw, H / fh)
    else:                      # center at `scale` * plate height
        r = (H * scale) / fh
    nw, nh = max(1, int(fw * r)), max(1, int(fh * r))
    fg = fg.resize((nw, nh), Image.LANCZOS)
    x, y = (W - nw) // 2, (H - nh) // 2
    layer.alpha_composite(fg, (x, y))
    return layer


# --------------------------------------------------------------------------- #
# Composite one frame
# --------------------------------------------------------------------------- #
def composite_frame(plate_rgb: np.ndarray, fg_layer: Image.Image, mode, opacity=1.0):
    bg = plate_rgb.astype(np.float32) / 255.0
    fg_arr = np.asarray(fg_layer, np.float32) / 255.0
    fg_rgb = fg_arr[..., :3]
    alpha = (fg_arr[..., 3:4]) * opacity
    blended = _blend(bg, fg_rgb, mode)
    out = bg * (1 - alpha) + blended * alpha
    return np.clip(out * 255, 0, 255).astype(np.uint8)


# --------------------------------------------------------------------------- #
# Grade
# --------------------------------------------------------------------------- #
def grade(img_u8: np.ndarray, exposure=1.0, contrast=1.0, saturation=1.0,
          tint=None, vignette=0.0, grain=0.0, seed=0) -> np.ndarray:
    x = img_u8.astype(np.float32) / 255.0
    x *= exposure
    x = (x - 0.5) * contrast + 0.5
    if saturation != 1.0:
        luma = (x * np.array([0.2126, 0.7152, 0.0722])).sum(-1, keepdims=True)
        x = luma + (x - luma) * saturation
    if tint is not None:
        x *= np.array(tint, np.float32)[None, None, :]
    if vignette:
        h, w = x.shape[:2]
        yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
        d = np.sqrt(((xx - w / 2) / (w / 2)) ** 2 + ((yy - h / 2) / (h / 2)) ** 2)
        x *= (1 - vignette * np.clip(d - 0.45, 0, 1) ** 1.6)[..., None]
    if grain:
        rng = np.random.default_rng(seed)
        x += rng.normal(0, grain, x.shape[:2] + (1,)).astype(np.float32)
    return np.clip(x * 255, 0, 255).astype(np.uint8)


# --------------------------------------------------------------------------- #
# Foreground resolution (still vs sequence)
# --------------------------------------------------------------------------- #
def resolve_fg(fg_arg: str):
    """Return ('still', [path]) or ('seq', [paths...])."""
    p = Path(fg_arg)
    if p.is_dir():
        frames = sorted(p.glob("*.png"))
        return ("seq", frames) if len(frames) > 1 else ("still", frames[:1])
    if "%0" in fg_arg or re.search(r"%\d*d", fg_arg):
        # printf pattern -> expand by scanning the directory
        d = Path(fg_arg).parent
        stem = Path(fg_arg).name
        rx = re.sub(r"%0?\d*d", r"(\\d+)", re.escape(stem).replace(r"\%", "%"))
        rx = stem
        rx = re.sub(r"%0?\d*d", r"\\d+", rx)
        frames = sorted(f for f in d.glob("*.png") if re.fullmatch(rx, f.name))
        return ("seq", frames) if len(frames) > 1 else ("still", frames[:1])
    if any(ch in fg_arg for ch in "*?["):
        frames = sorted(Path(x) for x in glob.glob(fg_arg))
        return ("seq", frames) if len(frames) > 1 else ("still", frames[:1])
    return ("still", [p])


# --------------------------------------------------------------------------- #
# Driver
# --------------------------------------------------------------------------- #
def run(args):
    plate = Image.open(args.plate).convert("RGB")
    plate_rgb = np.asarray(plate)
    plate_size = plate.size

    grade_kw = dict(exposure=args.exposure, contrast=args.contrast,
                    saturation=args.saturation, vignette=args.vignette,
                    grain=args.grain,
                    tint=[float(t) for t in args.tint.split(",")] if args.tint else None)

    kind, frames = resolve_fg(args.fg)
    if not frames:
        print(f"no foreground frames found for '{args.fg}'", file=sys.stderr)
        return 2
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)

    if kind == "still" or out.suffix.lower() != ".mp4":
        fg = Image.open(frames[0])
        layer = _place(fg, plate_size, args.fit, args.scale)
        comp = composite_frame(plate_rgb, layer, args.mode, args.opacity)
        comp = grade(comp, **grade_kw)
        Image.fromarray(comp, "RGB").save(out)
        print("still ->", out)
        return 0

    # sequence -> mp4
    tmp = out.parent / (out.stem + "_frames")
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True)
    for i, fp in enumerate(frames):
        layer = _place(Image.open(fp), plate_size, args.fit, args.scale)
        comp = composite_frame(plate_rgb, layer, args.mode, args.opacity)
        comp = grade(comp, seed=i, **grade_kw)
        Image.fromarray(comp, "RGB").save(tmp / f"c_{i:04d}.png")
    cmd = [
        FFMPEG, "-y", "-framerate", str(args.fps),
        "-i", str(tmp / "c_%04d.png"),
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",
        "-crf", "18", "-movflags", "+faststart", str(out),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        print("ffmpeg failed:\n" + res.stderr[-1500:], file=sys.stderr)
        return 1
    print(f"mp4 -> {out}  ({len(frames)} frames @ {args.fps}fps)")
    return 0


def main():
    ap = argparse.ArgumentParser(description="Composite foreground over a plate.")
    ap.add_argument("--plate", required=True)
    ap.add_argument("--fg", required=True, help="alpha PNG, dir, glob, or %%04d pattern")
    ap.add_argument("--out", required=True, help=".png or .mp4")
    ap.add_argument("--mode", default="screen",
                    choices=["normal", "screen", "add", "multiply",
                             "overlay", "soft_light", "lighten"])
    ap.add_argument("--fit", default="center", choices=["center", "fill", "contain"])
    ap.add_argument("--scale", type=float, default=0.78,
                    help="for fit=center: fg height as fraction of plate height")
    ap.add_argument("--opacity", type=float, default=1.0)
    ap.add_argument("--fps", type=int, default=24)
    # grade
    ap.add_argument("--exposure", type=float, default=1.0)
    ap.add_argument("--contrast", type=float, default=1.04)
    ap.add_argument("--saturation", type=float, default=1.06)
    ap.add_argument("--tint", default=None, help="r,g,b multipliers e.g. 1.03,1.0,0.97")
    ap.add_argument("--vignette", type=float, default=0.25)
    ap.add_argument("--grain", type=float, default=0.015)
    args = ap.parse_args()
    sys.exit(run(args))


if __name__ == "__main__":
    main()
