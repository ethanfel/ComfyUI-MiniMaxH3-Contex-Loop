# MiniMax H3 Loop Plan Formatting Guide

This guide belongs to `ComfyUI-MiniMaxH3-Contex-Loop` and describes the JSON
accepted by `MiniMax H3 Context Loop Plan` (`MiniMaxH3ChainPlan`), including
scene lengths, prompts, seeds, steps, audio timing, and resume-safe settings.

## Visual editor or raw JSON

`H3 Chain Plan` includes a scene-card editor. Write shared continuity text and
scene prompts as normal multiline text; the editor stores them as readable
JSON line arrays automatically. Drag scenes to reorder them, duplicate or
delete cards, and choose inherited duration, seconds, or exact H3 frames. The
timing label on every card shows raw and delivered frames, while the header
shows total delivered runtime. Scene cards receive distinct colors
automatically; use the small header swatch to customize one, or double-click
the swatch to restore its automatic color. Colors are UI-only and do not alter
the plan or checkpoint compatibility.

The compact **Output** button with its outline folder-open icon in the Plan
header creates and opens the current `output/h3_chains/<run_name>` directory on
the ComfyUI host. When the host is headless or its systemd service cannot
access a desktop session, the button copies the absolute host path instead.

The optional **MiniMax H3 Scene Prompt Editor** companion connects to the Plan
and provides a larger, adjustable-font view of one scene prompt at a time. Its
textarea is bidirectionally synchronized with the active
`plan_json.shots[n].prompt`; only the active scene and font-size preferences are
stored on the companion itself. Arrow buttons and `Alt+Left/Right` navigate
scenes, while `@` opens reference tags and `#` inserts dialogue markup.

Its optional **Prompt Assistant** connects to a running `comfyui-mcp
--panel-orchestrator` and can ask Codex or Hermes to discuss, rewrite, shorten,
critique, or improve continuity for the active scene. Shared and adjacent scene
context are controlled by checkboxes; selected text is included automatically.
The agent's proposed replacement is staged below the chat and remains editable.
Only **Apply to scene** changes `shots[n].prompt`. A source-revision fence warns
and asks for confirmation when manual edits landed after the request began.

Inside a prompt, type `@` or click **@ Reference** to insert one of the
references actually connected and active for that scene. Core conditioning
inserts native `<Picture N>`, `<Video N>`, or `<Audio N>` labels; Scheduled
Ref2VA offers optional stable `@aliases` which compile to those labels. Select
dialogue text and type
`#`, or click **# Dialogue**, to wrap it in `<d>...</d>`. These interactions
are authoring shortcuts only; they produce ordinary MiniMax prompt text.
When the editor can trace the Plan downstream to Scheduled Ref2VA, core
Ref2VA, or core Image-to-Video, the tray shows the references actually wired
for that scene. Hover to preview loaded media. Core FL2VA exposes its connected
first and last frames as `<Picture 1>` and `<Picture 2>`; L2VA with only a last
frame correctly exposes that frame as `<Picture 1>`. When a core I2V first
frame passes through **MiniMax H3 First-Scene Image Gate**, Picture 1 is active
only in scene 1 and is omitted from the menu on continuation scenes.

The experimental **Rich Scene Prompt Editor** adds color-coded tokens, larger
media previews, prompt guides, revision history, and one-click **Optimize**.
Its optimizer connection is global rather than stored on the node or in the
workflow. Open **ComfyUI Settings → MiniMax H3 Context Loop → Prompt
optimizer** and choose:

- **Direct API** (default) for an OpenAI-compatible Chat Completions endpoint,
  the OpenAI Responses format, or Gemini Native. Enter the server URL and model;
  an API key is optional for local OpenAI-compatible servers and required for
  Gemini Native.
- **MCP agent** to use a provider advertised by the compatible separately
  installed `comfyui-mcp` prompt bridge.
- **Disabled** to turn off optimizer execution while keeping manual Studio
  editing available.

Reference-media reading is a separate opt-in setting and is off by default.
When enabled, only reference files resolvable inside ComfyUI's input, output,
or temp roots are considered. OpenAI-compatible and Responses requests attach
images; Gemini Native can also receive video and audio. Provider credentials
are saved in ComfyUI user settings and are never serialized into workflow JSON.

Use the editor's **JSON** button when you need to inspect, paste, import, or
export the underlying plan. The JSON format below remains the runtime contract
and existing plans are backward compatible.

The Plan also exposes an optional forced STRING socket named
`plan_json_input`. Connect an LLM node, local story director, reusable STRING,
or any other provider-independent JSON source. A non-empty upstream string is
the execution source and receives the same normalization and validation as the
internal JSON; an empty string or disconnected socket uses the visual editor's
stored `plan_json`. While connected, the visual editor clearly labels its cards
as the editable fallback. This socket replaces only the scene-plan JSON—Plan
settings such as `run_name`, dimensions, context, and audio mode remain their
own inputs.

## Copy/paste workflow note

The following block is intentionally compact enough to paste into a ComfyUI
Note node:

```text
H3 LOOP PLAN — QUICK FORMAT

Use the built-in H3 Chain Plan scene editor, or open its JSON panel and paste
valid JSON. Use double quotes, no comments, and no trailing commas.

{
  "prompt_prefix": "Global subject, wardrobe, style and continuity rules.",
  "defaults": {
    "duration_seconds": 15,
    "steps": 20
  },
  "shots": [
    {
      "id": "intro",
      "prompt": [
        "Use <Picture 1> for the subject's identity and physical features.",
        "Her wardrobe remains unchanged throughout the sequence.",
        "",
        "Begin with an opening tracking shot backstage.",
        "End while she is opening the corridor door."
      ],
      "seed": 123
    },
    {
      "id": "street",
      "prompt": [
        "Continue through the already-opening door without resetting her stride.",
        "Keep the incoming camera direction, lighting and subject pose.",
        "",
        "Move from the corridor into the street.",
        "End with the camera beginning a left orbit."
      ],
      "duration_seconds": 10,
      "steps": 24,
      "seed": 456
    },
    {
      "id": "outro",
      "prompt": [
        "Continue the unfinished left orbit from the previous scene.",
        "Resolve the performance and finish on a calm wide composition."
      ],
      "length": 124
    }
  ]
}

SCENE OVERRIDES
- prompt can be one string OR an array of readable lines. The node joins array
  entries with real line breaks. Use an empty string entry for a blank line.
- duration_seconds: requested generated duration; rounded UP to H3's 17k+5 grid.
- length or frames: exact raw frame count; must be 5, 22, 39, 56...3592.
- steps: sampler steps for this scene, 1–10000.
- seed: fixed uint64 seed. Omit it for a deterministic seed from base_seed.
- id: unique scene name used by checkpoints. Changing it can change an auto seed.
- prompt: scene-specific text. It may be blank or omitted when prompt_prefix
  (or global_prompt) is non-empty; otherwise a prompt is required.

LENGTH AT 24 FPS, context=22, anchor=head
- 5 seconds  -> raw 124 frames; clip 1 delivers 124, later clips deliver 102.
- 10 seconds -> raw 243 frames; clip 1 delivers 243, later clips deliver 221.
- 15 seconds -> raw 362 frames; clip 1 delivers 362, later clips deliver 340.
Later clips lose the 22 repeated context frames after Trim. Use length for
frame-exact control. Every non-final shot must deliver at least the effective
incoming context requested by the following scene.

PRECEDENCE
shot value > JSON defaults > H3 Chain Plan node defaults.

RECOMMENDED PLAN SETTINGS
- width/height: multiples of 32; 960x544 is a good starting point.
- Transition Policy: Guide (22 frames); Latent Guide keeps Guide behavior but
  directly reuses a generated predecessor's saved latent. Use experimental
  Detail AV, Drift-Control AV, Hard AV, or Soft AV (39 frames) only for
  same-shot target-latent continuation. Drift-Control AV additionally routes
  MODEL through Chain Context and is initially validated at 20 steps.
- encode_mode: video
- anchor_mode: head
- crop: disabled
- Audio Policy for an exact music track: Source / source reference on /
  generated continuity off.
- Legacy fallback: context_length 22, continuation_mode guide, audio_mode
  source_track.
- segment_crf: 18–20

RUN / RESUME
- New run: unique run_name and Loop Start start_clip=1.
- Resume at scene N: keep the same settings and run_name; set start_clip=N.
- Optional bounded run: set scene_range to `N` or inclusive `N:M`. A
  non-empty range overrides start_clip and must remain contiguous.
- The Review Gate can discover saved checkpoints and set start_clip for you:
  Refresh, select Resume scene N, then press Load checkpoint.
- Approve & stop can join all accepted scenes into a partial MP4. Checkpointed
  audio is the default; wire the full song to source_audio to use source audio.
- Optional model unloading releases VRAM while the gate waits. Continuing must
  reload models; stopping ends the execution without a reload.
- Changing a completed scene's prompt, seed, length, model settings, references,
  or source audio invalidates its checkpoint history.
- Change generation_fingerprint whenever model, VAE, LoRA, references, CFG,
  scheduler, or another generation dependency changes.

SOURCE-TIMELINE WIRING
Register video/audio once with Source Timeline. Connect the descriptor to
Preflight (or Plan Studio) and Loop Start. Current Shot obtains scene slices
from state and Assemble recovers the descriptor from the manifest. The source
song must cover the complete delivered video duration.
```

## Complete JSON shape

`plan_json` accepts either a plan object or a bare list of shots:

```text
Plan = {
  "prompt_prefix"?: string | string[],
  "global_prompt"?: string | string[], // alias of prompt_prefix
  "defaults"?: {
    "duration_seconds"?: number,
    "steps"?: integer
  },
  "shots": Shot[]
}

Shot = string | {
  "id"?: string,
  "prompt"?: string | string[],
  "duration_seconds"?: number,
  "length"?: integer,
  "frames"?: integer,             // alias of length
  "steps"?: integer,
  "seed"?: integer | digit string,
  "lora_route"?: "base" | "a" | "b" | "c" | "d",
  "context_length"?: 0 | 1 | 5 | 22 | 39 | ... | 243,
  "audio_context_length"?: integer, // 0..240
  "continuation_mode"?: "guide" | "tone_carry_guide" | "latent_guide" | "tapered_guide" | "masked_av" | "tapered_av" | "feathered_av" | "audio_feathered_av" | "drift_control_av"
}
```

The notation above explains the structure; it is not JSON because it contains
comments and `?` markers. Actual `plan_json` must be strict JSON:

- use double quotes around keys and strings;
- do not include comments;
- do not leave a trailing comma;
- encode line breaks inside prompts as `\n`;
- include between 1 and 128 shots.

## Top-level plan fields

| Field | Required | Meaning |
|---|---:|---|
| `shots` | Yes | Ordered list of scenes. Each entry can be an object or a prompt string. |
| `prompt_prefix` | No | String or array of lines prepended to every scene prompt, separated by one blank line. Use it for identity, wardrobe, style, camera, and continuity rules shared by all scenes. |
| `global_prompt` | No | Alias for `prompt_prefix`. `prompt_prefix` wins when both are present. |
| `defaults.duration_seconds` | No | JSON-level default scene duration. Overrides the node's `default_duration_seconds`. |
| `defaults.steps` | No | JSON-level default sampler steps. Overrides the node's `default_steps`. |

For convenient pasting, top-level `duration_seconds` and `steps` are also
accepted as aliases and moved into `defaults` when **Apply JSON** is clicked.
The canonical JSON shown afterward always uses the `defaults` object.

Precedence is always:

```text
per-shot value > JSON defaults > H3 Chain Plan node value
```

## Per-scene fields

