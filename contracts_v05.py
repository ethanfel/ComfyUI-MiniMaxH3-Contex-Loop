"""Stable data-contract declarations for the 0.5 workflow UX migration.

This module is deliberately independent from ComfyUI, PyTorch, and the node
implementations.  It freezes the vocabulary and compatibility translations
before runtime nodes start consuming the new contracts.
"""

from __future__ import annotations

from typing import Any


SOURCE_TIMELINE_VERSION = "h3_source_timeline_v1"
AUDIO_POLICY_VERSION = "h3_audio_policy_v1"
TRANSITION_POLICY_VERSION = "h3_transition_policy_v1"
CHAIN_POLICY_VERSION = "h3_chain_policy_v1"
LIP_SYNC_OPTIONS_VERSION = "h3_lip_sync_options_v1"
SCENE_DEPENDENCY_VERSION = "h3_scene_dependency_v1"
PREFLIGHT_VERSION = "h3_preflight_v1"

FINAL_AUDIO_POLICIES = ("generated", "source", "none")
SOURCE_REFERENCE_POLICIES = ("off", "on")
GENERATED_CONTINUITY_POLICIES = ("off", "on")
SOURCE_AUDIO_TARGET_POLICIES = ("off", "locked")
PAIRED_AUDIO_POLICIES = ("off", "embedded")
PRIMARY_TRANSITION_PRESETS = ("cut", "guide", "hard_av", "soft_av")
GENERATION_SCENE_PROFILES = {
    "Visual continuity": "guide",
    "Independent scenes": "cut",
    "Hard picture + protected audio": "hard_av",
    "Hard picture + smooth audio": "soft_av",
}
GENERATION_AUDIO_PROFILES = {
    "Generate audio": ("generated", "off", "on", False),
    "Generate fresh audio per scene": ("generated", "off", "off", False),
    "Lip-sync to source audio": ("source", "off", "off", True),
    "Generate audio from source guide": ("generated", "on", "off", False),
    "Use source soundtrack only": ("source", "off", "off", False),
    "No final audio": ("none", "off", "off", False),
}
ADVANCED_TRANSITION_PRESETS = (
    "cut", "guide", "tone_guide", "latent_guide", "detail_guide",
    "detail_av", "drift_av", "color_drift_av", "hard_av", "soft_av",
)
DEFAULT_AUDIO_CONTEXT_LENGTH = 22
CONTEXT_SPATIAL_PROXY_MODES = ("off", "rgb_5_6", "latent_5_6")
CONTINUATION_POLICIES = (
    "guide", "tone_carry_guide", "latent_guide", "tapered_guide",
    "masked_av", "tapered_av", "feathered_av", "audio_feathered_av",
    "drift_control_av", "color_stable_drift_av")
TRANSITION_CONTEXT_LENGTHS = (
    0, 1, 5, 22, 39, 56, 73, 90, 107, 124,
    141, 158, 175, 192, 209, 226, 243,
)
AV_TRANSITION_CONTEXT_LENGTHS = (39, 90, 141, 192, 243)
VIDEO_ONLY_AV_TRANSITION_CONTEXT_LENGTHS = tuple(
    value for value in TRANSITION_CONTEXT_LENGTHS if value >= 5
)

# Experimental one-shot latent-context recipe adapted from beijinren's
# ComfyUI-H3-Context-Noise. Keep every generation-significant value in the
# scene dependency contract so changing the recipe cannot silently resume a
# scene rendered with an older taper.
DETAIL_AV_RECIPE = {
    "version": "h3_detail_av_latent_taper_v2",
    "context_frames": 39,
    "video_steps": 12,
    "alpha": 0.30,
    "alpha_end": 0.00,
    "ramp_steps": 4,
    "noise_scale": "match_latent_std",
    "seed_xor": 0xD37A11,
}

# Experimental recursive AV treatment.  Unlike Detail AV, this does not bake
# static noise into the copied predecessor.  At each model evaluation it uses
# the sampler's existing noise field and advances the video prefix to the next
# scheduler sigma.  The oldest eight of the 12 carried video steps receive the
# complete matched-noise ratio; the newest four taper .75/.50/.25/.00 so the
# generated-future boundary remains exact.  Audio retains the selected Audio
# Policy's normal hard/open mask.
DRIFT_CONTROL_AV_RECIPE = {
    "version": "h3_drift_control_av_v1",
    "context_frames": 39,
    "video_steps": 12,
    "matched_steps": 8,
    "taper_steps": 4,
    "sigma_rule": "next_schedule_sigma_over_current_sigma",
    "mask_quantization": 256,
    "audio": "unchanged_policy_mask",
    "validated_steps": 20,
}

