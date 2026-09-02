"""Exact master-audio masking with an optional previous-video prefix.

This is the timeline-audio specialization of the general H3 masked-target
path: the target audio stream is replaced with one exact master-audio interval
and protected for the complete raw clip. Continuations may additionally
protect the final native H3 run from either the preceding sampled AV latent or
the legacy decoded-video path.

The design is adapted from seitanism's GPL-3.0
ComfyUI-H3-Motion-Context-MultiRef Update 4 implementation, including Update
5's target-audio-grid boundary correction. This pack keeps a distinct public
node id and reuses its shared native-first mask capability gate so both packs
can be installed together.
"""

from __future__ import annotations

import logging
import math

import torch

from .masked_context import (
    _existing_mask_streams,
    _generated_video_tail,
    _snap_prefix_length,
    _validate_target_streams,
)
from .masking_support import require_h3_mask_support
from .nodes import AUDIO_HZ, FPS, _pixel_frames, _resize, _streams_from_latent
from .av_timing import sample_boundary_from_seconds


_LOG = logging.getLogger("minimax_h3_context_loop.master_audio_context")


def _cfr_index_map(frame_count, source_fps, device):
    source_fps = float(source_fps)
    if source_fps <= 0.0:
        raise ValueError("h3_master_audio_mask: source_fps must be positive.")
    count = int(frame_count)
    if count < 1:
        raise ValueError("h3_master_audio_mask: source video has no frames.")
    output_count = max(1, int(round(count * float(FPS) / source_fps)))
    if output_count == count and abs(source_fps - float(FPS)) < 1e-6:
        return torch.arange(count, device=device, dtype=torch.long)
    index = torch.arange(output_count, device=device, dtype=torch.float64)
    time = (index + 0.5) / float(FPS)
    source = torch.round(time * source_fps - 0.5).to(torch.long)
    return source.clamp_(0, count - 1)


def _stereo_first_batch(waveform):
    if getattr(waveform, "ndim", 0) != 3:
        raise ValueError(
            "h3_master_audio_mask: master audio waveform must be [B,C,L], "
            "got %s." %
            (tuple(getattr(waveform, "shape", ())),)
        )
    waveform = waveform[:1]
    channels = int(waveform.shape[1])
    if channels == 1:
        return waveform.repeat(1, 2, 1)
    if channels == 2:
        return waveform
    raise ValueError(
        "h3_master_audio_mask: master audio has %d channels; downmix it to stereo "
        "before this node." % channels
    )


def _resample(waveform, source_rate, target_rate):
    source_rate = int(source_rate)
    target_rate = int(target_rate)
    if source_rate == target_rate:
        return waveform
    try:
        import torchaudio
    except ImportError as exc:
        raise RuntimeError(
            "h3_master_audio_mask: master audio is %d Hz but the H3 audio VAE needs "
            "%d Hz and torchaudio is unavailable." %
            (source_rate, target_rate)
        ) from exc
    return torchaudio.functional.resample(waveform, source_rate, target_rate)


def _fit_audio_slice(waveform, samples):
    wanted = int(samples)
    available = int(waveform.shape[-1])
    if available > wanted:
        return waveform[..., :wanted]
    if available < wanted:
        _LOG.warning(
            "h3_master_audio_mask: master-audio slice is %d samples short; padding "
            "silence at the tail.", wanted - available)
        return torch.nn.functional.pad(waveform, (0, wanted - available))
    return waveform