| Field | Required | Rules and behavior |
|---|---:|---|
| `prompt` | Conditional | Scene-specific string or array of strings. It may be blank or omitted when `prompt_prefix`/`global_prompt` is non-empty. Array entries are joined with real newlines; use `""` for a blank line. The shared prefix is prepended automatically. |
| `id` | No | Unique checkpoint identifier. Defaults to `clip_0001`, `clip_0002`, etc. Unsupported filename characters become `_`; the result is limited to 96 characters. |
| `duration_seconds` | No | Positive requested raw generation duration. It is rounded up to a valid H3 frame count. Ignored when `length` or `frames` is present. |
| `length` | No | Exact raw frame count. Must be between 5 and 3592 and satisfy `length % 17 == 5`. |
| `frames` | No | Alias for `length`. `length` wins when both are present. |
| `steps` | No | Sampler steps for this scene, from 1 to 10000. |
| `seed` | No | Fixed unsigned 64-bit seed, from 0 to 18446744073709551615. A decimal digit string is also accepted and lets browsers preserve values above JavaScript's exact integer range. When omitted, the seed is derived deterministically from `base_seed`, scene index, and scene `id`. |

A shot can also be only a prompt string:

```json
{
  "shots": [
    "Opening scene.",
    "Continue through the doorway.",
    "Finish on a wide sunrise shot."
  ]
}
```

String shots use automatic IDs, the default duration and steps, and derived
seeds.

## Setting scene length

MiniMax H3 runs at 24 fps and accepts only raw lengths on this grid:

```text
5, 22, 39, 56, 73, ... 3592 frames
```

Equivalently:

```text
length % 17 == 5
```

### Use seconds for convenience

```json
{
  "id": "closeup",
  "prompt": "Continue into a close tracking shot.",
  "duration_seconds": 5
}
```

The node converts seconds using:

```text
requested_frames = ceil(duration_seconds × 24)
raw_frames = the next frame count where raw_frames % 17 == 5
```

It always rounds up. The generated duration can therefore be longer than the
number entered.

| Requested | Raw frames | Raw duration | Delivered by clip 1 | Delivered by later clip with 22-frame head context |
|---:|---:|---:|---:|---:|
| 0.2 s | 5 | 0.208 s | 5 frames / 0.208 s | Invalid: not longer than the overlap |
| 1 s | 39 | 1.625 s | 39 frames / 1.625 s | 17 frames / 0.708 s |
| 5 s | 124 | 5.167 s | 124 frames / 5.167 s | 102 frames / 4.250 s |
| 10 s | 243 | 10.125 s | 243 frames / 10.125 s | 221 frames / 9.208 s |
| 15 s | 362 | 15.083 s | 362 frames / 15.083 s | 340 frames / 14.167 s |
| 30 s | 736 | 30.667 s | 736 frames / 30.667 s | 714 frames / 29.750 s |

### Use frames for exact control

```json
{
  "id": "outro",
  "prompt": "Resolve the movement and end the performance.",
  "length": 124
}
```

Use `length` when exact H3 timing matters. Invalid examples include `120`,
`240`, and `360`; the nearby valid values are `124`, `243`, and `362`.

### Raw length versus delivered length

With the recommended `anchor_mode: head`, the beginning of every continuation
contains the previous scene's repeated context. `MiniMax H3 Context Loop Trim`
removes that overlap:

```text
clip 1 delivered frames = raw_frames
later delivered frames  = raw_frames - that scene's effective context_length
```

The Trim node's optional `images_with_overlap` output can retain the requested
number of repeated visual frames for an external stitcher. Its standard
`images` output remains fully trimmed, and audio always removes the complete
overlap from its public waveform. With `match_tail` enabled, that same AUDIO
value privately carries the full decoded overlap directly to Segment Save.
Generated-audio assembly lets a later masked-AV scene own that interval, so a
Soft AV audio release is not discarded. No additional audio socket or wire is
needed. Visual assembly remains independent and uses its configured overlap.

Generated-audio assembly derives each scene's sample budget from cumulative
delivered frame boundaries. This distributes fractional samples across the run
instead of independently rounding every scene, preventing boundary rounding
from accumulating into long-run A/V drift. New masked-AV checkpoints also save
the current scene's decoded overlap; old checkpoints without it retain the
legacy delivered-only hard-cut fallback.

For `context_length: 22`, a later scene with `length: 362` contributes 340 new
frames, or 14.167 seconds, to the final video. The source-audio window still
covers all 362 raw frames and begins 22 frames before the prior delivered end,
so its overlap matches the repeated picture context.

For the dedicated single-image I2VA example, each requested 10-second scene
rounds up to 243 raw frames and `context_length: 5`. Two scenes therefore
deliver `243 + (243 - 5) = 481` frames, or 20.04 seconds at 24 fps. The
First-Scene Image Gate supplies the opening image only to scene 1; scene 2 has
no Picture label and relies on incoming motion context.

With `anchor_mode: before`, no repeated head is delivered, so every scene
delivers its complete raw length. This mode is retained for experimentation;
`head` is the tested and recommended mode.

Every non-final scene must deliver at least the next scene's effective
`context_length` so that scene has enough context. The plan rejects shorter
predecessors before render; a next-scene override of `0` needs none.

## Prompt formatting

For human editing, use an array of lines instead of writing escaped `\n`
characters. The node joins entries with real newlines. Use an empty string
entry when you want a blank line:

```json
{
  "shots": [
    {
      "id": "arrival",
      "prompt": [
        "Use <Picture 1> for her facial identity, hairstyle, skin tone, age, body proportions, and distinctive physical features.",
        "Her wardrobe is the outfit defined here.",
        "",
        "Throughout every scene S1 wears the same fitted thigh-length dove-grey designer cocktail dress in opaque structured fabric with a deliberate low cleavage cutout, carries a small black designer handbag, and wears black high-heeled pumps.",
        "",
        "<Subject 2> (S2) enters from camera right."
      ]
    }
  ]
}
```

This reaches MiniMax as:

```text
Use <Picture 1> for her facial identity, hairstyle, skin tone, age, body proportions, and distinctive physical features.
Her wardrobe is the outfit defined here.

Throughout every scene S1 wears the same fitted thigh-length dove-grey designer cocktail dress in opaque structured fabric with a deliberate low cleavage cutout, carries a small black designer handbag, and wears black high-heeled pumps.

<Subject 2> (S2) enters from camera right.
```

Put stable information in `prompt_prefix` and only scene-specific changes in
each `prompt`; both fields accept the same readable array format:

```json
{
  "prompt_prefix": "<Subject 1> keeps the same face, yellow-and-pink hair, black cropped T-shirt, ripped jeans and silver chain. Photorealistic continuous music-video take with no cuts.",
  "defaults": {
    "duration_seconds": 15,
    "steps": 20
  },
  "shots": [
    {
      "id": "backstage",
      "prompt": "Track backward as <Subject 1> walks through the backstage room. End with her opening the corridor door."
    },
    {
      "id": "corridor",
      "prompt": "Continue the same stride and camera movement through the already-opening door. End with the camera beginning a left orbit."
    }
  ]
}
```

When the same complete prompt should drive every scene, scene prompts can be
empty or omitted:

```json
{
  "prompt_prefix": "The complete shared MiniMax prompt used for every scene.",
  "shots": [
    {"id": "scene_01", "length": 362},
    {"id": "scene_02", "length": 362}
  ]
}
```

For seamless results, each continuation prompt should explicitly preserve the
incoming action, camera direction, subject pose, lighting, and unfinished
movement. End each scene with an action still in progress, then begin the next
prompt by continuing that exact action.

## Seeds and steps

Use fixed seeds when a plan must be exactly reproducible:

```json
{
  "shots": [
    {
      "id": "scene_01",
      "prompt": "Opening scene.",
      "seed": 983590410766495,
      "steps": 20
    }
  ]
}
```

When `seed` is absent, a deterministic seed is derived from:

```text
base_seed + scene index + scene id
```

The same plan and `base_seed` produce the same derived seeds. Changing a scene
ID or moving it to another position changes its derived seed.

`lora_route` selects a pre-patched MODEL input on **MiniMax H3 Scene LoRA
Scheduler**. Omit it or use `base` for the unpatched route; `a` through `d`
select LoRA A-D. The scheduler is not a loader: create each branch with the
ordinary ComfyUI LoRA loader already used by the workflow, and stack loaders
when one scene needs several LoRAs. Because its MODEL inputs are lazy, only the
active scene's selected branch is evaluated. Route selection is stored in the
Plan and checkpoint revision as provenance, but is deliberately excluded from
checkpoint/resume verification. LoRA filenames and strengths remain external;
include them in `generation_fingerprint` only when strict invalidation is
desired.

`continuation_mode` describes the transition from the preceding clip into this
scene. Omit it to inherit the Plan node setting. Use `guide` when this is a new
shot that should retain motion/appearance context while allowing a different
camera, action, or environment. Use `latent_guide` for the same behavior while
reusing a compatible generated predecessor's sampled video latent directly;
imported context falls back to RGB/VAE Guide. Use `masked_av` when it directly
continues the same shot and should preserve the preceding AV prefix exactly.
Use experimental `tapered_av` for the same 39-frame hard-mask geometry while
conditioning on a deterministic, disposable video-only latent-noise copy; it
does not alter carried audio or the accepted predecessor checkpoint.
Use experimental `drift_control_av` to keep that predecessor latent clean while
the sampler moves its disposable prefix to the next scheduler sigma on every
evaluation. It is fixed to 39 context frames, uses an 8+4 clean-seam taper,
and requires the H3 MODEL to pass through Chain Context's MODEL sockets.
Scene 1 uses the field only when Existing Video Context supplies a predecessor.

`context_length` overrides incoming video context for one scene. Omit it (or
leave the visual selector blank) to inherit the Plan node setting. Set it to
`0` for a completely new visual scene. Positive values use the same native H3
choices as the Plan setting. Scene 1's override applies when Existing Video
Context is connected.

`audio_context_length` independently controls prior generated sound in guide
mode. Blank inherits the Plan audio setting; when that Plan setting is `0`, it
follows the scene's effective video context. An explicit per-scene `0` means no
audio carry, while a positive value can continue sound with video context `0`.
It applies to `generated_audio` and `source_plus_timeline`; `source_track` uses
its exact timeline slice. Masked AV ignores the independent value and preserves
audio for the same physical interval as its video prefix.

The compact Plan editor places these controls beside Steps under **Show
advanced**; Plan Studio keeps them in the existing scene-properties row.

## H3 Chain Plan node settings

| Setting | Accepted values | Recommended use |
|---|---|---|
| `run_name` | Filename-safe text; normalized to at most 96 characters | Give each independent render a unique name. Keep it unchanged only when resuming. |
| `generation_fingerprint` | Any stable version string | Include model, VAE, LoRA, global-reference, CFG, sampler, and scheduler versions. Change it when any external generation dependency changes. |
| `width`, `height` | Positive multiples of 32, UI range 32–4096 | `960 × 544` is the supplied long-form workflow setting. |
| `transition_policy` | Cut, Guide, Tone Guide, Latent Guide, Detail Guide, Detail AV, Drift-Control AV, Hard AV, Soft AV policy wire | Preferred 0.5 incoming-boundary control. |
| `audio_policy` | Independent final/reference/continuity policy wire | Preferred 0.5 audio-intent control. |
| `continuation_mode` | `guide`, `tone_carry_guide`, `latent_guide`, `tapered_guide`, `masked_av`, `tapered_av`, `feathered_av`, `audio_feathered_av`, or `drift_control_av` | Legacy/advanced implementation override for scenes without `shots[n].continuation_mode`. `latent_guide` needs video encode mode and at least 5 positive context frames; `tapered_guide` accepts normal Guide context lengths and 22 is its published baseline; experimental `tapered_av` and `drift_control_av` are fixed to 39 frames. Drift-Control AV also needs Chain Context's MODEL route. |
| `context_length` | `0`, `1`, then native runs `5`, `22`, `39`, ... `243` | Legacy/advanced exact context. Guide accepts the native runs; AV requires the shared-clock subset `39`, `90`, `141`, `192`, or `243`. |
| `encode_mode` | `video` or `frames` | Use `video`. It preserves motion inside the VAE latent and is more efficient. |
| `anchor_mode` | `head` or `before` | Use `head`; wire `trim_frames` into MiniMax H3 Context Loop Trim. |
| `crop` | `disabled` or `center` | Use `disabled` when references and output already share the intended framing. |
| `audio_mode` | `source_track`, `generated_audio`, or `source_plus_timeline` | Legacy 0.4 fallback when Audio Policy is unconnected. |
| `audio_context_length` | `0`–`240` frames | In generated-audio modes, `0` follows the video context length; `22` is the tested explicit value. It is unused for video-only context in `source_track`. |
| `default_duration_seconds` | Positive seconds, up to 149.667 s | Used only when JSON defaults and the scene both omit a length. |
| `default_steps` | `1`–`10000` | Used only when JSON defaults and the scene both omit steps. |
| `base_seed` | Unsigned 64-bit integer | Source for deterministic seeds when a scene omits `seed`. |
| `segment_crf` | `0`–`51` | H.264 checkpoint-segment quality. Lower is higher quality and larger. Start around `18`–`20`. |

