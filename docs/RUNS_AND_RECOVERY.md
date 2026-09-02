# Runs, review, and recovery

## Review Gate

Place **Review Gate** between Segment + Checkpoint and Loop End. Each scene is
persisted before the gate waits, then the gate offers:

- **Approve & continue**
- **Generate next candidate** when a multi-take batch is not complete
- **Retry scene / seed / length**
- **Reroll seed**
- **Approve & stop**, optionally assembling a partial video

Set Review Gate's optional **candidate_count** above 1 to collect several
different-seed takes. The gate pauses after every saved candidate instead of
blindly generating the full batch. Use **Generate next candidate** to continue,
or accept the current scene early and interrupt the remaining batch. The
carousel previews every completed take with synchronized sound; arrow keys and
the visible dots move between them. Mark one or more takes to keep, then choose
the take that becomes the active continuation. Its saved video frames and AV
tensors—not the last generated take—become the context for the following scene.
The active take and checked alternatives remain in checkpoint history; unkept
alternatives are deleted only after the active checkpoint is promoted safely.
The default value of 1 keeps the normal one-take review behavior. The widget can
be converted to an input and driven by a regular INT node; the safety limit is
20 candidates per scene.

Notification sound, automatic timeout, and model unloading while waiting are
optional. Drag the bar below the player to resize it; double-click to restore
the default height.

When a Scene Prompt Editor or Rich Scene Prompt Editor is bound to the same
Plan, Review Gate selects the scene under review there automatically. Editor
changes are used by **Retry prompt / seed** or **Reroll seed** through the live
Plan prompt. In 0.5, Review Gate's own prompt field is disabled by default.
Restore it under **Settings → MiniMax H3 Context Loop → Interface → Review Gate
→ Enable prompt editing inside Review Gate**. When enabled, text explicitly
typed in that field wins for the submitted retry and is synchronized back to
the Plan and connected editor after the server accepts it.

During sampling, the optional floating **Cancel & reroll scene N** control
targets only the active H3 prompt. It waits for confirmed interruption, writes a
new explicit scene seed, moves Loop Start to that scene, preserves a bounded
range end, and queues normally. Once saving or review begins, Review Gate owns
the retry instead.

Disable the floating control under **Settings → MiniMax H3 Context Loop →
Interface → Cancel & reroll** without affecting Review Gate.

## Between-scene memory cleanup

Loop End can apply a runtime-only `between_scene_cleanup` policy after the
current scene and checkpoint are durable, immediately before it starts the next
scene or retry:

- `off` keeps ComfyUI's normal caches.
- `unload_models` unloads model weights and empties the device allocator.
- `fresh_scene` first asks ComfyUI's active RAM-pressure cache to evict reusable
  execution outputs and runs Python garbage collection, then releases remaining
  pinned model pages, unloads models, and empties the device allocator. Use it
  for chains that switch large models between scenes; the next scene will reload
  anything that was evicted.

The policy does not enter Plan or resume hashes. It deliberately preserves the
small recursive carry and dynamic graph result because ComfyUI has no supported
way to reset the entire executor while that graph is still resolving. On cache
types other than RAM pressure, `fresh_scene` still unloads models and clears
allocators, but no executor-output eviction callback is available.

## Resume

For a fresh run:

```text
run_name: choose a new name
start_clip: 1
scene_range: blank
```

To resume scene N, keep the original `run_name` and dependency settings, then
set `start_clip: N`. The loop loads checkpoint N−1 and validates all completed
predecessors. Editing scene N or later is safe; changing an earlier prompt,
seed, timing, source waveform, Plan compatibility setting, or
`generation_fingerprint` invalidates the dependent resume.

Loop Start's `verify_resume_history` switch is enabled by default. Disable it
only when you intentionally want scene N to consume the existing saved scene
N−1 despite a changed Plan. The override skips Plan/history matching; it does
not skip missing-file checks, SHA-256 artifact validation, checkpoint tensor
validation, or metadata's own recorded-history consistency. Consequently, any
new settings that describe the saved predecessor are not retroactively present
in its pixels or AV latent.

