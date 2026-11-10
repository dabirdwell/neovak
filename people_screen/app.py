#!/usr/bin/env python3
"""NeoVak people screen. Its own process on port 8102, bound to the addresses the settings file
names under [hosts] screen (127.0.0.1 and this Mac's private network address). Run with the venv's
python3 (people_screen/start.sh does).

Every route needs a signed-in session (see auth.py and people.py). The address a request comes from is
never a key: a tunnel or a private network forwarder makes a remote request look local."""
import asyncio
import os
import secrets
import socket
import subprocess
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit

import uvicorn
from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.middleware import Middleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.responses import FileResponse, HTMLResponse
from starlette.responses import JSONResponse as _StarletteJSON
from starlette.routing import Route

import auth
import core
import studio
from neovak_queue.safe_text import ascii_json, scrub


class JSONResponse(_StarletteJSON):
    """Half of an emoji in something already saved must not stop a list from loading."""

    def render(self, content):
        return ascii_json(content)

PORT = int(os.environ.get("PS_PORT", "8102"))
HOSTS = core.SETTINGS.screen_hosts  # [hosts] screen in the settings file: the addresses this screen binds and answers to
# PS_EXTRA_HOSTS: other names this screen may be reached by, comma separated. A private network forwarder's
# name goes here when it forwards to this screen; it is a name, not an address to bind, and the forward
# itself arrives on 127.0.0.1.
EXTRA_HOSTS = [h.strip().lower() for h in os.environ.get("PS_EXTRA_HOSTS", "").split(",") if h.strip()]
ALLOWED = HOSTS + ["localhost"] + EXTRA_HOSTS
PAGE = Path(__file__).resolve().parent / "index.html"
SIGNIN_PAGE = Path(__file__).resolve().parent / "signin.html"
CSP = ("default-src 'none'; img-src 'self' blob: data:; media-src 'self' blob:; connect-src 'self'; "
       "style-src 'self' 'unsafe-inline'; script-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
NO_FRAME = {"X-Frame-Options": "DENY"}  # the older header for the same rule: no other site may put this screen in a frame
PROJECTS = studio.Projects()
PEOPLE = auth.People()
SESSIONS = auth.Sessions()
ATTEMPTS = auth.Attempts()
WRONG_PASSCODE_PAUSE = 0.6  # seconds, the same for every miss, so the answer's timing says nothing

core.AFTER_RECORD.append(lambda job: PROJECTS.add(job["result"]["name"], job["params"].get("project")))
_last_refresh = {"at": 0.0, "running": False}
_quiet = dict(core.RECORDS.backend("quiet_memory") or {"reading": None, "at": 0.0})  # kept across restarts of this screen
_engine = {"at": 0.0, "ok": None}


def _refresh_soon():
    """Refresh the engine's lists in the background, at most every ten minutes."""
    if _last_refresh["running"] or time.time() - _last_refresh["at"] < 600:
        return
    _last_refresh["running"] = True

    def work():
        try:
            core.refresh_backend()
        finally:
            _last_refresh.update(running=False, at=time.time())
    threading.Thread(target=work, daemon=True).start()


def _engine_state():
    """ready, working or silent. The engine is asked whether it answers even while a job of this screen is in
    flight (more often then), so a dead engine is never reported as working."""
    running = core.GENERATION.running()
    if time.time() - _engine["at"] > (5 if running else 15):
        _engine.update(ok=core.engine_answering(), at=time.time())
    if not _engine["ok"]:
        return "silent"
    return "working" if running else "ready"


QUIET_IDLE = 20     # seconds the queue has to have been idle before a live reading counts as a quiet one
QUIET_KEEP = 7200   # a quiet reading older than this says nothing about the machine as it is now
BUSY_MEMORY_TTL = 3  # while work runs, the shared memory reading is at most this old, on every page alike


def _judge(reading, state):
    """The figure every fit on the screen is judged against, and why.

    While something runs, its model holds memory, so the live figure would call everything too big; new work waits
    its turn, so it is judged against what was free when nothing ran. But the live figure is a floor on that (memory
    only comes back when the job ends), so whichever of the two is larger is used, and a session where jobs follow one
    another without a quiet minute still gets a fair figure. When nothing has run for a while the live reading is the
    truth and replaces the stored one. In the short while after a job ends the live figure can still be low while the
    weights drain, so the stored one is kept if it is larger, and raised when the live one passes it."""
    live = reading.get("available_gb")
    now = time.time()
    quiet = _quiet["reading"] if _quiet["reading"] and _quiet["reading"].get("available_gb") is not None and now - _quiet["at"] < QUIET_KEEP else None
    quiet_gb = quiet.get("available_gb") if quiet else None
    if live is not None and not state["now"] and (state["idle_for"] >= QUIET_IDLE or quiet_gb is None or live > quiet_gb):
        # idle long enough for a fresh reading, or the live figure is already better than the stored one
        if _quiet["reading"] is not reading:
            _quiet["reading"], _quiet["at"] = reading, now
            if now - _quiet.get("saved_at", 0) > 60:
                core.RECORDS.set_backend("quiet_memory", {"reading": reading, "at": now})
                _quiet["saved_at"] = now
        quiet, quiet_gb = reading, live
    if not state["recent"]:
        return reading  # nothing running and nothing just finished: the live figure is the one
    if state.get("starved"):
        # The engine is itself waiting for memory: nothing it is running will give memory back, so the figure from the
        # last quiet moment would promise a fit the memory check is refusing at this very minute.
        return dict(reading, starved=True)
    if live is None and quiet is None:
        return {"wait": True}
    if quiet is not None and (live is None or quiet_gb >= live):
        return dict(quiet, quiet=True) if quiet is not reading else dict(reading)
    return dict(reading)  # the live figure is the larger, and it is a floor on what the next job will find


def _status():
    _refresh_soon()
    state = core.queue_state()
    reading = core.MEMORY.read(BUSY_MEMORY_TTL if state["recent"] else None)
    fit = _judge(reading, state)
    judged = {"available_gb": fit.get("available_gb"), "safety_gb": fit.get("safety_gb"), "quiet": bool(fit.get("quiet")), "wait": bool(fit.get("wait")),
              "running": bool(state["now"])}
    return {"memory": {"available_gb": reading.get("available_gb"), "safety_gb": reading.get("safety_gb"), "judged": judged}, "busy": state["recent"],
            "hold": core.hold_status(), "engine": _engine_state(), "job": core.GENERATION.running(), "line": len(core.GENERATION.active()),
            "catalog": core.catalog(fit)}


def _who(request):
    """The signed-in person's id, which jobs and the open project are kept under."""
    person = getattr(request.state, "person", None)
    return person["id"] if person else None


def _refuse(message, code):
    return JSONResponse({"error": message}, status_code=code)


async def _plain_500(request, exc):
    return JSONResponse({"error": "That request was not understood."}, status_code=500)


def _foreign(request):
    """True for a request another site's page made: an Origin that is not one of this screen's names, or the
    browser's own Sec-Fetch-Site saying cross-site (the engine refuses the same header the same way)."""
    origin = request.headers.get("origin")
    if origin and urlsplit(origin).hostname not in ALLOWED:
        return True
    return (request.headers.get("sec-fetch-site") or "").strip().lower() == "cross-site"


async def _json_body(request):
    """Only JSON from this page's own address. A page on another site cannot post here."""
    if _foreign(request):
        return None
    if request.headers.get("content-type", "").split(";")[0].strip() != "application/json":
        return None
    try:
        body = await request.json()
        return scrub(body) if isinstance(body, dict) else None
    except (ValueError, RecursionError):
        return None


async def index(request):
    return HTMLResponse(PAGE.read_text(encoding="utf-8"),
                        headers={"Content-Security-Policy": CSP, "Cache-Control": "no-store", **NO_FRAME})


async def status(request):
    return JSONResponse(dict(await run_in_threadpool(_status), person=request.state.person["name"]))


# --- sign in ----------------------------------------------------------------------------------- #

def _cookie_token(headers):
    for part in (headers.get("cookie") or "").split(";"):
        name, _, value = part.strip().partition("=")
        if name == auth.COOKIE:
            return value.strip() or None
    return None


def _over_https(headers, scheme):
    """True behind Tailscale Serve's TLS (X-Forwarded-Proto) or on a direct https connection."""
    return scheme == "https" or (headers.get("x-forwarded-proto") or "").split(",")[0].strip().lower() == "https"


def _signin_page():
    nonce = secrets.token_urlsafe(16)
    if PEOPLE.any():
        foot = "Passcodes are made on the Mac that runs NeoVak, one for each person. Ask whoever runs it for yours."
    else:
        foot = ("No passcode has been made yet. On the Mac that runs NeoVak, in the Terminal, run "
                "<code>people.py add &quot;Your name&quot;</code> inside the people_screen folder and it prints one.")
    page = SIGNIN_PAGE.read_text(encoding="utf-8").replace("__NONCE__", nonce).replace("__FOOT__", foot)
    csp = (f"default-src 'none'; style-src 'nonce-{nonce}'; script-src 'nonce-{nonce}'; connect-src 'self'; "
           "img-src 'self' data:; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
    return HTMLResponse(page, status_code=401, headers={"Content-Security-Policy": csp, "Cache-Control": "no-store", **NO_FRAME})


class NoSniff:
    """Every answer, the refusals included, says it is exactly the type it names, so no browser guesses a script
    or a page out of a file. Outermost, so even the Host check's 400 carries it."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def marked(message):
            if message.get("type") == "http.response.start":
                message["headers"] = [h for h in message.get("headers", []) if h[0].lower() != b"x-content-type-options"] + \
                    [(b"x-content-type-options", b"nosniff")]
            await send(message)
        await self.app(scope, receive, marked)


class SignInGuard:
    """Every route needs a session, whatever address the request comes from: a tunnel or Tailscale Serve
    makes a remote request look local. Without one, the front door shows the sign-in page and everything
    else answers 401. Only the sign-in call itself is open."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}
        person = SESSIONS.person_for(_cookie_token(headers))
        if person:
            scope.setdefault("state", {})["person"] = person
            await self.app(scope, receive, send)
            return
        path, method = scope["path"], scope["method"]
        if path == "/api/signin" and method == "POST":
            await self.app(scope, receive, send)
            return
        if path == "/" and method in ("GET", "HEAD"):
            response = _signin_page()
        else:
            response = JSONResponse({"error": "Please sign in first.", "signin": "/"}, status_code=401, headers={"Cache-Control": "no-store"})
        await response(scope, receive, send)


def _set_session_cookie(response, token, secure, clear=False):
    response.set_cookie(auth.COOKIE, "" if clear else token, max_age=0 if clear else auth.SESSION_SECONDS,
                        path="/", httponly=True, samesite="strict", secure=secure)


async def signin(request):
    body = await _json_body(request)
    if body is None:
        return _refuse("That request was not understood.", 400)
    address = auth.address_of(request.headers, request.client.host if request.client else None)
    # The try is counted before the passcode is checked, so tries sent all at once cannot slip past the limit together.
    wait, ticket = ATTEMPTS.reserve(address)
    if wait:
        return JSONResponse({"error": f"Too many tries. Please wait {auth.in_plain_words(wait)}.", "wait": wait}, status_code=429)
    person = await run_in_threadpool(PEOPLE.check, body.get("code"))
    if person is None:
        await asyncio.sleep(WRONG_PASSCODE_PAUSE)
        return _refuse("That passcode did not match.", 401)
    ATTEMPTS.release(address, ticket)
    secure = _over_https(request.headers, request.url.scheme)
    token = SESSIONS.create(person, secure)
    response = JSONResponse({"name": person["name"]})
    _set_session_cookie(response, token, secure)
    return response


async def signout(request):
    if not _local_only(request):
        return _refuse("That request was not understood.", 400)
    SESSIONS.drop(_cookie_token(request.headers))
    response = JSONResponse({"ok": True})
    _set_session_cookie(response, "", _over_https(request.headers, request.url.scheme), clear=True)
    return response


_presses = {}  # what was asked for a moment ago, so one press sent twice starts one job
_presses_lock = threading.Lock()
SAME_PRESS_SECONDS = 4


def _start(body, person=None):
    """The same request again within a few seconds, from a second tab, a phone or a network retry, is the same press."""
    key = core.hashlib.sha256(core.json.dumps([person, body], sort_keys=True, default=str).encode()).hexdigest()
    with _presses_lock:
        for k in [k for k, v in _presses.items() if v["at"] and time.time() - v["at"] > SAME_PRESS_SECONDS]:
            del _presses[k]
        first = _presses.get(key)
        mine = None if first else _presses.setdefault(key, {"ready": threading.Event(), "jobs": None, "at": None})
    if first:
        first["ready"].wait(45)
        view = core.GENERATION.view(first["jobs"][0], viewer=person) if first["jobs"] else None
        if view:
            return JSONResponse(dict(view, others=first["jobs"][1:], same_press=True))
        mine = {"ready": threading.Event(), "jobs": None, "at": None}  # the first press started nothing, so this one is answered on its own
    try:
        answer, jobs = _start_once(body, person)
    except BaseException:
        jobs = None
        raise
    finally:
        mine["jobs"], mine["at"] = jobs, time.time() if jobs else 0
        mine["ready"].set()
        if not jobs:
            with _presses_lock:
                if _presses.get(key) is mine:
                    del _presses[key]
    return answer


def _start_once(body, person=None):
    answer = _start_checked(body, person)
    return answer if isinstance(answer, tuple) else (answer, None)


def _start_checked(body, person=None):
    try:
        lane, params, need_gb, what = core.validate_create(body)
    except core.Invalid as e:
        return _refuse(str(e), 400)
    estimate = core.estimate_for(lane, params)
    try:
        count = int(body.get("count") or 1)
    except (TypeError, ValueError, OverflowError):
        count = 1
    count = max(1, min(core.MAX_BATCH, count)) if lane == "image" else 1
    # The nightly hold keeps models from loading. An animation or a film loads no model (need_gb is 0), and the
    # engine runs one during the hold, so the screen lets it through too instead of giving a memory reason.
    hold = core.hold_status(estimate_seconds=estimate) if need_gb else {"active": False}
    if hold["active"]:
        return _refuse(hold["message"], 423)
    busy = core.queue_busy()  # anything running, from this screen or any other tool, has its model in memory
    if len(core.GENERATION.active()) + count > core.MAX_WAITING:
        return _refuse(f"There are already {len(core.GENERATION.active())} things waiting. "
                       f"The line holds {core.MAX_WAITING}, so please wait for some to finish.", 409)
    if need_gb and hold_check(estimate * count + core.GENERATION.line_seconds()):
        return _refuse(core.hold_status(estimate_seconds=estimate * count + core.GENERATION.line_seconds())["message"], 423)
    # When something is running, its model is in memory; the queue asks before each job. A recipe is not asked here at
    # all: each of its steps asks when it starts and waits for room by itself, so it can be lined up when memory is short.
    if need_gb and not busy and lane != "recipe":
        check = core.ask_governor(need_gb)
        if not check.get("go"):
            return JSONResponse({"error": core.no_go_message(check, what), "kind": "memory", "try": core.alternatives(lane, params, check)}, status_code=409)
    if not core.engine_answering():
        return _refuse("The engine is not answering. It may be busy with other work. Please try again in a minute.", 503)
    jobs = []
    seed = params.get("seed")
    batch = core.uuid.uuid4().hex[:8] if count > 1 else None
    for i in range(count):
        each = dict(params, batch=batch)
        if lane == "image" and i:  # the first keeps a chosen seed; the rest are new, so each is different
            each["seed"] = int.from_bytes(core.os.urandom(4), "big") % 2 ** 31
        each["project"] = PROJECTS.open_for(person)
        try:
            jobs.append(core.GENERATION.begin(lane, each, core.RUNNERS[lane], estimate, person=person))
        except core.Busy:
            break
    if not jobs:
        return _refuse("The line is full. Please wait for some of it to finish.", 409)
    view = core.GENERATION.view(jobs[0]["id"], viewer=person)
    view["others"] = [j["id"] for j in jobs[1:]]
    return JSONResponse(view, status_code=202), [j["id"] for j in jobs]


def hold_check(seconds):
    return core.hold_status(estimate_seconds=seconds)["active"]


async def create(request):
    body = await _json_body(request)
    if body is None:
        return _refuse("That request was not understood.", 400)
    return await run_in_threadpool(_start, body, _who(request))


async def estimate(request):
    """The time figures for the settings as they stand, before any press: the same figure for every choice in the
    lane's list and for the choice made, from the place the working screen's own figure comes from."""
    body = await _json_body(request)
    if body is None or not isinstance(body.get("lane"), str):
        return _refuse("That request was not understood.", 400)
    return JSONResponse(await run_in_threadpool(core.estimate_options, body["lane"], body))


def _save_recipe(body):
    name = core.clean_prompt(body.get("name"))
    if not name or len(name) > 80:
        return _refuse("Please give it a short name.", 400)
    try:
        saved = core.backend_post("/api/recipes", {"from": body.get("from"), "name": name, "values": body.get("values") or {}}, 15)
    except core.urllib.error.HTTPError as e:
        try:
            return _refuse(core.json.loads(e.read().decode("utf-8", "ignore")).get("error") or "That could not be saved.", 400)
        except ValueError:
            return _refuse("That could not be saved.", 400)
    except (core.urllib.error.URLError, OSError, TimeoutError):
        return _refuse("The engine is not answering, so nothing was saved.", 503)
    core.recipes(fresh=True)
    return JSONResponse({"id": saved["id"], "label": saved["name"]}, status_code=201)


async def recipe_save(request):
    body = await _json_body(request)
    if body is None:
        return _refuse("That request was not understood.", 400)
    return await run_in_threadpool(_save_recipe, body)


def _delete_recipe(rid):
    req = core.backend_request("/api/recipes/" + core.urllib.parse.quote(rid, safe=""), method="DELETE")
    try:
        with core.urllib.request.urlopen(req, timeout=10):
            pass
    except core.urllib.error.HTTPError as e:
        try:
            return _refuse(core.json.loads(e.read().decode("utf-8", "ignore")).get("error") or "That could not be removed.", 400)
        except ValueError:
            return _refuse("That could not be removed.", 400)
    except (core.urllib.error.URLError, OSError, TimeoutError):
        return _refuse("The engine is not answering.", 503)
    core.recipes(fresh=True)
    return JSONResponse({"ok": True})


async def recipe_delete(request):
    if _foreign(request):
        return _refuse("That request was not understood.", 400)
    return await run_in_threadpool(_delete_recipe, request.path_params["recipe_id"])


async def item(request):
    view = await run_in_threadpool(core.describe_name, request.path_params["name"], core.sizes_available())
    return JSONResponse(view) if view else _refuse("That file is not in the output folder.", 404)


async def job(request):
    view = await run_in_threadpool(core.GENERATION.view, request.path_params["job_id"], core.sizes_available(), _who(request))
    return JSONResponse(view) if view else _refuse("That job is not known.", 404)


async def job_stop(request):
    if not _local_only(request):
        return _refuse("That request was not understood.", 400)
    found = core.GENERATION.jobs.get(request.path_params["job_id"])
    if found and found.get("person") and found["person"] != _who(request):
        return _refuse("Someone else started that, so only they can stop it.", 403)
    ok = await run_in_threadpool(core.cancel_job, request.path_params["job_id"])
    return JSONResponse({"ok": True}) if ok else _refuse("That could not be stopped. It may have finished.", 409)


def _start_preview(body):
    if core.GENERATION.running():
        return _refuse("This Mac is busy, so the preview will have to wait.", 409)
    try:
        _, params, _, _ = core.validate_create(dict(body, lane="animation"))
    except core.Invalid as e:
        return _refuse(str(e), 400)
    try:
        return JSONResponse(core.run_preview(params))
    except core.FriendlyError as e:
        return _refuse(str(e), 409)


async def preview(request):
    body = await _json_body(request)
    if body is None:
        return _refuse("That request was not understood.", 400)
    return await run_in_threadpool(_start_preview, body)


async def gallery(request):
    q = request.query_params
    try:
        offset, limit = max(0, int(q.get("offset", 0))), min(120, max(1, int(q.get("limit", 48))))
    except ValueError:
        return _refuse("That request was not understood.", 400)
    names = PROJECTS.items(q["project"]) if q.get("project") else None
    if q.get("project") and names is None:
        return _refuse("That project is not known.", 404)
    return JSONResponse(await run_in_threadpool(core.gallery, offset, limit, q.get("favorites") == "1", core.sizes_available(),
                                                names, q.get("kind") or None, (q.get("text") or "").strip()[:200] or None,
                                                q.get("hidden") == "1"))


async def favorite(request):
    body = await _json_body(request)
    if body is None or core.safe_media_path(body.get("name")) is None:
        return _refuse("That file is not in the output folder.", 400)
    core.RECORDS.update(Path(body["name"]).name, favorite=bool(body.get("on")))
    return JSONResponse({"name": body["name"], "favorite": bool(body.get("on"))})


async def hide(request):
    """Hide a file from the gallery, the strip and the timeline bin, or bring it back. The file itself is never touched."""
    body = await _json_body(request)
    if body is None or core.safe_media_path(body.get("name")) is None:
        return _refuse("That file is not in the output folder.", 400)
    core.RECORDS.update(Path(body["name"]).name, hidden=bool(body.get("on")))
    return JSONResponse({"name": body["name"], "hidden": bool(body.get("on"))})


def _start_enhance(body):
    lane = body.get("lane") if body.get("lane") in core.ENHANCE_LANES else "image"
    text = core.clean_prompt(body.get("prompt"))
    if not text:
        return _refuse("Please write something to improve first.", 400)
    if len(text) > core.MAX_PROMPT:
        return _refuse(f"That is too long. Please keep it under {core.MAX_PROMPT} characters.", 400)
    hold = core.hold_status()
    if hold["active"]:
        return _refuse(hold["message"], 423)
    if not core.queue_busy():  # with work lined up the writer takes its turn on the queue, and the queue asks
        check = core.ask_governor("9b")
        if not check.get("go"):
            return _refuse(core.no_go_message(check, "the writing helper"), 409)
    try:
        run = core.ENHANCE.begin("enhance", {"prompt": text, "lane": lane}, core.run_enhance, 12)
    except core.Busy:
        return _refuse("The writing helper is still working on the last one.", 409)
    return JSONResponse(core.ENHANCE.view(run["id"]), status_code=202)


async def enhance(request):
    body = await _json_body(request)
    if body is None:
        return _refuse("That request was not understood.", 400)
    return await run_in_threadpool(_start_enhance, body)


async def enhance_job(request):
    view = core.ENHANCE.view(request.path_params["job_id"])
    return JSONResponse(view) if view else _refuse("That request is not known.", 404)


async def media(request):
    target = core.safe_media_path(request.path_params["path"])
    if target is None:
        return _refuse("Not found.", 404)
    return FileResponse(target)


def _local_only(request):
    return not _foreign(request)


async def ui_file(request):
    target = studio.named(studio.UI_DIR, request.path_params["name"], set(studio.UI_SUFFIXES))
    if target is None:
        return _refuse("Not found.", 404)
    return FileResponse(target, media_type=studio.UI_SUFFIXES[target.suffix.lower()], headers={"Cache-Control": "no-store"})


async def starter_file(request):
    target = studio.named(studio.STARTER_DIR, request.path_params["name"], studio.STARTER_SUFFIXES)
    if target is None:
        return _refuse("Not found.", 404)
    return FileResponse(target, headers={"Cache-Control": "max-age=3600"})


async def starters(request):
    return JSONResponse(await run_in_threadpool(studio.starter_manifest))


def _gallery_file(request):
    target = core.safe_media_path(request.path_params["name"])
    return target if target is not None and target.parent == core.OUTPUT_DIR.resolve() else None


async def lift(request):
    """The main subject on transparent pixels, for the layered picture on the stage."""
    target = _gallery_file(request)
    if target is None or target.suffix.lower() not in core.IMAGE_SUFFIXES:
        return _refuse("Not found.", 404)
    layer = await run_in_threadpool(studio.subject_layer, target)
    return FileResponse(layer, headers={"Cache-Control": "max-age=86400"}) if layer else _refuse("No subject found.", 404)


async def peaks(request):
    target = _gallery_file(request)
    if target is None or target.suffix.lower() in core.IMAGE_SUFFIXES | core.TEXT_SUFFIXES:
        return _refuse("Not found.", 404)
    data = await run_in_threadpool(studio.waveform, target)
    return JSONResponse(data) if data else _refuse("No sound found.", 404)


async def strip(request):
    target = _gallery_file(request)
    if target is None or target.suffix.lower() not in core.VIDEO_SUFFIXES:
        return _refuse("Not found.", 404)
    made = await run_in_threadpool(studio.film_strip, target)
    return FileResponse(made, headers={"Cache-Control": "max-age=86400"}) if made else _refuse("Not found.", 404)


async def media_info(request):
    target = _gallery_file(request)
    if target is None:
        return _refuse("Not found.", 404)
    seconds = None if target.suffix.lower() in core.IMAGE_SUFFIXES | core.TEXT_SUFFIXES else await run_in_threadpool(studio.media_seconds, target)
    return JSONResponse({"seconds": seconds})


async def peek(request):
    """The newest frame of a picture that is still being made."""
    job = core.GENERATION.jobs.get(request.path_params["job_id"])
    if job is None or not job.get("live_path"):
        return _refuse("Not ready.", 404)
    try:
        frame = await run_in_threadpool(studio.peek_image, job["live_path"])
    except OSError:  # the engine is still writing it, or has just removed it
        return _refuse("Not ready.", 404)
    return FileResponse(frame, headers={"Cache-Control": "no-store"})


def _queue_view(viewer=None):
    sizes = core.sizes_available()
    jobs = core.GENERATION.views(sizes, viewer)
    tracked = [*core.GENERATION.jobs.values(), *core.ENHANCE.jobs.values()]
    # Only real ids: a job of this screen that has no recipe run (most of them) must not put None in the set, or every
    # other tool's job, whose recipe run is None too, would be taken for one of this screen's own and left out of the line.
    mine = {j.get("backend_id") for j in tracked} - {None}
    runs = {j.get("backend_run") for j in tracked} - {None}
    others = []
    try:
        for j in core.backend_get("/api/jobs?limit=40", 3).get("jobs", []):
            ctx = (j.get("context") or {}).get("recipe") or {}
            if j.get("state") not in ("queued", "running") or j["id"] in mine or ctx.get("run") in runs or (j.get("params") or {}).get("still"):
                continue  # a recipe's own steps, and this screen's own work, are already in the line above
            stage = (j.get("progress") or {}).get("stage") or ""
            others.append({"id": j["id"], "state": j["state"], "lane": j.get("lane"), "client": j.get("client"), "stage": core.plain_stage(stage),
                           "night": j["state"] == "queued" and stage.startswith("waiting for the nightly")})
    except (core.urllib.error.URLError, OSError, TimeoutError, ValueError):
        pass
    rewrites = [core.ENHANCE.view(j["id"], viewer=viewer) for j in core.ENHANCE.active()]  # part of the line, though they do not take the stage
    out = {"jobs": jobs, "others": others, "rewrites": rewrites, "limit": core.MAX_WAITING}
    if any(j.get("state") == "running" for j in jobs) or others or rewrites:
        # The page asks for the line every second while work runs; the header's memory figure comes with it, from the one
        # shared reading, so every page of every person shows the same figure within a few seconds of each other.
        reading = core.MEMORY.read(BUSY_MEMORY_TTL)
        out["memory"] = {"available_gb": reading.get("available_gb"), "safety_gb": reading.get("safety_gb"), "running": True}
    return out


async def queue(request):
    return JSONResponse(await run_in_threadpool(_queue_view, _who(request)))


async def models(request):
    def page():
        reading = core.MEMORY.read()
        state = core.queue_state()
        fit = _judge(reading, state)
        return studio.models_page(reading, fit if fit is not reading else None, running=state["now"])
    return JSONResponse(await run_in_threadpool(page))


async def install(request):
    body = await _json_body(request)
    if body is None:
        return _refuse("That request was not understood.", 400)
    try:
        return JSONResponse(await run_in_threadpool(studio.start_install, body.get("id")), status_code=202)
    except core.Invalid as e:
        return _refuse(str(e), 400)


async def install_stop(request):
    body = await _json_body(request)
    if body is None:
        return _refuse("That request was not understood.", 400)
    return JSONResponse({"ok": True}) if studio.stop_install(body.get("id")) else _refuse("That download is not running.", 409)


async def upload(request):
    """A picture, clip or sound dragged in from this computer. Only a person's own page can send one."""
    if not _local_only(request):
        return _refuse("That file could not be used.", 400)
    if request.headers.get("content-type", "").split(";")[0].strip().lower() not in studio.UPLOAD_TYPES:
        return _refuse("That kind of file cannot be used here. Pictures (PNG, JPEG or WebP), MP4 clips and sound files can, up to 300 MB each.", 400)
    too_large = _refuse("That file is too large. Please use one under 300 MB.", 413)
    try:
        if int(request.headers.get("content-length") or 0) > studio.MAX_UPLOAD:
            return too_large
    except ValueError:
        return _refuse("That file could not be used.", 400)
    # Counted as it arrives: a request need not say how long it is, and may say something untrue.
    chunks, total = [], 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > studio.MAX_UPLOAD:
            return too_large
        chunks.append(chunk)
    data = b"".join(chunks)
    try:
        name = await run_in_threadpool(studio.take_upload, request.headers["content-type"], data)
    except core.Invalid as e:
        return _refuse(str(e), 400)
    # The file's own name on the person's computer, as its title, so three files added one after another can be told
    # apart by their words. It is shown as text only and never touches a path; the stored file keeps the screen's name.
    given = core.clean_prompt(Path(core.urllib.parse.unquote(request.headers.get("x-file-name") or "")[:300]).stem.replace("_", " "))
    if given and len(given) <= 80:
        core.RECORDS.update(name, prompt=given)
    PROJECTS.add(name, person=_who(request))
    return JSONResponse(await run_in_threadpool(core.describe_name, name, core.sizes_available()), status_code=201)


async def projects(request):
    if request.method == "GET":
        return JSONResponse(PROJECTS.listing(_who(request)))
    body = await _json_body(request)
    name = core.clean_prompt((body or {}).get("name"))
    if not name or len(name) > 80:
        return _refuse("Please give it a short name.", 400)
    return JSONResponse(PROJECTS.create(name, _who(request)), status_code=201)


async def project_action(request):
    """{"name"} renames, {"active": true} switches to it, {"add": "file"} or {"drop": "file"} changes its contents."""
    pid, body = request.path_params["project_id"], await _json_body(request)
    if body is None:
        return _refuse("That request was not understood.", 400)
    if body.get("active"):
        return JSONResponse({"ok": True}) if PROJECTS.activate(pid, _who(request)) else _refuse("That project is not known.", 404)
    if "name" in body:
        name = core.clean_prompt(body.get("name"))
        if not name or len(name) > 80:
            return _refuse("Please give it a short name.", 400)
        view = PROJECTS.rename(pid, name)
        return JSONResponse(view) if view else _refuse("That project is not known.", 404)
    for key, fn in (("add", PROJECTS.add), ("drop", lambda n, p: PROJECTS.drop(p, n))):
        if key in body:
            path = core.safe_media_path(body[key])
            if path is None or path.parent != core.OUTPUT_DIR.resolve():
                return _refuse("That file is not in the output folder.", 400)
            return JSONResponse({"ok": True}) if fn(path.name, pid) else _refuse("That could not be changed.", 400)
    return _refuse("That request was not understood.", 400)


async def project_remove(request):
    if not _local_only(request):
        return _refuse("That request was not understood.", 400)
    return JSONResponse({"ok": True}) if PROJECTS.remove(request.path_params["project_id"]) else _refuse("The last project cannot be removed.", 400)


async def project_timeline(request):
    pid, body = request.path_params["project_id"], await _json_body(request)
    if body is None:
        return _refuse("That request was not understood.", 400)
    try:
        clean = await run_in_threadpool(studio.clean_timeline, body)
    except core.Invalid as e:
        return _refuse(str(e), 400)
    return JSONResponse(clean) if PROJECTS.set_timeline(pid, clean) else _refuse("That project is not known.", 404)


async def thumb(request):
    target = core.safe_media_path(request.path_params["path"])
    if target is None or target.suffix.lower() not in core.IMAGE_SUFFIXES | core.VIDEO_SUFFIXES:
        return _refuse("Not found.", 404)
    try:
        small = await run_in_threadpool(core.thumbnail_for, target)
    except (OSError, subprocess.TimeoutExpired):
        return _refuse("Not found.", 404)
    return FileResponse(small, headers={"Cache-Control": "max-age=86400"})


app = Starlette(
    routes=[
        Route("/", index),
        Route("/api/signin", signin, methods=["POST"]),
        Route("/api/signout", signout, methods=["POST"]),
        Route("/api/status", status),
        Route("/api/create", create, methods=["POST"]),
    Route("/api/estimate", estimate, methods=["POST"]),
        Route("/api/job/{job_id}", job),
        Route("/api/recipes", recipe_save, methods=["POST"]),
        Route("/api/recipes/{recipe_id}", recipe_delete, methods=["DELETE"]),
        Route("/api/item/{name}", item),
        Route("/api/preview", preview, methods=["POST"]),
        Route("/api/job/{job_id}/stop", job_stop, methods=["POST"]),
        Route("/api/gallery", gallery),
        Route("/api/favorite", favorite, methods=["POST"]),
        Route("/api/hide", hide, methods=["POST"]),
        Route("/api/enhance", enhance, methods=["POST"]),
        Route("/api/enhance/{job_id}", enhance_job),
        Route("/media/{path:path}", media),
        Route("/ui/{name}", ui_file),
        Route("/starters/{name}", starter_file),
        Route("/api/starters", starters),
        Route("/lift/{name}", lift),
        Route("/peaks/{name}", peaks),
        Route("/strip/{name}", strip),
        Route("/api/info/{name}", media_info),
        Route("/peek/{job_id}", peek),
        Route("/api/queue", queue),
        Route("/api/models", models),
        Route("/api/models/install", install, methods=["POST"]),
        Route("/api/models/stop", install_stop, methods=["POST"]),
        Route("/api/upload", upload, methods=["POST"]),
        Route("/api/projects", projects, methods=["GET", "POST"]),
        Route("/api/projects/{project_id}", project_action, methods=["POST"]),
        Route("/api/projects/{project_id}", project_remove, methods=["DELETE"]),
        Route("/api/projects/{project_id}/timeline", project_timeline, methods=["POST"]),
        Route("/thumb/{path:path}", thumb),
    ],
    middleware=[Middleware(NoSniff), Middleware(TrustedHostMiddleware, allowed_hosts=ALLOWED), Middleware(SignInGuard)],
    exception_handlers={Exception: _plain_500},
)


def _listen(host):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind((host, PORT))
    s.set_inheritable(True)
    return s


def main():
    core.GENERATION.resume(core.RUNNERS)  # anything the engine was doing for this screen before a restart
    core.ENHANCE.resume({"enhance": core.run_enhance})
    sockets = []
    for host in HOSTS:
        try:
            sockets.append(_listen(host))
            print(f"listening on http://{host}:{PORT}", flush=True)
        except OSError as e:
            print(f"could not listen on {host}:{PORT}: {e}", flush=True)
    if not sockets:
        raise SystemExit("no address could be bound")
    people = PEOPLE.listing()
    print(f"sign-in: {len(people)} passcode{'s' if len(people) != 1 else ''} in {auth.PEOPLE_FILE}"
          + ("" if people else "  (nobody can sign in until people.py add is run)"), flush=True)
    if EXTRA_HOSTS:
        print("also answering to the names: " + ", ".join(EXTRA_HOSTS), flush=True)
    uvicorn.Server(uvicorn.Config(app, log_level="warning")).run(sockets=sockets)


if __name__ == "__main__":
    main()
