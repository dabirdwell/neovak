"""Animation lane: the show's motion engine (plates/motion.py and plates/typeset.py) behind a few
templates a person can fill in.

The engine takes a written timeline. A person gives words, a look and a shape, and each template
here builds that timeline. Nothing a person types reaches a command line or a file path: words go
inside the timeline as data, fonts and looks are picked from fixed lists, and a source picture or
clip must be inside a folder NeoVak may read. The source is only ever read.

The engine draws type character by character, so every letter on screen is exactly what was typed.
No model is involved, so the same words and settings give the same frames every time.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

from .base import Adapter, AdapterError
from .image_tools import ImageTool

REPO = Path(__file__).resolve().parent.parent.parent
MOTION = REPO / "plates" / "motion.py"
from .. import settings as _settings  # noqa: E402
FFMPEG = _settings.load().tool("ffmpeg")
FFPROBE = _settings.load().tool("ffprobe")
FPS = 24
SHAPES = {"landscape": (1920, 1080), "portrait": (1080, 1920), "square": (1080, 1080)}
PREVIEW_SCALE = 0.5
CLIP_SUFFIXES = {".mp4", ".mov", ".m4v"}
MAX_CLIP_SECONDS = 30
MAX_WORDS = 600
MS_PER_PIXEL_FRAME = 1.85e-4  # milliseconds per pixel per frame; measured: 5 s at 1920 by 1080 in 50 s

FONTS = {
    "clean": {"label": "Clean", "path": "/System/Library/Fonts/Avenir Next.ttc", "index": 5},
    "tall": {"label": "Tall", "path": "/System/Library/Fonts/Avenir Next Condensed.ttc", "index": 2},
    "classic": {"label": "Classic", "path": "/System/Library/Fonts/Supplemental/Baskerville.ttc", "index": 4},
}
LOOKS = {
    "night": {"label": "Night", "top": "#16283c", "bottom": "#050a12", "ink": "#f2ecdc", "soft": "#a9b6c4", "accent": "#e6b450", "dark": True},
    "paper": {"label": "Paper", "top": "#f6f1e6", "bottom": "#ddd3bf", "ink": "#1d1a16", "soft": "#6a6154", "accent": "#b3412b", "dark": False},
    "studio": {"label": "Studio", "top": "#2c2c33", "bottom": "#0d0d10", "ink": "#f4f4f6", "soft": "#a4a4ae", "accent": "#55c2d8", "dark": True},
    "ember": {"label": "Ember", "top": "#4a1a12", "bottom": "#120506", "ink": "#fbe9d4", "soft": "#d9a98a", "accent": "#ff8a3d", "dark": True},
}
TEMPLATES = {
    "title": {"label": "Title card", "words": "required"},
    "move": {"label": "Slow move over a picture", "words": "optional"},
    "strip": {"label": "Name strip", "words": "required"},
    "lines": {"label": "One line at a time", "words": "required"},
}
DIRECTIONS = ("in", "out", "left", "right")

_cmaps = {}


def _typeset():
    """plates/typeset.py, loaded when needed so the queue itself does not depend on Pillow."""
    plates = str(REPO / "plates")
    if plates not in sys.path:
        sys.path.insert(0, plates)
    import typeset
    return typeset


def _hex(color):
    color = color.lstrip("#")
    return tuple(int(color[i:i + 2], 16) for i in (0, 2, 4))


def clean_words(text):
    """Words as lines: control characters dropped, tabs to spaces, trailing space trimmed."""
    text = re.sub(r"[^\S\n]+", " ", (text or "").replace("\r\n", "\n").replace("\r", "\n"))
    text = "".join(c for c in text if c == "\n" or c.isprintable())
    return "\n".join(line.strip() for line in text.split("\n")).strip()


def check_letters(text, font_key):
    """Refuse a letter the typeface does not have; the engine would draw an empty box for it."""
    from fontTools.ttLib import TTCollection, TTFont
    spec = FONTS[font_key]
    if font_key not in _cmaps:
        path = spec["path"]
        font = TTCollection(path).fonts[spec["index"]] if path.endswith(".ttc") else TTFont(path)
        _cmaps[font_key] = set(font.getBestCmap())
    missing = sorted({c for c in text if not c.isspace() and ord(c) not in _cmaps[font_key]})
    if missing:
        raise AdapterError(f"This typeface has no letter for: {' '.join(missing[:8])}. Please take it out or choose another typeface.")


def wrap(text, font, width, tracking, line_width):
    """Greedy word wrap. A single word wider than the box stays on its own line, and the size search rejects it."""
    lines = []
    for para in text.split("\n"):
        line = ""
        for word in para.split(" "):
            trial = f"{line} {word}".strip()
            if line and line_width(font, trial, tracking) > width:
                lines.append(line)
                line = word
            else:
                line = trial
        lines.append(line)
    return lines


def fit_type(text, font_key, box_w, box_h, start, tracking=2, leading=1.18, smallest=None):
    """The largest whole point size at which the words fit the box. Returns (size, lines, block height)."""
    ts = _typeset()
    spec = FONTS[font_key]
    size = int(start)
    smallest = int(smallest or max(14, start * 0.28))
    while size >= smallest:
        font = ts.load_font(spec["path"], size, spec["index"])
        lines = wrap(text, font, box_w, tracking, ts.line_width)
        height = int(size * leading) * len(lines)
        if max(ts.line_width(font, ln, tracking) for ln in lines) <= box_w and height <= box_h:
            return size, lines, height
        size -= max(1, int(size * 0.06))
    raise AdapterError("Those words are too long for this shape. Please shorten them or try a wider shape.")


def type_layer(name, text_lines, size, font_key, fill, shadow, **extra):
    """One type layer. The engine splits lines on a backslash and n, written as those two characters."""
    spec = FONTS[font_key]
    layer = {"name": name, "type": "type", "text": "\\n".join(text_lines), "font": spec["path"], "index": spec["index"],
             "size": int(size), "fill": fill, "tracking": 2, "leading": 1.18, "pad": 24, "shadow": bool(shadow),
             "edge": bool(shadow), "shadow_off": max(2, int(size * 0.02)), "shadow_blur": max(2, int(size * 0.02)),
             "fit": "native", "anchor": [0.5, 0.5], "units": "px", "subpixel": True}
    layer.update(extra)
    return layer


def fade(t_in, t_out, length, end=1.0, ease="ease_out"):
    """Opacity keys: up from nothing at t_in, down to nothing at t_out."""
    keys = [{"t": t_in, "v": 0.0}, {"t": t_in + length, "v": end, "ease": ease}]
    if t_out - length > t_in + length:
        keys += [{"t": t_out - length, "v": end}, {"t": t_out, "v": 0.0, "ease": "ease_in_out"}]
    return keys


def rise(t_in, y, by, length=0.9):
    """Vertical keys: travels up by `by` pixels to rest on a whole pixel, so resting type stays sharp."""
    return [{"t": t_in, "v": float(y + by)}, {"t": t_in + length, "v": float(y), "ease": "ease_out"}]


class Canvas:
    """Sizes and the small pictures a template needs, written into the job's own working folder."""

    def __init__(self, shape, work, scale=1.0):
        w, h = SHAPES[shape]
        self.w, self.h = int(w * scale) // 2 * 2, int(h * scale) // 2 * 2
        self.work = Path(work)
        self.unit = min(self.w, self.h) / 1080
        self.count = 0

    def _name(self, stem):
        self.count += 1
        return str(self.work / f"{stem}_{self.count}.png")

    def plate(self, look):
        """A soft, dithered background rather than a flat fill: lighter at the top, darker at the edges."""
        import numpy as np
        from PIL import Image
        top, bottom = np.array(_hex(look["top"]), np.float32), np.array(_hex(look["bottom"]), np.float32)
        yy, xx = np.mgrid[0:self.h, 0:self.w].astype(np.float32)
        dist = np.sqrt(((xx - self.w * 0.5) / self.w * 1.5) ** 2 + ((yy - self.h * 0.3) / self.h * 1.5) ** 2)
        mix = np.clip(dist, 0, 1)[..., None]
        rgb = top * (1 - mix) + bottom * mix
        rng = np.random.default_rng(7)
        rgb = np.clip(rgb + rng.normal(0, 0.8, rgb.shape[:2] + (1,)), 0, 255).astype(np.uint8)
        path = self._name("plate")
        Image.fromarray(rgb, "RGB").save(path, compress_level=1)
        return path

    def scrim(self, strength=0.5, floor=0.25, low=False):
        """A dark veil so words stay readable over any picture. `low` darkens only the bottom third."""
        import numpy as np
        from PIL import Image
        yy = np.linspace(0, 1, self.h, dtype=np.float32)[..., None]
        if low:
            alpha = np.clip((yy - 0.55) / 0.45, 0, 1) ** 1.3 * strength
        else:
            alpha = floor + (strength - floor) * np.abs(yy - 0.5) * 2
        rgba = np.zeros((self.h, self.w, 4), np.uint8)
        rgba[..., 3] = (np.repeat(alpha, self.w, axis=1) * 255).astype(np.uint8)
        path = self._name("scrim")
        Image.fromarray(rgba, "RGBA").save(path, compress_level=1)
        return path

    def bar(self, width, height, color, radius=0, alpha=255):
        from PIL import Image, ImageDraw
        img = Image.new("RGBA", (int(width), int(height)), (0, 0, 0, 0))
        ImageDraw.Draw(img).rounded_rectangle((0, 0, int(width) - 1, int(height) - 1), radius=int(radius), fill=_hex(color) + (alpha,))
        path = self._name("bar")
        img.save(path, compress_level=1)
        return path


