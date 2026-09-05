# Example workflows

Choose the smallest workflow that matches your input. Start with **Normal**;
Studio adds an experimental editorial timeline but uses the same generation
loop.

For installation and first-run steps, see [Getting started](../docs/GETTING_STARTED.md).

## Quick choice

| Starting point | Recommended workflow |
|---|---|
| Text only | [T2V Normal](<T2V Normal - MiniMax H3.json>) |
| One opening image | [I2V Normal](<I2V Normal - MiniMax H3.json>) |
| First and last images | [FL2V Normal](<FL2V Normal - MiniMax H3.json>) |
| A few global Ref2VA references | [Ref2V Basic](<Ref2V Basic - MiniMax H3.json>) |
| Prompt-selected references | [Ref2V Tagged](<Ref2V Tagged - MiniMax H3.json>) |
| Prompt-selected references plus source audio | [Ref2V Studio Tagged Source Audio](<Ref2V Studio Tagged Source Audio - MiniMax H3.json>) |
| Video inpainting | [Masked Video Inpaint](<Masked Video Inpaint - MiniMax H3.json>) |
| Ref2VA-guided video inpainting | [Ref2V Masked Video Inpaint](<Ref2V Masked Video Inpaint - MiniMax H3.json>) |
| Continue one existing clip | [Masked AV Extension — Single Clip](<Masked AV Extension - Single Clip - MiniMax H3.json>) |
| Continue an existing clip across several scenes | [Masked AV Extension — Chain](<Masked AV Extension - Chain + Reference Image - MiniMax H3.json>) |
| Fill the gap between two clips | [Masked AV Bridge — Two Clips](<Masked AV Bridge - Two Clips - MiniMax H3.json>) |

## What the labels mean

| Label | Meaning |
|---|---|
| **Normal** | Standard Plan plus Scene Prompt Editor. Recommended starting point. |
| **Studio** | Experimental Plan Studio timeline and rich prompt editor. Sampling is unchanged. |
| **Experimental** | A useful test graph whose behavior is not a default recommendation. |
| **Muted recovery nodes** | Present for later assembly, but mode `2`; they do not run during generation. |
| **Bypassed node** | Mode `4`; forwards a compatible input without applying its operation. |

Most generation examples contain an intentionally muted recovery pair:

```text
[MUTED] Load Manifest  ──>  [MUTED] Assemble without rendering
```

