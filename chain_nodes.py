"""Disk-backed recursive clip chains specialized for MiniMax H3.

The visible graph contains one H3 sampling body.  Chain Start and Chain End
recursively clone that body with ComfyUI's GraphBuilder, carrying only the
previous clip's context tail and compact AV latent into the next iteration.
Each iteration is persisted before recursion, so a long chain can resume from
the first unfinished clip instead of starting over.

The recursive graph traversal is adapted from Ethanfel's SxCP loop nodes in
ComfyUI-Prompt-Builder, using the same ComfyUI expansion pattern with a single,
typed MiniMax chain state rather than arbitrary carry sockets.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
import os
import re
import secrets
import shutil
import subprocess
import time
import uuid
import wave
from fractions import Fraction
from typing import Any

import folder_paths

try:
    import av
except ImportError:  # ComfyUI normally ships PyAV.
    av = None

try:
    import torch
except ImportError:  # ComfyUI always ships torch; keeps local imports clear.
    torch = None

try:
    from PIL import Image, PngImagePlugin
except ImportError:  # Pillow ships with ComfyUI.
    Image = PngImagePlugin = None

try:
    from safetensors.torch import load_file as _st_load, save_file as _st_save
except ImportError:
    _st_load = _st_save = None

try:
    from comfy_execution.graph_utils import GraphBuilder, ExecutionBlocker, is_link
except ImportError:
    GraphBuilder = None
    ExecutionBlocker = None

    def is_link(value):
        return isinstance(value, list) and len(value) == 2

try:
    from aiohttp import web
    from server import PromptServer
except ImportError:
    web = None
    PromptServer = None

from .nodes import (
    MiniMaxH3MotionContext,
    _prepare_native_guide_conditioning,
    _resize,
    _streams_from_latent,
)


_LOG = logging.getLogger("minimax_h3_context_loop.chain")

FPS = 24
PLAN_VERSION = 2
MAX_SHOTS = 128
MAX_SEED = 0xFFFFFFFFFFFFFFFF
MAX_H3_FRAMES = 3592  # largest 17k+5 value accepted by H3's 3600-frame socket
H3_CONTEXT_LENGTHS = (1, 5, 22, 39)
AUDIO_MODES = ("source_track", "generated_audio", "source_plus_timeline")

PLAN_TYPE = "H3_CHAIN_PLAN"
STATE_TYPE = "H3_CHAIN_STATE"
FLOW_TYPE = "H3_CHAIN_FLOW"
SEGMENT_TYPE = "H3_CHAIN_SEGMENT"
MANIFEST_TYPE = "H3_CHAIN_MANIFEST"
EXTERNAL_CONTEXT_TYPE = "H3_CHAIN_EXTERNAL_CONTEXT"

_PENDING_REVIEWS: dict[str, dict[str, Any]] = {}


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"))


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _safe_name(value: str, fallback: str = "chain") -> str:
    text = re.sub(r"[^A-Za-z0-9._-]+", "_", str(value or "").strip())
    text = text.strip("._-")
    return (text or fallback)[:96]


def _prompt_text(value: Any, label: str) -> str:
    """Normalize a prompt string or a human-editable JSON array of lines."""
    if isinstance(value, list):
        if not all(isinstance(line, str) for line in value):
            raise ValueError("%s line arrays may contain only strings." % label)
        return "\n".join(value).strip()
    return str(value or "").strip()


def _h3_frame_length(seconds: float) -> int:
    """Round a duration up to H3's valid 17k+5 frame grid."""
    seconds = float(seconds)
    if not math.isfinite(seconds) or seconds <= 0:
        raise ValueError("H3 shot duration must be a finite positive number.")
    # Subtract a tiny tolerance so an exactly frame-aligned decimal does not
    # jump a frame because of binary floating-point representation.
    requested = max(5, int(math.ceil(seconds * FPS - 1e-9)))
    length = requested + (5 - requested % 17) % 17
    if length > MAX_H3_FRAMES:
        raise ValueError(
            "H3 shot duration %.6fs rounds to %d frames; the largest valid "
            "17k+5 length is %d frames (%.6fs)." %
            (seconds, length, MAX_H3_FRAMES, MAX_H3_FRAMES / float(FPS)))
    return length


def _validate_h3_length(length: Any, label: str) -> int:
    length = int(length)
    if length < 5 or length > MAX_H3_FRAMES or length % 17 != 5:
        raise ValueError(
            "%s must be an H3-valid frame length between 5 and %d "
            "with length %% 17 == 5; got %d." %
            (label, MAX_H3_FRAMES, length))
    return length


def _parse_scene_range(value: Any, total: int,
                       fallback_start: int) -> tuple[int, int]:
    """Parse one inclusive, contiguous scene selection.

    Disjoint selections are deliberately rejected: every H3 scene depends on
    its immediate predecessor, so skipping a scene inside a render selection
    would either break continuity or silently reuse an invalid checkpoint.
    """
    total = int(total)
    fallback_start = int(fallback_start)
    text = str(value or "").strip()
    if not text:
        start, end = fallback_start, total
    else:
        compact = re.sub(r"\s+", "", text)
        if "," in compact:
            raise ValueError(
                "scene_range supports one contiguous inclusive range only, "
                "such as '3' or '3:8'. Comma selections are not safe for a "
                "seamless chain.")
        match = re.fullmatch(r"(\d+)(?::(\d+))?", compact)
        if match is None:
            raise ValueError(
                "scene_range must be blank, one scene like '3', or one "
                "inclusive range like '3:8'.")
        start = int(match.group(1))
        end = int(match.group(2) or start)
    if start < 1 or start > total:
        raise ValueError("scene_range start must be between 1 and %d." % total)
    if end < start:
        raise ValueError("scene_range end must be greater than or equal to start.")
    if end > total:
        raise ValueError("scene_range end must be between %d and %d." %
                         (start, total))
    return start, end


def _derived_seed(base_seed: int, index: int, shot_id: str) -> int:
    payload = "%d:%d:%s" % (int(base_seed), int(index), shot_id)
    return int.from_bytes(hashlib.sha256(payload.encode("utf-8")).digest()[:8],
                          "big")


def _history_contract(plan: dict[str, Any], through_index: int) -> dict[str, Any]:
    shots = []
    for shot in plan["shots"][:int(through_index)]:
        shots.append({
            "id": shot["id"],
            "prompt_hash": shot["prompt_hash"],
            "seed": shot["seed"],
            "steps": shot["steps"],
            "raw_frames": shot["raw_frames"],
            "delivered_frames": shot["delivered_frames"],
            "generation_start_frame": shot["generation_start_frame"],
        })
    return {
        "version": PLAN_VERSION,
        "compatibility": plan["compatibility"],
        "shots": shots,
    }


def _history_hash(plan: dict[str, Any], through_index: int) -> str:
    return _fingerprint(_history_contract(plan, through_index))


def _audio_fingerprint(audio: dict[str, Any]) -> str:
    if torch is None:
        raise RuntimeError("Source-audio checkpoint validation requires torch.")
    waveform = audio["waveform"].detach().cpu().contiguous()
    digest = hashlib.sha256()
    digest.update(str(int(audio["sample_rate"])).encode("ascii"))
    digest.update(str(tuple(int(part) for part in waveform.shape)).encode("ascii"))
    digest.update(str(waveform.dtype).encode("ascii"))
    digest.update(memoryview(waveform.numpy()).cast("B"))
    return digest.hexdigest()


def _tensor_fingerprint(value: Any) -> str:
    """Hash a tensor without materializing one giant Python bytes object."""
    if torch is None or not torch.is_tensor(value):
        raise ValueError("H3 external video fingerprinting requires a tensor.")
    digest = hashlib.sha256()
    digest.update(str(tuple(int(part) for part in value.shape)).encode("ascii"))
    digest.update(str(value.dtype).encode("ascii"))
    chunks = value.detach().split(8, dim=0) if value.ndim else (value.detach(),)
    for chunk in chunks:
        cpu = chunk.to(device="cpu").contiguous()
        digest.update(memoryview(cpu.numpy()).cast("B"))
    return digest.hexdigest()


def _validate_audio(audio: dict[str, Any], label: str,
                    expected_frames: int | None = None) -> tuple[Any, int]:
    if torch is None:
        raise RuntimeError("H3 chain audio validation requires torch.")
    if not isinstance(audio, dict) or "waveform" not in audio:
        raise ValueError("%s must be a ComfyUI AUDIO value." % label)
    waveform = audio["waveform"]
    if not torch.is_tensor(waveform) or waveform.ndim not in (1, 2, 3):
        raise ValueError(
            "%s waveform must be a 1D, 2D, or 3D tensor; got %r." %
            (label, getattr(waveform, "shape", None)))
    sample_rate = int(audio.get("sample_rate", 0))
    if sample_rate <= 0:
        raise ValueError("%s sample rate must be positive." % label)
    samples = int(waveform.shape[-1])
    if samples < 1:
        raise ValueError("%s waveform is empty." % label)
    if expected_frames is not None:
        expected = int(round(int(expected_frames) / float(FPS) * sample_rate))
        if samples != expected:
            raise ValueError(
                "%s contains %d samples at %d Hz; expected exactly %d samples "
                "for %d delivered frames at %d fps. Wire decoded audio through "
                "MiniMax H3 Contex Loop Trim with match_tail enabled." %
                (label, samples, sample_rate, expected, int(expected_frames), FPS))
    return waveform, sample_rate


def _audio_is_silent(waveform: Any) -> bool:
    if torch is None:
        return False
    return float(waveform.detach().abs().max().item()) <= 1e-6


def _pad_audio_to_samples(audio: dict[str, Any], samples: int,
                          label: str) -> dict[str, Any]:
    waveform, sample_rate = _validate_audio(audio, label)
    target = int(samples)
    current = int(waveform.shape[-1])
    if current >= target:
        return {"waveform": waveform[..., :target], "sample_rate": sample_rate}
    shape = list(waveform.shape)
    shape[-1] = target - current
    padding = torch.zeros(shape, dtype=waveform.dtype, device=waveform.device)
    return {
        "waveform": torch.cat((waveform, padding), dim=-1),
        "sample_rate": sample_rate,
    }


def _audio_waveform_3d(audio: dict[str, Any], label: str) -> tuple[Any, int]:
    """Return the first Comfy audio batch as [1, channels, samples]."""
    waveform, sample_rate = _validate_audio(audio, label)
    if waveform.ndim == 1:
        waveform = waveform.unsqueeze(0).unsqueeze(0)
    elif waveform.ndim == 2:
        waveform = waveform.unsqueeze(0)
    else:
        waveform = waveform[:1]
    channels = int(waveform.shape[1])
    if channels not in (1, 2):
        raise ValueError("%s must be mono or stereo; got %d channels." %
                         (label, channels))
    return waveform, sample_rate


def _resample_audio_exact(audio: dict[str, Any], sample_rate: int,
                          samples: int, channels: int,
                          label: str) -> dict[str, Any]:
    """Resample/channel-match audio to one exact frame-locked tensor."""
    waveform, source_rate = _audio_waveform_3d(audio, label)
    sample_rate = int(sample_rate)
    samples = int(samples)
    channels = int(channels)
    if sample_rate <= 0 or samples < 1 or channels not in (1, 2):
        raise ValueError("Invalid target audio format for %s." % label)
    waveform = waveform.to(dtype=torch.float32)
    if int(waveform.shape[1]) != channels:
        if int(waveform.shape[1]) == 1 and channels == 2:
            waveform = waveform.expand(-1, 2, -1)
        elif int(waveform.shape[1]) == 2 and channels == 1:
            waveform = waveform.mean(dim=1, keepdim=True)
    current = int(waveform.shape[-1])
    rate_adjusted = int(round(current * sample_rate / float(source_rate)))
    if source_rate != sample_rate and rate_adjusted > 0:
        waveform = torch.nn.functional.interpolate(
            waveform.reshape(-1, 1, current), size=rate_adjusted,
            mode="linear", align_corners=False).reshape(
                1, channels, rate_adjusted)
    current = int(waveform.shape[-1])
    if current < samples:
        padding = torch.zeros(
            (1, channels, samples - current), dtype=waveform.dtype,
            device=waveform.device)
        waveform = torch.cat((waveform, padding), dim=-1)
    else:
        waveform = waveform[..., :samples]
    return {
        "waveform": waveform.detach().cpu().contiguous(),
        "sample_rate": sample_rate,
    }


def _resample_audio_tail_exact(audio: dict[str, Any], sample_rate: int,
                               samples: int, channels: int,
                               label: str) -> dict[str, Any]:
    """Resample and end-align an exact tail, left-padding when necessary."""
    waveform, source_rate = _audio_waveform_3d(audio, label)
    sample_rate = int(sample_rate)
    samples = int(samples)
    channels = int(channels)
    if sample_rate <= 0 or samples < 1 or channels not in (1, 2):
        raise ValueError("Invalid target audio tail format for %s." % label)
    waveform = waveform.to(dtype=torch.float32)
    if int(waveform.shape[1]) != channels:
        if int(waveform.shape[1]) == 1 and channels == 2:
            waveform = waveform.expand(-1, 2, -1)
        elif int(waveform.shape[1]) == 2 and channels == 1:
            waveform = waveform.mean(dim=1, keepdim=True)
    current = int(waveform.shape[-1])
    rate_adjusted = int(round(current * sample_rate / float(source_rate)))
    if source_rate != sample_rate and rate_adjusted > 0:
        waveform = torch.nn.functional.interpolate(
            waveform.reshape(-1, 1, current), size=rate_adjusted,
            mode="linear", align_corners=False).reshape(
                1, channels, rate_adjusted)
    current = int(waveform.shape[-1])
    if current < samples:
        padding = torch.zeros(
            (1, channels, samples - current), dtype=waveform.dtype,
            device=waveform.device)
        waveform = torch.cat((padding, waveform), dim=-1)
    else:
        waveform = waveform[..., current - samples:]
    return {
        "waveform": waveform.detach().cpu().contiguous(),
        "sample_rate": sample_rate,
    }


def _validate_source_audio_hash(compatibility: dict[str, Any],
                                source_audio: dict[str, Any] | None,
                                usage: str) -> None:
    if source_audio is None:
        raise ValueError("%s requires source_audio." % usage)
    _validate_audio(source_audio, "%s source audio" % usage)
    expected = str(compatibility.get("source_audio_hash") or "")
    if not expected or expected == "none":
        raise ValueError("%s has no source-audio fingerprint to validate." % usage)
    actual = _audio_fingerprint(source_audio)
    if actual != expected:
        raise ValueError(
            "%s received a different source waveform than H3 Chain Loop Start. "
            "Wire the same AUDIO value to Start, Current Shot, and Assemble." % usage)


def _external_context_contract(external_context: dict[str, Any]) -> dict[str, Any]:
    frames = external_context.get("context_frames")
    audio = external_context.get("context_audio")
    return {
        "version": int(external_context.get("version", 0)),
        "base_plan_hash": str(external_context.get("base_plan_hash") or ""),
        "context_frames": int(getattr(frames, "shape", (0,))[0]),
        "context_frames_sha256": _tensor_fingerprint(frames),
        "context_audio_sha256": (
            _audio_fingerprint(audio) if isinstance(audio, dict) else "none"),
    }


def _plan_with_external_context(
    plan: dict[str, Any],
    external_context: dict[str, Any] | None,
) -> dict[str, Any]:
    """Make scene 1 a real continuation from an imported video tail."""
    if external_context is None:
        return plan
    if not isinstance(external_context, dict):
        raise ValueError(
            "H3 Chain Loop Start external_context must come from MiniMax H3 "
            "Existing Video Context.")
    expected_base = str(plan.get("base_plan_hash") or plan["plan_hash"])
    if str(external_context.get("base_plan_hash") or "") != expected_base:
        raise ValueError(
            "H3 existing-video context was prepared for a different Chain Plan. "
            "Reconnect the current Plan to the adapter and queue again.")
    contract = _external_context_contract(external_context)
    context_hash = _fingerprint(contract)
    if context_hash != str(external_context.get("context_hash") or ""):
        raise ValueError(
            "H3 existing-video context changed after it was prepared; refusing "
            "to use an unverifiable video tail.")

    span = int(contract["context_frames"])
    configured = int(plan["compatibility"]["context_length"])
    if span != configured:
        raise ValueError(
            "H3 existing-video context contains %d frames; this plan requires "
            "exactly %d." % (span, configured))

    prepared = dict(plan)
    prepared["base_plan_hash"] = expected_base
    prepared["shots"] = [dict(shot) for shot in plan["shots"]]
    prepared["compatibility"] = dict(plan["compatibility"])
    prepared["compatibility"].update({
        "external_context_hash": context_hash,
        "external_context_frames": span,
    })
    prelude = external_context.get("prelude")
    prepared["prelude"] = (_json_document(prelude)
                           if isinstance(prelude, dict) else None)

    stitched_frames = 0
    anchor_mode = prepared["compatibility"]["anchor_mode"]
    for offset, shot in enumerate(prepared["shots"]):
        raw_frames = int(shot["raw_frames"])
        if offset == 0:
            if anchor_mode == "head":
                if raw_frames <= span:
                    raise ValueError(
                        "H3 scene 1 has %d raw frames, not enough for the "
                        "%d-frame imported-video overlap." % (raw_frames, span))
                generation_start = -span
                delivered_frames = raw_frames - span
            else:
                generation_start = 0
                delivered_frames = raw_frames
            shot["external_context_frames"] = span
        elif anchor_mode == "head":
            generation_start = stitched_frames - configured
            delivered_frames = raw_frames - configured
        else:
            generation_start = stitched_frames
            delivered_frames = raw_frames
        shot["generation_start_frame"] = generation_start
        shot["delivered_frames"] = delivered_frames
        # Scene 1's negative pre-roll comes from the imported video/audio, not
        # from the extension soundtrack. Current Shot builds that composite
        # explicitly and begins the new source track at frame zero.
        shot["audio_start_seconds"] = max(0, generation_start) / float(FPS)
        shot["audio_duration_seconds"] = raw_frames / float(FPS)
        stitched_frames += delivered_frames

    for shot in prepared["shots"][:-1]:
        if int(shot["delivered_frames"]) < configured:
            raise ValueError(
                "Shot %d (%s) delivers only %d frames, but the next clip "
                "requires %d context frames." %
                (shot["index"], shot["id"], shot["delivered_frames"],
                 configured))

    prepared["total_delivered_frames"] = stitched_frames
    prepared["plan_hash"] = _fingerprint({
        "base_plan_hash": expected_base,
        "external_context_hash": context_hash,
    })
    cfg = prepared["compatibility"]
    prepared["summary"] = (
        "%d clips; %d delivered frames (%.3fs) at %dx%d; context=%d; "
        "audio=%s; imported video; run=%s" %
        (len(prepared["shots"]), stitched_frames,
         stitched_frames / float(FPS), cfg["width"], cfg["height"],
         configured, cfg["audio_mode"], prepared["run_name"]))
    return prepared


