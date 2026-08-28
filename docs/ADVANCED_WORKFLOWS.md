# Advanced workflows

## Extend an existing video

Use **MiniMax H3 Existing Video Context** when scene 1 must continue a decoded
video rather than start from an empty timeline. The complete experimental model
is [Extend Existing Video Model Workflow - MiniMax H3](<../example_workflows/Archive/Extend Existing Video Model Workflow - MiniMax H3.json>).

```text
Plan ────────────────────────────────┐
Core Load Video (VIDEO) ─────────────┼→ Existing Video Context → Loop Start
Other loader IMAGE + AUDIO + FPS ────┘
H3 audio VAE ─────────────────────────────────────────────→ Loop Context
```

Use exactly one video route:

- `source_video` accepts native ComfyUI VIDEO, including embedded audio and
  exact FPS. An explicit audio input overrides embedded audio.
- `source_frames` accepts IMAGE from VHS or another decoder. Connect optional
  AUDIO and set the real decoded `source_fps`.

The adapter normalizes frames to the Plan canvas and H3's 24 fps, uses the last
`context_length` frames as scene 1's predecessor, and can persist the normalized
source as a prelude. In head mode:

```text
scene 1 delivered frames = raw frames - imported context frames
```

Connect the audio VAE to Loop Context for imported-audio timeline guidance in
`generated_audio` or `source_plus_timeline`. Visual continuation still works
without imported audio.

With `prepend_original=true`, Assemble places the normalized original before
generated scenes, including partial output. Arbitrary source codecs and frame
rates cannot be stream-concatenated safely, so the prelude is encoded once at
the Plan's `segment_crf`; generated H.264 segments remain stream-copied.

The imported tail is fingerprinted. Reconnect the same Plan and source when
resuming; a changed source correctly invalidates dependent checkpoints.

Recommended first settings:

```text
Chain Policy         Guide
encode_mode          video
anchor_mode          head
Loop Trim match_tail true
Spectrum             off
```

Chain Policy derives both visual and generated-audio overlap as 22 frames for
Guide. Use the Legacy 0.4 Policy Adapter only when this imported-context workflow
deliberately needs different visual and audio overlap lengths.

## Long visual context

`56` is a valid advanced context length. It carries 2.33 seconds of motion in
17 video latent steps, but head mode regenerates and removes all 56 frames from
every continuation. Start with `22`; use `56` when a long clip's camera move or
performance genuinely needs more history.

## Non-linear visual context

Scenes 2 and later normally take visual context from the immediately previous
timeline scene. **Visual context source** in Plan or Plan Studio can instead
select any earlier saved scene by stable scene ID:

```json
{
  "id": "scene_5",
  "visual_context_source": "scene_3",
  "context_length": 39,
  "video_blend_frames": 0
}
```

This changes only the picture-side continuation edge. In this example scene 5
uses scene 3's retained RGB/video latent, while Generated continuity still
uses scene 4's audio latent. The timeline, branch ancestry, soundtrack clock,
and final ordering remain 1 → 2 → 3 → 4 → 5. With head anchoring, the repeated
scene-3 prefix is removed by Loop Trim, so `video_blend_frames: 0` delivers a
hard cut from scene 4 to the newly generated part of scene 5.

Non-linear visual context requires a zero assembly blend because the visible
incoming timeline boundary is still scene 4 → scene 5. Checkpoint preflight
verifies both consumed dependencies independently: the selected visual scene
and, when enabled, the immediate generated-audio predecessor. Other earlier
scenes remain assembly-only and do not become false resume blockers.

### Selecting a source segment instead of its tail

Plan Studio's **Context** tab previews the complete delivered video for every
visual context block. The highlighted zone is the actual fixed-size context
window: its width is proportional to the configured frame span. Drag that
zone across the movie, place it near the player's current frame, or play only
the selected window. The position snaps to H3's native 17-frame / five-latent-
step temporal lattice. **Tail (default)**, or **Latest aligned (default)**
when that block's phase cannot end on the physical tail, removes the override.

