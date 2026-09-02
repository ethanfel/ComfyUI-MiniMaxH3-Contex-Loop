"""Schedule native MiniMax H3 reference-video influence during denoising.

H3 packs native Ref2VA picture/video/audio blocks into the same transformer
sequence as the target streams.  A reference video is therefore available to
every DiT block at every sampling evaluation; it is not reduced to a pose map.
That is useful for exact motion transfer, but it can also carry source color,
background, framing, and texture farther into the render than desired.

This experimental MODEL patch leaves the full reference video present during
early denoising, then applies a half-cosine fade to the value rows belonging to
native ``video`` and ``video_audio`` reference blocks.  Native still-picture
rows, Qwen presentation tokens, reference audio, continuation guides, and the
target streams are unchanged.

The patch mutates H3's freshly cloned V tensor in place before the active
attention backend consumes it.  It therefore adds no sequence-sized mask and
no second attention pass.  An existing optimized-attention override (including
SolAttn or Comfy Kitchen) remains the executor after this small value gate.
"""

from __future__ import annotations

import logging
import math
from typing import Any, Iterable

import torch


_LOG = logging.getLogger("minimax_h3_context_loop.reference_video_fade")
_WRAPPER_KEY = "h3_context_loop_reference_video_fade"
_MODEL_OPTION_MARKER = "h3_context_loop_reference_video_fade_recipe"
_STATE_MARKER = "h3_context_loop_reference_video_fade_state"


REFERENCE_VIDEO_FADE_PRESETS = {
    "full": (1.0, 1.0),
    "balanced": (0.67, 0.20),
    "freer": (0.50, 0.15),
    "early_only": (0.50, 0.0),
}


def _schedule_values(sigmas: Any) -> tuple[float, ...]:
    """Return finite non-negative scheduler levels in descending order."""
    if torch.is_tensor(sigmas):
        values: Iterable[Any] = sigmas.detach().float().reshape(-1).cpu()
    else:
        values = sigmas or ()
    normalized = []
    for value in values:
        number = float(value)
        if math.isfinite(number) and number >= 0.0:
            normalized.append(number)
    return tuple(sorted(set(normalized), reverse=True))


def schedule_progress(current_sigma: float, sigmas: Any) -> float | None:
    """Map an absolute sigma onto normalized progress through a full schedule."""
    schedule = _schedule_values(sigmas)
    if len(schedule) < 2:
        return None
    current = float(current_sigma)
    if not math.isfinite(current):
        return None
    if current >= schedule[0]:
        return 0.0
    if current <= schedule[-1]:
        return 1.0
    denominator = float(len(schedule) - 1)
    for index, (high, low) in enumerate(zip(schedule, schedule[1:])):
        if high >= current >= low:
            width = high - low
            fraction = 0.0 if width <= 0.0 else (high - current) / width
            return max(0.0, min(1.0, (index + fraction) / denominator))
    return None


def reference_strength(
    progress: float,
    fade_start: float,
    end_strength: float,
) -> float:
    """Half-cosine reference strength from full influence to the end value."""
    start = float(fade_start)
    end = float(end_strength)
    if not 0.0 <= start <= 1.0:
        raise ValueError("reference_video_fade: fade_start must be in [0, 1].")
    if not 0.0 <= end <= 1.0:
        raise ValueError(
            "reference_video_fade: end_strength must be in [0, 1].")
    position = max(0.0, min(1.0, float(progress)))
    if position <= start or start >= 1.0:
        return 1.0
    u = (position - start) / (1.0 - start)
    return end + (1.0 - end) * 0.5 * (1.0 + math.cos(math.pi * u))


