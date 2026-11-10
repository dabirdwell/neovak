#!/usr/bin/env python3
"""Add NeoVak's chat tools to Claude Desktop, pointing at this folder's own venv.

Run it with the venv's python3: venv/bin/python3 setup.py
It writes a backup of the config first, and never touches any other entry.
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
CONFIG = Path.home() / "Library/Application Support/Claude/claude_desktop_config.json"
BACKUP = CONFIG.with_suffix(".json.bak")

if not CONFIG.exists():
    print(f"Claude Desktop's config was not found at {CONFIG}. Nothing was changed.")
    sys.exit(1)
config = json.loads(CONFIG.read_text())

if "neovak" in config.get("mcpServers", {}):
    print("NeoVak is already in the config. Nothing was changed.")
else:
    BACKUP.write_text(json.dumps(config, indent=2))
    print(f"Backed up to {BACKUP}")
    python = HERE / "venv" / "bin" / "python3"
    config.setdefault("mcpServers", {})["neovak"] = {
        "command": str(python if python.exists() else Path(sys.executable)),
        "args": [str(HERE / "neovak_server.py")],
        "env": {"PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin", "NEOVAK_QUEUE": "1", "NEOVAK_QUEUE_WORKER": "0", "HF_HUB_OFFLINE": "1"},
    }
    CONFIG.write_text(json.dumps(config, indent=2))
    json.loads(CONFIG.read_text())
    print("NeoVak added to Claude Desktop's config. Restart Claude Desktop to see its tools.")
    print("The tools send work to the engine (run_rest.sh) and never run a model themselves.")
