#!/usr/bin/env python3
"""NeoVak REST API launcher: runs the HTTP server for local models and other computers on your own network."""
import math
import sys, os, shutil, re
from pathlib import Path
sys.path.insert(0, os.path.dirname(__file__))
os.chdir(os.path.dirname(__file__))

from neovak_server import (generate_image, generate_image_fast, edit_image_with_prompt,
                            upscale_image, generate_with_lora, check_models, list_presets,
                            open_editor, generate_speech, OUTPUT_DIR, QUEUE, RECIPES)

from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.middleware import Middleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.responses import JSONResponse as _StarletteJSON
from starlette.routing import Route
import uvicorn
from urllib.parse import urlsplit

from neovak_queue import secret
from neovak_queue.safe_text import ascii_json


class JSONResponse(_StarletteJSON):
    """Half of an emoji in something already saved must not stop a list from loading."""

    def render(self, content):
        return ascii_json(content)


# --- plates pipeline (typeset + motion) ------------------------------------- #
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "plates"))
import motion as plates_motion          # noqa: E402
import typeset as plates_typeset        # noqa: E402

REPO = Path(os.path.dirname(os.path.abspath(__file__)))
API_OUT = REPO / "plates" / "out" / "api"
MAX_API_FRAMES = 3600                   # 150 seconds at 24fps; a runaway-request guard


# Who may talk to this server: the names in the settings file ([hosts] engine), plus any in
# NEOVAK_EXTRA_HOSTS. It binds 127.0.0.1; a private network forwarder may give it more names, and those
# go in the settings. A page on another website, or a name made to point here, is refused.
from neovak_queue import settings as _settings  # noqa: E402
ALLOWED_HOSTS = _settings.load().engine_hosts