def _plan_with_source_audio(plan: dict[str, Any],
                            source_audio: dict[str, Any] | None) -> dict[str, Any]:
    mode = plan["compatibility"]["audio_mode"]
    if mode in ("source_track", "source_plus_timeline"):
        if source_audio is None:
            raise ValueError("H3 chain audio mode %s requires source_audio on "
                             "Loop Start." % mode)
        waveform, sample_rate = _validate_audio(
            source_audio, "H3 Chain Loop Start source audio")
        required_samples = int(round(
            int(plan["total_delivered_frames"]) / float(FPS) * sample_rate))
        silent_padding = False
        if int(waveform.shape[-1]) < required_samples:
            if _audio_is_silent(waveform):
                silent_padding = True
            else:
                raise ValueError(
                    "H3 Chain Loop Start source audio is too short: it contains %d "
                    "samples at %d Hz, but this plan requires at least %d samples "
                    "for %d delivered frames. Only silent placeholder audio is "
                    "automatically padded." %
                    (int(waveform.shape[-1]), sample_rate, required_samples,
                     int(plan["total_delivered_frames"])))
        source_hash = _audio_fingerprint(source_audio)
    else:
        source_hash = "none"
        silent_padding = False
    prepared = dict(plan)
    prepared["base_plan_hash"] = str(
        plan.get("base_plan_hash") or plan["plan_hash"])
    prepared["compatibility"] = dict(plan["compatibility"])
    prepared["compatibility"]["source_audio_hash"] = source_hash
    prepared["compatibility"]["source_audio_silent_padding"] = silent_padding
    if plan["compatibility"].get("external_context_hash"):
        prepared["plan_hash"] = _fingerprint({
            "prepared_plan_hash": plan["plan_hash"],
            "source_audio_hash": source_hash,
        })
    else:
        # Preserve the exact pre-v0.3.6 hash contract for ordinary chains so
        # every existing checkpoint remains resumable.
        prepared["plan_hash"] = _fingerprint({
            "base_plan_hash": plan["plan_hash"],
            "source_audio_hash": source_hash,
        })
    return prepared


