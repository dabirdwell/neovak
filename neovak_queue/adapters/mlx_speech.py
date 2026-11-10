"""Speech lane: mlx-audio 0.5.1 text to speech.

Every run has a time limit and runs with HF_HUB_OFFLINE=1. The live voice tool hung twice on a
dead connection to Hugging Face (S1_PARITY_2026-10-28.md section 8) and blocked the whole
service while it did. Offline removes that cause. The time limit covers any other hang: the
engine's process group is stopped, the job fails with a plain sentence, and nothing else is
affected.

Differences from the old tool: speed is passed when it is not 1.0 (the old tool dropped it);
long text is joined into one file; the words travel as one --text=... argument, so text that
starts with a dash cannot be read as an option; a description can be given to the voice that
is built from one. speaker is still accepted and unused, as before.
"""
import glob
import os
import re
import shutil
import subprocess
import time
import unicodedata
from datetime import datetime
from pathlib import Path

from .base import Adapter, AdapterError

# gb and the time limit come from real runs; STUDIO_PLAN.md lists them.
VOICES = {
    "kokoro": {"repo": "mlx-community/Kokoro-82M-bf16", "gb": 4, "timeout": 180, "per_char": 0.3, "own_speed": True},
    # csm-1b needs a setting the library's command line does not offer; tools/csm_say.py explains it.
    "csm-1b": {"repo": "mlx-community/csm-1b", "gb": 16, "timeout": 600, "per_char": 3.0, "runner": "csm_say.py"},
    "chatterbox": {"repo": "mlx-community/chatterbox-fp16", "gb": 13, "timeout": 600, "per_char": 3.0},
    "qwen3-tts": {"repo": "Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign", "gb": 23, "timeout": 600, "per_char": 3.0,
                  "needs_description": True},
}
# Voices a person added from the Models page. Their weights live in one folder and these are only
# usable when that folder is there; each was run here before it was listed (STUDIO_PLAN.md).
from .. import settings as _settings  # noqa: E402
INSTALL_ROOT = _settings.load().added_dir
VOICES.update({
    "soprano": {"repo": str(INSTALL_ROOT / "soprano-80m"), "gb": 2, "timeout": 180, "per_char": 0.5, "local": True},
})
MODELS = {k: v["repo"] for k, v in VOICES.items()}
MEMORY_GB = {k: v["gb"] for k, v in VOICES.items()}
NOT_HERE = {
    "fish-s2-pro": "Fish S2 Pro is not on this machine. Only 1.9 MB of its download ever arrived.",
}
DEFAULT_DESCRIPTION = "A calm, clear adult narrator with a warm, even tone."
TOOLS = Path(__file__).resolve().parent.parent / "tools"
FFMPEG = _settings.load().tool("ffmpeg")


def speakable(text):
    """The words without emoji and other symbols. Voices read those as noise, and it garbles the words beside them."""
    kept = "".join(c for c in text if unicodedata.category(c) not in ("So", "Sk", "Cf", "Cs", "Co", "Cn") and c != "\ufe0f")
    return re.sub(r"[ \t]{2,}", " ", kept).strip()