class WriteGuard:
    """Every request that changes something must be JSON from no origin or one of this server's own.
    Browsers always send Origin on a cross-site POST, and cannot send this content type without asking
    first, which this server never grants. Scripts on this machine send JSON and no Origin."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope["method"] in ("POST", "PUT", "PATCH", "DELETE"):
            headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}
            origin = headers.get("origin")
            refused = None
            if (origin and urlsplit(origin).hostname not in ALLOWED_HOSTS) or headers.get("sec-fetch-site") == "cross-site":
                refused = JSONResponse({"error": "Requests from other websites are not accepted."}, status_code=403)
            elif (headers.get("content-length", "0") != "0" or "transfer-encoding" in headers) and \
                    headers.get("content-type", "").split(";")[0].strip().lower() != "application/json":
                refused = JSONResponse({"error": "Please send a JSON object."}, status_code=415)
            if refused is not None:
                await refused(scope, receive, send)
                return
        await self.app(scope, receive, send)


class TokenGuard:
    """When a token is set (NEOVAK_TOKEN in the secrets file), every request but /health must carry it.
    The address is never trusted: Tailscale Serve forwards the tailnet to 127.0.0.1, so a request from
    across the network arrives looking local. With no token set, nothing changes, and /health says so."""

    def __init__(self, app):
        self.app = app
        self.token = secret.engine_token()

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and self.token and scope["path"] != "/health":
            headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}
            if not secret.matches(secret.presented(headers), self.token):
                refused = JSONResponse({"error": "This engine needs its access token. Send it as Authorization: Bearer."},
                                       status_code=401, headers={"Cache-Control": "no-store"})
                await refused(scope, receive, send)
                return
        await self.app(scope, receive, send)


def _has_token(request):
    return TOKEN is not None and secret.matches(secret.presented(request.headers), TOKEN)


TOKEN = secret.engine_token()


async def _plain_500(request, exc):
    return JSONResponse({"error": "That request could not be handled."}, status_code=500)


def _limit_arg(request, default):
    """?limit=, or the default when it is missing or is not a number."""
    try:
        return max(1, int(request.query_params.get("limit", default)))
    except ValueError:
        return default


async def _call(fn, **kw):
    # With the queue on, the old routes wait on a queue job; run them off the event loop so
    # /api/jobs status calls keep answering meanwhile. With it off, unchanged from before S1.
    if QUEUE is not None:
        return await run_in_threadpool(fn, **kw)
    return fn(**kw)

async def rest_generate(request):
    data = await request.json()
    return JSONResponse(await _call(generate_image, **{k: data[k] for k in data if k in
        ['prompt','style','size','model','steps','seed','quantize']}))

async def rest_generate_fast(request):
    data = await request.json()
    return JSONResponse(await _call(generate_image_fast, **{k: data[k] for k in data if k in
        ['prompt','style','size','seed']}))

def _answer(result):
    """A refusal from the tool itself (a picture outside the allowed folders, a missing file) is a 400, not a 200
    with an error inside it, so a caller that only looks at the status is not told it succeeded."""
    if isinstance(result, dict) and result.get("error") and not result.get("path") and not result.get("output"):
        return JSONResponse(result, status_code=400)
    return JSONResponse(result)

async def rest_edit(request):
    data = await request.json()
    return _answer(await _call(edit_image_with_prompt, **{k: data[k] for k in data if k in
        ['image_path','prompt','seed']}))

async def rest_upscale(request):
    data = await request.json()
    return _answer(await _call(upscale_image, **{k: data[k] for k in data if k in
        ['image_path','seed']}))

async def rest_presets(request):
    return JSONResponse(list_presets())

async def rest_speech(request):
    data = await request.json()
    return JSONResponse(await _call(generate_speech, **{k: data[k] for k in data if k in
        ['text','voice','speed','speaker']}))

async def rest_models(request):
    return JSONResponse(check_models())

async def rest_health(request):
    """Alive, and whether a token is needed. The folder names come only with the token when one is set."""
    body = {"status": "ok", "server": "NeoVak", "token": "required" if TOKEN else "off"}
    if TOKEN and not _has_token(request):
        return JSONResponse(body)
    body["output"] = str(OUTPUT_DIR)
    if QUEUE is not None:
        body["queue"] = {"worker_here": QUEUE.is_worker, "state_dir": str(QUEUE.dir)}
    return JSONResponse(body)


# --------------------------------------------------------------------------- #
# /api/typeset: text to an alpha PNG, through plates/typeset.py
# --------------------------------------------------------------------------- #
TYPESET_FIELDS = ['text','font','index','size','fill','tracking','leading','pad',
                  'shadow','shadow_off','shadow_blur','shadow_alpha','edge']


class PathRefused(Exception):
    """A path a caller sent that is outside the folders this server may use."""


def _write_roots():
    return [REPO / "plates" / "out", Path(OUTPUT_DIR)]


def _read_roots():
    extra = [Path(d) for d in os.environ.get("NEOVAK_SOURCE_DIRS", "").split(":") if d]
    return [REPO / "plates", REPO / "mark", Path(OUTPUT_DIR), *extra]


def _inside(path, roots, what):
    """The real path, after links are followed, when it is inside one of roots. Relative means relative to the repo."""
    if not isinstance(path, (str, Path)) or not str(path) or "\x00" in str(path):
        raise PathRefused(f"{what} has to be a path.")
    real = (Path(path) if Path(path).is_absolute() else REPO / path).resolve()
    if not any(real.is_relative_to(root.resolve()) for root in roots):
        raise PathRefused(f"{what} is outside the folders NeoVak may use.")
    return real


def _frames_folder(path):
    """This folder is emptied before a render, so only a folder strictly inside plates/out is accepted."""
    real = _inside(path, [REPO / "plates" / "out"], "'frames_dir'")
    if real == (REPO / "plates" / "out").resolve():
        raise PathRefused("'frames_dir' has to be a folder inside plates/out.")
    return real


def _font_allowed(font):
    if font is not None:
        _inside(font, [Path("/System/Library/Fonts"), Path("/Library/Fonts"), Path.home() / "Library" / "Fonts", REPO / "plates"], "'font'")


def _check_layers(tl):
    """Every file a timeline's layers would open. A sequence may be a folder, a glob or a printf pattern, so its
    fixed start is what is checked, and it may not climb back out afterwards."""
    for layer in tl["layers"]:
        kind = layer.get("type", "image")
        if kind == "type":
            _font_allowed(layer.get("font"))
        elif kind in ("image", "alpha_image") and layer.get("src"):
            _inside(layer["src"], _read_roots(), "A layer's 'src'")
        elif kind == "sequence" and layer.get("src"):
            if not isinstance(layer["src"], str):
                raise PathRefused("A layer's 'src' has to be a path.")
            parts = Path(layer["src"]).parts
            cut = next((i for i, part in enumerate(parts) if re.search(r"[*?\[%]", part)), len(parts))
            if ".." in parts[cut:]:
                raise PathRefused("A layer's 'src' is outside the folders NeoVak may use.")
            _inside(str(Path(*parts[:cut])) if cut else ".", _read_roots(), "A layer's 'src'")

def _typeset_job(data):
    from PIL import Image
    spec = {k: data[k] for k in data if k in TYPESET_FIELDS}
    if not spec.get("text"):
        return {"error": "'text' is required"}, 400
    _font_allowed(spec.get("font"))
    dest = _inside(data["out"], _write_roots(), "'out'") if data.get("out") else None  # before anything is drawn or written
    # Renders through the same cache the motion engine uses, so an identical
    # spec asked for twice costs one render.
    src = plates_motion.typeset_png(spec)
    if dest:
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dest)
    else:
        API_OUT.mkdir(parents=True, exist_ok=True)
        dest = API_OUT / src.name
        if dest != src:
            shutil.copyfile(src, dest)
    img = Image.open(dest)
    return {
        "path": str(dest),
        "cached_path": str(src),
        "width": img.width, "height": img.height,
        "mode": img.mode,
        "text": spec["text"],
        "font": spec.get("font", plates_typeset.DFONT),
        "index": int(spec.get("index", 6)),
        "size": int(spec.get("size", 160)),
        "fill": spec.get("fill", "#ece6d6"),
    }, 200

async def rest_typeset(request):
    try:
        data = await request.json()
    except Exception:
        return JSONResponse({"error": "body must be a JSON object"}, status_code=400)
    if not isinstance(data, dict):
        return JSONResponse({"error": "body must be a JSON object"}, status_code=400)
    try:
        body, code = await run_in_threadpool(_typeset_job, data)
    except (plates_motion.TimelineError, PathRefused) as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    except FileNotFoundError as e:
        return JSONResponse({"error": f"font or output path not found: {e}"}, status_code=400)
    except Exception as e:
        return JSONResponse({"error": f"typeset failed: {type(e).__name__}: {e}"},
                            status_code=500)
    return JSONResponse(body, status_code=code)


# --------------------------------------------------------------------------- #
# /api/motion: a timeline JSON to frames and an mp4, through plates/motion.py
# --------------------------------------------------------------------------- #
def _motion_job(data):
    if "timeline" in data:
        tl = data["timeline"]
    elif "timeline_path" in data:
        tl = plates_motion.load_timeline(_inside(data["timeline_path"], _read_roots(), "'timeline_path'"))
    else:
        tl = data                       # the body itself is the timeline
    tl = plates_motion.validate(tl)
    _check_layers(tl)

    total = int(round(float(tl["fps"]) * float(tl["duration"])))
    requested = data.get("max_frames")
    n = total if requested is None else min(total, int(requested))
    if n > MAX_API_FRAMES:
        return {"error": f"timeline resolves to {n} frames, over the API limit of "
                         f"{MAX_API_FRAMES}. Send 'max_frames', or render locally "
                         f"with plates/motion.py."}, 400

    # The defaults are built from the timeline's own name, so they are checked as well.
    name = str(tl.get("name", "motion"))
    out = _inside(data["out"] if data.get("out") is not None else API_OUT / f"{name}.mp4", _write_roots(), "'out'")
    frames_dir = _frames_folder(data.get("frames_dir") or tl.get("frames_dir") or f"plates/out/_{name}_frames")
    API_OUT.mkdir(parents=True, exist_ok=True)
    r = plates_motion.render(
        tl,
        max_frames=requested,
        make_video=bool(data.get("video", True)),
        out=out,
        frames_dir=frames_dir,
    )
    return r, 200

async def rest_motion(request):
    try:
        data = await request.json()
    except Exception:
        return JSONResponse({"error": "body must be a JSON object"}, status_code=400)
    if not isinstance(data, dict):
        return JSONResponse({"error": "body must be a JSON object"}, status_code=400)
    try:
        body, code = await run_in_threadpool(_motion_job, data)
    except (plates_motion.TimelineError, PathRefused) as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    except (KeyError, ValueError, TypeError) as e:
        return JSONResponse({"error": f"bad timeline: {type(e).__name__}: {e}"},
                            status_code=400)
    except Exception as e:
        return JSONResponse({"error": f"motion failed: {type(e).__name__}: {e}"},
                            status_code=500)
    return JSONResponse(body, status_code=code)


async def rest_motion_schema(request):
    """The timeline field reference, so a client does not have to guess."""
    return JSONResponse({
        "schema": plates_motion.__doc__,
        "eases": sorted(plates_motion.EASES),
        "layer_types": ["image", "alpha_image", "type", "sequence"],
        "blend_modes": sorted(plates_motion.KNOWN_BLENDS),
        "animatable": sorted(plates_motion.PROP_DEFAULTS),
        "max_frames": MAX_API_FRAMES,
        "example": "plates/examples/this_machine_open.json",
    })


# --------------------------------------------------------------------------- #
# /api/jobs: the S1 job queue (only when NEOVAK_QUEUE=1; see neovak_server.py)
#   POST /api/jobs                  {"lane"|"adapter", "params"} -> job (202)
#   GET  /api/jobs?state=&lane=&limit=   recent jobs, newest first
#   GET  /api/jobs/adapters         lanes, adapters, parameters, models
#   POST /api/jobs/estimate         {"adapter"|"lane", "params"} -> the time such a job would be expected to take
#   GET  /api/jobs/{id}             state, progress, result
#   POST /api/jobs/{id}/cancel      (DELETE /api/jobs/{id} does the same)
# --------------------------------------------------------------------------- #
async def rest_jobs(request):
    if request.method == "GET":
        q = request.query_params
        return JSONResponse({"jobs": QUEUE.list(state=q.get("state"), lane=q.get("lane"),
                                                limit=_limit_arg(request, 50)),
                             "worker_here": QUEUE.is_worker})
    try:
        data = await request.json()
    except Exception:
        return JSONResponse({"error": "body must be a JSON object"}, status_code=400)
    if not isinstance(data, dict):
        return JSONResponse({"error": "body must be a JSON object"}, status_code=400)
    from neovak_queue.adapters import AdapterError
    from neovak_queue.queue import LineFull
    wait = data.get("wait_for_memory")
    if isinstance(wait, float) and not math.isfinite(wait):
        return JSONResponse({"error": "wait_for_memory must be a number of seconds"}, status_code=400)
    try:
        context = {"wait_for_memory": max(0, min(3600, int(wait)))} if isinstance(wait, (int, float)) else None
        job = QUEUE.submit(data.get("adapter"), data.get("params") if data.get("params") is not None else {},
                           client=data.get("client", "rest"), lane=data.get("lane"), context=context)
    except RecursionError:
        return JSONResponse({"error": "body is nested too deeply"}, status_code=400)
    except LineFull as e:
        return JSONResponse({"error": str(e)}, status_code=429)
    except AdapterError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    return JSONResponse(job, status_code=202)

async def rest_job(request):
    job_id = request.path_params["job_id"]
    v = QUEUE.cancel(job_id) if request.method == "DELETE" else QUEUE.status(job_id)
    return JSONResponse(v, status_code=404 if v.get("state") == "not_found" else 200)

async def rest_job_cancel(request):
    v = QUEUE.cancel(request.path_params["job_id"])
    return JSONResponse(v, status_code=404 if v.get("state") == "not_found" else 200)

async def rest_job_adapters(request):
    return JSONResponse(QUEUE.describe())

async def rest_job_estimate(request):
    """POST {"adapter"|"lane", "params"}: how long such a job would be expected to take, from this queue's own
    history for those settings or the adapter's measured table. Nothing is submitted and nothing is written."""
    try:
        data = await request.json()
    except Exception:
        return JSONResponse({"error": "body must be a JSON object"}, status_code=400)
    if not isinstance(data, dict):
        return JSONResponse({"error": "body must be a JSON object"}, status_code=400)
    from neovak_queue.adapters import AdapterError
    try:
        view = await run_in_threadpool(QUEUE.estimate, data.get("adapter"), data.get("params"), data.get("lane"))
    except RecursionError:
        return JSONResponse({"error": "body is nested too deeply"}, status_code=400)
    except AdapterError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    return JSONResponse(view)