def _plan_with_review_revision(plan: dict[str, Any], index: int,
                               scene_prompt: str, seed: int) -> dict[str, Any]:
    """Revise the current scene while preserving the accepted history contract."""
    index = int(index)
    if index < 1 or index > len(plan["shots"]):
        raise ValueError("H3 review revision index is outside the plan.")
    scene_prompt = str(scene_prompt or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    prefix = str(plan.get("prompt_prefix") or "").strip()
    if not scene_prompt and not prefix:
        raise ValueError(
            "H3 review retry requires a scene prompt or shared prompt.")
    seed = int(seed)
    if seed < 0 or seed > MAX_SEED:
        raise ValueError("H3 review retry seed is outside the uint64 range.")

    revised = dict(plan)
    revised["shots"] = [dict(shot) for shot in plan["shots"]]
    shot = revised["shots"][index - 1]
    full_prompt = "\n\n".join(part for part in (prefix, scene_prompt) if part)
    shot["scene_prompt"] = scene_prompt
    shot["prompt"] = full_prompt
    shot["prompt_hash"] = hashlib.sha256(
        full_prompt.encode("utf-8")).hexdigest()
    shot["seed"] = seed

    overrides = dict(revised.get("review_overrides") or {})
    overrides[str(index)] = {
        "scene_prompt": scene_prompt,
        "prompt_hash": shot["prompt_hash"],
        "seed": seed,
    }
    revised["review_overrides"] = overrides
    base_plan_hash = str(revised.get("base_plan_hash") or revised["plan_hash"])
    source_hash = str(
        revised.get("compatibility", {}).get("source_audio_hash") or "none")
    external_hash = str(
        revised.get("compatibility", {}).get("external_context_hash") or "none")
    revision_contract = {
        "base_plan_hash": base_plan_hash,
        "source_audio_hash": source_hash,
        "review_overrides": overrides,
    }
    if external_hash != "none":
        revision_contract["external_context_hash"] = external_hash
    revised["plan_hash"] = _fingerprint(revision_contract)
    return revised


def _normalize_plan(
    plan_json: str,
    run_name: str,
    width: int,
    height: int,
    context_length: int,
    encode_mode: str,
    anchor_mode: str,
    crop: str,
    audio_mode: str,
    audio_context_length: int,
    default_duration_seconds: float,
    default_steps: int,
    base_seed: int,
    segment_crf: int,
    generation_fingerprint: str = "",
) -> dict[str, Any]:
    try:
        raw = json.loads(str(plan_json or ""))
    except json.JSONDecodeError as exc:
        raise ValueError("H3 Chain Plan JSON is invalid: %s" % exc) from exc
    if isinstance(raw, list):
        raw = {"shots": raw}
    if not isinstance(raw, dict):
        raise ValueError("H3 Chain Plan must be a JSON object or a list of shots.")

    raw_shots = raw.get("shots")
    if not isinstance(raw_shots, list) or not raw_shots:
        raise ValueError("H3 Chain Plan requires a non-empty 'shots' list.")
    if len(raw_shots) > MAX_SHOTS:
        raise ValueError("H3 Chain Plan supports at most %d shots." % MAX_SHOTS)

    width, height = int(width), int(height)
    if width < 32 or height < 32 or width % 32 or height % 32:
        raise ValueError("H3 chain width and height must be positive multiples of 32.")
    context_length = int(context_length)
    if context_length not in H3_CONTEXT_LENGTHS:
        raise ValueError("H3 context length must be one of %s." % (H3_CONTEXT_LENGTHS,))
    if encode_mode not in ("video", "frames"):
        raise ValueError("Unknown H3 context encode mode %r." % encode_mode)
    if anchor_mode not in ("head", "before"):
        raise ValueError("Unknown H3 context anchor mode %r." % anchor_mode)
    if crop not in ("disabled", "center"):
        raise ValueError("Unknown H3 context crop mode %r." % crop)
    if audio_mode not in AUDIO_MODES:
        raise ValueError("Unknown H3 chain audio mode %r." % audio_mode)
    default_steps = max(1, min(10000, int(default_steps)))
    base_seed = max(0, min(MAX_SEED, int(base_seed)))
    segment_crf = max(0, min(51, int(segment_crf)))

    defaults = raw.get("defaults") if isinstance(raw.get("defaults"), dict) else {}
    default_duration = float(defaults.get(
        "duration_seconds", raw.get("duration_seconds", default_duration_seconds)))
    default_steps = int(defaults.get("steps", raw.get("steps", default_steps)))
    if not math.isfinite(default_duration) or default_duration <= 0:
        raise ValueError("Default shot duration must be a finite positive number.")
    if default_steps < 1:
        raise ValueError("Default sampler steps must be at least 1.")

    prompt_prefix = _prompt_text(
        raw.get("prompt_prefix", raw.get("global_prompt", "")),
        "H3 Chain prompt_prefix",
    )
    seen_ids: set[str] = set()
    shots: list[dict[str, Any]] = []
    stitched_frames = 0
    for offset, item in enumerate(raw_shots):
        index = offset + 1
        if isinstance(item, str):
            item = {"prompt": item}
        if not isinstance(item, dict):
            raise ValueError("Shot %d must be an object or prompt string." % index)

        shot_id = _safe_name(item.get("id", "clip_%04d" % index),
                             "clip_%04d" % index)
        if shot_id in seen_ids:
            raise ValueError("Duplicate H3 shot id %r." % shot_id)
        seen_ids.add(shot_id)

        prompt = _prompt_text(item.get("prompt", ""),
                              "Shot %d (%s) prompt" % (index, shot_id))
        if not prompt and not prompt_prefix:
            raise ValueError(
                "Shot %d (%s) requires a scene prompt or shared prompt." %
                (index, shot_id))
        scene_prompt = prompt
        prompt = "\n\n".join(
            part for part in (prompt_prefix, scene_prompt) if part)

        explicit_length = item.get("length", item.get("frames"))
        if explicit_length is None:
            duration = float(item.get("duration_seconds", default_duration))
            if not math.isfinite(duration) or duration <= 0:
                raise ValueError(
                    "Shot %d duration must be a finite positive number." % index)
            raw_frames = _h3_frame_length(duration)
        else:
            raw_frames = _validate_h3_length(explicit_length,
                                                   "Shot %d length" % index)

        if index == 1:
            generation_start_frame = 0
            delivered_frames = raw_frames
        else:
            if raw_frames <= context_length:
                raise ValueError(
                    "Shot %d has %d raw frames, not enough for a %d-frame "
                    "continuation overlap." % (index, raw_frames, context_length))
            if anchor_mode == "head":
                generation_start_frame = stitched_frames - context_length
                delivered_frames = raw_frames - context_length
            else:
                # `before` places context at negative coordinates, so no
                # repeated head is delivered or trimmed from the new clip.
                generation_start_frame = stitched_frames
                delivered_frames = raw_frames

        steps = int(item.get("steps", default_steps))
        if steps < 1 or steps > 10000:
            raise ValueError("Shot %d steps must be between 1 and 10000." % index)
        seed_value = item.get("seed")
        seed = (_derived_seed(base_seed, index, shot_id)
                if seed_value is None else int(seed_value))
        if seed < 0 or seed > MAX_SEED:
            raise ValueError("Shot %d seed is outside the uint64 range." % index)

        shot = {
            "index": index,
            "id": shot_id,
            # Kept separately so the review gate can edit only this scene
            # without duplicating the shared prompt prefix.
            "scene_prompt": scene_prompt,
            "prompt": prompt,
            "prompt_hash": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
            "seed": seed,
            "steps": steps,
            "raw_frames": raw_frames,
            "delivered_frames": delivered_frames,
            "generation_start_frame": generation_start_frame,
            "audio_start_seconds": generation_start_frame / float(FPS),
            "audio_duration_seconds": raw_frames / float(FPS),
        }
        shots.append(shot)
        stitched_frames += delivered_frames

    for shot in shots[:-1]:
        if shot["delivered_frames"] < context_length:
            raise ValueError(
                "Shot %d (%s) delivers only %d frames, but the next clip "
                "requires %d context frames. Increase its length or reduce "
                "context_length." %
                (shot["index"], shot["id"], shot["delivered_frames"],
                 context_length))

    compatibility = {
        "fps": FPS,
        "width": width,
        "height": height,
        "context_length": context_length,
        "encode_mode": encode_mode,
        "anchor_mode": anchor_mode,
        "crop": crop,
        "audio_mode": audio_mode,
        "audio_context_length": max(0, int(audio_context_length)),
        "segment_crf": segment_crf,
        # Model, VAE, references, CFG, and scheduler live outside this node's
        # inputs. This caller-supplied tag lets a workflow make those external
        # generation dependencies part of the resume contract.
        "generation_fingerprint": str(generation_fingerprint or "").strip(),
    }
    plan = {
        "version": PLAN_VERSION,
        "run_name": _safe_name(run_name, "h3_chain"),
        "prompt_prefix": prompt_prefix,
        "shots": shots,
        "compatibility": compatibility,
        "segment_crf": segment_crf,
        "total_delivered_frames": stitched_frames,
    }
    plan["plan_hash"] = _fingerprint({
        "compatibility": compatibility,
        "shots": [{k: v for k, v in shot.items()
                   if k not in ("prompt", "scene_prompt")}
                  for shot in shots],
    })
    plan["summary"] = (
        "%d clips; %d delivered frames (%.3fs) at %dx%d; context=%d; "
        "audio=%s; run=%s" %
        (len(shots), stitched_frames, stitched_frames / float(FPS), width,
         height, context_length, audio_mode, plan["run_name"]))
    return plan


def _output_root() -> str:
    return os.path.abspath(folder_paths.get_output_directory())


def _run_dir(plan: dict[str, Any]) -> str:
    root = _output_root()
    path = os.path.abspath(os.path.join(root, "h3_chains", plan["run_name"]))
    if os.path.commonpath([root, path]) != root:
        raise ValueError("H3 chain run path escapes the ComfyUI output directory.")
    return path


def _relative_output_path(path: str) -> str:
    return os.path.relpath(os.path.abspath(path), _output_root())


def _absolute_output_path(path: str) -> str:
    if os.path.isabs(path):
        resolved = os.path.abspath(path)
    else:
        resolved = os.path.abspath(os.path.join(_output_root(), path))
    root = _output_root()
    if os.path.commonpath([root, resolved]) != root:
        raise ValueError("H3 chain artifact path escapes the output directory.")
    return resolved


def _video_output_item(path: str) -> dict[str, str]:
    relative = _relative_output_path(path)
    return {
        "filename": os.path.basename(relative),
        "subfolder": os.path.dirname(relative),
        "type": "output",
    }


def _artifact_paths(plan: dict[str, Any], index: int) -> dict[str, str]:
    run_dir = _run_dir(plan)
    return {
        "run_dir": run_dir,
        "segment": os.path.join(run_dir, "segments", "clip_%04d.mp4" % index),
        "checkpoint": os.path.join(run_dir, "checkpoints",
                                   "clip_%04d.safetensors" % index),
        "metadata": os.path.join(run_dir, "checkpoints", "clip_%04d.json" % index),
    }


def _run_archive_paths(plan: dict[str, Any]) -> dict[str, str]:
    run_dir = _run_dir(plan)
    return {
        "plan": os.path.join(run_dir, "plan.json"),
        "workflow": os.path.join(run_dir, "workflow.json"),
        "api_prompt": os.path.join(run_dir, "api_prompt.json"),
    }


def _versioned_path(path: str, transaction: str) -> str:
    stem, extension = os.path.splitext(path)
    return "%s.%s%s" % (stem, transaction, extension)


def _file_sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while True:
            block = handle.read(1024 * 1024)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def _safe_unlink(path: str) -> None:
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass


def _atomic_text(path: str, value: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temporary = "%s.%s.tmp" % (path, uuid.uuid4().hex)
    try:
        # Write exact UTF-8 bytes so Windows does not silently translate LF to
        # CRLF. Prompt hashes are defined over the normalized UTF-8 text.
        with open(temporary, "wb") as handle:
            handle.write(str(value).encode("utf-8"))
        os.replace(temporary, path)
    finally:
        _safe_unlink(temporary)


def _cleanup_previous_artifacts(plan: dict[str, Any], index: int,
                                previous_metadata: Any,
                                keep: set[str]) -> None:
    if not isinstance(previous_metadata, dict):
        return
    previous = previous_metadata.get("segment")
    if not isinstance(previous, dict):
        return
    canonical = _artifact_paths(plan, index)
    allowed = {
        "segment": os.path.dirname(canonical["segment"]),
        "checkpoint": os.path.dirname(canonical["checkpoint"]),
        "prompt_file": os.path.dirname(canonical["segment"]),
    }
    prefix = "clip_%04d" % index
    for key in ("segment", "checkpoint", "prompt_file"):
        value = previous.get(key)
        if not isinstance(value, str):
            continue
        try:
            path = _absolute_output_path(value)
        except (ValueError, OSError):
            continue
        if (path in keep or os.path.dirname(path) != allowed[key] or
                not os.path.basename(path).startswith(prefix)):
            continue
        try:
            _safe_unlink(path)
        except OSError as exc:
            _LOG.warning("H3 Chain could not clean old %s artifact %s: %s",
                         key, path, exc)


def _atomic_json(path: str, value: Any) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temporary = "%s.%s.tmp" % (path, uuid.uuid4().hex)
    try:
        with open(temporary, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(temporary, path)
    finally:
        _safe_unlink(temporary)


def _read_json(path: str) -> Any:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _effective_editor_plan(plan: dict[str, Any]) -> dict[str, Any]:
    """Return an exact, editable plan source for this execution revision."""
    return {
        "prompt_prefix": str(plan.get("prompt_prefix") or ""),
        "shots": [{
            "id": shot["id"],
            "prompt": shot.get("scene_prompt", ""),
            "length": int(shot["raw_frames"]),
            "steps": int(shot["steps"]),
            # A decimal string remains exact when the workflow passes through
            # JavaScript, including uint64 values above Number.MAX_SAFE_INTEGER.
            "seed": str(int(shot["seed"])),
        } for shot in plan["shots"]],
    }


def _json_document(value: Any) -> Any:
    """Clone one JSON document, accepting ComfyUI's occasional string form."""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return None
    if not isinstance(value, (dict, list)):
        return None
    try:
        return json.loads(json.dumps(value, ensure_ascii=False))
    except (TypeError, ValueError):
        return None


def _matching_plan_node_ids(api_prompt: Any,
                            plan: dict[str, Any]) -> tuple[Any, set[str]]:
    document = _json_document(api_prompt)
    if not isinstance(document, dict):
        return None, set()
    effective_json = json.dumps(
        _effective_editor_plan(plan), ensure_ascii=False, indent=2)
    candidates: list[tuple[str, dict[str, Any]]] = []
    exact: list[tuple[str, dict[str, Any]]] = []
    for node_id, node in document.items():
        if not isinstance(node, dict) or node.get("class_type") != "MiniMaxH3ChainPlan":
            continue
        inputs = node.get("inputs")
        if not isinstance(inputs, dict):
            continue
        candidate = (str(node_id), inputs)
        candidates.append(candidate)
        run_name = inputs.get("run_name")
        if (isinstance(run_name, str) and
                _safe_name(run_name, "h3_chain") == plan["run_name"]):
            exact.append(candidate)
    selected = exact or (candidates if len(candidates) == 1 else [])
    for _node_id, inputs in selected:
        inputs["plan_json"] = effective_json
    return document, {node_id for node_id, _inputs in selected}


def _patched_workflow(workflow: Any, plan: dict[str, Any],
                      plan_node_ids: set[str]) -> Any:
    document = _json_document(workflow)
    if not isinstance(document, dict):
        return None
    nodes = document.get("nodes")
    if not isinstance(nodes, list):
        return document
    effective_json = json.dumps(
        _effective_editor_plan(plan), ensure_ascii=False, indent=2)
    candidates = [node for node in nodes if isinstance(node, dict) and
                  node.get("type") == "MiniMaxH3ChainPlan"]
    selected = []
    for node in candidates:
        widgets = node.get("widgets_values")
        node_id = str(node.get("id"))
        run_name = (widgets[1] if isinstance(widgets, list) and len(widgets) > 1
                    else None)
        if (node_id in plan_node_ids or
                (isinstance(run_name, str) and
                 _safe_name(run_name, "h3_chain") == plan["run_name"])):
            selected.append(node)
    if not selected and len(candidates) == 1:
        selected = candidates
    for node in selected:
        widgets = node.get("widgets_values")
        if isinstance(widgets, list) and widgets:
            widgets[0] = effective_json
    return document


def _write_run_archives(plan: dict[str, Any], api_prompt: Any = None,
                        extra_pnginfo: Any = None) -> dict[str, str]:
    """Persist recovery documents and return output-relative paths.

    `plan.json` is always written and represents the exact effective revision,
    including review-gate prompt/seed changes. The frontend workflow and API
    prompt are written when ComfyUI supplies their standard hidden metadata.
    Existing workflow archives are retained if a non-Comfy caller later saves
    another segment without hidden metadata.
    """
    paths = _run_archive_paths(plan)
    archived_plan = dict(plan)
    archived_plan["format"] = "h3_chain_plan_archive_v1"
    archived_plan["editor_plan"] = _effective_editor_plan(plan)
    _atomic_json(paths["plan"], archived_plan)

    patched_prompt, plan_node_ids = _matching_plan_node_ids(api_prompt, plan)
    if patched_prompt is not None:
        _atomic_json(paths["api_prompt"], patched_prompt)

    workflow = None
    if isinstance(extra_pnginfo, dict):
        workflow = extra_pnginfo.get("workflow")
    patched_workflow = _patched_workflow(workflow, plan, plan_node_ids)
    if patched_workflow is not None:
        _atomic_json(paths["workflow"], patched_workflow)

    return _available_run_archives(plan)


def _available_run_archives(plan: dict[str, Any]) -> dict[str, str]:
    paths = _run_archive_paths(plan)
    return {key: _relative_output_path(path) for key, path in paths.items()
            if os.path.isfile(path)}


def _archive_media_metadata(archives: Any) -> dict[str, str]:
    """Load ComfyUI-compatible video tags from persisted run archives."""
    if not isinstance(archives, dict):
        return {}
    metadata = {}
    for archive_key, tag in (("api_prompt", "prompt"),
                             ("workflow", "workflow"),
                             ("plan", "h3_plan")):
        value = archives.get(archive_key)
        if not isinstance(value, str):
            continue
        try:
            document = _read_json(_absolute_output_path(value))
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            _LOG.warning("H3 Chain could not embed %s metadata: %s",
                         archive_key, exc)
            continue
        metadata[tag] = json.dumps(document, ensure_ascii=False,
                                   separators=(",", ":"))
    return metadata


def _prompt_fields(plan: dict[str, Any], index: int) -> dict[str, Any]:
    shot = plan["shots"][int(index) - 1]
    return {
        "prompt_prefix": str(plan.get("prompt_prefix") or ""),
        "scene_prompt": str(shot.get("scene_prompt") or ""),
        "prompt": str(shot.get("prompt") or ""),
        "prompt_hash": str(shot["prompt_hash"]),
    }


def _tensor_cpu_clone(value: Any) -> Any:
    if torch is not None and torch.is_tensor(value):
        return value.detach().cpu().contiguous().clone()
    return value


def _compact_latent(latent: dict[str, Any]) -> dict[str, Any]:
    parts = _streams_from_latent(latent)
    if len(parts) < 2:
        raise ValueError("H3 Chain requires a sampled MiniMax AV latent.")
    return {"samples": [_tensor_cpu_clone(parts[0]),
                        _tensor_cpu_clone(parts[1])]}


def _public_segment(value: dict[str, Any]) -> dict[str, Any]:
    return {key: value[key] for key in (
        "index", "id", "segment", "checkpoint", "metadata",
        "prompt_file", "raw_frames", "delivered_frames", "history_hash",
        "prompt_prefix", "scene_prompt", "prompt", "prompt_hash", "archives",
        "seed", "steps", "sample_rate", "segment_sha256",
        "checkpoint_sha256", "prompt_file_sha256") if key in value}


def _verify_segment_artifacts(segment: dict[str, Any], index: int) -> None:
    if int(segment.get("index", -1)) != int(index):
        raise ValueError(
            "H3 chain metadata slot %d points to segment index %r." %
            (index, segment.get("index")))
    for key, hash_key in (("segment", "segment_sha256"),
                          ("checkpoint", "checkpoint_sha256")):
        value = segment.get(key)
        expected_hash = str(segment.get(hash_key) or "")
        if not isinstance(value, str) or not expected_hash:
            raise ValueError(
                "H3 chain clip %d metadata has no verified %s artifact." %
                (index, key))
        artifact = _absolute_output_path(value)
        if not os.path.isfile(artifact):
            raise FileNotFoundError(
                "H3 chain clip %d %s is missing: %s" %
                (index, key, artifact))
        actual_hash = _file_sha256(artifact)
        if actual_hash != expected_hash:
            raise ValueError(
                "H3 chain clip %d %s failed its SHA-256 integrity check." %
                (index, key))
    prompt_file = segment.get("prompt_file")
    if isinstance(prompt_file, str):
        prompt_path = _absolute_output_path(prompt_file)
        if not os.path.isfile(prompt_path):
            raise FileNotFoundError(
                "H3 chain clip %d prompt sidecar is missing: %s" %
                (index, prompt_path))
        artifact_hash = str(segment.get("prompt_file_sha256") or "")
        if artifact_hash:
            actual_hash = _file_sha256(prompt_path)
        else:
            # Records saved before prompt_file_sha256 used prompt_hash for this
            # check. Windows text-mode writes converted LF to CRLF, so compare
            # their normalized text while retaining strict raw-byte checks for
            # all newly saved sidecars.
            with open(prompt_path, "r", encoding="utf-8", newline=None) as handle:
                prompt_text = handle.read()
            prompt_text = prompt_text.replace("\r\n", "\n").replace("\r", "\n")
            actual_hash = hashlib.sha256(prompt_text.encode("utf-8")).hexdigest()
            artifact_hash = str(segment.get("prompt_hash") or "")
        if not artifact_hash or actual_hash != artifact_hash:
            raise ValueError(
                "H3 chain clip %d prompt sidecar failed its SHA-256 integrity "
                "check." % index)


def _load_resume_state(plan: dict[str, Any], start_clip: int) -> dict[str, Any]:
    if _st_load is None:
        raise RuntimeError("safetensors is required to resume H3 chains.")
    previous_index = start_clip - 1
    segments = []
    previous_meta = None
    for index in range(1, previous_index + 1):
        paths = _artifact_paths(plan, index)
        if not os.path.isfile(paths["metadata"]):
            raise FileNotFoundError(
                "Cannot resume clip %d: metadata for predecessor clip %d is "
                "missing: %s" % (start_clip, index, paths["metadata"]))
        metadata = _read_json(paths["metadata"])
        expected = _history_hash(plan, index)
        if metadata.get("history_hash") != expected:
            raise ValueError(
                "Cannot resume clip %d: clip %d was generated from different "
                "settings, prompts, seeds, or durations." % (start_clip, index))
        segment = metadata.get("segment")
        if not isinstance(segment, dict):
            raise ValueError("Checkpoint metadata for clip %d has no segment." % index)
        if segment.get("history_hash") != expected:
            raise ValueError(
                "Checkpoint segment record for clip %d has a mismatched history."
                % index)
        _verify_segment_artifacts(segment, index)
        restored = _public_segment(segment)
        for key, value in _prompt_fields(plan, index).items():
            restored.setdefault(key, value)
        segments.append(restored)
        previous_meta = metadata

    if previous_meta is None:
        raise RuntimeError("Internal resume error: predecessor metadata unavailable.")
    checkpoint = _absolute_output_path(previous_meta["segment"]["checkpoint"])
    tensors = _st_load(checkpoint)
    required = {"context_frames", "video", "audio"}
    missing = sorted(required - set(tensors))
    if missing:
        raise ValueError("H3 chain checkpoint is missing tensors: %s" % missing)
    expected_context = min(
        int(plan["compatibility"]["context_length"]),
        int(plan["shots"][previous_index - 1]["delivered_frames"]))
    if int(tensors["context_frames"].shape[0]) != expected_context:
        raise ValueError(
            "H3 chain predecessor checkpoint contains %d context frames; "
            "expected %d." %
            (int(tensors["context_frames"].shape[0]), expected_context))
    return {
        "plan": plan,
        "index": start_clip,
        "previous_frames": tensors["context_frames"],
        "previous_latent": {"samples": [tensors["video"], tensors["audio"]]},
        "segments": segments,
        "resumed_from": previous_index,
    }


def _initial_state(plan: dict[str, Any], start_clip: int,
                   end_clip: int | None = None,
                   external_context: dict[str, Any] | None = None) -> dict[str, Any]:
    total = len(plan["shots"])
    start_clip = int(start_clip)
    if start_clip < 1 or start_clip > total:
        raise ValueError("start_clip must be between 1 and %d." % total)
    end_clip = total if end_clip is None else int(end_clip)
    if end_clip < start_clip or end_clip > total:
        raise ValueError(
            "end_clip must be between start_clip %d and %d." %
            (start_clip, total))
    if start_clip > 1:
        state = _load_resume_state(plan, start_clip)
    else:
        state = {
            "plan": plan,
            "index": 1,
            "previous_frames": (
                external_context.get("context_frames")
                if isinstance(external_context, dict) else None),
            "previous_latent": None,
            "previous_audio": (
                external_context.get("context_audio")
                if isinstance(external_context, dict) else None),
            "external_context": bool(external_context is not None),
            "segments": [],
            "resumed_from": 0,
        }
    state["range_start"] = start_clip
    state["end_clip"] = end_clip
    return state


def _slice_audio(audio: dict[str, Any], start_seconds: float,
                 duration_seconds: float,
                 pad_silence: bool = False) -> dict[str, Any]:
    waveform, sample_rate = _validate_audio(audio, "H3 source audio")
    total = int(waveform.shape[-1])
    start = max(0, int(round(float(start_seconds) * sample_rate)))
    end = max(start + 1, int(round(
        (float(start_seconds) + float(duration_seconds)) * sample_rate)))
    wanted = end - start
    if pad_silence and end > total:
        padded = _pad_audio_to_samples(
            audio, end, "H3 silent placeholder audio")
        return {
            "waveform": padded["waveform"][..., start:end],
            "sample_rate": sample_rate,
        }
    if start >= total:
        raise ValueError(
            "H3 source audio ends at %.3fs, before this clip's %.3fs start." %
            (total / float(sample_rate), start_seconds))
    if end > total:
        raise ValueError(
            "H3 source audio is too short for this chain: clip window "
            "%.3f..%.3fs requires %d samples, but the waveform ends at %.3fs. "
            "Short audio would truncate the final video." %
            (start_seconds, start_seconds + duration_seconds, wanted,
             total / float(sample_rate)))
    return {"waveform": waveform[..., start:end], "sample_rate": sample_rate}


def _slice_audio_after_external_context(
    source_audio: dict[str, Any],
    external_audio: dict[str, Any] | None,
    raw_frames: int,
    lead_frames: int,
    pad_silence: bool,
) -> dict[str, Any]:
    """Build scene 1 audio as imported tail + extension soundtrack start."""
    waveform, sample_rate = _audio_waveform_3d(
        source_audio, "H3 source audio")
    channels = int(waveform.shape[1])
    total_samples = int(round(int(raw_frames) / float(FPS) * sample_rate))
    lead_samples = int(round(int(lead_frames) / float(FPS) * sample_rate))
    lead_samples = min(lead_samples, total_samples)
    extension_samples = total_samples - lead_samples
    if int(waveform.shape[-1]) < extension_samples:
        if pad_silence and _audio_is_silent(waveform):
            source = _pad_audio_to_samples(
                {"waveform": waveform, "sample_rate": sample_rate},
                extension_samples, "H3 silent extension soundtrack")
            extension = source["waveform"]
        else:
            raise ValueError(
                "H3 extension soundtrack has %d samples; scene 1 requires %d "
                "after its imported-video audio lead." %
                (int(waveform.shape[-1]), extension_samples))
    else:
        extension = waveform[..., :extension_samples]
    if external_audio is None:
        lead = torch.zeros(
            (1, channels, lead_samples), dtype=extension.dtype,
            device=extension.device)
    else:
        lead = _resample_audio_tail_exact(
            external_audio, sample_rate, lead_samples, channels,
            "H3 existing-video context audio")["waveform"].to(
                device=extension.device, dtype=extension.dtype)
    return {
        "waveform": torch.cat((lead, extension), dim=-1),
        "sample_rate": sample_rate,
    }


def _write_segment_video(images: Any, path: str, fps: int, crf: int,
                         metadata: dict[str, Any] | None = None) -> None:
    if av is None or torch is None:
        raise RuntimeError("H3 segment saving requires PyAV and torch.")
    if len(images.shape) != 4 or int(images.shape[0]) < 1:
        raise ValueError("H3 segment images must be [frames,height,width,channels].")
    height, width = int(images.shape[1]), int(images.shape[2])
    if width % 2 or height % 2:
        raise ValueError("H.264 segment dimensions must be even.")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temporary = path[:-4] + ".tmp.mp4"
    if os.path.exists(temporary):
        os.unlink(temporary)
    container = None
    try:
        container = av.open(
            temporary, mode="w",
            options={"movflags": "use_metadata_tags+faststart"})
        if metadata:
            for key, value in metadata.items():
                if value is not None:
                    container.metadata[str(key)] = str(value)
        stream = container.add_stream("libx264", rate=Fraction(int(fps), 1))
        stream.width = width
        stream.height = height
        stream.pix_fmt = "yuv420p"
        stream.options = {"crf": str(int(crf)), "preset": "medium"}
        for image in images:
            array = (torch.clamp(image[..., :3] * 255.0, 0, 255)
                     .to(device="cpu", dtype=torch.uint8).numpy())
            frame = av.VideoFrame.from_ndarray(array, format="rgb24")
            for packet in stream.encode(frame):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)
        container.close()
        container = None
        os.replace(temporary, path)
    except Exception:
        if container is not None:
            container.close()
        if os.path.exists(temporary):
            os.unlink(temporary)
        raise


def _write_wav(audio: dict[str, Any], path: str) -> None:
    if torch is None:
        raise RuntimeError("H3 chain audio assembly requires torch.")
    waveform = audio["waveform"]
    if len(waveform.shape) == 3:
        waveform = waveform[0]
    elif len(waveform.shape) == 1:
        waveform = waveform.unsqueeze(0)
    if len(waveform.shape) != 2:
        raise ValueError("H3 chain audio must be [batch,channels,samples].")
    pcm = (torch.clamp(waveform, -1.0, 1.0).movedim(0, 1) * 32767.0)
    pcm = pcm.round().to(device="cpu", dtype=torch.int16).contiguous().numpy()
    with wave.open(path, "wb") as handle:
        handle.setnchannels(int(pcm.shape[1]))
        handle.setsampwidth(2)
        handle.setframerate(int(audio["sample_rate"]))
        handle.writeframes(pcm.tobytes())


def _external_video_frame_indices(frame_count: int, source_fps: float) -> Any:
    frame_count = int(frame_count)
    source_fps = float(source_fps)
    if frame_count < 1:
        raise ValueError("H3 existing-video source contains no frames.")
    if not math.isfinite(source_fps) or source_fps <= 0:
        raise ValueError("H3 existing-video source_fps must be positive.")
    target_count = max(1, int(round(frame_count * FPS / source_fps)))
    # CFR sample at each 24 fps target timestamp. floor() avoids looking ahead
    # across the join; the final selected frame remains the latest available
    # source frame at that instant.
    return (torch.arange(target_count, dtype=torch.float64) *
            (source_fps / float(FPS))).floor().to(dtype=torch.long).clamp(
                min=0, max=frame_count - 1)


def _resolve_video_inputs(source_video: Any, source_frames: Any,
                          source_audio: Any, source_fps: float,
                          label: str) -> tuple[Any, Any, float, str]:
    """Resolve native VIDEO or decoded IMAGE/AUDIO without hiding provenance."""
    if source_video is not None and source_frames is not None:
        raise ValueError(
            "%s received both source_video and source_frames. Connect one "
            "video input route only." % label)
    input_route = "decoded IMAGE/AUDIO"
    if source_video is not None:
        get_components = getattr(source_video, "get_components", None)
        if not callable(get_components):
            raise ValueError(
                "%s source_video must be a native ComfyUI VIDEO value with "
                "get_components()." % label)
        try:
            components = get_components()
        except Exception as exc:
            raise ValueError(
                "%s source_video could not be decoded: %s" %
                (label, exc)) from exc
        source_frames = getattr(components, "images", None)
        try:
            source_fps = float(getattr(components, "frame_rate"))
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "%s source_video has no valid frame rate." % label) from exc
        if source_audio is None:
            source_audio = getattr(components, "audio", None)
        input_route = "native VIDEO"
    elif source_frames is None:
        raise ValueError(
            "%s requires source_video or source_frames." % label)
    return source_frames, source_audio, float(source_fps), input_route


class MiniMaxH3ReferenceVideoPrepare:
    """Prepare a synchronized source performance for one-pass H3 Ref2VA."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "length": ("INT", {
                    "default": 209, "min": 5, "max": MAX_H3_FRAMES,
                    "step": 17,
                    "tooltip": "Exact H3 output/reference length. It must "
                               "satisfy length % 17 == 5. The source video "
                               "and copied soundtrack must both cover it."}),
                "source_fps": ("FLOAT", {
                    "default": 24.0, "min": 0.001, "max": 1000.0,
                    "step": 0.001,
                    "tooltip": "Actual frame rate represented by "
                               "source_frames. It is ignored for native "
                               "VIDEO, which carries its own exact FPS."}),
            },
            "optional": {
                "source_video": ("VIDEO", {
                    "tooltip": "Native ComfyUI VIDEO from core Load Video or "
                               "another VIDEO loader. Its frames, embedded "
                               "audio, and exact FPS are decoded directly."}),
                "source_frames": ("IMAGE", {
                    "tooltip": "Decoded IMAGE batch from VHS or another "
                               "loader. Connect this instead of source_video "
                               "and provide its actual source_fps."}),
                "source_audio": ("AUDIO", {
                    "tooltip": "Soundtrack paired with source_frames, or an "
                               "override for native VIDEO audio. The node "
                               "copies its opening samples exactly; it never "
                               "time-stretches or silently pads them."}),
            },
        }

    RETURN_TYPES = ("IMAGE", "AUDIO", "INT", "STRING")
    RETURN_NAMES = ("ref_video", "source_audio", "length", "status")
    OUTPUT_TOOLTIPS = (
        "The source performance sampled at H3's 24 fps for Ref2VA.",
        "The original source waveform cut exactly to the selected duration.",
        "Validated H3 frame length for the stock Ref2VA length input.",
        "Input route, source timing, selected frame count, and copied audio.",
    )
    FUNCTION = "prepare"
    CATEGORY = "conditioning/minimax/contex_loop"
    DESCRIPTION = ("Normalize a native VIDEO or IMAGE/AUDIO source to an "
                   "exact one-pass H3 Ref2VA performance reference while "
                   "copying, not regenerating, its synchronized soundtrack.")

    def prepare(self, length=209, source_fps=24.0, source_video=None,
                source_frames=None, source_audio=None):
        length = _validate_h3_length(length, "H3 reference-video length")
        source_frames, source_audio, source_fps, input_route = (
            _resolve_video_inputs(
                source_video, source_frames, source_audio, source_fps,
                "H3 reference-video prep"))
        if torch is None or not torch.is_tensor(source_frames):
            raise ValueError(
                "H3 reference-video source_frames must be an IMAGE tensor.")
        if source_frames.ndim != 4 or int(source_frames.shape[-1]) < 3:
            raise ValueError(
                "H3 reference-video source_frames must be "
                "[frames,height,width,channels]; got %r." %
                (getattr(source_frames, "shape", None),))

        indices = _external_video_frame_indices(
            int(source_frames.shape[0]), source_fps)
        available = int(indices.numel())
        if available < length:
            raise ValueError(
                "H3 reference-video source becomes %d frames at 24 fps, but "
                "length is %d. Choose a shorter H3-valid length or supply a "
                "longer video." % (available, length))
        selected = source_frames.index_select(
            0, indices[:length].to(device=source_frames.device))

        if source_audio is None:
            raise ValueError(
                "H3 reference-video prep requires source audio so the final "
                "soundtrack can be copied unchanged.")
        waveform, sample_rate = _audio_waveform_3d(
            source_audio, "H3 reference-video source audio")
        required_samples = int(round(length / float(FPS) * sample_rate))
        available_samples = int(waveform.shape[-1])
        if available_samples < required_samples:
            raise ValueError(
                "H3 reference-video source audio contains %d samples at %d "
                "Hz, but %d frames require %d. Choose a shorter H3-valid "
                "length; this node will not pad or stretch the soundtrack." %
                (available_samples, sample_rate, length, required_samples))
        copied_audio = {
            "waveform": waveform[..., :required_samples].clone(),
            "sample_rate": sample_rate,
        }
        status = (
            "%s: %d frames at %.6g fps -> %d frames at %d fps; copied "
            "%d audio samples at %d Hz (%.3fs)" %
            (input_route, int(source_frames.shape[0]), source_fps, length, FPS,
             required_samples, sample_rate, length / float(FPS)))
        return selected, copied_audio, length, status


def _external_prelude_paths(plan: dict[str, Any], fingerprint: str) -> dict[str, str]:
    directory = os.path.join(_run_dir(plan), "source")
    stem = "existing_video_%s" % str(fingerprint)[:20]
    return {
        "video": os.path.join(directory, stem + ".mp4"),
        "audio": os.path.join(directory, stem + ".safetensors"),
        "metadata": os.path.join(directory, stem + ".json"),
    }


def _save_external_audio(audio: dict[str, Any], path: str) -> None:
    if _st_save is None:
        raise RuntimeError(
            "safetensors is required to preserve existing-video audio.")
    waveform, sample_rate = _audio_waveform_3d(
        audio, "H3 existing-video prelude audio")
    temporary = "%s.%s.tmp" % (path, uuid.uuid4().hex)
    try:
        _st_save({"waveform": waveform.detach().cpu().contiguous()}, temporary,
                 metadata={
                     "format": "h3_existing_video_audio_v1",
                     "sample_rate": str(sample_rate),
                 })
        os.replace(temporary, path)
    finally:
        _safe_unlink(temporary)


class MiniMaxH3ChainExternalVideo:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "plan": (PLAN_TYPE, {
                    "tooltip": "The active H3 Chain Plan. Its canvas, crop, "
                               "context length, quality, and run folder are "
                               "used to prepare the imported video tail."}),
                "source_fps": ("FLOAT", {
                    "default": 24.0, "min": 0.001, "max": 1000.0,
                    "step": 0.001,
                    "tooltip": "Actual frame rate represented by source_frames "
                               "when using the separate IMAGE/AUDIO route. It "
                               "is ignored when source_video is connected, "
                               "because native VIDEO carries its own exact FPS."}),
                "prepend_original": ("BOOLEAN", {
                    "default": True,
                    "tooltip": "Persist a normalized copy of the complete "
                               "existing video and place it before generated "
                               "scenes during partial/final assembly. Disable "
                               "to output only the extension."}),
            },
            "optional": {
                "source_video": ("VIDEO", {
                    "tooltip": "Native ComfyUI VIDEO from core Load Video or "
                               "another VIDEO-producing loader. Its frames, "
                               "embedded audio, and exact FPS are decoded "
                               "directly. Connect either source_video or "
                               "source_frames, not both."}),
                "source_frames": ("IMAGE", {
                    "tooltip": "Decoded IMAGE batch from VHS or another video "
                               "loader. Set source_fps to the loader's actual "
                               "output rate. Connect either source_frames or "
                               "source_video, not both."}),
                "source_audio": ("AUDIO", {
                    "tooltip": "Optional soundtrack decoded from the existing "
                               "video. Use it with source_frames, or connect it "
                               "to override a native VIDEO's embedded audio. "
                               "Its tail can seed scene 1 audio; when prepend "
                               "is enabled it is preserved before the extension."}),
            },
        }

    RETURN_TYPES = (EXTERNAL_CONTEXT_TYPE, "STRING")
    RETURN_NAMES = ("external_context", "status")
    OUTPUT_TOOLTIPS = (
        "Typed imported-video tail for Loop Start. It contains only the small "
        "recursive context plus verified prelude artifact paths.",
        "Source/normalized frame counts, context duration, audio availability, "
        "and prepend status.",
    )
    FUNCTION = "prepare"
    CATEGORY = "conditioning/minimax/contex_loop"
    DESCRIPTION = ("Turn a native VIDEO or separately decoded IMAGE/AUDIO "
                   "video into scene 1's visual/audio predecessor, with "
                   "optional original-video prepend during assembly.")

    def prepare(self, plan, source_frames=None, source_fps=24.0,
                prepend_original=True, source_audio=None, source_video=None):
        source_frames, source_audio, source_fps, input_route = (
            _resolve_video_inputs(
                source_video, source_frames, source_audio, source_fps,
                "H3 existing-video adapter"))
        if torch is None or not torch.is_tensor(source_frames):
            raise ValueError("H3 existing-video source_frames must be an IMAGE tensor.")
        if source_frames.ndim != 4 or int(source_frames.shape[-1]) < 3:
            raise ValueError(
                "H3 existing-video source_frames must be "
                "[frames,height,width,channels]; got %r." %
                (getattr(source_frames, "shape", None),))
        cfg = plan["compatibility"]
        context_length = int(cfg["context_length"])
        indices = _external_video_frame_indices(
            int(source_frames.shape[0]), float(source_fps))
        normalized_count = int(indices.numel())
        if normalized_count < context_length:
            raise ValueError(
                "H3 existing video becomes %d frames at 24 fps, but this plan "
                "needs at least %d context frames. Supply a longer video or "
                "reduce context_length." % (normalized_count, context_length))

        selected_indices = indices if bool(prepend_original) else indices[-context_length:]
        selected = source_frames.index_select(
            0, selected_indices.to(device=source_frames.device))
        normalized = _resize(
            selected, int(cfg["width"]), int(cfg["height"]), cfg["crop"])
        context_frames = _tensor_cpu_clone(normalized[-context_length:])

        normalized_audio = None
        context_audio = None
        if source_audio is not None:
            _source_waveform, source_rate = _audio_waveform_3d(
                source_audio, "H3 existing-video source audio")
            normalized_samples = int(round(
                normalized_count / float(FPS) * source_rate))
            normalized_audio = _resample_audio_exact(
                source_audio, source_rate, normalized_samples,
                int(_source_waveform.shape[1]),
                "H3 existing-video source audio")
            configured_audio_frames = int(cfg["audio_context_length"])
            audio_context_frames = min(
                normalized_count, configured_audio_frames or context_length)
            context_samples = int(round(
                audio_context_frames / float(FPS) * source_rate))
            context_audio = {
                "waveform": _tensor_cpu_clone(
                    normalized_audio["waveform"][..., -context_samples:]),
                "sample_rate": source_rate,
            }

        external_context = {
            "version": 1,
            "base_plan_hash": str(plan.get("base_plan_hash") or plan["plan_hash"]),
            "context_frames": context_frames,
            "context_audio": context_audio,
            "prelude": None,
        }
        contract = _external_context_contract(external_context)
        external_context["context_hash"] = _fingerprint(contract)

        if bool(prepend_original):
            # The complete normalized source is needed only long enough to
            # persist an immutable stream-copy-compatible prelude. Recursive
            # state receives the short tail above, never this full tensor.
            if int(normalized.shape[0]) != normalized_count:
                raise RuntimeError(
                    "H3 existing-video normalization produced an unexpected "
                    "frame count.")
            content_fingerprint = _fingerprint({
                "frames": _tensor_fingerprint(normalized),
                "audio": (_audio_fingerprint(normalized_audio)
                          if normalized_audio is not None else "none"),
                "fps": FPS,
                "width": int(cfg["width"]),
                "height": int(cfg["height"]),
                "crop": cfg["crop"],
                "crf": int(plan["segment_crf"]),
            })
            paths = _external_prelude_paths(plan, content_fingerprint)
            os.makedirs(os.path.dirname(paths["video"]), exist_ok=True)
            cached = None
            if os.path.isfile(paths["metadata"]):
                try:
                    cached = _read_json(paths["metadata"])
                except (OSError, ValueError, json.JSONDecodeError):
                    cached = None
            video_reusable = bool(
                isinstance(cached, dict) and
                cached.get("source_fingerprint") == content_fingerprint and
                os.path.isfile(paths["video"]) and
                str(cached.get("video_sha256") or "") ==
                _file_sha256(paths["video"]))
            if not video_reusable:
                _write_segment_video(
                    normalized, paths["video"], FPS, int(plan["segment_crf"]),
                    metadata={
                        "title": "Existing video before H3 extension",
                        "comment": "Normalized 24 fps prelude for %s" %
                                   plan["run_name"],
                    })
            if normalized_audio is not None:
                audio_reusable = bool(
                    isinstance(cached, dict) and
                    cached.get("source_fingerprint") == content_fingerprint and
                    os.path.isfile(paths["audio"]) and
                    str(cached.get("audio_sha256") or "") ==
                    _file_sha256(paths["audio"]))
                if not audio_reusable:
                    _save_external_audio(normalized_audio, paths["audio"])
            prelude = {
                "format": "h3_existing_video_prelude_v1",
                "prepend": True,
                "source_fingerprint": content_fingerprint,
                "frame_count": normalized_count,
                "fps": FPS,
                "width": int(cfg["width"]),
                "height": int(cfg["height"]),
                "duration_seconds": normalized_count / float(FPS),
                "video": _relative_output_path(paths["video"]),
                "video_sha256": _file_sha256(paths["video"]),
                "source_fps": float(source_fps),
            }
            if normalized_audio is not None:
                prelude.update({
                    "audio": _relative_output_path(paths["audio"]),
                    "audio_sha256": _file_sha256(paths["audio"]),
                    "audio_sample_rate": int(normalized_audio["sample_rate"]),
                })
            _atomic_json(paths["metadata"], prelude)
            prelude["metadata"] = _relative_output_path(paths["metadata"])
            external_context["prelude"] = prelude

        status = (
            "%s: %d source frames at %.3f fps -> %d frames at %d fps; "
            "%d-frame (%.3fs) context; audio %s; original %s" %
            (input_route, int(source_frames.shape[0]), float(source_fps),
             normalized_count, FPS, context_length,
             context_length / float(FPS),
             "ready" if context_audio is not None else "not supplied",
             "will be prepended" if bool(prepend_original)
             else "will not be prepended"))
        return (external_context, status)


class MiniMaxH3ChainPlan:
    @classmethod
    def INPUT_TYPES(cls):
        sample = json.dumps({
            "shots": [
                {"id": "intro", "prompt": "Describe the opening shot."},
                {"id": "continuation", "prompt": "Continue the same take."},
            ]
        }, indent=2)
        return {
            "required": {
                "plan_json": ("STRING", {
                    "default": sample, "multiline": True,
                    "dynamicPrompts": False,
                    "tooltip": "JSON source for the visual Scene Plan editor. "
                               "It stores the shared prompt, ordered scenes, "
                               "optional scene lengths, steps, and seeds. Use "
                               "Raw JSON in the editor to import or export it."}),
                "run_name": ("STRING", {
                    "default": "h3_chain",
                    "tooltip": "Stable name for this chain's checkpoint folder "
                               "under ComfyUI output/h3_chain. Keep it unchanged "
                               "when resuming; change it to start an independent "
                               "render without reusing old checkpoints."}),
                "generation_fingerprint": ("STRING", {
                    "default": "",
                    "tooltip": "Change this tag whenever the model, VAE, global "
                               "references, CFG, scheduler, or other external "
                               "generation settings change. It is enforced when "
                               "resuming checkpoints."}),
                "width": ("INT", {
                    "default": 960, "min": 32, "max": 4096, "step": 32,
                    "tooltip": "Generation width for every scene. Connect the "
                               "Plan width output to the stock Ref2VA/I2V node "
                               "so its latent always matches the plan."}),
                "height": ("INT", {
                    "default": 544, "min": 32, "max": 4096, "step": 32,
                    "tooltip": "Generation height for every scene. Connect the "
                               "Plan height output to the stock Ref2VA/I2V node "
                               "so its latent always matches the plan."}),
                "context_length": (list(H3_CONTEXT_LENGTHS), {
                    "default": 22,
                    "tooltip": "Previous-scene frames carried into each "
                               "continuation. In the recommended head mode they "
                               "are regenerated at the start, then removed by "
                               "Trim. Larger values preserve more motion but "
                               "reduce each scene's new delivered frames."}),
                "encode_mode": (["video", "frames"], {
                    "default": "video",
                    "tooltip": "video encodes the overlap as one motion-bearing "
                               "clip and is recommended. frames encodes separate "
                               "still anchors and is heavier."}),
                "anchor_mode": (["head", "before"], {
                    "default": "head",
                    "tooltip": "head places the overlap at the beginning of the "
                               "new clip and requires Trim; it is the tested "
                               "default. before uses negative-time anchors and "
                               "returns no repeated frames."}),
                "crop": (["disabled", "center"], {
                    "default": "disabled",
                    "tooltip": "How saved context frames fit the generation "
                               "canvas. disabled stretches; center preserves "
                               "aspect ratio and center-crops."}),
                "audio_mode": (list(AUDIO_MODES), {
                    "default": "source_track",
                    "tooltip": "source_track slices one external track per "
                               "scene; generated_audio continues H3's generated "
                               "sound through latent context; "
                               "source_plus_timeline supplies both the source "
                               "slice and previous generated-audio context."}),
                "audio_context_length": ("INT", {
                    "default": 22, "min": 0, "max": 240,
                    "tooltip": "Previous generated-audio tail length in video "
                               "frames. 0 follows context_length. Used only by "
                               "generated_audio and source_plus_timeline; it is "
                               "ignored by source_track."}),
                "default_duration_seconds": ("FLOAT", {
                    "default": 15.0, "min": 0.1,
                    "max": MAX_H3_FRAMES / FPS, "step": 0.01,
                    "tooltip": "Scene duration used when neither the scene nor "
                               "JSON defaults specify one. It rounds UP to the "
                               "next H3-valid 17k+5 frame length."}),
                "default_steps": ("INT", {
                    "default": 20, "min": 1, "max": 10000,
                    "tooltip": "Sampler step count emitted for scenes without a "
                               "per-scene or JSON-default steps value."}),
                "base_seed": ("INT", {
                    "default": 0, "min": 0, "max": MAX_SEED,
                    "tooltip": "Base for deterministic per-scene seeds. A scene "
                               "with its own seed overrides this derived value."}),
                "segment_crf": ("INT", {
                    "default": 18, "min": 0, "max": 51,
                    "tooltip": "H.264 checkpoint quality: lower is higher "
                               "quality and larger files. 18 is visually high "
                               "quality; 0 is lossless and 51 is lowest quality."}),
            }
        }

    RETURN_TYPES = (PLAN_TYPE, "STRING", "INT", "INT", "INT")
    RETURN_NAMES = ("plan", "summary", "clip_count", "width", "height")
    OUTPUT_TOOLTIPS = (
        "Validated chain plan. Connect it to Loop Start and, for recovery, "
        "Manifest Load.",
        "Human-readable scene count, delivered duration, and compatibility "
        "summary.",
        "Number of scenes in the plan.",
        "Validated generation width; connect to the stock H3 conditioning node.",
        "Validated generation height; connect to the stock H3 conditioning node.",
    )
    FUNCTION = "build"
    CATEGORY = "conditioning/minimax/contex_loop"
    DESCRIPTION = ("Parse and validate a frame-exact MiniMax H3 shot plan. "
                   "The plan computes valid lengths, overlaps, audio windows, "
                   "seeds, and checkpoint compatibility hashes.")

    def build(self, plan_json, run_name, generation_fingerprint, width, height,
              context_length,
              encode_mode, anchor_mode, crop, audio_mode,
              audio_context_length, default_duration_seconds, default_steps,
              base_seed, segment_crf):
        plan = _normalize_plan(
            plan_json, run_name, width, height, context_length, encode_mode,
            anchor_mode, crop, audio_mode, audio_context_length,
            default_duration_seconds, default_steps, base_seed, segment_crf,
            generation_fingerprint)
        return (plan, plan["summary"], len(plan["shots"]),
                plan["compatibility"]["width"],
                plan["compatibility"]["height"])


class MiniMaxH3ChainScenePromptEditor:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "plan": (PLAN_TYPE, {
                    "tooltip": "Connect the H3 Chain Plan output. The companion "
                               "editor modifies that Plan node's active scene "
                               "prompt directly; this socket passes the "
                               "validated plan through unchanged."}),
            }
        }

    RETURN_TYPES = (PLAN_TYPE,)
    RETURN_NAMES = ("plan",)
    OUTPUT_TOOLTIPS = (
        "The connected validated plan, unchanged at execution time. You may "
        "insert this companion between Plan and Loop Start or connect it as "
        "an editor-only branch.",
    )
    FUNCTION = "passthrough"
    CATEGORY = "conditioning/minimax/contex_loop"
    DESCRIPTION = ("Large, keyboard-friendly companion editor synchronized "
                   "bidirectionally with each scene prompt in the connected "
                   "H3 Chain Plan.")

    def passthrough(self, plan):
        return (plan,)


class MiniMaxH3ChainLoopStart:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "plan": (PLAN_TYPE, {
                    "tooltip": "Validated output from H3 Chain Plan."}),
                "start_clip": ("INT", {
                    "default": 1, "min": 1, "max": MAX_SHOTS,
                    "tooltip": "Legacy/resume scene to render next. Use 1 for "
                               "a new chain. A non-empty scene_range overrides "
                               "this value. "
                               "A value above 1 loads and validates the saved "
                               "checkpoint for the preceding scene before "
                               "resuming."}),
            },
            "optional": {
                "scene_range": ("STRING", {
                    "default": "",
                    "tooltip": "Inclusive contiguous scenes to generate. "
                               "Leave blank to run from start_clip through the "
                               "end; use 3 for only scene 3 or 3:8 for scenes "
                               "3 through 8. A start above 1 requires the "
                               "preceding checkpoint. Disjoint comma selections "
                               "are rejected because they break continuity."}),
                "source_audio": ("AUDIO", {
                    "tooltip": "Full external soundtrack. Required by "
                               "source_track and source_plus_timeline. Current "
                               "Shot slices the exact window for each scene. A "
                               "short, completely silent placeholder is padded."}),
                "external_context": (EXTERNAL_CONTEXT_TYPE, {
                    "tooltip": "Optional output from MiniMax H3 Existing Video "
                               "Context. When connected, scene 1 continues from "
                               "that video's tail and its repeated head is "
                               "trimmed exactly like every later scene."}),
            },
            "hidden": {
                "initial_state": (STATE_TYPE,),
            },
        }

    RETURN_TYPES = (FLOW_TYPE, STATE_TYPE, "STRING")
    RETURN_NAMES = ("flow", "state", "status")
    OUTPUT_TOOLTIPS = (
        "Recursion control link. Connect directly to H3 Chain Loop End's flow "
        "input; do not route it through other nodes.",
        "Current chain state for Current Shot and the recursive body.",
        "Starting scene, total scene count, and resume/padding status.",
    )
    FUNCTION = "start"
    CATEGORY = "conditioning/minimax/contex_loop"
    DESCRIPTION = ("Start or resume a contiguous range of a sequential H3 "
                   "chain. Ranges beginning above 1 load and validate the "
                   "preceding segment checkpoint.")

    @classmethod
    def IS_CHANGED(cls, *args, **kwargs):
        return float("NaN")

    def start(self, plan, start_clip, source_audio=None, scene_range="",
              external_context=None, initial_state=None):
        if initial_state is None:
            prepared_plan = _plan_with_external_context(plan, external_context)
            prepared_plan = _plan_with_source_audio(prepared_plan, source_audio)
            range_start, range_end = _parse_scene_range(
                scene_range, len(prepared_plan["shots"]), start_clip)
            state = _initial_state(
                prepared_plan, range_start, range_end,
                external_context=external_context if range_start == 1 else None)
        else:
            state = dict(initial_state)
            prepared_plan = state["plan"]
            if prepared_plan.get("base_plan_hash") != plan.get("plan_hash"):
                raise ValueError("H3 chain plan changed during recursive execution.")
            state["plan"] = prepared_plan
        end_clip = int(state.get("end_clip", len(prepared_plan["shots"])))
        status = "clip %d/%d; selected range %d:%d" % (
            state["index"], len(prepared_plan["shots"]),
            int(state.get("range_start", state["index"])), end_clip)
        if state.get("resumed_from"):
            status += "; resumed from clip %d" % state["resumed_from"]
        if prepared_plan["compatibility"].get("source_audio_silent_padding"):
            status += "; silent source audio will be padded to the plan duration"
        if prepared_plan["compatibility"].get("external_context_hash"):
            status += "; scene 1 extends imported video"
            if isinstance(prepared_plan.get("prelude"), dict):
                status += "; original video will be prepended"
        return ("h3_chain", state, status)


class MiniMaxH3ChainCurrent:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "state": (STATE_TYPE, {
                    "tooltip": "Current state from H3 Chain Loop Start."}),
            },
            "optional": {
                "source_audio": ("AUDIO", {
                    "tooltip": "The same full source track connected to Loop "
                               "Start. It is sliced frame-exactly for the current "
                               "scene in source-track modes."}),
            },
        }

    RETURN_TYPES = (STATE_TYPE, "INT", "INT", "STRING", "STRING", "INT",
                    "INT", "INT", "INT", "INT", "FLOAT", "FLOAT",
                    "AUDIO", "STRING")
    RETURN_NAMES = ("state", "clip_index", "clip_count", "shot_id", "prompt",
                    "noise_seed", "length", "steps", "width", "height",
                    "audio_start", "audio_duration", "source_audio_slice",
                    "status")
    OUTPUT_TOOLTIPS = (
        "Unchanged current state for Chain Context, Segment Save, Review, and "
        "Loop End.",
        "One-based scene number currently being generated.",
        "Total scenes in the plan.",
        "Stable scene identifier used in checkpoints and status messages.",
        "Shared prompt followed by the current scene prompt. Connect to the "
        "stock H3 conditioning node's prompt input.",
        "Resolved unsigned 64-bit seed for the current scene. Connect to the "
        "sampler noise seed.",
        "H3-valid RAW frame count, including the repeated head overlap on "
        "continuations. Connect to the stock H3 conditioning node's length.",
        "Resolved sampler steps for this scene.",
        "Plan generation width.",
        "Plan generation height.",
        "Start time in seconds of this scene's extension-track window. For an "
        "imported-video scene 1, its separate context lead precedes this time.",
        "Raw conditioning-audio duration in seconds, including any imported "
        "scene 1 context lead.",
        "Frame-exact current source-audio window for Ref2VA. It is empty in "
        "generated_audio mode.",
        "Current scene timing, delivered frames, source window, and seed.",
    )
    FUNCTION = "current"
    CATEGORY = "conditioning/minimax/contex_loop"
    DESCRIPTION = ("Expose the current shot's prompt, seed, dimensions, valid "
                   "length, steps, and frame-exact source-audio window.")

    def current(self, state, source_audio=None):
        plan = state["plan"]
        index = int(state["index"])
        shot = plan["shots"][index - 1]
        mode = plan["compatibility"]["audio_mode"]
        audio_slice = None
        if mode in ("source_track", "source_plus_timeline"):
            _validate_source_audio_hash(
                plan["compatibility"], source_audio, "H3 Chain Current Shot")
            external_lead = int(shot.get("external_context_frames", 0))
            if index == 1 and external_lead > 0:
                audio_slice = _slice_audio_after_external_context(
                    source_audio, state.get("previous_audio"),
                    int(shot["raw_frames"]), external_lead,
                    pad_silence=bool(plan["compatibility"].get(
                        "source_audio_silent_padding")))
            else:
                audio_slice = _slice_audio(
                    source_audio, shot["audio_start_seconds"],
                    shot["audio_duration_seconds"],
                    pad_silence=bool(plan["compatibility"].get(
                        "source_audio_silent_padding")))
        external_lead = int(shot.get("external_context_frames", 0))
        if index == 1 and external_lead > 0:
            audio_status = "imported lead %.3fs + song 0..%.3fs" % (
                external_lead / float(FPS),
                int(shot["delivered_frames"]) / float(FPS))
        else:
            audio_status = "song %.3f..%.3fs" % (
                shot["audio_start_seconds"],
                shot["audio_start_seconds"] + shot["audio_duration_seconds"])
        status = ("clip %d/%d %s; raw=%df delivered=%df; %s; seed=%d" %
                  (index, len(plan["shots"]), shot["id"], shot["raw_frames"],
                   shot["delivered_frames"], audio_status, shot["seed"]))
        cfg = plan["compatibility"]
        return (state, index, len(plan["shots"]), shot["id"], shot["prompt"],
                shot["seed"], shot["raw_frames"], shot["steps"], cfg["width"],
                cfg["height"], shot["audio_start_seconds"],
                shot["audio_duration_seconds"], audio_slice, status)


class MiniMaxH3ChainContext:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "state": (STATE_TYPE, {
                    "tooltip": "Current state from H3 Chain Current Shot."}),
                "conditioning": ("CONDITIONING", {
                    "tooltip": "Conditioning from the stock MiniMax H3 "
                               "Ref2VA/I2V node. Scene 1 passes through without "
                               "motion context; later scenes receive the saved "
                               "continuation context."}),
                "vae": ("VAE", {
                    "tooltip": "MiniMax H3 video VAE used to encode saved "
                               "context frames for continuation scenes."}),
                "latent": ("LATENT", {
                    "tooltip": "The CURRENT scene's empty AV latent from the "
                               "stock H3 conditioning node."}),
            },
            "optional": {
                "audio_vae": ("VAE", {
                    "tooltip": "H3 audio VAE used only when scene 1 continues "
                               "from imported video audio. Later loop scenes "
                               "reuse their saved AV latent directly. It may be "
                               "left disconnected for visual-only context or "
                               "source_track mode."}),
            }
        }

    RETURN_TYPES = ("CONDITIONING", "INT", "BOOLEAN")
    RETURN_NAMES = ("conditioning", "trim_frames", "is_continuation")
    OUTPUT_TOOLTIPS = (
        "Conditioning ready for the H3 guider/sampler: scene 1 passes through "
        "unless Existing Video Context seeds it; later scenes always continue.",
        "Repeated leading frames to remove after decoding. Connect to "
        "MiniMax H3 Contex Loop Trim.",
        "True for resumed/continued scenes, false for the first scene.",
    )
    FUNCTION = "apply"
    CATEGORY = "conditioning/minimax/contex_loop"
    DESCRIPTION = ("Apply H3 Motion Context to every continuation, including "
                   "scene 1 when Existing Video Context is connected.")

    def apply(self, state, conditioning, vae, latent, audio_vae=None):
        index = int(state["index"])
        external_first = index == 1 and bool(state.get("external_context"))
        if index == 1 and not external_first:
            return (_prepare_native_guide_conditioning(conditioning), 0, False)
        previous_frames = state.get("previous_frames")
        if previous_frames is None:
            raise ValueError("H3 chain continuation has no previous frame checkpoint.")
        plan = state["plan"]
        cfg = plan["compatibility"]
        use_latent_audio = cfg["audio_mode"] in (
            "generated_audio", "source_plus_timeline")
        previous_latent = state.get("previous_latent") if use_latent_audio else None
        previous_audio = (state.get("previous_audio")
                          if use_latent_audio and external_first else None)
        if (use_latent_audio and previous_latent is None
                and previous_audio is None and not external_first):
            raise ValueError("H3 chain continuation has no previous AV latent.")
        out, trim = MiniMaxH3MotionContext().apply(
            conditioning=conditioning,
            vae=vae,
            latent=latent,
            context_frames=previous_frames,
            context_length=cfg["context_length"],
            encode_mode=cfg["encode_mode"],
            anchor_mode=cfg["anchor_mode"],
            crop=cfg["crop"],
            audio_context_length=cfg["audio_context_length"],
            audio_mode="timeline",
            context_latent=previous_latent,
            audio_vae=audio_vae,
            context_audio=previous_audio,
        )
        return (out, trim, True)


class MiniMaxH3ChainSegmentSave:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "state": (STATE_TYPE, {
                    "tooltip": "Current state from H3 Chain Current Shot."}),
                "images": ("IMAGE", {
                    "tooltip": "Delivered images AFTER MiniMax H3 Contex "
                               "Loop Trim. "
                               "The frame count must exactly match this scene's "
                               "planned delivered length."}),
                "sampled_latent": ("LATENT", {
                    "tooltip": "Raw sampler output for the current scene, "
                               "before VAE decoding. Its compact AV streams are "
                               "saved for checkpoint resume and audio context."}),
            },
            "optional": {
                "audio": ("AUDIO", {
                    "tooltip": "Delivered decoded audio AFTER MiniMax H3 "
                               "Contex Loop Trim with match_tail enabled. "
                               "Required for "
                               "generated_audio and synchronized review."}),
            },
            "hidden": {
                "prompt": "PROMPT",
                "extra_pnginfo": "EXTRA_PNGINFO",
            },
        }

    RETURN_TYPES = (SEGMENT_TYPE, "STRING")
    RETURN_NAMES = ("segment", "status")
    OUTPUT_TOOLTIPS = (
        "Persisted scene record for Review Gate and Loop End.",
        "Saved scene number, video/checkpoint paths, frame count, and duration.",
    )
    FUNCTION = "save"
    OUTPUT_NODE = True
    CATEGORY = "conditioning/minimax/contex_loop"
    DESCRIPTION = ("Immediately save one delivered H3 clip as an H.264 segment "
                   "plus a safetensors resume checkpoint, exact prompt metadata, "
                   "and workflow recovery sidecars.")

    @classmethod
    def IS_CHANGED(cls, *args, **kwargs):
        return float("NaN")

    def save(self, state, images, sampled_latent, audio=None, prompt=None,
             extra_pnginfo=None):
        if _st_save is None:
            raise RuntimeError("safetensors is required for H3 chain checkpoints.")
        plan = state["plan"]
        index = int(state["index"])
        shot = plan["shots"][index - 1]
        actual_frames = int(images.shape[0])
        expected_frames = int(shot["delivered_frames"])
        if actual_frames != expected_frames:
            raise ValueError(
                "H3 chain clip %d produced %d delivered frames; expected %d. "
                "Wire decoded images through MiniMax H3 Contex Loop Trim before "
                "Segment Save." % (index, actual_frames, expected_frames))

        mode = plan["compatibility"]["audio_mode"]
        if mode == "generated_audio" and audio is None:
            raise ValueError(
                "H3 chain generated_audio mode requires decoded audio on Segment "
                "Save. Wire it through MiniMax H3 Contex Loop Trim first.")
        compact = _compact_latent(sampled_latent)
        context_length = int(plan["compatibility"]["context_length"])
        context_frames = _tensor_cpu_clone(images[-context_length:])
        parts = compact["samples"]
        tensors = {
            "context_frames": context_frames,
            "video": parts[0],
            "audio": parts[1],
        }
        sample_rate = 0
        if audio is not None:
            waveform, sample_rate = _validate_audio(
                audio, "H3 chain clip %d delivered audio" % index,
                expected_frames=expected_frames)
            tensors["delivered_audio"] = _tensor_cpu_clone(waveform)

        paths = _artifact_paths(plan, index)
        os.makedirs(os.path.dirname(paths["segment"]), exist_ok=True)
        os.makedirs(os.path.dirname(paths["checkpoint"]), exist_ok=True)
        archives = _write_run_archives(plan, prompt, extra_pnginfo)
        previous_metadata = None
        if os.path.isfile(paths["metadata"]):
            try:
                previous_metadata = _read_json(paths["metadata"])
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                _LOG.warning("H3 Chain is replacing unreadable clip %d metadata: %s",
                             index, exc)

        transaction = uuid.uuid4().hex
        published_segment = _versioned_path(paths["segment"], transaction)
        published_checkpoint = _versioned_path(paths["checkpoint"], transaction)
        published_prompt = os.path.splitext(published_segment)[0] + ".prompt.txt"
        checkpoint_tmp = "%s.%s.tmp" % (published_checkpoint, uuid.uuid4().hex)
        committed = False
        try:
            video_metadata = _archive_media_metadata(archives)
            video_metadata.update({
                "title": "H3 scene %d - %s" % (index, shot["id"]),
                "comment": shot["prompt"],
                "description": shot.get("scene_prompt", ""),
                "synopsis": shot["prompt_hash"],
                "h3_prompt": shot["prompt"],
                "h3_seed": str(shot["seed"]),
            })
            _write_segment_video(
                images, published_segment, FPS, plan["segment_crf"],
                metadata=video_metadata)
            _atomic_text(published_prompt, shot["prompt"])
            _st_save(tensors, checkpoint_tmp, metadata={
                "format": "h3_chain_checkpoint_v3",
                "index": str(index),
                "history_hash": _history_hash(plan, index),
                "prompt_prefix": str(plan.get("prompt_prefix") or ""),
                "scene_prompt": str(shot.get("scene_prompt") or ""),
                "prompt": str(shot["prompt"]),
                "prompt_hash": str(shot["prompt_hash"]),
                "seed": str(shot["seed"]),
                "sample_rate": str(sample_rate),
            })
            os.replace(checkpoint_tmp, published_checkpoint)

            segment = {
                "index": index,
                "id": shot["id"],
                "segment": _relative_output_path(published_segment),
                "checkpoint": _relative_output_path(published_checkpoint),
                "metadata": _relative_output_path(paths["metadata"]),
                "prompt_file": _relative_output_path(published_prompt),
                "raw_frames": shot["raw_frames"],
                "delivered_frames": shot["delivered_frames"],
                "history_hash": _history_hash(plan, index),
                **_prompt_fields(plan, index),
                "archives": archives,
                "seed": shot["seed"],
                "steps": shot["steps"],
                "sample_rate": sample_rate,
                "segment_sha256": _file_sha256(published_segment),
                "checkpoint_sha256": _file_sha256(published_checkpoint),
                "prompt_file_sha256": _file_sha256(published_prompt),
            }
            metadata = {
                "format": "h3_chain_segment_v3",
                "run_name": plan["run_name"],
                "plan_hash": plan["plan_hash"],
                "history_hash": segment["history_hash"],
                "compatibility": plan["compatibility"],
                "archives": archives,
                "segment": segment,
            }
            # This metadata replacement is the transaction's commit point. Until
            # it succeeds, resume keeps referencing the previous immutable pair.
            _atomic_json(paths["metadata"], metadata)
            committed = True
        finally:
            _safe_unlink(checkpoint_tmp)
            if not committed:
                _safe_unlink(published_segment)
                _safe_unlink(published_checkpoint)
                _safe_unlink(published_prompt)

        _cleanup_previous_artifacts(
            plan, index, previous_metadata,
            {published_segment, published_checkpoint, published_prompt})
        status = ("saved clip %d/%d: %s + checkpoint %s" %
                  (index, len(plan["shots"]), published_segment,
                   published_checkpoint))
        _LOG.info("H3 Chain %s", status)
        return {"ui": {"text": [status]}, "result": (segment, status)}


def _review_video(plan: dict[str, Any], segment: dict[str, Any],
                  audio: dict[str, Any] | None) -> tuple[dict[str, str], bool, str]:
    source = _absolute_output_path(segment["segment"])
    relative_source = _relative_output_path(source)
    if audio is None:
        return ({
            "filename": os.path.basename(relative_source),
            "subfolder": os.path.dirname(relative_source),
            "type": "output",
        }, False, "No audio is connected; this review is silent.")

    expected_frames = int(segment["delivered_frames"])
    waveform, sample_rate = _validate_audio(
        audio, "H3 Chain Review audio", expected_frames=expected_frames)
    audio_value = {"waveform": waveform, "sample_rate": sample_rate}
    audio_hash = _audio_fingerprint(audio_value)
    video_hash = str(segment.get("segment_sha256") or _file_sha256(source))
    index = int(segment["index"])
    review_dir = os.path.join(_run_dir(plan), "reviews")
    os.makedirs(review_dir, exist_ok=True)
    name = "clip_%04d.%s.%s.review.mp4" % (
        index, video_hash[:12], audio_hash[:12])
    review_path = os.path.join(review_dir, name)

    if not os.path.isfile(review_path):
        ffmpeg = shutil.which("ffmpeg")
        transaction = uuid.uuid4().hex
        wav_tmp = os.path.join(review_dir, ".review.%s.wav" % transaction)
        video_tmp = os.path.join(review_dir, ".review.%s.mp4" % transaction)
        try:
            if ffmpeg:
                _write_wav(audio_value, wav_tmp)
                _run_ffmpeg([
                    ffmpeg, "-y", "-i", source, "-i", wav_tmp,
                    "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy",
                    "-c:a", "aac", "-b:a", "192k",
                    "-t", "%.9f" % (expected_frames / float(FPS)),
                    "-movflags", "+faststart", video_tmp,
                ], timeout_seconds=60.0)
            else:
                _LOG.warning(
                    "H3 Chain ffmpeg executable not found; preparing review "
                    "audio with the built-in PyAV fallback")
                _pyav_mux_audio(
                    source, audio_value, video_tmp, 192, expected_frames)
            os.replace(video_tmp, review_path)
        finally:
            _safe_unlink(wav_tmp)
            _safe_unlink(video_tmp)

        prefix = "clip_%04d." % index
        for filename in os.listdir(review_dir):
            if (filename != name and filename.startswith(prefix) and
                    filename.endswith(".review.mp4")):
                _safe_unlink(os.path.join(review_dir, filename))

    return (_video_output_item(review_path), True, "")


def _review_display_id(unique_id: Any, dynprompt: Any) -> str:
    execution_id = str(unique_id)
    if dynprompt is not None:
        try:
            return str(dynprompt.get_display_node_id(execution_id))
        except Exception:
            pass
    return execution_id


def _review_timeout_seconds(minutes: Any) -> float:
    value = float(minutes)
    if not math.isfinite(value) or value < 0:
        raise ValueError("H3 review timeout must be a finite non-negative value.")
    return min(1440.0, value) * 60.0


async def _await_review_decision(future: asyncio.Future,
                                 timeout_seconds: float) -> dict[str, Any]:
    """Wait with a heartbeat so cross-thread HTTP decisions always wake up.

    ComfyUI executes prompts on a worker thread and serves HTTP on another
    asyncio loop. Some loop/selector combinations queue call_soon_threadsafe
    callbacks without waking an otherwise idle selector. A short shielded wait
    keeps the execution loop responsive without cancelling its decision future.
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_seconds if timeout_seconds > 0 else None
    while True:
        if future.done():
            return future.result()
        wait_seconds = 0.25
        if deadline is not None:
            remaining = deadline - loop.time()
            if remaining <= 0:
                return {"action": "approve", "timed_out": True}
            wait_seconds = min(wait_seconds, remaining)
        try:
            return await asyncio.wait_for(
                asyncio.shield(future), timeout=wait_seconds)
        except asyncio.TimeoutError:
            if deadline is not None and loop.time() >= deadline:
                return {"action": "approve", "timed_out": True}


class MiniMaxH3ChainReview:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "state": (STATE_TYPE, {
                    "tooltip": "Current state from H3 Chain Current Shot. It "
                               "identifies the scene whose saved segment is "
                               "being reviewed."}),
                "segment": (SEGMENT_TYPE, {
                    "tooltip": "Persisted scene output from H3 Chain Segment "
                               "Save. Saving before review makes every accepted "
                               "scene recoverable."}),
                "enabled": ("BOOLEAN", {
                    "default": True,
                    "tooltip": "Pause after every saved segment for approval."}),
                "play_notification_sound": ("BOOLEAN", {
                    "default": False,
                    "tooltip": "Play a browser chime when a segment becomes "
                               "ready for review."}),
                "auto_continue_timeout_minutes": ("FLOAT", {
                    "default": 0.0,
                    "min": 0.0,
                    "max": 1440.0,
                    "step": 0.5,
                    "tooltip": "Automatically approve and continue after this "
                               "many minutes. 0 waits indefinitely."}),
                "unload_models_while_waiting": ("BOOLEAN", {
                    "default": False,
                    "tooltip": "Release model weights from VRAM after the review "
                               "appears. Approval remains responsive; continuing "
                               "must reload the model stack."}),
                "assemble_partial_on_stop": ("BOOLEAN", {
                    "default": True,
                    "tooltip": "Approve & stop also joins every accepted segment "
                               "through the current scene into a partial MP4."}),
                "partial_audio_source": (["checkpointed", "source", "none"], {
                    "default": "checkpointed",
                    "tooltip": "Audio for the partial MP4. checkpointed uses each "
                               "saved delivered-audio track; source requires the "
                               "full source_audio input."}),
            },
            "optional": {
                "audio": ("AUDIO", {
                    "tooltip": "Wire frame-exact delivered audio from H3 "
                               "MiniMax H3 Contex Loop Trim for synchronized "
                               "review."}),
                "source_audio": ("AUDIO", {
                    "tooltip": "Optional full source track used only when partial "
                               "audio source is source."}),
            },
            "hidden": {
                "dynprompt": "DYNPROMPT",
                "unique_id": "UNIQUE_ID",
            },
        }

    RETURN_TYPES = (SEGMENT_TYPE, "STRING")
    RETURN_NAMES = ("segment", "status")
    OUTPUT_TOOLTIPS = (
        "The approved segment, or the same segment after review is disabled. "
        "Connect to Loop End.",
        "Review decision, retry seed, timeout, stop, or partial-assembly status.",
    )
    FUNCTION = "review"
    OUTPUT_NODE = True
    CATEGORY = "conditioning/minimax/contex_loop"
    DESCRIPTION = ("Pause after a checkpointed H3 segment for synchronized "
                   "video/audio review. Approve, stop, retry an edited scene "
                   "prompt, or reroll its seed from the node UI.")

    @classmethod
    def IS_CHANGED(cls, *args, **kwargs):
        return float("NaN")

    async def review(self, state, segment, enabled, play_notification_sound,
                     auto_continue_timeout_minutes, unload_models_while_waiting,
                     assemble_partial_on_stop, partial_audio_source, audio=None,
                     source_audio=None,
                     dynprompt=None, unique_id=None):
        plan = state["plan"]
        index = int(state["index"])
        if int(segment.get("index", -1)) != index:
            raise ValueError(
                "H3 Chain Review received the wrong segment for clip %d." % index)
        if not enabled:
            status = "review bypassed for clip %d" % index
            return {"ui": {"text": [status]}, "result": (segment, status)}
        if PromptServer is None or web is None:
            raise RuntimeError("H3 Chain Review requires ComfyUI's prompt server.")

        # Publish the persisted video and pending token BEFORE preparing the
        # optional audiovisual preview. Firefox/proxy websocket differences
        # made this ordering bug look like a dead button: a slow or stuck audio
        # mux meant the browser never received a token at all. Review audio is
        # a convenience, not part of checkpoint validity, so it must never hold
        # the gate controls hostage.
        video, _has_audio, no_audio_warning = _review_video(
            plan, segment, None)
        shot = plan["shots"][index - 1]
        timeout_seconds = _review_timeout_seconds(
            auto_continue_timeout_minutes)
        server_now = time.time()
        deadline = server_now + timeout_seconds if timeout_seconds > 0 else None
        token = uuid.uuid4().hex
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        payload = {
            "token": token,
            "node_id": _review_display_id(unique_id, dynprompt),
            "execution_id": str(unique_id),
            "clip_index": index,
            "clip_count": len(plan["shots"]),
            "shot_id": shot["id"],
            "scene_prompt": shot.get("scene_prompt", shot["prompt"]),
            "prompt_prefix": str(plan.get("prompt_prefix") or ""),
            "seed": str(shot["seed"]),
            "video": video,
            "has_audio": False,
            "warning": ("Preparing synchronized audio preview…"
                        if audio is not None else no_audio_warning),
            "preview_pending": audio is not None,
            "preview_revision": 0,
            "play_notification_sound": bool(play_notification_sound),
            "unload_models_while_waiting": bool(unload_models_while_waiting),
            "assemble_partial_on_stop": bool(assemble_partial_on_stop),
            "timeout_seconds": timeout_seconds,
            "deadline": deadline,
            "server_now": server_now,
        }
        _PENDING_REVIEWS[token] = {
            "future": future,
            "loop": loop,
            "public": payload,
            "current_seed": int(shot["seed"]),
        }
        PromptServer.instance.send_sync(
            "minimax_h3_context_loop_review", dict(payload),
            PromptServer.instance.client_id)

        if audio is not None:
            # Keep tensor-to-WAV conversion on Comfy's execution thread. Some
            # PyTorch builds can deadlock when their CPU tensor pools are first
            # entered from asyncio.to_thread. The token is already public, and
            # The external ffmpeg path is time-bounded, and either media backend
            # can fail into a silent review instead of an unresolvable workflow
            # hang.
            try:
                video, has_audio, warning = _review_video(plan, segment, audio)
            except Exception as exc:
                _LOG.exception("H3 Chain synchronized review preview failed")
                has_audio = False
                warning = (
                    "Synchronized review audio is unavailable (%s). The saved "
                    "segment/checkpoint is valid; this review is silent." % exc)
            payload.update({
                "video": video,
                "has_audio": has_audio,
                "warning": warning,
                "preview_pending": False,
                "preview_revision": 1,
                "server_now": time.time(),
            })
            PromptServer.instance.send_sync(
                "minimax_h3_context_loop_review", dict(payload),
                PromptServer.instance.client_id)

        if unload_models_while_waiting:
            try:
                import comfy.model_management as model_management
                model_management.unload_all_models()
            except Exception as exc:
                _LOG.warning("H3 Chain Review could not unload models: %s", exc)

        try:
            decision = await _await_review_decision(future, timeout_seconds)
        finally:
            _PENDING_REVIEWS.pop(token, None)
            if not future.done():
                future.cancel()

        action = decision["action"]
        if action == "approve":
            timed_out = bool(decision.get("timed_out"))
            status = (("review timed out; auto-approved clip %d/%d; continuing")
                      if timed_out else ("approved clip %d/%d; continuing")) % (
                          index, len(plan["shots"]))
            if timed_out:
                PromptServer.instance.send_sync(
                    "minimax_h3_context_loop_review_resolved",
                    {"token": token, "node_id": payload["node_id"],
                     "action": "timeout_approve", "status": status},
                    PromptServer.instance.client_id)
            return {"ui": {"text": [status]}, "result": (segment, status)}
        if action == "stop":
            if ExecutionBlocker is None:
                raise RuntimeError("This ComfyUI build does not support review blocking.")
            status = "approved clip %d and stopped at its checkpoint" % index
            partial_item = None
            if assemble_partial_on_stop:
                try:
                    partial_path, partial_warning = _assemble_review_partial(
                        state, segment, partial_audio_source, source_audio)
                    partial_item = _video_output_item(partial_path)
                    status += "; partial video: %s" % partial_path
                    if partial_warning:
                        status += "; %s" % partial_warning
                except Exception as exc:
                    _LOG.exception("H3 Chain partial stop assembly failed")
                    status += "; partial assembly failed: %s" % exc
            resolved = {
                "token": token,
                "node_id": payload["node_id"],
                "action": "stop",
                "status": status,
            }
            if partial_item is not None:
                resolved["partial_video"] = partial_item
            PromptServer.instance.send_sync(
                "minimax_h3_context_loop_review_resolved", resolved,
                PromptServer.instance.client_id)
            return {
                "ui": {"text": [status]},
                "result": (ExecutionBlocker(None), status),
            }
        if action != "retry":
            raise RuntimeError("Unknown H3 review decision %r." % action)

        revised_segment = dict(segment)
        revised_segment["_h3_review_decision"] = {
            "action": "retry",
            "scene_prompt": decision["scene_prompt"],
            "seed": int(decision["seed"]),
        }
        status = "retrying clip %d with seed %d" % (
            index, int(decision["seed"]))
        return {"ui": {"text": [status]},
                "result": (revised_segment, status)}


