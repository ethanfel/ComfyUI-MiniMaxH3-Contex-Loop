"""Masked target-prefix continuation for recursive MiniMax H3 chains.

Generated scenes continue directly from the previous sampled H3 video/audio
latent tails, avoiding a lossy video decode/re-encode round trip.  Imported
scene-1 video and audio still use their respective VAEs because no sampled H3
latent exists yet.  A nested AV denoise mask protects the copied prefix while
the sampler generates only the future portion.

The mask design follows ComfyUI PR #15375 and seitanism's GPL-3.0
ComfyUI-H3-Motion-Context-MultiRef masked-extension work.  Runtime support is
enabled lazily so ordinary guide-mode chains do not patch H3 mask handling.
"""

from __future__ import annotations

import logging
import math

import torch

from .contracts_v05 import CONTEXT_SPATIAL_PROXY_RECIPE, DETAIL_AV_RECIPE
from .nodes import (
    AV_RUN_GRID,
    AUDIO_HZ,
    FPS,
    VIDEO_RUN_GRID,
    _audio_tail_from_latent,
    _pixel_frames,
    _resize,
    _streams_from_latent,
)


_LOG = logging.getLogger("minimax_h3_context_loop.masked_prefix")


def _latent_context_spatial_proxy(video_prefix):
    """Low-pass a copied AV prefix through the fixed 5/6 latent canvas.

    Time, channels, dtype, device, and final target geometry are unchanged.
    Only this disposable copy is filtered; the predecessor checkpoint remains
    byte-for-byte untouched.
    """
    if not torch.is_tensor(video_prefix) or video_prefix.ndim != 5:
        raise ValueError(
            "h3_context_spatial_proxy: video prefix must be "
            "[B,C,T,H,W], got %s." %
            (tuple(getattr(video_prefix, "shape", ())),))
    if not video_prefix.is_floating_point():
        raise ValueError(
            "h3_context_spatial_proxy: video prefix must be floating point.")

    batch, channels, steps, latent_height, latent_width = (
        int(value) for value in video_prefix.shape)
    alignment = int(CONTEXT_SPATIAL_PROXY_RECIPE["pixel_alignment"])
    numerator = int(CONTEXT_SPATIAL_PROXY_RECIPE["scale_numerator"])
    denominator = int(CONTEXT_SPATIAL_PROXY_RECIPE["scale_denominator"])

    def proxy_latent_size(value):
        pixels = int(value) * 16
        units = max(1, int(round(
            pixels * numerator / float(denominator * alignment))))
        return max(1, units * alignment // 16)

    proxy_height = proxy_latent_size(latent_height)
    proxy_width = proxy_latent_size(latent_width)
    if (proxy_height, proxy_width) == (latent_height, latent_width):
        return video_prefix.detach().contiguous().clone(), (
            proxy_height, proxy_width)

    source = video_prefix.permute(0, 2, 1, 3, 4).reshape(
        batch * steps, channels, latent_height, latent_width)
    work = source.float()
    reduced = torch.nn.functional.interpolate(
        work, size=(proxy_height, proxy_width), mode="area")
    restored = torch.nn.functional.interpolate(
        reduced, size=(latent_height, latent_width), mode="bilinear",
        align_corners=False)
    restored = restored.to(
        device=video_prefix.device, dtype=video_prefix.dtype)
    restored = restored.reshape(
        batch, steps, channels, latent_height, latent_width).permute(
            0, 2, 1, 3, 4).contiguous()
    return restored, (proxy_height, proxy_width)


def _detail_av_alpha(position, step_count):
    """Return the latent-noise amount for one carried video step."""
    position = int(position)
    step_count = int(step_count)
    if step_count < 1 or position < 0 or position >= step_count:
        raise ValueError("h3_detail_av: position is outside its context span.")
    ramp = min(int(DETAIL_AV_RECIPE["ramp_steps"]), step_count)
    from_end = step_count - 1 - position
    alpha = float(DETAIL_AV_RECIPE["alpha"])
    if from_end >= ramp:
        return alpha
    alpha_end = float(DETAIL_AV_RECIPE["alpha_end"])
    if from_end == 0:
        return alpha_end
    return alpha + (alpha_end - alpha) * (ramp - from_end) / ramp


def _detail_av_video_prefix(video_prefix, seed):
    """Build a deterministic, disposable noisy copy of an AV video prefix.

    Only the video tensor is accepted here. The caller retains the clean
    predecessor latent and the audio prefix independently, preventing this
    one-shot context treatment from contaminating recursive state.
    """
    if not torch.is_tensor(video_prefix) or video_prefix.ndim != 5:
        raise ValueError(
            "h3_detail_av: video prefix must be [B,C,T,H,W], got %s." %
            (tuple(getattr(video_prefix, "shape", ())),)
        )
    if not video_prefix.is_floating_point():
        raise ValueError("h3_detail_av: video prefix must be floating point.")
    steps = int(video_prefix.shape[2])
    expected_steps = int(DETAIL_AV_RECIPE["video_steps"])
    if steps != expected_steps:
        raise ValueError(
            "h3_detail_av: the v2 recipe requires %d video steps, got %d." %
            (expected_steps, steps)
        )

    out = video_prefix.detach().contiguous().clone()
    scale = float(out.detach().float().std().item())
    if not scale or not math.isfinite(scale):
        _LOG.warning(
            "h3_detail_av: degenerate carried-latent standard deviation; "
            "using unit Gaussian scale")
        scale = 1.0
    generator = torch.Generator(device="cpu")
    generator.manual_seed(int(seed) & 0xFFFFFFFFFFFFFFFF)
    alphas = []
    for position in range(steps):
        amount = _detail_av_alpha(position, steps)
        alphas.append(amount)
        block = out[:, :, position]
        noise = torch.randn(
            tuple(block.shape), generator=generator, dtype=torch.float32,
            device="cpu")
        noise = noise.mul_(scale).to(
            device=block.device, dtype=block.dtype)
        out[:, :, position] = block * (1.0 - amount) + noise * amount
    return out, scale, tuple(alphas)


def _require_h3_mask_support():
    """Compatibility alias retained for focused tests and chain callers."""
    from .masking_support import require_h3_mask_support

    return require_h3_mask_support("masked AV continuation")


def _snap_prefix_length(
        requested, available, target_frames, preserve_audio_prefix=True):
    """Resolve an AV prefix on the grid required by its active streams."""
    cap = min(int(requested), int(available), int(target_frames) - 1)
    preserve_audio_prefix = bool(preserve_audio_prefix)
    grid = AV_RUN_GRID if preserve_audio_prefix else VIDEO_RUN_GRID
    minimum = 39 if preserve_audio_prefix else 5
    run = next((value for value in grid if value <= cap), 0)
    if run < minimum:
        requirement = (
            "at least 39 previous frames and an exact shared video/audio "
            "boundary" if preserve_audio_prefix else
            "at least 5 previous frames on H3's video latent grid"
        )
        raise ValueError(
            "h3_masked_prefix: masked continuation needs %s and a target "
            "longer than the prefix." % requirement
        )
    if run != int(requested):
        if preserve_audio_prefix:
            detail = "exact shared AV runs are 39, 90, 141, 192, and 243"
        else:
            detail = "video-only prefix snapped to H3's video latent grid"
        _LOG.warning(
            "h3_masked_prefix: context_length %d -> exact H3 prefix %d (%s)",
            int(requested), run, detail)
    return run


def _validate_target_streams(latent, strict_audio_grid=True):
    video, audio = _streams_from_latent(latent)[:2]
    if video.ndim == 4:
        video = video.unsqueeze(0)
    if audio.ndim == 3:
        audio = audio.unsqueeze(0)
    if video.ndim != 5:
        raise ValueError(
            "h3_masked_prefix: video latent must be [B,C,T,H,W], got %s" %
            (tuple(video.shape),)
        )
    if audio.ndim != 4:
        raise ValueError(
            "h3_masked_prefix: audio latent must be [B,C,2,T], got %s" %
            (tuple(audio.shape),)
        )
    if int(video.shape[0]) != 1 or int(audio.shape[0]) != 1:
        raise ValueError(
            "h3_masked_prefix: masked continuation supports H3 batch size 1."
        )
    target_frames = _pixel_frames(int(video.shape[2]))
    expected_audio = int(round(target_frames / float(FPS) * AUDIO_HZ))
    if int(audio.shape[-1]) != expected_audio:
        message = (
            "h3_masked_prefix: target latent has %d audio steps for %d video "
            "frames; expected %d on H3's nominal 40 Hz grid." %
            (int(audio.shape[-1]), target_frames, expected_audio)
        )
        if strict_audio_grid:
            raise RuntimeError(message)
        _LOG.warning("%s The target audio length is authoritative.", message)
    return video, audio, target_frames


def _generated_video_tail(previous_latent, frames, target_video):
    """Copy a phase-aligned video prefix from a generated H3 AV latent."""
    parts = _streams_from_latent(previous_latent)
    if len(parts) < 2:
        raise ValueError(
            "h3_masked_prefix: previous sampled latent has no audio stream. "
            "Wire the joint H3 AV sampler output, not a video-only latent."
        )
    source_video, source_audio = parts[:2]
    if source_video.ndim == 4:
        source_video = source_video.unsqueeze(0)
    if source_audio.ndim == 3:
        source_audio = source_audio.unsqueeze(0)
    if source_video.ndim != 5:
        raise ValueError(
            "h3_masked_prefix: previous video latent must be [B,C,T,H,W], "
            "got %s." % (tuple(source_video.shape),)
        )
    if source_audio.ndim != 4:
        raise ValueError(
            "h3_masked_prefix: previous audio latent must be [B,C,2,T], got "
            "%s." % (tuple(source_audio.shape),)
        )
    if int(source_video.shape[0]) != 1 or int(source_audio.shape[0]) != 1:
        raise ValueError(
            "h3_masked_prefix: generated-latent continuation supports H3 "
            "batch size 1."
        )

    # Valid H3 prefix runs 5/22/39/... map to 2/7/12/... latent steps. Full
    # H3 clips and these prefixes are both 2 mod 5 latent steps, so slicing the
    # source tail and placing it at target step zero preserves temporal phase.
    video_steps = 2 + 5 * ((int(frames) - 5) // 17)
    if _pixel_frames(video_steps) != int(frames):
        raise RuntimeError(
            "h3_masked_prefix: internal H3 context mapping failed for %d "
            "frames." % int(frames)
        )
    if int(source_video.shape[2]) < video_steps:
        raise ValueError(
            "h3_masked_prefix: previous sampled latent has too few video "
            "steps for the %d-frame context." % int(frames)
        )
    if tuple(source_video.shape[1:2] + source_video.shape[3:]) != tuple(
            target_video.shape[1:2] + target_video.shape[3:]):
        raise ValueError(
            "h3_masked_prefix: previous/target video latent geometry differs: "
            "%s vs %s. Keep chained clips at the same H3 resolution." %
            (tuple(source_video.shape), tuple(target_video.shape))
        )
    return source_video[:1, :, -video_steps:].clone(), video_steps


def _encoded_video_tail(vae, previous_frames, frames, target_video, crop):
    """Encode an imported decoded-video tail when no H3 source latent exists."""
    if getattr(previous_frames, "ndim", 0) != 4:
        raise ValueError(
            "h3_masked_prefix: imported previous frames must be IMAGE "
            "[N,H,W,C]."
        )
    available = int(previous_frames.shape[0])
    if available < int(frames):
        raise ValueError(
            "h3_masked_prefix: imported video has %d frames but the resolved "
            "prefix needs %d." % (available, int(frames))
        )
    width = int(target_video.shape[4]) * 16
    height = int(target_video.shape[3]) * 16
    video_tail = _resize(
        previous_frames[available - int(frames):], width, height, crop)
    video_prefix = vae.encode(video_tail)
    if getattr(video_prefix, "ndim", 0) != 5:
        raise ValueError(
            "h3_masked_prefix: video VAE returned %s; expected "
            "[B,C,T,H,W]." %
            (tuple(getattr(video_prefix, "shape", ())),)
        )
    video_steps = int(video_prefix.shape[2])
    covered = _pixel_frames(video_steps)
    if covered != int(frames):
        raise RuntimeError(
            "h3_masked_prefix: %d imported context frames encoded to %d "
            "video steps covering %d frames; refusing a phase-shifted seam." %
            (int(frames), video_steps, covered)
        )
    return video_prefix, video_steps


def _encode_imported_audio(audio_vae, audio, frames):
    if audio_vae is None:
        raise ValueError(
            "h3_masked_prefix: imported-video scene 1 needs the H3 audio VAE "
            "connected to Chain Context."
        )
    if audio is None:
        raise ValueError(
            "h3_masked_prefix: imported-video scene 1 has no context audio. "
            "Reconnect source audio to Existing Video Context."
        )
    waveform = audio["waveform"]
    sample_rate = int(audio["sample_rate"])
    vae_rate = int(getattr(audio_vae, "audio_sample_rate", 32000))
    if sample_rate != vae_rate:
        try:
            import torchaudio
        except ImportError as exc:
            raise RuntimeError(
                "h3_masked_prefix: imported audio is %d Hz but the H3 audio "
                "VAE wants %d Hz and torchaudio is unavailable." %
                (sample_rate, vae_rate)
            ) from exc
        waveform = torchaudio.functional.resample(
            waveform, sample_rate, vae_rate)
    wanted = int(round(int(frames) / float(FPS) * vae_rate))
    if int(waveform.shape[-1]) < wanted:
        raise ValueError(
            "h3_masked_prefix: imported context audio is shorter than the "
            "%d-frame masked prefix." % int(frames)
        )
    encoded = audio_vae.encode(waveform[:1, ..., -wanted:].movedim(1, -1))
    if getattr(encoded, "ndim", 0) != 4:
        raise ValueError(
            "h3_masked_prefix: audio VAE returned %s; expected [B,C,2,T]." %
            (tuple(getattr(encoded, "shape", ())),)
        )
    steps = int(round(int(frames) / float(FPS) * AUDIO_HZ))
    if int(encoded.shape[-1]) < steps:
        raise RuntimeError(
            "h3_masked_prefix: %d frames need %d audio steps but the audio "
            "VAE produced %d." % (int(frames), steps, int(encoded.shape[-1]))
        )
    return encoded[:1, ..., -steps:], steps, "imported decoded audio"


def _existing_mask_streams(latent, video, audio):
    mask = latent.get("noise_mask")
    if mask is None:
        return (
            torch.ones(
                (1, 1, int(video.shape[2]), int(video.shape[3]),
                 int(video.shape[4])),
                device=video.device, dtype=torch.float32,
            ),
            torch.ones(
                (1, 1, int(audio.shape[2]), int(audio.shape[3])),
                device=audio.device, dtype=torch.float32,
            ),
        )
    if hasattr(mask, "unbind"):
        parts = list(mask.unbind())
    elif isinstance(mask, (tuple, list)):
        parts = list(mask)
    else:
        raise ValueError(
            "h3_masked_prefix: an existing target noise_mask is not a nested "
            "H3 video/audio mask and cannot be composed safely."
        )
    if len(parts) < 2:
        raise ValueError(
            "h3_masked_prefix: existing target noise_mask has no audio stream."
        )
    video_mask, audio_mask = parts[:2]
    if video_mask.ndim == 4:
        video_mask = video_mask.unsqueeze(0)
    if audio_mask.ndim == 3:
        audio_mask = audio_mask.unsqueeze(0)
    expected_video = (1, 1, int(video.shape[2]), int(video.shape[3]),
                      int(video.shape[4]))
    expected_audio = (1, 1, int(audio.shape[2]), int(audio.shape[3]))
    try:
        video_mask = torch.broadcast_to(video_mask, expected_video).clone()
        audio_mask = torch.broadcast_to(audio_mask, expected_audio).clone()
    except RuntimeError as exc:
        raise ValueError(
            "h3_masked_prefix: existing AV noise-mask shapes %s / %s cannot "
            "broadcast to target %s / %s." %
            (tuple(video_mask.shape), tuple(audio_mask.shape), expected_video,
             expected_audio)
        ) from exc
    return video_mask.float(), audio_mask.float()


def apply_locked_source_audio_target(
        latent, audio_vae, source_audio, *, lip_sync_options=None,
        voice=None, clip_start_seconds=0.0,
        voice_clip_start_seconds=None,
        force_active_voice_prefix_seconds=0.0):
    """Place exact scene-local source audio in H3's protected target stream.

    Reuse the standalone master-audio implementation so Chain Policy receives
    the same authoritative target-grid sizing, short encoder-lookahead retry,
    channel normalization, and mask composition as the public masking node.
    The Current Shot window is already scene-local, so its clock begins at 0.
    """
    if audio_vae is None:
        raise ValueError(
            "h3_source_audio_target: Lock source audio requires the H3 audio "
            "VAE connected to Chain Context.")
    if not isinstance(source_audio, dict):
        raise ValueError(
            "h3_source_audio_target: Current Shot state has no source-audio "
            "target window. Keep Current Shot state connected to Chain Context.")
    from .master_audio_context import MiniMaxH3ContexMasterAudioMaskedAV

    option_kwargs = {}
    if lip_sync_options is not None:
        option_kwargs = {
            key: lip_sync_options[key]
            for key in (
                "preroll_seconds", "lookahead_seconds", "audio_denoise",
                "gap_denoise", "gate_hold_seconds")
        }
    out, prefix_frames, _clip_audio = (
        MiniMaxH3ContexMasterAudioMaskedAV().prepare(
            latent=latent,
            audio_vae=audio_vae,
            master_audio=source_audio,
            clip_start_seconds=clip_start_seconds,
            context_length=0,
            voice=voice,
            voice_clip_start_seconds=voice_clip_start_seconds,
            force_active_voice_prefix_seconds=(
                force_active_voice_prefix_seconds),
            **option_kwargs,
        ))
    if int(prefix_frames) != 0:
        raise RuntimeError(
            "h3_source_audio_target: audio-only target unexpectedly changed "
            "the video prefix.")
    return out


def _feather_preserved_prefix(video_mask, audio_mask, video_steps, audio_steps):
    """Apply a narrow, high-denoise handoff at a protected AV tail."""
    video_steps = int(video_steps)
    audio_steps = int(audio_steps)
    video_feather = min(4, max(0, video_steps - 1))
    if video_feather < 1:
        video_mask[:, :, :video_steps] = 0.0
        audio_mask[..., :audio_steps] = 0.0
        return 0, 0
    # Fractional H3 masks are most useful close to full denoise.  Keep the
    # accepted prefix exact until the final four video-latent steps, then
    # give the model a deliberately narrow 0.85..0.95 reconstruction band.
    # Audio uses its own shorter 200 ms ramp instead of inheriting the much
    # wider video-to-audio grid conversion, which used to start the audible
    # handoff roughly 575 ms before the prefix boundary.
    audio_feather = min(max(0, audio_steps - 1), 8)
    video_ramp = torch.linspace(
        0.85, 0.95, video_feather,
        device=video_mask.device, dtype=video_mask.dtype,
    )
    video_hard_steps = video_steps - video_feather
    video_mask[:, :, :video_hard_steps] = 0.0
    video_mask[:, :, video_hard_steps:video_steps] = torch.minimum(
        video_mask[:, :, video_hard_steps:video_steps],
        video_ramp.view(1, 1, video_feather, 1, 1),
    )
    if audio_feather:
        audio_ramp = torch.linspace(
            0.85, 0.95, audio_feather,
            device=audio_mask.device, dtype=audio_mask.dtype,
        )
        audio_hard_steps = audio_steps - audio_feather
        audio_mask[..., :audio_hard_steps] = 0.0
        audio_mask[..., audio_hard_steps:audio_steps] = torch.minimum(
            audio_mask[..., audio_hard_steps:audio_steps],
            audio_ramp.view(1, 1, 1, audio_feather),
        )
    return video_feather, audio_feather


def _audio_feather_preserved_prefix(
    video_mask, audio_mask, video_steps, audio_steps,
):
    """Keep picture exact and release only the final audio-prefix ticks."""
    video_steps = int(video_steps)
    audio_steps = int(audio_steps)
    video_mask[:, :, :video_steps] = 0.0
    audio_feather = min(8, max(0, audio_steps))
    audio_hard_steps = audio_steps - audio_feather
    audio_mask[..., :audio_hard_steps] = 0.0
    if audio_feather:
        indices = torch.arange(
            1, audio_feather + 1,
            device=audio_mask.device, dtype=audio_mask.dtype,
        )
        audio_ramp = 0.5 - 0.5 * torch.cos(
            torch.pi * indices / float(audio_feather))
        audio_mask[..., audio_hard_steps:audio_steps] = torch.minimum(
            audio_mask[..., audio_hard_steps:audio_steps],
            audio_ramp.view(1, 1, 1, audio_feather),
        )
    return audio_feather


def _drop_prefix_guides(conditioning, prefix_frames):
    """Remove target guides that conflict with the preserved latent prefix."""
    out = []
    dropped = []
    for embedding, extra in conditioning:
        metadata = extra.copy()
        kept = []
        for guide in metadata.get("minimax_keyframes") or []:
            position = float(guide.get(
                "resolved_frame_index", guide.get("frame_index", 0)))
            if 0 <= position < int(prefix_frames):
                dropped.append(position)
            else:
                kept.append(guide)
        if "minimax_keyframes" in metadata:
            metadata["minimax_keyframes"] = kept
        out.append([embedding, metadata])
    if dropped:
        _LOG.warning(
            "h3_masked_prefix: dropped %d target guide(s) inside preserved "
            "frames 0..%d; the clean target latent already owns that prefix.",
            len(dropped), int(prefix_frames) - 1,
        )
    return out


def apply_masked_prefix(
    conditioning,
    vae,
    latent,
    previous_frames,
    context_length,
    crop,
    previous_latent=None,
    audio_vae=None,
    previous_audio=None,
    temporal_feather=False,
    audio_only_feather=False,
    preserve_audio_prefix=True,
    detail_video_taper=False,
    detail_video_seed=0,
    context_spatial_proxy="off",
    latent_color_carry=None,
):
    """Return conditioning, masked target latent, and repeated trim length."""
    _require_h3_mask_support()
    target_video, target_audio, target_frames = _validate_target_streams(latent)
    width = int(target_video.shape[4]) * 16
    height = int(target_video.shape[3]) * 16

    if previous_latent is not None:
        source_video = _streams_from_latent(previous_latent)[0]
        if source_video.ndim == 4:
            source_video = source_video.unsqueeze(0)
        if source_video.ndim != 5:
            raise ValueError(
                "h3_masked_prefix: previous video latent must be "
                "[B,C,T,H,W], got %s." % (tuple(source_video.shape),)
            )
        available = _pixel_frames(int(source_video.shape[2]))
        frames = _snap_prefix_length(
            context_length, available, target_frames,
            preserve_audio_prefix=preserve_audio_prefix)
        video_prefix, video_steps = _generated_video_tail(
            previous_latent, frames, target_video)
        video_source = "previous sampled latent"
    else:
        if getattr(previous_frames, "ndim", 0) != 4:
            raise ValueError(
                "h3_masked_prefix: imported previous frames must be IMAGE "
                "[N,H,W,C]."
            )
        available = int(previous_frames.shape[0])
        frames = _snap_prefix_length(
            context_length, available, target_frames,
            preserve_audio_prefix=preserve_audio_prefix)
        video_prefix, video_steps = _encoded_video_tail(
            vae, previous_frames, frames, target_video, crop)
        video_source = "imported decoded frames via video VAE"
    if video_steps >= int(target_video.shape[2]):
        raise ValueError(
            "h3_masked_prefix: video prefix consumes the whole target latent."
        )

    context_spatial_proxy = str(context_spatial_proxy or "off").strip().lower()
    if context_spatial_proxy == "latent_5_6":
        if previous_latent is None:
            raise ValueError(
                "h3_context_spatial_proxy: latent 5/6 requires a sampled "
                "predecessor latent; imported RGB context is not eligible.")
        original_height = int(video_prefix.shape[3])
        original_width = int(video_prefix.shape[4])
        video_prefix, proxy_size = _latent_context_spatial_proxy(video_prefix)
        video_source += " + 5/6 latent spatial proxy"
        _LOG.info(
            "h3_context_spatial_proxy: AV boundary latent %dx%d -> %dx%d "
            "-> %dx%d; audio and saved predecessor are unchanged.",
            original_width, original_height, int(proxy_size[1]),
            int(proxy_size[0]), original_width, original_height)
    elif context_spatial_proxy != "off":
        raise ValueError(
            "h3_context_spatial_proxy: masked AV accepts only off or "
            "latent_5_6, got %r." % context_spatial_proxy)

    latent_color_summary = None
    if latent_color_carry is not None:
        if previous_latent is None:
            raise ValueError(
                "h3_latent_color_carry: Color-Stable Drift AV requires a "
                "sampled generated predecessor latent; imported scene-1 "
                "context is not eligible.")
        if not isinstance(latent_color_carry, dict):
            raise ValueError(
                "h3_latent_color_carry: scene anchor data is malformed.")
        from .latent_color_carry import apply_delta_vae_color_carry

        video_prefix, latent_color_summary = apply_delta_vae_color_carry(
            video_prefix,
            vae,
            latent_color_carry.get("anchor_stats"),
            latent_color_carry.get("current_stats"),
        )
        if bool(latent_color_summary.get("applied", False)):
            video_source += " + tapered scene-one VAE-delta color carry"
        else:
            video_source += " + scene-one color carry (neutral)"

    detail_scale = None
    detail_alphas = ()
    if bool(detail_video_taper):
        if int(frames) != int(DETAIL_AV_RECIPE["context_frames"]):
            raise ValueError(
                "h3_detail_av: the experimental v2 recipe requires exactly "
                "%d context frames, got %d." %
                (int(DETAIL_AV_RECIPE["context_frames"]), int(frames))
            )
        video_prefix, detail_scale, detail_alphas = _detail_av_video_prefix(
            video_prefix, detail_video_seed)
        video_source += " + disposable Detail AV latent taper"

    if not bool(preserve_audio_prefix):
        audio_prefix = None
        audio_steps = 0
        audio_source = "open target (generated continuity off)"
    elif previous_latent is not None:
        audio_prefix, audio_steps, overhang = _audio_tail_from_latent(
            previous_latent, frames)
        audio_source = "previous sampled latent"
        if abs(overhang) > 1e-9:
            _LOG.warning(
                "h3_masked_prefix: predecessor audio grid ends %.3f latent "
                "steps from its last video frame; the copied %d-step prefix "
                "is end-aligned. Use 39/90/141/... context frames for an exact "
                "prefix duration.",
                overhang, audio_steps,
            )
    else:
        audio_prefix, audio_steps, audio_source = _encode_imported_audio(
            audio_vae, previous_audio, frames)
    if bool(preserve_audio_prefix):
        expected_audio_steps = int(round(frames / float(FPS) * AUDIO_HZ))
        if audio_steps != expected_audio_steps:
            raise RuntimeError(
                "h3_masked_prefix: %d video frames require %d audio steps, "
                "got %d." % (frames, expected_audio_steps, audio_steps)
            )
        if audio_steps >= int(target_audio.shape[-1]):
            raise ValueError(
                "h3_masked_prefix: audio prefix consumes the whole target "
                "latent.")

    out_video = target_video.clone()
    out_audio = target_audio.clone()
    vp = video_prefix[:1].to(out_video.device, out_video.dtype)
    ap = (audio_prefix[:1].to(out_audio.device, out_audio.dtype)
          if audio_prefix is not None else None)
    if (int(vp.shape[1]) != int(out_video.shape[1])
            or tuple(vp.shape[3:]) != tuple(out_video.shape[3:])):
        raise ValueError(
            "h3_masked_prefix: encoded video prefix shape %s does not match "
            "target %s." % (tuple(vp.shape), tuple(out_video.shape))
        )
    if ap is not None and tuple(ap.shape[1:3]) != tuple(out_audio.shape[1:3]):
        raise ValueError(
            "h3_masked_prefix: audio prefix shape %s does not match target %s."
            % (tuple(ap.shape), tuple(out_audio.shape))
        )
    out_video[:, :, :video_steps] = vp
    if ap is not None:
        out_audio[..., :audio_steps] = ap

    video_mask, audio_mask = _existing_mask_streams(
        latent, out_video, out_audio)
    video_feather_steps = audio_feather_steps = 0
    if bool(audio_only_feather):
        audio_feather_steps = _audio_feather_preserved_prefix(
            video_mask, audio_mask, video_steps, audio_steps)
    elif bool(temporal_feather):
        video_feather_steps, audio_feather_steps = _feather_preserved_prefix(
            video_mask, audio_mask, video_steps, audio_steps)
    else:
        video_mask[:, :, :video_steps] = 0.0
        audio_mask[..., :audio_steps] = 0.0

    import comfy.nested_tensor

    out_latent = latent.copy()
    out_latent["samples"] = comfy.nested_tensor.NestedTensor(
        (out_video, out_audio))
    out_latent["noise_mask"] = comfy.nested_tensor.NestedTensor(
        (video_mask, audio_mask))
    out_conditioning = _drop_prefix_guides(conditioning, frames)

    if not bool(preserve_audio_prefix):
        mask_summary = "audio fully denoisable (generated continuity off)"
    elif audio_only_feather:
        mask_summary = "audio-only half-cosine feather %d audio steps" % (
            audio_feather_steps)
    elif temporal_feather:
        mask_summary = "temporal feather %d video / %d audio steps" % (
            video_feather_steps, audio_feather_steps)
    else:
        mask_summary = "hard prefix mask"
    if detail_scale is not None:
        mask_summary += (
            "; Detail AV video-only Gaussian taper %.3f -> %.3f over "
            "%d steps (sigma %.4f, seed %d)" %
            (float(detail_alphas[0]), float(detail_alphas[-1]),
             int(DETAIL_AV_RECIPE["ramp_steps"]), float(detail_scale),
             int(detail_video_seed)))
    if latent_color_summary is not None:
        mask_summary += (
            "; scene-one latent color delta %s, brightness %+.4f, "
            "saturation %.4f, audio unchanged" %
            ("applied" if latent_color_summary.get("applied") else "neutral",
             float(latent_color_summary.get("brightness", 0.0)),
             float(latent_color_summary.get("saturation", 1.0))))
    _LOG.info(
        "h3_masked_prefix: preserved %d target frames = %d video steps / %d "
        "audio steps (%.3fs, video from %s, audio from %s); %s; target %d "
        "frames at %dx%d; trim %d",
        frames, video_steps, audio_steps, frames / float(FPS), video_source,
        audio_source,
        mask_summary,
        target_frames, width, height, frames,
    )
    return out_conditioning, out_latent, frames
