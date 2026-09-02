"""Frame-locked source AV targets for recursive MiniMax H3 editing.

The stock H3 conditioning node owns the exact joint video/audio target grid.
This node selects the current Chain Loop interval from a source video, encodes
its picture and sound, and copies both streams into that authoritative target.
It deliberately avoids LTX AV concat/separate helpers: independently encoded
streams can differ by one audio token at fractional 24-fps/40-Hz boundaries.
"""

from __future__ import annotations

import logging
import math

import torch

from .masked_context import _validate_target_streams
from .masking_ops import normalize_comfy_mask
from .nodes import AUDIO_HZ, FPS, _resize


try:
    import torchaudio
except ImportError:  # pragma: no cover - only exercised on minimal installs
    torchaudio = None


_LOG = logging.getLogger("minimax_h3_context_loop.source_av_target")
STATE_TYPE = "H3_CHAIN_STATE"


def _canonical_indices(frame_count, source_fps, device):
    source_fps = float(source_fps)
    if not math.isfinite(source_fps) or source_fps <= 0.0:
        raise ValueError("h3_source_av_target: source_fps must be positive.")
    frame_count = int(frame_count)
    if frame_count < 1:
        raise ValueError("h3_source_av_target: source video has no frames.")
    output_count = max(1, int(round(frame_count * FPS / source_fps)))
    if output_count == frame_count and abs(source_fps - FPS) < 1e-6:
        return torch.arange(frame_count, device=device, dtype=torch.long)
    frame = torch.arange(output_count, device=device, dtype=torch.float64)
    source = torch.round((frame + 0.5) * source_fps / FPS - 0.5)
    return source.to(torch.long).clamp_(0, frame_count - 1)


def _stereo_waveform(audio, target_rate):
    if not isinstance(audio, dict):
        raise ValueError(
            "h3_source_av_target: source_audio must be a ComfyUI AUDIO.")
    waveform = audio.get("waveform")
    if getattr(waveform, "ndim", 0) != 3:
        raise ValueError(
            "h3_source_av_target: source audio must be [B,C,L], got %s." %
            (tuple(getattr(waveform, "shape", ())),))
    waveform = waveform[:1]
    channels = int(waveform.shape[1])
    if channels == 1:
        waveform = waveform.repeat(1, 2, 1)
    elif channels != 2:
        raise ValueError(
            "h3_source_av_target: source audio has %d channels; downmix it "
            "to stereo first." % channels)
    source_rate = int(audio.get("sample_rate", 0))
    target_rate = int(target_rate)
    if source_rate <= 0:
        raise ValueError(
            "h3_source_av_target: source audio has no valid sample rate.")
    if source_rate != target_rate:
        if torchaudio is None:
            raise RuntimeError(
                "h3_source_av_target: source audio is %d Hz but the H3 audio "
                "VAE needs %d Hz and torchaudio is unavailable." %
                (source_rate, target_rate))
        waveform = torchaudio.functional.resample(
            waveform, source_rate, target_rate)
    return waveform


def _fit_slice(waveform, start, samples, allow_tail_padding, label):
    start = int(start)
    samples = int(samples)
    if start < 0 or samples < 0:
        raise ValueError("h3_source_av_target: invalid audio slice.")
    available = max(0, int(waveform.shape[-1]) - start)
    if available < samples and not allow_tail_padding:
        raise ValueError(
            "h3_source_av_target: source audio is too short for %s; need %d "
            "samples from offset %d but only %d remain." %
            (label, samples, start, available))
    result = waveform[..., start:start + samples]
    missing = samples - int(result.shape[-1])
    if missing > 0:
        result = torch.nn.functional.pad(result, (0, missing))
    return result, missing


def _encode_audio_to_target(
    audio_vae,
    waveform,
    start_frame,
    frame_count,
    target_audio,
):
    sample_rate = int(getattr(audio_vae, "audio_sample_rate", 32000))
    start_sample = int(round(int(start_frame) / FPS * sample_rate))
    picture_samples = int(round(int(frame_count) / FPS * sample_rate))
    # The actual picture interval must exist. Any padding below is limited to
    # the sub-frame encoder lookahead needed to cover the stock target grid.
    picture, _ = _fit_slice(
        waveform, start_sample, picture_samples, False, "the picture interval")
    target_steps = int(target_audio.shape[-1])
    grid_samples = int(math.ceil(
        target_steps / float(AUDIO_HZ) * sample_rate))
    encode_samples = max(picture_samples, grid_samples)
    encoded_source, padded = _fit_slice(
        waveform, start_sample, encode_samples, True, "the H3 audio grid")
    encoded = audio_vae.encode(encoded_source.movedim(1, -1))
    if getattr(encoded, "ndim", 0) != 4:
        raise ValueError(
            "h3_source_av_target: audio VAE returned %s; expected "
            "[B,C,2,T]." % (tuple(getattr(encoded, "shape", ())),))
    if int(encoded.shape[-1]) < target_steps:
        missing_steps = target_steps - int(encoded.shape[-1])
        guard_samples = int(math.ceil(
            (missing_steps + 1) * sample_rate / float(AUDIO_HZ)))
        encoded_source, retry_padding = _fit_slice(
            waveform, start_sample, encode_samples + guard_samples, True,
            "the H3 audio-grid retry")
        padded = max(padded, retry_padding)
        encoded = audio_vae.encode(encoded_source.movedim(1, -1))
    if getattr(encoded, "ndim", 0) != 4 or int(encoded.shape[-1]) < target_steps:
        raise RuntimeError(
            "h3_source_av_target: audio VAE cannot fill the stock %d-step "
            "target (produced %d)." %
            (target_steps, int(getattr(encoded, "shape", (0, 0, 0, 0))[-1])))
    encoded = encoded[:1, ..., :target_steps].to(
        device=target_audio.device, dtype=target_audio.dtype)
    if tuple(encoded.shape) != tuple(target_audio.shape):
        raise ValueError(
            "h3_source_av_target: encoded audio shape %s does not match the "
            "stock target %s." %
            (tuple(encoded.shape), tuple(target_audio.shape)))
    clip_audio = {
        "waveform": picture,
        "sample_rate": sample_rate,
    }
    return encoded, clip_audio, padded