def _manifest_from_segments(plan: dict[str, Any], values: list[dict[str, Any]],
                            complete: bool) -> dict[str, Any]:
    segments = []
    archives = _available_run_archives(plan)
    for item in values:
        segment = _public_segment(item)
        index = int(segment.get("index", -1))
        if 1 <= index <= len(plan["shots"]):
            for key, value in _prompt_fields(plan, index).items():
                segment.setdefault(key, value)
        if archives:
            segment.setdefault("archives", archives)
        segments.append(segment)
    expected_count = len(plan["shots"]) if complete else len(segments)
    if expected_count < 1:
        raise ValueError("H3 chain manifest requires at least one saved clip.")
    if len(segments) != expected_count:
        raise ValueError(
            "H3 chain manifest is incomplete: found %d persisted clips, expected %d."
            % (len(segments), expected_count))
    indexes = [int(item.get("index", -1)) for item in segments]
    if indexes != list(range(1, expected_count + 1)):
        raise ValueError("H3 chain manifest segment indexes are not contiguous.")
    total_frames = int(plan["total_delivered_frames"]) if complete else sum(
        int(item.get(
            "delivered_frames",
            plan["shots"][int(item["index"]) - 1]["delivered_frames"]))
        for item in segments)
    manifest = {
        "format": ("h3_chain_manifest_v3" if complete
                   else "h3_chain_partial_manifest_v3"),
        "run_name": plan["run_name"],
        "plan_hash": plan["plan_hash"],
        "prompt_prefix": str(plan.get("prompt_prefix") or ""),
        "compatibility": plan["compatibility"],
        "clip_count": expected_count,
        "total_delivered_frames": total_frames,
        "duration_seconds": total_frames / float(FPS),
        "segments": segments,
    }
    if archives:
        manifest["archives"] = archives
    if isinstance(plan.get("prelude"), dict):
        manifest["prelude"] = _json_document(plan["prelude"])
    if not complete:
        manifest["planned_clip_count"] = len(plan["shots"])
        manifest["last_completed_clip"] = len(segments)
    return manifest


