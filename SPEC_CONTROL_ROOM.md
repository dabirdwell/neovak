# SPEC_CONTROL_ROOM.md — Recipes and the Control Room

Status: v0.1 draft for David's review, 2026-08-06.
Author: Claude (chat session, Aug 5-6). Nothing here is committed
product truth until David strikes and keeps lines.

## 0. Decisions already locked (Aug 5-6 session)

These are settled and the spec builds on them. Relitigating them is
out of scope for review; everything else is fair game.

1. Two modes, one app. A fast, easy, proven-quality mode ("Fast
   Lane") and a revealed-surface mode ("Control Room"). David's
   phrasing: "recipes with a parameter surface that can be revealed."
2. Architecture: a parameter set that compiles to a graph (Option B)
   is the product. A raw graph view (Option A) exists as a back
   panel, never as the primary surface.
3. Saving is first-class. A Control Room session can be saved down
   as a new recipe. Back-panel edits can be promoted into recipes.
4. Bindings are by node ID + input name, never by class_type.
5. Graph templates stay unmodified ComfyUI API-format JSON, so
   anything from the ComfyUI ecosystem drops in unconverted.
6. Local model calls in the tooling use the talk_local.py pattern
   (/Users/david/Documents/Claude_Technical/talk_local.py). No
   max_tokens caps. Token generosity is canon.

## 1. The problem, stated against the current code

NeoVak today (/Users/david/Documents/Claude_Technical/neovak/,
neovak_ui.py 3,491 lines NiceGUI, neovak_backend.py 3,903 lines)
drives seven frozen workflow JSONs in workflows/, dated Jan-Feb 2026.
Parameterization is a loop at neovak_backend.py:1236 that walks the
graph switching on class_type, with model families sniffed from
filename substrings (is_flux, is_qwen, is_lightning, is_sd15) and
family-specific rules hardcoded inside the branches (Flux: cfg=1.0,
steps<=8; Qwen FP8: cfg 2.5).

Consequences, each observed directly:

- No LoRA or adapter control on image or video paths at all. The one
  LoRA control in the app is a bare path text field on the music tab.
- Reference images exist only where hand-bolted (variations, inpaint,
  upscale). Nothing general.
- Two nodes of the same class in one graph are indistinguishable to
  the injector, which is why family sniffing exists at all.
- New engines cost a new frozen JSON plus new branches. That tax is
  why the app froze in February while the engine world moved.
- MiniMax H3's reference-to-video mode is unexpressible in this
  architecture, because the mode is defined by what you feed it.

## 2. The recipe: the core object

A recipe is one JSON file with three parts: identity, a pointer to a
pure ComfyUI API-format graph template, and a parameter schema whose
entries bind to graph locations.

```json
{
  "recipe": "h3_ref2va_character",
  "title": "Character video from reference stills",
  "engine": "minimax-h3",
  "version": 1,
  "graph": "graphs/h3_ref2va.json",
  "params": [
    {
      "id": "motion_prompt",
      "label": "What happens",
      "tier": "basic",
      "type": "text",
      "bind": {"node": "6", "input": "text"}
    },
    {
      "id": "reference_images",
      "label": "Character reference stills",
      "tier": "basic",
      "type": "image_list", "max_items": 4,
      "bind": {"node": "78", "input": "images"}
    },
    {
      "id": "length_frames",
      "label": "Clip length",
      "tier": "advanced",
      "type": "int", "default": 141,
      "constraint": "17n+5",
      "bind": {"node": "70", "input": "length"}
    },
    {
      "id": "style_lora",
      "label": "Style adapter",
      "tier": "advanced",
      "type": "lora", "weight_range": [0.0, 1.5],
      "bind": {"node": "injected", "input": "lora_name"}
    }
  ],
  "provenance": {"created_by": "promote", "parent": "h3_i2v", "date": "2026-08-06"}
}
```

Notes on the shape:

- `tier` is one of basic / advanced / expert. Progressive disclosure
  becomes a filter over data, not a UI someone hand-builds per tab.
  Fast Lane IS the recipe filtered to `tier: basic` with defaults.
- `type: lora` is a first-class parameter type. Any recipe that
  declares one gets the adapter picker for free. Same principle for
  `image`, `image_list`, `audio`, `seed`.
- `constraint` entries are declared, checked before submission, and
  surfaced in the UI (a length slider that snaps to 17n+5), replacing
  knowledge that today lives buried in if-branches.
- `provenance` records where a recipe came from: authored, promoted
  from the back panel, or imported.

## 3. The compiler

One function replaces the class_type loop: load graph template, walk
the recipe's params, write each value to `graph[bind.node]["inputs"]
[bind.input]`, run constraint checks, submit via the existing
submit_workflow() at neovak_backend.py:991 (which is fine and stays).

Rules:

- Node-ID binding only. If a template's node IDs change, that is a
  new template version; recipes reference templates by path + hash.
- A recipe fails loudly at load time if any binding points at a node
  or input the template does not have ("stale binding"), rather than
  silently generating something wrong.
- Family-specific defaults (Flux cfg=1.0 etc.) move out of code and
  into each recipe's `default` fields. When migration is complete,
  `grep -c "is_flux" neovak_backend.py` must return 0. That grep is
  the acceptance test for this whole section.

## 4. Control Room UI

The Control Room is the recipe rendered as controls, grouped by tier:
basic always visible, advanced behind one reveal, expert behind a
second. No new UI framework; NiceGUI renders forms from the schema.

- Every control shows the human label, with the raw binding
  (node/input) visible on hover or long-press, so the mapping is
  never a secret.
- `lora`-typed params render as a picker over the discovered adapter
  library plus a weight slider. Trigger-word auto-injection and
  thumbnails are v2 (see §10).
- `seed` params render with lock / randomize / history.
- Constraint violations block the generate button with the reason,
  before ComfyUI ever sees the graph.

## 5. The back panel

Any recipe opens raw on demand: every node, every input, rendered
generically from the graph plus ComfyUI's `GET /object_info` (which
supplies types, ranges, and enum options for every registered node).
This is deliberately plain, a table of nodes and inputs, not a
node-graph canvas. ComfyUI itself remains the canvas; the back panel
is for reaching the 10% the schema does not cover without leaving
the app.

Ecosystem import works through this door in v1: drop any ComfyUI
API-format JSON in graphs/ and it is immediately usable via the back
panel, schema or no schema.

## 6. Save and promote (the compounding loop)

Two verbs:

- Save: from the Control Room, current values -> new recipe file.
  Small, diffable, provenance recorded.
- Promote: from the back panel, the app diffs edited raw values
  against the template, lists the touched inputs, and offers to name
  each one and assign a tier. Accepting writes a new recipe whose
  schema covers exactly what the user actually reached for.

Promote is the mechanism by which the app improves through use. It is
also the reason the back panel must exist: without it there is
nothing to promote from.

## 7. Schema drafting pipeline (tooling, not runtime)

Authoring tax is Option B's main cost. It is paid down two ways:

1. `GET /object_info` auto-drafts the mechanical half of any schema:
   every input's type, range, step, and options.
2. The 27B on :8089 drafts the human half: labels, one-line
   descriptions, tier assignments. Via the talk_local.py pattern, no
   caps, output reviewed by a person (or by the session Claude), not
   trusted blind.

Target: a new recipe's schema is a review task measured in minutes,
not an authoring task measured in an evening.

## 8. Output provenance

Every output embeds: recipe name, full parameter values, graph
template hash, engine, seed, date. PNG text chunks for stills; a
JSON sidecar for video and audio (container metadata where the
format allows it, sidecar always, so nothing depends on ffmpeg
remux behavior).

Dragging any past output back into the app restores its exact state:
recipe open, values set, seed locked. This is the A1111/Comfy habit
creators already rely on, made native. A Tull lane (generations as
timeline events) reads these sidecars later; nothing extra to build
now beyond writing them.

## 9. MiniMax H3 integration (the forcing function)

Ground state, verified Aug 5-6:

- ComfyUI 0.30.2 at /Users/david/Documents/AI-Projects/ComfyUI,
  all five custom nodes importing, torch 2.13.0, MPS true.
- Native H3 nodes at comfy_extras/nodes_minimax_h3.py
  (EmptyMiniMaxH3LatentAV, MiniMaxH3ImageToVideo,
  MiniMaxH3ReferenceToVideo, MiniMaxH3SigmaShift).
- Weights downloaded, 50G total, at
  /Volumes/Mix Master Mike/ComfyUI/models/_h3/
  (fl2va_pruned int8_convrot 20G, qwen3vl_32b int8_convrot 25G,
  video VAE fp16 4.8G, audio VAE fp32 577M).
- The eager backend carries dequantize_int8_convrot_weight, so the
  int8 checkpoints have a non-CUDA route. Speed on MPS is UNKNOWN.

Pre-work (config, in-lane, reversible):

- Fix /Users/david/Documents/AI-Projects/ComfyUI/extra_model_paths.yaml:
  external_models currently points at
  /Volumes/Mix Master Mike/Experimental Models/ComfyUI_Models/,
  which does not exist. Point it at
  /Volumes/Mix Master Mike/ComfyUI/models/ and fold _h3/ into the
  standard subdirs. This also decides the fate of the broken LTX-2
  19B and Wan2.2 symlinks in models/diffusion_models/.

Constraints to declare in H3 recipes: frame length 17n+5; 24fps;
native audio via the audio VAE (this is the reason H3 matters: one
pass, sound included); 768P resolution option exists upstream.

Ties to existing sprints, both v2:

- FL2VA conditions on first and last frames, which makes
  SPRINT_VIDEO_CHAIN.md's segment chaining native: condition each
  segment on the previous clip's final frame instead of hoping
  seams hold.
- Ref2VA is character consistency from stills, which is what
  SPRINT_LUMINA_WORLD.md needs: Lumina recognizable across shots
  from a reference sheet.

## 10. Proposed v1 / v2 split (David strikes lines here)

v1, the compounding core:

1. Recipe format + compiler + validator (§2-3).
2. Migrate all seven existing workflows to recipes. Fast Lane
   parity with today is the bar; the class_type loop and family
   sniffing are deleted at the end.
3. Control Room rendering from tiers (§4).
4. Back panel + raw ecosystem import (§5).
5. Save + promote (§6).
6. lora / image / seed parameter types, with the minimal picker
   (dropdown + weight slider).
7. Provenance embed + drag-back restore (§8).
8. H3 recipes: text-to-video and image-to-video on FL2VA, plus one
   Ref2VA recipe.
9. Governor preflight: before heavy generation, call
   /Users/david/Documents/Claude_Technical/model_governor.py status
   and show what the load will evict, before it evicts it.
10. Schema drafting pipeline as internal tooling (§7).

v2, the taste layer:

- Parameter sweep contact sheets (lock everything, vary one, pick
  the cell, values become the recipe).
- Blind A/B taste test with hidden settings, logged picks feeding
  recipe defaults. Structured Emergence pointed at David's own eye.
- Named style library (the Fooocus lesson: opinionated defaults).
- LoRA palette upgrades: thumbnails, trigger-word auto-injection.
- Wildcard syntax {red|blue|green}; seed bookmarks by name.
- Import wizard: dropped graph -> auto-drafted schema via §7.
- FL2VA segment chaining (VIDEO_CHAIN rewrite on native rails).
- Lumina reference-sheet pipeline (LUMINA_WORLD).
- Form composer for custom Control Room layouts (InvokeAI lesson).
- Tull lane reading provenance sidecars.

## 11. Milestones, each with its check

M0. H3 feasibility probe. Fix extra_model_paths.yaml, link weights,
    boot ComfyUI on MPS, run a minimal FL2VA text-to-video graph at
    low res / short length. Record wall time and peak memory with
    the governor watching.
    Check: output file exists and ffprobe reads it; timing logged.
    M0 gates the H3 half of v1. If int8_convrot on MPS is unusably
    slow, H3 recipes wait for better quants and v1 proceeds on the
    existing engines, unchanged in architecture.

M1. Compiler for ONE recipe (sdxl_simple). Parity test: same seed
    through legacy path and compiler path, outputs compared.
    Check: parity artifact pair saved; diff is noise-level.

M2. All seven workflows migrated; injector loop deleted.
    Check: grep -c "is_flux" neovak_backend.py returns 0; all seven
    Fast Lane tabs generate.

M3. Control Room renders any recipe from its schema.
    Check: h3 recipe's advanced tier reveals and generates.

M4. Back panel + promote writes a working recipe file.
    Check: a promoted recipe generates without hand-editing.

M5. Provenance + drag-back restore.
    Check: drag yesterday's output in, regenerate, byte-similar.

M6. Governor preflight wired into the generate path.
    Check: heavy load shows the eviction warning before firing.

## 12. Risks and unknowns, stated plainly

- MPS speed of int8_convrot dequant: unknown until M0. This is the
  single biggest unknown and it is why M0 is first.
- Unified memory pressure: the 27B watch officer holds 26G resident.
  A 45G+ model load will evict it. Preflight makes this visible;
  it does not make it free.
- Schema drift: a graph edited without its schema gives wrong labels
  and dead bindings. Mitigation: load-time lint of every binding
  against the template and /object_info, failing loudly (§3).
- NiceGUI dynamic form rendering at expert-tier width is unproven in
  this codebase. M3 exists to find out early.
- Repo hygiene: the neovak checkout carries an iCloud conflict
  artifact (".git 2" -> .git.nosync) and lives inside the iCloud
  domain. The iCloud/git divergence hazard
  (/Users/david/Documents/Fawkes/Infrastructure/iCloud_Git_Divergence_Hazard.md)
  applies. Verify against the working tree, not memory of it.

## 13. Out of scope for this spec

- Voice, SFX, and music tabs keep their current paths untouched
  until the image/video migration proves the pattern.
- No node-graph canvas. ComfyUI is the canvas.
- No cloud anything. This is the sovereign stack.
- Kaya/tour or any multi-user story.

END DRAFT v0.1. Strike freely.
