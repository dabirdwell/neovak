"""Who may use the people screen.

A passcode for each person, kept salted and hashed in the screen's state folder, added and removed only
from the command line (people.py). A session cookie that lasts 30 days and survives a restart of the
screen. A limit on wrong tries from one address. Standard library only.

The address of a request is never trusted. A laptop may reach the screen through an SSH tunnel, and
Tailscale Serve forwards to 127.0.0.1, so a request from across the network arrives looking local.
Every route needs a session, whatever the address says.
"""
import hashlib
import hmac
import json
import os
import secrets
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
STATE_DIR = Path(os.environ.get("PS_STATE_DIR", HERE / "state"))
PEOPLE_FILE = STATE_DIR / "people.json"
SESSION_FILE = STATE_DIR / "sessions.json"
COOKIE = "neovak_screen"
SESSION_DAYS = 30
SESSION_SECONDS = SESSION_DAYS * 86400
ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"  # no i, l, o, 0 or 1, so a passcode read aloud is not misheard
PASSCODE_GROUPS = 3
GROUP = 4
MAX_NAME = 40
TRIES_PER_ADDRESS = 8      # wrong tries one address may make in the window
TRIES_IN_ALL = 60          # wrong tries from everywhere in the window, so a forged address gains nothing
WINDOW_SECONDS = 15 * 60
# Once the wrong tries from everywhere reach TRIES_IN_ALL, the screen takes one try a minute from anyone, instead of
# closing the door to everybody for the whole window: one guesser can no longer lock the household out for 15 minutes,
# and one guess a minute against a 12 character passcode (31 letters each) is still no way in.
SHARED_GAP_SECONDS = 60


def new_passcode():
    return "-".join("".join(secrets.choice(ALPHABET) for _ in range(GROUP)) for _ in range(PASSCODE_GROUPS))


def normalize(code):
    """What a person typed, with spaces, dashes and capitals forgiven."""
    return "".join(c for c in str(code or "").lower() if c.isalnum())[:64]


def _hash(code, salt_hex):
    return hashlib.scrypt(normalize(code).encode("utf-8"), salt=bytes.fromhex(salt_hex), n=2 ** 14, r=8, p=1, dklen=32).hex()


def _read(path, default):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else dict(default)
    except (OSError, ValueError):
        return dict(default)


