# Building the 0.6 workflow catalog

`recipes/` is the source of truth. Each recipe names its node settings and
connections; it contains no UI widget arrays, node dimensions, link-slot numbers,
or frontend metadata. Existing example prompts and intended connections were
reviewed as reference material. The old archive-based builder is no longer used.
The files under `example_workflows/Archive/` are never read or modified by this
builder.

From this checkout, run:

```sh
python3 tools/build_v06_workflows.py
python3 tools/build_v06_workflows.py --check
python3 tests/_workflow_schema_unit_test.py
python3 tests/_workflow_catalog_unit_test.py
```

The builder imports this branch's H3 `INPUT_TYPES` / output definitions in an
offline schema environment. Run it in its own Python process, not inside a
running ComfyUI server. The normal package dependencies, including torch, must
be available; no model weights or GPU inference are used.

`external_schemas.json` contains only dependency contracts, with provenance and
installation-specific file inventories removed. It is not a snapshot of nightly
H3 nodes. Update these external contracts deliberately when changing the
documented dependency requirements; do not import an entire server inventory.

## Serialization rules

- Name every widget explicitly. A new/missing field fails the build until its
  recipe has been reviewed.
- Connected widgets still occupy their normal position in `widgets_values`.
  They also need the input's `widget.name` metadata.
- Seed controls include `control_after_generate` in frontend order.
- V3 dynamic combos include their selected child settings; autogrow reference
  sockets are generated from named connections.
- VHS uses named widget serialization. Preview state and uploaded-file browser
  metadata are not embedded.
- Studio's connected Plan values initialize its mirror consistently.

Tests cover widget types, enums and ranges, required inputs, converted-widget
metadata, bidirectional links, output slots, Studio plan wiring, title-inclusive
node bounds, group containment, preserved assets, and deterministic generation.
The reported two-slot Tagged Ref2VA shift is an explicit negative regression test.

## Layout and release checks

Project controls precede numbered dependency columns. Titles are short enough
not to force automatic width expansion. Stacks reserve body height, the 30-pixel
title bar and a 70-pixel gap. DOM editors and image/video previews get explicit
space. Recovery is isolated and disabled; detailed Notes become companion guides.

The September 5 audit opened all 18 files in an isolated ComfyUI 1.51.9 frontend
with this 0.6 branch's schemas and JavaScript (plus VHS), and checked serialized
API prompts. All project writes and queue requests were blocked. This checks
loading, settings and wiring, not numerical model output or GPU memory use.
Before release, also test representative real renders with installed models and
assets, particularly the optional external upscale packs.