Plan-wide continuation mode and context length are the exceptions: they choose
how the next scene consumes its saved predecessor. Changing either does not
alter completed frames or their saved AV latent, so it does not invalidate the
prefix. If the checkpoint's cached decoded tail is shorter than the newly
requested context, the loop re-decodes its complete saved video latent and
extracts the longer tail without regenerating the scene. Explicit per-scene
continuation and context overrides remain part of that scene's history.

Review Gate's checkpoint browser can set up this resume and preview the joined
partial through the selected predecessor.

**Manifest Load** also supports interrupted runs. It discovers the longest
contiguous active checkpoint prefix beginning at scene 1, verifies every scene
and artifact through that point, and emits a partial manifest when later scenes
have not been saved. Connect that output directly to **Assemble** to recover the
finished prefix without sampling again. A missing scene ends the prefix; an
orphaned later checkpoint is never joined across the gap. When every planned
scene is present, the same node emits the normal completed manifest.

### Restore an earlier scene revision

**Refresh** in Review Gate discovers the active checkpoint and every immutable
revision retained for that scene. Choose the scene to resume, then select the
desired version of each predecessor under **Checkpoint history**. Clicking
**Restore & load** validates the selected MP4, safetensors checkpoint, hashes,
shared prompt, and compatibility contract before atomically promoting the
selected prefix. The corresponding prompts, seeds, lengths, steps, and scene
identifiers are restored into the connected Plan, and Loop Start is armed for
the next scene.

The active versions are selected by default. Restoring an earlier version does
not delete the current one, so another revision can be promoted later. Exact
continuation requires the revision's checkpoint metadata and safetensors file;
an MP4 copied from `segments/` or `reviews/` alone cannot recreate the saved AV
latent. When only video survives, use Existing Video Context as a re-encoded
continuation instead.

Retrying, rerolling, and candidate collection intentionally retain earlier
files as immutable revisions; they are recovery points rather than abandoned
temporary files. Inactive leaf revisions can be deleted from the same panel or
the dedicated Checkpoint Manager to reclaim space.
Review Gate now retrieves a fresh server-side deletion preview before asking
for confirmation. Active revisions and revisions with dependent later scenes
cannot be deleted. Cleanup is limited to that revision's segment, safetensors
checkpoint, prompt/audio/blend sidecars, unshared preview, and versioned
metadata; Plan archives, assets, prompt history, assembled exports, and other
revisions are never included.

## Checkpoint Manager

Connect the active Plan output to **MiniMax H3 Checkpoint Manager**. It passes
the Plan through unchanged and never pauses execution, so it can stay between
Plan and the next consumer. The connected Plan preselects its run; the run
selector can inspect any other folder under `output/h3_chains`.

The manager groups immutable scene revisions into inferred branches. A revision
can appear in more than one branch when it is their shared ancestor. Selecting
a revision shows its saved preview, prompt, seed, timing, canvas, storage,
parent, following scenes, and the exact video/audio frame context those
following scenes consume. Older checkpoints derive this graph from predecessor
revision and checkpoint hashes; newly saved checkpoints also carry a stable
branch id and effective context fields.

Plan chapters are checkpoint-management boundaries. The **All scenes** tab
shows a separate graph for each chapter. Selecting or activating a Chapter 2
branch changes only Chapter 2 pointers and connected Plan scene values; Chapter
1 keeps its current active branch. The chapter-start checkpoint can retain its
original predecessor as provenance, but that structural edge does not choose
the preceding chapter. Explicit visual or audio context recorded by a scene is
still preserved as a generation dependency.

If a branch ends with an empty next-scene slot and a compatible saved candidate
exists elsewhere, the graph displays a dashed empty card. Click it to preview
the available candidates and choose **Attach selected candidate**. This is
offered only when the candidate consumes neither predecessor video context nor
generated-audio continuity. The manager creates a new immutable lineage record
pointing at the chosen parent; the original video, audio, prompt, and checkpoint
files remain shared and are not regenerated or copied. Shared-file deletion is
reference-aware, so those files are retained until the last lineage record that
uses them is deleted.