# Optional scene-one color anchor layered onto Drift-Control AV.  Only the
# disposable copied video prefix is touched.  Two encodes isolate the desired
# RGB change from ordinary VAE reconstruction error:
# E(graded decode) - E(original decode).  The low-frequency delta fades from
# zero at the old overlap edge to full strength beside the generated future.
# Saved predecessor video/audio latents and the complete audio path remain
# immutable.
LATENT_COLOR_CARRY_RECIPE = {
    "version": "h3_latent_color_delta_v1",
    "context_frames": 39,
    "video_steps": 12,
    "anchor": "first_generated_scene_delivered_tail",
    "source": "current_predecessor_delivered_tail",
    "strength": 0.50,
    "max_luma_shift_code_values": 6.0,
    "max_saturation_change": 0.06,
    "spatial_lowpass_kernel": 3,
    "temporal_taper": "full_prefix_smoothstep_zero_to_one",
    "delta_rule": "E(graded_D(z))-E(D(z))",
    "audio": "unchanged",
}

# Boundary-only low-grid experiment reconstructed from a mixed-resolution
# chain: a 1376x768 target carried a predecessor generated at 1152x640.  The
# Guide recipe spatially reduces the complete saved predecessor video latent,
# decodes that disposable 5/6 latent at its native 1152x640 canvas, then lets
# Motion Context restore only the requested RGB tail to the target canvas.
# This deliberately keeps the nonlinear low-grid VAE decode that a simple RGB
# resize cannot reproduce.  AV keeps its cheaper latent down/up prefix filter.
# Generated scenes and checkpoint/assembly artifacts keep the Plan canvas.
CONTEXT_SPATIAL_PROXY_RECIPE = {
    "version": "h3_context_spatial_proxy_v2",
    "scale_numerator": 5,
    "scale_denominator": 6,
    "pixel_alignment": 32,
    "guide_source": "saved_predecessor_video_latent",
    "guide_latent_downsample": "area",
    "guide_decode": "full_low_grid_stream",
    "guide_tail": "delivered_frames",
    "guide_restore": "motion_context_lanczos",
    "latent_downsample": "area",
    "latent_restore": "bilinear",
    "preserve_latent_statistics": False,
}

LEGACY_AUDIO_MODE_POLICIES = {
    "source_track": {
        "final_audio": "source",
        "source_reference": "on",
        "generated_continuity": "off",
    },
    "generated_audio": {
        "final_audio": "generated",
        "source_reference": "off",
        "generated_continuity": "on",
    },
    "source_plus_timeline": {
        "final_audio": "source",
        "source_reference": "on",
        "generated_continuity": "on",
    },
}

TRANSITION_PRESETS = {
    "cut": {
        "continuation_mode": "guide",
        "context_length": 0,
        "label": "Cut / Independent",
    },
    "guide": {
        "continuation_mode": "guide",
        "context_length": 22,
        "label": "Guided transition",
    },
    "tone_guide": {
        "continuation_mode": "tone_carry_guide",
        "context_length": 22,
        "label": "Tone-carry guided transition",
    },
    "latent_guide": {
        "continuation_mode": "latent_guide",
        "context_length": 22,
        "label": "Latent-guided transition",
    },
    "detail_guide": {
        "continuation_mode": "tapered_guide",
        "context_length": 22,
        "label": "Detail-preserving guided transition",
    },
    "detail_av": {
        "continuation_mode": "tapered_av",
        "context_length": 39,
        "label": "Detail-preserving AV continuation (experimental)",
    },
    "drift_av": {
        "continuation_mode": "drift_control_av",
        "context_length": 39,
        "label": "Drift-Control AV continuation (experimental)",
    },
    "color_drift_av": {
        "continuation_mode": "color_stable_drift_av",
        "context_length": 39,
        "label": "Color-Stable Drift AV continuation (experimental)",
    },
    "hard_av": {
        "continuation_mode": "masked_av",
        "context_length": 39,
        "label": "Hard continuation",
    },
    "soft_av": {
        "continuation_mode": "audio_feathered_av",
        "context_length": 39,
        "label": "Soft continuation (hard picture, soft audio)",
    },
    "audio_feather_av": {
        "continuation_mode": "audio_feathered_av",
        "context_length": 39,
        "label": "Audio-feathered continuation (legacy alias)",
    },
}

DEPENDENCY_SCOPES = (
    "global_generation",
    "scene_generation",
    "incoming_boundary",
    "assembly_only",
)


