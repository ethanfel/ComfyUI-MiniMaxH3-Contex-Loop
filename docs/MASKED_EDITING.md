# Masked editing

MiniMax H3 can edit a real source AV latent instead of treating the source as
an ordinary reference. A nested denoise mask controls every target stream:

```text
0 = preserve the source latent
1 = regenerate this row
```

This is the general form of the chain's `masked_av`, `tapered_av`,
`feathered_av`, and `drift_control_av` continuation. The chain builds a
temporal prefix mask automatically; the public masking nodes accept arbitrary
static or tracked spatial masks.

`masked_av` assigns `0` to the complete repeated picture prefix.
Experimental `tapered_av` uses the same hard mask after replacing only the
carried video prefix with a deterministic, disposable matched-variance noise
taper; audio and the accepted predecessor remain unchanged.
`feathered_av` keeps most of that picture prefix exact, then raises the mask
gradually toward `1` over its final latent steps. When Audio Policy enables
Generated continuity, the matching audio prefix participates too: with the
recommended 39-frame context, 8 of 12 video steps and 42 of 65 audio steps are
fully protected; the final 4 video and 23 audio prefix steps form the denoise
ramp. With Generated continuity off, audio remains fully denoisable. Both modes
trim all 39 repeated picture frames after decoding.

Experimental `drift_control_av` keeps the accepted predecessor checkpoint
clean. During sampling it applies the sampler's existing noise field to the
oldest eight of a 12-step picture prefix at `next_sigma / current_sigma`, then
tapers the last four steps `.75/.50/.25/.00` so the seam itself stays exact.
The same live mask reaches H3's row-timestep calculation through Chain
Context's MODEL output. Audio remains owned by Audio Policy. This mode is fixed
to 39 context frames and initially validated at 20 sampling steps.