class MlxSpeech(Adapter):
    name = "mlx-audio"
    lane = "speech"
    summary = "Text to speech with mlx-audio (Kokoro, Chatterbox, CSM-1B, Qwen3-TTS)."
    params = {
        "text": {"type": "str", "help": "Text to speak. Under about 200 words is best."},
        "voice": {"type": "str", "default": "kokoro", "choices": sorted(MODELS),
                  "help": "Speech model."},
        "speed": {"type": "float", "default": 1.0, "help": "0.5 to 2.0."},
        "speaker": {"type": "int", "default": 0, "help": "Accepted for compatibility; unused."},
        "description": {"type": "str", "default": "",
                        "help": "For qwen3-tts: the voice, in plain words."},
    }

    def models(self):
        return [{"voice": k, "repo": v["repo"], "memory_gb": v["gb"]} for k, v in VOICES.items()]

    def memory_gb(self, params):
        return MEMORY_GB.get(params.get("voice", "kokoro"), 6)

    def validate(self, params):
        if params.get("voice") in NOT_HERE:
            raise AdapterError(NOT_HERE[params["voice"]])
        spec = VOICES.get(params.get("voice", "kokoro")) or {}
        if spec.get("local") and not Path(spec["repo"]).is_dir():
            raise AdapterError("That voice is not on this machine yet. It can be added from the Models page.")
        clean = super().validate(params)
        if not any(c.isalnum() for c in speakable(clean["text"])):  # three dots read aloud are a burst of noise
            raise AdapterError("There are no words to read aloud here.")
        if not 0.5 <= clean["speed"] <= 2.0:
            raise AdapterError("'speed' must be between 0.5 and 2.0")
        return clean

    def estimate_key(self, params):
        return f"mlx-audio:{params['voice']}:{len(params['text']) // 100}"

    def plan(self, job):
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out = Path(self.config["output_dir"]) / f"neovak_speech_{stamp}_{job['id'][-6:]}.wav"
        return {"outputs": [str(out)]}

    def time_limit(self, params):
        """Seconds a run may take before it is treated as hung. A test can override it."""
        override = self.config.get("speech_timeout_seconds")
        if override:
            return float(override)
        spec = VOICES[params["voice"]]
        return spec["timeout"] + len(params["text"]) * spec["per_char"]

    def run(self, job, ctx):
        p = job["params"]
        spec = VOICES[p["voice"]]
        final_path = job["outputs"][0]
        fp = Path(final_path)
        output_dir = str(fp.parent / fp.stem.replace("neovak_speech_", "speech_", 1))
        python, words = str(Path(self.config["venv_bin"]) / "python3"), speakable(p["text"])
        if spec.get("runner"):
            cmd = [python, str(TOOLS / spec["runner"]), "--model", spec["repo"], f"--text={words}", "--output_path", output_dir]
        else:
            cmd = [python, "-m", "mlx_audio.tts.generate", "--model", spec["repo"], f"--text={words}", "--output_path", output_dir,
                   "--join_audio"]
        if p["speed"] != 1.0 and spec.get("own_speed"):  # the only engine here that honours --speed; measured Nov 9 2026
            cmd += ["--speed", str(p["speed"])]
        if spec.get("needs_description"):
            cmd.append(f"--instruct={p.get('description') or DEFAULT_DESCRIPTION}")
        env = os.environ.copy()
        env["HF_HUB_OFFLINE"] = "1"
        env.setdefault("HF_HOME", str(Path(self.config["model_dir"]) / "huggingface"))
        limit = self.time_limit(p)
        ctx.progress(stage="generating")
        start = time.time()
        r = ctx.spawn(cmd, env=env, timeout=limit, measure=True)
        elapsed = round(time.time() - start, 1)
        wavs = sorted(glob.glob(f"{output_dir}/*.wav"), key=os.path.getsize, reverse=True)
        if ctx.cancel_requested or getattr(r, "timed_out", False):
            shutil.rmtree(output_dir, ignore_errors=True)
            if getattr(r, "timed_out", False):
                raise AdapterError(f"the voice engine stopped responding and was stopped after "
                                   f"{limit:.0f} seconds; nothing else was affected")
            return None
        if r.returncode != 0 or not wavs:
            shutil.rmtree(output_dir, ignore_errors=True)
            from .mflux_image import MISSING_WEIGHTS
            if any(mark in (r.stderr or "") for mark in MISSING_WEIGHTS):
                raise AdapterError("That voice's files are not on this machine, so nothing was made. "
                                   "Nothing was downloaded: NeoVak stays offline while it makes things.")
            if r.returncode != 0:
                raise AdapterError(r.stderr[-500:] if r.stderr else f"mlx-audio exited {r.returncode}")
            raise AdapterError("The voice engine finished without writing a sound file, so nothing was made.")
        os.rename(wavs[0], final_path)
        shutil.rmtree(output_dir, ignore_errors=True)
        if p["speed"] != 1.0 and not spec.get("own_speed"):
            self._retime(final_path, p["speed"], ctx)
            if ctx.cancel_requested:
                return None
        if os.environ.get("NEOVAK_PREVIEW", "").lower() in ("1", "true", "yes"):
            subprocess.Popen(["open", final_path])
        text = p["text"]
        return {"files": [final_path], "path": final_path,
                "text": text[:100] + ("..." if len(text) > 100 else ""),
                "voice": p["voice"], "speed": p["speed"], "peak_gb": getattr(r, "peak_gb", None),
                "time_seconds": elapsed}

    def _retime(self, path, speed, ctx):
        """Changes the pace of a finished recording and keeps its pitch, for the voices that ignore --speed."""
        out = Path(path).with_name(Path(path).stem + ".retime.wav")
        done = ctx.spawn([FFMPEG, "-nostdin", "-y", "-loglevel", "error", "-i", path, "-af", f"atempo={speed}", str(out)], timeout=300)
        if ctx.cancel_requested:
            out.unlink(missing_ok=True)
            Path(path).unlink(missing_ok=True)
            return
        if done.returncode != 0 or not out.is_file():
            out.unlink(missing_ok=True)
            Path(path).unlink(missing_ok=True)
            raise AdapterError("The recording was made, but its speed could not be changed. Nothing was kept.")
        os.replace(out, path)
