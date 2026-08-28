<p align="center">
  <img src="assets/minimax-h3-contex-loop.svg" alt="MiniMax H3 Contex Loop v0.5 — scene plans that survive the render" width="100%">
</p>

# ComfyUI MiniMax H3 Contex Loop

Build a multi-scene MiniMax H3 video with one reusable sampling body. Review
each scene, retry mistakes, resume interrupted runs, and assemble accepted
scenes from disk.

**[Getting started](https://github.com/ethanfel/ComfyUI-MiniMaxH3-Contex-Loop/wiki/Getting-Started)** ·
**[Choose a workflow](https://github.com/ethanfel/ComfyUI-MiniMaxH3-Contex-Loop/wiki/Workflow-Chooser)** ·
**[Troubleshooting](https://github.com/ethanfel/ComfyUI-MiniMaxH3-Contex-Loop/wiki/Troubleshooting)** ·
[Full wiki](https://github.com/ethanfel/ComfyUI-MiniMaxH3-Contex-Loop/wiki)

> **Version 0.5 status:** `main` is the supported 0.5 release line.
> Saved 0.4 workflows and checkpoints remain supported.

> **Contex** is the intentional public repository spelling.

## What you get

| Goal | This pack provides |
|---|---|
| Make a longer story | A visual scene Plan drives one recursive H3 graph. |
| Keep motion and sound connected | Guide and protected AV-prefix transitions. |
| Direct each scene | Prompts, seeds, timing, pictures, motion video, and audio references. |
| Work from existing footage | Source timelines, clip continuation, inpainting, and two-ended bridges. |
| Iterate safely | Review, edit and retry, reroll, stop early, and atomic checkpoints. |
| Recover the production | Resume, partial assembly, saved assets, and latent-to-PNG export. |

## Quick start

From `ComfyUI/custom_nodes`:

```bash
git clone https://github.com/ethanfel/ComfyUI-MiniMaxH3-Contex-Loop.git
```

Restart ComfyUI, then:

1. Open a maintained workflow from [`example_workflows/`](example_workflows/).
2. Resolve missing model selections; models are not bundled.
3. Give Plan a unique `run_name` and edit its scene prompts.
   Use `{wide shot|close-up}` for alternatives. Each scene's **Prompt
   alternatives** control can derive a stable scene seed, keep an exact fixed
   seed, or randomize that scene on every queue. These choices never change
   sampler seeds, and the exact resolved choice is saved with the checkpoint.
4. Keep **Guide** and **Generated audio** for a simple first run.
5. Queue the graph. Preflight checks timing, media, references, compatibility,
   and resume state before H3 loads.
6. At Review Gate, approve, retry, reroll, or approve and stop. To compare
   several takes per scene, set its optional `candidate_count` above 1 (or
   convert it to an input and connect an INT node). The requested takes generate
   automatically in one batch. Each completed take appears immediately in the
   live carousel while the next take renders. **Use this take & stop batch**
   activates that saved checkpoint, cancels only the speculative in-flight H3
   prompt, and immediately requeues the next scene; a completion race falls
   back to the normal safe candidate boundary. The final scene of an active
   range still reaches Loop End so it can emit the completed manifest.
   **Pause candidate run** waits at the next candidate boundary without
   accepting. After the requested count, Review Gate pauses normally so you can
   mark alternatives to keep. Enable `review_each_candidate` only when you want
   a blocking decision after every saved take. The selected take supplies the
   exact continuation; unkept alternatives are deleted.
7. Assemble the completed or partial manifest.

Version 0.5 expects a current ComfyUI build containing native **Add Guide for
MiniMax H3** from [ComfyUI PR #15439](https://github.com/Comfy-Org/ComfyUI/pull/15439).
`ffmpeg` on `PATH` is preferred; ComfyUI's bundled PyAV can handle review and
assembly when FFmpeg is unavailable.

Some examples need bundled media copied into `ComfyUI/input/`. See the
[asset guide](example_workflows/assets/README.md).

### Project Asset Carousel (nightly)

**MiniMax H3 Project Asset Carousel** replaces a wall of loader and tag nodes
with one path-backed project library. Put it before Plan through its
`project_assets` output and connect its `references` output to Tagged Ref2VA.
When the project has a Source track, Plan stores its path-backed Source Timeline
automatically; Loop Start, Plan Studio, recovery, and assembly read it from the
Plan without another wire. Uploads and imports are copied to
`ComfyUI/input/h3_projects/<project>/` for use by ordinary loaders and mirrored
to `output/h3_chains/<project>/project_assets/` for recovery. Only compact
catalog metadata is saved in the workflow; only tags used by the current scene
are decoded during sampling. For an existing workflow, connect its final
`tagged_references` line to the carousel once: tags, media kinds, semantic or
native roles, and reference options appear as **Unassigned** cards without
copying media from the carrier. Bind each card explicitly from ComfyUI input,
an upload, a backup, or a server path. Unassigned cards never consume H3
reference slots and never enter the generation fingerprint.

Drop one or several image, video, or audio files directly onto the Carousel to
create project assets immediately. Files can also be chosen with **Upload**, or
copied from the existing ComfyUI input folder with **Import** (the default
source); Server path and H3 backup imports remain available from the same
source selector.

Images can be edited nondestructively from the Carousel. **Edit / upscale**
opens a full-source pixel editor with draggable placement, exact dimensions,
megapixel targets and presets, working aspect locking, and
Lanczos/bicubic/bilinear/nearest resampling. Final dimensions can be snapped to
`8`, `16`, `32`, or `64` while retaining the locked ratio; snapping defaults to
`8`. **Use full image** removes cropping without discarding the selected
megapixel target, while **Reset all** restores the complete editor defaults.
Every operation creates a new PNG variant and records its parent and transform;
the source remains unchanged.
Connect ComfyUI core's **Load Upscale Model** output to the optional
`upscale_model` input to enable **Model upscale**. The editor reports both the
exact full-image/crop size sent into the model and the final fitted asset size.
That button queues only the Carousel and its loader dependency and never
launches the downstream H3 chain. The input is lazy and is not loaded during
ordinary generation. Asset cards may also be duplicated without copying media
bytes and organized into presentation-only folders. Folders appear directly
in the Carousel as Discord-style cards with a four-item miniature; click to
expand or collapse their assets inline, or drag an asset onto a folder card to
move it there. Expansion state, folder names, membership, and order do not
affect prompts or fingerprints.

## Choose a workflow

| I want to… | Start here |
|---|---|
| Generate from text | [T2V Normal](<example_workflows/T2V Normal - MiniMax H3.json>) |
| Animate an opening image | [I2V Normal](<example_workflows/I2V Normal - MiniMax H3.json>) |
| Move between first/last images | [FL2V Normal](<example_workflows/FL2V Normal - MiniMax H3.json>) |
| Use prompt-driven pictures | [Ref2V Tagged](<example_workflows/Ref2V Tagged - MiniMax H3.json>) |
| Guide scenes with a source soundtrack | [Ref2V Studio Tagged Source Audio](<example_workflows/Ref2V Studio Tagged Source Audio - MiniMax H3.json>) |
| Inpaint a fixed or tracked region | [Masked Video Inpaint](<example_workflows/Masked Video Inpaint - MiniMax H3.json>) |
| Inpaint with a picture-defined replacement | [Ref2V Masked Video Inpaint](<example_workflows/Ref2V Masked Video Inpaint - MiniMax H3.json>) |
| Continue one existing clip | [Masked AV Extension — Single Clip](<example_workflows/Masked AV Extension - Single Clip - MiniMax H3.json>) |
| Continue several reviewed scenes | [Masked AV Extension — Chain](<example_workflows/Masked AV Extension - Chain + Reference Image - MiniMax H3.json>) |
| Generate the gap between two clips | [Two-Clip Masked AV Bridge](<example_workflows/Masked AV Bridge - Two Clips - MiniMax H3.json>) |

Choose **Normal** for the standard Plan and Scene Prompt Editor. **Studio**
workflows add an optional experimental timeline interface without changing the
generation graph. The [wiki workflow chooser](https://github.com/ethanfel/ComfyUI-MiniMaxH3-Contex-Loop/wiki/Workflow-Chooser)
explains every maintained example and required asset.

## How it works

```text
Chain Policy → [Advanced] → [Legacy 0.4] → Plan
Source Timeline ───────────────────────────┘
                                             ↓
                           Preflight → Loop Start → Current Shot
                                                        ↓
                                      H3 conditioning → sample → decode
                                                        ↓
                                      trim → checkpoint → review → Loop End ─↺

Loop End manifest → Assemble
```

Only one scene passes through the sampling body at a time. The accepted
predecessor supplies continuity to the next scene; completed media and recovery
metadata remain on disk.

## Find help by task

| Task | Guide |
|---|---|
| Install and run the first scene | [Getting started](https://github.com/ethanfel/ComfyUI-MiniMaxH3-Contex-Loop/wiki/Getting-Started) |
| Choose Cut, Guide, Hard AV, Soft AV, or audio behavior | [Continuity and audio](https://github.com/ethanfel/ComfyUI-MiniMaxH3-Contex-Loop/wiki/Continuity-and-Audio) |
| Use `@tags`, motion references, or Source Timeline | [References and source media](https://github.com/ethanfel/ComfyUI-MiniMaxH3-Contex-Loop/wiki/References-and-Source-Media) |
| Inpaint, outpaint, extend, or bridge footage | [Masked editing](https://github.com/ethanfel/ComfyUI-MiniMaxH3-Contex-Loop/wiki/Masked-Editing) |
| Retry, resume, recover, or assemble later | [Review, resume, and recovery](https://github.com/ethanfel/ComfyUI-MiniMaxH3-Contex-Loop/wiki/Review-Resume-and-Recovery) |
| Upscale a completed checkpoint branch | [Runs, review, and recovery](docs/RUNS_AND_RECOVERY.md#whole-chain-seedvr2-finishing) |
| Diagnose a problem | [Troubleshooting](https://github.com/ethanfel/ComfyUI-MiniMaxH3-Contex-Loop/wiki/Troubleshooting) |
| Check where a feature came from | [Feature origins](https://github.com/ethanfel/ComfyUI-MiniMaxH3-Contex-Loop/wiki/Feature-Origins) |
| Look up Plan fields and implementation details | [Advanced reference](https://github.com/ethanfel/ComfyUI-MiniMaxH3-Contex-Loop/wiki/Advanced-Reference) |

Repository-native references remain available under [`docs/`](docs/) and in
the [complete Plan format guide](H3_CHAIN_FORMAT_GUIDE.md).

Checkpoint Manager identifies saved takes by scene and inferred branch, previews
saved media and exact video/audio dependencies, and safely deletes inactive
leaves one revision at a time. When an independent saved take can safely fill
another branch's next empty scene, the empty graph card can attribute it there
without regeneration or duplicate media. Editorial chapters are independent
branch scopes: **All scenes** shows one graph per chapter, and activating a take
in one chapter preserves the active takes in every other chapter. Its Plan and Source Timeline
pass-throughs can remain connected in generation workflows, while its
selected-manifest output launches a standalone deferred upscale loop with no
source Plan. Each profile is isolated under `upscaled/<profile>`, and saving
the large HQ latent is optional.
The bundled chain-aware de-rope variant combines LBH 3D with MAINodes in the
same second pass, protects recursive scene boundaries, restores the prior HQ
Drift-Control tail, and returns recovered video/audio to the source clock
before checkpointing.
For whole-video SeedVR2 finishing, Full-Chain Latent Video Adapter instead
re-decodes every selected H3 checkpoint into one cached, lossless, file-backed
movie. It resolves scene overlaps before upscaling and uses a temporary
disk-backed VAE output buffer, so the complete production never becomes one
in-memory IMAGE tensor.
Tagged and Scheduled Ref2VA also cache each active scene's native reference
latents and compact Qwen presentation automatically; the upscale loop restores
them from the checkpoint fingerprint without original reference-media wires.
See
[Runs, review, and recovery](docs/RUNS_AND_RECOVERY.md).

## Origins and license

This project began with **NikoDemon80's**
[H3 Motion Context](https://github.com/NikoDemon80/ComfyUI-H3-Motion-Context)
and grew into a separate checkpointed production-loop pack. Original,
adapted, inspired, integrated, and compatibility work is mapped in
[Feature traceability](docs/FEATURE_TRACEABILITY.md); licenses and exact
upstream revisions are recorded in [Third-party notices](THIRD_PARTY_NOTICES.md).

GPL-3.0. See [LICENSE](LICENSE). Contributions are covered by
[CONTRIBUTING.md](CONTRIBUTING.md).
