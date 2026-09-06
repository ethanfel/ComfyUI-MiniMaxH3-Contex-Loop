# Scheduled references

Use Scheduled Ref2VA when a picture, video, or audio reference should apply to
selected scenes rather than every recursive iteration.

```text
Scheduled Picture Ref ─→ Scheduled Video Ref ─→ Scheduled Audio Ref
                                                    ↓
Current Shot ─ prompt, clip_index, clip_count ─→ Scheduled Ref2VA
Current Shot ─ width, height, length ───────────→ Scheduled Ref2VA
CLIP + video VAE + audio VAE ──────────────────→ Scheduled Ref2VA
```

## Scene selectors

| Value | Active scenes |
|---|---|
| blank, `all`, or `*` | every scene |
| `3` | scene 3 |
| `1:5` | scenes 1 through 5 |
| `1,3,5:8` | scenes 1, 3, and 5 through 8 |

Disjoint selectors are safe for references because they do not skip the loop's
motion dependency.

## Aliases and native labels

Aliases such as `@hero_face`, `@performance`, and `@voice` are optional
authoring conveniences. The wrapper replaces active aliases with the native H3
label assigned in that scene. It never inserts definitions or rewrites semantic
prompt text.

Native numbering is compact and independent by media type:

1. active pictures become `<Picture 1>`, `<Picture 2>`, and so on;
2. active videos receive independent `<Video N>` labels;
3. paired video soundtracks are presented immediately before their video and
   consume `<Audio N>` labels;
4. standalone audio continues the independent audio numbering.

If an earlier picture becomes inactive, a later `@hero` may compile to
`<Picture 1>`. This is why aliases are safer for changing schedules. Core
workflows may continue to use native labels directly.

Write the meaning of every reference in the Plan prompt itself:

```text
subject_definitions:
<Subject 1> uses @hero_face for facial identity and @performance for movement.
```

## Compliance policies

- **strict** compiles valid active aliases and stops on unresolved/inactive tags
  or invalid scheduled media.
- **soft** compiles valid aliases, leaves unresolved prompt tags intact, logs a
  warning, and continues.
- **disabled** passes the prompt and all `@tags` through unchanged. Scheduler
  validation becomes warning-only; unusable media is omitted and excess slots
  are capped to stock H3 limits.

Errors outside the scheduler remain real errors, including invalid model/VAE
wiring, sampling failures, continuation tensor incompatibility, and checkpoint
integrity failures.

## Preview and insertion

The Scene Prompt Editor's **@ Reference** tray shows only sources active for
the selected scene. Hover a loader-backed tag to preview image, video, or audio,
then click to insert it. Audio never autoplays.

## Dedicated semantic picture anchors

For new workflows, register Qwen-only stills with **Semantic Picture Anchor**,
chain those small nodes, and finish them with one **Semantic Anchor Bundle**.
Connect the Bundle's **references** output to Tagged Ref2VA's **references**,
Plan Studio's **tagged_references**, and Run Manager's **tagged_references**.
That one reference carrier contains both native `@references` and Qwen-only
`#anchors`, but semantic images remain excluded from native H3 capacity. The
Bundle owns the shared presentation size and mode, so individual anchor nodes
store their original picture and scale it only when a scene actually calls its
`#tag`.

The prompt-driven Tagged route accepts both `#picture` and
`#picture[2.50s]`. Bare `#picture` presents the matching Semantic Picture
Anchor to Qwen as one untimed image. Adding `[2.50s]` gives that same Qwen-only
visual an approximate scene-local placement. Neither form adds a native VAE
reference. Timed anchors are useful for reinforcing a replacement character's
identity later in a shot:

```text
<Subject 1> is the replacement performer defined by @replacement.
#replacement[0.00s] #replacement[2.50s] #replacement[4.75s]
```

`@replacement`, bare `#replacement`, and `#replacement[...]` have distinct
jobs and may be used
together, including from different source nodes. The `@` form is a native
Ref2VA picture and counts toward H3's nine active Picture slots. The `#` form is
Qwen-only semantic reinforcement and never counts toward native picture,
video, or audio limits. A supplied time must fall inside the current scene.
Timing is optional and approximate—not an exact frame, pose, spatial mask,
motion control, or continuation seam.

Tagged Picture nodes remain accepted as `#tags` for existing workflows, but
the dedicated semantic chain is preferred: inactive semantic images can stay
in the project without crowding native reference accounting, while the Bundle
emits one combined incremental fingerprint for Plan resume safety.
Start with two or three sparse anchors—too many repeated pictures can resist
the source video's changing pose.

### Picture storyboard mode

