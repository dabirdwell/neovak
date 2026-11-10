"""Timeline: a sequence of pictures and clips with sounds laid over it, joined into one film.

No model is loaded. Everything is ffmpeg from an argument list, on files already in a folder NeoVak may
read. Sources are only read, and the result is always a new file. A person's file names never reach a
filter string: every file is an input by position, and a filter only ever names positions and numbers.
"""
import json
import os
import subprocess
from datetime import datetime
from pathlib import Path

from .base import Adapter, AdapterError

from .. import settings as _settings  # noqa: E402
FFMPEG = _settings.load().tool("ffmpeg")
FFPROBE = _settings.load().tool("ffprobe")
PICTURES = {".png", ".jpg", ".jpeg", ".webp"}
CLIPS = {".mp4", ".mov"}
SOUNDS = {".wav", ".mp3", ".m4a"}
SHAPES = {"landscape": (1920, 1080), "portrait": (1080, 1920), "square": (1080, 1080)}
MAX_CLIPS, MAX_SOUNDS, MAX_SECONDS = 60, 24, 900


def probe(path):
    r = subprocess.run([FFPROBE, "-v", "error", "-show_entries", "stream=codec_type:format=duration", "-of", "json", str(path)],
                       capture_output=True, text=True, timeout=60)
    data = json.loads(r.stdout or "{}")
    kinds = [s.get("codec_type") for s in data.get("streams") or []]
    return {"seconds": float((data.get("format") or {}).get("duration") or 0), "video": "video" in kinds, "audio": "audio" in kinds}


def _number(value, low, high, what):
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise AdapterError(f"{what} has to be a number.")
    if not low <= number <= high:
        raise AdapterError(f"{what} has to be between {low} and {high}.")
    return number


