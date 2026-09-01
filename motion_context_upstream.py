"""Transparent adapter for seitanism's public H3 Motion Context node.

The production Chain keeps its stable sockets and state contract.  At runtime
this module discovers the public ``MiniMaxH3MotionContext`` registration from
ComfyUI and delegates the compatible Guide path to it.  Loop-only extensions
that the upstream node does not yet expose continue through the internal
engine supplied by the caller.

No upstream module is imported by package path: ComfyUI custom-node folder
names are user-controlled.  The live node registry is the authoritative and
rename-safe discovery surface.
"""

from __future__ import annotations

import importlib
import logging
from typing import Any


_LOG = logging.getLogger("minimax_h3_context_loop.motion_context_upstream")

UPSTREAM_NODE_ID = "MiniMaxH3MotionContext"
_BASE_INPUTS = frozenset({
    "conditioning",
    "vae",
    "latent",
    "context_frames",
    "context_length",
    "encode_mode",
    "anchor_mode",
    "crop",
    "audio_context_length",
    "audio_mode",
    "target_start",
    "context_latent",
    "audio_vae",
    "context_audio",
})
_BACKEND_MESSAGES: set[str] = set()


def _log_once(key: str, level: int, message: str, *args: Any) -> None:
    if key in _BACKEND_MESSAGES:
        return
    _BACKEND_MESSAGES.add(key)
    _LOG.log(level, message, *args)


def _native_guides_available() -> bool:
    try:
        from .patch_layout import native_guides_available

        return bool(native_guides_available())
    except Exception:
        return False


def _payload_audio_merge_error(exc: BaseException) -> bool:
    message = str(exc)
    return bool(
        "h3_motion_context:" in message
        and "native_keyframe_ref_audio_merge" in message
    )


def _enable_internal_payload_merge() -> tuple[bool, str]:
    """Enable the guarded keyframe/ref merge for a partially native core.

    Some ComfyUI builds expose native arbitrary Guides but still drop Guide
    audio when Ref2VA audio is present. The public upstream provider correctly
    refuses that combination. Our internal engine can retain it when the
    marker-gated payload compatibility wrapper owns the merge.
    """
    try:
        from .patch_payload import (
            apply_patch,
            claim_patch_ownership,
            is_applied,
        )

        if not apply_patch() or not is_applied():
            return False, "payload compatibility patch could not be enabled"
        claimed, detail = claim_patch_ownership(require_keyframe_audio=True)
        if not claimed or not is_applied():
            return False, str(detail)
        return True, str(detail)
    except Exception as exc:
        return False, str(exc)


def _conditioning_has_refs(conditioning: Any) -> bool:
    for item in conditioning or ():
        if not isinstance(item, (list, tuple)) or len(item) < 2:
            continue
        metadata = item[1]
        if (isinstance(metadata, dict)
                and bool(metadata.get("minimax_refs"))):
            return True
    return False


def _ensure_delegated_payload_merge(
        conditioning: Any, *, effective_context: int,
        audio_context_length: int, audio_mode: str,
        context_latent: Any, context_audio: Any) -> str | None:
    """Verify payload capabilities before calling any upstream version."""
    has_refs = _conditioning_has_refs(conditioning)
    has_context_audio = context_latent is not None or context_audio is not None
    requested_audio_frames = (
        int(audio_context_length) or int(effective_context))
    appends_audio_ref = bool(
        has_context_audio and requested_audio_frames > 0
        and str(audio_mode) != "timeline")
    require_video = bool(
        int(effective_context) > 0 and (has_refs or appends_audio_ref))
    require_audio = bool(
        has_refs and has_context_audio and requested_audio_frames > 0
        and str(audio_mode) == "timeline")
    if not require_video and not require_audio:
        return None

    # Older upstream providers predate their own capability guard and can
    # otherwise return conditioning that fails only inside the sampler. Use
    # Chain's live behavioral probe regardless of provider version.
    from .nodes import _ensure_native_payload_merge

    return _ensure_native_payload_merge(
        require_video=require_video, require_audio=require_audio)


