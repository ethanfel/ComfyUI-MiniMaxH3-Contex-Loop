# Getting started

This guide takes the shortest path from a clean install to one reviewed,
assembled video.

## 1. Install the packs

From `ComfyUI/custom_nodes`:

```bash
git clone https://github.com/seitanism/ComfyUI-H3-Motion-Context-MultiRef.git
git clone https://github.com/ethanfel/ComfyUI-MiniMaxH3-Contex-Loop.git
```

Restart ComfyUI. Use a current ComfyUI build with native **Add Guide for
MiniMax H3** support. `ffmpeg` is recommended for preview and assembly; PyAV is
the fallback where supported.

You also need your own MiniMax H3 diffusion model, text encoder, video VAE, and
audio VAE. They are not included in this repository.

## 2. Open the smallest matching example

| Your starting material | Recommended first workflow |
|---|---|
| Text only | [T2V Normal](<../example_workflows/T2V Normal - MiniMax H3.json>) |
| One opening image | [I2V Normal](<../example_workflows/I2V Normal - MiniMax H3.json>) |
| First and last images | [FL2V Normal](<../example_workflows/FL2V Normal - MiniMax H3.json>) |
| Prompt-selected references | [Ref2V Tagged](<../example_workflows/Ref2V Tagged - MiniMax H3.json>) |
| Existing video | [Masked AV Extension — Single Clip](<../example_workflows/Masked AV Extension - Single Clip - MiniMax H3.json>) |

Open or drag the JSON into ComfyUI. Start with a **Normal** workflow. Studio is
an optional editorial interface, not a simpler sampler.

Some examples use bundled media. Copy those files from
[`example_workflows/assets/`](../example_workflows/assets/) to `ComfyUI/input/`
before opening the workflow.

## 3. Resolve models and missing nodes

Set the four model loaders:

| Loader | Select |
|---|---|
| **Load Diffusion Model** | MiniMax H3 model |
| **Load CLIP** | H3 text encoder |
| **Load VAE — Video** | H3 video VAE |
| **Load VAE — Audio** | H3 audio VAE |

If ComfyUI reports a missing `MiniMaxH3MotionContext` node, install or update
the MultiRef companion pack and restart. If it reports missing native H3 nodes,
update ComfyUI.

Deferred-upscale examples need extra packs. Their requirements are listed in
the [workflow catalog](../example_workflows/README.md#deferred-upscale).

## 4. Edit only the first-run controls

### Plan

For a new graph, use **MiniMax H3 Plan (Modern)**. It keeps the established
vertical scene-column editor but groups its smaller control set into Project,
Canvas, Generation defaults, and Delivery. Its Generation Profile connection
is required, and it has no legacy context, audio, or continuation fallbacks.

The original **MiniMax H3 Context Loop Plan** remains unchanged so old workflows
open safely. After connecting Generation Profile, right-click it and choose
**Upgrade to Modern Plan…** to preserve its scenes, supported settings,
position, and links.

Set these values first:

| Control | First-run choice |
|---|---|
| `run_name` | A short unique name, for example `red_kite_test_01` |
| Width / height | Keep the example defaults |
| Scene Plan | Replace the sample scene prompts |
| Default duration | Keep the example default until the graph works |

`run_name` is the identity of the production. Reusing it exposes the same
checkpoint history; changing it starts a separate run.

Use the visual Scene Plan or Scene Prompt Editor for normal work. Raw Plan JSON
is an import/export and advanced-editing surface.

### Continuity and audio

For a new graph, connect **Generation Profile** to Plan and begin with:

| Control | Recommended value |
|---|---|
| Scene continuity | **Visual continuity** |
| Audio profile | **Generate audio** |

Some shipped examples still contain the compatible **Manual Chain Policy
(Legacy)** node. Its saved Guide/generated defaults are safe for a first run;
you do not need to rebuild the workflow before testing it.

### Review Gate

Keep `enabled = true`. Start with `candidate_count = 1`. Multiple candidates
are useful after the basic workflow is working.

## 5. Understand the disabled nodes

Most generation examples include two grey or muted recovery nodes:

```text
[MUTED] Load Manifest  ──>  [MUTED] Assemble — recovery
```

They are intentionally present but do not execute during generation. Leave
them muted for the first run. The active Assemble node connected to Loop End
handles normal final assembly.

A bypassed node is different: it forwards a compatible input without applying
its operation. Optional attention overrides in some upscale examples are
bypassed because they are not safe on every system.

See the [disabled-node legend](NODE_REFERENCE.md#how-disabled-nodes-are-shown)
for the notation used throughout these docs.

## 6. Queue and review

Queue the workflow normally.

1. **Preflight** validates timing, references, media, and resume compatibility
   before the large models load.
2. The loop renders and checkpoints one scene.
3. **Review Gate** opens with synchronized video and audio.
4. Choose an action:

| Action | Result |
|---|---|
| **Approve & continue** | Accept this take and render the next scene. |
| **Retry scene / seed / length** | Render the scene again from the same accepted predecessor. |
| **Reroll seed** | Give only this scene a new seed, then retry it. |
| **Approve & stop** | Accept this scene, optionally assemble a partial video, and stop cleanly. |

When `candidate_count` is greater than one, Review Gate displays saved takes in
a carousel. The selected take becomes the exact continuation for the next
scene; checked alternatives remain in checkpoint history.

After the final approval, Loop End emits a manifest and the active Assemble
node creates the final MP4.

## 7. Find the result

One run is stored under:

```text
ComfyUI/output/h3_chains/<run_name>/
├── checkpoints/     saved continuation state and revision data
├── segments/        reviewed scene media
├── final/           assembled MP4 and optional audio/subtitle sidecars
└── ...              manifests, previews, and recovery metadata
```

Exact subfolders can grow as review branches, project assets, or upscale
profiles are added. Use **Run Manager** or **Checkpoint Manager** instead of
manually changing active revision files.

## Assemble later without rendering

1. Open the same workflow.
2. Set Plan's `run_name` to the saved run.
3. Unmute the recovery **Load Manifest** and **Assemble** nodes.
4. Queue only the recovery Assemble node.

This reads the saved manifest and segments from disk. It does not execute the
sampler body.

## Common first-run problems

| Symptom | What to check |
|---|---|
| Preflight says the run already contains incompatible work | Use a new `run_name`, or restore the original generation settings. |
| Queue pauses after one scene | Review Gate is waiting for a decision. |
| Opening image appears in every scene | Keep **Frame Gate** active; do not bypass it. |
| No final MP4 appears | Approve the final scene and confirm the active Assemble node is enabled. |
| Recovery nodes render unexpectedly | Mute the recovery Load Manifest and Assemble pair. |
| Audio or preview tools fail | Install `ffmpeg`, or confirm ComfyUI's PyAV installation works. |
| A source-audio profile fails preflight | Connect a Source Timeline containing enough audio for the plan. |

For deeper diagnosis, use [Compatibility](COMPATIBILITY.md), [Audio and
continuity](AUDIO_AND_CONTINUITY.md), or [Runs and recovery](RUNS_AND_RECOVERY.md).