class Timeline(Adapter):
    name = "timeline"
    lane = "edit"
    summary = "Join pictures, clips and sounds from a timeline into one film."
    prefix = "neovak_video"
    params = {
        "clips": {"type": "list", "help": "In order: {file, seconds, trim}. A picture holds for its seconds; a clip starts at trim."},
        "sounds": {"type": "list", "default": [], "help": "{file, start, trim, seconds, gain}, laid over the picture."},
        "prompt": {"type": "str", "default": "", "help": "A name for the film, for the file's record."},
        "shape": {"type": "str", "default": "landscape", "choices": sorted(SHAPES)},
        "keep_clip_sound": {"type": "bool", "default": True, "help": "Keep the sound that came with each clip."},
    }

    def _roots(self):
        extra = [d for d in os.environ.get("NEOVAK_SOURCE_DIRS", "").split(":") if d]
        return [Path(d).resolve() for d in [self.config["output_dir"], *self.config.get("source_dirs", []), *extra]]

    def _checked(self, path, suffixes, what):
        if not isinstance(path, str) or not path or "\x00" in path or not path.startswith("/"):
            raise AdapterError(f"Please give the full path of a {what} in the output folder.")
        real = Path(path).resolve()
        if not any(real.is_relative_to(root) for root in self._roots()):
            raise AdapterError(f"That {what} is not in a folder NeoVak may read.")
        if real.suffix.lower() not in suffixes or not real.is_file():
            raise AdapterError(f"That is not a {what} NeoVak can open.")
        return str(real)

    def validate(self, params):
        p = super().validate(params)
        if not isinstance(p["clips"], list) or not 1 <= len(p["clips"]) <= MAX_CLIPS:
            raise AdapterError(f"A timeline needs between 1 and {MAX_CLIPS} pictures or clips.")
        if not isinstance(p["sounds"], list) or len(p["sounds"]) > MAX_SOUNDS:
            raise AdapterError(f"A timeline can hold up to {MAX_SOUNDS} sounds.")
        clips, total = [], 0.0
        for c in p["clips"]:
            if not isinstance(c, dict):
                raise AdapterError("Each item on the timeline must name a file.")
            f = self._checked(c.get("file"), PICTURES | CLIPS, "picture or clip")
            sec = _number(c.get("seconds"), 0.2, 300, "Length")
            clips.append({"file": f, "seconds": sec, "trim": _number(c.get("trim") or 0, 0, 3600, "Trim")})
            total += sec
        if total > MAX_SECONDS:
            raise AdapterError(f"A timeline can be up to {MAX_SECONDS // 60} minutes long.")
        sounds = []
        for s in p["sounds"]:
            if not isinstance(s, dict):
                raise AdapterError("Each sound on the timeline must name a file.")
            sounds.append({"file": self._checked(s.get("file"), SOUNDS, "sound"), "start": _number(s.get("start") or 0, 0, MAX_SECONDS, "Start"),
                           "trim": _number(s.get("trim") or 0, 0, 3600, "Trim"), "seconds": _number(s.get("seconds"), 0.1, MAX_SECONDS, "Length"),
                           "gain": _number(1 if s.get("gain") is None else s.get("gain"), 0, 2, "Volume")})
        p["clips"], p["sounds"] = clips, sounds
        return p

    def plan(self, job):
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return {"outputs": [str(Path(self.config["output_dir"]) / f"{self.prefix}_{stamp}_j{job['id'][-6:]}.mp4")]}

    def default_estimate(self, params):
        return 5 + sum(c["seconds"] for c in params["clips"]) * 0.6

    def estimate_key(self, params):
        return f"timeline:{int(sum(c['seconds'] for c in params['clips']) // 30)}"

    def parse_progress(self, line):
        if line.startswith("out_time_us="):
            try:
                done = int(line.split("=", 1)[1]) / 1e6
            except ValueError:
                return None
            total = max(1, round(getattr(self, "_total", 0) or 1))
            return {"step": min(total, max(0, round(done))), "total": total, "stage": "joining"}
        return None

    @staticmethod
    def command(clips, sounds, infos, shape, keep_clip_sound, part):
        w, h = SHAPES[shape]
        args, filters, labels, audio, start = [], [], [], [], 0.0
        for i, c in enumerate(clips):
            if Path(c["file"]).suffix.lower() in PICTURES:
                args += ["-loop", "1", "-framerate", "24", "-t", f"{c['seconds']:.3f}", "-i", c["file"]]
            else:
                args += ["-ss", f"{c['trim']:.3f}", "-t", f"{c['seconds']:.3f}", "-i", c["file"]]
            filters.append(f"[{i}:v:0]scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:black,"
                           f"setsar=1,fps=24,format=yuv420p,tpad=stop_mode=clone:stop_duration=0.5,trim=0:{c['seconds']:.3f},setpts=PTS-STARTPTS[v{i}]")
            labels.append(f"[v{i}]")
            if keep_clip_sound and infos[i].get("audio"):
                filters.append(f"[{i}:a:0]atrim=0:{c['seconds']:.3f},asetpts=PTS-STARTPTS,adelay={int(start * 1000)}:all=1[c{i}]")
                audio.append(f"[c{i}]")
            start += c["seconds"]
        total = start
        filters.append("".join(labels) + f"concat=n={len(clips)}:v=1:a=0[v]")
        for j, s in enumerate(sounds):
            at = len(clips) + j
            args += ["-ss", f"{s['trim']:.3f}", "-t", f"{s['seconds']:.3f}", "-i", s["file"]]
            filters.append(f"[{at}:a:0]volume={s['gain']:.3f},adelay={int(s['start'] * 1000)}:all=1[s{j}]")
            audio.append(f"[s{j}]")
        if audio:
            filters.append("".join(audio) + f"amix=inputs={len(audio)}:duration=longest:normalize=0,apad,atrim=0:{total:.3f}[a]")
        cmd = [FFMPEG, "-nostdin", "-y", "-nostats", "-progress", "pipe:1", *args, "-filter_complex", ";".join(filters), "-map", "[v]"]
        if audio:
            cmd += ["-map", "[a]", "-c:a", "aac", "-b:a", "192k"]
        cmd += ["-t", f"{total:.3f}", "-c:v", "libx264", "-crf", "18", "-preset", "medium", "-pix_fmt", "yuv420p", "-movflags", "+faststart", part]
        return cmd, total

    def run(self, job, ctx):
        p, final = job["params"], Path(job["outputs"][0])
        infos = []
        for c in p["clips"]:
            info = {"audio": False, "seconds": c["seconds"]}
            if Path(c["file"]).suffix.lower() not in PICTURES:
                info = probe(c["file"])
                if not info["video"]:
                    raise AdapterError("One of the clips has no picture NeoVak can read.")
            infos.append(info)
        part = final.with_name(f".part_{final.name}")
        cmd, total = self.command(p["clips"], p["sounds"], infos, p["shape"], p["keep_clip_sound"], str(part))
        self._total = total
        ctx.progress(stage="joining", step=0, total=max(1, round(total)))
        r = ctx.spawn(cmd, timeout=3600)
        try:
            if ctx.cancel_requested:
                return None
            if r.returncode != 0 or not part.exists():
                raise AdapterError("The film could not be joined. " + (r.stderr or "")[-300:])
            made = probe(part)
            if not made["video"] or abs(made["seconds"] - total) > 0.4:
                raise AdapterError(f"The film came out {made['seconds']:.1f} seconds long instead of {total:.1f}, so it was not kept.")
            os.replace(part, final)
        finally:
            part.unlink(missing_ok=True)
        return {"files": [str(final)], "path": str(final), "seconds": round(made["seconds"], 2), "shape": p["shape"],
                "size": "x".join(map(str, SHAPES[p["shape"]])), "has_sound": made["audio"], "pieces": len(p["clips"]) + len(p["sounds"])}