def _manifest_from_state(state: dict[str, Any]) -> dict[str, Any]:
    return _manifest_from_segments(state["plan"], state["segments"], True)


def _partial_manifest(state: dict[str, Any],
                      segment: dict[str, Any]) -> dict[str, Any]:
    plan = state["plan"]
    index = int(state["index"])
    values = list(state.get("segments", [])) + [_public_segment(segment)]
    if index != len(values):
        raise ValueError(
            "H3 partial manifest expected clip %d after %d predecessors." %
            (index, len(values) - 1))
    return _manifest_from_segments(plan, values, False)


def _manifest_path(plan: dict[str, Any]) -> str:
    return os.path.join(_run_dir(plan), "manifest.json")


class MiniMaxH3ChainLoopEnd:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "flow": (FLOW_TYPE, {
                    "rawLink": True,
                    "tooltip": "Connect DIRECTLY from Loop Start's flow "
                               "output. This raw link defines the recursive body "
                               "that Loop End clones for later scenes."}),
                "state": (STATE_TYPE, {
                    "tooltip": "Current state from Current Shot. Loop End adds "
                               "the accepted segment and advances its scene "
                               "index."}),
                "images": ("IMAGE", {
                    "tooltip": "Delivered current-scene images after Motion "
                               "Context Trim. Their tail becomes the next "
                               "scene's visual context."}),
                "sampled_latent": ("LATENT", {
                    "tooltip": "Current sampler output. Its AV streams become "
                               "the next scene's generated-audio context when "
                               "the selected audio mode requires it."}),
                "segment": (SEGMENT_TYPE, {
                    "tooltip": "Approved persisted segment from Review Gate, "
                               "or directly from Segment Save when no review is "
                               "wanted."}),
            },
            "hidden": {
                "dynprompt": "DYNPROMPT",
                "unique_id": "UNIQUE_ID",
            },
        }

    RETURN_TYPES = (MANIFEST_TYPE, "STRING", "IMAGE", "LATENT")
    RETURN_NAMES = ("manifest", "manifest_json", "last_context_frames",
                    "last_context_latent")
    OUTPUT_TOOLTIPS = (
        "Completed chain manifest for H3 Chain Assemble. Produced only when "
        "the final scene is accepted.",
        "Human-readable JSON form of the completed manifest.",
        "Delivered tail frames from the final scene for optional chaining into "
        "another workflow.",
        "Final sampled H3 AV latent for optional continuation outside this loop.",
    )
    FUNCTION = "end"
    CATEGORY = "conditioning/minimax/contex_loop"
    DESCRIPTION = ("Finish one persisted clip, carry only its context tail and "
                   "AV latent, then recursively execute the next shot.")

    def _explore_dependencies(self, node_id: str, dynprompt: Any,
                              upstream: dict[str, list[str]],
                              parent_ids: list[str]) -> None:
        node_info = dynprompt.get_node(node_id)
        for value in node_info.get("inputs", {}).values():
            if not is_link(value):
                continue
            parent_id = value[0]
            display_id = dynprompt.get_display_node_id(parent_id)
            display_node = dynprompt.get_node(display_id)
            if display_node["class_type"] != "MiniMaxH3ChainLoopEnd":
                parent_ids.append(display_id)
            if parent_id not in upstream:
                upstream[parent_id] = []
                self._explore_dependencies(parent_id, dynprompt, upstream,
                                           parent_ids)
            upstream[parent_id].append(node_id)

    def _explore_output_nodes(self, dynprompt: Any,
                              upstream: dict[str, list[str]],
                              parent_ids: list[str]) -> None:
        try:
            import nodes as comfy_nodes
            mappings = comfy_nodes.NODE_CLASS_MAPPINGS
        except Exception:
            return
        output_nodes: dict[str, Any] = {}
        for node_id, node in dynprompt.get_original_prompt().items():
            class_def = mappings.get(node.get("class_type"))
            if not class_def or not getattr(class_def, "OUTPUT_NODE", False):
                continue
            for value in node.get("inputs", {}).values():
                if is_link(value):
                    output_nodes[node_id] = value
        for parent_id in list(upstream):
            display_id = dynprompt.get_display_node_id(parent_id)
            for output_id, link in output_nodes.items():
                linked_id = link[0]
                if (linked_id in parent_ids and display_id == linked_id and
                        output_id not in upstream[parent_id]):
                    if "." in parent_id:
                        parts = parent_id.split(".")
                        parts[-1] = output_id
                        upstream[parent_id].append(".".join(parts))
                    else:
                        upstream[parent_id].append(output_id)

    def _collect_contained(self, node_id: str,
                           upstream: dict[str, list[str]],
                           contained: dict[str, bool]) -> None:
        for child_id in upstream.get(node_id, []):
            if child_id in contained:
                continue
            contained[child_id] = True
            self._collect_contained(child_id, upstream, contained)

    def _recurse(self, flow, next_state, dynprompt, unique_id):
        if GraphBuilder is None:
            raise RuntimeError("H3 Chain Loop requires ComfyUI GraphBuilder.")
        unique_id = str(unique_id)
        upstream: dict[str, list[str]] = {}
        parent_ids: list[str] = []
        self._explore_dependencies(unique_id, dynprompt, upstream, parent_ids)
        parent_ids = list(set(parent_ids))
        self._explore_output_nodes(dynprompt, upstream, parent_ids)

        open_node = str(flow[0])
        start_info = dynprompt.get_node(open_node)
        if start_info["class_type"] != "MiniMaxH3ChainLoopStart":
            raise ValueError("H3 Chain Loop End must receive flow from H3 Chain Loop Start.")
        contained: dict[str, bool] = {unique_id: True, open_node: True}
        self._collect_contained(open_node, upstream, contained)

        graph = GraphBuilder()
        for node_id in contained:
            original = dynprompt.get_node(node_id)
            clone_id = "Recurse" if node_id == unique_id else node_id
            node = graph.node(original["class_type"], clone_id)
            node.set_override_display_id(node_id)
        for node_id in contained:
            original = dynprompt.get_node(node_id)
            clone_id = "Recurse" if node_id == unique_id else node_id
            node = graph.lookup_node(clone_id)
            for key, value in original.get("inputs", {}).items():
                if is_link(value) and value[0] in contained:
                    parent = graph.lookup_node(value[0])
                    node.set_input(key, parent.out(value[1]))
                else:
                    node.set_input(key, value)
        graph.lookup_node(open_node).set_input("initial_state", next_state)
        # The imported source may contain thousands of decoded frames. Once
        # Loop Start has reduced it to typed state, recursive iterations must
        # not keep the adapter dependency alive or prepare the prelude again.
        if "external_context" in start_info.get("inputs", {}):
            graph.lookup_node(open_node).set_input("external_context", None)
        recurse = graph.lookup_node("Recurse")
        return {
            "result": tuple(recurse.out(index)
                            for index in range(len(self.RETURN_TYPES))),
            "expand": graph.finalize(),
        }

    def end(self, flow, state, images, sampled_latent, segment,
            dynprompt=None, unique_id=None):
        plan = state["plan"]
        index = int(state["index"])
        if int(segment.get("index", -1)) != index:
            raise ValueError("H3 Chain End received the wrong segment for clip %d."
                             % index)
        review = segment.get("_h3_review_decision")
        if isinstance(review, dict) and review.get("action") == "retry":
            revised_plan = _plan_with_review_revision(
                plan, index, review.get("scene_prompt", ""),
                int(review.get("seed", plan["shots"][index - 1]["seed"])))
            retry_state = dict(state)
            retry_state["plan"] = revised_plan
            # Keep the predecessor context and accepted segment list unchanged;
            # the just-saved rejected artifact is transactionally replaced by
            # Segment Save when this same index completes again.
            return self._recurse(flow, retry_state, dynprompt, unique_id)
        context_length = int(plan["compatibility"]["context_length"])
        next_state = {
            "plan": plan,
            "index": index + 1,
            "range_start": int(state.get("range_start", 1)),
            "end_clip": int(state.get("end_clip", len(plan["shots"]))),
            # clone: a tensor view would retain the entire decoded clip
            "previous_frames": _tensor_cpu_clone(images[-context_length:]),
            "previous_latent": _compact_latent(sampled_latent),
            "segments": list(state.get("segments", [])) +
                        [_public_segment(segment)],
            "resumed_from": state.get("resumed_from", 0),
        }
        end_clip = int(next_state["end_clip"])
        if index < end_clip:
            return self._recurse(flow, next_state, dynprompt, unique_id)

        complete = end_clip == len(plan["shots"])
        manifest = _manifest_from_segments(
            plan, next_state["segments"], complete=complete)
        # A normal chain has already created its run directory in Segment Save.
        # Keeping this conditional also permits lightweight/custom segment sinks
        # that deliberately do not use the disk-backed saver.
        if os.path.isdir(_run_dir(plan)):
            if complete:
                manifest_path = _manifest_path(plan)
            else:
                manifest_path = os.path.join(
                    _run_dir(plan), "partial",
                    "through_clip_%04d.manifest.json" % end_clip)
            _atomic_json(manifest_path, manifest)
        manifest_json = json.dumps(manifest, ensure_ascii=False, indent=2,
                                   sort_keys=True)
        return (manifest, manifest_json, next_state["previous_frames"],
                next_state["previous_latent"])


