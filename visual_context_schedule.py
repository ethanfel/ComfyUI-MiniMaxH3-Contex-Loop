"""Sigma-matched late reveal for recursive MiniMax H3 Guide context.

ComfyUI currently gives every H3 visual condition in one conditioning payload
one static ``visual_cond_noise_aug`` value.  The released default (0.999)
makes a predecessor Guide almost perfectly clean at the first denoising call,
even though the target is still nearly pure noise.  In a recursive chain that
clean condition can repeatedly feed its palette and texture errors into the
next scene.

This experimental patch replaces that static value at each diffusion-model
call.  If ``t = 1 - sigma``, the exact matched recipe uses::

    visual_cond_noise_aug = clamp(max(t, floor), ceiling)

H3 core uses the same value both to mix clean condition latent with a stable,
seeded noise latent and to label the condition timestep.  With ``floor=0`` the
recommended matched recipe therefore starts at the target's own noise level
and reveals the Guide at exactly the same rate as the target denoises.  The
experimental next-step recipe evaluates the same formula at the next lower
endpoint of the original full sigma schedule, allowing the last model call to
see a clean Guide.  The same seeded noise is reused at every call, so both
recipes form coherent forward-noise trajectories rather than fresh random
corruption.

ComfyUI's public payload currently has no per-keyframe strength.  The default
scope therefore installs a hash-gated, behavior-preserving H3 ``_forward``
extension which applies the schedule only to keyframes marked by Chain
Context; identity, authored keyframes, and Ref2VA media retain their original
strength.  An all-visual diagnostic scope uses only the public global payload
value.  Neither scope pretends to modify an AV preserved prefix, which lives in
the target latent and is controlled by a denoise mask instead.
"""

from __future__ import annotations

import logging
import hashlib
import inspect
import math
import re
import types
from typing import Any, Iterable

import torch


_LOG = logging.getLogger(
    "minimax_h3_context_loop.visual_context_late_reveal")
_WRAPPER_KEY = "h3_context_loop_visual_context_late_reveal"
_MODEL_OPTION_MARKER = "h3_context_loop_visual_context_late_reveal_recipe"
_STATE_MARKER = "h3_context_loop_visual_context_late_reveal_state"
_CONTEXT_KEYFRAME_MARKER = "h3_chain_context_visual"
_FUTURE_ANCHOR_KEYFRAME_MARKER = "h3_chain_future_end_anchor"
_SELECTIVE_FORWARD_MARKER = "_h3_context_selective_schedule_version"
_SELECTIVE_FORWARD_VERSION = 1
_CORE_VISUAL_AUGS_KEY = "visual_cond_noise_augs"
_NOISE_BACKENDS = frozenset(("comfy_rows", "dependent_latent"))
_VALIDATED_FORWARD_SHA256S = frozenset((
    # ComfyUI cc0fc21f / current row-wise target-mask implementation.
    "14bdfccd6860f252005b8d43ab446aa9a938a13dc819061724b8f914218f5fd1",
))

_GUIDE_MODES = frozenset((
    "guide",
    "tone_carry_guide",
    "latent_guide",
    "tapered_guide",
))
_AV_MODES = frozenset((
    "masked_av",
    "tapered_av",
    "feathered_av",
    "audio_feathered_av",
    "drift_control_av",
    "color_stable_drift_av",
))


def scheduled_visual_condition_aug(
    sigma: float,
    floor: float = 0.0,
    ceiling: float = 0.999,
) -> float:
    """Return a target-timestep-matched visual-condition augmentation."""
    sigma_value = float(sigma)
    floor_value = float(floor)
    ceiling_value = float(ceiling)
    if not math.isfinite(sigma_value):
        raise ValueError(
            "h3_visual_context_schedule: sigma must be finite.")
    if not math.isfinite(floor_value) or not 0.0 <= floor_value <= 1.0:
        raise ValueError(
            "h3_visual_context_schedule: floor must be in [0, 1].")
    if not math.isfinite(ceiling_value) or not 0.0 <= ceiling_value <= 1.0:
        raise ValueError(
            "h3_visual_context_schedule: ceiling must be in [0, 1].")
    if floor_value > ceiling_value:
        raise ValueError(
            "h3_visual_context_schedule: floor cannot exceed ceiling.")
    target_t = max(0.0, min(1.0, 1.0 - sigma_value))
    return min(ceiling_value, max(floor_value, target_t))


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


def next_schedule_sigma(current_sigma: float, sigmas: Any) -> float:
    """Resolve the next lower full-schedule endpoint for one model call.

    Exact schedule endpoints advance to the following endpoint. Intermediate
    solver evaluations use the lower endpoint of their enclosing interval.
    This keeps split-sigma branches on one absolute schedule and avoids a
    per-branch progress reset.
    """
    schedule = _schedule_values(sigmas)
    if len(schedule) < 2:
        raise ValueError(
            "h3_visual_context_schedule: next_step requires full_sigmas "
            "with at least two finite non-negative levels.")
    current = float(current_sigma)
    if not math.isfinite(current):
        raise ValueError(
            "h3_visual_context_schedule: sigma must be finite.")
    for index, value in enumerate(schedule):
        if math.isclose(current, value, rel_tol=1e-5, abs_tol=1e-6):
            return schedule[min(index + 1, len(schedule) - 1)]
    if current > schedule[0]:
        return schedule[0]
    for high, low in zip(schedule, schedule[1:]):
        if high > current > low:
            return low
    return schedule[-1]


def parse_manual_schedule(value: Any) -> tuple[float, ...]:
    """Parse a compact list of exact visual-condition clean fractions."""
    if isinstance(value, str):
        raw_values = [
            item for item in re.split(r"[,;\s]+", value.strip()) if item
        ]
    elif isinstance(value, Iterable):
        raw_values = list(value)
    else:
        raw_values = [value]
    if not raw_values:
        raise ValueError(
            "h3_visual_context_schedule: manual_schedule must contain at "
            "least one value in [0, 1].")
    parsed = []
    for index, raw_value in enumerate(raw_values):
        if isinstance(raw_value, bool):
            raise ValueError(
                "h3_visual_context_schedule: manual_schedule value %d must "
                "be a number in [0, 1]." % (index + 1))
        try:
            number = float(raw_value)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "h3_visual_context_schedule: manual_schedule value %d (%r) "
                "is not a number." % (index + 1, raw_value)) from exc
        if not math.isfinite(number) or not 0.0 <= number <= 1.0:
            raise ValueError(
                "h3_visual_context_schedule: manual_schedule value %d "
                "must be finite and in [0, 1], got %r."
                % (index + 1, raw_value))
        parsed.append(number)
    return tuple(parsed)


