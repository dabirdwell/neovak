"""Recipes: a saved set of steps, each step one job on the queue.

The format is one JSON object (ruling of 2026-09-10, "Recipes"):

  {"schema": 1, "id": "...", "name": "...", "description": "...",
   "inputs": [{"name": "picture", "label": "Describe the picture", "type": "long_text",
               "tier": "basic", "required": true, "default": "", "place": "..."}],
   "steps": [{"id": "picture", "label": "Make the picture", "adapter": "mflux", "about_seconds": 25,
              "params": {"prompt": "{{picture}}", "seed": "{{seed}}"}},
             {"id": "clip", "label": "Set it moving", "adapter": "ltx-video",
              "params": {"source": "{{steps.picture.file}}", "prompt": "{{motion}}"}}]}

A parameter is bound to an adapter parameter, never to an engine's internals. {{name}} is an input;
{{steps.ID.file}}, .seed or .text is what an earlier step made. Substitution is one pass over the
recipe's own text, so words a person types are never read as references. A value that is the whole
string keeps its type (a seed stays a number).

Input types: text, long_text, number, choice, seed. Tiers: basic, advanced, expert.

A run is a small state machine on disk (<state>/runs/<id>.json). Whichever process holds the
queue's worker lock advances every run once a second, so a run survives a restart of the engine
just as its jobs do. Other processes may start, read and cancel runs.

While a run waits, it says what for: memory (a step the model governor refused is tried again for
up to an hour, and nothing goes around the governor) or the nightly job (the window named in the settings file,
when a step that loads a model is held back, including one that would still be running then).
"""
import fcntl
import json
import os
import re
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from . import provenance
from . import settings as _settings
from .adapters.base import AdapterError

SCHEMA = 1
TIERS = ("basic", "advanced", "expert")
INPUT_TYPES = ("text", "long_text", "number", "choice", "seed")
STEP_OUTPUTS = ("file", "seed", "text")
MAX_STEPS, MAX_INPUTS, MAX_TEXT = 8, 20, 6000
FINAL = ("done", "failed", "cancelled")
SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
INPUT_NAME = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
STEP_ID = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
RUN_ID = re.compile(r"^r-[0-9]{8}-[0-9]{6}-[0-9a-f]{6}$")
REF = re.compile(r"\{\{\s*([A-Za-z0-9_.]+)\s*\}\}")
NO_GO_MARK = "model governor said NO-GO"
MEMORY_WAIT_SECONDS = 3600
MEMORY_RETRY_SECONDS = 60


class RecipeError(Exception):
    """A problem a person can read."""


def hold_reason(estimate_seconds=0, now=None):
    """The nightly window from the settings file, or a job that would still be running when it opens.
    A machine with no window in its settings never waits."""
    return _settings.load().hold_reason(estimate_seconds, now)


def _refs(value):
    if isinstance(value, str):
        return REF.findall(value)
    return []


def substitute(value, inputs, outputs):
    """One pass only. Inputs and earlier steps' outputs go in as data, and are not read again."""
    if not isinstance(value, str):
        return value

    def look_up(ref):
        parts = ref.split(".")
        if parts[0] == "steps":
            if len(parts) != 3 or parts[1] not in outputs or parts[2] not in STEP_OUTPUTS:
                raise RecipeError(f"This recipe refers to {ref}, which no earlier step made.")
            found = outputs[parts[1]].get(parts[2])
            if found is None:
                raise RecipeError(f"The step {parts[1]} did not produce a {parts[2]}.")
            return found
        if len(parts) != 1 or ref not in inputs:
            raise RecipeError(f"This recipe refers to {ref}, which it does not ask for.")
        return inputs[ref]
    whole = REF.fullmatch(value.strip())
    if whole:
        return look_up(whole.group(1))
    return REF.sub(lambda m: str(look_up(m.group(1))), value)


def _plain(value, limit, what):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise RecipeError(f"{what} is needed, in under {limit} characters.")
    return value.strip()


