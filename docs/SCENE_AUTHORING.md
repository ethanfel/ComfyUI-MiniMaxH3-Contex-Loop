# Scene authoring

## Plan structure

The Plan node provides a visual editor and stores ordinary JSON underneath.
Put shared instructions in `prompt_prefix`; each scene should describe what
changes.

```json
{
  "prompt_prefix": "Keep the same performer, wardrobe and visual language.",
  "defaults": {"duration_seconds": 15, "steps": 20},
  "shots": [
    {"id": "intro", "prompt": "Instrumental opening in the elevator.", "seed": 123},
    {"id": "street", "prompt": "Continue outside into the rain.", "seed": 456}
  ]
}
```

Prompts may be multiline strings or arrays of lines. Seconds are rounded up to
H3's valid `17k+5` frame grid. Use `length` when exact raw frames matter.

The [complete format guide](../H3_CHAIN_FORMAT_GUIDE.md) documents every Plan
and per-scene field, raw versus delivered length, prompt structure, seeds, and
timing.

## Per-scene LoRA routes

Each scene has a **Scene LoRA route** selector: Base or LoRA A-D. Connect
Current Shot `state` to **MiniMax H3 Scene LoRA Scheduler**, connect the normal
base MODEL to `base_model`, and connect MODEL outputs from ordinary ComfyUI
LoRA loaders to the A-D inputs. The scheduler only routes those prepared
models; it never chooses a file or applies a LoRA.

One route can contain a stack of ordinary LoRA loaders. The same LoRA at two
strengths can be represented by two branches. Inputs are lazy, so a connected
branch is not evaluated until a scene selects it. Put patches shared by every
scene after the scheduler. When using Drift-Control, send the scheduled MODEL
through Chain Context's MODEL input/output before the sampler.

## Scene Prompt Editor

Connect Plan to **MiniMax H3 Scene Prompt Editor** for a large synchronized
textarea. It edits the selected scene's real `shots[n].prompt`; there is no
second prompt copy.

- Arrow buttons or `Alt+Left/Right` change scenes.
- Typing `@` offers the connected Picture/Video/Audio aliases. In Tagged mode,
  inserting an inactive alias activates it; scheduled references remain limited
  to the selected scene.
- Typing `#` offers valid dedicated Semantic Picture Anchors (and legacy
  Tagged Picture compatibility anchors) only.
- Typing `<` offers H3 subjects, dialogue tags, and available native reference
  labels, plus `<scenetrans>` and `<|cutoff|>` dialogue-flow markers. Typing
  `[` filters 12 shot markers, multilingual dialogue markers, and canonical
  summary-intent combinations; for example, `[re` lists the supported
  reference-generation combinations. Typing `(S` offers stable speaker IDs.
- Typing the start of an H3 section name at the beginning of a line completes
  `subject_definitions:`, `integrated_multimodal_description:`, and the other
  standard sections. `Ctrl+Space` (`Cmd+Space` on macOS) opens the full H3
  completion catalog. Use arrows to select and `Enter` or `Tab` to insert.
- **@ Reference** remains available for browsing connected media previews.
- **Dialogue** wraps a selection in `<d>` tags.
- Choose **Auto schema**, T2VA, I2VA, FL2VA, L2VA, or Ref2VA, then open
  **Sections** to inspect the exact required order, jump to a category, insert
  a missing category, or normalize the mode's keyframe-alignment line.
  Diagnostics cover section spelling/order, shot numbering and timestamps,
  Ref2VA task directives and definitions, dialogue/language/flow balance, and
  connected native references. FL2VA/L2VA expose duration and final-shot
  controls for their exact alignment sentence.
- Live word/character counts stay in the footer. Both dedicated editors can
  switch between the ordinary prompt source and rich H3 token presentation;
  this changes presentation only, never Plan text.
- `#picture` adds an untimed Qwen-only semantic Picture when the picture is
  supplied through Semantic Anchor Bundle. Add a time as
  `#picture[2.50s]` for a scene-local Qwen checkpoint; with the Bundle set to
  `picture_storyboard`, the time becomes an approximate prompt instruction.
  Neither form consumes a native H3 reference slot.