# --------------------------------------------------------------------------- #
# /api/recipes, /api/recipe-runs, /api/provenance: step S3 (queue on only)
#   GET  /api/recipes                list, with each one's plan
#   POST /api/recipes                {"recipe": {...}} or {"from": id, "name": ..., "values": {...}}
#   GET|DELETE /api/recipes/{id}
#   POST /api/recipes/{id}/run       {"values": {...}} -> run (202)
#   GET  /api/recipe-runs?limit=     newest first
#   GET  /api/recipe-runs/{id}
#   POST /api/recipe-runs/{id}/cancel
#   GET  /api/provenance/{file name}          the sidecar beside that output
#   POST /api/provenance/{file name}/remake   {"new_seed": false} -> job (202)
# --------------------------------------------------------------------------- #
async def _s3_body(request):
    """JSON only: a page on another site cannot send this content type without being asked first."""
    if request.headers.get("content-type", "").split(";")[0].strip() != "application/json":
        return None
    try:
        body = await request.json()
    except Exception:
        return None
    return body if isinstance(body, dict) else None

def _s3_error(message, code=400):
    return JSONResponse({"error": message}, status_code=code)

async def rest_recipes(request):
    from neovak_queue.recipes import RecipeError
    if request.method == "GET":
        return JSONResponse({"recipes": await run_in_threadpool(RECIPES.list)})
    body = await _s3_body(request)
    if body is None:
        return _s3_error("Please send a JSON object.")
    try:
        if body.get("from"):
            saved = RECIPES.save_copy(body["from"], body.get("name"), body.get("values") or {})
        else:
            saved = RECIPES.save(body.get("recipe"))
    except RecipeError as e:
        return _s3_error(str(e))
    return JSONResponse(saved, status_code=201)

