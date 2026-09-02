# Archived example workflows

The complete maintained 0.5 catalog is preserved unchanged in [`0.5/`](0.5/).
Those files retain their historical node types, positional widget values,
frontend metadata, prompts, and asset bindings for exact reproduction; they
are not recommended for a new 0.6 project.

The additional files directly in this Archive are still older mixed and
experimental examples retained for compatibility and reference. The clean 0.6
workflow catalog lives one level above this folder, beginning with
[`T2V Normal - MiniMax H3 0.6.json`](<../T2V Normal - MiniMax H3 0.6.json>) and
[`T2V Studio - MiniMax H3 0.6.json`](<../T2V Studio - MiniMax H3 0.6.json>).

`Ref2V Legacy Scheduled - MiniMax H3.json` and
`Ref2V Studio Legacy Scheduled - MiniMax H3.json` preserve the former active
Ref2V examples with explicit numeric scene selectors. The recommended Ref2V
examples now use prompt-driven Tagged nodes one level above this folder.

## V2 demos: choose single-image I2VA, core FL2VA, or Scheduled Ref2VA

[`Looping Single Image I2VA 20s V2 - MiniMax H3.json`](<Looping Single Image I2VA 20s V2 - MiniMax H3.json>)
is the simple long-form image-to-video starting point. It uses one opening
image, no last-frame input, and two requested 10-second scenes. The included
**First-Scene Image Gate** passes `<Picture 1>` to ComfyUI's stock
`MiniMaxH3ImageToVideo` only for scene 1; later recursive scenes receive no
first-frame keyframe and continue from saved H3 Motion Context. The prompt
editor marks Picture 1 active for scene 1 and inactive for scene 2.

H3 rounds each 10-second request up to 243 raw frames. With the example's
five-frame head overlap, the final delivery is `243 + (243 - 5) = 481` frames,
or 20.04 seconds at 24 fps. Duplicate the second Plan scene to extend the
chain; each additional requested 10-second continuation contributes 238 frames
(about 9.92 seconds). Replace the opening image and both generic motion prompts
before queueing.

[`Looping Core FL2VA V2 - MiniMax H3.json`](<Looping Core FL2VA V2 - MiniMax H3.json>)
is the scheduler-free starting point. It uses ComfyUI's stock
`MiniMaxH3ImageToVideo` with a deliberately one-scene, 124-frame plan so one
first/last keyframe pair is applied exactly once. The prompt follows H3's
FL2VA format and the Scene Prompt Editor previews both connected native Picture
labels. Disconnect the last image for a one-scene I2VA render, the first for
L2VA, or both for T2VA. For a multi-scene I2VA chain use the dedicated example
above; a globally connected keyframe would otherwise constrain every recursive
scene.

[`Looping Seamless Chain V2 - Scheduled Refs - MiniMax H3.json`](<Looping Seamless Chain V2 - Scheduled Refs - MiniMax H3.json>)
is the full fourteen-scene Ref2VA demonstration. It includes the large Scene
Prompt Editor, reference hover previews, Review Gate, muted recovery assembly,
and date/version-safe final filenames. Its schedule exercises every media
route:

- `@hero_face` is active only in scenes 1–7;
- `@hero_look` is always active and therefore renumbers from `<Picture 2>` to
  `<Picture 1>` beginning in scene 8;
- `@performance` and paired `@performance_audio` are active in scenes 4–6;
- the frame-exact `@song` slice is always active, moving from `<Audio 1>` to
  `<Audio 2>` while the paired soundtrack is present and back afterward.

Both workflows contain in-canvas operating notes. Replace their placeholder
media filenames and model selections before queueing. The older global-reference
workflow remains available unchanged for compatibility and comparison.

## Scheduled Ref2VA wiring

Version 0.3.10 adds a typed reference chain which can replace the stock
**MiniMax H3 Reference to Video** node inside the primary loop workflow:

```text
Picture Ref (scenes 1,3,5:8) ─→ Video Ref (scenes 1:4)
  ─→ Audio Ref (scene 3) ─→ Scheduled Ref2VA

Current Shot ─ prompt, clip_index, clip_count, width, height, length ─────↗
```