class MiniMaxH3ChainManifestLoad:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "plan": (PLAN_TYPE, {
                    "tooltip": "The same validated H3 Chain Plan used for the "
                               "original render. Plan and generation "
                               "fingerprints are checked against every saved "
                               "scene."}),
            },
            "optional": {
                "source_audio": ("AUDIO", {
                    "tooltip": "The original full source track when the plan "
                               "uses source_track or source_plus_timeline. Its "
                               "fingerprint must match the saved checkpoints."}),
                "external_context": (EXTERNAL_CONTEXT_TYPE, {
                    "tooltip": "Reconnect the same Existing Video Context used "
                               "for scene 1. Its tail fingerprint restores the "
                               "correct resume contract and its persisted "
                               "prelude remains available to Assemble."}),
            },
        }

    RETURN_TYPES = (MANIFEST_TYPE, "STRING", "STRING")
    RETURN_NAMES = ("manifest", "manifest_json", "status")
    OUTPUT_TOOLTIPS = (
        "Verified completed manifest reconstructed from saved scene "
        "checkpoints; connect to H3 Chain Assemble.",
        "Human-readable JSON form of the reconstructed manifest.",
        "Number of verified scenes and checkpoint directory used.",
    )
    FUNCTION = "load"
    CATEGORY = "conditioning/minimax/contex_loop"
    DESCRIPTION = ("Validate every saved clip and rebuild a completed chain "
                   "manifest without rerendering the final clip.")

    @classmethod
    def IS_CHANGED(cls, *args, **kwargs):
        return float("NaN")

    def load(self, plan, source_audio=None, external_context=None):
        prepared_plan = _plan_with_external_context(plan, external_context)
        prepared_plan = _plan_with_source_audio(prepared_plan, source_audio)
        completed = _load_resume_state(
            prepared_plan, len(prepared_plan["shots"]) + 1)
        manifest = _manifest_from_state(completed)
        _atomic_json(_manifest_path(prepared_plan), manifest)
        manifest_json = json.dumps(
            manifest, ensure_ascii=False, indent=2, sort_keys=True)
        status = "loaded and verified %d saved clips from %s" % (
            len(manifest["segments"]), _run_dir(prepared_plan))
        return (manifest, manifest_json, status)