async def rest_recipe(request):
    from neovak_queue.recipes import RecipeError
    rid = request.path_params["recipe_id"]
    if request.method == "DELETE":
        try:
            gone = RECIPES.delete(rid)
        except RecipeError as e:
            return _s3_error(str(e), 403)
        return JSONResponse({"deleted": rid}) if gone else _s3_error("That recipe is not in the book.", 404)
    recipe = await run_in_threadpool(RECIPES.get, rid)
    return JSONResponse(RECIPES.describe(recipe)) if recipe else _s3_error("That recipe is not in the book.", 404)

async def rest_recipe_plan(request):
    """The plan for the values typed so far, so the time before the press follows them. Nothing is started."""
    body = await _s3_body(request)
    if body is None:
        return _s3_error("Please send a JSON object.")
    recipe = await run_in_threadpool(RECIPES.get, request.path_params["recipe_id"])
    if not recipe:
        return _s3_error("That recipe is not in the book.", 404)
    return JSONResponse({"plan": await run_in_threadpool(RECIPES.plan_for, recipe, body.get("values"))})

async def rest_recipe_run(request):
    from neovak_queue.recipes import RecipeError
    body = await _s3_body(request)
    if body is None:
        return _s3_error("Please send a JSON object.")
    try:
        run = await run_in_threadpool(RECIPES.start, request.path_params["recipe_id"], body.get("values") or {}, None, body.get("client", "rest"))
    except RecipeError as e:
        return _s3_error(str(e))
    return JSONResponse(run, status_code=202)