def check_recipe(raw, adapters):
    """Returns a clean copy of a recipe, or raises RecipeError in a plain sentence."""
    if not isinstance(raw, dict):
        raise RecipeError("A recipe has to be a JSON object.")
    if raw.get("schema", SCHEMA) != SCHEMA:
        raise RecipeError(f"This recipe is in a format this version cannot read (it reads format {SCHEMA}).")
    name = _plain(raw.get("name"), 80, "A name")
    description = raw.get("description") or ""
    if not isinstance(description, str) or len(description) > 400:
        raise RecipeError("The description has to be under 400 characters.")
    inputs, seen = [], set()
    raw_inputs = raw.get("inputs") or []
    if not isinstance(raw_inputs, list) or len(raw_inputs) > MAX_INPUTS:
        raise RecipeError(f"A recipe can ask for at most {MAX_INPUTS} things.")
    for item in raw_inputs:
        if not isinstance(item, dict) or not INPUT_NAME.match(str(item.get("name") or "")):
            raise RecipeError("Every input needs a short name in lower case letters.")
        if item["name"] in seen:
            raise RecipeError(f"The input {item['name']} is listed twice.")
        seen.add(item["name"])
        kind = item.get("type") or "text"
        tier = item.get("tier") or "basic"
        if kind not in INPUT_TYPES:
            raise RecipeError(f"{item['name']}: the type has to be one of {', '.join(INPUT_TYPES)}.")
        if tier not in TIERS:
            raise RecipeError(f"{item['name']}: the tier has to be basic, advanced or expert.")
        clean = {"name": item["name"], "label": _plain(item.get("label") or item["name"], 80, "A label"), "type": kind, "tier": tier,
                 "required": bool(item.get("required")), "default": item.get("default"), "help": str(item.get("help") or "")[:200],
                 "place": str(item.get("place") or "")[:200]}
        if kind == "choice":
            choices = item.get("choices")
            if not isinstance(choices, list) or not choices or not all(isinstance(c, dict) and "value" in c and "label" in c for c in choices):
                raise RecipeError(f"{item['name']}: a choice needs a list of values and labels.")
            clean["choices"] = [{"value": c["value"], "label": str(c["label"])[:60]} for c in choices]
            if clean["default"] is None:
                clean["default"] = clean["choices"][0]["value"]
            if clean["default"] not in [c["value"] for c in clean["choices"]]:
                raise RecipeError(f"{item['name']}: its default is not one of its choices.")
        if kind == "number":
            for key in ("min", "max"):
                if key in item:
                    if not isinstance(item[key], (int, float)):
                        raise RecipeError(f"{item['name']}: {key} has to be a number.")
                    clean[key] = item[key]
        inputs.append(clean)
    raw_steps = raw.get("steps")
    if not isinstance(raw_steps, list) or not 1 <= len(raw_steps) <= MAX_STEPS:
        raise RecipeError(f"A recipe needs between 1 and {MAX_STEPS} steps.")
    steps, earlier = [], {}
    for item in raw_steps:
        if not isinstance(item, dict) or not STEP_ID.match(str(item.get("id") or "")):
            raise RecipeError("Every step needs a short id in lower case letters.")
        sid = item["id"]
        if sid in earlier:
            raise RecipeError(f"The step {sid} is listed twice.")
        adapter = adapters.get(item.get("adapter"))
        if adapter is None:
            raise RecipeError(f"{sid}: NeoVak has no engine called {item.get('adapter')}.")
        params = item.get("params")
        if not isinstance(params, dict):
            raise RecipeError(f"{sid}: its settings have to be a JSON object.")
        unknown = sorted(set(params) - set(adapter.params))
        if unknown:
            raise RecipeError(f"{sid}: {adapter.name} has no setting called {', '.join(unknown)}.")
        for key, value in params.items():
            if not isinstance(value, (str, int, float, bool, type(None))):
                raise RecipeError(f"{sid}: {key} has to be a single value.")
            for ref in _refs(value):
                parts = ref.split(".")
                if parts[0] == "steps":
                    if len(parts) != 3 or parts[2] not in STEP_OUTPUTS:
                        raise RecipeError(f"{sid}: {ref} is not something a step can make.")
                    if parts[1] not in earlier:
                        raise RecipeError(f"{sid}: {ref} refers to a step that has not happened yet.")
                    if parts[2] == "text" and earlier[parts[1]] != "text":
                        raise RecipeError(f"{sid}: {ref} refers to a step that does not write words.")
                elif len(parts) != 1 or ref not in seen:
                    raise RecipeError(f"{sid}: {ref} is not one of this recipe's inputs.")
        steps.append({"id": sid, "label": _plain(item.get("label") or sid, 80, "A step label"), "adapter": adapter.name, "params": params,
                      "about_seconds": item.get("about_seconds") if isinstance(item.get("about_seconds"), (int, float)) else None})
        earlier[sid] = adapter.lane
    out = {"schema": SCHEMA, "name": name, "description": description, "inputs": inputs, "steps": steps}
    if raw.get("id") is not None:
        if not isinstance(raw["id"], str) or not SLUG.match(raw["id"]):
            raise RecipeError("A recipe id is lower case letters, digits and dashes.")
        out["id"] = raw["id"]
    if isinstance(raw.get("order"), int):
        out["order"] = raw["order"]
    if isinstance(raw.get("based_on"), str):
        out["based_on"] = raw["based_on"][:64]
    return out