Start with
[`Masked Video Inpaint - MiniMax H3 0.6.json`](<../example_workflows/Masked Video Inpaint - MiniMax H3 0.6.json>).
For picture-defined replacement appearance, use
[`Ref2V Masked Video Inpaint - MiniMax H3 0.6.json`](<../example_workflows/Ref2V Masked Video Inpaint - MiniMax H3 0.6.json>).
For temporal continuation and bridging, use the three
[masked AV examples](../example_workflows/README.md#masked-editing-and-existing-video).

## Ablejones / MaskVidExperiments interoperability

Ablejones/droz's
[`droz_MiniMaxH3_LatentMaskInpainting_wReference_v3.1.json`](https://discord.com/channels/1076117621407223829/1539132102585356359/1539347237887549512)
uses `MVEx Mask To Latent Space` in `auto + max + max` mode before stock
`Set Latent Noise Mask`. At zero additional grow, that is the same H3 mask
contract as **Apply Target Mask → H3 exact**: VAE-aware causal frame groups,
conservative max reduction, and 2×2 latent-token unification. The corresponding
[workflow thread](https://discord.com/channels/1076117621407223829/1539132102585356359/1539132102585356359)
also documents the crop-based approach and its current border-flicker caveat.

The maintained Ref2V demo maps the remaining wiring as follows:

| Ablejones v3.1 | This pack |
|---|---|
| `MiniMaxH3ReferenceToVideo` picture input | The same core Ref2VA picture input |
| Video/audio VAE encode + two `SetLatentNoiseMask` nodes + `LTXVConcatAVLatent` | **Loop Source AV Target** followed by **Apply Target Mask** on the authoritative stock joint target |
| `MVEx Subject Crop/Uncrop` | Optional external speed/compositing layer; the maintained loop demo stays full-frame |
| SAM3 tracked mask | Any static mask or complete tracked MASK batch through **Loop Mask Slice** |
| `grow_spatial` / `grow_temporal` | Optional pixel-mask preparation before **Loop Mask Slice**; the bundled generous static mask uses zero additional grow |

Do not feed the source movie into Ref2VA again merely to label it. The source
movie is already the clean target latent and supplies protected pixels, motion,
camera, and synchronized audio. A picture reference should supply only the
replacement appearance. Crop/uncrop remains useful when a small subject would
otherwise spend most compute on an unchanged full frame, but a multi-scene
chain must slice crop boxes on the same scene windows before uncropping.

## Nodes

### Masking · Loop Source AV Target

**MiniMax H3 Masking · Loop Source AV Target** is the preferred source-video
path inside Chain Loop. Connect Current Shot `state`, Chain Context `latent`,
both H3 VAEs, and the complete synchronized source frames/audio. The node uses
`generation_start_frame` and the stock H3 joint target to select and encode the
exact current interval.

The stock target's video and audio lengths are authoritative. At fractional
24-fps/40-Hz boundaries, exact picture-duration audio can encode one token
shorter than the stock H3 audio target. This node adds only the encoder-grid
lookahead needed to fill that target and trims back to its exact step count.
Do not put `LTXVConcatAVLatent` or `LTXVSeparateAVLatent` in this path.

### Masking · Loop Mask Slice

**MiniMax H3 Masking · Loop Mask Slice** accepts either one static mask or a
complete tracked MASK batch. A single frame is explicitly broadcast across the
current scene. A multi-frame batch is treated as a source-timeline mask and
sliced with the current shot's `generation_start_frame` and `raw_frames`.

Set `source_fps` to the rate represented by the tracked mask batch. For a
24-fps source/mask pair, the bundled two-scene workflow selects mask frames
0..174 for scene 1 and 136..310 for scene 2. The repeated 136..174 interval is
therefore identical to the source AV continuation overlap. Connect
`scene_mask` to Grid Preview; its existing spatial snapping then operates only
on the correct current interval. Apply Target Mask's exact mode validates that
the returned tracked batch has the complete raw scene length; it never
stretches a short tracked batch silently.

### Masking · Trim Source AV

**MiniMax H3 Masking · Trim Source AV** drops only trailing video frames until
the source has a valid H3 `17k+5` length. Optional source audio is trimmed to
the same duration at H3's fixed 24 fps. It never resizes frames, changes fps,
or pads short audio.

Use the returned `h3_length` for the core H3 conditioning node. Resize the
returned frames once to the final H3 canvas, then feed that exact batch to the
video VAE, mask preview, and any tracking path.

### Masking · Grid Preview

H3's video VAE reduces each spatial axis by 16 and the DiT groups the result
into 2×2 latent patches. One independently masked H3 row therefore covers
roughly **32×32 source pixels**.

**MiniMax H3 Masking · Grid Preview** shows those cells and returns a snapped
MASK suitable for Apply Target Mask. Its canvas must match the encoded source,
be divisible by 32, and contain a valid one-frame or `17k+5` H3 run. Runtime
exact mode also unions every source-frame group that feeds one causal video
latent, then paints that effective selection back over the grouped frames.

- `runtime exact (latent max)` reproduces the spatial reduction used by H3;
- `any pixel coverage` selects a whole cell for any marked source pixel;
- `50% pixel coverage` selects cells at least half covered;
- `full pixel coverage` selects only completely covered cells;
- `cell_adjust` grows or shrinks by complete cells.

The `grid_preview` IMAGE contains only the selected `preview_frame` to avoid
duplicating an entire video for display. The `snapped_mask` output retains the
complete static or tracked mask batch.

### Masking · Apply Target Mask

**MiniMax H3 Masking · Apply Target Mask** expects the source media as the
sampler's real joint video/audio target latent. In a loop, produce it with
**Loop Source AV Target**, apply the mask, and connect `masked_target` to
`SamplerCustomAdvanced.latent_image`.

Do not also add the same source as `<Video>` merely to make masking work. A
reference influences generation; it does not provide the clean latent values
that the mask protects.

The main mask may use either convention:

- `white = generate` for conventional inpainting;
- `white = preserve` when the supplied artwork describes protected content.

The default **H3 exact (causal/token max)** conversion follows the video VAE's
repeating `1,4,4,4,4` pixel-frame groups and max-reduces each group to its real
latent step. It then max-reduces spatially and unifies every 2×2 latent block
read by one H3 token. This preserves thin details and moving-mask coverage that
trilinear interpolation can weaken or shift. One mask is broadcast; a tracked
mask must contain exactly the pixel-frame span represented by the target. In a
loop, connect Loop Mask Slice to supply it. **legacy trilinear** remains
available for reproducing earlier workflows. Switching conversion modes changes
generation, so also change the Plan generation fingerprint and regenerate the
affected scene history. Batch size is currently one.

This conversion is for inpainting, replacement, removal, outpainting, and
other masked edits. It does not add a mask input to ordinary AV extension; the
chain continues to create its own temporal AV-prefix mask automatically.

## Audio modes

| Mode | Behavior |
|---|---|
| `preserve source audio` | Protect the complete encoded source-audio latent. This is the default for visual edits. |
| `generate all audio` | Regenerate the complete H3 audio stream. |
| `follow video mask` | Generate audio during times where any video region is selected. |
| `custom audio mask` | Reduce the optional MASK to a time envelope; white generates and black preserves. |

Audio is not spatial, so a visual object mask has no unique audio equivalent.
Use preserve mode unless the edit deliberately needs new sound.

## Exact master-audio timelines

**Masking · Master Audio + Video Prefix** is the asymmetric timeline-audio
form of target masking. It takes the empty joint target produced by stock H3
conditioning, VAE-encodes the exact master-audio interval beginning at
`clip_start_seconds`, replaces the complete target audio stream, and assigns
audio mask `0` for the full raw clip. The master may be music, dialogue,
narration, or another finished soundtrack.

The H3 target audio grid is authoritative when picture duration falls between
40 Hz boundaries. The node may encode a few milliseconds of additional real
timeline audio so a floor-style audio VAE fills every target step, then crops
the latent to the target length. Its `clip_audio` output remains exactly the
picture duration; it never invents or repeats a latent token.

For live H3 chaining, connect the preceding sampler output to `source_latent`.
The node copies its phase-aligned video-latent tail directly into the protected
target prefix without decoding or re-encoding it. The source latent's audio is
ignored: the selected `master_audio` interval remains authoritative.

`source_frames` remains the legacy fallback for imported or decoded media. The
node converts it to 24 fps, selects the final native H3 context run, VAE-encodes
it into the target video prefix, and protects only those video rows. Connect
either `source_latent` or `source_frames`, never both. Future video rows remain
`1` and are generated normally. The returned `trim_frames` is authoritative
for Loop Trim and visual overlap assembly.

The master audio is target content, not a Ref2VA audio reference. Keep every
`ref_audio_*` input disconnected, and mux the untouched full master audio onto
the assembled picture for final delivery.

## Composition with chain continuation

If the target already contains a nested H3 noise mask, Apply Target Mask
intersects the two masks. **Preservation wins.** This allows an arbitrary
spatial edit to compose safely with the protected or feathered prefix produced
by either AV mask mode:

```text
chain prefix mask × spatial edit mask = final generation mask
```

The same rule holds whether Apply Target Mask sits before or after Chain
Context, because both nodes emit latent-sized nested AV masks.

## Inpaint, outpaint, and clip bridging

The bundled workflow implements video inpainting. The same mask contract also
supports the other operations once their source target is prepared:

- **Outpaint:** place the source on a larger H3 canvas, encode that canvas,
  preserve the original rectangle, and generate the exposed border.
- **Object removal/replacement:** provide a static or tracked object mask and
  describe only the intended replacement while asking H3 to retain the rest.
- **Temporal repair:** use a mask batch that is black on retained frames and
  white during the interval to regenerate.
- **Two-clip bridge:** **Masking · Two-Clip AV Bridge** encodes the end of clip
  A and beginning of clip B into opposite ends of an empty joint H3 target,
  protects both AV windows, and generates only the middle interval. Use exact
  H3 endpoint runs; 39 frames is recommended because it maps to exactly 65
  audio steps.

This integration bundles the arbitrary mask/inpaint workflow and the two-ended
AV bridge. Expanded-canvas outpaint preparation remains external to the pack;
it can be added without changing the H3 mask/runtime layer.

## Runtime compatibility

The masking nodes prefer native ComfyUI support equivalent to PR #15375. On a
supported post-PR-#15439 H3 baseline, they lazily install only the missing mask
engine, payload extraction, token-aligned inpaint scaling, or legacy sampler
bridge. The original pixel mask remains authoritative for final sampler
blending; only H3's internal timestep labels are pooled to the video/audio
token grids. No MODEL patch node is needed, and importing the pack does not
modify stock H3 behavior.

A partially updated native implementation is rejected rather than combined
with the compatibility snapshot. Restart ComfyUI fully after updating core or
an H3 optimization extension.

Per-row mask support guarantees the sampling mechanics, not that H3 was trained
equally strongly for every edit topology. Feathered source preparation and a
short test render remain advisable for outpainting and complex tracked masks.