class MiniMaxH3ContexLoopSourceAVTarget:
    """Replace the current loop target with its exact source AV interval."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "state": (STATE_TYPE, {
                    "tooltip": "Current state from H3 Chain Current Shot."}),
                "latent": ("LATENT", {
                    "tooltip": "Current stock H3 joint target, normally the "
                               "latent output from Chain Context."}),
                "vae": ("VAE", {"tooltip": "MiniMax H3 video VAE."}),
                "audio_vae": ("VAE", {"tooltip": "MiniMax H3 audio VAE."}),
                "source_frames": ("IMAGE", {
                    "tooltip": "Complete decoded source-video timeline."}),
                "source_audio": ("AUDIO", {
                    "tooltip": "Audio from the same source video."}),
                "source_fps": ("FLOAT", {
                    "default": 24.0, "min": 0.001, "max": 1000.0,
                    "step": 0.001,
                    "tooltip": "Actual FPS of source_frames. Connect the FPS "
                               "output from Get Video Components."}),
                "crop": (["disabled", "center"], {
                    "default": "center",
                    "tooltip": "Resize policy for the selected source-video "
                               "interval: disabled stretches to the target "
                               "canvas; center preserves aspect ratio and "
                               "center-crops.",
                }),
            },
        }

    RETURN_TYPES = ("LATENT", "IMAGE", "AUDIO", "STRING")
    RETURN_NAMES = ("source_target", "scene_frames", "scene_audio", "status")
    OUTPUT_TOOLTIPS = (
        "Current stock H3 target with the exact source-video and source-audio "
        "scene interval encoded into it.",
        "The resized 24 fps source frames selected for the current scene.",
        "The synchronized source-audio interval selected for the current scene.",
        "Summary of the selected timeline range, target grid, and any audio "
        "tail padding.",
    )
    FUNCTION = "prepare"
    CATEGORY = "conditioning/minimax/context_loop/masking"
    DESCRIPTION = (
        "Select the current Chain Loop interval from a source video and copy "
        "frame-locked video/audio encodes into the stock H3 joint target.")

    def prepare(
        self,
        state,
        latent,
        vae,
        audio_vae,
        source_frames,
        source_audio,
        source_fps=24.0,
        crop="center",
    ):
        target_video, target_audio, target_frames = _validate_target_streams(
            latent, strict_audio_grid=False)
        if getattr(source_frames, "ndim", 0) != 4:
            raise ValueError(
                "h3_source_av_target: source_frames must be IMAGE "
                "[N,H,W,C].")
        try:
            index = int(state["index"])
            shot = state["plan"]["shots"][index - 1]
            start_frame = int(shot["generation_start_frame"])
            planned_frames = int(shot["raw_frames"])
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise ValueError(
                "h3_source_av_target: invalid Chain Current Shot state.") from exc
        if planned_frames != target_frames:
            raise RuntimeError(
                "h3_source_av_target: scene %d plans %d frames but the stock "
                "target covers %d." % (index, planned_frames, target_frames))
        if start_frame < 0:
            raise ValueError(
                "h3_source_av_target: scene %d begins before the source "
                "timeline; external-prelude editing is unsupported." % index)

        indices = _canonical_indices(
            int(source_frames.shape[0]), source_fps, source_frames.device)
        end_frame = start_frame + target_frames
        if end_frame > int(indices.numel()):
            raise ValueError(
                "h3_source_av_target: scene %d needs canonical source frames "
                "%d..%d, but the video has only %d frames at 24 fps." %
                (index, start_frame, end_frame - 1, int(indices.numel())))
        selected = source_frames.index_select(
            0, indices[start_frame:end_frame])
        width = int(target_video.shape[4]) * 16
        height = int(target_video.shape[3]) * 16
        scene_frames = _resize(selected, width, height, crop)
        encoded_video = vae.encode(scene_frames)
        if getattr(encoded_video, "ndim", 0) != 5:
            raise ValueError(
                "h3_source_av_target: video VAE returned %s; expected "
                "[B,C,T,H,W]." %
                (tuple(getattr(encoded_video, "shape", ())),))
        encoded_video = encoded_video[:1].to(
            device=target_video.device, dtype=target_video.dtype)
        if tuple(encoded_video.shape) != tuple(target_video.shape):
            raise ValueError(
                "h3_source_av_target: encoded video shape %s does not match "
                "the stock target %s." %
                (tuple(encoded_video.shape), tuple(target_video.shape)))

        audio_rate = int(getattr(audio_vae, "audio_sample_rate", 32000))
        waveform = _stereo_waveform(source_audio, audio_rate)
        encoded_audio, scene_audio, padded = _encode_audio_to_target(
            audio_vae, waveform, start_frame, target_frames, target_audio)

        import comfy.nested_tensor

        output = latent.copy()
        output["samples"] = comfy.nested_tensor.NestedTensor((
            encoded_video.clone(), encoded_audio.clone()))
        status = (
            "H3 loop source target scene %d: source frames %d..%d -> %d "
            "frames at %dx%d; stock target %d video / %d audio steps; audio "
            "grid tail padding %d samples."
            % (index, start_frame, end_frame - 1, target_frames, width, height,
               int(target_video.shape[2]), int(target_audio.shape[-1]), padded))
        _LOG.info(status)
        return output, scene_frames, scene_audio, status


class MiniMaxH3ContexLoopMaskSlice:
    """Select the tracked mask interval matching the current loop scene."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "state": (STATE_TYPE, {
                    "tooltip": "Current state from H3 Chain Current Shot."}),
                "mask": ("MASK", {
                    "tooltip": "One static mask or a complete tracked mask "
                               "timeline. White means generate."}),
                "source_fps": ("FLOAT", {
                    "default": 24.0, "min": 0.001, "max": 1000.0,
                    "step": 0.001,
                    "tooltip": "FPS represented by a tracked mask batch. A "
                               "single mask is broadcast and ignores FPS."}),
            },
        }

    RETURN_TYPES = ("MASK", "INT", "STRING")
    RETURN_NAMES = ("scene_mask", "scene_mask_frames", "status")
    OUTPUT_TOOLTIPS = (
        "Static mask broadcast or tracked-mask slice aligned to the current "
        "scene's complete raw frame interval.",
        "Number of mask frames returned for the current scene.",
        "Summary of the selected scene interval and whether the mask was "
        "broadcast or sliced.",
    )
    FUNCTION = "slice"
    CATEGORY = "conditioning/minimax/context_loop/masking"
    DESCRIPTION = (
        "Broadcast one static mask or slice the exact tracked-mask interval "
        "for the current Chain Loop scene and its continuation overlap.")

    def slice(self, state, mask, source_fps=24.0):
        timeline = normalize_comfy_mask(mask)
        try:
            index = int(state["index"])
            shot = state["plan"]["shots"][index - 1]
            start_frame = int(shot["generation_start_frame"])
            scene_frames = int(shot["raw_frames"])
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise ValueError(
                "h3_loop_mask_slice: invalid Chain Current Shot state.") from exc
        if start_frame < 0:
            raise ValueError(
                "h3_loop_mask_slice: scene %d begins before the mask "
                "timeline." % index)

        mask_frames = int(timeline.shape[0])
        if mask_frames == 1:
            selected = timeline.expand(
                scene_frames, int(timeline.shape[1]), int(timeline.shape[2])
            ).clone()
            mode = "static mask broadcast"
        else:
            indices = _canonical_indices(
                mask_frames, source_fps, timeline.device)
            end_frame = start_frame + scene_frames
            if end_frame > int(indices.numel()):
                raise ValueError(
                    "h3_loop_mask_slice: scene %d needs canonical mask frames "
                    "%d..%d, but the tracked mask has only %d frames at 24 "
                    "fps." %
                    (index, start_frame, end_frame - 1,
                     int(indices.numel())))
            selected = timeline.index_select(
                0, indices[start_frame:end_frame])
            mode = "tracked mask slice"

        status = (
            "H3 loop %s scene %d: source mask batch %d frames -> timeline "
            "%d..%d (%d scene masks)." %
            (mode, index, mask_frames, start_frame,
             start_frame + scene_frames - 1, scene_frames))
        _LOG.info(status)
        return selected.contiguous(), scene_frames, status


NODE_CLASS_MAPPINGS = {
    "MiniMaxH3ContexLoopSourceAVTarget": MiniMaxH3ContexLoopSourceAVTarget,
    "MiniMaxH3ContexLoopMaskSlice": MiniMaxH3ContexLoopMaskSlice,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "MiniMaxH3ContexLoopSourceAVTarget": (
        "MiniMax H3 Masking · Loop Source AV Target"),
    "MiniMaxH3ContexLoopMaskSlice": (
        "MiniMax H3 Masking · Loop Mask Slice"),
}