def schedule_step_index(current_sigma: float, sigmas: Any) -> int:
    """Map an absolute sigma to its enclosing full-schedule step.

    A solver evaluation strictly inside ``(sigma[i+1], sigma[i])`` remains
    part of step ``i``.  An evaluation exactly at ``sigma[i+1]`` begins the
    next step.  This makes a manual schedule deterministic for multi-eval
    solvers and across separately patched split-sigma model branches.
    """
    schedule = _schedule_values(sigmas)
    if len(schedule) < 2:
        raise ValueError(
            "h3_visual_context_schedule: a manual schedule requires "
            "full_sigmas with at least two finite non-negative levels.")
    current = float(current_sigma)
    if not math.isfinite(current):
        raise ValueError(
            "h3_visual_context_schedule: sigma must be finite.")
    if current >= schedule[0] or math.isclose(
            current, schedule[0], rel_tol=1e-5, abs_tol=1e-6):
        return 0
    final_step = len(schedule) - 2
    for index, (high, low) in enumerate(zip(schedule, schedule[1:])):
        if math.isclose(current, high, rel_tol=1e-5, abs_tol=1e-6):
            return min(index, final_step)
        if math.isclose(current, low, rel_tol=1e-5, abs_tol=1e-6):
            return min(index + 1, final_step)
        if high > current > low:
            return min(index, final_step)
    return final_step


def _active_schedule_context(
    state: Any,
    scope: str = "chain_context_only",
) -> bool:
    """Resolve whether this scene can contain the selected visual rows."""
    if not isinstance(state, dict):
        return False
    try:
        index = int(state["index"])
        plan = state["plan"]
        compatibility = plan["compatibility"]
        shot = plan["shots"][index - 1]
    except (KeyError, IndexError, TypeError, ValueError):
        return False

    inherited_length = int(compatibility.get("context_length", 0))
    override_length = shot.get("context_length")
    context_length = (
        inherited_length if override_length is None else int(override_length))
    continuation_mode = str(shot.get(
        "continuation_mode",
        compatibility.get("continuation_mode", "guide"),
    ))
    has_predecessor = index > 1 or bool(state.get("external_context"))
    accepted_modes = (
        _GUIDE_MODES | _AV_MODES
        if str(scope) == "future_anchor_only"
        else _GUIDE_MODES
    )
    return (
        has_predecessor
        and context_length > 0
        and continuation_mode in accepted_modes
    )


def _active_guide_context(state: Any) -> bool:
    """Backward-compatible helper for the original Guide-only scope."""
    return _active_schedule_context(state, "chain_context_only")


def _marked_visual_flags(payload: dict, marker: str) -> list[bool]:
    """Return marker flags in ComfyUI's cond-video packing order."""
    flags = [
        bool(keyframe.get(marker, False))
        for keyframe in (payload.get("keyframes") or ())
        if keyframe.get("latent") is not None
    ]
    # Core appends reference latents after all keyframe latents. References
    # are deliberately never weakened by the recursive-context schedule.
    flags.extend(
        False
        for reference in (payload.get("refs") or ())
        if "latent" in reference
    )
    latents = list(payload.get("cond_video_latents") or ())
    if len(flags) != len(latents):
        raise RuntimeError(
            "H3 visual schedule payload order changed: found %d visual "
            "condition records for %d packed latents. Update the ComfyUI "
            "compatibility implementation before sampling."
            % (len(flags), len(latents)))
    return flags


def _context_visual_flags(payload: dict) -> list[bool]:
    """Return recursive-prefix flags (the original selective scope)."""
    return _marked_visual_flags(payload, _CONTEXT_KEYFRAME_MARKER)


def _selective_visual_augs(
    payload: dict,
    scheduled_aug: float,
    default_aug: float,
    selection_flags: Any = None,
) -> list[float]:
    """Keep ordinary refs strong while scheduling selected visual rows."""
    base_aug = float(payload.get("visual_cond_noise_aug", default_aug))
    flags = (
        _context_visual_flags(payload)
        if selection_flags is None
        else [bool(value) for value in selection_flags]
    )
    return [
        float(scheduled_aug) if is_context else base_aug
        for is_context in flags
    ]


def _source_reads_payload_key(source: str, key: str) -> bool:
    """Recognize an explicit payload read, not a comment/name coincidence."""
    return (
        'payload.get("%s"' % key in source
        or "payload.get('%s'" % key in source
        or 'payload["%s"]' % key in source
        or "payload['%s']" % key in source
    )


def _core_supports_per_condition_visual_augs(
    h3m: Any,
    diffusion_model: Any,
    forward_source: str,
) -> bool:
    """Detect the proposed public H3 per-condition augmentation contract.

    Both row construction and segment timestep assignment must consume the
    list. Accepting only one side would silently pair the correct noise mix
    with an incorrect timestep label (or the reverse).
    """
    rows_method = getattr(diffusion_model, "_cond_video_rows", None)
    rows_function = getattr(rows_method, "__func__", rows_method)
    try:
        rows_source = inspect.getsource(rows_function)
    except (OSError, TypeError):
        return False
    direct_contract = (
        _source_reads_payload_key(forward_source, _CORE_VISUAL_AUGS_KEY)
        and _source_reads_payload_key(rows_source, _CORE_VISUAL_AUGS_KEY)
    )
    if direct_contract:
        return True
    if not bool(getattr(
            h3m, "PER_CONDITION_VISUAL_COND_NOISE_AUGS", False)):
        return False
    helper = getattr(diffusion_model, "_visual_cond_noise_augs", None)
    helper_function = getattr(helper, "__func__", helper)
    try:
        helper_source = inspect.getsource(helper_function)
    except (OSError, TypeError):
        return False
    helper_call = "self._visual_cond_noise_augs(payload)"
    return (
        _source_reads_payload_key(helper_source, _CORE_VISUAL_AUGS_KEY)
        and helper_call in rows_source
        and helper_call in forward_source
    )


