"""Two-ended MiniMax H3 audiovisual latent bridge.

The tail of one decoded source clip and the head of a second clip are encoded
into opposite ends of a normal H3 target latent.  A nested AV denoise mask
protects both source windows while allowing only the middle interval to be
generated.  Mask semantics follow ComfyUI PR #15375: 0 preserves the supplied
target latent and 1 denoises it.

This implementation adapts the GPL-3.0 masked bridge published by seitanism's
ComfyUI-H3-Motion-Context-MultiRef project for this pack's distinct node IDs,
runtime capability gate, categories, and error contract.
"""

from __future__ import annotations

import logging

import torch

from .masking_support import require_h3_mask_support
from .nodes import AUDIO_HZ, FPS, _pixel_frames, _resize


try:
    import torchaudio
except ImportError:  # pragma: no cover - exercised only on minimal installs
    torchaudio = None


_LOG = logging.getLogger("minimax_h3_context_loop.masked_bridge")


def _largest_h3_video_run(frames):
    frames = int(frames)
    if frames < 5:
        return 0
    return 5 + ((frames - 5) // 17) * 17


def _target_streams(latent):
    if not isinstance(latent, dict) or latent.get("samples") is None:
        raise ValueError("h3_masked_bridge: expected a target LATENT.")
    samples = latent["samples"]
    if hasattr(samples, "unbind"):
        parts = list(samples.unbind())
    elif isinstance(samples, (tuple, list)):
        parts = list(samples)
    else:
        raise ValueError(
            "h3_masked_bridge: expected a joint H3 AV latent, got %r." %
            type(samples))
    if len(parts) < 2:
        raise ValueError(
            "h3_masked_bridge: target latent has no joint video/audio streams.")
    video, audio = parts[:2]
    if video.ndim == 4:
        video = video.unsqueeze(0)
    if audio.ndim == 3:
        audio = audio.unsqueeze(0)
    if video.ndim != 5:
        raise ValueError(
            "h3_masked_bridge: video latent must be [B,C,T,H,W], got %s." %
            (tuple(video.shape),))
    if audio.ndim != 4:
        raise ValueError(
            "h3_masked_bridge: audio latent must be [B,C,channels,T], got %s."
            % (tuple(audio.shape),))
    if int(video.shape[0]) != 1 or int(audio.shape[0]) != 1:
        raise ValueError(
            "h3_masked_bridge: only MiniMax H3 batch size 1 is supported.")
    return video, audio


def _cfr_index_map(frame_count, source_fps, device):
    source_fps = float(source_fps)
    if source_fps <= 0.0:
        raise ValueError("h3_masked_bridge: source FPS must be greater than 0.")
    frame_count = int(frame_count)
    if frame_count < 1:
        raise ValueError("h3_masked_bridge: a source video has no frames.")
    output_count = max(1, int(round(frame_count * FPS / source_fps)))
    if output_count == frame_count and abs(source_fps - FPS) < 1e-6:
        return torch.arange(frame_count, device=device, dtype=torch.long)
    frame = torch.arange(output_count, device=device, dtype=torch.float64)
    time = (frame + 0.5) / FPS
    source = torch.round(time * source_fps - 0.5).to(torch.long)
    return source.clamp_(0, frame_count - 1)


def _stereo_audio(audio, target_rate, frame_count, label):
    if audio is None or not isinstance(audio, dict):
        raise ValueError("h3_masked_bridge: %s is required." % label)
    waveform = audio.get("waveform")
    if getattr(waveform, "ndim", 0) != 3:
        raise ValueError(
            "h3_masked_bridge: %s waveform must be [B,C,L], got %s." %
            (label, tuple(getattr(waveform, "shape", ()))))
    waveform = waveform[:1]
    channels = int(waveform.shape[1])
    if channels == 1:
        waveform = waveform.repeat(1, 2, 1)
    elif channels != 2:
        raise ValueError(
            "h3_masked_bridge: %s has %d channels; downmix it to stereo first."
            % (label, channels))
    source_rate = int(audio.get("sample_rate", 0))
    if source_rate <= 0:
        raise ValueError("h3_masked_bridge: %s has no valid sample rate." % label)
    if source_rate != int(target_rate):
        if torchaudio is None:
            raise RuntimeError(
                "h3_masked_bridge: %s is %d Hz but the audio VAE needs %d Hz "
                "and torchaudio is unavailable." %
                (label, source_rate, int(target_rate)))
        waveform = torchaudio.functional.resample(
            waveform, source_rate, int(target_rate))
    wanted = int(round(int(frame_count) / FPS * int(target_rate)))
    have = int(waveform.shape[-1])
    if have > wanted:
        waveform = waveform[..., :wanted]
    elif have < wanted:
        _LOG.warning(
            "h3_masked_bridge: %s is %d samples short of its video; padding "
            "only the source clip tail before selecting the protected window.",
            label, wanted - have)
        waveform = torch.nn.functional.pad(waveform, (0, wanted - have))
    return waveform


def _encode_video_window(vae, frames, width, height, crop, label):
    resized = _resize(frames, width, height, crop)
    encoded = vae.encode(resized)
    if getattr(encoded, "ndim", 0) != 5:
        raise ValueError(
            "h3_masked_bridge: %s video VAE returned %s; expected "
            "[B,C,T,H,W]." % (label, tuple(getattr(encoded, "shape", ()))))
    covered = _pixel_frames(int(encoded.shape[2]))
    if covered != int(frames.shape[0]):
        raise RuntimeError(
            "h3_masked_bridge: %s %d-frame window encoded to %d steps "
            "covering %d frames; refusing a phase-shifted seam." %
            (label, int(frames.shape[0]), int(encoded.shape[2]), covered))
    return encoded[:1]


def _encode_audio_window(audio_vae, waveform, preserve_frames, side, label):
    sample_rate = int(getattr(audio_vae, "audio_sample_rate", 32000))
    samples = int(round(int(preserve_frames) / FPS * sample_rate))
    if int(waveform.shape[-1]) < samples:
        raise ValueError(
            "h3_masked_bridge: %s is shorter than the %d-frame protected "
            "window." % (label, int(preserve_frames)))
    if side == "tail":
        window = waveform[..., -samples:]
    elif side == "head":
        window = waveform[..., :samples]
    else:  # pragma: no cover - private caller contract
        raise ValueError("h3_masked_bridge: invalid audio side %r." % side)
    encoded = audio_vae.encode(window.movedim(1, -1))
    if getattr(encoded, "ndim", 0) != 4:
        raise ValueError(
            "h3_masked_bridge: %s audio VAE returned %s; expected "
            "[B,C,channels,T]." %
            (label, tuple(getattr(encoded, "shape", ()))))
    exact_steps = int(preserve_frames) / FPS * AUDIO_HZ
    expected = int(round(exact_steps))
    if abs(exact_steps - expected) > 1e-9:
        _LOG.warning(
            "h3_masked_bridge: %d protected frames end between H3 audio "
            "ticks (%.6f -> %d steps); 39/90/141/... are exact AV boundaries.",
            int(preserve_frames), exact_steps, expected)
    got = int(encoded.shape[-1])
    if got < expected:
        raise RuntimeError(
            "h3_masked_bridge: %s needs %d audio steps but the VAE produced "
            "%d." % (label, expected, got))
    if got > expected:
        encoded = (encoded[..., -expected:] if side == "tail"
                   else encoded[..., :expected])
    return encoded[:1]


class MiniMaxH3ContexMaskedAVBridge:
    """Protect source AV windows at both ends and generate only the middle."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "latent": ("LATENT", {
                    "tooltip": "Empty joint H3 AV target latent for the full "
                               "bridge duration."}),
                "vae": ("VAE", {"tooltip": "MiniMax H3 video VAE."}),
                "audio_vae": ("VAE", {"tooltip": "MiniMax H3 audio VAE."}),
                "start_frames": ("IMAGE", {
                    "tooltip": "First source clip. Its final protected window "
                               "becomes the bridge prefix."}),
                "end_frames": ("IMAGE", {
                    "tooltip": "Second source clip. Its initial protected "
                               "window becomes the bridge suffix."}),
                "start_fps": ("FLOAT", {
                    "default": 24.0, "min": 0.001, "max": 1000.0,
                    "step": 0.001,
                    "tooltip": "Actual frame rate represented by "
                               "start_frames; it is converted to H3's 24 fps "
                               "timeline before selecting the protected tail.",
                }),
                "end_fps": ("FLOAT", {
                    "default": 24.0, "min": 0.001, "max": 1000.0,
                    "step": 0.001,
                    "tooltip": "Actual frame rate represented by end_frames; "
                               "it is converted to H3's 24 fps timeline before "
                               "selecting the protected head.",
                }),
                "preserve_frames": ("INT", {
                    "default": 39, "min": 5, "max": 9999,
                    "tooltip": "Exact H3 run: 5, 22, 39, 56, ... . Use 39 "
                               "for an exact 65-step AV boundary."}),
                "crop": (["disabled", "center"], {
                    "default": "center",
                    "tooltip": "Resize policy for both endpoint videos: "
                               "disabled stretches to the target canvas; "
                               "center preserves aspect ratio and center-crops.",
                }),
            },
            "optional": {
                "start_audio": ("AUDIO", {
                    "tooltip": "Optional audio synchronized with the first "
                               "clip. When absent, H3 generates the bridge's "
                               "opening audio instead of protecting silence."}),
                "end_audio": ("AUDIO", {
                    "tooltip": "Optional audio synchronized with the second "
                               "clip. When absent, H3 generates the bridge's "
                               "ending audio instead of protecting silence."}),
            },
        }

    RETURN_TYPES = ("LATENT", "INT", "INT")
    RETURN_NAMES = ("latent", "middle_frames", "preserve_frames")
    OUTPUT_TOOLTIPS = (
        "Full bridge target with protected source AV windows at both ends "
        "and a denoised middle.",
        "Number of picture frames left for the model to generate between "
        "the two protected endpoints.",
        "Actual number of protected picture frames copied from each endpoint.",
    )
    FUNCTION = "prepare"
    CATEGORY = "conditioning/minimax/context_loop/masking"
    DESCRIPTION = (
        "Construct a true two-ended H3 AV bridge target: preserve the first "
        "clip's tail and second clip's head, then denoise only the middle.")

    def prepare(
        self,
        latent,
        vae,
        audio_vae,
        start_frames,
        start_audio=None,
        end_frames=None,
        end_audio=None,
        start_fps=24.0,
        end_fps=24.0,
        preserve_frames=39,
        crop="center",
    ):
        require_h3_mask_support("two-ended masked AV bridge")
        target_video, target_audio = _target_streams(latent)
        target_frames = _pixel_frames(int(target_video.shape[2]))
        if _largest_h3_video_run(target_frames) != target_frames:
            raise RuntimeError(
                "h3_masked_bridge: target covers %d frames, not an exact H3 "
                "run." % target_frames)
        expected_audio = int(round(target_frames / FPS * AUDIO_HZ))
        if int(target_audio.shape[-1]) != expected_audio:
            raise RuntimeError(
                "h3_masked_bridge: target has %d audio steps for %d frames; "
                "expected %d." %
                (int(target_audio.shape[-1]), target_frames, expected_audio))

        for frames, label in ((start_frames, "start_frames"),
                              (end_frames, "end_frames")):
            if getattr(frames, "ndim", 0) != 4 or int(frames.shape[0]) < 1:
                raise ValueError(
                    "h3_masked_bridge: %s must be IMAGE [N,H,W,C]." % label)
        start_idx = _cfr_index_map(
            int(start_frames.shape[0]), start_fps, start_frames.device)
        end_idx = _cfr_index_map(
            int(end_frames.shape[0]), end_fps, end_frames.device)

        protected = int(preserve_frames)
        if protected < 5 or _largest_h3_video_run(protected) != protected:
            raise ValueError(
                "h3_masked_bridge: preserve_frames must be an exact H3 video "
                "run (5, 22, 39, 56, ...); got %d." % protected)
        if int(start_idx.numel()) < protected:
            raise ValueError(
                "h3_masked_bridge: first clip has %d canonical frames; need "
                "%d." % (int(start_idx.numel()), protected))
        if int(end_idx.numel()) < protected:
            raise ValueError(
                "h3_masked_bridge: second clip has %d canonical frames; need "
                "%d." % (int(end_idx.numel()), protected))
        if 2 * protected >= target_frames:
            raise ValueError(
                "h3_masked_bridge: protected windows consume the complete "
                "%d-frame target." % target_frames)

        width = int(target_video.shape[4]) * 16
        height = int(target_video.shape[3]) * 16
        start_tail = start_frames.index_select(0, start_idx[-protected:])
        end_head = end_frames.index_select(0, end_idx[:protected])
        start_video = _encode_video_window(
            vae, start_tail, width, height, crop, "first clip tail")
        end_video = _encode_video_window(
            vae, end_head, width, height, crop, "second clip head")
        video_steps = int(start_video.shape[2])
        if int(end_video.shape[2]) != video_steps:
            raise RuntimeError(
                "h3_masked_bridge: protected video windows encoded to "
                "different lengths.")
        suffix_step = int(target_video.shape[2]) - video_steps
        if suffix_step % 5:
            raise RuntimeError(
                "h3_masked_bridge: suffix begins at latent phase %d; refusing "
                "an out-of-phase protected endpoint." % (suffix_step % 5))

        vae_rate = int(getattr(audio_vae, "audio_sample_rate", 32000))
        start_audio_latent = None
        if start_audio is not None:
            start_waveform = _stereo_audio(
                start_audio, vae_rate, int(start_idx.numel()), "start_audio")
            start_audio_latent = _encode_audio_window(
                audio_vae, start_waveform, protected, "tail",
                "first clip tail")
        else:
            _LOG.info(
                "h3_masked_bridge: start_audio is absent; opening audio stays "
                "unmasked for H3 generation.")
        end_audio_latent = None
        if end_audio is not None:
            end_waveform = _stereo_audio(
                end_audio, vae_rate, int(end_idx.numel()), "end_audio")
            end_audio_latent = _encode_audio_window(
                audio_vae, end_waveform, protected, "head", "second clip head")
        else:
            _LOG.info(
                "h3_masked_bridge: end_audio is absent; ending audio stays "
                "unmasked for H3 generation.")
        start_audio_steps = (int(start_audio_latent.shape[-1])
                             if start_audio_latent is not None else 0)
        end_audio_steps = (int(end_audio_latent.shape[-1])
                           if end_audio_latent is not None else 0)
        if (start_audio_latent is not None and end_audio_latent is not None
                and end_audio_steps != start_audio_steps):
            raise RuntimeError(
                "h3_masked_bridge: protected audio windows encoded to "
                "different lengths.")

        out_video = target_video.clone()
        out_audio = target_audio.clone()
        start_video = start_video.to(out_video)
        end_video = end_video.to(out_video)
        if (tuple(start_video.shape[1:2] + start_video.shape[3:]) !=
                tuple(out_video.shape[1:2] + out_video.shape[3:])):
            raise ValueError(
                "h3_masked_bridge: first video latent shape does not match "
                "the target canvas.")
        if (tuple(end_video.shape[1:2] + end_video.shape[3:]) !=
                tuple(out_video.shape[1:2] + out_video.shape[3:])):
            raise ValueError(
                "h3_masked_bridge: second video latent shape does not match "
                "the target canvas.")
        if start_audio_latent is not None:
            start_audio_latent = start_audio_latent.to(out_audio)
            if tuple(start_audio_latent.shape[1:3]) != tuple(
                    out_audio.shape[1:3]):
                raise ValueError(
                    "h3_masked_bridge: first audio latent shape does not match "
                    "the H3 target.")
        if end_audio_latent is not None:
            end_audio_latent = end_audio_latent.to(out_audio)
            if tuple(end_audio_latent.shape[1:3]) != tuple(
                    out_audio.shape[1:3]):
                raise ValueError(
                    "h3_masked_bridge: second audio latent shape does not "
                    "match the H3 target.")

        out_video[:, :, :video_steps] = start_video
        out_video[:, :, -video_steps:] = end_video
        video_mask = torch.ones(
            (1, 1, int(out_video.shape[2]), int(out_video.shape[3]),
             int(out_video.shape[4])),
            device=out_video.device, dtype=torch.float32)
        audio_mask = torch.ones(
            (1, 1, int(out_audio.shape[2]), int(out_audio.shape[3])),
            device=out_audio.device, dtype=torch.float32)
        video_mask[:, :, :video_steps] = 0.0
        video_mask[:, :, -video_steps:] = 0.0
        if start_audio_latent is not None:
            out_audio[..., :start_audio_steps] = start_audio_latent
            audio_mask[..., :start_audio_steps] = 0.0
        if end_audio_latent is not None:
            out_audio[..., -end_audio_steps:] = end_audio_latent
            audio_mask[..., -end_audio_steps:] = 0.0

        import comfy.nested_tensor
        output = latent.copy()
        output["samples"] = comfy.nested_tensor.NestedTensor(
            (out_video, out_audio))
        output["noise_mask"] = comfy.nested_tensor.NestedTensor(
            (video_mask, audio_mask))
        middle_frames = target_frames - 2 * protected
        _LOG.info(
            "h3_masked_bridge: %d-frame target at %dx%d; preserve %d frames "
            "(%d video / %d+%d audio steps) at the two ends; generate %d "
            "frames.",
            target_frames, width, height, protected, video_steps,
            start_audio_steps, end_audio_steps, middle_frames)
        return output, middle_frames, protected


NODE_CLASS_MAPPINGS = {
    "MiniMaxH3ContexMaskedAVBridge": MiniMaxH3ContexMaskedAVBridge,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "MiniMaxH3ContexMaskedAVBridge": (
        "MiniMax H3 Masking · Two-Clip AV Bridge"),
}
