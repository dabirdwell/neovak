#!/usr/bin/env python3
"""Downloads one model the Models page offers. Arguments: repo, revision, destination, largest allowed bytes,
then the licences allowed, comma separated. Run as its own process group so Stop can end it.

It sends no token, so no account travels with the request. It checks the size and licence with the
server again right before downloading and refuses if either has changed from what the page promised.
"""
import json
import os
import sys
from pathlib import Path

os.environ.pop("HF_HUB_OFFLINE", None)
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
from huggingface_hub import HfApi, snapshot_download  # noqa: E402


def main():
    repo, revision, dest, largest, licences = sys.argv[1], sys.argv[2], Path(sys.argv[3]), int(sys.argv[4]), set(sys.argv[5].split(","))
    info = HfApi().model_info(repo, revision=revision, files_metadata=True, token=False)
    total = sum(f.size or 0 for f in info.siblings)
    tags = {t.split(":", 1)[1] for t in info.tags if t.startswith("license:")}
    if info.gated or info.private or not (tags & licences) or not 0 < total <= largest:
        print(json.dumps({"refused": True, "bytes": total, "licence": sorted(tags)}), flush=True)
        return 3
    print(json.dumps({"bytes": total, "files": [f.rfilename for f in info.siblings]}), flush=True)
    snapshot_download(repo, revision=revision, local_dir=str(dest), token=False)
    for f in info.siblings:
        if not (dest / f.rfilename).is_file():
            print(json.dumps({"missing": f.rfilename}), flush=True)
            return 4
    (dest / ".neovak_installed.json").write_text(json.dumps({"repo": repo, "revision": revision, "bytes": total, "licence": sorted(tags)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
