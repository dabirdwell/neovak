#!/opt/homebrew/bin/python3
"""Runs music_job.py from the folder above unchanged, but points its record keeping
at this screen's own file, so the repo's jobs.json is left alone.

usage: music_runner.py JOBS_FILE JOB_ID OUTPUT_WAV DURATION_SECONDS CAPTION [LYRICS]
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import music_job  # noqa: E402

music_job.JOBS = Path(sys.argv[1])
sys.argv = ["music_job.py"] + sys.argv[2:]
sys.exit(music_job.main())
