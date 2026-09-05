# MiniMax H3 0.6 example workflows

These are clean ComfyUI UI-workflow documents built for the 0.6 node surface.
They use fresh node serialization, the organized **Production Plan**, explicit
**Generation Profile**, and numbered, non-overlapping project/generation columns. Older
0.5 files are preserved unchanged in [`Archive/0.5/`](Archive/0.5/).

For installation and first-run setup, see
[Getting started](../docs/GETTING_STARTED.md).

Each workflow has a compact **START HERE** note. The longer setup and wiring
instructions are in its matching Markdown file under [`guides/`](guides/),
so they no longer take up large empty canvas panels. Titles and preview sizes
were checked in ComfyUI, including the VHS preview extension.

The catalog is compiled from [named recipes](../tools/v06/README.md), **not**
archived workflow JSON. All H3 sockets, widget positions, and values are checked
against the **0.6 checkout**. Model files, source tracks, and extra packs still
need to be installed/selected as described below; schema validation does not
replace a GPU render test.

The loader defaults use the canonical filenames from the
[official Comfy-Org MiniMax H3 package](https://huggingface.co/Comfy-Org/MiniMax-H3):
put diffusion weights in `models/diffusion_models/`, the Qwen3-VL encoder in
`models/text_encoders/`, and both VAEs in `models/vae/`. The workflows do not
assume a custom model subfolder.

## Choose a starting point

| Input or task | Recommended workflow |
|---|---|
| Text only | [T2V Normal](<T2V Normal - MiniMax H3 0.6.json>) |
| Text-only timeline, takes, and trims | [T2V Studio](<T2V Studio - MiniMax H3 0.6.json>) |
| One opening image | [I2V Normal](<I2V Normal - MiniMax H3 0.6.json>) |
| Image-led timeline, takes, and trims | [I2V Studio](<I2V Studio - MiniMax H3 0.6.json>) |
| First and last images | [FL2V Normal](<FL2V Normal - MiniMax H3 0.6.json>) |
| A few global Ref2VA pictures | [Ref2V Basic](<Ref2V Basic - MiniMax H3 0.6.json>) |
| Prompt-selected `@tag` references | [Ref2V Tagged](<Ref2V Tagged - MiniMax H3 0.6.json>) |
| Tagged references with full project authoring | [Ref2V Studio](<Ref2V Studio - MiniMax H3 0.6.json>) |
| Project references plus exact source audio | [Ref2V Studio Source Audio](<Ref2V Studio Source Audio - MiniMax H3 0.6.json>) |
| Video inpainting | [Masked Video Inpaint](<Masked Video Inpaint - MiniMax H3 0.6.json>) |
| Ref2VA-guided video inpainting | [Ref2V Masked Video Inpaint](<Ref2V Masked Video Inpaint - MiniMax H3 0.6.json>) |
| Continue existing video | [Masked AV Extension — Single Clip](<Masked AV Extension - Single Clip - MiniMax H3 0.6.json>) |
| Extend existing video over several scenes | [Masked AV Extension — Chain](<Masked AV Extension - Chain + Reference Image - MiniMax H3 0.6.json>) |
| Generate the exact gap between two clips | [Masked AV Bridge — Two Clips](<Masked AV Bridge - Two Clips - MiniMax H3 0.6.json>) |

## Normal and Studio

**Normal** workflows keep the familiar scene-column Production Plan and the
standard prompt editor. They are the smallest useful graphs.

**Studio** workflows add the Plan Studio timeline, Project Asset Carousel, rich
prompt editor, and Checkpoint Manager. The Carousel owns the project/run name,
reference lineage, and optional Source Track. Checkpoint Manager browses saved
scenes, alternate branches, trims, previews, and restoration state. These
authoring tools do not change the sampler body.

To initialize a Studio reference project:

1. Copy or import the two 0.6 courier images from [`assets/`](assets/).
2. In Project Asset Carousel, tag the arrival image `courier_arrival` and the
   delivery image `greenhouse_delivery`; assign both the **Picture** role.
3. In the Source Audio workflow, also import one audio file and assign
   **Source track**. Generation Profile is already set to
   **Lip-sync to source audio**.
4. Edit the example scenes and queue the workflow.

The Carousel stores media as ordinary project assets rather than embedding
image bytes or stale file bindings into workflow JSON.

## Current 0.6 authoring contract

Every maintained recursive workflow uses:

- **MiniMax H3 Generation Profile** for scene continuity and audio intent;
- **MiniMax H3 Production Plan** for scene columns, timing, seeds, and output;
- 20-step `res_multistep` / `simple` sampling defaults;
- explicit carried-overlap language in continuation prompts, so new action
  begins after the inherited boundary rather than being cut short;
- a muted manifest/assembly recovery path where appropriate.

In I2V workflows, do not bypass **Frame Gate**. It prevents the opening picture
from being reapplied to every scene. FL2V uses Frame Index Switch plus Frame
Gate to demonstrate an A→B→A endpoint sequence.

For prompt syntax, see [Scene authoring](../docs/SCENE_AUTHORING.md). For tags,
motion references, and source media, see
[Scheduled references](../docs/SCHEDULED_REFERENCES.md).

## Masked editing and existing video

The masked workflows keep the bundled CC0 soldier-crab source because it gives
the mask, source-video, source-audio, and protected-boundary examples a legal,
reproducible common input. Copy the required files from `assets/` to
`ComfyUI/input/` before opening those workflows.

The two-clip bridge is a single masked target with an ordinary sampler. The
extension and inpaint workflows use the checkpoint/review/resume loop. See
[Masked editing](../docs/MASKED_EDITING.md) for H3 grid behavior and audio
protection.

## Deferred upscale

Deferred workflows start from a lineage selected in Checkpoint Manager; they
are not first-install tests.

| Workflow | Extra requirement |
|---|---|
| [SeedVR2 Full Chain](<Deferred Upscale - SeedVR2 Full Chain - MiniMax H3 0.6.json>) | [ethanfel SeedVR2 fork](https://github.com/ethanfel/ComfyUI-SeedVR2_VideoUpscaler) |
| [H3 LBH 3D](<Deferred Upscale - H3 LBH 3D - MiniMax H3 0.6.json>) | [LBH H3 latent upscaler](https://github.com/LBH-123-AI/Comfyui_Minimax_h3_latent_Upscaler) |
| [H3 LBH 3D + De-Rope](<Deferred Upscale + De-Rope - H3 LBH 3D - MiniMax H3 0.6.json>) | LBH pack plus [ComfyUI-MAINodes](https://github.com/matlowai/ComfyUI-MAINodes) |
| [Pixel DLSS5 + USDU — Experimental](<Deferred Upscale - Pixel DLSS5 + USDU - EXPERIMENTAL - MiniMax H3 0.6.json>) | [DLSS5](https://github.com/Blueforcer/ComfyUI-DLSS5-Enhancer), [H3 USDU Guider fork](https://github.com/lisitskyaa/ComfyUI_UltimateSDUpscaleGuider_H3), and Turbo v4 LoRA; [setup and testing limits](<guides/Deferred Upscale - Pixel DLSS5 + USDU - EXPERIMENTAL - MiniMax H3 0.6.md>) |

Upscaled variants are saved below
`output/h3_chains/<run>/upscaled/<profile>/` and never replace source
checkpoints. See [Runs and recovery](../docs/RUNS_AND_RECOVERY.md).

The SeedVR2 workflow uses the current **SeedVR2 Video Path Upscaler** node
(`SeedVR2VideoPathUpscaler`), not the retired `SeedVR2DirectVideoUpscaler` ID.
Install the base SeedVR2 model-loader pack as well as the linked video-path
extension. For LBH, the temporal-chunking and unload controls are explicitly
saved; the De-Rope injection preset is **custom**, with 20 total steps and 0.5
injection, so it does not silently override the visible schedule.

## Assets and provenance

The arrival/delivery pictures were generated specifically as neutral 0.6
reference assets. The masked examples use CC0 footage. Exact hashes, licenses,
copy instructions, and the older 0.5 reference provenance are documented in
[`assets/README.md`](assets/README.md).

ComfyUI cannot load arbitrary files from the custom-node repository directly;
copy them to `ComfyUI/input/` or import them through Project Asset Carousel.
