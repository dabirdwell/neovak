#!/usr/bin/env python3
"""typeset.py: deterministic type layer for the plates pipeline.

Renders text to an alpha PNG (letterpress-ready) for plates/composite.py.
Every character guaranteed, every render, forever. Script, not mind:
the model paints the plate; this sets the type.

Examples:
  venv/bin/python plates/typeset.py --text "THIS MACHINE" --size 180 --out plates/out/type_title.png
  venv/bin/python plates/typeset.py --probe --font "/System/Library/Fonts/Avenir Next Condensed.ttc"
"""
import argparse, sys
from PIL import Image, ImageDraw, ImageFont, ImageFilter

DFONT = "/System/Library/Fonts/Avenir Next Condensed.ttc"

def load_font(path, size, index):
    try:
        return ImageFont.truetype(path, size, index=index)
    except Exception:
        return ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", size, index=1)

def probe(path):
    for i in range(18):
        try:
            f = ImageFont.truetype(path, 24, index=i)
            print(i, f.getname())
        except Exception:
            break

def line_width(font, text, tracking):
    return int(sum(font.getlength(c) for c in text) + tracking * max(0, len(text) - 1))

def draw_line(layer, xy, text, font, tracking, fill):
    d = ImageDraw.Draw(layer)
    x, y = xy
    for c in text:
        d.text((x, y), c, font=font, fill=fill)
        x += font.getlength(c) + tracking

def render(args):
    font = load_font(args.font, args.size, args.index)
    lines = args.text.split("\\n")
    widths = [line_width(font, ln, args.tracking) for ln in lines]
    lh = int(args.size * args.leading)
    W = max(widths) + 2 * args.pad
    H = lh * len(lines) + 2 * args.pad
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    # letterpress shadow: dark, offset, blurred
    if args.shadow:
        sh = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        for i, ln in enumerate(lines):
            x = (W - widths[i]) // 2
            draw_line(sh, (x + args.shadow_off, args.pad + i * lh + args.shadow_off),
                      ln, font, args.tracking, (0, 0, 0, args.shadow_alpha))
        img = Image.alpha_composite(img, sh.filter(ImageFilter.GaussianBlur(args.shadow_blur)))

    # main fill
    body = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    fill = tuple(int(args.fill.lstrip("#")[j:j+2], 16) for j in (0, 2, 4)) + (255,)
    for i, ln in enumerate(lines):
        x = (W - widths[i]) // 2
        draw_line(body, (x, args.pad + i * lh), ln, font, args.tracking, fill)
    img = Image.alpha_composite(img, body)
    # top-edge highlight for the pressed look
    if args.edge:
        hi = body.copy().filter(ImageFilter.GaussianBlur(0.6))
        r, g, b, a = hi.split()
        a = a.point(lambda v: int(v * 0.35))
        hi = Image.merge("RGBA", (r.point(lambda v: 255), g.point(lambda v: 255),
                                  b.point(lambda v: 255), a))
        img.paste(hi, (0, -max(1, args.size // 60)), hi)
    img.save(args.out)
    print(f"typeset OK: {args.out} {W}x{H} font={font.getname()} chars_exact=True")

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--text"); p.add_argument("--out")
    p.add_argument("--font", default=DFONT); p.add_argument("--index", type=int, default=6)
    p.add_argument("--size", type=int, default=160)
    p.add_argument("--fill", default="#ece6d6")
    p.add_argument("--tracking", type=int, default=2)
    p.add_argument("--leading", type=float, default=1.25)
    p.add_argument("--pad", type=int, default=48)
    p.add_argument("--shadow", action="store_true", default=True)
    p.add_argument("--shadow-off", type=int, default=4)
    p.add_argument("--shadow-blur", type=int, default=3)
    p.add_argument("--shadow-alpha", type=int, default=170)
    p.add_argument("--edge", action="store_true", default=True)
    p.add_argument("--probe", action="store_true")
    a = p.parse_args()
    if a.probe: probe(a.font); sys.exit(0)
    if not (a.text and a.out): p.error("--text and --out required")
    render(a)