Leave it muted while generating. To assemble an existing run, unmute both
nodes and queue only the recovery Assemble node. See the
[disabled-node guide](../docs/NODE_REFERENCE.md#how-disabled-nodes-are-shown).

## Text, image, and reference generation

| Workflow | What it demonstrates |
|---|---|
| [T2V Normal](<T2V Normal - MiniMax H3.json>) | Two text-generated scenes, standard editor, checkpoint/review loop, final assembly |
| [T2V Studio](<T2V Studio - MiniMax H3.json>) | The same T2V sampler with Plan Studio authoring |
| [I2V Normal](<I2V Normal - MiniMax H3.json>) | Opening image applied only to scene 1 through Frame Gate |
| [I2V Studio](<I2V Studio - MiniMax H3.json>) | The same I2V sampler with Plan Studio authoring |
| [FL2V Normal](<FL2V Normal - MiniMax H3.json>) | A→B→A endpoint sequence using Frame Index Switch and Frame Gate |
| [Ref2V Basic](<Ref2V Basic - MiniMax H3.json>) | Core Ref2VA with global references |
| [Ref2V Tagged](<Ref2V Tagged - MiniMax H3.json>) | Prompt-driven `@tag` references with the standard editor |
| [Ref2V Studio Tagged](<Ref2V Studio Tagged - MiniMax H3.json>) | Tagged references, Plan Studio, and project/run restoration tools |
| [Ref2V Studio Tagged Source Audio](<Ref2V Studio Tagged Source Audio - MiniMax H3.json>) | Tagged references plus a Source Timeline soundtrack |
| [Ref2V Sequential Motion — Experimental](<Ref2V Sequential Motion - EXPERIMENTAL - MiniMax H3.json>) | An advancing long motion-reference timeline combined with recursive context |

In I2V workflows, do not bypass **Frame Gate**. It prevents the opening image
from being reapplied to every scene.

For prompt syntax and timing, use [Scene authoring](../docs/SCENE_AUTHORING.md).
For `@tags`, schedules, motion references, and Source Timeline, use
[Scheduled references](../docs/SCHEDULED_REFERENCES.md).

## Masked editing and existing video

| Workflow | What it demonstrates |
|---|---|
| [Masked Video Inpaint](<Masked Video Inpaint - MiniMax H3.json>) | Recursive source-video editing with an H3-grid mask |
| [Ref2V Masked Video Inpaint](<Ref2V Masked Video Inpaint - MiniMax H3.json>) | The same mask path with a picture defining the replacement appearance |
| [Masked AV Extension — Single Clip](<Masked AV Extension - Single Clip - MiniMax H3.json>) | Continue one source clip from a protected AV prefix |
| [Masked AV Extension — Chain](<Masked AV Extension - Chain + Reference Image - MiniMax H3.json>) | Three reviewed extensions plus a tagged appearance reference |
| [Masked AV Bridge — Two Clips](<Masked AV Bridge - Two Clips - MiniMax H3.json>) | Protect both endpoints and generate the exact middle gap |

The masking examples use the bundled soldier-crab media. Copy the required
files from [`assets/`](assets/) into `ComfyUI/input/` before loading them.

The two-clip bridge is a single masked target with an ordinary sampler; it does
not pretend to be a recursive multi-scene run. The extension and inpaint
examples use the normal checkpoint, review, resume, and assembly loop.

See [Masked editing](../docs/MASKED_EDITING.md) for mask meaning, 32×32 H3
cells, tracked masks, audio protection, and outpaint preparation.

## Deferred upscale

These are second-pass workflows for a saved Context Loop run. They are not good
first-install tests.

| Workflow | Extra requirement | Use it for |
|---|---|---|
| [SeedVR2 Full Chain](<Deferred Upscale - SeedVR2 Full Chain - MiniMax H3.json>) | [ethanfel SeedVR2 fork](https://github.com/ethanfel/ComfyUI-SeedVR2_VideoUpscaler) | Decode the selected lineage into one disk-backed video, then upscale it in low-RAM chunks. |
| [H3 LBH 3D](<Deferred Upscale - H3 LBH 3D - MiniMax H3.json>) | [Comfyui_Minimax_h3_latent_Upscaler](https://github.com/LBH-123-AI/Comfyui_Minimax_h3_latent_Upscaler) and its 3D checkpoint | Upscale each saved H3 scene in a resumable child loop. |
| [H3 LBH 3D + De-Rope](<Deferred Upscale + De-Rope - H3 LBH 3D - MiniMax H3.json>) | LBH pack plus [ComfyUI-MAINodes](https://github.com/matlowai/ComfyUI-MAINodes) | Combine latent spatial upscale with the guarded De-Rope recovery path. |
| [Pixel DLSS5 + USDU — Experimental](<Deferred Upscale - Pixel DLSS5 + USDU - EXPERIMENTAL - MiniMax H3.json>) | [DLSS5](https://github.com/Blueforcer/ComfyUI-DLSS5-Enhancer), [H3 USDU Guider fork](https://github.com/lisitskyaa/ComfyUI_UltimateSDUpscaleGuider_H3), Turbo v4 LoRA | Per-scene IMAGE refinement with actual-size conditioning and preserved audio; [setup and testing limits](<guides/Deferred Upscale - Pixel DLSS5 + USDU - EXPERIMENTAL - MiniMax H3.md>). |

The attention override in both LBH examples is deliberately **bypassed**.
Large canvases can exceed the prequantized attention path's stride limits, so
the supplied graph keeps ComfyUI's normal attention backend.

Checkpoint Manager supplies the selected, verified scene lineage. Upscale
profiles save separately under
`output/h3_chains/<run>/upscaled/<profile>/`; they do not replace the source
checkpoints.

See [Runs and recovery](../docs/RUNS_AND_RECOVERY.md#whole-chain-seedvr2-finishing)
for caching, source-audio handling, pass-2 conditioning, and resume rules.

## Bundled assets

| File | Used by |
|---|---|
| `jigen_market_garden_doom_opening.png` | I2V and Ref2V examples |
| `jigen_market_garden_doom_last.png` | FL2V and Ref2V examples |
| `soldier_crabs_bribie_island_cc0.webm` | Masked inpaint, extension, and bridge examples |
| `soldier_crabs_inpaint_mask.png` | Masked inpaint examples |
| `soldier_crabs_reference_cc0.png` | Ref2V masked/extension examples |

Read [`assets/README.md`](assets/README.md) for exact copy instructions,
licenses, and provenance. ComfyUI does not load arbitrary files directly from a
custom-node repository; media must be copied or imported into its input area.

## Prompt and media credits

- T2V scene 1 is reproduced from a prompt shared by **🦙rishappi** in
  Banodoco's `#minimax_h3_chatter` on August 11, 2026:
  [original message](https://discord.com/channels/1076117621407223829/1532625331960152124/1536689209761599608).
- The I2V opening image and scene-1 prompt were shared by **ᴊɪɢᴇɴ** in
  Banodoco's `#minimax_h3_gens` on August 12, 2026:
  [prompt and image](https://discord.com/channels/1076117621407223829/1533677158067736777/1537180042210054226),
  [generated result](https://discord.com/channels/1076117621407223829/1533677158067736777/1537178443358142555).
- The soldier-crab examples use bundled CC0 footage and original repository
  prompts. They do not use or imitate the copyrighted *Crab Rave* soundtrack,
  music video, choreography, or branding.

Source notes are also embedded as visible notes in the relevant workflows.

## Archive

Maintained workflow JSON files stay directly in `example_workflows/` so
ComfyUI can discover them. Retired and older type-based examples live in
[`Archive/`](Archive/); use them only when reproducing an older graph.
