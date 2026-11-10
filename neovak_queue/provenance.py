"""Provenance sidecars. Beside every finished output sits <file name>.json, which says what made it:
prompt, seed, model, time, the settings, the files it started from, and any recipe it belongs to.

Standard library only, so the people screen can use it too. Paths inside the output folder are
stored as bare file names, and nothing else about the machine is written, so a file and its sidecar
can be handed to someone else without carrying a home folder name with them.
"""
import hashlib
import json
import os
from datetime import datetime
from pathlib import Path

SCHEMA = 1
SUFFIX = ".json"
THUMBNAIL_MARK = "_thumb."
PROMPT_KEYS = ("prompt", "text", "brief")
FILE_PARAM_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".mp4", ".mov", ".wav", ".mp3", ".m4a"}


def sidecar_path(file_path):
    p = Path(file_path)
    return p.with_name(p.name + SUFFIX)


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def now_stamp():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def write(file_path, record):
    """Writes the sidecar for one finished file and returns its path."""
    file_path = Path(file_path)
    body = {"neovak_sidecar": SCHEMA, "file": file_path.name, "sha256": sha256(file_path),
            "bytes": file_path.stat().st_size}
    body.update(record)
    target = sidecar_path(file_path)
    tmp = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(body, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    os.replace(tmp, target)
    return target


def _inside(output_dir, value):
    try:
        return Path(value).resolve().is_relative_to(Path(output_dir).resolve())
    except (OSError, ValueError, RuntimeError):
        return False


def split_sources(params, output_dir):
    """Returns (params safe to store, sources). A parameter naming a real file becomes a bare name."""
    stored, sources = {}, []

    def take(key, value):
        path = Path(value)
        entry = {"param": key, "file": path.name, "in_output_folder": _inside(output_dir, value)}
        if path.is_file():
            entry["sha256"] = sha256(path)
        sources.append(entry)
        return path.name

    for key, value in params.items():
        if key not in PROMPT_KEYS and isinstance(value, str) and value.startswith("/") and Path(value).suffix.lower() in FILE_PARAM_SUFFIXES:
            stored[key] = take(key, value)
        elif isinstance(value, list) and any(isinstance(v, dict) for v in value):
            # a timeline's clips and sounds: each item names a file the same way
            kept = []
            for i, item in enumerate(value):
                kept.append({k: (take(f"{key}.{i}.{k}", v) if isinstance(v, str) and v.startswith("/") and Path(v).suffix.lower() in FILE_PARAM_SUFFIXES else v)
                             for k, v in item.items()} if isinstance(item, dict) else item)
            stored[key] = kept
        else:
            stored[key] = value
    return stored, sources


def _model_of(adapter, params, result):
    model = result.get("model") or params.get("model") or params.get("voice") or adapter.name
    name = None
    try:
        for entry in adapter.models():
            if model in (entry.get("model"), entry.get("voice")):
                name = entry.get("label") or entry.get("repo")
    except Exception:  # noqa: BLE001  a description must never cost a finished file its record
        pass
    return model, name or str(model)


def for_job(rec, adapter, output_dir):
    """Sidecars for every output of a finished queue job. Returns the paths written."""
    params, result = rec.get("params") or {}, rec.get("result") or {}
    stored, sources = split_sources(params, output_dir)
    prompt = next((params[k] for k in PROMPT_KEYS if params.get(k)), None)
    seed = result.get("seed", params.get("seed"))
    model, model_name = _model_of(adapter, params, result)
    settings = {k: v for k, v in stored.items() if k not in PROMPT_KEYS + ("seed",) and k not in {s["param"] for s in sources}}
    record = {"made": now_stamp(), "seconds": (rec.get("progress") or {}).get("elapsed_seconds"), "lane": rec.get("lane"),
              "adapter": rec.get("adapter"), "model": model, "model_name": model_name,
              "model_in_file": result.get("model_in_file"), "prompt": prompt,
              "prompt_as_sent": result.get("prompt") if isinstance(result.get("prompt"), str) else None,
              "seed": seed, "settings": settings, "sources": sources, "job": rec.get("id"), "client": rec.get("client"),
              "peak_gb": result.get("peak_gb"), "remake": {"adapter": rec.get("adapter"), "params": stored,
                                                            "file_params": [s["param"] for s in sources]}}
    context = rec.get("context") or {}
    if context.get("recipe"):
        record["recipe"] = context["recipe"]
    if context.get("chain"):
        record["chain"] = context["chain"]
    written = []
    for path in result.get("files") or []:
        if THUMBNAIL_MARK in Path(path).name or not Path(path).is_file():
            continue
        written.append(str(write(path, record)))
    return written


def read(output_dir, name):
    """The sidecar of a file directly inside the output folder, or None. Names only, never paths."""
    if not isinstance(name, str) or not name or "/" in name or "\\" in name or "\x00" in name or name.startswith("."):
        return None
    root = Path(output_dir).resolve()
    try:
        target = (root / (name + SUFFIX)).resolve()
        target.relative_to(root)
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) and data.get("neovak_sidecar") else None


def remake_request(sidecar, output_dir, new_seed=False):
    """(adapter, params) to make the same thing again. Raises ValueError with a plain sentence when
    a file it started from has gone or has changed, because the result would no longer be the same."""
    remake = sidecar.get("remake") or {}
    if not remake.get("adapter") or not isinstance(remake.get("params"), dict):
        raise ValueError("This file was not made in a way that can be repeated.")
    params = dict(remake["params"])
    root = Path(output_dir).resolve()
    for source in sidecar.get("sources") or []:
        name, key = source.get("file"), source.get("param")
        path = (root / name).resolve() if source.get("in_output_folder") and isinstance(name, str) and "/" not in name else None
        if path is None or not path.is_file() or not path.is_relative_to(root):
            raise ValueError(f"It started from {name}, which is no longer in the output folder.")
        if source.get("sha256") and sha256(path) != source["sha256"]:
            raise ValueError(f"It started from {name}, and that file has changed since.")
        if "." in key:  # one file inside a list, such as clips.0.file
            field, index, inner = key.split(".", 2)
            params[field] = [dict(v) if isinstance(v, dict) else v for v in params[field]]
            params[field][int(index)][inner] = str(path)
        else:
            params[key] = str(path)
    if new_seed and "seed" in params:
        params["seed"] = -1
    return remake["adapter"], params
