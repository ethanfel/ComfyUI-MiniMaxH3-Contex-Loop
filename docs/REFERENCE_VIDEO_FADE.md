# Reference Video Fade (experimental)

## Why it exists

MiniMax H3 does not reduce a Ref2VA video to poses. Core VAE-encodes the
complete 24 fps reference and packs its latent rows into the same transformer
sequence as text, reference pictures/audio, and the target AV streams. Those
video rows remain available at every DiT block and every sampling evaluation.

That strong path explains why a simple character-swap prompt can reproduce the
reference camera, action, and timing so closely. It also means source color,
background, framing, and texture can influence the target even though source
pixels are not directly composited into the output.

Dropping every second or third input frame is not a safe strength control. It
changes reference speed, duration, and temporal coordinates. Repeating frames
keeps duration but introduces stepped motion. Reference Video Fade therefore
keeps the complete video and schedules its transformer contribution instead.

## What the node does

**MiniMax H3 Reference Video Fade (Experimental)** is an opt-in MODEL patch.
During early denoising, native reference-video rows remain at full value
strength. After `fade_start`, their value contribution follows a half-cosine
curve toward `end_strength`:

```text
strength = 1                                      progress <= fade_start
u = (progress - fade_start) / (1 - fade_start)
strength = end + (1-end) × 0.5 × (1 + cos(pi×u)) progress > fade_start
```

`progress` is measured against the complete sigma schedule from 0 at the first
sampling level to 1 at the end. The node modifies only H3 attention V slices
belonging to native `video` and `video_audio` reference blocks. H3's V tensor
is already fresh scratch memory, so the slices are scaled in place without a
sequence-sized mask, a duplicate model, or a second attention pass.

The following remain unchanged:

- native still-picture references;
- Qwen text and visual-presentation tokens;
- native reference audio;
- continuation guides or AV-prefix masks;
- target video and target audio rows.

The reference video is still completely encoded and supplied to H3. This is a
smooth reduction of its attention value contribution, not a hard removal. Its
Q/K rows and Qwen presentation can still carry weaker semantic influence.

## Relationship to continuation color control

Reference Video Fade and **Color-Stable Drift AV** act on different inputs and
can be used together:

- Reference Video Fade reduces late denoising influence from an external
  native Ref2VA motion video. It is the control to test when source framing,
  background, or color keeps leaking into the generated scene.
- Color-Stable Drift AV corrects the disposable previous-scene prefix used for
  chain continuation. It does not alter the external motion reference, source
  audio, or saved scene latent.

Use Reference Video Fade alone to diagnose motion-reference leakage. Add
Color-Stable Drift AV only when chained scenes also develop their own
scene-to-scene color drift. Neither feature modifies the final assembled video.

## Presets

| Preset | Full reference through | End strength |
|---|---:|---:|
| `full` | 100% | 100% (true bypass) |
| `balanced` | 67% | 20% |
| `freer` | 50% | 15% |
| `early_only` | 50% | 0% |
| `custom` | `custom_fade_start` | `custom_end_strength` |

Start with `balanced`. Use `freer` when the reference reproduces source color,
background, or camera too literally. `early_only` is an aggressive diagnostic,
not a recommended default.

## Wiring

For one sampler/model:

```text
H3 MODEL → other backend/model patches → Reference Video Fade → sampler
```

In a Context Loop Drift-Control graph, the faded MODEL may feed Chain Context's
MODEL input; use Chain Context's MODEL output for sampling.

For split-sigma sampling, connect the original **unsplit** schedule to
`full_sigmas`. If the split switches models, put one Reference Video Fade node
on each model branch and connect the same `full_sigmas` to every copy. This
prevents the second half from restarting the fade at progress zero.

Place the node after an attention-backend selector when possible. It chains an
already installed optimized-attention override, including SolAttn or Comfy
Kitchen, instead of replacing it.

## Scope and limitations

- All native `video` and `video_audio` reference blocks are faded. Core does
  not preserve Tagged-reference role names in the packed payload, so a graph
  with several native reference videos fades all of them. Still pictures are
  never selected.
- This is value gating, not an exact target-query-to-reference-key attention
  mask. It is deliberately the low-memory implementation suitable for H3's
  very long packed sequence.
- It does not fade the 2 fps Qwen presentation derived from the reference
  video. Prompts can therefore retain semantic awareness after the native
  latent-video contribution has weakened.
- Results are model-, sampler-, schedule-, and prompt-dependent. Treat the
  presets as experimental comparisons and keep the rest of the graph fixed.
