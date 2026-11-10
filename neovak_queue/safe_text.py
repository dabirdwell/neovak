"""Text that is safe to keep, write and answer with.

JSON can carry half of an emoji (a lone surrogate, Unicode category Cs). Python accepts it into a str and then
fails as soon as the text has to be encoded as UTF-8, which is what every response and sidecar does. So text from
outside has them removed on the way in (scrub), and a response is written so that one can never crash it (ascii_json).
Standard library only.
"""
import json
import unicodedata


def scrub(value):
    """value with every lone surrogate removed, at any depth of lists and dicts."""
    if isinstance(value, str):
        return "".join(c for c in value if unicodedata.category(c) != "Cs") if any("\ud800" <= c <= "\udfff" for c in value) else value
    if isinstance(value, list):
        return [scrub(v) for v in value]
    if isinstance(value, dict):
        return {scrub(k): scrub(v) for k, v in value.items()}
    return value


def ascii_json(content):
    """The bytes of a JSON response. Plain ASCII, so nothing already saved can stop a list from loading."""
    return json.dumps(content, ensure_ascii=True, allow_nan=False, separators=(",", ":")).encode("ascii")