async def rest_recipe_runs(request):
    return JSONResponse({"runs": await run_in_threadpool(RECIPES.list_runs, _limit_arg(request, 20))})

async def rest_recipe_run_status(request):
    v = await run_in_threadpool(RECIPES.status, request.path_params["run_id"])
    return JSONResponse(v) if v else _s3_error("That run is not known.", 404)

async def rest_recipe_run_cancel(request):
    v = await run_in_threadpool(RECIPES.cancel, request.path_params["run_id"])
    return JSONResponse(v) if v else _s3_error("That run is not known.", 404)

async def rest_provenance(request):
    from neovak_queue import provenance
    found = provenance.read(OUTPUT_DIR, request.path_params["name"])
    return JSONResponse(found) if found else _s3_error("No record is kept beside that file.", 404)

async def rest_provenance_remake(request):
    from neovak_queue import provenance
    from neovak_queue.adapters import AdapterError
    body = await _s3_body(request)
    if body is None:
        return _s3_error("Please send a JSON object.")
    found = provenance.read(OUTPUT_DIR, request.path_params["name"])
    if not found:
        return _s3_error("No record is kept beside that file.", 404)
    try:
        adapter, params = provenance.remake_request(found, OUTPUT_DIR, new_seed=bool(body.get("new_seed")))
        job = QUEUE.submit(adapter, params, client=body.get("client", "rest"), context={"remake_of": found.get("file")})
    except (ValueError, AdapterError) as e:
        return _s3_error(str(e), 409)
    return JSONResponse(job, status_code=202)