def reference_video_ranges(
    payload: Any,
) -> tuple[tuple[tuple[int, int], ...], int]:
    """Resolve packed row ranges for native video refs, excluding pictures."""
    if not isinstance(payload, dict):
        return (), 0
    layout = payload.get("layout")
    segments = tuple(getattr(layout, "segments", ()) or ())
    if not segments:
        return (), 0
    refs = tuple(payload.get("refs") or ())
    visual_refs = tuple(
        ref for ref in refs
        if isinstance(ref, dict)
        and str(ref.get("kind") or "") in ("image", "video", "video_audio")
    )
    visual_segments = tuple(
        (int(start), int(stop))
        for start, stop, kind in segments
        if str(kind) == "ref_img"
    )
    # A mismatch means an unknown core/fork changed row packing.  Refuse to
    # guess: fading a picture or target range would be worse than a no-op.
    if len(visual_refs) != len(visual_segments):
        return (), int(segments[-1][1])
    ranges = tuple(
        segment for ref, segment in zip(visual_refs, visual_segments)
        if str(ref.get("kind") or "") in ("video", "video_audio")
    )
    return ranges, int(segments[-1][1])


class _ReferenceVideoFadeState:
    """Per-cloned-model schedule and packed-reference attention state."""

    def __init__(
        self,
        fade_start: float,
        end_strength: float,
        schedule_override: Any = None,
    ):
        # Validate eagerly, including the full-strength boundary case.
        reference_strength(1.0, fade_start, end_strength)
        self.fade_start = float(fade_start)
        self.end_strength = float(end_strength)
        self.schedule_override = _schedule_values(schedule_override)
        self.current_strength = 1.0
        self.current_progress = 0.0
        self.current_sigma: float | None = None
        self.reference_ranges: tuple[tuple[int, int], ...] = ()
        self.sequence_length = 0
        self.gated_attention_calls = 0
        self._warned_schedule = False
        self._warned_layout = False
        self._reported_active = False

    def _update(
        self,
        timestep: Any,
        transformer_options: dict[str, Any],
        payload: Any,
    ) -> None:
        timestep_value = float(
            torch.as_tensor(timestep).detach().float().reshape(-1)[0])
        # H3 BaseModel supplies model_sampling.timestep(sigma) = sigma * 1000.
        sigma = timestep_value / 1000.0
        schedule = (
            self.schedule_override
            or _schedule_values(transformer_options.get("sample_sigmas", ()))
            or _schedule_values(transformer_options.get("sigmas", ()))
        )
        progress = schedule_progress(sigma, schedule)
        if progress is None:
            # Normal Comfy sampling exposes sample_sigmas.  This fallback keeps
            # an unusual custom sampler usable while making its limitation
            # visible instead of silently restarting a split schedule.
            progress = max(0.0, min(1.0, 1.0 - sigma))
            if not self._warned_schedule:
                _LOG.warning(
                    "H3 Reference Video Fade received no usable sigma "
                    "schedule; falling back to 1-sigma progress. Connect the "
                    "original full_sigmas for split or custom sampling.")
                self._warned_schedule = True
        ranges, sequence_length = reference_video_ranges(payload)
        has_video_ref = (
            isinstance(payload, dict)
            and any(
                isinstance(ref, dict)
                and str(ref.get("kind") or "") in ("video", "video_audio")
                for ref in (payload.get("refs") or ()))
        )
        if not ranges and has_video_ref:
            if not self._warned_layout:
                _LOG.warning(
                    "H3 Reference Video Fade found no safely identifiable "
                    "native video-reference rows. The patch is a no-op for "
                    "this conditioning payload.")
                self._warned_layout = True
        self.current_sigma = sigma
        self.current_progress = progress
        self.current_strength = reference_strength(
            progress, self.fade_start, self.end_strength)
        self.reference_ranges = ranges
        self.sequence_length = sequence_length
        if ranges and not self._reported_active:
            _LOG.info(
                "H3 Reference Video Fade active on %d native video block(s); "
                "full through %.0f%% of denoising, then cosine fade to %.0f%%",
                len(ranges), self.fade_start * 100.0,
                self.end_strength * 100.0)
            self._reported_active = True

    def diffusion_model_wrapper(
        self,
        executor,
        x,
        timestep,
        context,
        transformer_options=None,
        minimax_payload=None,
        **kwargs,
    ):
        options = transformer_options if isinstance(
            transformer_options, dict) else {}
        self._update(timestep, options, minimax_payload)
        if minimax_payload is not None:
            kwargs["minimax_payload"] = minimax_payload
        return executor(
            x, timestep, context, transformer_options=options, **kwargs)

    def make_attention_override(self, previous_override=None):
        state = self

        def override(
            original,
            q,
            k,
            v,
            heads,
            mask=None,
            attn_precision=None,
            skip_reshape=False,
            skip_output_reshape=False,
            **kwargs,
        ):
            strength = float(state.current_strength)
            ranges = state.reference_ranges
            sequence_length = int(state.sequence_length)
            if (
                strength < 1.0 - 1e-7
                and ranges
                and skip_reshape
                and torch.is_tensor(q)
                and torch.is_tensor(k)
                and torch.is_tensor(v)
                and q.ndim == k.ndim == v.ndim == 4
                and int(q.shape[-2]) == sequence_length
                and int(k.shape[-2]) == sequence_length
                and int(v.shape[-2]) == sequence_length
            ):
                # H3 creates V with v.clone() immediately before attention, so
                # these small slices are single-owner scratch memory.  In-place
                # scaling avoids another sequence-sized allocation per block.
                for start, stop in ranges:
                    v[..., int(start):int(stop), :].mul_(strength)
                state.gated_attention_calls += 1

            call_kwargs = dict(
                mask=mask,
                attn_precision=attn_precision,
                skip_reshape=skip_reshape,
                skip_output_reshape=skip_output_reshape,
                **kwargs,
            )
            if previous_override is not None:
                return previous_override(
                    original, q, k, v, heads, **call_kwargs)
            return original(q, k, v, heads, **call_kwargs)

        return override