You may write stable aliases such as `@hero_face` in Plan scene prompts. They
are optional authoring conveniences rather than required H3 syntax. Scheduled
Ref2VA compiles them to the active scene's exact `<Picture N>`, `<Video N>`,
and `<Audio N>` numbering before expanding to ComfyUI's stock Ref2VA node.
Write all subject, video, and audio definitions directly in the Plan/Prompt
Editor; schedule nodes never inject hidden prompt text.
Video-paired soundtracks remain paired on the same dynamic index and receive a
separate tag (blank `audio_tag` derives `@<video_tag>_audio`). A scene may have
no active references; it still expands through the stock node with no dynamic
reference sockets.

To adapt the bundled global-reference loop without rebuilding its links by
hand, right-click its core **MiniMax H3 Reference to Video** node and choose
**Convert to MiniMax H3 Scheduled Ref2VA**. Existing connected reference
sockets become all-scene schedule entries; narrow their `scenes` fields and
replace fixed native labels in Plan prompts with the generated `@tags`.

## Three-Angle Guitar Ref2VA - Experimental - MiniMax H3

A one-pass performance re-filming experiment, rather than a recursive loop.
Core **Load Video** opens `3ClbaJYWVO4_000030.mp4`; **Reference Video Prep**
samples it at H3's 24 fps, selects 209 valid frames (8.708 seconds), and copies
the matching source-audio samples without padding or time-stretching. Stock
Ref2VA receives the synchronized picture/audio pair and a source-specific
three-angle prompt. At export, the original waveform replaces generated audio.

The prompt preserves the visible performer, plaid shirt, cream Telecaster-style
guitar, hand choreography, and musical timing while deliberately removing the
source product card, website watermark, text, and split-screen layout. Treat
this as experimental and select model paths available in your installation.

## Extend Existing Video Model Workflow - Experimental - MiniMax H3

A compact two-scene model for extending an existing MP4. Core **Load Video**
connects its native `VIDEO` directly to **MiniMax H3 Existing Video Context**.
VHS and other loaders can instead use the adapter's separate `IMAGE`, `AUDIO`,
and `source_fps` inputs. Scene 1 continues from the imported tail, generated
audio can inherit its ending, and `prepend_original` places the normalized
source before the generated extension.

The Review Gate is fully wired between **Segment Save** and **Loop End**, with
frame-locked preview audio from Loop Trim. Its recovery branch is muted by
default. Select your own source video and model files before queueing. This is a
new standalone example; none of the earlier workflow JSON files were changed.
Treat it as experimental until the imported video/audio continuation path has
received broader testing across source codecs, frame rates, and H3 setups.

## Looping Seamless Chain Global Refs Example - MiniMax H3

Disk-backed recursive Ref2VA chain using the visual H3 Chain Plan editor,
global character references, a frame-exact source-song timeline, per-segment
checkpointing, interruption resume, and final assembly. The recovery branch is
muted by default and can assemble an already completed chain without sampling
the last scene again. This is the primary workflow for
`ComfyUI-MiniMaxH3-Contex-Loop` and uses the uniquely named
`MiniMaxH3LoopTrim`, so it can run while NikoDemon80's upstream Motion Context
pack is installed.

Replace the supplied image/audio filenames and model selections with files
available in your ComfyUI installation. Scene-count and duration labels are
intentionally generic because both are controlled by the editable plan.

## Seamless Chain Global Refs 6 Clips - MiniMax H3

This is also a historical manual workflow rather than the recursive loop demo.
It is a six-clip Ref2VA chain with global character-reference images, 39-frame video
and timeline-audio context, optional full previous-clip audio references, and
sequential clip bypass controls.

Workflow and the underlying Ref2VA multi-reference/audio compatibility patch
were contributed by **seitanism** in the Banodoco MiniMax H3
seamless-extension thread: [original patch](https://discord.com/channels/1076117621407223829/1535700117452226560/1535771676158206032)
and [original workflow](https://discord.com/channels/1076117621407223829/1535700117452226560/1535771814452793474),
shared on 2026-08-08. Its original Motion Context node ids resolve through
NikoDemon80's upstream pack. Do not run the separately posted global patch
script alongside either marker-gated custom-node implementation.

Extra custom nodes used by the demo:

- [rgthree-comfy](https://github.com/rgthree/rgthree-comfy) for group controls
  and `Any Switch`.
- [ComfyUI-VideoHelperSuite](https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite)
  for preview/final video combining.

The workflow's optional full-audio-reference section is off by default. Keep
it off for the baseline test because a full Ref2VA audio reference can make
music restart or replay; Motion Context's 39-frame timeline-audio path remains
enabled independently.
