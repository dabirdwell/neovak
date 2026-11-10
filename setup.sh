#!/bin/bash
# One command to get NeoVak ready on an Apple Silicon Mac:
#   ./setup.sh
# It checks the Mac and Python, makes NeoVak's own venv, installs what the picture and voice
# lanes need, writes an example settings file if there is none, and runs the doctor so you can
# see what this Mac has. It downloads Python packages only. It never downloads model weights.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE"

say() { printf '%s\n' "$*"; }
stop() { printf 'Stopped: %s\n' "$*" >&2; exit 1; }

[ "$(uname -s)" = "Darwin" ] || stop "NeoVak runs on macOS only."
[ "$(uname -m)" = "arm64" ] || stop "NeoVak runs on Apple Silicon (M1 and later) only. This Mac reports $(uname -m)."

PY=""
for candidate in /opt/homebrew/bin/python3.13 /opt/homebrew/bin/python3.12 /opt/homebrew/bin/python3.11 /opt/homebrew/bin/python3 /usr/local/bin/python3 "$(command -v python3 || true)"; do
  if [ -n "$candidate" ] && [ -x "$candidate" ] && "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
    PY="$candidate"; break
  fi
done
[ -n "$PY" ] || stop "Python 3.11 or later was not found. Install Homebrew (https://brew.sh) and then: brew install python@3.13"
say "Using $PY ($("$PY" --version 2>&1))"

if ! command -v ffmpeg >/dev/null 2>&1 && [ ! -x /opt/homebrew/bin/ffmpeg ]; then
  say "ffmpeg is not installed. Voices, clips, animation and the timeline need it: brew install ffmpeg"
fi

if [ ! -x venv/bin/python3 ]; then
  say "Making NeoVak's own Python environment in ./venv"
  "$PY" -m venv venv
fi
say "Installing Python packages (this is the only download setup.sh makes)"
venv/bin/python3 -m pip install --quiet --upgrade pip
venv/bin/python3 -m pip install --quiet -r requirements.txt

SETTINGS="$HOME/.config/neovak/settings.toml"
if [ ! -f "$SETTINGS" ]; then
  mkdir -p "$(dirname "$SETTINGS")"
  cp settings.example.toml "$SETTINGS"
  say "Wrote an example settings file to $SETTINGS. Open it to tell NeoVak where your models are."
else
  say "Settings file: $SETTINGS"
fi

say ""
say "Now the doctor, which says what this Mac has for each lane:"
say ""
venv/bin/python3 -m neovak_queue.doctor || true
say ""
say "To start NeoVak:   ./run_rest.sh            (the engine, in this window)"
say "In another window: people_screen/start.sh   (the screen), then open http://127.0.0.1:8102"