def resolve_reference_video_fade_preset(
    preset: str,
    custom_fade_start: float,
    custom_end_strength: float,
) -> tuple[float, float]:
    name = str(preset or "balanced")
    if name == "custom":
        values = (float(custom_fade_start), float(custom_end_strength))
    elif name in REFERENCE_VIDEO_FADE_PRESETS:
        values = REFERENCE_VIDEO_FADE_PRESETS[name]
    else:
        raise ValueError(
            "Unknown H3 Reference Video Fade preset %r." % name)
    reference_strength(1.0, values[0], values[1])
    return values


def install_reference_video_fade_model(
    model: Any,
    fade_start: float,
    end_strength: float,
    schedule_override: Any = None,
):
    """Clone one H3 model and install the schedule-aware reference gate."""
    reference_strength(1.0, fade_start, end_strength)
    if float(fade_start) >= 1.0 and float(end_strength) >= 1.0:
        return model
    if model is None or not callable(getattr(model, "clone", None)):
        raise ValueError(
            "H3 Reference Video Fade requires a ComfyUI MODEL input.")
    inner = getattr(model, "model", None)
    model_type = str(getattr(getattr(inner, "model_type", None), "name", ""))
    if model_type != "FLOW_AV" and inner.__class__.__name__ != "MiniMaxH3":
        raise ValueError(
            "H3 Reference Video Fade only supports MiniMax H3 AV models.")

    patched = model.clone()
    options = getattr(patched, "model_options", None)
    if not isinstance(options, dict):
        raise ValueError(
            "H3 Reference Video Fade received a MODEL without model options.")
    if _MODEL_OPTION_MARKER in options:
        raise ValueError(
            "H3 Reference Video Fade is already installed on this MODEL. "
            "Use one fade patch per model branch.")
    if not callable(getattr(patched, "add_wrapper_with_key", None)):
        raise RuntimeError(
            "H3 Reference Video Fade requires current ComfyUI model wrappers.")

    from comfy.patcher_extension import WrappersMP

    transformer_options = dict(options.get("transformer_options") or {})
    previous_override = transformer_options.get(
        "optimized_attention_override")
    state = _ReferenceVideoFadeState(
        fade_start,
        end_strength,
        schedule_override=schedule_override,
    )
    transformer_options["optimized_attention_override"] = (
        state.make_attention_override(previous_override))
    options["transformer_options"] = transformer_options
    patched.add_wrapper_with_key(
        WrappersMP.DIFFUSION_MODEL,
        _WRAPPER_KEY,
        state.diffusion_model_wrapper,
    )
    options[_MODEL_OPTION_MARKER] = {
        "version": 1,
        "fade_start": float(fade_start),
        "end_strength": float(end_strength),
        "full_schedule_values": len(state.schedule_override),
        "scope": "native_video_and_video_audio_value_rows",
    }
    options[_STATE_MARKER] = state
    _LOG.info(
        "H3 Reference Video Fade installed: start %.3f, end %.3f, %s; "
        "existing attention override %s",
        float(fade_start), float(end_strength),
        ("%d full-schedule values" % len(state.schedule_override)
         if state.schedule_override else "sampler-provided schedule"),
        "chained" if previous_override is not None else "not present",
    )
    return patched