### Which audio mode should I use for a voice?

The Plan's `audio_mode` controls the chain timeline and final soundtrack. It
does not turn scheduled `@voice` / native `<Audio N>` references on or off.

- Use `source_track` when you have the finished spoken performance, dialogue,
  vocal, or song and want that exact recording in the final video. Connect the
  complete track to Loop Start and Assemble, then route Current Shot's
  frame-exact slice into Ref2VA or Scheduled Audio.
- Use `generated_audio` when you have only a short voice identity, accent, or
  timbre reference and want H3 to generate new speech/sound described by the
  prompt. Schedule that clip as `@voice`, connect the audio VAE to Loop Context,
  and save the trimmed decoded audio for continuity and assembly.
- Use `source_plus_timeline` only when you intentionally want both the exact
  source slice and the preceding generated-audio latent. It is experimental.

## Scene-scheduled Ref2VA references

Use the scheduled reference nodes when a picture, video, or audio reference
should apply to selected scenes instead of every recursive iteration.

```text
Scheduled Picture Ref ─→ Scheduled Video Ref ─→ Scheduled Audio Ref
                                                    ↓
Current Shot ─ state, prompt, clip_index, clip_count ─→ Scheduled Ref2VA
Current Shot ─ width, height, length ───────────→ Scheduled Ref2VA
CLIP + video VAE + audio VAE ──────────────────→ Scheduled Ref2VA
```

### Convert an existing core Ref2VA node

For an existing workflow, right-click **MiniMax H3 Reference to Video** and
select **Convert to MiniMax H3 Scheduled Ref2VA**. The conversion is a graph
edit, not a runtime monkeypatch. It:

- replaces the visible core node with Scheduled Ref2VA at the same position;
- preserves CLIP, both VAEs, prompt, width, height, length, image-size mode,
  and both downstream core outputs;
- creates one schedule entry for every connected picture, video, paired video
  soundtrack, and standalone audio socket;
- keeps same-index video/audio inputs together in one Video Schedule node;
- connects Current Shot `state`, `clip_index`, and `clip_count` when the loop node is
  already connected to the core prompt/dimensions, or is the only Current Shot;
- connects a static schedule fingerprint to the only Plan when safe and leaves
  it disconnected when a reference depends on Current Shot, avoiding a cycle;
- preserves an existing non-empty Plan `generation_fingerprint` instead of
  overwriting it; combine the displayed schedule hash explicitly in that case.

Converted entries initially use all scenes and readable aliases such as
`@picture_1`, `@video_1`, `@video_1_audio`, and `@audio_1`. Edit their selectors,
and tags after conversion. A paired-audio socket without its same-index video
is ignored because core Ref2VA would ignore it as well.

Each entry has a stable human alias. Using it is optional: a Plan prompt can say `@hero_face`,
`@performance`, or `@voice` without knowing which native H3 ordinal that
reference will receive in a particular scene. Core workflows can continue using
native labels directly. In a scheduled prompt, do not mix native and alias names
for the same source; either manage native numbering yourself or let the alias
compiler own it.

The `scenes` field uses one-based scene numbers:

| Value | Active scenes |
|---|---|
| blank, `all`, or `*` | every scene |
| `3` | scene 3 |
| `1:5` | scenes 1 through 5 |
| `1,3,5:8` | scenes 1, 3, and 5 through 8 |

Overlapping or adjacent ranges are normalized. Zero, reversed ranges, malformed
tokens, and selections beyond `clip_count` stop before model execution with a
specific error. Unlike Loop Start's render range, disjoint reference selections
are safe because they do not skip the chain's motion dependency.

### Video-reference timeline modes

`sequential` remains experimental in 0.5. `restart_each_scene` remains the safe,
backward-compatible default and preserves existing schedule fingerprints.

Each Scheduled Video Ref chooses one of two source-timeline behaviors:

| Mode | Behavior |
|---|---|
| `restart_each_scene` | Every active scene receives the reference beginning at source frame 0. This is the compatibility default for existing workflows and short reusable motion examples. |
| `sequential` | The source advances on the Plan timeline. Each scene receives an exact source slice beginning at that scene's `generation_start_frame`, relative to the first scene where this reference is active. |

Sequential mode requires Current Shot `state` connected to Scheduled Ref2VA.
It uses the same overlap already represented in the Plan. With 243 raw frames
and 22 head-context frames, scene 1 uses reference frames `0:243`; scene 2
starts at generation frame 221 and therefore uses `221:464`. This overlap is
intentional: the reference motion shown beneath the pinned continuation frames
is the same motion, rather than frame 0 replaying against a later scene.

If the selector begins at scene 4, reference source frame 0 aligns with scene
4. Later active scenes follow the Plan's elapsed generation time, including
inactive gaps. The video must already be 24 fps and contain every requested
frame. Paired video audio is sliced to the same time interval with sample-exact
rounding. A short source, missing state, changed Plan timing, or mismatched
scene state stops with an explicit error; the scheduler never wraps or pads a
motion reference silently.

Motion Context is not `<Video 0>` and does not consume one of stock Ref2VA's
three external video slots. It travels as an H3 guide/keyframe and has no
prompt-visible label; scheduled references remain `<Video 1>` through
`<Video 3>`. Internally all visual conditioning blocks are presented to the
model, so additional references may still cost VRAM and introduce competing
motion instructions.

