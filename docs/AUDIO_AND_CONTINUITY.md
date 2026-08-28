# Audio and continuity

## Choose a generation profile

New workflows should use **Generation Profile**, which replaces the individual
audio switches with explicit intent:

| Audio profile | Generation and final-output behavior |
|---|---|
| Generate audio | H3 generates sound and carries it between scenes |
| Generate fresh audio per scene | H3 generates sound without carrying the preceding scene's audio latent |
| Lip-sync to source audio | The exact Source Timeline window drives generation and remains the final soundtrack |
| Generate audio from source guide | Source audio is a loose reference while H3 creates the final sound |
| Use source soundtrack only | The source track is used for assembly without guiding generation |
| No final audio | The assembled MP4 is silent |

Its **Scene continuity** profile separately selects visual continuity,
independent scenes, or a hard/smooth audiovisual boundary. The profile output
is the same canonical `chain_policy` record used everywhere else and can feed
Advanced Policy Override before Plan.

The deprecated **Manual Chain Policy (Legacy)** remains loadable for existing
workflows and unusual combinations that do not fit a named profile. Its legacy
controls are described below.

## Manual policy axes

Version 0.5 separates three independent decisions and one exact-target switch:

| Axis | Values | Meaning |
|---|---|---|
| Final audio | `generated`, `source`, `none` | What Assemble places in the final MP4 |
| Source reference | `on`, `off` | Whether the exact active source window guides H3 |
| Generated continuity | `on`, `off` | Whether the previous sampled audio latent continues into the next scene |
| Lock source audio | `on`, `off` | Whether each exact source window occupies the complete target audio latent and is protected from denoising |

Set these controls and the default incoming boundary on the deprecated
**Manual Chain Policy (Legacy)** node. Its output may connect directly to Plan
or pass through an
**Advanced Policy Override**. Advanced Policy preserves every audio choice and
replaces only the incoming transition with a named experimental recipe such as
Drift-Control AV. Use the **Legacy 0.4 Policy Adapter** only for a genuine 0.4
import, a raw implementation/context pair, or an independent numeric audio
overlap. It can also accept an incoming Chain Policy, in which case its legacy
`audio_mode` is ignored and the modern audio intent is preserved.

Policy layers are ordered left to right. Each downstream layer replaces only
the boundary fields it owns; the last boundary layer wins, while the audio
record continues unchanged:

```text
Generation Profile → Plan
Generation Profile → Advanced Policy Override → Plan
Manual Chain Policy (Legacy) → Plan
Generation Profile → Legacy 0.4 Policy Adapter → Plan
```

The reverse Advanced/Legacy order is also valid: whichever is nearest Plan
owns the effective transition. A standalone Legacy Adapter retains exact 0.4
`audio_mode` behavior for imported workflows.

### Per-scene audio behavior

Final soundtrack remains a single Chain Policy choice, but the three
generation-time audio axes can be overridden independently on each scene in
Plan or Plan Studio:

- **Source reference** decides whether that scene receives its exact source
  window as a loose Ref2VA audio reference.
- **Generated continuity** decides whether that scene carries the preceding
  sampled audio latent.
- **Lock source audio** places that scene's exact source window in the target
  audio latent and protects it from denoising. Lock wins over the other two
  switches for that scene.

Each selector defaults to **Inherit Chain Policy**. Therefore existing plans
do not change, and only scenes with an explicit override acquire new JSON or a
new generation dependency. For example, a music video can use a source
performance reference for scene 1, create fresh generated sound in scene 2,
and lock an exact source passage in scene 3 while still choosing one global
final soundtrack:

```json
{
  "shots": [
    {"id": "scene_1", "prompt": "...", "source_reference": "on"},
    {"id": "scene_2", "prompt": "...", "generated_continuity": "off"},
    {"id": "scene_3", "prompt": "...", "source_audio_target": "locked"}
  ]
}
```

The canonical stored values are `on`/`off` for `source_reference` and
`generated_continuity`, and `locked`/`off` for `source_audio_target`. Omitting
a key means inherit. Source audio still connects once at Loop Start or through
Source Timeline; scenes that do not consume it need no rewiring. Changing one
scene's effective source reference, generated carry, or lock invalidates that
scene and its descendants, not unrelated earlier checkpoints.