def _registered_upstream(fallback_node_type: Any):
    """Return (class, accepted input names), or (None, empty set).

    A schema check prevents an unrelated pack that reused the historical node
    id from being called as the current native MultiRef implementation.
    """
    try:
        comfy_nodes = importlib.import_module("nodes")
        candidate = getattr(comfy_nodes, "NODE_CLASS_MAPPINGS", {}).get(
            UPSTREAM_NODE_ID)
    except Exception:
        return None, frozenset()
    if candidate is None or candidate is fallback_node_type:
        return None, frozenset()
    try:
        schema = candidate.INPUT_TYPES()
        required = schema.get("required", {})
        optional = schema.get("optional", {})
        accepted = frozenset(required) | frozenset(optional)
    except Exception as exc:
        _log_once(
            "invalid-schema:%r" % (candidate,), logging.WARNING,
            "H3 Chain ignored the registered %s provider because its input "
            "schema could not be read: %s", UPSTREAM_NODE_ID, exc)
        return None, frozenset()
    missing = sorted(_BASE_INPUTS - accepted)
    if missing:
        _log_once(
            "incompatible-schema:%r" % (candidate,), logging.WARNING,
            "H3 Chain ignored the registered %s provider because it lacks "
            "the expected input(s): %s", UPSTREAM_NODE_ID,
            ", ".join(missing))
        return None, frozenset()
    return candidate, accepted


def _fallback_reason(
        accepted: frozenset[str], *, context_length: int,
        effective_context: int, anchor_mode: str, audio_context_length: int,
        audio_mode: str, context_latent: Any, context_audio: Any,
        video_context_latent: Any, future_end_anchor: bool) -> str | None:
    if not _native_guides_available():
        return "ComfyUI does not expose native H3 guides"
    if int(context_length) <= 0 or int(effective_context) <= 0:
        return "audio-only continuity"
    if anchor_mode != "head":
        return "legacy before-anchor placement"
    if (video_context_latent is not None
            and "video_context_latent" not in accepted):
        return "direct video-latent Guide reuse"
    if bool(future_end_anchor) and "future_end_anchor" not in accepted:
        return "future end anchor"
    has_audio = context_latent is not None or context_audio is not None
    effective_audio = int(audio_context_length) or int(effective_context)
    if (has_audio and audio_mode == "timeline"
            and effective_audio > int(effective_context)):
        return "audio context longer than visual context"
    for name, value in (
            ("context_latent", context_latent),
            ("context_audio", context_audio)):
        if value is not None and name not in accepted:
            return "upstream provider lacks %s" % name
    return None


def _frame_count(latent: Any) -> int:
    from .nodes import _pixel_frames, _video_from_latent

    video = _video_from_latent(latent)
    return int(_pixel_frames(int(video.shape[2])))


def _prepare_conditioning(
        conditioning: Any, latent: Any, head_end: int) -> tuple[Any, int]:
    """Apply the Loop keyframe arbitration that upstream intentionally lacks."""
    if not isinstance(conditioning, (list, tuple)) or len(conditioning) != 1:
        raise TypeError(
            "H3 Chain upstream Motion Context requires one conditioning "
            "entry; use the internal compatibility path for composite lists.")
    embedding, extra = conditioning[0]
    if not isinstance(extra, dict):
        raise TypeError("H3 conditioning metadata must be a dictionary.")

    metadata = extra.copy()
    prior = list(metadata.get("minimax_keyframes") or [])
    if not prior:
        return [[embedding, metadata]], 0

    frame_count = _frame_count(latent)
    prior_frame_count = metadata.get("minimax_frame_count")
    if (prior_frame_count is not None
            and int(prior_frame_count) != frame_count):
        raise ValueError(
            "h3_motion_context: the conditioning carries keyframes resolved "
            "for a %d frame clip, but the latent is %d frames. Wire the "
            "conditioning and latent from the same stock H3 node."
            % (int(prior_frame_count), frame_count))

    kept = []
    dropped = []
    for keyframe in prior:
        position = float(keyframe.get(
            "motion_context_index",
            keyframe.get("resolved_frame_index", 0)))
        if position < int(head_end):
            dropped.append(position)
            continue
        kept.append(dict(keyframe))
    metadata["minimax_keyframes"] = kept
    if dropped:
        _LOG.warning(
            "H3 Chain upstream adapter dropped %d existing keyframe "
            "anchor(s) at frame(s) %s because the carried head owns frames "
            "0..%d; anchors outside the overlap remain intact.",
            len(dropped), sorted(set(dropped)), int(head_end) - 1)
    return [[embedding, metadata]], len(kept)