If deleting the active branch tip rolls the run back while alternate leaf
revisions remain, select the surviving branch and click **Make branch active**.
The manager validates and promotes that revision's chapter lineage directly,
including when no Plan is connected. With an editable Plan connected, it also
restores the lineage's saved scene prompts, seeds, lengths, steps, context,
LoRA route, and boundary/audio overrides. Exact saved prompts reactivate their
existing Prompt Editor history revisions instead of adding duplicates.
Immutable revisions, workflow state, references, and assembled videos are left
untouched. You can then keep the chosen candidate active and continue deleting
the rejected inactive leaves.
**Load selected branch** remains the separate resume operation: it also restores
saved Plan inputs and arms Loop Start for the following scene.

Deletion is deliberately one scene revision at a time:

1. Select an inactive revision.
2. Inspect its complete file list, estimated reclaimed size, and preserved
   categories.
3. If later revisions depend on it, select and delete those leaf revisions
   first.
4. Confirm the now-safe leaf deletion. If anything changed after the preview,
   the server refuses it and asks for a fresh preview.

This first release does not bulk-delete branches. The leaf-first workflow makes
the exact context consequences visible and avoids silently orphaning later
checkpoints.

### Whole-chain SeedVR2 finishing

SeedVR2 is best treated as a final whole-video backend, not as another
scene-recursive H3 pass. Select the final scene of a complete branch in
Checkpoint Manager and use this graph:

```text
Checkpoint Manager.selected_manifest
        + original H3 video VAE
        ↓
Full-Chain Latent Video Adapter
        ↓ native, file-backed VIDEO
SeedVR2 Direct Video Upscaler
        ↓
core Save Video
```

**Full-Chain Latent Video Adapter** verifies and decodes the original
safetensors video latent for every selected scene; it never reads the saved
H.264 scene previews. It trims repeated context, applies the saved incoming
blend schedule, and writes one lossless RGB movie before SeedVR2 starts.
SeedVR2 therefore chunks a continuous timeline rather than restarting at H3
scene boundaries. A chain with Existing Video Context also streams its saved
prelude into the same movie.

`decode_buffer=disk-backed` is the recommended default. MiniMax H3's VAE keeps
its native temporal chunking but writes the decoded float scene into a
temporary mmap. The adapter converts and encodes one frame at a time, retaining
only the next boundary window in normal RAM, then deletes that scene buffer.
Peak ordinary RAM is therefore bounded by latent/model overhead and the blend
window instead of the decoded duration of the full chain. `memory` is a
compatibility fallback that holds one decoded scene at a time; neither mode
holds the whole production.

The continuous source is content-addressed and reused at:

```text
output/h3_chains/<run_name>/upscaled/seedvr2/source/<cache_key>.mkv
```

The cache key includes the immutable checkpoint lineage, VAE implementation,
blend schedule, prelude, and selected audio policy. Disable `reuse_cache` to
force a fresh VAE decode. `audio_source=plan` recovers the saved final-audio
policy and source audio directly from the manifest. Both an explicit Source
Timeline and a legacy AUDIO connected once at Loop Start are now materialized
as path-backed run state. Only manifests created before that legacy promotion,
and therefore lacking a recovery descriptor, need the optional `source_audio`
socket.

