#!/bin/bash
# Starts the NeoVak people screen on port 8102 and returns at once. Paths come from the settings file.
HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE" || exit 1
mkdir -p state/logs
if [ -f state/server.pid ] && kill -0 "$(cat state/server.pid)" 2>/dev/null; then
  echo "already running, PID $(cat state/server.pid)"
  exit 0
fi
nohup "$HERE/../venv/bin/python3" "$HERE/app.py" >> state/logs/server.log 2>&1 &
echo $! > state/server.pid
echo "started, PID $(cat state/server.pid)"