def _dependent_visual_noise_rows(
    self,
    h3m,
    latent,
    seed: int,
    target_latent_t: int,
    condition_count: int,
):
    """Reproduce the dependent latent-noise draw in public H3 ports.

    The reviewed RunningHub, DiffSynth, and SGLang H3 runtimes draw one CPU
    tensor whose temporal length includes the target plus one slot per visual
    condition, slice the condition's temporal prefix, and only then patchify.
    Every condition restarts the generator at the request seed. SGLang names
    this the dependent-noise policy.
    """
    if not torch.is_tensor(latent) or latent.ndim != 5:
        raise ValueError(
            "H3 Guide Late Reveal dependent latent noise requires a rank-5 "
            "condition latent [B,C,T,H,W].")
    if int(latent.shape[0]) != 1:
        raise ValueError(
            "H3 Guide Late Reveal dependent latent noise supports batch 1.")
    target_t = int(target_latent_t)
    count = int(condition_count)
    if target_t <= 0 or count <= 0:
        raise ValueError(
            "H3 Guide Late Reveal dependent latent noise requires positive "
            "target length and condition count.")
    condition_t = int(latent.shape[2])
    full_t = target_t + count
    if condition_t > full_t:
        raise ValueError(
            "H3 Guide Late Reveal condition length %d exceeds the dependent "
            "noise draw length %d." % (condition_t, full_t))
    generator = torch.Generator("cpu").manual_seed(int(seed))
    noise = torch.randn(
        1,
        int(latent.shape[1]),
        full_t,
        int(latent.shape[3]),
        int(latent.shape[4]),
        generator=generator,
        dtype=torch.float32,
        device="cpu",
    )[:, :, :condition_t]
    return h3m.patchify_video(noise, self.patch_size)


def _condition_rows_with_augs(
    self,
    h3m,
    payload,
    device,
    visual_augs,
    *,
    context_flags=None,
    target_latent_t=None,
    noise_backend="comfy_rows",
):
    latents = list(payload.get("cond_video_latents") or ())
    if len(visual_augs) != len(latents):
        raise RuntimeError(
            "H3 Guide Late Reveal received %d visual strengths for %d "
            "condition latents." % (len(visual_augs), len(latents)))
    backend = str(noise_backend)
    if backend not in _NOISE_BACKENDS:
        raise ValueError(
            "Unknown H3 Guide Late Reveal noise backend %r." % backend)
    if context_flags is None:
        flags = [False] * len(latents)
    else:
        flags = [bool(value) for value in context_flags]
        if len(flags) != len(latents):
            raise RuntimeError(
                "H3 Guide Late Reveal received %d context flags for %d "
                "condition latents." % (len(flags), len(latents)))
    if backend == "dependent_latent" and target_latent_t is None:
        raise ValueError(
            "H3 Guide Late Reveal dependent latent noise requires the target "
            "latent temporal length.")
    seed = int(payload.get("seed", 0))
    rows = []
    for latent, raw_aug, is_context in zip(latents, visual_augs, flags):
        aug = float(raw_aug)
        row = h3m.patchify_video(
            latent.to(torch.float32), self.patch_size)
        if aug < 1.0:
            if backend == "dependent_latent" and is_context:
                # Secondary A/B only. Ordinary authored/reference rows keep
                # ComfyUI's byte-for-byte row-noise construction.
                noise = _dependent_visual_noise_rows(
                    self,
                    h3m,
                    latent,
                    seed,
                    int(target_latent_t),
                    len(latents),
                )
            else:
                # Match stock ComfyUI exactly: each visual condition restarts
                # the same CPU RNG stream, producing stable noise at every
                # sampler call.
                generator = torch.Generator("cpu").manual_seed(seed)
                noise = torch.randn(
                    row.shape, generator=generator, dtype=torch.float32)
            row = aug * row + (1.0 - aug) * noise.to(row.device)
        rows.append(row.to(device))
    return torch.cat(rows, dim=0) if rows else None


def _segment_timestep_plan(
    layout,
    t_video: float,
    t_audio: float,
    visual_augs,
    audio_aug: float,
) -> list[float]:
    """Map per-condition strengths to their packed H3 layout segments."""
    visual_index = 0
    segment_times = []
    for _start, _stop, kind in layout.segments:
        if kind in {"cond", "ref_img"}:
            if visual_index >= len(visual_augs):
                raise RuntimeError(
                    "H3 Guide Late Reveal layout contains more visual "
                    "segments than condition strengths.")
            segment_times.append(max(
                t_video, float(visual_augs[visual_index])))
            visual_index += 1
        elif kind in {"cond_audio", "ref_audio"}:
            segment_times.append(max(t_audio, float(audio_aug)))
        elif kind in {"text", "video"}:
            segment_times.append(t_video)
        elif kind == "audio":
            segment_times.append(t_audio)
        else:
            raise RuntimeError(
                "Unknown MiniMax H3 packed segment kind: %s" % kind)
    if visual_index != len(visual_augs):
        raise RuntimeError(
            "H3 Guide Late Reveal received %d visual strengths but the "
            "layout contains %d visual segments."
            % (len(visual_augs), visual_index))
    return segment_times