For a prerecorded song or dialogue performance that must remain exact, choose
Source final audio and enable **Lock source audio**. The switch resolves Source
reference and Generated continuity off: the source is no longer a loose Ref2VA
audio bank or a carried predecessor prefix. Chain Context VAE-encodes the
scene-local source window into H3's target audio stream and sets its complete
denoise mask to zero. Video remains denoisable and can attend to the protected
audio for timing and lip sync. Source-rate conversion for H3's audio VAE may
still occur; final assembly with Final audio=source uses the Source Timeline
track rather than model-decoded audio. For a short voice/timbre
reference where H3 should generate new words, choose Generated final audio and
schedule that clip as an ordinary tagged audio reference.

Legacy music-video workflows may still connect a full `AUDIO` directly to
Loop Start instead of building Source Timeline. Loop Start now materializes
that waveform once under the run's `source_timeline/` folder and carries its
path-backed recovery descriptor through recursive state, checkpoint metadata,
and the final manifest. Current Shot, partial review assembly, final assembly,
and the full-chain SeedVR2 adapter can therefore recover it without another
audio wire. Existing redundant downstream wires remain compatible when their
fingerprint matches. A manifest produced before this recovery descriptor was
added still needs its legacy `source_audio` fallback connected.

For normal finishing, leave `audio_source` set to `plan`. `Final audio =
generated` uses the generated WAV sidecars written by Segment Save, `Final
audio = source` uses the persisted source track, and `Final audio = none`
stays silent. The explicit source/generated/none choices on finishing nodes are
overrides, not required routing steps.

Saved 0.4 modes migrate without changing behavior:

| Legacy `audio_mode` | Final | Source reference | Generated continuity |
|---|---|---|---|
| `generated_audio` | generated | off | on |
| `source_track` | source | on | off |
| `source_plus_timeline` | source | on | on |

These descriptions apply to `guide`, `tone_carry_guide`, `latent_guide`, and
`tapered_guide`.
Tone Carry Guide uses the RGB/VAE route and applies the predecessor's saved,
direct boundary-tone curve before encoding its context. It falls back to clean
Guide when no coherent curve was detected and never silently takes the direct
video-latent path.
When an older checkpoint predates this curve metadata, resume recovers it from
the two existing scene videos. The saved checkpoint and sampled AV latent are
reused unchanged; diffusion is not rerun.
Latent Guide reuses the generated predecessor's sampled video-latent tail
directly, while imported or incompatible context falls back to the normal
RGB/VAE Guide route. Tapered Guide changes only the disposable video context
passed to the Guide VAE. In the
experimental `masked_av`, `tapered_av`, `feathered_av`, and
`drift_control_av` modes, Chain Context always places a video prefix inside the
target latent. With Generated continuity on it also
places the matching audio prefix; `masked_av` protects that complete prefix and
`tapered_av` protects a disposable video-only latent-noise copy of that prefix;
`feathered_av` progressively denoises its final latent steps. With Generated
continuity off, the audio mask remains fully open even when final assembly uses
`source_track`. For recursive scenes, enabled audio carry copies the previous
sampler's audio latent directly. For scene 1 after Existing Video Context,
carrying imported audio requires source audio and the H3 audio VAE.

With **Lock source audio** on, the complete scene-local audio mask is zero
instead. This composes with every picture boundary: Cut and Guide affect only
video context, while AV modes preserve or taper their video prefix without
copying predecessor audio over the locked source window.

Experimental `drift_control_av` is a recursive picture-only treatment layered
on the same 39-frame AV prefix. It does not bake random noise into a checkpoint
or redraw noise between scenes. At each model evaluation, it uses the sampler's
existing noise field and sets the prefix mask to `next_sigma / current_sigma`.
The oldest eight of the 12 video-latent steps use that complete ratio; the last
four multiply it by `.75`, `.50`, `.25`, and `.00`, leaving the actual seam
clean. The same live mask drives both ComfyUI's inpaint blend and, through an
apply-model hook, H3's internal per-row timestep labels. Audio remains exact or
open according to Audio Policy.