See
[`Ref2V Sequential Motion - EXPERIMENTAL - MiniMax H3.json`](<example_workflows/Ref2V Sequential Motion - EXPERIMENTAL - MiniMax H3.json>)
for the minimal two-scene wiring. Its Reference Video Prep selects 464 frames,
so the user-supplied native video and embedded audio must cover at least
19.333 seconds after conversion to 24 fps.

### Prompt definitions and native labels

Write reference definitions directly in the Plan prompt. Optional stable aliases
are useful when scheduled references renumber between scenes:

```text
subject_definitions:
<Subject 1> is the woman whose facial identity comes from @hero_face and whose
walking motion comes from @performance; preserve her hairstyle, skin tone,
apparent age, and distinctive physical features.
```

For one active picture and one active video, the compiled prompt receives:

```text
subject_definitions:
<Subject 1> is the woman whose facial identity comes from <Picture 1> and whose
walking motion comes from <Video 1>; preserve her hairstyle, skin tone,
apparent age, and distinctive physical features.
```

The wrapper only replaces active `@tags`; it never inserts definitions. This
keeps the complete six-section H3 prompt visible in the Plan and Prompt Editor.
Unknown tags and tags scheduled for another scene are rejected rather than
leaking unresolved aliases into H3.

ComfyUI's stock Ref2VA presents media in a fixed order, and the compiler mirrors
it exactly:

1. active pictures, numbered `<Picture 1>`, `<Picture 2>`, and so on;
2. active videos, with each paired soundtrack's `<Audio N>` presented directly
   before that video's `<Video N>`;
3. active standalone audio, continuing the independent `<Audio N>` numbering.

Picture, video, and audio ordinals are independent. A video soundtrack therefore
receives its own audio tag; if `audio_tag` is blank, `@performance` derives
`@performance_audio`. The stock limits are validated per scene: 9 pictures,
3 videos, and 3 standalone audios. Scenes with no active references remain
valid and expand to stock Ref2VA without dynamic reference sockets.

### Optional legacy patch ownership control

Updated ComfyUI builds containing merged PR #15439 keep H3 guide placement and
Ref2VA merging entirely core-owned; Patch Priority is then an unchanged
pass-through reporting that no compatibility patch is required. On an older
ComfyUI build, the first compatible H3 Motion Context copy loaded owns the
legacy process-level wrappers. If an older installed copy wins load order, wire
**MiniMax H3 Patch Priority** between the conditioning node and **MiniMax H3
Context Loop Context**:

```text
Ref2VA / I2V conditioning → Patch Priority → Context Loop Context
```

The node passes conditioning through bit-for-bit and executes an ownership
check first. It can replace only a recognised older copy of the same shared
patch family. It preserves the known-compatible H3-Multishot payload merge and
SolAttn layout observer. Any unknown wrapper is rejected with its ownership
reason instead of being overwritten. The selection is process-global after the
node executes; one wired node is enough for the workflow, while a disconnected
control node will not execute.

### Checkpoint compatibility

Every schedule entry fingerprints its normalized selector, tags, and actual
media bytes. For a schedule made entirely from static loaders, connect
its `schedule_fingerprint` output to Plan `generation_fingerprint`. Changing a
reference file, its selector, or its tag will then invalidate incompatible
saved predecessors.

An entry may instead consume a per-iteration output—for example Current Shot's
frame-exact `source_audio_slice`. Keep that entry inside the recursive body and
do not connect its changing fingerprint backward to Plan. Source-track mode
already fingerprints the complete source waveform at Loop Start, so its scene
slices remain resume-safe without creating a graph cycle.

## Extending an existing video

Use **MiniMax H3 Existing Video Context** when scene 1 must continue a decoded
video rather than begin from an empty timeline.

Open
[`Extend Existing Video Model Workflow - MiniMax H3.json`](<example_workflows/Extend Existing Video Model Workflow - MiniMax H3.json>)
for a complete two-scene model with generated-audio continuity, original-video
prepend, review/retry controls, and a muted recovery branch. This workflow is
**experimental** while the imported AV continuation path receives broader
real-world validation. It is a separate example; the existing looping and
historical workflows are not modified.

```text
Chain Plan ───────────────────────────┐
Core Load Video (VIDEO) ───────────────┼→ Existing Video Context → Loop Start
Other loader IMAGE + AUDIO + FPS ─────┘
H3 audio VAE (when carrying audio) ─────────────────────────────→ Loop Context
```

Use exactly one video route:

- `source_video` accepts a native ComfyUI `VIDEO`. The adapter decodes its
  frames and embedded audio and reads its exact FPS; the `source_fps` widget is
  ignored. A separately connected `source_audio` overrides embedded audio.
- `source_frames` accepts an `IMAGE` batch from VHS or another loader. Wire its
  `AUDIO` output when available and set or connect `source_fps` to the actual
  frame rate represented by that batch.

Connecting both `source_video` and `source_frames` is rejected instead of
silently choosing one.

The adapter performs four explicit operations:

1. decodes native `VIDEO`, or accepts already decoded `source_frames`, then
   resamples from the effective source FPS to H3's 24 fps;
2. fits them to the Plan width/height using the Plan crop setting;
3. keeps the last effective scene-1 `context_length` frames and optional
   matching audio tail as scene 1's predecessor (or none when it is `0`);
4. when `prepend_original` is enabled, persists the complete normalized source
   for automatic partial/final assembly.

No original H3 latent is required or recoverable from an ordinary MP4. The
decoded tail is re-encoded with the same H3 video/audio VAE path used between
generated scenes.

With recommended `anchor_mode: head`, imported context changes scene 1 timing
to the same rule used by later continuations:

```text
scene 1 delivered frames = raw_frames - scene 1's effective context_length
```

Therefore a 362-frame first scene with 22 imported context frames contributes
340 new frames. Keep Loop Trim connected with `match_tail=true`.

Legacy `source_audio` has two distinct meanings in this setup:

- Existing Video Context `source_audio` is the soundtrack of the video being
  extended. Its tail seeds the first join and its full normalized duration is
  preserved when prepend is enabled.