Set Semantic Anchor Bundle's mode to `picture_storyboard` to compile
timed `#picture[time]` syntax differently. Each distinct tagged image is
added once as a separate Qwen-only `<Picture N>`, and the compiler adds an
approximate scene-relative timing sentence for every requested time. No image
is VAE encoded, spatially fused, or inserted into a fixed generated frame.
Bare `#picture` is already an untimed `<Picture N>` in either mode.

This mode gives Qwen a high-detail visual shot plan while H3 remains free to
invent motion and transitions. `timestamped_video` remains the default and is
better for sparse temporal reinforcement. Storyboard mode is useful for a
sequence of compositions or appearances, but its textual timing is softer.

The Bundle's `semantic_anchor_size` accepts 384, 512, 768, 1024, 1280, or
source. Higher
values preserve more face, wardrobe, prop, and environment detail at the cost
of longer Qwen conditioning and greater VRAM/runtime pressure. Prefer 512 or
768 generally, 1024 for important detailed anchors, and 1280 for a small number
of critical stills.

With core Ref2VA, the tray previews media and inserts native labels. With core
Image to Video it exposes first and last frames as `<Picture N>` according to
the active keyframes.

## External RefMod experiment

Tagged Ref2VA can expose the exact active visual sources selected for the
current scene to
[ComfyUI-MiniMaxH3Mod](https://github.com/Luisacaotica/ComfyUI-MiniMaxH3Mod).
Install that node pack, then set Tagged Ref2VA's `conditioning_backend` to
`external_refmod` and wire:

```text
Tagged Ref2VA refmod_sources ─→ Extract H3 RefMod refs_bundle
Tagged Ref2VA positive ───────→ Apply H3 RefMod conditioning
Extract H3 RefMod mods ───────→ Apply H3 RefMod mods
Apply H3 RefMod conditioning ─→ H3 Chain Context conditioning
Tagged Ref2VA latent ─────────→ H3 Chain Context latent
```

In this mode Tagged Ref2VA still selects scene-local `@tags`, resolves lazy
project images, and slices sequential reference videos. It describes those
RefMods in text using their readable tag names, creates base conditioning and
a matching empty AV latent through core `MiniMaxH3ImageToVideo`, and skips
stock Ref2VA. `refmod_sources` uses the external pack's existing `H3_REF_LIST`
contract, so no direct Python import or patched external node is required.
Native behavior remains the default.

Semantic `#tag` and `#tag[timestamp]` visuals use a hybrid path. Ordinary active `@visuals`
remain exclusively in RefMod, while only the active anchor images are presented
to Qwen and numbered in their own `<Picture N>` or `<Video N>` namespace. Bare
tags are Pictures; timed tags are Video checkpoints in `timestamped_video` mode
or Picture cues in storyboard mode. This preserves the supplied timing
without paying Qwen's media-token cost for every ordinary reference again.
An asset intentionally used as both `@tag` and either `#` form participates in
both paths.

The external experiment remains unable to carry reference audio. A scene with
active standalone tagged audio or paired reference-video audio stops with a
clear error instead of silently losing it. Source Timeline/final audio managed
outside Tagged Ref2VA remains unaffected.

The reference registry and backend choice participate in the Plan fingerprint,
but the external Extract/Apply widgets and resulting mod bytes do not. Use a
new run name when changing RefMod mode, resolution, pooling, frame retention,
token cap, or strength. Native deferred-upscale reference caching is disabled
for `external_refmod`; the deferred pass does not yet reconstruct external
mods automatically.

## Resume fingerprints

For static loaders, connect `schedule_fingerprint` to Plan's
`generation_fingerprint`. Changing media bytes, tags, or selectors then
invalidates incompatible checkpoints.

Do not create a fingerprint cycle when a scheduled entry consumes Current Shot,
such as `source_audio_slice`. Source-track mode already fingerprints the full
source waveform at Loop Start.

## Automatic deferred-upscale cache

Tagged and Scheduled Ref2VA enable `cache_for_upscale` by default. The wrapper
stores native H3 picture/video/audio reference latents, original picture masters
for larger pass-2 canvases, and the resized Qwen image or 2 fps video presentation.

New caches use **V3 per-reference tensor objects**, not one large safetensors
bundle per scene. Each original, presentation tensor, and encoded latent is
stored independently, addressed by its exact dtype, shape, and bytes. Different
scenes, prompts, reference ordering, and projects reuse identical objects. An
original picture can be shared even when its resized presentations and encoded
variants differ. Different VAE results, resolutions, video slices, and audio
payloads never share an object unless the resulting tensors are identical.

Small scene JSON manifests retain the registry fingerprint, prompt, frame
contract, canvas, reference sizing, roles, ordering, timestamps, and object links.
Their signatures include the tensor-object map. This deduplicates **disk storage**;
it does not skip VAE encoding based on guessed model identity, or spill the
upscaler's working frames/model memory to disk.

Ref2VA writes objects to `output/h3_reference_cache/objects/` and scene manifests
to `output/h3_reference_cache/<fingerprint>/` because it does not require a Plan
or `run_name` input. Segment Save then hard-links each unique object (or copies
it once per project when linking is unavailable) and publishes local metadata:

```text
output/h3_chains/<run-name>/reference_cache/
  scene_0001.<scene-contract>.json
  scene_0002.<scene-contract>.json
  objects/<tensor-content-hash>.safetensors
```

The standalone deferred-upscale workflow reads `generation_fingerprint` from
the selected checkpoint branch and restores the matching scene automatically.
It does not need the source Plan or any original reference-media connection.
The checkpoint points only to the run-local descriptor, making the run folder
self-contained for copying, backup, and later upscale. Object maps and tensor
files are SHA-256 verified before use; relocated projects do not need the shared
store. Do not delete individual objects: multiple scenes can reference them. Disable
`cache_for_upscale` only when the extra reference encode and disk cache are not
wanted. Existing checkpoints made before this feature have no cache; the
upscale conditioning node can either fall back to text-only conditioning or
raise an explicit error.

V1/V2 bundled caches remain readable and are not automatically rewritten or
deleted merely by installing the update. New writes use V3. Use the converter
below to opt existing bundles into conversion and success-gated retirement.
There is no automatic garbage collection of the new shared tensor objects.

Checkpoints with exact cache links made during the earlier global-cache-only implementation are
adopted automatically on their next complete-branch selection in Checkpoint
Manager. The verified tensor is hard-linked or copied into the run-local cache;
the original `output/h3_reference_cache/` object is deliberately left intact.
No source render or manual file move is required. Workflow-local and chapter-only
selection are read-only and do not migrate caches. Older checkpoints without an
exact cache link still use the fingerprint-based shared-cache lookup.

### Converting existing bundles

**Update every ComfyUI instance sharing the output directory before enabling
conversion.** Old node versions cannot follow V3 redirects after retirement.
Run this with a Python environment containing PyTorch and safetensors; no model
load, VAE re-encoding, or generation is required to convert:

```bash
python tools/convert_reference_caches.py --output-root /path/to/ComfyUI/output --all --dry-run
python tools/convert_reference_caches.py --output-root /path/to/ComfyUI/output --all --apply
```

For narrower scope, replace `--all` with `--run <run_name>` (project-local caches
only), or `--metadata <relative/path/to/scene_cache.json>` (repeatable). Dry-run
is the default and writes nothing. `--apply` is resumable: completed conversions
are verified and reused, and incomplete conversions retain their old bundle.
Conversion needs temporary headroom for unique objects until successful use.

The converter retains the original `scene_….json` and large bundle, and writes
a neighbouring `scene_….converted.json` with links to the per-tensor objects.
Tensor values, dtypes, reference roles, prompt, order, and timestamps are
preserved exactly; V1 caches do not gain original images they never contained.
Immutable checkpoint JSON and source-manifest identities are not rewritten,
so existing upscale profiles can still resume.

**Automatic retirement happens after a successful scene save using converted
conditioning**, not during conversion, cache discovery, preview, or conditioning
encoding. The H3 generation/upscale saver requires a same-execution use receipt
on the conditioning path of a supported sampler leading to its saved pixels.
Built-in `SamplerCustom`, `SamplerCustomAdvanced`, `KSampler`/`KSamplerAdvanced`,
H3 USDU `UltimateSDUpscale*`, and the CAT USDU video adapter are recognized.
Unknown wrappers, cached conditioning from a previous execution, failed or
cancelled renders, and unprovable branches keep the legacy bundle.

After verifying the committed output, the complete converted tensors against
the original bundle, and other cache JSON consumers of that pathname, the saver
deletes **only that legacy safetensors file**. It retains the original JSON,
converted manifest, tensor objects and a small `.retired.json` receipt so old
checkpoint addresses continue to resolve. Other hard links are left intact;
unlinking one path may not release physical space until its remaining links
are also retired. The saver reports retirement in its status and log. Cleanup
failure keeps the bundle and never invalidates a successfully saved render.

## Patch priority

If an older compatible H3 Motion Context copy wins process load order, insert
**MiniMax H3 Patch Priority** between Ref2VA/I2V conditioning and Context Loop
Context. It passes conditioning unchanged while claiming only the recognized
shared patch family. Known H3-Multishot and SolAttn hooks remain active; unknown
wrappers produce a clear error rather than being overwritten.