- `A−` and `A+` change persistent type size.
- The node may sit inline before Loop Start or on an editor-only branch.

The reference tray discovers downstream Scheduled Ref2VA, core Ref2VA, and core
Image to Video nodes without introducing an execution socket or graph cycle.
Hovering a loader-backed reference previews its image, video, or audio; computed
tensors remain usable even when no browser-playable source file can be found.

The schema inspector and completion catalog are shared by the focused Scene
Prompt Editor and the optimizer-enabled Rich Scene Prompt Editor. They are
backported from the standalone
[H3 Prompt IDE](https://github.com/ethanfel/ComfyUI-H3-Prompt-IDE), while these
nodes retain Motion Context Plan synchronization, revisions, `@tags`,
semantic anchors, and optimizer integration.

### Nightly editor interactions

Click a Subject, speaker, dialogue, lyrics, caption or flow token to replace
or remove it. Pasted tokens become interactive immediately. Connected media
references keep their existing reference/syntax/time popup and previews.
Ctrl/Cmd-click an ordinary `[Shot N]`, language, task directive or retention
marker to change it without replacing the surrounding sentence.

Inside `retention_analysis:`, completion offers visual or audio retention
values according to the reference kind, including known `@aliases` and
`#picture` anchors. Inside `detailed_description:`, typing
`[Shot N] At` offers `At 00:00.000, `, selecting the seconds/milliseconds
for immediate editing. Ctrl/Cmd+Space also offers the timestamp after a plain
`At` in that section.

ComfyUI **Settings → MiniMax H3 Context Loop → Prompt editor** controls the
default Rich/Plain presentation, automatic suggestions, optional trailing
spaces, and the new marker replacement menus. Saved per-node presentation
choices win. Trailing spaces are off by default to preserve existing typing
behavior; semantic anchors never receive an inserted space before their time.
Turning off automatic suggestions still allows Ctrl/Cmd+Space.

Ctrl/Cmd+S saves the workflow while the editor is focused. Ctrl/Cmd+Z remains
scene-local. Token diagnostics flag malformed lyrics/caption pairs, incorrect
special-token case, and legacy `<cutoff>`; they do not rewrite saved prompts
or change generation. No task-aware Edit templates or new node sockets are
introduced by this port.

## Prompt revisions

The compact `‹ Active current / total ›` selector below the editor activates a
prompt version in the Plan; it is not a read-only history browser. Each version
is labeled **Active draft**, **Active executed**, **Draft history**, or
**Executed history**. Typing updates one active draft rather than creating a
revision per keystroke. When Current Shot executes, that exact prompt becomes
immutable; typing from it creates a child draft. Activating an older version
explicitly replaces the selected scene prompt in the Plan.

History is stored outside Plan JSON and loaded only for the selected scene:

```text
output/h3_chains/<run_name>/prompt_history/<scene_id>/
```

The Plan retains only the active prompt, keeping workflow JSON readable and
load time independent of old revisions.

## Seeds and bounded runs

Set a scene seed explicitly when repeatability matters. If omitted, Plan derives
a deterministic seed from `base_seed` and scene identity.

Loop Start's `scene_range` accepts one continuous selection:

| Value | Result |
|---|---|
| blank | `start_clip` through the end |
| `3` | scene 3 only |
| `3:8` | scenes 3 through 8, inclusive |

A range starting above scene 1 requires the preceding checkpoint. Disjoint
selections are rejected because skipped scenes would break the motion chain.

## Prompt Assistant status

The embedded Prompt Assistant is currently dormant so the editor retains its
compact manual workflow. Use the `comfyui-mcp` sidebar Agent panel for Codex or
Hermes assistance. The implementation, safety model, and future console-agent
design are preserved in the
[Prompt Assistant study](../AGENT_PROMPT_ASSISTANT_STUDY.md).