Use the audio-preserving **SeedVR2 Direct Video Upscaler** from
[ethanfel/ComfyUI-SeedVR2_VideoUpscaler](https://github.com/ethanfel/ComfyUI-SeedVR2_VideoUpscaler).
It reads the adapter movie in `chunk_size` batches, returns one file-backed
H.264 VIDEO, and embeds the source audio in that VIDEO so it can connect
straight to core Save Video. Its separate AUDIO output remains available for
alternate muxing graphs.

### Deferred H3 upscale child runs

Select the right-hand generated tip you want in Checkpoint Manager,
then connect its **selected_manifest** output to **MiniMax H3 Checkpoint Upscale
Adapter**. The manager verifies the immutable lineage and embeds recovery-only
compatibility and Source Timeline metadata directly. No source Plan, Chain
Policy, or decoded source media is retained by the recursive upscale graph:

```text
Checkpoint Manager → Upscale Adapter → Upscale Current Scene
                                      → backend graph
                                      → Upscale Segment Save
                                      → Upscale Loop End → H3 Chain Assemble
```

**Upscale Current Scene** prefers the optional `denoised_output` saved by
Segment + Checkpoint and falls back to the terminal sampler latent in older
checkpoints. It exposes the joint H3 AV latent as well as separate video and
audio latents:

- Combined-style nodes can consume `source_latent` directly.
- Video-only LBH nodes consume `source_video_latent`. **MiniMax H3 Pass-2 AV
  Prepare** recombines their output with `source_audio_latent`, performs
  NestedTensor-safe CONST re-noise on video only, and locks the saved audio
  with a zero denoise mask.
- LTX 2.5 is a decoded-video V2V path, not an H3-latent path. Decode the H3
  source latent, run the LTX refinement/upscale graph, and send its raw frame
  batch to Upscale Segment Save.

For H3 pass-2 conditioning, **Upscale Reference Conditioning** first reads the
exact cache descriptor recorded on the selected source revision. Tagged and
Scheduled Ref2VA create that cache automatically: native H3 reference latents
remain in safetensors while compact Qwen presentation frames allow the saved
compiled prompt to be tokenized again. **H3 Conditioning Sync From Latents**
then compares the original scene video latent with the actual LBH output. It
applies the exact horizontal and vertical scale to `match` picture
`minimax_refs` and `minimax_keyframes`, while preserving `max` picture refs at
their Core H3 capped geometry. Pictures already rebuilt from a cache-v2 RGB
master at the pass-2 canvas are not scaled twice. It updates changed reference
H/W metadata and deliberately leaves text, temporal positions, and audio
conditioning untouched. A de-rope target may have a longer video time axis;
sync accepts that deliberate difference because it changes only spatial
reference geometry. Upscale Reference
Conditioning's default `exclude_video_keep_audio` policy removes both the Qwen
motion-video presentation and native motion-video latent because the pass-2
source latent already contains the generated motion; audio paired with a video
reference is converted to an audio-only reference. `keep_video_native` and
`resize_video` remain available for comparison, and the sync node follows the
selected conditioning policy automatically. Build sampler 2's new
Guider from the returned conditioning rather than reusing the original Guider.
Thus the child graph needs no reference registry or original picture/video/audio
connections. Both cache versions retain the encoded native reference blocks
used by sync; cache v2 additionally keeps original picture masters for
workflows that choose target-resolution VAE re-encoding instead.

The bundled **Deferred Upscale + De-Rope - H3 LBH 3D** workflow wraps
[ComfyUI-MAINodes](https://github.com/matlowai/ComfyUI-MAINodes)' stable
decoded time-smear recipe in the child loop:

```text
source x0 → H3 Jerk Oracle → Chain De-Rope Guard → H3 Time Smear
          → H3 video VAE encode → LBH 3D → Chain De-Rope Continuity
          → H3 V2V Init + Inject Schedule → sampler
          → Exact/Audio Recover → re-encode → Chain Recovered AV
```

Guard forces the parent scene's repeated prefix to rate 1 and protects the
last 17 frames when another selected scene follows. It enables Time Smear's
`expand_to_end` only at the branch tip. Freeze Mask consumes Time Smear's final
`hold_map_used` (including legal-grid padding) and freezes the protected prefix
inside H3 V2V Init. For Drift-Control scene 2+, Continuity then replaces that
target-resolution prefix with the prior HQ tail before sampling.

Audio uses the identical hold map. Decode the source RAW audio latent, run H3
Audio Smear, VAE-encode it into H3 V2V Init, and recover the pass-2 audio after
sampling. The workflow seeds audio at strength 0.5 to keep dialogue timing
aligned but uses MAINodes' safe final preset that retains the original
performance. Segment Save's optional `recovered_audio` input trims the same
repeated RAW prefix as video and records the recovered result. Chain Recovered
AV rejects a still-dilated latent and packs the re-encoded world-clock video
and audio for optional full-latent saving and compact Drift-Control resume.

This is the stable pixel-smear route, not MAINodes' experimental temporal
latent insertion. The expanded IMAGE batch stays on CPU, but high-motion
scenes can still become two to three times longer internally. Narrow the
adapter's scene range or reduce oracle aggressiveness when RAM or wall time is
too high. Spatial upscale and de-rope remain in the same regeneration pass so
a later independent upscale cannot undo the recovered motion timing.

When pass 2 should use a different reference set, insert **Upscale Reference +
Prompt Override** on the normal `H3_TAGGED_REFERENCES` line and connect its
`references` and `prompt_override` outputs to **Upscale Reference
Conditioning**. An explicit registry replaces, rather than ambiguously merging
with, the compiled cache. The node can remove comma-separated tags without
renumbering references by hand; the conditioning node recompiles the resulting
prompt, Qwen presentation, and native blocks together. Leave its reference
input unconnected to retain the automatic cache route. Connected picture/video
refs require the original H3 video VAE, while activated standalone or paired
audio additionally requires the H3 audio VAE. No Plan or Source Timeline is
introduced; sequential/source-timeline live refs should be converted to a
scene-local restart/standalone reference before use in deferred upscale.

Upscale Reference Conditioning encodes the exact saved compiled prompt by
default. Its optional `prompt_override` is encoded instead when supplied, so a
user can provide a short appearance/detail-only pass-2 prompt without repeating
the source scene's motion or camera instructions. Automatic natural-language
motion stripping is intentionally avoided because it cannot reliably separate
action from identity, framing, or continuity clauses. The bundled LBH workflow
therefore leaves the override blank and uses the original compiled prompt by
default. Its How To Run note retains a neutral preservation/detail replacement
prompt for an explicit copy/paste A/B test.
Revisions without a cache can use `text_only`; select `error` when the second
pass must not proceed without Ref2VA conditioning.

Segment Save adopts each verified cache object into
`output/h3_chains/<run_name>/reference_cache/` and records only that run-local
descriptor. Copying or backing up the parent run therefore preserves everything
required to rebuild pass-2 Ref2VA conditioning.

Legacy checkpoints that still point into `output/h3_reference_cache/` migrate
without a rerender. Selecting their complete branch in Checkpoint Manager
hard-links the verified cache into the corresponding run (or copies it when a
hard link is unavailable) and returns a run-local descriptor. Migration never
deletes the global object or rewrites immutable revision metadata. Later branch
loads resolve the verified run-local equivalent first, so the old staging copy
can be archived or removed after a successful selection and upscale check.

Send the backend's decoded **raw** frame batch to both Segment Save and Loop
End. They remove the parent scene's repeated context head exactly once, persist
the delivered HQ segment, and carry optional HQ context to the next iteration.
Set a distinct `profile` for each recipe so settings and outputs cannot collide.
The profile folder is:

```text
output/h3_chains/<run_name>/upscaled/<profile>/
├── segments/
├── checkpoints/
├── prompts/
├── audio/
├── partial/
├── upscale_manifest.json
└── final/
```

`save_latent` defaults off. Segment Save still writes a small verified
safetensors checkpoint containing the assembly audio, so the child run remains
resumable and mergeable without duplicating the much larger HQ sampler latent.
When the following source scene uses Drift-Control AV, that checkpoint also
contains only the preceding scene's 12-step HQ video tail. Pass-2 AV Prepare
splices this tail into scene 2+'s prefix, gives it zero added noise and a zero
denoise mask, and refines only the new video region. This compact context is
enough for exact interruption-safe HQ continuation without enabling full
latent saving. Older child checkpoints without the tail safely protect their
independently upscaled source prefix and report that fallback in node status.
Enable full latent saving only when you want to reopen/refine the HQ latent
itself. The transient `upscaled_latent` connection on Loop End remains usable
for scene continuity whether or not persistence is enabled.

For new parent renders, connect SamplerCustomAdvanced `denoised_output` to
Segment + Checkpoint's optional `denoised_latent` input. Existing checkpoints
remain valid and use their terminal sampler output. Keep the parent branch
until every selected child scene has been persisted; a completed child profile
contains its own HQ video segments and audio needed by H3 Chain Assemble.
Assemble recognizes the upscale manifest, reconstructs a recoverable Source
Timeline from the embedded parent manifest, and keeps the canonical HQ result
under `upscaled/<profile>/final/`. Its normal `copy_to_output` and
`output_subfolder` controls can additionally publish the MP4 in ComfyUI's
regular output tree. Legacy source-track runs without the embedded descriptor
still need their original full AUDIO connected to Assemble.

## Run Manager

Connect the active Plan output to **MiniMax H3 Run Manager**. It discovers runs
under the ComfyUI host's `output/h3_chains`, including remote Docker hosts.
Select a run and choose **Load selected archive into Plan**; after confirmation
it restores archived prompts and Plan controls without changing graph links.

The two names at the top are deliberately separate:

- **Active Plan** is the connected Plan's current `run_name`. Generation and
  **Save assets to active Plan** use this name.
- **Selected archive** is only the folder highlighted in the browser. Selecting
  it does not change the Plan. **Load selected archive into Plan** is the only
  action that applies its archived prompts and settings.

When both names match, the archive is marked **ACTIVE PLAN**. When they differ,
the selected archive is labeled **not loaded**, so opening an old folder or
inspecting it cannot be mistaken for switching the generation run.

Restore prefers:

1. `api_prompt.json`;
2. `workflow.json`;
3. effective settings derived from `plan.json` for older runs.

The fallback retains exact scene lengths, steps, and seeds even when an old run
did not archive unused default-widget values.

## Archive reference assets

Connect loader outputs to Run Manager's dynamic **Connect loader asset** socket,
up to 12 assets. Classify each as Picture, Video, Audio reference, or Source
track so a short voice reference cannot be confused with a project soundtrack.

Wire all Semantic Picture Anchor nodes into one Semantic Anchor Bundle, then
connect the Bundle's **references** output to Run Manager's
**tagged_references** socket. The same line can feed Tagged Ref2VA and Plan
Studio. The interface discovers the Bundle's upstream image loaders and
archives/restores them as individual picture assets without consuming the 12
direct loader sockets.

- Archive images and audio default on.
- Archive video defaults off because video references can be large.
- Only files inside ComfyUI's input directory are eligible for fallback copies.
- Content-addressing deduplicates unchanged media and retains changed versions.

Restore first uses the original input-relative path. If it is missing and a
fallback exists, Run Manager copies the archived asset into a unique ComfyUI
input filename and updates a compatible loader. Targets are matched by persistent
binding identity, archived node ID/type, then unambiguous compatible loaders.
Ambiguous targets remain unchanged and are reported.

## Run folder contents

```text
output/h3_chains/<run_name>/
├── plan.json
├── workflow.json
├── api_prompt.json
├── manifest.json
├── prompt_history/<scene_id>/
├── segments/clip_0001.<revision>.mp4
├── segments/clip_0001.<revision>.prompt.txt
├── checkpoints/clip_0001.json
├── checkpoints/clip_0001.<revision>.json
├── checkpoints/clip_0001.<revision>.safetensors
├── generated_audio/
├── reference_cache/
├── upscaled/<profile>/
└── final/<filename>.mp4
```

Regenerating a scene updates its active checkpoint pointer but retains all
earlier MP4s, prompt sidecars, metadata, safetensors, and generated WAVs. Each
revision records what it supersedes.

Workflow and API graph metadata are embedded in segment/final files using
ComfyUI's standard tags. `workflow.json` is the preferred file to drag back
into ComfyUI; `plan.json` remains the authoritative effective render record.
Keep run folders private when workflows contain credentials.

## Assembly

Assemble accepts completed or partial manifests, including an interrupted
prefix reconstructed by Manifest Load. Its filename supports date
tokens such as `%date:yyyy-MM-dd%`, `%year%`, `%month%`, `%day%`, `%hour%`,
`%minute%`, and `%second%`. Existing files are never overwritten; numbered
suffixes are added automatically.

### Recovery blend schedules

`blend_schedule` can override the Plan's global visual blend only during
assembly. `plan` preserves the recorded setting. A comma-separated schedule is
applied to scene boundaries in timeline order: `5,30` uses five frames for the
first join and thirty for every later join because the last value repeats.
`0` produces hard cuts. This does not change checkpoints, prompts, seeds, or
generated frames.

When the requested boundary fits inside the saved blend MP4, assembly reuses
that artifact directly. If it requests more overlap than Segment Save retained,
connect the original MiniMax H3 video VAE to `blend_video_vae`. Recovery then
re-decodes the existing safetensors checkpoint into a temporary lossless RGB
video and deletes it after assembly. Diffusion is never rerun. The final video
still receives the one H.264 encode required by any pixel-space crossfade.

Each scheduled value must not exceed that incoming scene's repeated context.
For example, a chain whose first join has five context frames and later joins
have thirty-nine can use `5,30`; requesting thirty at the first join is rejected.

### Optional scene-one color stabilization

Set Assemble's `color_stabilization` to `scene_1_anchor` to counter gradual
exposure or saturation drift in a completed chain. Assembly measures a
center-weighted sample of the first generated scene, then fits only a weak,
bounded luma/saturation correction for each later scene. A correction is capped
at six code values of luma and six percent of saturation, at half the measured
strength.

This remains experimental. On the simplified 0.5 surface, right-click Assemble
and choose **Show advanced H3 controls** to reveal `color_stabilization` (and
the experimental `boundary_tone_match` control) without changing their saved
values or backend behavior.

The exact join inherits the preceding scene's accepted correction. Starting
after the retained overlap, that correction moves smoothly to the next scene's
target over 72 frames. Consequently the option cannot introduce a new grade
step at the boundary and does not change motion, timing, or audio. A prelude is
not used as the reference: the first generated scene remains the anchor.

This is an assembly grade, not diffusion conditioning. It does not change
checkpoints or future continuation input. It is disabled by default. Enabling
it uses the same single pixel-processing encode as a visual blend; on a hard-cut
assembly it replaces the otherwise lossless stream copy with one encode.

For an experimental correction that can influence later generation instead of
only the final MP4, choose **Color-Stable Drift AV** through Advanced Policy or
on a scene's incoming transition. It applies a bounded scene-one correction to
the disposable copied video latent as a VAE delta, tapering from zero to full
strength across the 39-frame context. Scene 1 remains the anchor, scene 2 is
neutral, and scene 3 onward can receive a corrected predecessor tail. It does
not alter the saved predecessor checkpoint or audio. Because this changes
generation conditioning, it is recorded in the incoming-boundary dependency
and is intentionally separate from this assembly-only option.

Enable `copy_to_output` to keep the canonical final in the run folder and also
publish an MP4 into the regular ComfyUI output tree. `output_subfolder` is
relative to that output root, supports nested folders and the same date tokens,
and may be empty to place the copy directly in `output/`. The existing
`filename` value is used for both copies, and collisions are versioned.

## Re-decode checkpoints to PNG

Connect a manifest and the original H3 video VAE to **Export PNG Sequence**. It
verifies each safetensors checkpoint, decodes one scene at a time, removes the
repeated overlap, and writes a continuous 8-bit RGB PNG sequence plus
`export.json` under:

```text
output/h3_chains/<run_name>/frames/<export_name>/
```

PNG compression is lossless. Use the same VAE, ComfyUI version, precision, and
decode settings for the closest reconstruction. The checkpointed latent is
exact, but a new VAE decode is not guaranteed to be bit-identical to an older
decode made under different settings.