def _generated_audio(manifest: dict[str, Any]) -> dict[str, Any]:
    if _st_load is None or torch is None:
        raise RuntimeError("Generated-audio assembly requires safetensors and torch.")
    waveforms = []
    sample_rate = None
    for segment in manifest["segments"]:
        checkpoint = _absolute_output_path(segment["checkpoint"])
        tensors = _st_load(checkpoint)
        if "delivered_audio" not in tensors:
            raise ValueError(
                "Checkpoint for clip %d has no delivered audio. Wire decoded "
                "audio through Trim and Segment Save." % segment["index"])
        current_rate = int(segment.get("sample_rate", 0))
        if current_rate <= 0:
            raise ValueError("Checkpoint for clip %d has no audio sample rate."
                             % segment["index"])
        if sample_rate is None:
            sample_rate = current_rate
        elif current_rate != sample_rate:
            raise ValueError("Generated segment audio sample rates do not match.")
        waveform = tensors["delivered_audio"]
        expected = int(round(
            int(segment["delivered_frames"]) / float(FPS) * current_rate))
        if int(waveform.shape[-1]) != expected:
            raise ValueError(
                "Checkpoint for clip %d has %d delivered audio samples; expected "
                "%d for %d frames." %
                (segment["index"], int(waveform.shape[-1]), expected,
                 int(segment["delivered_frames"])))
        waveforms.append(waveform)
    return {"waveform": torch.cat(waveforms, dim=-1),
            "sample_rate": int(sample_rate)}


def _validate_prelude(manifest: dict[str, Any]) -> dict[str, Any] | None:
    value = manifest.get("prelude")
    if value is None:
        return None
    if not isinstance(value, dict) or not bool(value.get("prepend")):
        raise ValueError("H3 chain manifest has an invalid prelude record.")
    frames = int(value.get("frame_count", 0))
    if frames < 1 or int(value.get("fps", 0)) != FPS:
        raise ValueError(
            "H3 chain prelude must contain at least one frame at %d fps." % FPS)
    compatibility = manifest.get("compatibility") or {}
    if (int(value.get("width", 0)) != int(compatibility.get("width", 0)) or
            int(value.get("height", 0)) !=
            int(compatibility.get("height", 0))):
        raise ValueError(
            "H3 chain prelude dimensions do not match generated segments.")
    video_value = value.get("video")
    expected_video_hash = str(value.get("video_sha256") or "")
    if not isinstance(video_value, str) or not expected_video_hash:
        raise ValueError("H3 chain prelude has no verified video artifact.")
    video_path = _absolute_output_path(video_value)
    if not os.path.isfile(video_path):
        raise FileNotFoundError("H3 chain prelude video is missing: %s" % video_path)
    if _file_sha256(video_path) != expected_video_hash:
        raise ValueError("H3 chain prelude video failed its SHA-256 integrity check.")
    audio_value = value.get("audio")
    if audio_value is not None:
        expected_audio_hash = str(value.get("audio_sha256") or "")
        if not isinstance(audio_value, str) or not expected_audio_hash:
            raise ValueError("H3 chain prelude has an unverified audio artifact.")
        audio_path = _absolute_output_path(audio_value)
        if not os.path.isfile(audio_path):
            raise FileNotFoundError(
                "H3 chain prelude audio is missing: %s" % audio_path)
        if _file_sha256(audio_path) != expected_audio_hash:
            raise ValueError(
                "H3 chain prelude audio failed its SHA-256 integrity check.")
    return value


def _prelude_audio(record: dict[str, Any]) -> dict[str, Any] | None:
    value = record.get("audio")
    if value is None:
        return None
    if _st_load is None:
        raise RuntimeError("safetensors is required to load H3 prelude audio.")
    tensors = _st_load(_absolute_output_path(value))
    waveform = tensors.get("waveform")
    if waveform is None:
        raise ValueError("H3 chain prelude audio contains no waveform tensor.")
    sample_rate = int(record.get("audio_sample_rate", 0))
    audio = {"waveform": waveform, "sample_rate": sample_rate}
    _validate_audio(audio, "H3 chain prelude audio",
                    expected_frames=int(record["frame_count"]))
    return audio


def _audio_with_prelude(
    audio: dict[str, Any],
    extension_frames: int,
    prelude: dict[str, Any],
) -> dict[str, Any]:
    waveform, sample_rate = _audio_waveform_3d(
        audio, "H3 extension assembly audio")
    channels = int(waveform.shape[1])
    extension_samples = int(round(
        int(extension_frames) / float(FPS) * sample_rate))
    normalized_extension = _resample_audio_exact(
        {"waveform": waveform, "sample_rate": sample_rate},
        sample_rate, extension_samples, channels,
        "H3 extension assembly audio")
    prelude_samples = int(round(
        int(prelude["frame_count"]) / float(FPS) * sample_rate))
    saved = _prelude_audio(prelude)
    if saved is None:
        prefix = torch.zeros(
            (1, channels, prelude_samples), dtype=torch.float32)
    else:
        prefix = _resample_audio_exact(
            saved, sample_rate, prelude_samples, channels,
            "H3 chain prelude audio")["waveform"]
    return {
        "waveform": torch.cat(
            (prefix, normalized_extension["waveform"]), dim=-1),
        "sample_rate": sample_rate,
    }


def _validate_manifest(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    segments = manifest.get("segments") or []
    clip_count = int(manifest.get("clip_count", 0))
    if clip_count < 1 or len(segments) != clip_count:
        raise ValueError(
            "H3 chain manifest contains %d segments; expected %d." %
            (len(segments), clip_count))
    total_frames = 0
    for index, segment in enumerate(segments, start=1):
        _verify_segment_artifacts(segment, index)
        total_frames += int(segment.get("delivered_frames", 0))
    expected_frames = int(manifest.get("total_delivered_frames", -1))
    if total_frames != expected_frames:
        raise ValueError(
            "H3 chain manifest segment durations total %d frames; expected %d."
            % (total_frames, expected_frames))
    return segments


def _run_ffmpeg(command: list[str], timeout_seconds: float | None = None) -> None:
    try:
        # ffmpeg writes UTF-8. text=True alone decodes with the locale's
        # preferred encoding, which on a non-UTF-8 Windows console (cp932,
        # cp1251, ...) raises UnicodeDecodeError inside subprocess's reader
        # threads. Those threads die, result.stderr comes back truncated or
        # empty, and a genuine ffmpeg failure below reports no reason at all.
        # Decode as UTF-8 and never let diagnostics be the thing that fails.
        result = subprocess.run(
            command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            encoding="utf-8", errors="replace", timeout=timeout_seconds)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            "ffmpeg timed out after %.1f seconds" % float(timeout_seconds)) from exc
    if result.returncode:
        tail = "\n".join(result.stderr.splitlines()[-20:])
        raise RuntimeError("ffmpeg failed (%d):\n%s" % (result.returncode, tail))


def _pyav_video_signature(stream: Any) -> tuple[Any, ...]:
    codec = stream.codec_context
    return (
        str(codec.name or ""),
        int(codec.width),
        int(codec.height),
        str(codec.format.name if codec.format is not None else ""),
    )


def _pyav_shift_packet(packet: Any, stream: Any,
                        offset_seconds: Fraction) -> None:
    """Move one remuxed segment packet onto the joined video timeline."""
    time_base = packet.time_base or stream.time_base
    if time_base is None:
        raise RuntimeError(
            "PyAV could not determine an H3 segment video time base.")
    time_base = Fraction(time_base)
    start_time = int(stream.start_time or 0)
    start_seconds = Fraction(start_time) * Fraction(stream.time_base)
    shift = round((offset_seconds - start_seconds) / time_base)
    if packet.pts is not None:
        packet.pts = int(packet.pts) + shift
    if packet.dts is not None:
        packet.dts = int(packet.dts) + shift


def _pyav_concat_video(segment_paths: list[str], delivered_frames: list[int],
                        path: str, metadata: dict[str, Any]) -> None:
    """Stream-copy compatible H.264 segments without an ffmpeg executable."""
    if av is None:
        raise RuntimeError(
            "H3 Chain Assemble found neither an ffmpeg executable nor PyAV.")
    if len(segment_paths) != len(delivered_frames) or not segment_paths:
        raise ValueError("PyAV H3 assembly requires one duration per segment.")

    output = None
    try:
        output = av.open(
            path, mode="w",
            options={"movflags": "use_metadata_tags+faststart"})
        for key, value in metadata.items():
            if value is not None:
                output.metadata[str(key)] = str(value)

        output_stream = None
        expected_signature = None
        frame_offset = 0
        for index, (source, frames) in enumerate(
                zip(segment_paths, delivered_frames), start=1):
            with av.open(source, mode="r") as current:
                streams = list(current.streams.video)
                if len(streams) != 1:
                    raise ValueError(
                        "H3 chain clip %d contains %d video streams; expected 1."
                        % (index, len(streams)))
                input_stream = streams[0]
                signature = _pyav_video_signature(input_stream)
                if output_stream is None:
                    output_stream = output.add_stream_from_template(input_stream)
                    expected_signature = signature
                elif signature != expected_signature:
                    raise ValueError(
                        "H3 chain clip %d has incompatible video parameters %r; "
                        "the first clip uses %r." %
                        (index, signature, expected_signature))

                offset = Fraction(frame_offset, FPS)
                for packet in current.demux(input_stream):
                    if packet.dts is None:
                        continue
                    _pyav_shift_packet(packet, input_stream, offset)
                    packet.stream = output_stream
                    output.mux(packet)
            frame_offset += int(frames)
        output.close()
        output = None
    except Exception:
        if output is not None:
            output.close()
        _safe_unlink(path)
        raise


def _pyav_mux_audio(video_path: str, audio: dict[str, Any], path: str,
                     bitrate_kbps: int, total_frames: int) -> None:
    """Stream-copy joined video and encode frame-locked AAC through PyAV."""
    if av is None or torch is None:
        raise RuntimeError("PyAV H3 audio muxing requires PyAV and torch.")
    waveform, sample_rate = _validate_audio(
        audio, "PyAV H3 Chain Assemble audio")
    if waveform.ndim == 3:
        waveform = waveform[0]
    elif waveform.ndim == 1:
        waveform = waveform.unsqueeze(0)
    if waveform.ndim != 2:
        raise ValueError("H3 chain audio must be [batch,channels,samples].")
    channels = int(waveform.shape[0])
    if channels not in (1, 2):
        raise ValueError(
            "PyAV H3 assembly supports mono or stereo audio; got %d channels."
            % channels)
    required_samples = int(round(
        int(total_frames) / float(FPS) * sample_rate))
    if int(waveform.shape[-1]) < required_samples:
        raise ValueError(
            "PyAV H3 assembly audio contains %d samples; %d are required."
            % (int(waveform.shape[-1]), required_samples))
    waveform = (torch.clamp(waveform[..., :required_samples], -1.0, 1.0)
                .to(device="cpu", dtype=torch.float32).contiguous().numpy())
    layout = "mono" if channels == 1 else "stereo"

    source = output = None
    try:
        source = av.open(video_path, mode="r")
        streams = list(source.streams.video)
        if len(streams) != 1:
            raise ValueError(
                "Joined H3 video contains %d video streams; expected 1."
                % len(streams))
        input_video = streams[0]
        output = av.open(
            path, mode="w",
            options={"movflags": "use_metadata_tags+faststart"})
        for key, value in source.metadata.items():
            output.metadata[str(key)] = str(value)
        output_video = output.add_stream_from_template(input_video)
        output_audio = output.add_stream("aac", rate=sample_rate)
        output_audio.bit_rate = int(bitrate_kbps) * 1000
        output_audio.layout = layout

        for packet in source.demux(input_video):
            if packet.dts is None:
                continue
            packet.stream = output_video
            output.mux(packet)

        chunk_size = 1024
        for start in range(0, required_samples, chunk_size):
            stop = min(required_samples, start + chunk_size)
            frame = av.AudioFrame.from_ndarray(
                waveform[:, start:stop], format="fltp", layout=layout)
            frame.sample_rate = sample_rate
            frame.pts = start
            frame.time_base = Fraction(1, sample_rate)
            for packet in output_audio.encode(frame):
                output.mux(packet)
        for packet in output_audio.encode():
            output.mux(packet)

        output.close()
        output = None
        source.close()
        source = None
    except Exception:
        if output is not None:
            output.close()
        if source is not None:
            source.close()
        _safe_unlink(path)
        raise


def _write_ffmetadata(path: str, metadata: dict[str, Any]) -> None:
    def escape(value: Any) -> str:
        text = str(value).replace("\\", "\\\\")
        for character in ("=", ";", "#"):
            text = text.replace(character, "\\" + character)
        return text.replace("\n", "\\\n")

    lines = [";FFMETADATA1"]
    lines.extend("%s=%s" % (escape(key), escape(value))
                 for key, value in metadata.items() if value is not None)
    _atomic_text(path, "\n".join(lines) + "\n")


def _manifest_media_metadata(manifest: dict[str, Any]) -> dict[str, str]:
    metadata = _archive_media_metadata(manifest.get("archives"))
    metadata.update({
        "title": "MiniMax H3 chain - %s" % manifest.get("run_name", "h3_chain"),
        "comment": "%d H3 scenes; prompts and recovery workflow embedded" %
                   int(manifest.get("clip_count", 0)),
        "h3_manifest": json.dumps(
            manifest, ensure_ascii=False, separators=(",", ":")),
    })
    return metadata


def _checkpoint_export_segments(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    segments = manifest.get("segments") or []
    clip_count = int(manifest.get("clip_count", 0))
    if clip_count < 1 or len(segments) != clip_count:
        raise ValueError(
            "H3 PNG export manifest contains %d segments; expected %d." %
            (len(segments), clip_count))
    delivered_total = 0
    for expected_index, segment in enumerate(segments, start=1):
        if int(segment.get("index", -1)) != expected_index:
            raise ValueError(
                "H3 PNG export requires contiguous segment indexes starting "
                "at 1; expected clip %d." % expected_index)
        checkpoint_value = segment.get("checkpoint")
        if not isinstance(checkpoint_value, str):
            raise ValueError(
                "H3 PNG export clip %d has no checkpoint path." % expected_index)
        checkpoint = _absolute_output_path(checkpoint_value)
        if not os.path.isfile(checkpoint):
            raise FileNotFoundError(
                "H3 PNG export checkpoint is missing: %s" % checkpoint)
        expected_hash = str(segment.get("checkpoint_sha256") or "")
        if expected_hash and _file_sha256(checkpoint) != expected_hash:
            raise ValueError(
                "H3 PNG export clip %d checkpoint failed its SHA-256 integrity "
                "check." % expected_index)
        raw_frames = int(segment.get("raw_frames", 0))
        delivered_frames = int(segment.get("delivered_frames", 0))
        if raw_frames < 1 or delivered_frames < 1 or delivered_frames > raw_frames:
            raise ValueError(
                "H3 PNG export clip %d has invalid raw/delivered frame counts "
                "%d/%d." % (expected_index, raw_frames, delivered_frames))
        delivered_total += delivered_frames
    expected_total = int(manifest.get("total_delivered_frames", -1))
    if delivered_total != expected_total:
        raise ValueError(
            "H3 PNG export segment durations total %d frames; expected %d." %
            (delivered_total, expected_total))
    return segments


def _new_export_directory(manifest: dict[str, Any], export_name: str) -> str:
    run_name = _safe_name(manifest.get("run_name"), "h3_chain")
    name = _safe_name(export_name, "png_sequence")
    base = os.path.abspath(os.path.join(
        _output_root(), "h3_chains", run_name, "frames", name))
    root = _output_root()
    if os.path.commonpath([root, base]) != root:
        raise ValueError("H3 PNG export path escapes the ComfyUI output directory.")
    for suffix in range(0, 10000):
        candidate = base if suffix == 0 else "%s_%04d" % (base, suffix + 1)
        try:
            os.makedirs(candidate, exist_ok=False)
            return candidate
        except FileExistsError:
            continue
    raise RuntimeError("H3 PNG export could not allocate a unique output folder.")


def _write_png(path: str, image: Any, compression: int,
               metadata: dict[str, Any]) -> None:
    if Image is None or PngImagePlugin is None or torch is None:
        raise RuntimeError("H3 PNG export requires Pillow and torch.")
    if not torch.is_tensor(image) or image.ndim != 3 or image.shape[-1] < 3:
        raise ValueError(
            "H3 PNG export expected one [height,width,channels] image; got %r." %
            (getattr(image, "shape", None),))
    pixels = (torch.clamp(image[..., :3], 0.0, 1.0) * 255.0)
    pixels = pixels.round().to(device="cpu", dtype=torch.uint8).numpy()
    pnginfo = PngImagePlugin.PngInfo()
    for key, value in metadata.items():
        if value is not None:
            pnginfo.add_text(str(key), str(value))
    temporary = "%s.%s.tmp" % (path, uuid.uuid4().hex)
    try:
        Image.fromarray(pixels).save(
            temporary, format="PNG", compress_level=int(compression),
            pnginfo=pnginfo)
        os.replace(temporary, path)
    finally:
        _safe_unlink(temporary)


class MiniMaxH3ChainExportPNG:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "manifest": (MANIFEST_TYPE, {
                    "tooltip": "Completed or partial manifest from Loop End or "
                               "Manifest Load. Checkpoint latents are decoded "
                               "scene by scene; the H.264 segments are not used."}),
                "video_vae": ("VAE", {
                    "tooltip": "The same MiniMax H3 video VAE used for the "
                               "original render. Decode precision and VAE "
                               "settings determine whether regenerated pixels "
                               "exactly match the first decode."}),
                "export_name": ("STRING", {
                    "default": "png_sequence",
                    "tooltip": "Folder name under output/h3_chains/<run>/frames. "
                               "An existing folder is never overwritten; a "
                               "numbered sibling is created automatically."}),
                "first_frame_number": ("INT", {
                    "default": 1, "min": 0, "max": 999999999,
                    "tooltip": "Number used by the first exported file. Frames "
                               "then continue across scene boundaries without "
                               "resetting."}),
                "png_compression": ("INT", {
                    "default": 4, "min": 0, "max": 9,
                    "tooltip": "Lossless PNG compression effort. 0 is fastest "
                               "and largest; 9 is slowest and smallest. It does "
                               "not change pixels."}),
                "embed_workflow": ("BOOLEAN", {
                    "default": True,
                    "tooltip": "Embed the archived ComfyUI workflow, API graph, "
                               "effective plan, and chain manifest in the first "
                               "PNG. Scene prompt metadata is embedded in the "
                               "first frame of every scene."}),
            },
        }

    RETURN_TYPES = ("STRING", "INT", "STRING")
    RETURN_NAMES = ("output_directory", "frame_count", "status")
    OUTPUT_TOOLTIPS = (
        "Absolute folder containing the continuous PNG sequence and export.json.",
        "Total number of delivered frames written across all decoded scenes.",
        "Export folder, scene count, frame count, and frame-number range.",
    )
    FUNCTION = "export"
    OUTPUT_NODE = True
    CATEGORY = "conditioning/minimax/contex_loop"
    DESCRIPTION = ("Re-decode every saved H3 video checkpoint with the selected "
                   "VAE, remove each scene's repeated context overlap, and write "
                   "a continuous lossless PNG sequence without retaining the "
                   "whole production in memory.")

    @classmethod
    def IS_CHANGED(cls, *args, **kwargs):
        return float("NaN")

    def export(self, manifest, video_vae, export_name, first_frame_number,
               png_compression, embed_workflow):
        if _st_load is None or torch is None:
            raise RuntimeError(
                "H3 PNG export requires safetensors and torch.")
        segments = _checkpoint_export_segments(manifest)
        output_dir = _new_export_directory(manifest, export_name)
        partial_path = os.path.join(output_dir, "export.partial.json")
        final_path = os.path.join(output_dir, "export.json")
        frame_number = int(first_frame_number)
        first_number = frame_number
        written = 0
        clip_records = []
        archive_metadata = (_archive_media_metadata(manifest.get("archives"))
                            if bool(embed_workflow) else {})
        manifest_metadata = json.dumps(
            manifest, ensure_ascii=False, separators=(",", ":"))

        for segment in segments:
            index = int(segment["index"])
            checkpoint = _absolute_output_path(segment["checkpoint"])
            tensors = _st_load(checkpoint)
            video = tensors.get("video")
            if video is None:
                raise ValueError(
                    "H3 PNG export checkpoint for clip %d has no video latent." %
                    index)
            images = video_vae.decode(video)
            if not torch.is_tensor(images):
                raise ValueError(
                    "H3 PNG export VAE returned %r instead of an image tensor." %
                    type(images))
            if images.ndim == 5:
                images = images.reshape(
                    -1, images.shape[-3], images.shape[-2], images.shape[-1])
            if images.ndim != 4:
                raise ValueError(
                    "H3 PNG export VAE returned image shape %s; expected "
                    "[frames,height,width,channels]." % (tuple(images.shape),))

            raw_frames = int(segment["raw_frames"])
            delivered_frames = int(segment["delivered_frames"])
            trim_frames = raw_frames - delivered_frames
            if int(images.shape[0]) != raw_frames:
                raise ValueError(
                    "H3 PNG export decoded %d frames for clip %d; its manifest "
                    "requires %d raw frames before trimming %d overlap frames." %
                    (int(images.shape[0]), index, raw_frames, trim_frames))
            images = images[trim_frames:trim_frames + delivered_frames]
            clip_first = frame_number
            prompt = str(segment.get("prompt") or "")
            scene_metadata = json.dumps({
                "index": index,
                "id": str(segment.get("id") or "clip_%04d" % index),
                "prompt_prefix": str(segment.get("prompt_prefix") or ""),
                "scene_prompt": str(segment.get("scene_prompt") or ""),
                "prompt": prompt,
                "prompt_hash": str(segment.get("prompt_hash") or ""),
                "seed": str(segment.get("seed") or ""),
                "raw_frames": raw_frames,
                "delivered_frames": delivered_frames,
                "trim_frames": trim_frames,
            }, ensure_ascii=False, separators=(",", ":"))

            for scene_frame, image in enumerate(images):
                filename = "frame_%08d.png" % frame_number
                png_metadata = {
                    "h3_run_name": str(manifest.get("run_name") or ""),
                    "h3_clip_index": str(index),
                    "h3_clip_frame": str(scene_frame + 1),
                    "h3_frame_number": str(frame_number),
                    "h3_prompt_hash": str(segment.get("prompt_hash") or ""),
                }
                if scene_frame == 0:
                    png_metadata["h3_scene"] = scene_metadata
                    png_metadata["h3_prompt"] = prompt
                if written == 0 and bool(embed_workflow):
                    png_metadata.update(archive_metadata)
                    png_metadata["h3_manifest"] = manifest_metadata
                _write_png(
                    os.path.join(output_dir, filename), image,
                    int(png_compression), png_metadata)
                frame_number += 1
                written += 1

            clip_records.append({
                "index": index,
                "id": str(segment.get("id") or "clip_%04d" % index),
                "checkpoint": segment["checkpoint"],
                "prompt": prompt,
                "prompt_hash": str(segment.get("prompt_hash") or ""),
                "seed": segment.get("seed"),
                "trim_frames": trim_frames,
                "delivered_frames": delivered_frames,
                "first_frame_number": clip_first,
                "last_frame_number": frame_number - 1,
            })
            progress = {
                "format": "h3_chain_png_export_v1",
                "complete": False,
                "run_name": manifest.get("run_name"),
                "source_manifest_format": manifest.get("format"),
                "first_frame_number": first_number,
                "frame_count": written,
                "clips": clip_records,
                "archives": manifest.get("archives", {}),
            }
            _atomic_json(partial_path, progress)
            del images, video, tensors

        export_record = {
            "format": "h3_chain_png_export_v1",
            "complete": True,
            "run_name": manifest.get("run_name"),
            "source_manifest_format": manifest.get("format"),
            "source_plan_hash": manifest.get("plan_hash"),
            "first_frame_number": first_number,
            "last_frame_number": frame_number - 1,
            "frame_count": written,
            "clips": clip_records,
            "archives": manifest.get("archives", {}),
        }
        _atomic_json(final_path, export_record)
        _safe_unlink(partial_path)
        status = ("exported %d clips / %d PNG frames (%d..%d) -> %s" %
                  (len(segments), written, first_number, frame_number - 1,
                   output_dir))
        _LOG.info("H3 Chain %s", status)
        return {"ui": {"text": [status]},
                "result": (output_dir, written, status)}