Select **Drift-Control AV**, connect the H3 MODEL to Chain Context's optional
`model` input, and use its `model` output for the first or only sampler stage.
Chain Context stops before scene 1 when a Drift-Control Plan is missing that
route. For a sigma split that switches models, leave Chain Context's `model`
input disconnected. Connect the original full schedule (before the split) to
its `drift_sigmas` input, then place **MiniMax H3 Drift-Control Model Patch
(Sigma Split)** between each raw model and its sampler. Feed every patch Current
Shot `state`, Chain Context `latent`, and that same original full sigma
schedule. This keeps both model loaders independent and sequential. Each patch
stores only a small CPU sigma tuple and cloned ModelPatcher metadata, not
another copy of either model's weights.

Do not put Differential Diffusion or another dynamic denoise-mask patch on the
same MODEL path. The initial validated baseline is 39 frames and 20 sampling
steps; other samplers, schedulers, and step counts remain experimental.

The 0.5 **Soft AV** preset selects `audio_feathered_av`: all picture-prefix
steps remain exact. With Generated continuity on, only the final eight carried
audio ticks are released with a half-cosine ramp. With Generated continuity
off, the target audio stays fully denoisable and paired source audio spans the
complete raw scene window instead of inheriting the delivered-video window.
This is the tested upstream AV extension recipe. The older
dual-stream `feathered_av` remains a raw Legacy Adapter override for
compatibility.

AV prefixes must end on both native clocks: 39, 90, 141, 192, or 243 frames.
The normal 39-frame prefix maps exactly to 12 video latent steps and 65 audio
steps; 22 frames maps to 36.666... audio steps and is rejected before model
loading. At 39 frames, legacy raw `feathered_av` fully protects the first 8 video /
42 audio steps and ramps the final 4 video / 23 audio prefix steps.

Chain Policy controls the normal incoming boundary: Cut carries no picture,
Guide uses 22 clean RGB/VAE guide frames, Tone Carry Guide uses the same RGB
span with the predecessor's detected tone correction, Latent Guide uses the
same span from the saved sampled video latent, Detail Guide uses the same span with an
eight-frame chroma-noise exit taper, Detail AV uses a protected disposable
39-frame video-latent copy with matched-variance Gaussian noise tapering from
0.30 to a completely clean boundary while leaving audio exact, Drift-Control
AV applies schedule-matched noise to a clean carried prefix at every model
evaluation, Hard AV uses a protected 39-frame prefix, and Soft AV keeps the
picture exact while feathering only a carried-audio exit. With Generated
continuity off, all AV presets carry picture only.
Detail AV v2 is fixed to 39 frames. Its seed and complete recipe enter the
incoming-boundary dependency fingerprint, its predecessor checkpoint is never
mutated, and the entire treated prefix is trimmed before delivery. Advanced
mode may pair either experimental Guide with another Guide context length; 22
is the published baseline. Mixed plans must still use
encode/anchor settings compatible with every AV-mask scene.

Chain Context exposes `visual_cond_noise_aug` as a Guide-only diagnostic.
`0.999` preserves ComfyUI's current H3 behavior; `0.995` and `0.990` add
progressively more noise to visual condition rows and lower their pinned
timestep. The full `0.000` to `1.000` range is exposed for causal diagnosis:
`0.000` retains the same packed condition-row count and positions while
replacing their latent content with seeded noise and removing the clean
timestep pin. It is not a useful production setting. ComfyUI currently owns
this as one value for the complete conditioning payload, so it also affects
Ref2VA character, keyframe, and motion-reference rows in that continuation
scene. AV prefixes are target latent rows rather than Guide rows, so the
control is deliberately ignored by AV modes. Keep it at `0.999` outside
controlled comparisons.