The stored values are zero-based frame indexes within the source scene's
delivered video (after that source's own incoming overlap was trimmed):

```json
{
  "id": "scene_5",
  "context_length": 22,
  "visual_context_source": "scene_3",
  "visual_context_start_frame": 119,
  "video_blend_frames": 0
}
```

For an untrimmed source this selects delivered frames 119 through 140 from
scene 3. Valid numeric starts depend on the source's own trimmed incoming
prefix, so use Plan Studio instead of hand-authoring an arbitrary frame. The
backend converts both ends to native latent-step boundaries and slices the
saved video latent directly. It never replaces that crop with an RGB VAE
re-encode; RGB Guide/mask consumers use retained frames or a decode-only
mirror. Generated-audio continuity remains the immediate previous scene's
tail.

## Composed visual context

A continuation can use two saved picture histories back to back. In Plan or
Plan Studio, **Composed context first source** selects the scene placed first;
**Composed total / split** selects both the native H3 context total and how it
is divided. The ordinary **Visual context source** supplies the second block
immediately before the new generation:

```json
{
  "id": "scene_5",
  "context_length": 39,
  "visual_context_lead_source": "scene_4",
  "visual_context_lead_frames": 5,
  "visual_context_source": "scene_3",
  "video_blend_frames": 0
}
```

This example constructs one 39-frame visual prefix:

```text
scene 4 tail:  5 RGB frames /  2 video-latent steps
scene 3 tail: 34 RGB frames / 10 video-latent steps
result:       39 RGB frames / 12 video-latent steps
```

The selector groups every valid ordered split under its resulting total. `39`
offers `5+34`, `17+22`, `22+17`, and `34+5`; `56` offers both orientations of
`5+51`, `17+39`, and `22+34`; longer native totals continue the same pattern.
Choosing one combination writes that total to the scene's `context_length`
and the first span to `visual_context_lead_frames`.

The blocks are concatenated in their authored order; they are not blended or
interpolated. Both `22+17` and `17+22` now select source windows on the target
block's matching temporal phase and concatenate the saved latent crops
directly. For an inverse layout, the first block's latest aligned crop can end
before its source movie's physical tail; Plan Studio shows that position.
Both sources may be any distinct earlier scenes on the active
branch—the first source does not have to have a lower scene number than the
second. The composed prefix remains one context, so its normal head trim or AV
mask uses the selected total exactly once.

Composition changes only picture context. Generated audio remains one complete
latent tail from the immediately previous timeline scene, so there is no audio
splice at the internal visual seam and a scene's independent audio-context
override still works. Final assembly still follows normal scene order and must
use `video_blend_frames: 0` at this boundary. Checkpoint preflight verifies
both selected visual revisions plus the immediate audio predecessor when that
audio continuity is active.

The Context tab exposes one independent aligned range for each composed block. The
second block uses `visual_context_start_frame`; the first block uses
`visual_context_lead_start_frame`. Either or both may be omitted to use that
block's latest phase-aligned native crop.

## Last-frame destinations

When stock H3 Image to Video supplies `last_frame`, Motion Context preserves
that target on continuation scenes. The carried repeated head replaces a
conflicting `first_frame` anchor because both cannot own the same opening
coordinates.

Place official **MiniMax H3 Add Guide** nodes after Loop Context for additional
scene-local image, video, or audio anchors.

## Re-film a synchronized performance

The [three-angle guitar workflow](<../example_workflows/Three-Angle Guitar Ref2VA - EXPERIMENTAL - MiniMax H3.json>)
uses **Reference Video Prep** to convert native VIDEO or decoded IMAGE/AUDIO
into exact 24 fps Ref2VA input. Its soundtrack is copied without padding or
time-stretching, allowing one performance to be generated from multiple camera
angles in one pass.

Reference Video Prep rejects sources shorter than the requested H3-valid length
instead of silently padding or stretching them.

## External stitchers

Loop Trim's `images_with_overlap` output exposes part of the repeated visual
context while leaving its normal images and audio fully trimmed. Connect
**Current Shot → state** to **Loop Trim → state**. Loop Trim then resolves each
incoming scene's optional `video_blend_frames` override, or the Plan default
when the scene value is blank. Scene N controls the N−1→N boundary. Keep it at
`0` for a hard boundary. The old Plan/default and Current Shot/resolved integer
outputs remain compatibility sockets only; do not wire either one in a 0.5
workflow.