class MotionAnimation(ImageTool):
    name = "motion"
    lane = "animation"
    summary = "Make a short animated title, name strip, line by line text or slow move over a picture, from words."
    prefix = "neovak_anim"
    params = {
        "template": {"type": "str", "default": "title", "choices": list(TEMPLATES), "help": "Which kind of animation."},
        "text": {"type": "str", "default": "", "help": "The words. First line is the main line, second the smaller line; for one line at a time, one per line."},
        "source": {"type": "str", "default": None, "help": "Optional picture or clip for the background, inside a folder NeoVak may read. It is only read."},
        "look": {"type": "str", "default": "night", "choices": list(LOOKS)},
        "font": {"type": "str", "default": "clean", "choices": list(FONTS)},
        "shape": {"type": "str", "default": "landscape", "choices": list(SHAPES)},
        "seconds": {"type": "float", "default": 5, "help": "Length, 2 to 20 seconds. A background clip sets its own length."},
        "direction": {"type": "str", "default": "in", "choices": list(DIRECTIONS), "help": "For the slow move: in, out, left or right."},
        "still": {"type": "bool", "default": False, "help": "Make one small frame as a preview instead of the whole clip."},
    }

    # ------------------------------------------------------------------ checks and planning
    def memory_gb(self, params):
        return 0  # no model is loaded; every run measured under 0.5 GB at 1920 by 1080

    def clip_info(self, path):
        real = Path(path).resolve()
        r = subprocess.run([FFPROBE, "-v", "error", "-select_streams", "v:0", "-show_entries", "format=duration:stream=width,height",
                            "-of", "json", str(real)], capture_output=True, text=True, timeout=30)
        try:
            info = json.loads(r.stdout)
            return float(info["format"]["duration"]), info["streams"][0]
        except (ValueError, KeyError, IndexError):
            raise AdapterError("That clip could not be read.")

    def checked_any(self, path):
        """A picture, or a short clip, inside a folder NeoVak may read. Returns (real path, is clip)."""
        if isinstance(path, str) and Path(path).suffix.lower() in CLIP_SUFFIXES:
            real = Path(path).resolve() if path.startswith("/") else None
            if real is None or not any(real.is_relative_to(root) for root in self._roots()):
                raise AdapterError("That clip is not in a folder NeoVak may read.")
            if not real.is_file():
                raise AdapterError("That clip was not found.")
            seconds, _ = self.clip_info(real)
            if seconds > MAX_CLIP_SECONDS:
                raise AdapterError(f"That clip is too long. Please use one under {MAX_CLIP_SECONDS} seconds.")
            return str(real), True
        real, _, _ = self.checked_source(path)
        return real, False

    def validate(self, params):
        p = Adapter.validate(self, params)
        p["text"] = clean_words(p["text"])
        spec = TEMPLATES[p["template"]]
        if spec["words"] == "required" and not p["text"]:
            raise AdapterError("Please type the words for this animation.")
        if len(p["text"]) > MAX_WORDS:
            raise AdapterError(f"That is too many words for an animation. Please keep it under {MAX_WORDS} characters.")
        if not 2 <= p["seconds"] <= 20:
            raise AdapterError("An animation can be 2 to 20 seconds long.")
        if p["text"]:
            check_letters(p["text"], p["font"])
        p["clip"] = False
        if p["source"]:
            p["source"], p["clip"] = self.checked_any(p["source"])
            if p["clip"] and p["template"] == "move":
                raise AdapterError("The slow move works on a picture, not a clip.")
            if p["clip"]:
                p["seconds"] = round(self.clip_info(p["source"])[0], 3)  # the clip sets the length
        elif p["template"] == "move":
            raise AdapterError("Please choose a picture for the slow move.")
        self.layout_check(p)
        return p

    def layout_check(self, p):
        """Run the template's sizing now, so words that cannot fit are refused before anything starts."""
        work = tempfile.mkdtemp(prefix="neovak_anim_check_")
        try:
            canvas = Canvas(p["shape"], work)
            self.words_layers(p, canvas, float(p["seconds"]))
        finally:
            shutil.rmtree(work, ignore_errors=True)

    def plan(self, job):
        p = job["params"]
        if p["still"]:
            folder = Path(self.config["output_dir"]) / "_previews"
            return {"outputs": [str(folder / f"preview_j{job['id'][-6:]}.png")]}
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return {"outputs": [str(Path(self.config["output_dir"]) / f"{self.prefix}_{stamp}_j{job['id'][-6:]}.mp4")]}

    def seconds_for(self, p):
        return float(p.get("seconds") or 5)

    def default_estimate(self, params):
        if params.get("still"):
            return 3
        w, h = SHAPES[params.get("shape") or "landscape"]
        extra = 12 if params.get("clip") else 0
        # A straight line through measured runs (see STUDIO_PLAN.md, the animation stage).
        return round(4 + w * h * self.seconds_for(params) * FPS * MS_PER_PIXEL_FRAME / 1000 + extra)

    def estimate_key(self, params):
        return f"motion:{params.get('still')}:{params.get('shape')}:{round(self.seconds_for(params))}:{bool(params.get('clip'))}"

    def parse_progress(self, line):
        m = re.match(r"motion frame (\d+)/(\d+)", line)
        if m:
            return {"step": int(m.group(1)), "total": int(m.group(2)), "stage": "drawing frames"}
        if line.startswith("motion encoding"):
            return {"stage": "writing the clip"}
        return None

    # ------------------------------------------------------------------ templates
    def background_layers(self, p, canvas, T, work):
        """The bottom of the stack: the person's picture or clip under a veil, or a soft plate."""
        look = LOOKS[p["look"]]
        if p["source"] and p.get("_prepared_clip"):
            layers = [{"name": "clip", "type": "sequence", "src": p["_prepared_clip"], "frame_mode": "hold", "fit": "cover", "matte": "alpha"}]
        elif p["source"]:
            layers = [{"name": "picture", "type": "image", "src": p["_prepared"], "fit": "cover", "subpixel": True,
                       "keys": {"scale": [{"t": 0.0, "v": 1.0}, {"t": T, "v": 1.05}]}}]
        else:
            layers = [{"name": "plate", "type": "image", "src": canvas.plate(look), "fit": "cover", "subpixel": True,
                       "keys": {"scale": [{"t": 0.0, "v": 1.0}, {"t": T, "v": 1.05}]}}]
        return layers

    def on_picture(self, p):
        return bool(p["source"])

    def ink(self, p):
        """Words over a picture are always light; words on the plate use the look's own colours."""
        look = LOOKS[p["look"]]
        if self.on_picture(p):
            return "#ffffff", "#e4e4e8", look["accent"], True
        return look["ink"], look["soft"], look["accent"], look["dark"]

    def words_layers(self, p, canvas, T):
        return {"title": self.title_words, "move": self.move_words, "strip": self.strip_words, "lines": self.lines_words}[p["template"]](p, canvas, T)

    def title_words(self, p, canvas, T):
        lines = p["text"].split("\n")
        main = " ".join(lines[:1])
        sub = " ".join(lines[1:])
        ink, soft, accent, shadow = self.ink(p)
        u, W, H = canvas.unit, canvas.w, canvas.h
        size, wrapped, head_h = fit_type(main, p["font"], W * 0.8, H * 0.5, 148 * u, smallest=40 * u)
        layers = []
        # The engine draws each line from the top of its box, so descenders run past the block's
        # lower edge. The rule has to clear them.
        gap = int(max(46 * u, size * 0.55))
        sub_size, sub_wrapped, sub_h = 0, [], 0
        if sub:
            sub_size, sub_wrapped, sub_h = fit_type(sub, p["font"], W * 0.72, H * 0.2, min(52 * u, size * 0.5), smallest=22 * u)
        total = head_h + (gap + sub_h if sub else 0)
        top = H / 2 - total / 2
        head_y = int(top + head_h / 2)
        start, end = 0.25, T - 0.05
        layers.append(type_layer("title", wrapped, size, p["font"], ink, shadow,
                                 keys={"x": W // 2, "y": rise(start, head_y, int(30 * u)), "opacity": fade(start, end, 0.7)}))
        rule_y = int(top + head_h + gap * 0.62)
        rule = canvas.bar(max(60 * u, min(W * 0.14, size * 2.2)), max(2, int(4 * u)), accent, radius=2)
        layers.append({"name": "rule", "type": "alpha_image", "src": rule, "fit": "native", "anchor": [0.5, 0.5], "units": "px", "subpixel": True,
                       "keys": {"x": W // 2, "y": rule_y, "opacity": fade(start + 0.2, end, 0.5),
                                "scale": [{"t": start + 0.2, "v": 0.15}, {"t": start + 1.0, "v": 1.0, "ease": "ease_out"}]}})
        if sub:
            sub_y = int(top + head_h + gap + sub_h / 2)
            layers.append(type_layer("subtitle", sub_wrapped, sub_size, p["font"], soft, shadow,
                                     keys={"x": W // 2, "y": rise(start + 0.35, sub_y, int(18 * u)), "opacity": fade(start + 0.35, end, 0.7)}))
        return layers

    def strip_words(self, p, canvas, T):
        lines = p["text"].split("\n")
        name, role = lines[0], " ".join(lines[1:])
        look, u, W, H = LOOKS[p["look"]], canvas.unit, canvas.w, canvas.h
        name_size, _, name_h = fit_type(name.replace("\n", " "), p["font"], W * 0.62, H * 0.13, 64 * u, smallest=26 * u, leading=1.1)
        role_size, role_h = 0, 0
        if role:
            role_size, _, role_h = fit_type(role, p["font"], W * 0.62, H * 0.08, 34 * u, smallest=18 * u, leading=1.1)
        ts = _typeset()
        spec = FONTS[p["font"]]
        width = max(ts.line_width(ts.load_font(spec["path"], name_size, spec["index"]), name, 2),
                    ts.line_width(ts.load_font(spec["path"], role_size or name_size, spec["index"]), role, 2) if role else 0)
        pad_x, pad_y = int(34 * u), int(24 * u)
        panel_w, panel_h = int(width + pad_x * 2 + 8 * u), int(name_h + (role_h + 8 * u if role else 0) + pad_y * 2)
        left, bottom = int(W * 0.06), int(H - H * 0.1)
        panel_y = bottom - panel_h // 2
        off = -int(panel_w * 1.2)
        start, end = 0.2, T - 0.25
        def slide(rest, delay=0.0):
            keys = [{"t": start + delay, "v": float(rest + off)}, {"t": start + delay + 0.65, "v": float(rest), "ease": "ease_out"}]
            if T > 2.2:
                keys += [{"t": end - 0.45, "v": float(rest)}, {"t": end, "v": float(rest + off), "ease": "ease_in_out"}]
            return keys
        panel = canvas.bar(panel_w, panel_h, look["bottom"], radius=int(10 * u), alpha=232)
        layers = [{"name": "strip", "type": "alpha_image", "src": panel, "fit": "native", "anchor": [0, 0.5], "units": "px", "subpixel": True,
                   "keys": {"x": slide(left), "y": panel_y}}]
        edge = canvas.bar(max(3, int(6 * u)), panel_h, look["accent"], radius=2)
        layers.append({"name": "edge", "type": "alpha_image", "src": edge, "fit": "native", "anchor": [0, 0.5], "units": "px", "subpixel": True,
                       "keys": {"x": slide(left), "y": panel_y}})
        text_x = left + int(pad_x + 8 * u) - 24  # 24 is the type layer's own padding
        top = panel_y - panel_h // 2 + pad_y
        ink, soft = look["ink"], look["soft"]  # the panel is the look's own colour, so its own type reads on it
        layers.append(type_layer("name", [name], name_size, p["font"], ink, False, anchor=[0, 0.5],
                                 keys={"x": slide(text_x, 0.06), "y": int(top + name_h / 2)}))
        if role:
            layers.append(type_layer("role", [role], role_size, p["font"], soft, False, anchor=[0, 0.5],
                                     keys={"x": slide(text_x, 0.12), "y": int(top + name_h + 8 * u + role_h / 2)}))
        return layers

    def lines_words(self, p, canvas, T):
        lines = [ln for ln in p["text"].split("\n") if ln]
        if len(lines) > 8:
            raise AdapterError("Please use at most eight lines.")
        slot = T / len(lines)
        if slot < 1.2:
            raise AdapterError(f"That is too many lines for {T:.0f} seconds. Please make it longer or use fewer lines.")
        ink, _, accent, shadow = self.ink(p)
        u, W, H = canvas.unit, canvas.w, canvas.h
        size = min(fit_type(ln, p["font"], W * 0.8, H * 0.46, 104 * u, smallest=30 * u)[0] for ln in lines)
        layers = []
        for i, ln in enumerate(lines):
            _, wrapped, _ = fit_type(ln, p["font"], W * 0.8, H * 0.46, size, smallest=size)
            t0 = i * slot + 0.1
            t1 = (i + 1) * slot - 0.05 if i < len(lines) - 1 else T - 0.05
            layers.append(type_layer(f"line {i + 1}", wrapped, size, p["font"], ink, shadow,
                                     keys={"x": W // 2, "y": rise(t0, H // 2, int(26 * u), 0.55), "opacity": fade(t0, t1, min(0.45, slot / 3))}))
        return layers

    def move_words(self, p, canvas, T):
        if not p["text"]:
            return []
        lines = p["text"].split("\n")
        main, sub = lines[0], " ".join(lines[1:])
        u, W, H = canvas.unit, canvas.w, canvas.h
        size, wrapped, head_h = fit_type(main, p["font"], W * 0.8, H * 0.28, 76 * u, smallest=30 * u)
        gap = int(10 * u)
        sub_size, sub_wrapped, sub_h = 0, [], 0
        if sub:
            sub_size, sub_wrapped, sub_h = fit_type(sub, p["font"], W * 0.8, H * 0.12, 36 * u, smallest=20 * u)
        bottom = H - int(H * 0.09)
        head_y = int(bottom - (sub_h + gap if sub else 0) - head_h / 2)
        start, end = 0.7, T - 0.1
        layers = [type_layer("words", wrapped, size, p["font"], "#ffffff", True,
                             keys={"x": W // 2, "y": rise(start, head_y, int(20 * u)), "opacity": fade(start, end, 0.7)})]
        if sub:
            layers.append(type_layer("words small", sub_wrapped, sub_size, p["font"], "#e4e4e8", True,
                                     keys={"x": W // 2, "y": rise(start + 0.25, int(bottom - sub_h / 2), int(14 * u)), "opacity": fade(start + 0.25, end, 0.7)}))
        return layers

    def move_layers(self, p, canvas, T):
        """The slow move itself: the picture always covers the canvas, so no edge ever shows."""
        from PIL import Image
        with Image.open(p["_prepared"]) as im:
            fw, fh = im.size
        W, H = canvas.w, canvas.h
        base = max(W / fw, H / fh)
        ease = "smoothstep"
        direction = p["direction"]
        if direction in ("in", "out"):
            big = 1.16
            a, b = (1.0, big) if direction == "in" else (big, 1.0)
            keys = {"scale": [{"t": 0.0, "v": a}, {"t": T, "v": b, "ease": ease}], "x": 0.5, "y": 0.5}
        else:
            scale = 1.14
            excess = (fw * base * scale - W) / (2 * W)  # how far the centre can travel, as a share of the width
            sign = 1 if direction == "left" else -1
            keys = {"scale": scale, "y": 0.5, "x": [{"t": 0.0, "v": 0.5 + sign * excess * 0.92},
                                                     {"t": T, "v": 0.5 - sign * excess * 0.92, "ease": ease}]}
        layers = [{"name": "picture", "type": "image", "src": p["_prepared"], "fit": "cover", "subpixel": True, "keys": keys}]
        if p["text"]:
            layers.append({"name": "veil", "type": "alpha_image", "src": canvas.scrim(strength=0.72, low=True), "fit": "cover"})
        return layers

    def timeline(self, p, canvas, T):
        if p["template"] == "move":
            layers = self.move_layers(p, canvas, T)
        else:
            layers = self.background_layers(p, canvas, T, canvas.work)
            if self.on_picture(p):
                layers.append({"name": "veil", "type": "alpha_image", "fit": "cover",
                               "src": canvas.scrim(strength=0.72, low=True) if p["template"] == "strip" else canvas.scrim()})
        layers += self.words_layers(p, canvas, T)
        for layer in layers:  # nothing asks for a whole image redraw at a size it does not need
            layer.setdefault("keys", {})
        return {"name": "neovak_anim", "width": canvas.w, "height": canvas.h, "fps": FPS, "duration": round(T, 3),
                "background": LOOKS[p["look"]]["bottom"], "crf": 16, "frame_compress": 1,
                "grade": {"vignette": 0.18 if not p["source"] else 0.0, "grain": 0.006}, "layers": layers}

    # ------------------------------------------------------------------ preparing a source
    def prepare_picture(self, p, canvas, work):
        """A working copy of the picture at a sensible size, upright, with no transparency. The original is not touched."""
        from PIL import Image, ImageOps
        with Image.open(p["source"]) as im:
            img = ImageOps.exif_transpose(im).convert("RGBA")
        fit = max(canvas.w / img.width, canvas.h / img.height) * 1.3
        if fit < 1:
            img = img.resize((max(1, round(img.width * fit)), max(1, round(img.height * fit))), Image.LANCZOS)
        flat = Image.new("RGB", img.size, _hex(LOOKS[p["look"]]["bottom"]))
        flat.paste(img, mask=img.split()[3])
        out = str(Path(work) / "picture.png")
        flat.save(out, compress_level=1)
        p["_prepared"] = out

    def prepare_clip(self, p, canvas, work, ctx, still_t=None):
        """Frames from the clip, at this canvas size. Run by ffmpeg from an argument list."""
        target = Path(work) / "clip"
        target.mkdir()
        crop = f"scale={canvas.w}:{canvas.h}:force_original_aspect_ratio=increase,crop={canvas.w}:{canvas.h}"
        cmd = [FFMPEG, "-nostdin", "-loglevel", "error", "-y"]
        if still_t is not None:
            cmd += ["-ss", str(still_t)]
        cmd += ["-i", p["source"], "-vf", (f"fps={FPS}," + crop) if still_t is None else crop]
        cmd += ["-frames:v", "1", str(target / "f_0000.png")] if still_t is not None else ["-compression_level", "1", str(target / "f_%04d.png")]
        r = ctx.spawn(cmd, timeout=300)
        if r.returncode != 0 or not any(target.glob("*.png")):
            raise AdapterError("That clip could not be read.")
        p["_prepared_clip"] = str(target)

    # ------------------------------------------------------------------ the run
    def run(self, job, ctx):
        p = dict(job["params"])
        output = Path(job["outputs"][0])
        output.parent.mkdir(parents=True, exist_ok=True)
        scale = PREVIEW_SCALE if p["still"] else 1.0
        T = self.seconds_for(p)
        work = tempfile.mkdtemp(prefix="neovak_anim_")
        started = time.time()
        try:
            canvas = Canvas(p["shape"], work, scale)
            ctx.progress(stage="setting up", step=0, total=None)
            still_t = None
            if p["still"]:
                still_t = self.still_time(p, T)
            if p["clip"]:
                self.prepare_clip(p, canvas, work, ctx, still_t)
                if ctx.cancel_requested:
                    return None
            elif p["source"]:
                self.prepare_picture(p, canvas, work)
            tl = self.timeline(p, canvas, T)
            path = Path(work) / "timeline.json"
            path.write_text(json.dumps(tl))
            silent = str(output) if not p["clip"] or p["still"] else str(Path(work) / "silent.mp4")
            python = str(Path(self.config["venv_bin"]) / "python3") if self.config.get("venv_bin") else sys.executable
            cmd = [python, str(MOTION), str(path), "--out", silent, "--frames-dir", str(Path(work) / "frames"), "--progress"]
            if p["still"]:
                cmd += ["--still-at", str(still_t)]
            env = dict(os.environ, NEOVAK_TYPE_CACHE=str(Path(work) / "type"), PYTHONUNBUFFERED="1")
            r = ctx.spawn(cmd, env=env, cwd=str(REPO), measure=True, timeout=max(300, T * 90))
            if r.returncode == 0 and p["clip"] and not p["still"] and not ctx.cancel_requested:
                ctx.progress(stage="adding the sound")
                mux = ctx.spawn([FFMPEG, "-nostdin", "-loglevel", "error", "-y", "-i", silent, "-i", p["source"], "-map", "0:v", "-map", "1:a?",
                                 "-c:v", "copy", "-c:a", "aac", str(output)], timeout=300)
                if mux.returncode != 0:
                    r.returncode, r.stderr = mux.returncode, mux.stderr
            job = dict(job, params=dict(job["params"], source=job["params"].get("source") or ""))
            out = self.finish(job, ctx, r, "The animation engine", template=p["template"], time_seconds=round(time.time() - started, 1))
            if out is None:
                return None
            if p["still"]:
                self.prune_previews(output.parent)
                out.update(size=f"{canvas.w}x{canvas.h}", still=True)
                return out
            from .ltx_video import LtxVideo
            got = LtxVideo.probe(str(output))
            want = max(1, int(round(FPS * round(T, 3))))
            if got["video"] is None or (got["width"], got["height"]) != (canvas.w, canvas.h) or abs(got["frames"] - want) > 3:
                output.unlink(missing_ok=True)
                raise AdapterError(f"The animation came out different from what was asked for ({got['width']} by {got['height']}, {got['frames']} frames), so it was not kept.")
            out.update(size=f"{canvas.w}x{canvas.h}", frames=got["frames"], seconds=round(got["frames"] / FPS, 2), has_audio=got["audio"])
            return out
        finally:
            shutil.rmtree(work, ignore_errors=True)

    @staticmethod
    def still_time(p, T):
        """A moment when everything has arrived and nothing has left yet."""
        if p["template"] == "lines":
            return round(min(T * 0.5, T / max(1, len([ln for ln in p["text"].split("\n") if ln])) * 0.6), 3)
        return round(min(1.8, T * 0.55), 3)

    @staticmethod
    def prune_previews(folder, keep=12):
        """Keeps only the newest previews. It only ever looks at the preview files this lane writes."""
        old = sorted(folder.glob("preview_j*.png"), key=lambda f: f.stat().st_mtime, reverse=True)[keep:]
        for f in old:
            f.unlink(missing_ok=True)