def _clean_values(recipe, values):
    """Each input's value, checked; blank means its default. A blank seed is chosen here and kept."""
    if not isinstance(values, dict):
        raise RecipeError("The values have to be a JSON object.")
    known = {i["name"] for i in recipe["inputs"]}
    unknown = sorted(set(values) - known)
    if unknown:
        raise RecipeError(f"This recipe does not ask for {', '.join(unknown)}.")
    out = {}
    for spec in recipe["inputs"]:
        value = values.get(spec["name"], spec.get("default"))
        if value in (None, "") and spec.get("default") not in (None, ""):
            value = spec["default"]
        kind, label = spec["type"], spec["label"]
        if kind == "seed":
            if value in (None, "", -1):
                value = int.from_bytes(os.urandom(4), "big") % 2 ** 31
            try:
                value = int(value)
            except (TypeError, ValueError):
                raise RecipeError(f"{label} has to be a whole number.")
            if not 0 <= value < 2 ** 32:
                raise RecipeError(f"{label} is out of range.")
        elif kind == "number":
            try:
                value = float(value) if value not in (None, "") else None
            except (TypeError, ValueError):
                raise RecipeError(f"{label} has to be a number.")
            if value is None and spec["required"]:
                raise RecipeError(f"Please fill in: {label}.")
            if value is not None:
                if ("min" in spec and value < spec["min"]) or ("max" in spec and value > spec["max"]):
                    raise RecipeError(f"{label} has to be between {spec.get('min')} and {spec.get('max')}.")
                value = int(value) if value == int(value) else value
        elif kind == "choice":
            if value not in [c["value"] for c in spec["choices"]]:
                raise RecipeError(f"Please pick one of the listed choices for {label}.")
        else:
            value = "" if value is None else value
            if not isinstance(value, str):
                raise RecipeError(f"{label} has to be text.")
            # A leading dash would be read by an engine as one of its own options.
            value = value.strip().lstrip("- ").strip()
            if len(value) > MAX_TEXT:
                raise RecipeError(f"{label} is too long. Please keep it under {MAX_TEXT} characters.")
            if spec["required"] and not value:
                raise RecipeError(f"Please fill in: {label}.")
        out[spec["name"]] = value
    return out