class MiniMaxH3ContexMasterAudioMaskedAV:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "latent": ("LATENT", {
                    "tooltip": "Target AV latent from the stock MiniMax H3 "
                               "conditioning node.",
                }),
                "audio_vae": ("VAE", {
                    "tooltip": "MiniMax H3 audio VAE used to encode the exact "
                               "master-audio slice into the target latent.",
                }),
                "master_audio": ("AUDIO", {
                    "tooltip": "Full prerecorded audio timeline (music, "
                               "dialogue, narration, or effects). The exact "
                               "current interval is inserted into the target "
                               "and fully protected.",
                }),
                "clip_start_seconds": ("FLOAT", {
                    "default": 0.0, "min": 0.0, "max": 99999.0,
                    "step": 0.001,
                    "tooltip": "Start of this raw H3 clip on the master-audio "
                               "timeline.",
                }),
                "context_length": ("INT", {
                    "default": 39, "min": 0, "max": 9999,
                    "tooltip": "Previous-video prefix request. Native runs "
                               "such as 5, 22, 39, 56... are used; 0 disables "
                               "video prefixing when neither source input is "
                               "connected.",
                }),
                "source_fps": ("FLOAT", {
                    "default": 24.0, "min": 1.0, "max": 240.0,
                    "step": 0.001,
                    "tooltip": "Frame rate of the legacy decoded "
                               "source_frames path. It is ignored when "
                               "source_latent is used.",
                }),
                "crop": (["disabled", "center"], {
                    "default": "disabled",
                    "tooltip": "Resize policy for legacy source_frames: "
                               "disabled stretches to the target canvas; "
                               "center preserves aspect ratio and center-crops. "
                               "Ignored when source_latent is used.",
                }),
            },
            "optional": {
                "vae": ("VAE", {
                    "tooltip": "MiniMax H3 video VAE; required when previous "
                               "source_frames are connected.",
                }),
                "source_frames": ("IMAGE", {
                    "tooltip": "Legacy decoded continuation path. Its final "
                               "native H3 context run is VAE-encoded into the "
                               "protected video prefix. Prefer source_latent "
                               "for live H3 chaining.",
                }),
                "source_latent": ("LATENT", {
                    "tooltip": "Preferred live continuation path. The "
                               "phase-aligned tail of the previous sampled H3 "
                               "video latent is copied directly; its audio is "
                               "ignored because master_audio remains "
                               "authoritative.",
                }),
            },
        }

    RETURN_TYPES = ("LATENT", "INT", "AUDIO")
    RETURN_NAMES = ("latent", "trim_frames", "clip_audio")
    OUTPUT_TOOLTIPS = (
        "Sampler target with exact protected master audio and optional "
        "protected previous-video prefix.",
        "Actual protected visual prefix length; trim this many decoded frames.",
        "Exact master-audio interval represented by this raw target.",
    )
    FUNCTION = "prepare"
    CATEGORY = "conditioning/minimax/context_loop/masking"
    DESCRIPTION = (
        "Insert an exact master-audio interval into the complete H3 audio "
        "target and protect it from denoising; optionally preserve a previous "
        "sampled-latent or decoded-video prefix while generating only future "
        "video rows."
    )

    def prepare(
        self,
        latent,
        audio_vae,
        master_audio,
        clip_start_seconds=0.0,
        context_length=39,
        source_fps=24.0,
        crop="disabled",
        vae=None,
        source_frames=None,
        source_latent=None,
    ):
        require_h3_mask_support("exact master-audio latent masking")
        target_video, target_audio, target_frames = _validate_target_streams(
            latent, strict_audio_grid=False)
        if source_latent is not None and source_frames is not None:
            raise ValueError(
                "h3_master_audio_mask: connect either source_latent or "
                "source_frames, not both.")

        # The stock H3 target owns the audio-grid length. It can round up one
        # 40 Hz step beyond what a floor-style audio VAE produces from the
        # exact picture-duration waveform (for example 124 frames -> 207
        # target steps while a picture-only encode can return 206).
        expected_audio_steps = int(target_audio.shape[-1])
        nominal_audio_steps = int(round(
            target_frames / float(FPS) * AUDIO_HZ))
        if expected_audio_steps != nominal_audio_steps:
            _LOG.warning(
                "h3_master_audio_mask: target contains %d audio steps for "
                "%d frames; nominal 40 Hz calculation gives %d. Using the "
                "target length.", expected_audio_steps, target_frames,
                nominal_audio_steps)
        vae_rate = int(getattr(audio_vae, "audio_sample_rate", 32000))
        if not isinstance(master_audio, dict):
            raise ValueError(
                "h3_master_audio_mask: master_audio is not a Comfy AUDIO.")
        waveform = _stereo_first_batch(master_audio.get("waveform"))
        waveform = _resample(
            waveform, int(master_audio.get("sample_rate", 0)), vae_rate)

        start_seconds = float(clip_start_seconds)
        if start_seconds < 0.0:
            raise ValueError(
                "h3_master_audio_mask: clip_start_seconds must be >= 0.")
        start_sample = sample_boundary_from_seconds(start_seconds, vae_rate)
        picture_end_sample = sample_boundary_from_seconds(
            start_seconds + target_frames / float(FPS), vae_rate)
        picture_samples = picture_end_sample - start_sample
        if picture_samples < 1:
            raise RuntimeError(
                "h3_master_audio_mask: computed an empty master-audio slice.")
        audio_slice = _fit_audio_slice(
            waveform[..., start_sample:picture_end_sample],
            picture_samples,
        )

        # Keep clip_audio at exact picture duration, but encode enough real
        # timeline audio to cover the complete rounded H3 grid. At the end of
        # the source, _fit_audio_slice supplies only the missing tail silence;
        # it never fabricates or repeats latent tokens.
        grid_samples = int(math.ceil(
            expected_audio_steps / float(AUDIO_HZ) * vae_rate))
        encode_samples = max(picture_samples, grid_samples)
        encode_slice = _fit_audio_slice(
            waveform[..., start_sample:start_sample + encode_samples],
            encode_samples,
        )
        encoded_audio = audio_vae.encode(encode_slice.movedim(1, -1))
        if getattr(encoded_audio, "ndim", 0) != 4:
            raise ValueError(
                "h3_master_audio_mask: audio VAE returned %s; expected "
                "[B,C,2,T]." %
                (tuple(getattr(encoded_audio, "shape", ())),)
            )
        got_audio_steps = int(encoded_audio.shape[-1])
        if got_audio_steps < expected_audio_steps:
            missing = expected_audio_steps - got_audio_steps
            guard_samples = int(math.ceil(
                (missing + 1) * vae_rate / float(AUDIO_HZ)))
            retry_samples = encode_samples + guard_samples
            retry_slice = _fit_audio_slice(
                waveform[..., start_sample:start_sample + retry_samples],
                retry_samples,
            )
            retry_audio = audio_vae.encode(retry_slice.movedim(1, -1))
            if getattr(retry_audio, "ndim", 0) != 4:
                raise ValueError(
                    "h3_master_audio_mask: audio VAE retry returned %s; "
                    "expected [B,C,2,T]." %
                    (tuple(getattr(retry_audio, "shape", ())),)
                )
            retry_steps = int(retry_audio.shape[-1])
            _LOG.warning(
                "h3_master_audio_mask: audio VAE initially produced %d/%d "
                "target steps; retried with %.2f ms of real-audio grid "
                "lookahead and got %d.", got_audio_steps,
                expected_audio_steps,
                guard_samples / float(vae_rate) * 1000.0, retry_steps)
            encoded_audio = retry_audio
            got_audio_steps = retry_steps

        if got_audio_steps < expected_audio_steps:
            raise RuntimeError(
                "h3_master_audio_mask: target requires %d audio steps but the "
                "audio VAE produced %d even after grid lookahead." %
                (expected_audio_steps, got_audio_steps)
            )
        if got_audio_steps > expected_audio_steps:
            _LOG.info(
                "h3_master_audio_mask: audio VAE produced %d steps for a %d-step "
                "target; retaining the leading aligned interval.",
                got_audio_steps, expected_audio_steps)
            encoded_audio = encoded_audio[..., :expected_audio_steps]

        out_video = target_video.clone()
        out_audio = target_audio.clone()
        encoded_audio = encoded_audio[:1].to(
            device=out_audio.device, dtype=out_audio.dtype)
        if tuple(encoded_audio.shape) != tuple(out_audio.shape):
            raise ValueError(
                "h3_master_audio_mask: encoded master audio shape %s does not match "
                "target %s." %
                (tuple(encoded_audio.shape), tuple(out_audio.shape))
            )
        out_audio.copy_(encoded_audio)

        prefix_frames = 0
        video_steps = 0
        if source_latent is not None:
            if int(context_length) <= 0:
                raise ValueError(
                    "h3_master_audio_mask: context_length must be positive "
                    "when source_latent is connected.")
            source_parts = _streams_from_latent(source_latent)
            if len(source_parts) < 2:
                raise ValueError(
                    "h3_master_audio_mask: source_latent must be a joint H3 "
                    "video/audio latent.")
            source_video = source_parts[0]
            if source_video.ndim == 4:
                source_video = source_video.unsqueeze(0)
            if source_video.ndim != 5:
                raise ValueError(
                    "h3_master_audio_mask: source video latent must be "
                    "[B,C,T,H,W].")
            available = _pixel_frames(int(source_video.shape[2]))
            prefix_frames = _snap_prefix_length(
                context_length, available, target_frames)
            prefix, video_steps = _generated_video_tail(
                source_latent, prefix_frames, target_video)
            if video_steps >= int(out_video.shape[2]):
                raise ValueError(
                    "h3_master_audio_mask: video prefix consumes the complete "
                    "target.")
            out_video[:, :, :video_steps] = prefix.to(
                device=out_video.device, dtype=out_video.dtype)
        elif source_frames is not None:
            if vae is None:
                raise ValueError(
                    "h3_master_audio_mask: connect the video VAE when source_frames "
                    "is connected.")
            if (getattr(source_frames, "ndim", 0) != 4
                    or int(source_frames.shape[0]) < 1):
                raise ValueError(
                    "h3_master_audio_mask: source_frames must be IMAGE "
                    "[N,H,W,C].")
            if int(context_length) <= 0:
                raise ValueError(
                    "h3_master_audio_mask: context_length must be positive when "
                    "source_frames is connected.")
            indices = _cfr_index_map(
                int(source_frames.shape[0]), source_fps,
                source_frames.device)
            prefix_frames = _snap_prefix_length(
                context_length, int(indices.numel()), target_frames)
            tail = source_frames.index_select(0, indices[-prefix_frames:])
            width = int(target_video.shape[4]) * 16
            height = int(target_video.shape[3]) * 16
            prefix = vae.encode(_resize(tail, width, height, crop))
            if getattr(prefix, "ndim", 0) != 5:
                raise ValueError(
                    "h3_master_audio_mask: video VAE returned %s; expected "
                    "[B,C,T,H,W]." %
                    (tuple(getattr(prefix, "shape", ())),)
                )
            video_steps = int(prefix.shape[2])
            covered = _pixel_frames(video_steps)
            if covered != prefix_frames:
                raise RuntimeError(
                    "h3_master_audio_mask: %d source frames encoded to %d video "
                    "steps covering %d frames; refusing a shifted seam." %
                    (prefix_frames, video_steps, covered)
                )
            if video_steps >= int(out_video.shape[2]):
                raise ValueError(
                    "h3_master_audio_mask: video prefix consumes the complete "
                    "target.")
            prefix = prefix[:1].to(
                device=out_video.device, dtype=out_video.dtype)
            if (int(prefix.shape[1]) != int(out_video.shape[1])
                    or tuple(prefix.shape[3:]) != tuple(out_video.shape[3:])):
                raise ValueError(
                    "h3_master_audio_mask: video prefix shape %s does not match "
                    "target %s." %
                    (tuple(prefix.shape), tuple(out_video.shape))
                )
            out_video[:, :, :video_steps] = prefix

        # Compose with an upstream masked target instead of replacing it. This
        # is what lets Chain Context own the protected continuation-video
        # prefix while this node replaces and protects the complete current
        # master-audio interval. It also keeps both standalone video-prefix
        # paths composable with any future spatial/video mask.
        video_mask, _ = _existing_mask_streams(
            latent, out_video, out_audio)
        if video_steps:
            video_mask[:, :, :video_steps] = 0.0
        audio_mask = torch.zeros(
            (1, 1, int(out_audio.shape[2]), int(out_audio.shape[3])),
            device=out_audio.device, dtype=torch.float32)

        import comfy.nested_tensor

        output = latent.copy()
        output["samples"] = comfy.nested_tensor.NestedTensor(
            (out_video, out_audio))
        output["noise_mask"] = comfy.nested_tensor.NestedTensor(
            (video_mask, audio_mask))
        clip_audio = {"waveform": audio_slice, "sample_rate": vae_rate}
        _LOG.info(
            "h3_master_audio_mask: target %d frames / %.3fs; master "
            "%.3f..%.3fs "
            "encoded to %d fully protected audio steps; video prefix %d "
            "frames / %d steps.",
            target_frames, target_frames / float(FPS), start_seconds,
            start_seconds + target_frames / float(FPS),
            expected_audio_steps, prefix_frames, video_steps)
        return output, prefix_frames, clip_audio


NODE_CLASS_MAPPINGS = {
    "MiniMaxH3ContexMasterAudioMaskedAV": (
        MiniMaxH3ContexMasterAudioMaskedAV),
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "MiniMaxH3ContexMasterAudioMaskedAV": (
        "MiniMax H3 Masking · Master Audio + Video Prefix"),
}