- Loop Start / Current Shot / Assemble `source_audio` is the compatibility
  soundtrack for the generated extension. In 0.5, register that media once with
  Source Timeline instead. For scene 1 the loop constructs one raw conditioning
  window from the imported audio tail followed by this track from time zero.

For `generated_audio` or `source_plus_timeline`, connect the H3 audio VAE to
Loop Context so the imported decoded tail can become a timeline audio guide.
With no imported audio, visual continuation still works and generated sound
starts fresh. In `source_track`, the first source-reference window already
contains the imported tail, so Loop Context does not need the audio VAE.

When `prepend_original=true`, Assemble detects the prelude in the manifest and
places it before all generated segments. Original audio is prepended to either
the source-track or checkpointed generated extension audio; `audio_source:none`
creates a silent final MP4. The source must be normalized and re-encoded because
arbitrary input videos cannot safely share H.264 parameters, dimensions, and
timestamps with generated segments. The Plan's `segment_crf` controls that
single normalization pass.

Reconnect the same Plan, source video, and adapter when resuming or rebuilding a
manifest. The imported tail is fingerprinted as part of checkpoint continuity;
changing it correctly invalidates dependent generated scenes.

## Audio modes and formatting

### `source_track`

Recommended for a music video driven by one song.

- In 0.5, set Audio Policy to Source/On/Off and connect the full track once to
  Source Timeline. The old Loop Start/Current Shot/Assemble AUDIO fan-out
  remains accepted for saved 0.4 workflows.
- Current Shot slices a frame-exact raw audio window for each Ref2VA scene.
- Motion Context carries picture context only.
- Assemble muxes the original source track over the stitched video.
- Wire trimmed decoded audio into Segment Save. H3's generated audio is saved
  as per-scene WAVs and as one combined `.generated.wav` beside the final MP4,
  even though the MP4 itself uses the original source track.
- The song must be at least as long as the total delivered video.
- A genuinely silent placeholder may be shorter; Loop Start detects it and
  zero-pads scene slices and final assembly to the required duration.
- The waveform is hashed; changing or miswiring the song is rejected.

### `generated_audio`

- No source track is required.
- Chain Context carries the preceding H3 audio latent on the timeline.
- Wire trimmed decoded audio into Segment Save.
- Assemble uses cumulative frame boundaries and lets every later masked-AV
  scene own its saved decoded overlap, preserving hard or feathered AV sound.
- The same generated track is also preserved as WAV sidecars for later editing.
- MiniMax H3 Context Loop Trim must keep `match_tail` enabled for exact sample counts.

### `source_plus_timeline`

- Ref2VA receives the frame-exact source-song window.
- Chain Context also carries the preceding generated audio latent.
- This mode is experimental.
- Assemble selects the source track when `audio_source` is `plan`.
- H3's generated track remains available in the generated-audio WAV sidecars.

## Native MiniMax H3 guides