class RecipeBook:
    def __init__(self, queue, builtin_dir, tick_seconds=1.0, start=True, clock=time.time, memory_wait=MEMORY_WAIT_SECONDS,
                 memory_retry=MEMORY_RETRY_SECONDS, hold=hold_reason):
        self.queue = queue
        self.builtin_dir = Path(builtin_dir)
        self.saved_dir = queue.dir / "recipes"
        self.runs_dir = queue.dir / "runs"
        self.active_dir = self.runs_dir / "active"
        for d in (self.saved_dir, self.active_dir):
            d.mkdir(parents=True, exist_ok=True)
        self.clock, self.memory_wait, self.memory_retry, self.hold = clock, memory_wait, memory_retry, hold
        self.tick_seconds = tick_seconds
        self._tlock = threading.Lock()
        self._stop = threading.Event()
        self.thread = None
        if start:
            self.thread = threading.Thread(target=self._loop, name="neovak-recipes", daemon=True)
            self.thread.start()

    def stop(self):
        self._stop.set()
        if self.thread:
            self.thread.join(10)

    # ================================================================ the book
    def _builtin(self):
        found = {}
        for path in sorted(self.builtin_dir.glob("*.json")):
            try:
                recipe = check_recipe(json.loads(path.read_text()), self.queue.adapters)
            except (OSError, json.JSONDecodeError, RecipeError):
                continue
            recipe.update(id=path.stem, builtin=True)
            found[path.stem] = recipe
        return found

    def _saved(self):
        found = {}
        for path in sorted(self.saved_dir.glob("*.json")):
            try:
                recipe = check_recipe(json.loads(path.read_text()), self.queue.adapters)
            except (OSError, json.JSONDecodeError, RecipeError):
                continue
            recipe.update(id=path.stem, builtin=False)
            found[path.stem] = recipe
        return found

    def _all(self):
        found = self._builtin()
        found.update(self._saved())
        return found

    def get(self, recipe_id):
        return self._all().get(recipe_id)

    def _plan(self, recipe, values):
        """What the recipe will need, read from the adapters with nothing submitted. A step that
        depends on an earlier one is measured without those settings."""
        total, largest = 0, 0
        steps = []
        for step in recipe["steps"]:
            adapter = self.queue.adapters[step["adapter"]]
            params = {}
            for key, value in step["params"].items():
                if not any(r.startswith("steps.") for r in _refs(value)):
                    try:
                        params[key] = substitute(value, values, {})
                    except RecipeError:
                        pass
            estimate, gb = step.get("about_seconds"), 0
            try:
                gb = adapter.memory_gb(params) or 0
            except Exception:  # noqa: BLE001
                gb = 0
            # The same figure the queue gives the job once it is submitted (_expected: history for these settings, a
            # warm run plus a load, else the adapter's table), so the time before the press and during the run agree.
            # Words not typed yet, or written by an earlier step, are stood in for by a placeholder: they do not change
            # which settings the time is measured for.
            for trial in (dict(params), self._stand_ins(adapter, params)):
                try:
                    seconds, _basis = self.queue._expected(adapter, adapter.validate(trial))
                except Exception:  # noqa: BLE001  a step that needs an earlier step's file cannot be validated yet
                    continue
                if seconds:
                    estimate = seconds
                    break
            else:
                try:
                    estimate = adapter.default_estimate(params) or estimate
                except Exception:  # noqa: BLE001
                    pass
            total += estimate or 30
            if isinstance(gb, dict):  # a writer in LM Studio: its figure, with the model named for the governor
                largest = max(largest, gb.get("gb") or 0)
            elif isinstance(gb, (int, float)):
                largest = max(largest, gb)
            elif gb == "9b":
                largest = max(largest, 10)
            elif gb == "27b":
                largest = max(largest, 38)
            # the kind of work the step does (a picture, a clip, a voice, words, a joining), so a screen can draw it
            kind = "join" if adapter.name in ("join-sound", "timeline") else getattr(adapter, "lane", None)
            steps.append({"id": step["id"], "label": step["label"], "memory_gb": gb, "estimate_seconds": estimate, "kind": kind})
        return {"estimate_seconds": round(total), "memory_gb": largest, "steps": steps}

    @staticmethod
    def _stand_ins(adapter, params):
        """params with a short placeholder in every text setting that is empty or not known yet."""
        trial = dict(params)
        for key, spec in adapter.params.items():
            if spec.get("type", "str") == "str" and not str(trial.get(key) or "").strip() and "choices" not in spec \
                    and not str(spec.get("default") or "").strip():
                trial[key] = "a lighthouse at dusk"
        return trial

    def describe(self, recipe):
        defaults = {i["name"]: i.get("default") for i in recipe["inputs"]}
        return dict(recipe, plan=self._plan(recipe, {k: v for k, v in defaults.items() if v is not None}))

    def plan_for(self, recipe, values):
        """The plan for the values typed so far (a 2 second clip is timed as one), measured the way describe measures
        the defaults. A value that would be refused at the press is left at its default here, and nothing runs."""
        values = values if isinstance(values, dict) else {}
        defaults = {i["name"]: i.get("default") for i in recipe["inputs"]}
        merged = {k: v for k, v in defaults.items() if v is not None}
        for spec in recipe["inputs"]:
            v = values.get(spec["name"])
            if v in (None, "") or isinstance(v, (dict, list, bool)):
                continue
            if spec["type"] == "choice":  # "2" from a form names the same choice as 2
                v = next((c["value"] for c in spec["choices"] if str(c["value"]) == str(v)), v)
            try:
                checked = _clean_values({"inputs": [dict(spec, required=False)]}, {spec["name"]: v})
            except RecipeError:
                continue
            if checked.get(spec["name"]) not in (None, ""):
                merged[spec["name"]] = checked[spec["name"]]
        return self._plan(recipe, merged)

    def list(self):
        # The recipes that come with NeoVak first, in their own order, then the ones people saved, by name.
        return [self.describe(r) for r in sorted(self._all().values(), key=lambda r: (0 if r.get("builtin") else 1, r.get("order", 50), r["name"].lower()))]

    def save(self, raw, new_id=None):
        """Saves a recipe of its own. A built-in recipe can be copied but never replaced."""
        recipe = check_recipe(raw, self.queue.adapters)
        wanted = new_id or recipe.get("id") or re.sub(r"[^a-z0-9]+", "-", recipe["name"].lower()).strip("-")[:48] or "recipe"
        if not SLUG.match(wanted):
            raise RecipeError("A recipe id is lower case letters, digits and dashes.")
        builtin = self._builtin()
        chosen, n = wanted, 1
        while chosen in builtin or (new_id is None and raw.get("id") is None and (self.saved_dir / f"{chosen}.json").exists()):
            n += 1
            chosen = f"{wanted}-{n}"
        recipe["id"] = chosen
        self.queue._atomic(self.saved_dir / f"{chosen}.json", recipe)
        return self.describe(dict(self.get(chosen)))

    def save_copy(self, from_id, name, values):
        """A person's own defaults over an existing recipe."""
        base = self.get(from_id)
        if base is None:
            raise RecipeError("That recipe is not in the book.")
        given = {k: v for k, v in (values or {}).items() if v not in (None, "")}
        checked = _clean_values(dict(base, inputs=[i for i in base["inputs"] if i["name"] in given]), given)
        copy = json.loads(json.dumps(base))
        copy.pop("id", None); copy.pop("builtin", None)
        copy["name"], copy["based_on"] = name, from_id
        for spec in copy["inputs"]:
            if spec["name"] in given:
                spec["default"] = checked[spec["name"]]
        return self.save(copy)

    def delete(self, recipe_id):
        if recipe_id in self._builtin():
            raise RecipeError("That recipe comes with NeoVak and cannot be removed.")
        if not SLUG.match(recipe_id or ""):
            return False
        path = self.saved_dir / f"{recipe_id}.json"
        if not path.exists():
            return False
        path.unlink()
        return True

    # ================================================================ runs
    @contextmanager
    def _locked(self):
        with self._tlock:
            with open(self.runs_dir / "runs.lock", "a") as fh:
                fcntl.flock(fh, fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    fcntl.flock(fh, fcntl.LOCK_UN)

    def _path(self, run_id):
        return self.runs_dir / f"{run_id}.json"

    def _load(self, run_id):
        if not isinstance(run_id, str) or not RUN_ID.match(run_id):
            return None
        return self.queue._read_path(self._path(run_id))

    def _mutate(self, run_id, fn):
        with self._locked():
            run = self._load(run_id)
            if run is None:
                return None
            fn(run)
            run["updated"] = provenance.now_stamp()
            self.queue._atomic(self._path(run_id), run)
            if run["state"] in FINAL:
                (self.active_dir / run_id).unlink(missing_ok=True)
            return run

    def start(self, recipe_id=None, values=None, recipe=None, client=""):
        """Check everything that can be checked, then write the run. Raises RecipeError."""
        if recipe is not None:
            chosen = check_recipe(recipe, self.queue.adapters)
            chosen.setdefault("id", "inline")
        else:
            chosen = self.get(recipe_id)
            if chosen is None:
                raise RecipeError("That recipe is not in the book.")
        cleaned = _clean_values(chosen, values or {})
        if self.queue.line_is_full():
            raise RecipeError("The line is full, so this recipe was not started. Please wait for some of it to finish.")
        for step in chosen["steps"]:
            if any(r.startswith("steps.") for v in step["params"].values() for r in _refs(v)):
                continue  # needs an earlier step's output; checked when it starts
            try:
                self.queue.adapters[step["adapter"]].validate({k: substitute(v, cleaned, {}) for k, v in step["params"].items()})
            except AdapterError as e:
                raise RecipeError(f"{step['label']}: {e}")
        plan = self._plan(chosen, cleaned)
        run_id = f"r-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
        estimates = {s["id"]: s for s in plan["steps"]}
        run = {"id": run_id, "schema": SCHEMA, "recipe": chosen, "values": cleaned, "state": "running", "client": client,
               "created": provenance.now_stamp(), "created_ts": self.clock(), "finished": None, "cancel_requested": False,
               "error": None, "waiting": None, "plan": plan, "result": None,
               "steps": [{"id": s["id"], "label": s["label"], "adapter": s["adapter"], "state": "pending", "job": None, "params": None,
                          "output": None, "error": None, "estimate_seconds": estimates[s["id"]]["estimate_seconds"],
                          "memory_gb": estimates[s["id"]]["memory_gb"], "retry_at": None, "waiting_since": None, "tries": 0}
                         for s in chosen["steps"]]}
        with self._locked():
            self.queue._atomic(self._path(run_id), run)
            (self.active_dir / run_id).touch()
        return self.view(run)

    def cancel(self, run_id):
        run = self._mutate(run_id, lambda r: r.update(cancel_requested=True) if r["state"] not in FINAL else None)
        return self.view(run) if run else None

    def status(self, run_id):
        run = self._load(run_id)
        return self.view(run) if run else None

    def list_runs(self, limit=20):
        names = sorted((p for p in self.runs_dir.glob("r-*.json")), key=lambda p: p.name, reverse=True)[:max(1, limit)]
        runs = [self.queue._read_path(p) for p in names]
        return [self.view(r) for r in runs if r]

    def view(self, run):
        out = {k: run.get(k) for k in ("id", "state", "created", "finished", "error", "waiting", "values", "result", "cancel_requested", "client")}
        out["recipe"] = {k: run["recipe"].get(k) for k in ("id", "name")}
        steps, total, elapsed = [], 0.0, 0.0
        for step in run["steps"]:
            view = {k: step.get(k) for k in ("id", "label", "adapter", "state", "job", "error", "output", "estimate_seconds", "memory_gb", "waiting")}
            estimate = step.get("estimate_seconds") or 30
            if step.get("job"):
                job = self.queue.status(step["job"])
                progress = job.get("progress") or {}
                view["progress"] = {k: progress.get(k) for k in ("stage", "step", "total", "elapsed_seconds", "estimate_seconds")}
                if step["state"] == "running":
                    estimate = max(estimate, progress.get("estimate_seconds") or 0, progress.get("elapsed_seconds") or 0)
                    elapsed += progress.get("elapsed_seconds") or 0
                elif step["state"] == "done":
                    estimate = progress.get("elapsed_seconds") or estimate
                    elapsed += estimate
            total += estimate
            steps.append(view)
        out["steps"] = steps
        out["estimate_seconds"] = round(total)
        out["elapsed_seconds"] = round(elapsed)
        return out

    # ================================================================ moving runs along
    def _loop(self):
        while not self._stop.wait(self.tick_seconds):
            if self.queue.is_worker:
                self.tick()

    def tick(self):
        for marker in sorted(self.active_dir.iterdir()):
            if marker.name.startswith("."):
                continue
            try:
                self._advance(marker.name)
            except Exception as e:  # noqa: BLE001  one bad run must not stop the others
                self._mutate(marker.name, lambda r: r.update(state="failed", finished=provenance.now_stamp(), error=f"{type(e).__name__}: {e}"))

    def _finish(self, run, state, error=None):
        def fn(r):
            r.update(state=state, error=error, finished=provenance.now_stamp(), waiting=None)
            for step in r["steps"]:
                if step["state"] in ("pending", "waiting"):
                    step.update(state="not run", waiting=None)
            produced = [s for s in r["steps"] if s.get("output") and s["output"].get("file")]
            if state == "done" and produced:
                r["result"] = {"file": produced[-1]["output"]["file"], "name": Path(produced[-1]["output"]["file"]).name,
                               "seed": next((s["output"].get("seed") for s in produced if s["output"].get("seed") is not None), None),
                               "files": [Path(s["output"]["file"]).name for s in produced]}
        self._mutate(run["id"], fn)

    def _advance(self, run_id):
        run = self._load(run_id)
        if run is None:
            (self.active_dir / run_id).unlink(missing_ok=True)
            return
        if run["state"] in FINAL:
            (self.active_dir / run_id).unlink(missing_ok=True)
            return
        step = next((s for s in run["steps"] if s["state"] not in ("done", "skipped")), None)
        if step is None:
            self._finish(run, "done")
            return
        if run.get("cancel_requested"):
            if step["state"] == "running" and step.get("job"):
                job = self.queue.status(step["job"])
                if job.get("state") not in FINAL:
                    self.queue.cancel(step["job"])
                    return
            self._mutate(run_id, lambda r: self._mark(r, step["id"], state="cancelled"))
            self._finish(self._load(run_id), "cancelled")
            return
        if step["state"] in ("pending", "waiting"):
            self._begin_step(run, step)
        elif step["state"] == "running":
            self._check_step(run, step)

    @staticmethod
    def _mark(run, step_id, **fields):
        for step in run["steps"]:
            if step["id"] == step_id:
                step.update(fields)

    def _wait(self, run, step, why, retry_at=None):
        def fn(r):
            self._mark(r, step["id"], state="waiting", waiting=why, retry_at=retry_at)
            r["waiting"] = why
        self._mutate(run["id"], fn)

    def _begin_step(self, run, step):
        if step.get("retry_at") and self.clock() < step["retry_at"]:
            return
        recipe_step = next(s for s in run["recipe"]["steps"] if s["id"] == step["id"])
        adapter = self.queue.adapters.get(step["adapter"])
        outputs = {s["id"]: s["output"] for s in run["steps"] if s.get("output")}
        try:
            if adapter is None:
                raise RecipeError(f"NeoVak has no engine called {step['adapter']} any more.")
            params = {k: substitute(v, run["values"], outputs) for k, v in recipe_step["params"].items()}
            needs_model = bool(adapter.memory_gb(params))
        except RecipeError as e:
            self._fail(run, step, str(e))
            return
        if needs_model:
            why = self.hold(step.get("estimate_seconds") or 0)
            if why:
                self._wait(run, step, why)
                return
        done_steps = [{"step": s["id"], "label": s["label"], "file": Path(s["output"]["file"]).name,
                       "seed": s["output"].get("seed")} for s in run["steps"] if s.get("output") and s["output"].get("file")]
        context = {"recipe": {"id": run["recipe"].get("id"), "name": run["recipe"].get("name"), "run": run["id"], "step": step["id"],
                              "step_label": step["label"], "values": run["values"]}, "chain": done_steps}
        try:
            job = self.queue.submit(step["adapter"], params, client="recipe", context=context)
        except AdapterError as e:
            self._fail(run, step, str(e))
            return

        def fn(r):
            self._mark(r, step["id"], state="running", job=job["id"], params=job.get("params"), waiting=None, retry_at=None,
                       tries=step.get("tries", 0) + 1)
            r["waiting"] = None
        self._mutate(run["id"], fn)

    def _fail(self, run, step, message):
        self._mutate(run["id"], lambda r: self._mark(r, step["id"], state="failed", error=message))
        self._finish(self._load(run["id"]), "failed", message)

    def _check_step(self, run, step):
        job = self.queue.status(step["job"])
        state = job.get("state")
        if state not in FINAL:
            return
        if state == "cancelled":
            self._mutate(run["id"], lambda r: self._mark(r, step["id"], state="cancelled"))
            self._finish(self._load(run["id"]), "cancelled")
            return
        if state == "failed":
            if NO_GO_MARK in (job.get("error") or ""):
                since = step.get("waiting_since") or self.clock()
                if self.clock() - since >= self.memory_wait:
                    self._fail(run, step, "There was not enough free memory for this step, even after waiting an hour. "
                                          "The steps already finished have been kept.")
                    return
                self._mutate(run["id"], lambda r: self._mark(r, step["id"], waiting_since=since))
                self._wait(run, step, "memory to free up", self.clock() + self.memory_retry)
                return
            self._fail(run, step, job.get("error") or "This step failed.")
            return
        result = job.get("result") or {}
        files = [f for f in (result.get("files") or []) if provenance.THUMBNAIL_MARK not in Path(f).name]
        output = {"file": result.get("path") or (files[0] if files else None), "seed": result.get("seed", (job.get("params") or {}).get("seed")),
                  "text": result.get("text") if job.get("lane") == "text" else None, "model": result.get("model")}

        def fn(r):
            self._mark(r, step["id"], state="done", output=output, waiting_since=None)
        self._mutate(run["id"], fn)
