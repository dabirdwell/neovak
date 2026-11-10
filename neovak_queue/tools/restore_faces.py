#!/usr/bin/env python3
"""Restore faces in a picture with GFPGAN, using Apple Vision to find them.

  restore_faces.py <source> <output.png> <GFPGANv1.4.pth> <vision_tool> <strength 0..1>

Runs under the ComfyUI venv, the one Python on this machine with torch and spandrel; the engine's
own venv is not changed. The source is only read, and the output is always a new file.
Exit 3 means no usable face was found, and no output is written.
"""
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageOps

SIDE = 512
# Where the eyes, nose and mouth corners sit in the aligned 512 by 512 crop GFPGAN was trained on.
TEMPLATE = np.array([[192.98138, 239.94708], [318.90277, 240.19360], [256.63416, 314.01935],
                     [201.26117, 371.41043], [313.08905, 371.15118]])
MIN_EYE_GAP = 14


def similarity(src, dst):
    """The rotation, scale and shift that best maps src onto dst, as a 3 by 3 matrix."""
    rows, targets = [], []
    for (x, y), (u, v) in zip(src, dst):
        rows += [[x, -y, 1, 0], [y, x, 0, 1]]
        targets += [u, v]
    (a, b, tx, ty), *_ = np.linalg.lstsq(np.array(rows, float), np.array(targets, float), rcond=None)
    return np.array([[a, -b, tx], [b, a, ty], [0, 0, 1]])


def warp(image, matrix, size, resample=Image.BICUBIC):
    """PIL's transform takes the map from the new picture back to the old one."""
    inverse = np.linalg.inv(matrix)
    return image.transform(size, Image.AFFINE, tuple(inverse[:2].ravel()), resample)


def soft_mask():
    """White inside, fading to nothing at the edges of the aligned crop."""
    mask = Image.new("L", (SIDE, SIDE), 0)
    ImageDraw.Draw(mask).rounded_rectangle((44, 44, SIDE - 44, SIDE - 44), radius=96, fill=255)
    return mask.filter(ImageFilter.GaussianBlur(24))


def main():
    source, output, weights, tool = sys.argv[1:5]
    strength = float(sys.argv[5])
    found = subprocess.run([tool, "faces", source], capture_output=True, text=True)
    if found.returncode == 3:
        print("no faces", file=sys.stderr)
        return 3
    if found.returncode:
        print(found.stderr, file=sys.stderr)
        return 1
    points = [np.array(f, float) for f in json.loads(found.stdout)]
    usable = [p for p in points if np.linalg.norm(p[1] - p[0]) >= MIN_EYE_GAP]
    if not usable:
        print("faces too small", file=sys.stderr)
        return 3

    original = ImageOps.exif_transpose(Image.open(source))
    alpha = original.getchannel("A") if original.mode in ("RGBA", "LA") else None
    canvas = original.convert("RGB")

    import torch
    from spandrel import ModelLoader
    device = torch.device("mps" if torch.backends.mps.is_available() else "cpu")
    net = ModelLoader(device).load_from_file(weights).model.eval()
    torch.manual_seed(0)
    mask = soft_mask()
    for marks in usable:
        matrix = similarity(marks, TEMPLATE)
        crop = warp(canvas, matrix, (SIDE, SIDE))
        x = torch.from_numpy(np.asarray(crop, np.float32) / 127.5 - 1).permute(2, 0, 1)[None].to(device)
        with torch.no_grad():
            y = net(x, return_rgb=False, randomize_noise=False)[0]
        y = ((y[0].clamp(-1, 1) + 1) * 127.5).permute(1, 2, 0).cpu().numpy().round().astype(np.uint8)
        restored = Image.fromarray(y)
        back = warp(restored, np.linalg.inv(matrix), canvas.size)
        area = warp(mask, np.linalg.inv(matrix), canvas.size, Image.BILINEAR)
        if strength < 1:
            area = area.point(lambda v: int(v * strength))
        canvas.paste(back, (0, 0), area)
    if alpha is not None:
        canvas.putalpha(alpha)
    target = Path(output)
    if target.exists():
        print("output already exists", file=sys.stderr)
        return 1
    canvas.save(target)
    print(json.dumps({"faces": len(points), "restored": len(usable), "skipped": len(points) - len(usable)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