def migrate_legacy_audio_mode(mode: str) -> dict[str, str]:
    """Return a new independent audio-policy record for a 0.4 mode."""
    try:
        policy = LEGACY_AUDIO_MODE_POLICIES[str(mode)]
    except KeyError as exc:
        raise ValueError("Unknown legacy H3 audio mode %r." % mode) from exc
    return {"version": AUDIO_POLICY_VERSION, **policy}


def migrate_continuation_mode(mode: str) -> str:
    """Map retired experimental implementations to a supported mode."""
    value = str(mode)
    if value == "feathered_av_rgb":
        return "feathered_av"
    return value


def audio_policy(
    final_audio: str,
    source_reference: str,
    generated_continuity: str,
    source_audio_target: str | bool = "off",
    lip_sync_options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate and return one independent 0.5 audio-policy record."""
    final = str(final_audio)
    source = str(source_reference)
    continuity = str(generated_continuity)
    if isinstance(source_audio_target, bool):
        target = "locked" if source_audio_target else "off"
    else:
        target = str(source_audio_target or "off").strip().lower()
    if final not in FINAL_AUDIO_POLICIES:
        raise ValueError("Unknown H3 final-audio policy %r." % final_audio)
    if source not in SOURCE_REFERENCE_POLICIES:
        raise ValueError(
            "Unknown H3 source-reference policy %r." % source_reference)
    if continuity not in GENERATED_CONTINUITY_POLICIES:
        raise ValueError(
            "Unknown H3 generated-continuity policy %r." %
            generated_continuity)
    if target not in SOURCE_AUDIO_TARGET_POLICIES:
        raise ValueError(
            "Unknown H3 source-audio-target policy %r." %
            source_audio_target)
    # A clean source waveform occupying the complete target audio latent is
    # already the strongest possible audio condition.  Keeping a separate
    # Ref2VA audio bank or a predecessor audio prefix would describe competing
    # clocks, so the compact switch resolves both axes off canonically.
    if target == "locked":
        source = "off"
        continuity = "off"
    policy = {
        "version": AUDIO_POLICY_VERSION,
        "final_audio": final,
        "source_reference": source,
        "generated_continuity": continuity,
    }
    # Preserve the byte-for-byte v1 spelling for existing workflows and
    # checkpoints when the new opt-in behavior is disabled.
    if target != "off":
        policy["source_audio_target"] = target
    if target == "locked" and lip_sync_options is not None:
        policy["lip_sync_options"] = masked_song_options(lip_sync_options)
    return policy


def masked_song_options(
    value: dict[str, Any] | None = None,
    *,
    preroll_seconds: float = 1.0,
    lookahead_seconds: float = 0.2,
    audio_denoise: float = 0.0,
    gap_denoise: float = 0.15,
    gate_hold_seconds: float = 0.2,
    voice_fingerprint: str = "",
) -> dict[str, Any]:
    """Validate the optional contextual song-latent recipe.

    The record is stored only for target-locked source audio.  Its absence is
    the stable spelling of the pre-feature hard-cut/full-freeze behavior.
    """
    if value is not None:
        if not isinstance(value, dict):
            raise ValueError(
                "H3 lip-sync options must come from MiniMax H3 Lip-Sync "
                "Options.")
        if value.get("version") != LIP_SYNC_OPTIONS_VERSION:
            raise ValueError("H3 lip-sync options version is missing or obsolete.")
        preroll_seconds = value.get("preroll_seconds", preroll_seconds)
        lookahead_seconds = value.get("lookahead_seconds", lookahead_seconds)
        audio_denoise = value.get("audio_denoise", audio_denoise)
        gap_denoise = value.get("gap_denoise", gap_denoise)
        gate_hold_seconds = value.get(
            "gate_hold_seconds", gate_hold_seconds)
        voice_fingerprint = value.get(
            "voice_fingerprint", voice_fingerprint)

    def bounded(name: str, raw: Any, low: float, high: float) -> float:
        if isinstance(raw, bool):
            raise ValueError("H3 lip-sync %s must be a number." % name)
        try:
            resolved = float(raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "H3 lip-sync %s must be a number." % name) from exc
        if resolved < low or resolved > high:
            raise ValueError(
                "H3 lip-sync %s must be between %.3g and %.3g." %
                (name, low, high))
        return resolved

    resolved = {
        "version": LIP_SYNC_OPTIONS_VERSION,
        "preroll_seconds": bounded(
            "pre-roll", preroll_seconds, 0.0, 4.0),
        "lookahead_seconds": bounded(
            "lookahead", lookahead_seconds, 0.0, 2.0),
        "audio_denoise": bounded(
            "sung-region denoise", audio_denoise, 0.0, 1.0),
        "gap_denoise": bounded(
            "gap denoise", gap_denoise, 0.0, 1.0),
        "gate_hold_seconds": bounded(
            "voice-gate hold", gate_hold_seconds, 0.0, 2.0),
    }
    fingerprint = str(voice_fingerprint or "").strip().lower()
    if fingerprint:
        if (len(fingerprint) != 64 or any(
                character not in "0123456789abcdef"
                for character in fingerprint)):
            raise ValueError(
                "H3 lip-sync voice fingerprint must be a SHA-256 hex digest.")
        resolved["voice_fingerprint"] = fingerprint
    return resolved


def compose_chain_policy(
    audio: dict[str, Any],
    transition: dict[str, Any],
    *,
    audio_context_length: int = DEFAULT_AUDIO_CONTEXT_LENGTH,
) -> dict[str, Any]:
    """Combine validated 0.5 policies without changing their stored shape.

    Plan consumes the two canonical child records and the legacy-compatible
    audio-context value, then persists behavior-only compatibility fields.
    This keeps checkpoint hashes independent of workflow topology.
    """
    if not isinstance(audio, dict) or audio.get("version") != AUDIO_POLICY_VERSION:
        raise ValueError("H3 Chain Policy requires a current Audio Policy.")
    resolved_audio = audio_policy(
        audio.get("final_audio"), audio.get("source_reference"),
        audio.get("generated_continuity"),
        audio.get("source_audio_target", "off"),
        audio.get("lip_sync_options"))
    if (not isinstance(transition, dict) or
            transition.get("version") != TRANSITION_POLICY_VERSION):
        raise ValueError("H3 Chain Policy requires a current Transition Policy.")
    resolved_transition = transition_policy(
        transition.get("preset"),
        expert_override=bool(transition.get("expert_override", False)),
        continuation_mode=transition.get("continuation_mode"),
        context_length=transition.get("context_length"))
    if isinstance(audio_context_length, bool):
        raise ValueError(
            "H3 Chain Policy audio context must be between 0 and 240 frames.")
    try:
        resolved_audio_context = int(audio_context_length)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "H3 Chain Policy audio context must be between 0 and 240 frames."
        ) from exc
    if resolved_audio_context < 0 or resolved_audio_context > 240:
        raise ValueError(
            "H3 Chain Policy audio context must be between 0 and 240 frames.")
    mode = str(resolved_transition["continuation_mode"])
    context = int(resolved_transition["context_length"])
    carries_generated_audio = (
        resolved_audio["generated_continuity"] == "on"
        and resolved_audio.get("source_audio_target", "off") != "locked"
        and resolved_audio_context > 0
    )
    if (mode in (
            "masked_av", "feathered_av", "audio_feathered_av"
        ) and context > 0 and carries_generated_audio
            and context not in AV_TRANSITION_CONTEXT_LENGTHS):
        raise ValueError(
            "H3 AV generated-audio continuity requires an exact shared "
            "video/audio boundary: 39, 90, 141, 192, or 243 context "
            "frames. Set generated continuity off (or audio context to 0) "
            "to test a video-only AV window from 5 frames.")
    return {
        "version": CHAIN_POLICY_VERSION,
        "audio_policy": resolved_audio,
        "transition_policy": resolved_transition,
        "audio_context_length": resolved_audio_context,
    }


def chain_policy(
    incoming_transition: str,
    final_audio: str,
    source_reference: str,
    generated_continuity: str,
    lock_source_audio: bool = False,
    lip_sync_options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the compact normal-user policy from its semantic choices."""
    preset = str(incoming_transition)
    if preset not in PRIMARY_TRANSITION_PRESETS:
        raise ValueError(
            "H3 Chain Policy incoming transition must be one of %s." %
            (PRIMARY_TRANSITION_PRESETS,))
    resolved_transition = transition_policy(preset)
    return compose_chain_policy(
        audio_policy(
            final_audio, source_reference, generated_continuity,
            "locked" if bool(lock_source_audio) else "off",
            lip_sync_options),
        resolved_transition,
        # Normal authoring keeps picture and generated-audio carry on the
        # same tested boundary. The Advanced Policy keeps that semantic
        # pairing for experimental recipes; independent numeric values remain
        # available only through the 0.4 Legacy Policy Adapter.
        audio_context_length=resolved_transition["context_length"])


def paired_audio_policy(value: str | bool) -> str:
    """Normalize a reference-local paired-audio choice or legacy boolean."""
    if isinstance(value, bool):
        return "embedded" if value else "off"
    normalized = str(value).strip().lower()
    if normalized not in PAIRED_AUDIO_POLICIES:
        raise ValueError("Unknown H3 paired-audio policy %r." % value)
    return normalized


def transition_preset(name: str) -> dict[str, Any]:
    """Return an isolated resolved transition preset."""
    try:
        preset = TRANSITION_PRESETS[str(name)]
    except KeyError as exc:
        raise ValueError("Unknown H3 transition preset %r." % name) from exc
    return {"version": TRANSITION_POLICY_VERSION, "preset": str(name), **preset}


def transition_policy(
    preset: str,
    *,
    expert_override: bool = False,
    continuation_mode: str | None = None,
    context_length: int | None = None,
) -> dict[str, Any]:
    """Resolve a semantic preset and optional explicit low-level override."""
    resolved = transition_preset(preset)
    expert = bool(expert_override)
    if expert:
        mode = migrate_continuation_mode(continuation_mode)
        if mode not in CONTINUATION_POLICIES:
            raise ValueError(
                "Unknown H3 continuation implementation %r." %
                continuation_mode)
        try:
            context = int(context_length)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "H3 transition context must be 0 or one of %s." %
                (TRANSITION_CONTEXT_LENGTHS,)) from exc
        if context not in TRANSITION_CONTEXT_LENGTHS:
            raise ValueError(
                "H3 transition context must be 0 or one of %s." %
                (TRANSITION_CONTEXT_LENGTHS,))
        if mode == "latent_guide" and 0 < context < 5:
            raise ValueError(
                "H3 Latent Guide requires at least 5 context frames.")
        if (mode in (
                "masked_av", "feathered_av", "audio_feathered_av"
        ) and context > 0
                and context not in VIDEO_ONLY_AV_TRANSITION_CONTEXT_LENGTHS):
            raise ValueError(
                "H3 video-only AV transition experiments require at least "
                "5 context frames (or 0 to disable continuation). Exact "
                "39/90/141/192/243-frame alignment is still required when "
                "generated predecessor audio is carried.")
        if (mode == "tapered_av" and context not in (
                0, int(DETAIL_AV_RECIPE["context_frames"]))):
            raise ValueError(
                "H3 Detail AV currently requires exactly 39 context frames "
                "(or 0 to disable continuation).")
        if (mode in ("drift_control_av", "color_stable_drift_av")
                and context not in (
                0, int(DRIFT_CONTROL_AV_RECIPE["context_frames"]))):
            raise ValueError(
                "H3 Drift-Control AV and Color-Stable Drift AV currently "
                "require exactly 39 context frames (or 0 to disable "
                "continuation).")
        resolved["continuation_mode"] = mode
        resolved["context_length"] = context
    resolved["expert_override"] = expert
    return resolved