When ComfyUI exposes **MiniMax H3 Add Guide** (introduced by
[ComfyUI PR #15439](https://github.com/Comfy-Org/ComfyUI/pull/15439)), Loop
Context automatically emits core video/audio guide records instead of the
legacy keyframe/ref representation. Existing ComfyUI releases continue through
the guarded compatibility path with a one-time update warning, so workflows do
not need a version switch.

To add a scene-local still, clip, or audio anchor, place the official Add Guide
node **after Loop Context**. It appends its guide to the continuation anchors.
When Ref2VA references are present, merged core places the complete guide set
on the target scene timeline rather than the preceding reference cursor. This
pack does not wrap the native layout or payload path.

## Starting, resuming, and changing a plan

For a fresh render:

```text
run_name: choose a new name
start_clip: 1
scene_range: leave blank
```

To resume from scene N:

```text
run_name: keep the original name
start_clip: N
scene_range: leave blank
```

The Start node loads the checkpoint from scene `N - 1` and validates every
completed predecessor. You may edit scene N and later scenes. Changing any of
the following for an earlier completed scene invalidates resume:

- prompt, seed, steps, duration, or length;
- width, height, context, crop, anchor, encoding, or audio mode;
- source audio waveform;
- `generation_fingerprint`.

The checkpoint browser embedded in the Review Gate is a shortcut for this
setup. It lists saved predecessor slots under the current `run_name`, changes
Loop Start's `start_clip`, and leaves the same validation to the next queued
execution. Loading previews the joined partial through that checkpoint when
available, or the saved predecessor scene otherwise. **Approve & stop** also
writes a partial joined video through the accepted scene when
`assemble_partial_on_stop` is enabled.

During active sampling, the floating **Cancel & reroll scene N** action uses
the scene index emitted by Current Shot. It cancels that exact ComfyUI prompt
ID, waits for an `execution_interrupted` confirmation, stores a new explicit
seed in scene N, sets `start_clip` to N, and queues normally. Scene N > 1 is
only cancelled after checkpoint N - 1 is confirmed ready. For a bounded run,
the remaining range becomes `N:end`; otherwise `scene_range` is cleared so it
cannot override the adjusted `start_clip`. If the prompt finishes during the
request, no Plan value is changed and nothing is automatically requeued.

### Generate a bounded scene range

`scene_range` is inclusive and overrides `start_clip` when non-empty:

```text
scene_range: 3       # generate only scene 3
scene_range: 3:8     # generate scenes 3 through 8
```

Whitespace is allowed. A range starting above 1 loads and validates the
checkpoint for the preceding scene. A range ending before the final planned
scene emits a partial manifest containing every verified predecessor through
the selected end, so Assemble can create the chain through that point.

Disjoint syntax such as `1,3,5:8` is intentionally rejected. Scene 5 depends
on scene 4, and rerendering an earlier selected scene would invalidate a
skipped descendant checkpoint.

Model, VAE, LoRA, references, CFG, sampler, and scheduler sit outside the Plan
node, so the chain cannot inspect them directly. Record them in
`generation_fingerprint` and change that string whenever they change.

## Saved prompts and workflow recovery

Segment Save preserves the actual effective prompt and seed used for every
accepted render. A run under `output/h3_chains/<run_name>/` contains:

```text
source/existing_video_<hash>.mp4  normalized prelude when prepend is enabled
source/existing_video_<hash>.safetensors  preserved prelude audio
plan.json                         normalized effective plan for this run
workflow.json                     loadable frontend ComfyUI workflow
api_prompt.json                   queued API-format graph fallback
manifest.json                     completed segment manifest
segments/clip_0001.<id>.mp4       video with the full prompt in MP4 metadata
segments/clip_0001.<id>.prompt.txt
checkpoints/clip_0001.json        structured prompt, seed, paths and hashes
checkpoints/clip_0001.<id>.json   immutable metadata for each saved revision
checkpoints/clip_0001.<id>.safetensors
final/<filename>.mp4              workflow, API graph and manifest embedded
```

Saving the same scene again updates `checkpoints/clip_0001.json` to the active
revision but retains every earlier MP4, prompt sidecar, safetensors checkpoint,
and versioned metadata file. Each current record links to the previous one via
`supersedes`, so rerolling or regenerating a scene is non-destructive.

The segment record and manifest store `prompt_prefix`, `scene_prompt`, the
combined `prompt`, `prompt_hash`, `prompt_file_sha256`, `seed`, and paths to the
recovery archives. `prompt_hash` identifies normalized prompt text, while
`prompt_file_sha256` verifies the exact sidecar bytes. Older Windows sidecars
that used CRLF line endings remain resumable through normalized text checking.
The same prompt fields are also stored in the safetensors metadata. In 0.5,
edit the active prompt in Scene Prompt Editor or Rich Scene Prompt Editor;
Review Gate reads that Plan prompt on Retry/Reroll. Its legacy textarea is
available through the Interface setting. Review retries rewrite `plan.json`,
`workflow.json`, and `api_prompt.json` with the effective scene prompt and
exact uint64 seed before saving the replacement.
Both segment and assembled MP4 files use ComfyUI's standard `workflow` and
`prompt` tags, so metadata-aware ComfyUI loaders can recover the graph directly;
assembled files additionally embed the completed `h3_manifest`.

`workflow.json` is the file to drag back into ComfyUI. `plan.json` remains the
authoritative record of what the loop actually rendered if an external API
queued the job without frontend workflow metadata. As with ordinary ComfyUI
workflow metadata, connected node widget values are archived too; keep the run
folder private if a workflow contains credentials or other sensitive values.

### Re-decode checkpoints to PNG

Wire a completed or partial manifest and the same H3 video VAE into
**MiniMax H3 Context Loop Export PNG Sequence**. The node:

1. verifies every safetensors checkpoint hash without depending on the H.264
   segment file;
2. decodes one full scene latent at a time;
3. computes `trim_frames = raw_frames - delivered_frames` and removes the
   repeated continuation overlap;
4. writes a continuous frame-numbered 8-bit RGB PNG sequence;
5. writes `export.json` with scene frame ranges, prompts, seeds and checkpoints.

The export lives under
`output/h3_chains/<run_name>/frames/<export_name>/`. If that folder already
exists, a numbered sibling is created instead of overwriting it. PNG compression
is lossless: changing `png_compression` only changes encoding time and file size.
When `embed_workflow` is enabled, the first PNG stores the archived `workflow`,
API `prompt`, effective `h3_plan`, and `h3_manifest`; each scene's first frame
stores its effective scene metadata and full prompt.

The checkpoint contains the exact sampled video latent, but VAE decoding is a
separate computation. For the closest reconstruction, use the same H3 video
VAE, ComfyUI version, precision, and decode/tiling behavior as the original
render. The PNG files are lossless representations of this new decode after its
conversion to standard 8-bit RGB; they are not guaranteed to be bit-identical
to frames decoded previously under different settings.

## Complete music-video template

```json
{
  "prompt_prefix": "<Subject 1> is the same performer in every scene. Preserve facial identity, hair, wardrobe, proportions and accessories. Photorealistic high-energy music video shown as one uninterrupted moving-camera take. No cuts. Continue subject motion, camera momentum, lighting and geometry across every boundary.",
  "defaults": {
    "duration_seconds": 15,
    "steps": 20
  },
  "shots": [
    {
      "id": "clip_01",
      "prompt": "Begin in a backstage room. Track backward as <Subject 1> approaches a lit doorway. End while the door is opening.",
      "seed": 1001
    },
    {
      "id": "clip_02",
      "prompt": "Continue through the already-opening doorway without resetting her stride or the camera. Follow into a concrete corridor. End as the corridor begins transforming.",
      "seed": 1002
    },
    {
      "id": "clip_03",
      "prompt": "Continue the corridor transformation and the same forward motion. Move into a wide exterior. End with the camera starting to rise.",
      "duration_seconds": 10,
      "steps": 24,
      "seed": 1003
    },
    {
      "id": "clip_04",
      "prompt": "Complete the rising camera move, resolve the performance, and finish on a calm wide composition.",
      "length": 124,
      "seed": 1004
    }
  ]
}
```

## Common formatting errors

| Error | Fix |
|---|---|
| Invalid JSON | Use double quotes, remove comments, and remove trailing commas. |
| Empty prompt | Provide a non-empty scene `prompt`, or provide a non-empty `prompt_prefix`/`global_prompt` that the scene can use alone. |
| Duplicate ID | Give every scene a unique `id`. |
| Invalid exact length | Use a value from the `17k+5` grid, such as `124`, `243`, or `362`. |
| Continuation is too short | Make its raw length greater than `context_length`; every non-final scene must also deliver enough frames for the next context. |
| Unexpected scene duration | Remember that seconds round up and later `head` clips lose the repeated context after trimming. Inspect Current Shot's `raw` and `delivered` status. |
| Resume rejected | Restore the prior completed-scene settings and source track, or start a new run from clip 1 with a new `run_name`. |
| Source audio too short | Use a longer song, shorten the plan, or choose a non-source audio mode. Truly silent placeholder audio is padded automatically; non-silent audio is never padded. |
| Final audio/video drift | Wire both decoded streams through MiniMax H3 Context Loop Trim and leave `match_tail` enabled. It truncates excess audio or zero-pads a fractional-step shortage. |
