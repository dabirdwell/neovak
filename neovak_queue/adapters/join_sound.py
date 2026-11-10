"""Put a voice over a clip. No model is loaded: ffmpeg, from an argument list, on two files already
in a folder NeoVak may read. Both are only read, and the result is always a new file.

When the words run longer than the clip, the last frame holds until they finish. When they are
shorter, the clip plays out and the sound ends in silence. The clip's own sound is dropped unless
keep_sound asks for it underneath the voice.
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
VIDEO_SUFFIXES = {".mp4", ".mov"}
AUDIO_SUFFIXES = {".wav", ".mp3", ".m4a"}
TAIL_SECONDS = 0.6  # a breath after the last word, so a held picture does not cut off on it


def media_info(path):
    r = subprocess.run([FFPROBE, "-v", "error", "-show_entries", "stream=codec_type:format=duration", "-of", "json", str(path)],
                       capture_output=True, text=True, timeout=60)
    data = json.loads(r.stdout or "{}")
    kinds = [s.get("codec_type") for s in data.get("streams") or []]
    return {"seconds": float((data.get("format") or {}).get("duration") or 0), "video": "video" in kinds, "audio": "audio" in kinds}


class JoinSound(Adapter):
    name = "join-sound"
    lane = "edit"
    summary = "Lay a voice recording over a clip, holding the last frame if the words run longer."
    prefix = "neovak_video"
    params = {
        "video": {"type": "str", "help": "The clip. It is only read."},
        "audio": {"type": "str", "help": "The voice recording. It is only read."},
        "keep_sound": {"type": "float", "default": 0.0, "help": "How loud the clip's own sound stays under the voice, 0 to 1."},
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
        p["video"] = self._checked(p["video"], VIDEO_SUFFIXES, "clip")
        p["audio"] = self._checked(p["audio"], AUDIO_SUFFIXES, "voice recording")
        if not 0 <= p["keep_sound"] <= 1:
            raise AdapterError("'keep_sound' must be between 0 and 1")
        return p

    def plan(self, job):
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return {"outputs": [str(Path(self.config["output_dir"]) / f"{self.prefix}_{stamp}_j{job['id'][-6:]}.mp4")]}

    def default_estimate(self, params):
        return 12

    @staticmethod
    def command(video, audio, part, clip, voice, keep_sound):
        total = max(clip["seconds"], voice["seconds"] + TAIL_SECONDS)
        hold = max(0.0, total - clip["seconds"])
        graph, video_map = [], "0:v:0"
        if hold > 0.02:
            graph.append(f"[0:v:0]tpad=stop_mode=clone:stop_duration={hold:.3f}[v]")
            video_map = "[v]"
        if keep_sound > 0 and clip["audio"]:
            graph.append(f"[0:a:0]volume={keep_sound:.3f},apad[under];[1:a:0]apad[voice];"
                         f"[under][voice]amix=inputs=2:duration=longest:normalize=0,atrim=0:{total:.3f}[a]")
        else:
            graph.append(f"[1:a:0]apad,atrim=0:{total:.3f}[a]")
        cmd = [FFMPEG, "-nostdin", "-y", "-i", video, "-i", audio, "-filter_complex", ";".join(graph),
               "-map", video_map, "-map", "[a]", "-t", f"{total:.3f}"]
        cmd += ["-c:v", "libx264", "-crf", "17", "-preset", "medium", "-pix_fmt", "yuv420p"] if hold > 0.02 else ["-c:v", "copy"]
        cmd += ["-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", part]
        return cmd, total, hold

    def run(self, job, ctx):
        p, final = job["params"], Path(job["outputs"][0])
        clip, voice = media_info(p["video"]), media_info(p["audio"])
        if not clip["video"] or not clip["seconds"]:
            raise AdapterError("That clip has no picture NeoVak can read.")
        if not voice["audio"] or not voice["seconds"]:
            raise AdapterError("That voice recording has no sound NeoVak can read.")
        part = final.with_name(f".part_{final.name}")  # the gallery skips a leading dot
        cmd, total, hold = self.command(p["video"], p["audio"], str(part), clip, voice, p["keep_sound"])
        ctx.progress(stage="joining picture and voice")
        r = ctx.spawn(cmd, timeout=900)
        try:
            if ctx.cancel_requested:
                return None
            if r.returncode != 0 or not part.exists():
                raise AdapterError("The picture and voice could not be joined. " + (r.stderr or "")[-300:])
            made = media_info(part)
            if not made["video"] or not made["audio"] or abs(made["seconds"] - total) > 0.25:
                raise AdapterError(f"The joined clip came out {made['seconds']:.1f} seconds long instead of {total:.1f}, so it was not kept.")
            os.replace(part, final)
        finally:
            part.unlink(missing_ok=True)
        return {"files": [str(final)], "path": str(final), "seconds": round(made["seconds"], 2),
                "clip_seconds": round(clip["seconds"], 2), "voice_seconds": round(voice["seconds"], 2),
                "held_last_frame_seconds": round(hold, 2)}