def source_timeline_shape() -> dict[str, Any]:
    """Document the required serializable shape without creating media state."""
    return {
        "version": SOURCE_TIMELINE_VERSION,
        "video": {
            "path": "absolute host path or empty",
            "stream_index": 0,
            "native_fps": "positive rational",
            "start_pts_seconds": "number",
            "duration_seconds": "positive number",
            "frame_count_24fps": "non-negative integer",
        },
        "audio": {
            "kind": "embedded | external_path | deferred_tensor | none",
            "path": "absolute host path or empty",
            "stream_index": "non-negative integer or null",
            "sample_rate": "positive integer or null",
            "duration_seconds": "non-negative number",
        },
        "origin": {
            "skip_native_frames": "non-negative integer",
            "skip_seconds": "non-negative number",
        },
        "fingerprints": {
            "video": "sha256 or empty",
            "audio": "sha256 or empty",
            "timeline": "sha256",
        },
        "recovery": {
            "original_available": "boolean",
            "archived_path": "absolute host path or empty",
            "run_owned_audio_path": "absolute host path or empty",
        },
    }


def scene_dependency_shape() -> dict[str, Any]:
    """Document the versioned, four-scope checkpoint dependency record."""
    return {
        "version": SCENE_DEPENDENCY_VERSION,
        "scene": "one-based integer",
        "scopes": {scope: "JSON-safe field map" for scope in DEPENDENCY_SCOPES},
        "fingerprints": {scope: "sha256" for scope in DEPENDENCY_SCOPES},
        "generation_hash": "sha256 of scopes except assembly_only",
    }