def _decorate_output(
        output: Any, prior_count: int, trim: int, *,
        visual_cond_noise_aug: float, audio_mode: str,
        audio_context_length: int, context_latent: Any) -> Any:
    """Restore Loop-private guide markers and exact latent-audio placement."""
    from .nodes import FRAME_RESCALE, _audio_tail_from_latent

    decorated = []
    for embedding, extra in output:
        metadata = extra.copy()
        keyframes = [dict(value) for value in
                     (metadata.get("minimax_keyframes") or [])]
        added = keyframes[int(prior_count):]
        has_visual = False
        for keyframe in added:
            if keyframe.get("latent") is not None:
                keyframe["h3_chain_context_visual"] = True
                has_visual = True

        if (context_latent is not None and audio_mode == "timeline"
                and any(value.get("audio_latent") is not None
                        for value in added)):
            a_frames = int(audio_context_length) or int(trim)
            _tail, ref_audio_t, overhang = _audio_tail_from_latent(
                context_latent, a_frames)
            audio_start = (
                float(trim)
                + float(overhang) / float(FRAME_RESCALE)
                - float(ref_audio_t) / float(FRAME_RESCALE))
            for keyframe in added:
                audio_latent = keyframe.get("audio_latent")
                if audio_latent is None:
                    continue
                current_start = float(keyframe.get(
                    "resolved_frame_index", 0))
                if abs(current_start - audio_start) <= 1e-9:
                    break
                if keyframe.get("latent") is not None:
                    # Current upstream combines matching visual/audio starts.
                    # A fractional H3 grid correction must move only audio.
                    del keyframe["audio_latent"]
                    keyframes.append({
                        "resolved_frame_index": audio_start,
                        "audio_latent": audio_latent,
                    })
                else:
                    keyframe["resolved_frame_index"] = audio_start
                break

        if has_visual:
            metadata["minimax_visual_cond_noise_aug"] = float(
                visual_cond_noise_aug)
        metadata["minimax_keyframes"] = keyframes
        decorated.append([embedding, metadata])
    return decorated