JOB_ROUTES = [
    Route("/api/recipes", rest_recipes, methods=["GET", "POST"]),
    Route("/api/recipes/{recipe_id}", rest_recipe, methods=["GET", "DELETE"]),
    Route("/api/recipes/{recipe_id}/run", rest_recipe_run, methods=["POST"]),
    Route("/api/recipes/{recipe_id}/plan", rest_recipe_plan, methods=["POST"]),
    Route("/api/recipe-runs", rest_recipe_runs),
    Route("/api/recipe-runs/{run_id}", rest_recipe_run_status),
    Route("/api/recipe-runs/{run_id}/cancel", rest_recipe_run_cancel, methods=["POST"]),
    Route("/api/provenance/{name}", rest_provenance),
    Route("/api/provenance/{name}/remake", rest_provenance_remake, methods=["POST"]),
    Route("/api/jobs", rest_jobs, methods=["GET", "POST"]),
    Route("/api/jobs/adapters", rest_job_adapters),
    Route("/api/jobs/estimate", rest_job_estimate, methods=["POST"]),
    Route("/api/jobs/{job_id}", rest_job, methods=["GET", "DELETE"]),
    Route("/api/jobs/{job_id}/cancel", rest_job_cancel, methods=["POST"]),
    Route("/api/upscale", rest_upscale, methods=["POST"]),
] if QUEUE is not None else []


app = Starlette(middleware=[Middleware(TrustedHostMiddleware, allowed_hosts=ALLOWED_HOSTS), Middleware(TokenGuard), Middleware(WriteGuard)],
                exception_handlers={Exception: _plain_500}, routes=JOB_ROUTES + [
    Route("/api/generate", rest_generate, methods=["POST"]),
    Route("/api/generate/fast", rest_generate_fast, methods=["POST"]),
    Route("/api/edit", rest_edit, methods=["POST"]),
    Route("/api/speech", rest_speech, methods=["POST"]),
    Route("/api/typeset", rest_typeset, methods=["POST"]),
    Route("/api/motion", rest_motion, methods=["POST"]),
    Route("/api/motion/schema", rest_motion_schema),
    Route("/api/presets", rest_presets),
    Route("/api/models", rest_models),
    Route("/health", rest_health),
])

if __name__ == "__main__":
    # NEOVAK_PORT lets a test copy run beside the live service (S1 used 8101).
    port = int(os.environ.get("NEOVAK_PORT", "8100"))
    print(f"NeoVak REST API on http://localhost:{port}")
    if QUEUE is not None:
        print(f"  Jobs:      /api/jobs  (state in {QUEUE.dir}, worker here: {QUEUE.is_worker})")
    print(f"  Names:     {', '.join(ALLOWED_HOSTS)}  (bound to 127.0.0.1; a private network forwarder may add names in the settings file)")
    print(f"  Token:     {'required on every route but /health' if TOKEN else 'none set, so anyone who can reach this port can call it'}  ({secret.ENV_FILE})")
    print(f"  Output:    {OUTPUT_DIR}")
    print(f"  Plates:    {API_OUT}")
    uvicorn.run(app, host="127.0.0.1", port=port)