For the next discriminating test, **MiniMax H3 Visual Context Schedule (Research)**
accepts the H3 MODEL and Current Shot state. `matched` changes the same core
value at every diffusion call to `clamp(1 - sigma, 0.000, 0.999)`. The
recommended first A/B uses this exact target match. Experimental `next_step`
uses the next lower endpoint in the original full sigma schedule instead. On
H3's shifted 20-step simple schedule it is still only about `0.009` clean at
evaluation 2, but reaches `0.999` on the final model call instead of stopping
near `0.613`. Unlike static content corruption, H3 always receives condition
content and a condition timestep describing the same mixture. The seeded
condition noise is stable across calls, so the Guide is revealed along one
coherent trajectory instead of being freshly randomized. Scene 1, Cut, and AV
transitions pass through unchanged. Place one instance on each switched model
branch and route each MODEL output through its associated sampler stages.
`matched` and `custom` do not require `full_sigmas`; `next_step` requires the
same original unsplit scheduler output on every model branch.

The `manual` preset also requires that original `full_sigmas` connection. Its
text input accepts clean fractions separated by commas, semicolons, spaces, or
newlines. Values are indexed by absolute scheduler step, so they remain stable
with solver sub-evaluations and split model branches. A short list holds its
last value: `0, 0.999` gives the recursive Guide pure seeded noise on step 1,
then the stock near-clean `0.999` mixture on step 2 and every later step.

Keep `noise_backend=comfy_rows` for the first A/B. It preserves ComfyUI's
existing packed-row noise draw exactly and changes only the recursive
condition's mixture and timestep schedule. If that removes the early color
shift but continuity is too weak, `dependent_latent` is a separate parity test:
for Chain Context rows only, it draws seeded noise in latent shape at temporal
length `target_T + visual_condition_count`, slices the condition prefix, and
then patchifies, matching the reviewed RunningHub and DiffSynth runtimes.
Authored keyframes and Ref2VA rows still use ComfyUI's original path.

Keep `scope=chain_context_only` for the useful experiment. Chain Context marks
only the predecessor video Guide records that it creates; a source-hash-gated
compatibility forward assigns those records the dynamic content and timestep
while native character, authored-keyframe, and Ref2VA rows retain their
original strength. `all_visual_conditions` is the earlier public-wrapper
diagnostic and intentionally weakens every visual condition in the payload.
The selective implementation refuses unknown ComfyUI H3 forwards or competing
object patches rather than guessing at changed packed-segment semantics.

This remains a research control, not a new default. The selective compatibility
path copies current H3 forward structure because ComfyUI's public API still has
only one scalar for the complete visual payload. The maintainable production
solution is equivalent per-condition support in core.

Drift-Control AV v1 is also fixed to 39 frames. Its sigma rule, 8+4 temporal
taper, mask quantization, audio behavior, and validated-step baseline enter the
incoming-boundary dependency fingerprint. Changing the mode or recipe therefore
requires regenerating that incoming scene, while the saved predecessor remains
unchanged.

**Color-Stable Drift AV** is the opt-in latent-domain counterpart to Final
Assembly's scene-one color stabilizer. It keeps Drift-Control's 39-frame mask,
but adds only the difference between a VAE encode of a weakly corrected RGB
decode and an encode of the unchanged RGB decode. The shared VAE reconstruction
error cancels. That low-frequency delta ramps from zero at the old overlap edge
to full strength beside the generated future. The first generated scene is the
anchor; scene 2 is therefore neutral, while scene 3 onward can resist recursive
exposure/saturation drift. Audio and saved checkpoints remain exact. It costs
one 39-frame decode and two 39-frame encodes only when a non-neutral correction
is detected.

In Plan Studio, a scene normally chooses Inherit, Cut, Guide, Hard AV, or Soft
AV. That single choice writes the matching visual and generated-audio overlap.
The raw per-scene implementation and separate visual/audio context fields are
under Advanced boundary controls. Plan-wide raw 0.4 defaults belong to the
Legacy 0.4 Policy Adapter.

### Editorial scene placement, gaps, and subtitles

Plan Studio can place each generated scene at an exact 24 fps timeline frame.
The first legal position is the end of the preceding scene, so scene order and
generation dependencies remain unchanged and clips never overlap. Moving a
scene later creates uncovered track time; preview shows that interval as black
and final Assemble renders the same number of black frames.