def _write(path, data):
    """Written whole, then moved into place, readable by this user only."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=1, sort_keys=True), encoding="utf-8")
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


class People:
    """The people who hold a passcode. The passcode itself is never stored, only its salted hash."""

    def __init__(self, path=None):
        self.path = Path(path or PEOPLE_FILE)
        self.lock = threading.Lock()

    def _load(self):
        return _read(self.path, {"people": []}).get("people") or []

    def listing(self):
        return [{"id": p["id"], "name": p["name"], "added": p.get("added")} for p in self._load()]

    def named(self, name):
        want = " ".join(str(name or "").split()).casefold()
        return next((p for p in self._load() if p["name"].casefold() == want), None)

    def add(self, name):
        """A new person. Returns (person, passcode). The passcode is shown once and never kept."""
        name = " ".join(str(name or "").split())
        if not name or len(name) > MAX_NAME:
            raise ValueError(f"Please give a name of 1 to {MAX_NAME} characters.")
        with self.lock:
            people = self._load()
            if any(p["name"].casefold() == name.casefold() for p in people):
                raise ValueError(f"There is already a passcode for {name}. Remove it first to make a new one.")
            code = new_passcode()
            salt = secrets.token_hex(16)
            person = {"id": secrets.token_hex(8), "name": name, "salt": salt, "hash": _hash(code, salt),
                      "added": time.strftime("%Y-%m-%d %H:%M")}
            people.append(person)
            _write(self.path, {"people": people})
        return person, code

    def remove(self, name):
        with self.lock:
            people = self._load()
            keep = [p for p in people if p["name"].casefold() != " ".join(str(name or "").split()).casefold()]
            if len(keep) == len(people):
                return None
            _write(self.path, {"people": keep})
            return next(p for p in people if p not in keep)

    def check(self, code):
        """The person this passcode belongs to, or None. Every stored hash is tried, so a miss costs the same as a hit."""
        if not normalize(code):
            return None
        found = None
        for p in self._load():
            if hmac.compare_digest(_hash(code, p["salt"]), p["hash"]) and found is None:
                found = p
        return found

    def any(self):
        return bool(self._load())


class Sessions:
    """Signed-in sessions, by the hash of their cookie token, on disk so a restart signs nobody out."""

    def __init__(self, path=None):
        self.path = Path(path or SESSION_FILE)
        self.lock = threading.Lock()
        self.stamp = None
        with self.lock:
            self._reload()

    def _stamp(self):
        try:
            st = self.path.stat()
            return (st.st_mtime_ns, st.st_size)
        except OSError:
            return None

    def _reload(self):
        self.rows = self._fresh(_read(self.path, {"sessions": {}}).get("sessions") or {})
        self.stamp = self._stamp()

    def _catch_up(self):
        """people.py removes sessions in the file while the screen runs; the screen must see that at once."""
        if self._stamp() != self.stamp:
            self._reload()

    @staticmethod
    def _fresh(rows):
        now = time.time()
        return {k: v for k, v in rows.items() if isinstance(v, dict) and now - float(v.get("made", 0)) < SESSION_SECONDS}

    @staticmethod
    def _key(token):
        return hashlib.sha256(str(token or "").encode("utf-8")).hexdigest()

    def _save(self):
        _write(self.path, {"sessions": self.rows})
        self.stamp = self._stamp()

    def create(self, person, secure=False):
        token = secrets.token_urlsafe(32)
        with self.lock:
            self._catch_up()
            self.rows[self._key(token)] = {"person": person["id"], "name": person["name"], "made": time.time(), "seen": time.time(), "secure": bool(secure)}
            self._save()
        return token

    def person_for(self, token):
        """{"id", "name"} for a live session, else None. The last-seen time is refreshed at most hourly."""
        if not token:
            return None
        key = self._key(token)
        with self.lock:
            self._catch_up()
            row = self.rows.get(key)
            if row is None or time.time() - float(row.get("made", 0)) >= SESSION_SECONDS:
                if row is not None:
                    del self.rows[key]
                    self._save()
                return None
            if time.time() - float(row.get("seen", 0)) > 3600:
                row["seen"] = time.time()
                self._save()
            return {"id": row["person"], "name": row["name"]}

    def drop(self, token):
        with self.lock:
            self._catch_up()
            if self.rows.pop(self._key(token), None) is not None:
                self._save()
                return True
        return False

    def drop_person(self, person_id):
        with self.lock:
            self._catch_up()
            before = len(self.rows)
            self.rows = {k: v for k, v in self.rows.items() if v.get("person") != person_id}
            if len(self.rows) != before:
                self._save()
            return before - len(self.rows)

    def count_for(self, person_id):
        with self.lock:
            return sum(1 for v in self.rows.values() if v.get("person") == person_id)


class Attempts:
    """Wrong passcodes, counted per address and in all, inside a sliding window."""

    def __init__(self):
        self.lock = threading.Lock()
        self.by_address = {}
        self.all = []

    def _trim(self):
        edge = time.time() - WINDOW_SECONDS
        self.all = [t for t in self.all if t > edge]
        for addr in list(self.by_address):
            kept = [t for t in self.by_address[addr] if t > edge]
            if kept:
                self.by_address[addr] = kept
            else:
                del self.by_address[addr]

    def wait_seconds(self, address):
        """0 when another try is allowed now, else how long until the oldest counted try falls out of the window."""
        with self.lock:
            return self._wait_locked(address)

    def _wait_locked(self, address):
        """wait_seconds for a caller that already holds the lock."""
        self._trim()
        mine = self.by_address.get(address, [])
        waits = []
        if len(mine) >= TRIES_PER_ADDRESS:
            waits.append(mine[-TRIES_PER_ADDRESS] + WINDOW_SECONDS - time.time())
        if len(self.all) >= TRIES_IN_ALL:
            gap = self.all[-1] + SHARED_GAP_SECONDS - time.time()
            if gap > 0:
                waits.append(gap)
        if not waits:
            return 0
        return max(1, int(max(waits)) + 1)

    def reserve(self, address):
        """(wait, ticket). Counts the try before the passcode is checked, under the same lock that decides whether it
        may be made, so a burst of tries sent at once is counted try by try and the limits hold: the ninth try from one
        address, and the try after sixty in all, wait, however many arrive in the same moment. wait is 0 and ticket the
        try's own mark when the try may go ahead; give the ticket back with release() when the passcode was right."""
        with self.lock:
            wait = self._wait_locked(address)
            if wait:
                return wait, None
            now = time.time()
            self.by_address.setdefault(address, []).append(now)
            self.all.append(now)
            return 0, now

    def release(self, address, ticket):
        """A try that turned out right is not a wrong try: its mark comes off both counts."""
        with self.lock:
            for marks in (self.by_address.get(address, []), self.all):
                if ticket in marks:
                    marks.remove(ticket)
            self.by_address.pop(address, None)

    def failed(self, address):
        with self.lock:
            now = time.time()
            self.by_address.setdefault(address, []).append(now)
            self.all.append(now)

    def clear(self, address):
        with self.lock:
            self.by_address.pop(address, None)


LOOPBACK = ("127.0.0.1", "::1", "localhost")


def address_of(scope_headers, client_host):
    """The address a sign-in try is counted against. Behind Tailscale Serve over https the real address is in
    X-Forwarded-For. It is read only when the request reached this screen from the Mac itself under a name that is not
    a loopback address (that is what a forwarder sends), and the entry read is the last one that is not a loopback
    address: a forwarder adds the address it saw at the end, so anything a client wrote earlier in the header is
    ignored and a guesser cannot spread its tries over made-up addresses."""
    if client_host in ("127.0.0.1", "::1"):
        host = (scope_headers.get("host") or "").strip().lower()
        name = host[1:].split("]")[0] if host.startswith("[") else host.rsplit(":", 1)[0]
        if name and name not in LOOPBACK:
            hops = [h.strip() for h in (scope_headers.get("x-forwarded-for") or "").split(",") if h.strip()]
            hops = [h for h in hops if h not in LOOPBACK]
            if hops:
                return hops[-1][:64]
    return client_host or "unknown"


def in_plain_words(seconds):
    if seconds < 60:
        return f"{seconds} seconds"
    minutes = (seconds + 59) // 60
    return "1 minute" if minutes == 1 else f"{minutes} minutes"
