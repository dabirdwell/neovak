"""The engine's access token: one shared secret in a file, read by the engine and by anything that calls it.

Standard library only, so the people screen and small scripts can use it too.

The file is ~/.config/neovak/env (mode 600), the same file run_rest.sh reads before it starts the
engine. A line NEOVAK_TOKEN=... turns the token on. With no such line the engine answers as it always has,
and /health says so, so nobody is left believing a door is locked when it is not.

NEOVAK_ENV_FILE points a test copy at another file, so a test engine and a test screen can share a token
of their own without touching the real one.

Why a token and not the address: the engine binds 127.0.0.1 and Tailscale Serve forwards the tailnet to it,
so a request from a phone across the network arrives looking local. The address proves nothing.
"""
import hmac
import os
import secrets
from pathlib import Path

ENV_FILE = Path(os.environ.get("NEOVAK_ENV_FILE") or (Path.home() / ".config" / "neovak" / "env"))
HEADER = "Authorization"
NAME = "NEOVAK_TOKEN"


def _from_file(path=None):
    try:
        text = Path(path or ENV_FILE).read_text(encoding="utf-8")
    except OSError:
        return None
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("export "):
            line = line[7:].strip()
        if not line.startswith(NAME + "="):
            continue
        value = line[len(NAME) + 1:].strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        return value or None
    return None


def engine_token():
    """The token in use, or None when none is set. The process environment wins, then the file."""
    value = (os.environ.get(NAME) or "").strip()
    return value or _from_file()


def auth_headers(token=None):
    """Headers a caller adds to every request to the engine. Empty when no token is set."""
    token = token if token is not None else engine_token()
    return {HEADER: "Bearer " + token} if token else {}


def presented(headers):
    """The token a request carries, from Authorization: Bearer or X-NeoVak-Token, else None."""
    auth = headers.get("authorization") or ""
    if auth.lower().startswith("bearer "):
        return auth[7:].strip() or None
    return (headers.get("x-neovak-token") or "").strip() or None


def matches(given, expected):
    return bool(given) and bool(expected) and hmac.compare_digest(given.encode("utf-8"), expected.encode("utf-8"))


def new_token():
    return secrets.token_urlsafe(32)


if __name__ == "__main__":
    import sys
    if sys.argv[1:] == ["new"]:
        print(new_token())
    elif sys.argv[1:] == ["status"]:
        print("token set" if engine_token() else "no token set", "(" + str(ENV_FILE) + ")")
    else:
        print("usage: python3 -m neovak_queue.secret new | status", file=sys.stderr)
        raise SystemExit(2)
