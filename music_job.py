#!/opt/homebrew/bin/python3
"""Background music job for NeoVak's generate_music when the job queue is off. Wired 2026-10-15.

neovak_server.py starts this as a detached process and returns a job id at once. This script asks the
memory check for room (11 GB), runs MiniMax-Music3 (4-bit, MLX) from the separate mlx-audio environment
named in the settings file (NeoVak's own venv is never touched), and writes the outcome into NeoVak's
jobs.json, where check_job reads it.

usage: music_job.py JOB_ID OUTPUT_WAV DURATION_SECONDS CAPTION [LYRICS]
"""
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
JOBS = HERE / "jobs.json"
sys.path.insert(0, str(HERE))
from neovak_queue import settings as _settings  # noqa: E402
from neovak_queue import memory as _memory  # noqa: E402
_S = _settings.load()
GEN = str(Path(_S.tool("music_python")).parent / "mlx_audio.music.generate") if _S.tool("music_python") else ""
MODEL = "mlx-community/MiniMax-Music3-4bit"
NEED_GIB = "11"


def update(job_id, **fields):
    fields["updated"] = datetime.now().isoformat()
    for _ in range(20):
        try:
            jobs = json.loads(JOBS.read_text()) if JOBS.exists() else {}
            jobs.setdefault(job_id, {}).update(fields)
            tmp = JOBS.with_name("jobs.json.tmp_%d" % os.getpid())
            tmp.write_text(json.dumps(jobs, indent=2))
            os.replace(tmp, JOBS)
            return
        except (json.JSONDecodeError, OSError):
            time.sleep(0.25)


def main():
    job_id, out, duration, caption = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
    lyrics = sys.argv[5] if len(sys.argv) > 5 else "[inst]"
    if not GEN or not Path(GEN).is_file():
        update(job_id, status="failed", error="Music needs the mlx-audio environment, which is not set up on this machine. "
                                               "The settings file names it under [tools] music_python.")
        return 1
    update(job_id, status="checking_memory")
    check = _memory.preflight(NEED_GIB)
    if not check["go"]:
        update(job_id, status="blocked", governor=check["report"][-800:],
               message="The memory check said NO-GO: not enough free memory for the music model "
                       "(about 11 GB). Nothing was run. Try again when a large model is unloaded.")
        return 1
    update(job_id, status="generating")
    start = time.time()
    cmd = [GEN, "--model", MODEL, "--caption", caption, "--lyrics", lyrics,
           "--duration", str(int(float(duration))), "--steps", "30",
           "--seed", str(int(start) % 100000), "--output", out]
    r = subprocess.run(cmd, capture_output=True, text=True)
    elapsed = round(time.time() - start, 1)
    if r.returncode == 0 and Path(out).exists():
        update(job_id, status="done", path=out, time_seconds=elapsed, message="Music written.")
        return 0
    update(job_id, status="failed", time_seconds=elapsed, error=((r.stderr or r.stdout or "no output")[-800:]))
    return 1


if __name__ == "__main__":
    sys.exit(main())
