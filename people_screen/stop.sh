#!/bin/bash
# Stops the NeoVak people screen. It touches only the process recorded by start.sh.
HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE" || exit 1
if [ -f state/server.pid ] && kill -0 "$(cat state/server.pid)" 2>/dev/null; then
  kill "$(cat state/server.pid)" && echo "stopped PID $(cat state/server.pid)"
  rm -f state/server.pid
else
  echo "not running"
fi
