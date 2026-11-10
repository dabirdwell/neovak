#!/bin/bash
# NeoVak REST launcher for launchd. Secrets live in ~/.config/neovak/env (mode 600), not in the plist.
# Every path of this machine comes from ~/.config/neovak/settings.toml; this script only finds itself.
HERE="$(cd "$(dirname "$0")" && pwd)"
set -a
[ -f "$HOME/.config/neovak/env" ] && . "$HOME/.config/neovak/env"
set +a
export PATH=/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin
export NEOVAK_QUEUE=1 HF_HUB_OFFLINE=1
cd "$HERE" || exit 1
exec "$HERE/venv/bin/python3" "$HERE/rest_server.py"