def _selective_context_forward(
    self,
    h3m,
    runtime,
    x,
    timestep,
    context,
    transformer_options=None,
    minimax_payload=None,
    denoise_mask=None,
    audio_denoise_mask=None,
    **kwargs,
):
    """Current ComfyUI H3 _forward with per-visual-condition timesteps.

    This is intentionally hash-gated at installation.  Apart from replacing
    the single visual augmentation/timestep with one value per packed visual
    condition, it preserves the validated core forward contract verbatim,
    including row-wise AV masks, attention replacements, Kitchen/SolAttn
    routing, prefetch, and the final velocity heads.
    """
    transformer_options = transformer_options or {}
    video_x, audio_x = x[0], x[1]
    orig_t, orig_h, orig_w = (
        video_x.shape[2], video_x.shape[3], video_x.shape[4])
    video_x = h3m.comfy.ldm.common_dit.pad_to_patch_size(
        video_x, self.patch_size)
    if video_x.shape[0] != 1:
        raise ValueError("MiniMax H3 supports batch size 1")
    payload = minimax_payload or {}
    device = video_x.device
    dtype = context.dtype

    latent_t, lat_h, lat_w = (
        video_x.shape[2], video_x.shape[3], video_x.shape[4])
    audio_t = audio_x.shape[-1]
    text_len = context.shape[1]
    layout = payload.get("layout")
    if (layout is None or layout.signature !=
            (text_len, latent_t, lat_h, lat_w, audio_t)):
        layout = h3m.PackedLayout(
            text_len, latent_t, lat_h, lat_w, audio_t,
            keyframes=payload.get("keyframes"),
            refs=payload.get("refs"))

    shift_v = float(transformer_options.get(
        "minimax_h3_sigma_shift_video", self.sigma_shift_video))
    shift_a = float(transformer_options.get(
        "minimax_h3_sigma_shift_audio", self.sigma_shift_audio))
    sigma_v = (timestep.flatten()[0] / 1000.0).float().clamp(min=1e-6)
    sigma_value = float(sigma_v)
    t_v = float(1.0 - sigma_v)
    t_a = float(1.0 - h3m.time_shift_sigma(
        sigma_v, shift_v, shift_a))

    scheduled_aug = runtime.aug_for_sigma(sigma_value)
    context_flags = runtime.selection_flags(payload)
    visual_augs = _selective_visual_augs(
        payload,
        scheduled_aug,
        h3m.VISUAL_COND_TIMESTEP,
        selection_flags=context_flags,
    )
    audio_aug = float(payload.get(
        "audio_cond_noise_aug", h3m.AUDIO_COND_TIMESTEP))
    segment_times = _segment_timestep_plan(
        layout, t_v, t_a, visual_augs, audio_aug)

    # Preserve current ComfyUI's row-wise target mask timestep behavior.
    t_pin_v = max(t_v, h3m.VISUAL_COND_TIMESTEP)
    t_pin_a = max(t_a, h3m.AUDIO_COND_TIMESTEP)
    video_rows_t = None
    audio_rows_t = None
    if denoise_mask is not None:
        mask = h3m.mask_row_values(
            denoise_mask[0, 0].to(torch.float32),
            latent_t, lat_h, lat_w)
        if mask is not None:
            rows_t = (
                1.0 - mask * sigma_v.to(mask.device)).clamp(max=t_pin_v)
            if rows_t.unique().numel() == 1:
                video_time = float(rows_t[0])
                for index, (_a, _b, kind) in enumerate(layout.segments):
                    if kind == "video":
                        segment_times[index] = video_time
                        break
            else:
                video_rows_t = rows_t
    if audio_denoise_mask is not None:
        mask = audio_denoise_mask[0, 0].to(torch.float32).reshape(-1)
        if not bool((mask >= 1.0 - 1e-3).all()):
            sigma_a = 1.0 - t_a
            rows_t = (1.0 - mask * sigma_a).clamp(max=t_pin_a)
            if rows_t.unique().numel() == 1:
                audio_time = float(rows_t[0])
                for index, (_a, _b, kind) in enumerate(layout.segments):
                    if kind == "audio":
                        segment_times[index] = audio_time
                        break
            else:
                audio_rows_t = rows_t

    unique_t = sorted(
        set(segment_times)
        | (set(video_rows_t.unique().tolist())
           if video_rows_t is not None else set())
        | (set(audio_rows_t.unique().tolist())
           if audio_rows_t is not None else set()))
    t_row = {value: index for index, value in enumerate(unique_t)}
    segment_tags = {
        "text": 1, "video": 0, "audio": 2, "cond": 0,
        "ref_img": 0, "cond_audio": 2, "ref_audio": 2,
    }

    def rows_to_mod_index(rows, tag):
        levels = rows.unique()
        base = torch.tensor(
            [t_row[value] * 3 + tag for value in levels.tolist()],
            dtype=torch.long, device=rows.device)
        return base[torch.searchsorted(levels, rows)]

    text_tags = payload.get("text_token_tags")
    mod_segments = []
    for segment_index, (start, stop, kind) in enumerate(layout.segments):
        row_base = t_row[segment_times[segment_index]] * 3
        if kind == "text" and text_tags is not None:
            tags = text_tags.view(-1).tolist()
            run_start = 0
            for index in range(1, stop - start + 1):
                if (index == stop - start
                        or tags[index] != tags[run_start]):
                    mod_segments.append((
                        start + run_start, start + index,
                        row_base + int(tags[run_start])))
                    run_start = index
        elif kind == "video" and video_rows_t is not None:
            mod_segments.append((
                start, stop,
                rows_to_mod_index(video_rows_t, segment_tags[kind])))
        elif kind == "audio" and audio_rows_t is not None:
            mod_segments.append((
                start, stop,
                rows_to_mod_index(audio_rows_t, segment_tags[kind])))
        else:
            mod_segments.append((
                start, stop, row_base + segment_tags[kind]))

    img_update = layout.img_update.to(device)
    audio_update = layout.audio_update.to(device)
    video_rows = h3m.patchify_video(
        video_x.to(torch.float32), self.patch_size)
    audio_rows = h3m.pack_audio(audio_x.to(torch.float32))
    cond_video_rows = _condition_rows_with_augs(
        self,
        h3m,
        payload,
        device,
        visual_augs,
        context_flags=context_flags,
        target_latent_t=orig_t,
        noise_backend=runtime.noise_backend,
    )
    cond_audio_rows = self._cond_audio_rows(payload, device)

    all_video_rows = video_rows
    if cond_video_rows is not None:
        all_video_rows = torch.empty(
            img_update.shape[0], video_rows.shape[1],
            dtype=torch.float32, device=device)
        all_video_rows[~img_update] = cond_video_rows
        all_video_rows[img_update] = video_rows
    all_audio_rows = audio_rows
    if cond_audio_rows is not None:
        all_audio_rows = torch.empty(
            audio_update.shape[0], audio_rows.shape[1],
            dtype=torch.float32, device=device)
        all_audio_rows[~audio_update] = cond_audio_rows
        all_audio_rows[audio_update] = audio_rows

    video_embed = self.video_patch_proj(all_video_rows).to(dtype)
    audio_embed = self.audio_patch_proj(all_audio_rows).to(dtype)
    text_states = context[0]
    if text_states.shape[-1] != self.hidden_size:
        text_states = self.token_refiner(
            self.condition_proj(text_states),
            transformer_options=transformer_options)

    hidden = torch.empty(
        layout.seq_len, self.hidden_size, dtype=dtype, device=device)
    video_offset = audio_offset = 0
    for start, stop, kind in layout.segments:
        count = stop - start
        if kind == "text":
            hidden[start:stop] = text_states
        elif kind in {"cond", "ref_img", "video"}:
            hidden[start:stop] = video_embed[
                video_offset:video_offset + count]
            video_offset += count
        else:
            hidden[start:stop] = audio_embed[
                audio_offset:audio_offset + count]
            audio_offset += count

    t_values = torch.tensor(unique_t, dtype=torch.float32, device=device)
    if self.use_adaln_curves:
        table = h3m.comfy.model_management.cast_to(
            self.adaln_t_table, device=device)
        position = t_values.clamp(0.0, 1.0) * (table.shape[0] - 1)
        lower = position.floor().long().clamp(max=table.shape[0] - 2)
        t_emb = torch.lerp(
            table[lower], table[lower + 1],
            (position - lower).unsqueeze(1))
    else:
        t_emb = self.time_embedder(t_values).to(dtype)

    rope_freqs = h3m.rope_rotation_table(
        self.rope_freqs(layout.position_ids, device), dtype)
    patches_replace = transformer_options.get("patches_replace", {})
    blocks_replace = patches_replace.get("dit", {})
    prefetch_queue = h3m.comfy.model_prefetch.make_prefetch_queue(
        list(self.blocks), device, transformer_options)
    for index, block in enumerate(self.blocks):
        h3m.comfy.model_prefetch.prefetch_queue_pop(
            prefetch_queue, device, block)
        if ("double_block", index) in blocks_replace:
            def block_wrap(args, current_block=block):
                return {"img": current_block(
                    args["img"], args["t_emb"], args["mod_segments"],
                    args["rope_freqs"],
                    transformer_options=args["transformer_options"])}

            hidden = blocks_replace[("double_block", index)](
                {"img": hidden, "t_emb": t_emb,
                 "mod_segments": mod_segments,
                 "rope_freqs": rope_freqs,
                 "transformer_options": transformer_options},
                {"original_block": block_wrap})["img"]
        else:
            hidden = block(
                hidden, t_emb, mod_segments, rope_freqs,
                transformer_options=transformer_options)
    if prefetch_queue is not None:
        h3m.comfy.model_prefetch.prefetch_queue_pop(
            prefetch_queue, device, None)

    video_index, (video_start, video_stop, _kind) = next(
        (index, segment)
        for index, segment in enumerate(layout.segments)
        if segment[2] == "video")
    audio_index, (audio_start, audio_stop, _kind) = next(
        (index, segment)
        for index, segment in enumerate(layout.segments)
        if segment[2] == "audio")
    if video_rows_t is not None:
        video_segment = (
            video_start, video_stop,
            rows_to_mod_index(video_rows_t, 0) // 3)
    else:
        video_segment = (
            video_start, video_stop,
            t_row[segment_times[video_index]])
    if audio_rows_t is not None:
        audio_segment = (
            audio_start, audio_stop,
            rows_to_mod_index(audio_rows_t, 0) // 3)
    else:
        audio_segment = (
            audio_start, audio_stop,
            t_row[segment_times[audio_index]])
    video_out, audio_out = self.final_layer(
        hidden, t_emb, video_segment, audio_segment)
    video_out = h3m.unpatchify_video(
        video_out, latent_t, lat_h // 2, lat_w // 2,
        self.latents_dim, self.patch_size)
    video_out = video_out[:, :, :orig_t, :orig_h, :orig_w]
    audio_out = h3m.unpack_audio(audio_out)
    return [-video_out.to(video_x.dtype), -audio_out.to(audio_x.dtype)]


class _VisualContextScheduleState:
    """Runtime state for one cloned H3 model patch."""

    def __init__(
        self,
        floor: float,
        ceiling: float,
        mode: str = "matched",
        full_sigmas: Any = None,
        noise_backend: str = "comfy_rows",
        manual_schedule: Any = None,
        selection_marker: str = _CONTEXT_KEYFRAME_MARKER,
        selection_label: str = "Chain Context prefix",
    ):
        scheduled_visual_condition_aug(1.0, floor, ceiling)
        self.floor = float(floor)
        self.ceiling = float(ceiling)
        self.mode = str(mode)
        if self.mode not in {"matched", "next_step", "manual"}:
            raise ValueError(
                "h3_visual_context_schedule: mode must be matched, "
                "next_step, or manual.")
        self.full_sigmas = _schedule_values(full_sigmas)
        if self.mode in {"next_step", "manual"} and len(
                self.full_sigmas) < 2:
            raise ValueError(
                "h3_visual_context_schedule: %s requires the original "
                "full_sigmas input." % self.mode)
        self.manual_schedule = (
            parse_manual_schedule(manual_schedule)
            if self.mode == "manual" else ())
        if (self.mode == "manual"
                and len(self.manual_schedule) > len(self.full_sigmas) - 1):
            raise ValueError(
                "h3_visual_context_schedule: manual_schedule contains %d "
                "values but full_sigmas defines only %d sampler steps."
                % (len(self.manual_schedule), len(self.full_sigmas) - 1))
        self.noise_backend = str(noise_backend)
        if self.noise_backend not in _NOISE_BACKENDS:
            raise ValueError(
                "h3_visual_context_schedule: noise_backend must be one of "
                "%s." % sorted(_NOISE_BACKENDS))
        self.selection_marker = str(selection_marker)
        self.selection_label = str(selection_label)
        self.last_sigma: float | None = None
        self.last_basis_sigma: float | None = None
        self.last_aug: float | None = None
        self.model_calls = 0
        self._reported_active = False

    def selection_flags(self, payload: dict) -> list[bool]:
        return _marked_visual_flags(payload, self.selection_marker)

    def endpoint_aug_summary(self) -> str:
        if self.mode == "manual":
            return (
                "manual values [%s] over %d sampler steps; final value "
                "holds after entry %d"
                % (
                    ", ".join("%.3f" % value
                              for value in self.manual_schedule),
                    len(self.full_sigmas) - 1,
                    len(self.manual_schedule),
                ))
        if self.mode != "next_step":
            return "dynamic current-step schedule"
        values = [
            scheduled_visual_condition_aug(
                self.full_sigmas[index + 1], self.floor, self.ceiling)
            for index in range(len(self.full_sigmas) - 1)
        ]
        return "%d calls: [%s]" % (
            len(values), ", ".join("%.3f" % value for value in values))

    def aug_for_sigma(self, sigma: float) -> float:
        basis_sigma = float(sigma)
        if self.mode == "manual":
            step_index = schedule_step_index(
                basis_sigma, self.full_sigmas)
            self.last_sigma = float(sigma)
            self.last_basis_sigma = basis_sigma
            self.last_aug = self.manual_schedule[min(
                step_index, len(self.manual_schedule) - 1)]
            return self.last_aug
        if self.mode == "next_step":
            basis_sigma = next_schedule_sigma(
                basis_sigma, self.full_sigmas)
        self.last_sigma = float(sigma)
        self.last_basis_sigma = basis_sigma
        self.last_aug = scheduled_visual_condition_aug(
            basis_sigma, self.floor, self.ceiling)
        return self.last_aug

    def report_model_call(self) -> None:
        """Log the discriminating early schedule points for a live A/B."""
        if self.model_calls > 3:
            return
        if (self.last_sigma is None or self.last_basis_sigma is None
                or self.last_aug is None):
            return
        _LOG.info(
            "H3 Guide Late Reveal call %d: target sigma %.6f, basis sigma "
            "%.6f, context clean fraction/timestep %.6f",
            self.model_calls, self.last_sigma, self.last_basis_sigma,
            self.last_aug)

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
        payload = minimax_payload
        visual_rows = (
            payload.get("cond_video_latents")
            if isinstance(payload, dict) else None)
        if visual_rows:
            # MiniMaxH3Model receives model_sampling.timestep(sigma), which is
            # sigma * 1000 for this flow model. This remains absolute across
            # a split-sigma handoff; next_step resolves it against the one
            # original full schedule supplied to both model branches.
            timestep_value = float(
                torch.as_tensor(timestep).detach().float().reshape(-1)[0])
            sigma = timestep_value / 1000.0
            aug = self.aug_for_sigma(sigma)
            # Never mutate shared conditioning state in place. Latent tensors
            # remain shared; only this tiny dictionary is copied per call.
            payload = dict(payload)
            payload["visual_cond_noise_aug"] = aug
            self.model_calls += 1
            if not self._reported_active:
                _LOG.info(
                    "H3 Guide Late Reveal active: visual conditions use %s "
                    "schedule, floor %.3f, ceiling %.3f; current "
                    "ComfyUI applies the schedule to every visual condition "
                    "row in this continuation payload; %s",
                    self.mode, self.floor, self.ceiling,
                    self.endpoint_aug_summary())
                self._reported_active = True
            self.report_model_call()
        if payload is not None:
            kwargs["minimax_payload"] = payload
        return executor(
            x, timestep, context, transformer_options=options, **kwargs)

    def selective_diffusion_model_wrapper(
        self,
        executor,
        x,
        timestep,
        context,
        transformer_options=None,
        minimax_payload=None,
        **kwargs,
    ):
        """Use a future core per-condition API without replacing _forward."""
        options = transformer_options if isinstance(
            transformer_options, dict) else {}
        payload = minimax_payload
        if isinstance(payload, dict):
            flags = self.selection_flags(payload)
            if any(flags):
                timestep_value = float(
                    torch.as_tensor(timestep).detach().float().reshape(-1)[0])
                aug = self.aug_for_sigma(timestep_value / 1000.0)
                raw_augs = payload.get(_CORE_VISUAL_AUGS_KEY)
                if raw_augs is None:
                    base = float(payload.get(
                        "visual_cond_noise_aug", 0.999))
                    visual_augs = [base] * len(flags)
                else:
                    visual_augs = [float(value) for value in raw_augs]
                    if len(visual_augs) != len(flags):
                        raise RuntimeError(
                            "H3 Guide Late Reveal core API received %d visual "
                            "strengths for %d condition blocks."
                            % (len(visual_augs), len(flags)))
                visual_augs = [
                    aug if is_context else visual_augs[index]
                    for index, is_context in enumerate(flags)
                ]
                payload = dict(payload)
                payload[_CORE_VISUAL_AUGS_KEY] = visual_augs
                self.model_calls += 1
                if not self._reported_active:
                    _LOG.info(
                        "H3 Guide Late Reveal using native per-condition "
                        "core API: %d %s block(s) scheduled, %d "
                        "other visual block(s) unchanged; %s",
                        sum(flags), self.selection_label,
                        len(flags) - sum(flags),
                        self.endpoint_aug_summary())
                    self._reported_active = True
                self.report_model_call()
        if payload is not None:
            kwargs["minimax_payload"] = payload
        return executor(
            x, timestep, context, transformer_options=options, **kwargs)


def install_visual_context_schedule_model(
    model: Any,
    floor: float = 0.0,
    ceiling: float = 0.999,
    scope: str = "chain_context_only",
    mode: str = "matched",
    full_sigmas: Any = None,
    noise_backend: str = "comfy_rows",
    manual_schedule: Any = None,
):
    """Clone an H3 model and install the per-call Guide schedule."""
    scheduled_visual_condition_aug(1.0, floor, ceiling)
    scope_value = str(scope)
    if scope_value not in {
            "chain_context_only", "future_anchor_only",
            "all_visual_conditions"}:
        raise ValueError(
            "Unknown H3 visual context schedule scope %r." % scope_value)
    noise_backend_value = str(noise_backend)
    if noise_backend_value not in _NOISE_BACKENDS:
        raise ValueError(
            "Unknown H3 Guide Late Reveal noise backend %r."
            % noise_backend_value)
    if (scope_value == "all_visual_conditions"
            and noise_backend_value != "comfy_rows"):
        raise ValueError(
            "dependent_latent noise requires a selective scope. Use "
            "scope=chain_context_only, scope=future_anchor_only, or "
            "noise_backend=comfy_rows.")
    if model is None or not callable(getattr(model, "clone", None)):
        raise ValueError(
            "H3 Guide Late Reveal requires a ComfyUI MODEL input.")
    inner = getattr(model, "model", None)
    model_type = str(getattr(getattr(inner, "model_type", None), "name", ""))
    if model_type != "FLOW_AV" and inner.__class__.__name__ != "MiniMaxH3":
        raise ValueError(
            "H3 Guide Late Reveal only supports MiniMax H3 AV models.")

    patched = model.clone()
    options = getattr(patched, "model_options", None)
    if not isinstance(options, dict):
        raise ValueError(
            "H3 Guide Late Reveal received a MODEL without model options.")
    if _MODEL_OPTION_MARKER in options:
        raise ValueError(
            "H3 Guide Late Reveal is already installed on this MODEL. Use "
            "one instance per model branch.")
    selection_marker = (
        _FUTURE_ANCHOR_KEYFRAME_MARKER
        if scope_value == "future_anchor_only"
        else _CONTEXT_KEYFRAME_MARKER
    )
    selection_label = (
        "future-anchor"
        if scope_value == "future_anchor_only"
        else "Chain Context prefix"
    )
    runtime = _VisualContextScheduleState(
        floor,
        ceiling,
        mode=mode,
        full_sigmas=full_sigmas,
        noise_backend=noise_backend_value,
        manual_schedule=manual_schedule,
        selection_marker=selection_marker,
        selection_label=selection_label,
    )
    backend = "global_payload_wrapper"
    if scope_value == "all_visual_conditions":
        if not callable(getattr(patched, "add_wrapper_with_key", None)):
            raise RuntimeError(
                "H3 Guide Late Reveal requires current ComfyUI model "
                "wrappers for the all-visual diagnostic scope.")
        from comfy.patcher_extension import WrappersMP
        patched.add_wrapper_with_key(
            WrappersMP.DIFFUSION_MODEL,
            _WRAPPER_KEY,
            runtime.diffusion_model_wrapper,
        )
    else:
        if not callable(getattr(patched, "get_model_object", None)):
            raise RuntimeError(
                "H3 Guide Late Reveal selective scope requires current "
                "ComfyUI MODEL object access.")
        from comfy.ldm.minimax import model as h3m

        base_model = patched.model
        diffusion_model = getattr(base_model, "diffusion_model", None)
        if diffusion_model is None:
            raise ValueError(
                "H3 Guide Late Reveal could not find the MiniMax H3 "
                "diffusion model inside this MODEL.")
        original_forward = patched.get_model_object(
            "diffusion_model._forward")
        existing_version = getattr(
            original_forward, _SELECTIVE_FORWARD_MARKER, None)
        if existing_version is not None:
            raise ValueError(
                "H3 Guide Late Reveal selective scheduling is already "
                "installed on this MODEL branch.")
        if getattr(original_forward, "_t8_multikeyframe_patch_version", None):
            raise RuntimeError(
                "H3 Guide Late Reveal cannot safely stack its selective "
                "forward with T8 per-keyframe forward patching. Use the "
                "all_visual_conditions diagnostic scope or one patch only.")
        forward_function = getattr(
            original_forward, "__func__", original_forward)
        if getattr(forward_function, "__module__", None) != h3m.__name__:
            raise RuntimeError(
                "An unrecognized MiniMax H3 _forward object patch is "
                "already active; selective context scheduling was refused "
                "to avoid unsafe wrapper order.")
        try:
            forward_source = inspect.getsource(forward_function)
        except (OSError, TypeError) as exc:
            raise RuntimeError(
                "H3 Guide Late Reveal could not inspect ComfyUI's MiniMax "
                "H3 _forward implementation, so selective scheduling was "
                "refused safely.") from exc
        if _core_supports_per_condition_visual_augs(
                h3m, diffusion_model, forward_source):
            if runtime.noise_backend != "comfy_rows":
                raise RuntimeError(
                    "This ComfyUI H3 core exposes per-condition strengths "
                    "but not a selectable condition-noise construction. "
                    "Use noise_backend=comfy_rows until core exposes that "
                    "capability.")
            if not callable(getattr(patched, "add_wrapper_with_key", None)):
                raise RuntimeError(
                    "This ComfyUI H3 core supports per-condition visual "
                    "strengths, but its MODEL lacks diffusion wrappers.")
            from comfy.patcher_extension import WrappersMP
            patched.add_wrapper_with_key(
                WrappersMP.DIFFUSION_MODEL,
                _WRAPPER_KEY + "_selective",
                runtime.selective_diffusion_model_wrapper,
            )
            backend = "core_per_condition"
        else:
            if not callable(getattr(patched, "add_object_patch", None)):
                raise RuntimeError(
                    "H3 Guide Late Reveal selective compatibility requires "
                    "current ComfyUI MODEL object patches.")
            forward_hash = hashlib.sha256(
                forward_source.encode("utf-8")).hexdigest()
            if forward_hash not in _VALIDATED_FORWARD_SHA256S:
                raise RuntimeError(
                    "This ComfyUI build changed MiniMax H3 _forward and does "
                    "not expose the reviewed per-condition visual API; "
                    "selective Guide scheduling is disabled until that "
                    "implementation is reviewed. Expected %s, got %s. The "
                    "all_visual_conditions diagnostic scope does not replace "
                    "_forward."
                    % (sorted(_VALIDATED_FORWARD_SHA256S), forward_hash))
            required_contract = (
                'layout = payload.get("layout")',
                "cond_video_rows = self._cond_video_rows(payload, device)",
                "mod_segments = []",
                "mask_row_values",
                "self.final_layer",
            )
            missing = [
                snippet for snippet in required_contract
                if snippet not in forward_source
            ]
            if missing:
                raise RuntimeError(
                    "This ComfyUI build no longer matches the validated H3 "
                    "forward contract; missing %s." % missing)

            def _patched_forward(_self, *args, **kwargs):
                payload = kwargs.get("minimax_payload") or {}
                flags = runtime.selection_flags(payload)
                if not any(flags):
                    return original_forward(*args, **kwargs)
                if not runtime._reported_active:
                    _LOG.info(
                        "H3 Guide Late Reveal selective compatibility active: "
                        "%d %s visual block(s) follow %s "
                        "schedule, floor %.3f, ceiling %.3f; %d other visual "
                        "reference block(s) retain their original strength; %s",
                        sum(flags), runtime.selection_label, runtime.mode,
                        runtime.floor,
                        runtime.ceiling, len(flags) - sum(flags),
                        runtime.endpoint_aug_summary())
                    _LOG.info(
                        "H3 Guide Late Reveal context noise backend: %s",
                        runtime.noise_backend)
                    runtime._reported_active = True
                timestep = (
                    args[1] if len(args) > 1 else kwargs.get("timestep"))
                if timestep is not None:
                    timestep_value = float(torch.as_tensor(
                        timestep).detach().float().reshape(-1)[0])
                    runtime.aug_for_sigma(timestep_value / 1000.0)
                    runtime.model_calls += 1
                    runtime.report_model_call()
                return _selective_context_forward(
                    _self, h3m, runtime, *args, **kwargs)

            setattr(
                _patched_forward, _SELECTIVE_FORWARD_MARKER,
                _SELECTIVE_FORWARD_VERSION)
            patched.add_object_patch(
                "diffusion_model._forward",
                types.MethodType(_patched_forward, diffusion_model))
            backend = "compat_forward"
    options[_MODEL_OPTION_MARKER] = {
        "version": 7,
        "floor": float(floor),
        "ceiling": float(ceiling),
        "rule": (
            "manual_full_sigma_step_hold_last"
            if runtime.mode == "manual"
            else "clamp(max(1-basis_sigma,floor),ceiling)"),
        "mode": runtime.mode,
        "full_sigma_count": len(runtime.full_sigmas),
        "manual_schedule": list(runtime.manual_schedule),
        "scope": scope_value,
        "selection_marker": runtime.selection_marker,
        "backend": backend,
        "noise_backend": runtime.noise_backend,
    }
    options[_STATE_MARKER] = runtime
    return patched


class MiniMaxH3VisualContextLateRevealModelPatch:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "model": ("MODEL", {
                    "tooltip": "MiniMax H3 AV MODEL. Route the output through "
                               "every sampler stage."}),
                "state": ("H3_CHAIN_STATE", {
                    "tooltip": "Current Shot state. Scene 1 and Cut pass "
                               "through unchanged. Prefix scopes activate on "
                               "Guide continuations; future_anchor_only also "
                               "activates on AV continuations."}),
                "preset": ([
                    "off", "matched", "next_step", "manual", "custom",
                ], {
                    "default": "matched",
                    "tooltip": "matched (recommended first A/B): noise and "
                               "reveal recursive Guide context at the "
                               "target's exact current timestep. next_step "
                               "uses the next full-schedule endpoint and "
                               "reaches a clean Guide on the final model "
                               "call; connect full_sigmas. off is unchanged. "
                               "manual reads one exact clean fraction per "
                               "full-schedule step and holds its final value; "
                               "connect full_sigmas. "
                               "custom uses exact matching with expert floor "
                               "and ceiling."}),
                "scope": ([
                    "chain_context_only",
                    "future_anchor_only",
                    "all_visual_conditions",
                ], {
                    "default": "chain_context_only",
                    "tooltip": "chain_context_only (recommended): schedule "
                               "only predecessor Guide blocks created by "
                               "Chain Context; identity, keyframes, and "
                               "Ref2VA media stay at their original strength. "
                               "future_anchor_only: schedule only the marked "
                               "one-frame suffix created by Chain Context; "
                               "this works with Guide and AV. For a two-step "
                               "composition anchor, use manual preset, "
                               "'0.999, 0.999, 0', and full_sigmas. "
                               "all_visual_conditions: diagnostic mode that "
                               "also schedules every other visual reference."}),
                "noise_backend": ([
                    "comfy_rows",
                    "dependent_latent",
                ], {
                    "default": "comfy_rows",
                    "tooltip": "comfy_rows (recommended first A/B): keep "
                               "ComfyUI's existing packed-row noise exactly. "
                               "dependent_latent (secondary A/B): only for "
                               "Chain Context rows, reproduce public H3 "
                               "ports' dependent target-length latent noise "
                               "before patchification; other references stay "
                               "unchanged."}),
                "manual_schedule": ("STRING", {
                    "default": "0.000, 0.999",
                    "multiline": False,
                    "tooltip": "Manual preset only. Comma, semicolon, space, "
                               "or newline-separated clean fractions in "
                               "[0,1], indexed by the original full sigma "
                               "schedule. If fewer values than sampler steps "
                               "are supplied, the final value holds. Example "
                               "'0, 0.999' means first step 0 and every later "
                               "step 0.999. Connect full_sigmas."}),
                "custom_floor": ("FLOAT", {
                    "default": 0.000, "min": 0.000, "max": 1.000,
                    "step": 0.001, "round": 0.001,
                    "tooltip": "Custom only. Minimum clean fraction and "
                               "timestep pin at the start. 0 is the exact "
                               "target-matched research recipe."}),
                "custom_ceiling": ("FLOAT", {
                    "default": 0.999, "min": 0.000, "max": 1.000,
                    "step": 0.001, "round": 0.001,
                    "tooltip": "Custom only. Maximum clean fraction late "
                               "in denoising; 0.999 matches current H3 visual "
                               "conditioning convention."}),
            },
            "optional": {
                "full_sigmas": ("SIGMAS", {
                    "tooltip": "Required by next_step and manual. Connect "
                               "the original unsplit scheduler output so both "
                               "split-sigma sampler stages share one absolute "
                               "schedule."}),
            },
        }

    RETURN_TYPES = ("MODEL",)
    RETURN_NAMES = ("model",)
    OUTPUT_TOOLTIPS = (
        "H3 MODEL with a sigma-indexed schedule for the selected recursive "
        "Guide prefix, future suffix anchor, or all visual conditions.",
    )
    FUNCTION = "patch"
    CATEGORY = "conditioning/minimax/context_loop/experimental"
    DESCRIPTION = (
        "Research patch for recursive visual-context drift. At each H3 model "
        "call it schedules either the predecessor Guide prefix, the separate "
        "future suffix anchor, or all visual conditions. "
        "A manual preset accepts exact per-step clean fractions and holds its "
        "last value. "
        "It is cheap and split-sigma safe. The recommended selective scope "
        "leaves character, authored keyframe, and Ref2VA rows unchanged; the "
        "all-visual scope is retained as a diagnostic. It does not modify an "
        "AV prefix; future_anchor_only schedules only its separate Guide "
        "suffix. The default noise backend retains ComfyUI exactly; an "
        "optional secondary backend reproduces public H3 latent-noise order."
    )

    def patch(
        self,
        model,
        state,
        preset,
        scope,
        noise_backend,
        manual_schedule,
        custom_floor,
        custom_ceiling,
        full_sigmas=None,
    ):
        preset_value = str(preset)
        if preset_value == "off":
            return (model,)
        if preset_value == "next_step":
            floor, ceiling, mode = 0.0, 0.999, "next_step"
        elif preset_value == "matched":
            floor, ceiling, mode = 0.0, 0.999, "matched"
        elif preset_value == "manual":
            floor, ceiling, mode = 0.0, 0.999, "manual"
        elif preset_value == "custom":
            floor, ceiling, mode = (
                float(custom_floor), float(custom_ceiling), "matched")
        else:
            raise ValueError(
                "Unknown H3 Guide Late Reveal preset %r." % preset)
        # Validate before scene 1 runs so a missing next-step schedule or bad
        # custom range cannot waste a completed first generation only to fail
        # when scene 2 first activates recursive context.
        _VisualContextScheduleState(
            floor,
            ceiling,
            mode=mode,
            full_sigmas=full_sigmas,
            noise_backend=noise_backend,
            manual_schedule=manual_schedule,
        )
        if not _active_schedule_context(state, scope):
            return (model,)
        return (install_visual_context_schedule_model(
            model, floor=floor, ceiling=ceiling, scope=scope,
            mode=mode, full_sigmas=full_sigmas,
            noise_backend=noise_backend,
            manual_schedule=manual_schedule),)


NODE_CLASS_MAPPINGS = {
    "MiniMaxH3VisualContextLateRevealModelPatch": (
        MiniMaxH3VisualContextLateRevealModelPatch),
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "MiniMaxH3VisualContextLateRevealModelPatch": (
        "MiniMax H3 Visual Context Schedule (Research)"),
}