Generated clip audio is moved with its scene and silence is inserted in every
gap. Source Timeline audio instead remains locked to the absolute project clock,
so a song continues through black. These positions live in the run's
`editorial.json`, outside the Plan hash, and do not invalidate checkpoints.

An audio asset may also store lyrics. Timestamp lines as LRC (`[MM:SS.xx]`) or
paste SRT, then select that asset in Plan Studio's Subtitles tab. Subtitle
preview and exported `.srt` use the same absolute editorial clock and optional
offset; they do not enter prompts or generation fingerprints.

### Scheduled boundary spatial proxy

`context_spatial_proxy` is an optional **per-scene incoming-boundary** setting.
It is off when absent, so it can be scheduled only where a long chain begins
to burn in or needs a controlled spatial reset:

```json
{
  "id": "scene_4",
  "continuation_mode": "masked_av",
  "context_length": 39,
  "context_spatial_proxy": "latent_5_6"
}
```

`rgb_5_6` is shown as **Low-grid 5/6 · Guide** and is available for Guide,
Tone Carry Guide, and Detail Guide on scenes 2 and later. It reduces the
complete saved predecessor video latent (for example, 86×48 becomes 72×40),
VAE-decodes that disposable stream natively at 1152×640, and selects the
requested delivered RGB tail. Motion Context then restores that tail to
1376×768 before the normal Guide encode. This preserves the nonlinear
low-grid VAE decode observed in the source mixed-resolution experiment; it is
not merely an RGB resize.
Because it VAE-decodes the predecessor stream once more, Low-grid Guide uses
more preparation time and peak memory than native Guide. Schedule it only on
boundaries where the reset is wanted.
`latent_5_6` is available for AV modes. It downscales and restores only the
copied video-prefix latent (86×48 becomes 72×40 and returns to 86×48). It does
not filter the paired audio prefix. Neither mode resizes generated frames,
saved checkpoints, predecessor state, or assembly output. The fixed recipe is
stored in the incoming-scene dependency, so enabling it for scene 4 leaves
scenes 2 and 3 valid but requires scene 4 and its successors to be regenerated.

## Source Timeline wiring

Register picture and sound once. New workflows pass a typed descriptor instead
of repeating a decoded full-track AUDIO wire:

```text
Load Video ─┐
            ├→ Source Timeline ─┬→ Preflight / Plan Studio
Load Audio ─┘                   └→ Loop Start → Current Shot
                                                   └→ scene-local source slice

Loop End manifest → Assemble (recovers the timeline descriptor)
```

Current Shot requests each overlap-aware scene window from the descriptor.
Loop Start fingerprints the source so changed media cannot silently resume old
checkpoints. Path-backed video and audio remain lazy; only the active scene is
decoded. A tensor-only AUDIO input is normalized once into a run-owned file.
The source must cover the required delivered timeline; Preflight reports the
exact shortfall and last complete scene before model loading.

The 0.4 Lazy Motion AV Loader fan-out remains accepted as a compatibility route:

```text
Lazy Motion AV Loader source_video ─┬→ Tagged Motion Ref source_video
                                    └→ Run Manager asset
Lazy Motion AV Loader source_audio ─┬→ Loop Start
                                    ├→ Current Shot
                                    ├→ Tagged Audio Ref
                                    └→ Assemble
Lazy Motion AV Loader skip frames ───→ Tagged Motion Ref skip frames
```

The native VIDEO remains disk-backed. The loader decodes only the complete
post-skip audio track, which is still required: Loop Start establishes its
fingerprint and Current Shot maps exact Plan frame windows onto its sample
clock for H3 audio-latent alignment. Scene-local paired audio from the tagged
motion reference does not replace this master track.

For new workflows, Source Timeline performs that registration without decoding
the complete audio track or requiring the downstream fan-out.

### Tagged Ref2VA source timeline

Current Shot's source slice may feed a standalone Tagged Audio Ref. Keep the
registry fingerprint that returns to Plan independent of that downstream slice:

```text
Plan → Loop Start → Current Shot → Tagged Audio Ref → Tagged Ref2VA
  ↑                                                     │
  └──────── picture/reference registry fingerprint ─────┘
```