class MiniMaxH3ReferenceVideoFadeModelPatch:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "model": ("MODEL", {
                    "tooltip": "MiniMax H3 AV MODEL. Place this after any "
                               "backend/model patches and route its output "
                               "through every sampler stage."}),
                "preset": ([
                    "full", "balanced", "freer", "early_only", "custom",
                ], {
                    "default": "balanced",
                    "tooltip": "full: unchanged. balanced: full through 67%, "
                               "fade to 20%. freer: full through 50%, fade to "
                               "15%. early_only: full through 50%, fade to "
                               "zero. custom uses the two expert widgets."}),
                "custom_fade_start": ("FLOAT", {
                    "default": 0.67, "min": 0.0, "max": 1.0,
                    "step": 0.01,
                    "tooltip": "Custom only. Fraction of the COMPLETE "
                               "denoising schedule that keeps native video "
                               "references at full strength."}),
                "custom_end_strength": ("FLOAT", {
                    "default": 0.20, "min": 0.0, "max": 1.0,
                    "step": 0.01,
                    "tooltip": "Custom only. Native video-reference value "
                               "strength at the end of denoising."}),
            },
            "optional": {
                "full_sigmas": ("SIGMAS", {
                    "tooltip": "Original COMPLETE sigma schedule before any "
                               "split. Required for split-sigma sampling so "
                               "stage two continues the same fade instead of "
                               "starting a new local curve. Use the same "
                               "schedule on every switched model branch."}),
            },
        }

    RETURN_TYPES = ("MODEL",)
    RETURN_NAMES = ("model",)
    OUTPUT_TOOLTIPS = (
        "H3 MODEL with an opt-in native reference-video denoising fade. "
        "Still-picture refs, Qwen presentation, reference audio, continuation "
        "guides, and target streams remain unchanged.",
    )
    FUNCTION = "patch"
    CATEGORY = "conditioning/minimax/context_loop/experimental"
    DESCRIPTION = (
        "Experimental low-memory Ref2VA freedom control. H3 still receives "
        "the complete native reference video, but its attention value "
        "contribution fades late in denoising. This targets every native "
        "video/video+audio reference block and leaves still pictures intact. "
        "It composes with an existing SolAttn or Comfy Kitchen attention "
        "override. For sigma splits, connect the original full schedule."
    )

    def patch(
        self,
        model,
        preset,
        custom_fade_start,
        custom_end_strength,
        full_sigmas=None,
    ):
        fade_start, end_strength = resolve_reference_video_fade_preset(
            preset, custom_fade_start, custom_end_strength)
        return (install_reference_video_fade_model(
            model,
            fade_start,
            end_strength,
            schedule_override=full_sigmas,
        ),)


NODE_CLASS_MAPPINGS = {
    "MiniMaxH3ReferenceVideoFadeModelPatch": (
        MiniMaxH3ReferenceVideoFadeModelPatch),
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "MiniMaxH3ReferenceVideoFadeModelPatch": (
        "MiniMax H3 Reference Video Fade (Experimental)"),
}