def apply_motion_context(
        fallback_node_type: Any, *, conditioning: Any, vae: Any, latent: Any,
        context_frames: Any, context_length: int, encode_mode: str,
        anchor_mode: str, crop: str, audio_context_length: int = 0,
        audio_mode: str = "timeline", context_latent: Any = None,
        audio_vae: Any = None, context_audio: Any = None,
        video_context_latent: Any = None,
        visual_cond_noise_aug: float = 0.999,
        future_end_anchor: bool = False):
    """Use the registered upstream provider when it covers this Chain mode."""
    upstream_type, accepted = _registered_upstream(fallback_node_type)
    available = int(getattr(context_frames, "shape", (0,))[0])
    effective_context = min(int(context_length), available)

    reason = None
    if upstream_type is None:
        reason = "upstream Motion Context is not installed"
    else:
        reason = _fallback_reason(
            accepted,
            context_length=int(context_length),
            effective_context=effective_context,
            anchor_mode=str(anchor_mode),
            audio_context_length=int(audio_context_length),
            audio_mode=str(audio_mode),
            context_latent=context_latent,
            context_audio=context_audio,
            video_context_latent=video_context_latent,
            future_end_anchor=bool(future_end_anchor),
        )

    if reason is not None:
        _log_once(
            "fallback:" + reason, logging.INFO,
            "H3 Chain Motion Context uses its internal compatibility engine "
            "for %s.", reason)
        return fallback_node_type().apply(
            conditioning=conditioning,
            vae=vae,
            latent=latent,
            context_frames=context_frames,
            context_length=context_length,
            encode_mode=encode_mode,
            anchor_mode=anchor_mode,
            crop=crop,
            audio_context_length=audio_context_length,
            audio_mode=audio_mode,
            context_latent=context_latent,
            audio_vae=audio_vae,
            context_audio=context_audio,
            video_context_latent=video_context_latent,
            visual_cond_noise_aug=visual_cond_noise_aug,
            future_end_anchor=future_end_anchor,
        )

    try:
        prepared, prior_count = _prepare_conditioning(
            conditioning, latent, effective_context)
    except TypeError as exc:
        _log_once(
            "fallback:conditioning-shape", logging.INFO,
            "H3 Chain Motion Context uses its internal compatibility engine "
            "because the upstream provider cannot preserve this conditioning "
            "shape: %s", exc)
        return fallback_node_type().apply(
            conditioning=conditioning,
            vae=vae,
            latent=latent,
            context_frames=context_frames,
            context_length=context_length,
            encode_mode=encode_mode,
            anchor_mode=anchor_mode,
            crop=crop,
            audio_context_length=audio_context_length,
            audio_mode=audio_mode,
            context_latent=context_latent,
            audio_vae=audio_vae,
            context_audio=context_audio,
            video_context_latent=video_context_latent,
            visual_cond_noise_aug=visual_cond_noise_aug,
            future_end_anchor=future_end_anchor,
        )

    from .nodes import _validate_visual_cond_noise_aug

    visual_cond_noise_aug = _validate_visual_cond_noise_aug(
        visual_cond_noise_aug)

    _ensure_delegated_payload_merge(
        prepared,
        effective_context=effective_context,
        audio_context_length=int(audio_context_length),
        audio_mode=str(audio_mode),
        context_latent=context_latent,
        context_audio=context_audio,
    )

    kwargs = {
        "conditioning": prepared,
        "vae": vae,
        "latent": latent,
        "context_frames": context_frames,
        "context_length": context_length,
        "encode_mode": encode_mode,
        "anchor_mode": anchor_mode,
        "crop": crop,
        "audio_context_length": audio_context_length,
        "audio_mode": audio_mode,
    }
    for name, value in (
            ("context_latent", context_latent),
            ("audio_vae", audio_vae),
            ("context_audio", context_audio),
            ("video_context_latent", video_context_latent),
            ("visual_cond_noise_aug", visual_cond_noise_aug),
            ("future_end_anchor", future_end_anchor)):
        if name in accepted:
            kwargs[name] = value
    if "target_start" in accepted:
        kwargs["target_start"] = 0

    function_name = str(getattr(upstream_type, "FUNCTION", "apply"))
    upstream = upstream_type()
    try:
        result = getattr(upstream, function_name)(**kwargs)
    except RuntimeError as exc:
        if not _payload_audio_merge_error(exc):
            raise
        repaired, detail = _enable_internal_payload_merge()
        if not repaired:
            raise RuntimeError(
                "%s H3 Chain could not enable its guarded internal audio "
                "merge fallback: %s" % (exc, detail)
            ) from exc
        _log_once(
            "fallback:native-keyframe-ref-audio-merge",
            logging.WARNING,
            "H3 Chain Motion Context uses its internal compatibility engine "
            "because the live ComfyUI payload drops Guide audio when Ref2VA "
            "audio is also active (%s).",
            detail,
        )
        return fallback_node_type().apply(
            conditioning=conditioning,
            vae=vae,
            latent=latent,
            context_frames=context_frames,
            context_length=context_length,
            encode_mode=encode_mode,
            anchor_mode=anchor_mode,
            crop=crop,
            audio_context_length=audio_context_length,
            audio_mode=audio_mode,
            context_latent=context_latent,
            audio_vae=audio_vae,
            context_audio=context_audio,
            video_context_latent=video_context_latent,
            visual_cond_noise_aug=visual_cond_noise_aug,
            future_end_anchor=future_end_anchor,
        )
    output, trim = result[0], int(result[1])
    output = _decorate_output(
        output, prior_count, trim,
        visual_cond_noise_aug=float(visual_cond_noise_aug),
        audio_mode=str(audio_mode),
        audio_context_length=int(audio_context_length),
        context_latent=context_latent,
    )
    _log_once(
        "upstream:%s.%s" % (upstream_type.__module__, upstream_type.__name__),
        logging.INFO,
        "H3 Chain Motion Context delegates compatible Guide scenes to the "
        "registered upstream provider %s.%s; Chain sockets and workflows "
        "remain unchanged.", upstream_type.__module__, upstream_type.__name__)
    return output, trim


__all__ = ["UPSTREAM_NODE_ID", "apply_motion_context"]