class MiniMaxH3ChainAssemble:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "manifest": (MANIFEST_TYPE, {
                    "tooltip": "Completed manifest from Loop End or Manifest "
                               "Load. Every segment file is verified before "
                               "joining."}),
                "audio_source": (["plan", "source", "generated", "none"],
                                 {
                                     "default": "plan",
                                     "tooltip": "plan follows the plan's audio "
                                                "mode; source muxes the external "
                                                "track; generated joins saved "
                                                "delivered scene audio; none "
                                                "creates a silent MP4."}),
                "filename": ("STRING", {
                    "default": "final",
                    "tooltip": "Final MP4 basename inside this chain's output "
                               "folder. The .mp4 extension is added "
                               "automatically."}),
                "audio_bitrate": ("INT", {
                    "default": 256, "min": 64, "max": 512,
                    "tooltip": "AAC bitrate in kilobits per second for the "
                               "final mux. It does not re-encode the saved H.264 "
                               "video segments."}),
            },
            "optional": {
                "source_audio": ("AUDIO", {
                    "tooltip": "Full original source track. Required when "
                               "audio_source resolves to source; it is trimmed "
                               "or safely silent-padded to the final duration."}),
            },
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("video_path",)
    OUTPUT_TOOLTIPS = (
        "Absolute path of the assembled final MP4.",
    )
    FUNCTION = "assemble"
    OUTPUT_NODE = True
    CATEGORY = "conditioning/minimax/contex_loop"
    DESCRIPTION = ("Stream-copy saved H3 segments into one MP4 and mux either "
                   "the original source track or checkpointed generated audio.")

    @classmethod
    def IS_CHANGED(cls, *args, **kwargs):
        return float("NaN")

    def assemble(self, manifest, audio_source, filename, audio_bitrate,
                 source_audio=None):
        segments = _validate_manifest(manifest)
        prelude = _validate_prelude(manifest)
        selected = audio_source
        if selected == "plan":
            mode = manifest["compatibility"]["audio_mode"]
            selected = ("source" if mode in
                        ("source_track", "source_plus_timeline")
                        else "generated")
        audio = None
        if selected == "source":
            _validate_source_audio_hash(
                manifest["compatibility"], source_audio,
                "H3 Chain Assemble")
            waveform, sample_rate = _validate_audio(
                source_audio, "H3 Chain Assemble source audio")
            required_samples = int(round(
                int(manifest["total_delivered_frames"]) /
                float(FPS) * sample_rate))
            if int(waveform.shape[-1]) < required_samples:
                if manifest["compatibility"].get(
                        "source_audio_silent_padding") and _audio_is_silent(waveform):
                    audio = _pad_audio_to_samples(
                        source_audio, required_samples,
                        "H3 Chain Assemble silent placeholder audio")
                else:
                    raise ValueError(
                        "H3 Chain Assemble source audio has %d samples; at least "
                        "%d are required for %d video frames." %
                        (int(waveform.shape[-1]), required_samples,
                         int(manifest["total_delivered_frames"])))
            else:
                audio = source_audio
        elif selected == "generated":
            audio = _generated_audio(manifest)
        elif selected != "none":
            raise ValueError("Unknown H3 chain assembly audio source %r."
                             % selected)
        extension_frames = int(manifest["total_delivered_frames"])
        prelude_frames = int(prelude["frame_count"]) if prelude is not None else 0
        total_output_frames = prelude_frames + extension_frames
        if audio is not None and prelude is not None:
            audio = _audio_with_prelude(audio, extension_frames, prelude)

        run_name = _safe_name(manifest.get("run_name"), "h3_chain")
        run_dir = os.path.join(_output_root(), "h3_chains", run_name)
        final_dir = os.path.join(run_dir, "final")
        os.makedirs(final_dir, exist_ok=True)
        final_name = _safe_name(filename, "final")
        final_path = os.path.join(final_dir, final_name + ".mp4")
        concat_path = os.path.join(final_dir, ".concat.txt")
        video_tmp = os.path.join(final_dir, ".video.tmp.mp4")
        final_tmp = os.path.join(final_dir, ".final.tmp.mp4")
        wav_tmp = os.path.join(final_dir, ".audio.tmp.wav")
        metadata_tmp = os.path.join(final_dir, ".metadata.tmp.txt")

        segment_paths = []
        delivered_frames = []
        if prelude is not None:
            segment_paths.append(_absolute_output_path(prelude["video"]))
            delivered_frames.append(prelude_frames)
        for item in segments:
            path = _absolute_output_path(item["segment"])
            if not os.path.isfile(path):
                raise FileNotFoundError("H3 chain segment is missing: %s" % path)
            segment_paths.append(path)
            delivered_frames.append(int(item["delivered_frames"]))
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg and av is None:
            raise RuntimeError(
                "H3 Chain Assemble found neither an ffmpeg executable nor "
                "PyAV. Install ffmpeg or restore ComfyUI's av package.")

        for temporary in (video_tmp, final_tmp, wav_tmp, metadata_tmp):
            if os.path.exists(temporary):
                os.unlink(temporary)
        backend = "ffmpeg"
        try:
            media_metadata = _manifest_media_metadata(manifest)
            if ffmpeg:
                with open(concat_path, "w", encoding="utf-8") as handle:
                    for path in segment_paths:
                        escaped = path.replace("\\", "\\\\").replace(
                            "'", "'\\''")
                        handle.write("file '%s'\n" % escaped)
                _write_ffmetadata(metadata_tmp, media_metadata)
                _run_ffmpeg([
                    ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i",
                    concat_path, "-f", "ffmetadata", "-i", metadata_tmp,
                    "-map", "0:v:0", "-map_metadata", "1", "-c", "copy",
                    "-movflags", "use_metadata_tags+faststart", video_tmp,
                ])
            else:
                backend = "PyAV fallback"
                _LOG.warning(
                    "H3 Chain ffmpeg executable not found; assembling with "
                    "the built-in PyAV stream-copy fallback")
                _pyav_concat_video(
                    segment_paths, delivered_frames, video_tmp, media_metadata)

            if audio is None:
                os.replace(video_tmp, final_tmp)
            elif ffmpeg:
                _write_wav(audio, wav_tmp)
                _run_ffmpeg([
                    ffmpeg, "-y", "-i", video_tmp, "-i", wav_tmp,
                    "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy",
                    "-c:a", "aac", "-b:a", "%dk" % int(audio_bitrate),
                    "-t", "%.9f" % (total_output_frames / float(FPS)),
                    "-map_metadata", "0",
                    "-movflags", "use_metadata_tags+faststart", final_tmp,
                ])
            else:
                _pyav_mux_audio(
                    video_tmp, audio, final_tmp, int(audio_bitrate),
                    total_output_frames)
            os.replace(final_tmp, final_path)
        finally:
            for temporary in (concat_path, video_tmp, final_tmp, wav_tmp,
                              metadata_tmp):
                if os.path.exists(temporary):
                    os.unlink(temporary)

        status = "assembled %d generated clips%s with %s -> %s" % (
            len(segments), " + existing-video prelude" if prelude else "",
            backend, final_path)
        _LOG.info("H3 Chain %s", status)
        return {"ui": {"text": [status]}, "result": (final_path,)}


def _assemble_review_partial(
    state: dict[str, Any],
    segment: dict[str, Any],
    audio_source: str,
    source_audio: dict[str, Any] | None,
) -> tuple[str, str]:
    manifest = _partial_manifest(state, segment)
    index = int(segment["index"])
    partial_dir = os.path.join(_run_dir(state["plan"]), "partial")
    manifest_path = os.path.join(
        partial_dir, "through_clip_%04d.manifest.json" % index)
    _atomic_json(manifest_path, manifest)

    selected = {
        "checkpointed": "generated",
        "source": "source",
        "none": "none",
    }.get(str(audio_source))
    if selected is None:
        raise ValueError("Unknown H3 partial audio source %r." % audio_source)

    assembler = MiniMaxH3ChainAssemble()
    filename = "partial_through_clip_%04d" % index
    warning = ""
    try:
        result = assembler.assemble(
            manifest, selected, filename, 192, source_audio)
    except Exception as audio_error:
        if selected == "none":
            raise
        _LOG.warning(
            "H3 Chain partial audio assembly failed; saving silent video: %s",
            audio_error)
        result = assembler.assemble(
            manifest, "none", filename, 192, source_audio)
        warning = "audio unavailable, so the partial video is silent (%s)" % audio_error
    return str(result["result"][0]), warning


async def _submit_review_decision(request):
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Expected a JSON request body."},
                                 status=400)
    token = str(body.get("token") or "")
    pending = _PENDING_REVIEWS.get(token)
    if pending is None:
        return web.json_response(
            {"error": "This H3 review is no longer pending."}, status=404)
    future = pending["future"]
    if future.done():
        return web.json_response(
            {"error": "This H3 review already has a decision."}, status=409)

    action = str(body.get("action") or "")
    if action not in ("approve", "retry", "reroll", "stop"):
        return web.json_response({"error": "Unknown review action."}, status=400)

    decision: dict[str, Any] = {"action": action}
    if action in ("retry", "reroll"):
        scene_prompt = str(body.get("scene_prompt") or "").strip()
        prompt_prefix = str(
            pending.get("public", {}).get("prompt_prefix") or "").strip()
        if not scene_prompt and not prompt_prefix:
            return web.json_response(
                {"error": "Retry requires a scene prompt or shared prompt."},
                status=400)
        if len(scene_prompt) > 200000:
            return web.json_response(
                {"error": "The retry prompt is too large."}, status=400)
        if action == "reroll":
            seed = secrets.randbits(64)
            while seed == int(pending["current_seed"]):
                seed = secrets.randbits(64)
        else:
            try:
                seed = int(str(body.get("seed")))
            except (TypeError, ValueError):
                return web.json_response(
                    {"error": "The retry seed must be an integer."}, status=400)
            if seed < 0 or seed > MAX_SEED:
                return web.json_response(
                    {"error": "The retry seed is outside the uint64 range."},
                    status=400)
        decision = {
            "action": "retry",
            "scene_prompt": scene_prompt,
            "seed": seed,
        }

    def resolve_on_execution_loop():
        if not future.done():
            future.set_result(decision)

    try:
        pending["loop"].call_soon_threadsafe(resolve_on_execution_loop)
    except RuntimeError:
        return web.json_response(
            {"error": "This H3 review execution loop is no longer running."},
            status=409)
    return web.json_response({
        "ok": True,
        "action": decision["action"],
        "seed": str(decision.get("seed", pending["current_seed"])),
    })


async def _list_pending_reviews(_request):
    reviews = []
    # HTTP and execution can run on different threads/loops. Snapshot first so
    # a review resolving during recovery cannot invalidate this iteration and
    # turn a browser's reconnect GET into an intermittent 500 response.
    for item in list(_PENDING_REVIEWS.values()):
        if item["future"].done():
            continue
        payload = dict(item["public"])
        payload["server_now"] = time.time()
        reviews.append(payload)
    return web.json_response({"reviews": reviews})


async def _list_saved_checkpoints(request):
    run_name = _safe_name(request.query.get("run_name", ""), "")
    if not run_name:
        return web.json_response(
            {"error": "A non-empty H3 chain run_name is required."}, status=400)
    checkpoint_dir = os.path.join(
        _output_root(), "h3_chains", run_name, "checkpoints")
    checkpoints = []
    if os.path.isdir(checkpoint_dir):
        for filename in sorted(os.listdir(checkpoint_dir)):
            match = re.fullmatch(r"clip_(\d{4})\.json", filename)
            if match is None:
                continue
            try:
                metadata = _read_json(os.path.join(checkpoint_dir, filename))
                segment = metadata.get("segment")
                if not isinstance(segment, dict):
                    continue
                index = int(segment.get("index", int(match.group(1))))
                if index != int(match.group(1)):
                    continue
                segment_path = _absolute_output_path(segment["segment"])
                checkpoint_path = _absolute_output_path(segment["checkpoint"])
                ready = (os.path.isfile(segment_path) and
                         os.path.isfile(checkpoint_path))
                item = {
                    "scene": index,
                    "scene_id": str(segment.get("id") or "clip_%04d" % index),
                    "resume_scene": index + 1,
                    "ready": ready,
                }
                if os.path.isfile(segment_path):
                    item["video"] = _video_output_item(segment_path)
                partial_path = os.path.join(
                    _output_root(), "h3_chains", run_name, "final",
                    "partial_through_clip_%04d.mp4" % index)
                if os.path.isfile(partial_path):
                    item["partial_video"] = _video_output_item(partial_path)
                checkpoints.append(item)
            except (OSError, TypeError, ValueError, json.JSONDecodeError,
                    KeyError):
                continue
    return web.json_response({
        "run_name": run_name,
        "checkpoints": checkpoints,
    })


if (PromptServer is not None and web is not None and
        getattr(PromptServer, "instance", None) is not None):
    PromptServer.instance.routes.post(
        "/minimax_h3_context_loop/review")(_submit_review_decision)
    PromptServer.instance.routes.get(
        "/minimax_h3_context_loop/reviews")(_list_pending_reviews)
    PromptServer.instance.routes.get(
        "/minimax_h3_context_loop/checkpoints")(_list_saved_checkpoints)


CHAIN_NODE_CLASS_MAPPINGS = {
    "MiniMaxH3ChainPlan": MiniMaxH3ChainPlan,
    "MiniMaxH3ChainScenePromptEditor": MiniMaxH3ChainScenePromptEditor,
    "MiniMaxH3ReferenceVideoPrepare": MiniMaxH3ReferenceVideoPrepare,
    "MiniMaxH3ChainExternalVideo": MiniMaxH3ChainExternalVideo,
    "MiniMaxH3ChainLoopStart": MiniMaxH3ChainLoopStart,
    "MiniMaxH3ChainCurrent": MiniMaxH3ChainCurrent,
    "MiniMaxH3ChainContext": MiniMaxH3ChainContext,
    "MiniMaxH3ChainSegmentSave": MiniMaxH3ChainSegmentSave,
    "MiniMaxH3ChainReview": MiniMaxH3ChainReview,
    "MiniMaxH3ChainLoopEnd": MiniMaxH3ChainLoopEnd,
    "MiniMaxH3ChainManifestLoad": MiniMaxH3ChainManifestLoad,
    "MiniMaxH3ChainExportPNG": MiniMaxH3ChainExportPNG,
    "MiniMaxH3ChainAssemble": MiniMaxH3ChainAssemble,
}

CHAIN_NODE_DISPLAY_NAME_MAPPINGS = {
    "MiniMaxH3ChainPlan": "MiniMax H3 Contex Loop Plan",
    "MiniMaxH3ChainScenePromptEditor": "MiniMax H3 Scene Prompt Editor",
    "MiniMaxH3ReferenceVideoPrepare": "MiniMax H3 Reference Video Prep",
    "MiniMaxH3ChainExternalVideo": "MiniMax H3 Existing Video Context",
    "MiniMaxH3ChainLoopStart": "MiniMax H3 Contex Loop Start",
    "MiniMaxH3ChainCurrent": "MiniMax H3 Contex Loop Current Shot",
    "MiniMaxH3ChainContext": "MiniMax H3 Contex Loop Context",
    "MiniMaxH3ChainSegmentSave": "MiniMax H3 Contex Loop Segment + Checkpoint",
    "MiniMaxH3ChainReview": "MiniMax H3 Contex Loop Review Gate",
    "MiniMaxH3ChainLoopEnd": "MiniMax H3 Contex Loop End",
    "MiniMaxH3ChainManifestLoad": "MiniMax H3 Contex Loop Load Manifest",
    "MiniMaxH3ChainExportPNG": "MiniMax H3 Contex Loop Export PNG Sequence",
    "MiniMaxH3ChainAssemble": "MiniMax H3 Contex Loop Assemble",
}