The canonical topology is:

```text
Load Audio → Source Timeline → Loop Start → Current Shot
                                             ├→ source_audio_slice → Tagged Audio Ref
                                             └→ state ─────────────→ Tagged Ref2VA
```

The structured scene dependency records the canonical PCM window, so that
scene—not unrelated future audio—is invalidated when the source changes. Do not
return the slice-derived audio fingerprint to Plan, because that would create a
real graph cycle. Current Shot's optional alignment switch changes only the
reference slice.

## Experimental reference-grid alignment

For 362 video frames, the exact picture duration is 15.083333 seconds. Stock H3
creates 603 target audio steps, while an exact-duration audio reference reaches
604 steps after audio-VAE padding.

Current Shot's `align_audio_reference` switch shortens only its Ref2VA output:

```text
362-frame source window: 15.083333 s
aligned reference slice: 15.070000 s
reference audio latents: 603, with a 5 ms padded tail in the final step
```

The exact 15.075-second latent boundary still reproduced visual duplication in
testing; 15.070 seconds did not. The switch therefore uses a 5 ms safety
undercut. It computes the equivalent sample boundary for the connected sample
rate, passes shorter audio through unchanged, and never changes the full source
used by Assemble.

This remains experimental model-behavior guidance rather than a proven H3
architecture requirement. Leave the switch off when comparing against stock
frame-exact behavior.

## Generated audio is always retained

When decoded audio is connected to Segment + Checkpoint, every scene receives
an uncompressed WAV under:

```text
output/h3_chains/<run_name>/generated_audio/
```

Completed assembly also writes `<final-name>.generated.wav` beside the MP4,
even when the final video uses `source_track`. This keeps H3's ambience, effects,
and regenerated performance available for post-production.

Generated WAV assembly budgets samples from cumulative delivered-video frame
boundaries, preventing per-scene rounding from accumulating into drift. This
approach was inspired by **seitanism's**
[MultiRef implementation](https://github.com/seitanism/ComfyUI-H3-Motion-Context-MultiRef).
For masked AV, Loop Trim also carries the complete decoded overlap privately
inside its normal AUDIO output. Segment Save checkpoints it, and the later
scene owns that interval during combined generated-audio assembly. This keeps
Soft AV's half-cosine audio release instead of throwing it away at the trim.
The same ownership rule applies when scene 1 continues an Existing Video
Context prelude. Legacy checkpoints without the extra tensor keep
delivered-only assembly.

## Continuation trimming

Use **MiniMax H3 Contex Loop Trim** after decoding. In head mode it removes the
repeated visual prefix. With `match_tail=true`, it time-conforms the small H3
grid mismatch to the exact delivered-frame duration and carries the
full AV overlap privately to Segment Save. Connect Trim's AUDIO output directly;
there is no second overlap-audio socket.

`images_with_overlap` exposes an additional visual stream containing the
retained repeated context selected by the active scene state. In 0.5 chains,
wire **Current Shot → state** to **Loop Trim → state**. A scene-level
`video_blend_frames` value controls the boundary entering that scene; blank
inherits the Plan default and explicit `0` keeps a hard cut. The manual
`retain_overlap_frames` input and both blend integer outputs are legacy routes.
This assembly-only setting does not alter diffusion, the normal clean images
output, or audio.

All continuation modes return the prefix length as `trim_frames`. In AV mask
modes those leading frames come from target-latent rows rather than persistent
guide-conditioning rows. They still overlap the preceding scene and must be
removed from delivered duration, including the feathered portion.

## Measure a join

Place **MiniMax H3 Contex Loop Seam Probe** between the current clip's untrimmed
audio decode and Loop Trim. Connect the preceding sampler AV latent, H3 audio
VAE, and the same `trim_frames` value.

The AUDIO output is unchanged. The report measures:

- correlation across the join;
- estimated timing offset;
- broadband level step;
- low-frequency ambience-floor step.

Strongly periodic music can alias by one complete cycle; the report marks that
as a known limitation. `tests/seam_probe.py` provides the file-based equivalent.
