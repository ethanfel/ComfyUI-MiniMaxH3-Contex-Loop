"""Public general masked-target nodes for MiniMax H3 video editing."""

from __future__ import annotations

import torch
import torch.nn.functional as F

from .masking_ops import (
    GRID_MODES,
    H3_PIXEL_CELL,
    H3_VIDEO_FPS,
    MASK_CONVERSION_MODES,
    floor_h3_frame_count,
    normalize_comfy_mask,
    quantize_h3_pixel_mask,
    reduce_h3_mask_to_video_latent,
    resize_mask_to_video_latent,
    temporal_audio_mask,
    trim_audio_to_frames,
)
from .masking_support import require_h3_mask_support


MASK_MEANINGS = ("white = generate", "white = preserve")
AUDIO_MASK_MODES = (
    "preserve source audio",
    "generate all audio",
    "follow video mask",
    "custom audio mask",
)


def _nested_parts(value, label):
    if isinstance(value, (tuple, list)):
        return list(value)
    if bool(getattr(value, "is_nested", False)) and hasattr(value, "unbind"):
        return list(value.unbind())
    raise ValueError(
        "%s must be a nested H3 video/audio value, not a single tensor." %
        label
    )


def _target_streams(latent):
    if not isinstance(latent, dict) or latent.get("samples") is None:
        raise ValueError("H3 Masked Target needs a LATENT containing samples.")
    streams = _nested_parts(latent["samples"], "H3 target latent")
    if len(streams) < 2:
        raise ValueError(
            "H3 Masked Target needs both video and audio streams. Encode the "
            "source media and combine it as a joint AV latent first."
        )
    video, audio = streams[:2]
    if not isinstance(video, torch.Tensor) or video.ndim != 5:
        raise ValueError(
            "H3 target video latent must be [B,C,T,H,W], got %s." %
            (list(getattr(video, "shape", ())),)
        )
    if not isinstance(audio, torch.Tensor) or audio.ndim != 4:
        raise ValueError(
            "H3 target audio latent must be [B,C,channels,T], got %s." %
            (list(getattr(audio, "shape", ())),)
        )
    if int(video.shape[0]) != 1 or int(audio.shape[0]) != 1:
        raise ValueError("H3 masked targets currently support batch size 1.")
    return video, audio


def _existing_video_mask(value, video):
    if value.ndim == 5:
        work = value[:, :1].to(device=video.device, dtype=torch.float32)
        if int(work.shape[0]) != 1:
            raise ValueError("Existing H3 video mask has an unsupported batch.")
        if tuple(work.shape[2:]) != tuple(video.shape[2:]):
            work = F.interpolate(
                work,
                size=tuple(int(v) for v in video.shape[2:]),
                mode="trilinear",
                align_corners=False,
            )
        return work.clamp(0.0, 1.0).contiguous()
    if value.ndim == 4 and int(value.shape[0]) == 1:
        return _existing_video_mask(value.unsqueeze(1), video)
    return resize_mask_to_video_latent(value, video)


def _existing_audio_mask(value, audio):
    work = value.to(device=audio.device, dtype=torch.float32)
    if work.ndim == 1:
        work = work[None, None, None]
    elif work.ndim == 2:
        work = work[None, None]
    elif work.ndim == 3:
        work = work.unsqueeze(0)
    if work.ndim != 4 or int(work.shape[0]) != 1:
        raise ValueError(
            "Existing H3 audio mask must broadcast to [1,C,channels,T]; got "
            "%s." % (list(work.shape),)
        )
    work = work.amax(dim=1, keepdim=True)
    if int(work.shape[2]) != int(audio.shape[2]):
        work = work.amax(dim=2, keepdim=True).expand(
            1, 1, int(audio.shape[2]), int(work.shape[3]))
    if int(work.shape[-1]) != int(audio.shape[-1]):
        lead = int(work.shape[2])
        work = F.interpolate(
            work.reshape(lead, 1, int(work.shape[-1])),
            size=int(audio.shape[-1]),
            mode="linear",
            align_corners=False,
        ).reshape(1, 1, lead, int(audio.shape[-1]))
    return work.clamp(0.0, 1.0).contiguous()


def _compose_existing_masks(latent, video_mask, audio_mask, video, audio):
    existing = latent.get("noise_mask")
    if existing is None:
        return video_mask, audio_mask, False
    parts = _nested_parts(existing, "Existing H3 noise mask")
    if len(parts) < 2:
        raise ValueError(
            "Existing H3 noise mask has no audio component and cannot be "
            "composed safely."
        )
    old_video = _existing_video_mask(parts[0], video)
    old_audio = _existing_audio_mask(parts[1], audio)
    # Preserve wins. This lets a spatial edit compose with masked_av's exact
    # protected prefix regardless of which node executes first.
    return (
        torch.minimum(video_mask, old_video),
        torch.minimum(audio_mask, old_audio),
        True,
    )


class MiniMaxH3ContexTrimSourceAV:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "frames": ("IMAGE", {
                    "tooltip": "Source video frames. Trailing frames are "
                               "dropped to the largest valid H3 17k+5 length; "
                               "frames are never padded or resized.",
                }),
            },
            "optional": {
                "audio": ("AUDIO", {
                    "tooltip": "Optional synchronized source audio, trimmed "
                               "to the returned frame duration at 24 fps.",
                }),
            },
        }

    RETURN_TYPES = ("IMAGE", "AUDIO", "INT", "STRING")
    RETURN_NAMES = ("trimmed_frames", "trimmed_audio", "h3_length",
                    "trim_info")
    OUTPUT_TOOLTIPS = (
        "Source frames trimmed to the largest valid H3 17k+5 length.",
        "Synchronized audio trimmed to the returned frame duration, or an "
        "empty output when no audio was connected.",
        "The valid H3 frame count represented by both returned streams.",
        "Human-readable summary of the frame and audio trimming performed.",
    )
    FUNCTION = "trim"
    CATEGORY = "conditioning/minimax/context_loop/masking"
    DESCRIPTION = ("Trim source video and optional audio to the largest H3 "
                   "17k+5 run without inventing frames or silence.")

    def trim(self, frames, audio=None):
        if not isinstance(frames, torch.Tensor) or frames.ndim != 4:
            raise ValueError(
                "H3 source AV trim expects IMAGE [T,H,W,C], got %s." %
                (list(getattr(frames, "shape", ())),)
            )
        source_count = int(frames.shape[0])
        h3_length = floor_h3_frame_count(source_count)
        trimmed_frames = frames[:h3_length]
        trimmed_audio, target_samples = trim_audio_to_frames(audio, h3_length)
        dropped = source_count - h3_length
        duration = h3_length / float(H3_VIDEO_FPS)
        audio_text = "no audio connected"
        if trimmed_audio is not None:
            actual = int(trimmed_audio["waveform"].shape[-1])
            sample_rate = int(trimmed_audio["sample_rate"])
            audio_text = "audio %d/%d samples at %d Hz" % (
                actual, target_samples, sample_rate)
            if actual < target_samples:
                audio_text += " (source shorter; no silence added)"
        info = (
            "H3 source trim: %d -> %d frames; dropped %d; %.3fs at 24 fps; %s."
            % (source_count, h3_length, dropped, duration, audio_text)
        )
        return trimmed_frames, trimmed_audio, h3_length, info


class MiniMaxH3ContexMaskedTarget:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "target_latent": ("LATENT", {
                    "tooltip": "Joint source video/audio latent used as the "
                               "actual H3 target. Known regions are preserved "
                               "from this latent; do not add the same source "
                               "again merely as a video reference.",
                }),
                "mask": ("MASK", {
                    "tooltip": "Static or per-frame video-space mask. It is "
                               "mapped to H3's causal video-latent frames and "
                               "2x2 latent-token cells. Exact mode accepts "
                               "one static mask or one mask per source frame.",
                }),
                "mask_meaning": (list(MASK_MEANINGS), {
                    "default": MASK_MEANINGS[0],
                    "tooltip": "Choose whether white pixels regenerate or "
                               "remain protected.",
                }),
                "audio_mode": (list(AUDIO_MASK_MODES), {
                    "default": AUDIO_MASK_MODES[0],
                    "tooltip": "Preserve or generate all source audio, map "
                               "the video mask onto time, or use the optional "
                               "custom audio mask.",
                }),
            },
            "optional": {
                "audio_mask": ("MASK", {
                    "tooltip": "Used only by custom audio mask. Spatial "
                               "dimensions are reduced; white time regions "
                               "generate and black regions remain protected.",
                }),
                "mask_conversion": (list(MASK_CONVERSION_MODES), {
                    "default": MASK_CONVERSION_MODES[0],
                    "tooltip": "H3 exact maps pixel masks with the video "
                               "VAE's causal 1/4/4/4/4 frame groups and "
                               "2x2 latent-token max coverage. Legacy "
                               "trilinear retains the older interpolated "
                               "conversion for workflow comparison. Changing "
                               "this changes generation; update the Plan's "
                               "generation fingerprint before resuming.",
                }),
            },
        }

    RETURN_TYPES = ("LATENT", "STRING")
    RETURN_NAMES = ("masked_target", "mask_info")
    OUTPUT_TOOLTIPS = (
        "Copy of target_latent carrying the composed H3 video and audio "
        "denoise mask.",
        "Summary of the latent dimensions and generated percentages for "
        "each stream.",
    )
    FUNCTION = "apply"
    CATEGORY = "conditioning/minimax/context_loop/masking"
    DESCRIPTION = ("Attach causal, token-aligned H3 video/audio denoise masks "
                   "to a real source AV target for inpainting and temporal "
                   "edits. Ordinary AV extension needs no user mask.")

    def apply(
        self,
        target_latent,
        mask,
        mask_meaning,
        audio_mode,
        audio_mask=None,
        mask_conversion=MASK_CONVERSION_MODES[0],
    ):
        require_h3_mask_support("general masked-target generation")
        video, audio = _target_streams(target_latent)

        generation_mask = normalize_comfy_mask(mask)
        if mask_meaning == "white = preserve":
            generation_mask = 1.0 - generation_mask
        elif mask_meaning != "white = generate":
            raise ValueError("Unknown H3 mask meaning %r." % mask_meaning)
        if mask_conversion == MASK_CONVERSION_MODES[0]:
            video_mask = reduce_h3_mask_to_video_latent(
                generation_mask, video)
            conversion_summary = "H3 exact causal/token max"
        elif mask_conversion == MASK_CONVERSION_MODES[1]:
            video_mask = resize_mask_to_video_latent(generation_mask, video)
            conversion_summary = "legacy trilinear"
        else:
            raise ValueError(
                "Unknown H3 mask conversion mode %r." % mask_conversion)

        if audio_mode == "preserve source audio":
            out_audio_mask = torch.zeros(
                (1, 1, int(audio.shape[2]), int(audio.shape[3])),
                device=audio.device,
                dtype=torch.float32,
            )
        elif audio_mode == "generate all audio":
            out_audio_mask = torch.ones(
                (1, 1, int(audio.shape[2]), int(audio.shape[3])),
                device=audio.device,
                dtype=torch.float32,
            )
        elif audio_mode == "follow video mask":
            out_audio_mask = temporal_audio_mask(generation_mask, audio)
        elif audio_mode == "custom audio mask":
            if audio_mask is None:
                raise ValueError(
                    "custom audio mask mode requires the optional audio_mask "
                    "input. White generates; black preserves."
                )
            out_audio_mask = temporal_audio_mask(audio_mask, audio)
        else:
            raise ValueError("Unknown H3 audio mask mode %r." % audio_mode)

        video_mask, out_audio_mask, composed = _compose_existing_masks(
            target_latent,
            video_mask,
            out_audio_mask,
            video,
            audio,
        )

        import comfy.nested_tensor

        output = target_latent.copy()
        output["noise_mask"] = comfy.nested_tensor.NestedTensor(
            (video_mask, out_audio_mask))
        video_percent = 100.0 * float(video_mask.mean().item())
        audio_percent = 100.0 * float(out_audio_mask.mean().item())
        info = (
            "H3 masked target: latent video %dx%dx%d, generate %.2f%%; "
            "audio %d steps, generate %.2f%%; %s; mask %s; existing mask %s."
            % (
                int(video.shape[4]),
                int(video.shape[3]),
                int(video.shape[2]),
                video_percent,
                int(audio.shape[-1]),
                audio_percent,
                audio_mode,
                conversion_summary,
                "intersected" if composed else "none",
            )
        )
        return output, info


class MiniMaxH3ContexMaskGridPreview:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image": ("IMAGE", {
                    "tooltip": "Exact resized H3 canvas used by the video "
                               "VAE. Width and height must be divisible by 32.",
                }),
                "mask": ("MASK", {
                    "tooltip": "Static or tracked ComfyUI mask interpreted "
                               "using mask_meaning.",
                }),
                "cell_selection": (list(GRID_MODES), {
                    "default": GRID_MODES[0],
                    "tooltip": "Runtime exact matches H3 latent reduction. "
                               "Coverage modes provide deliberate conservative "
                               "or strict alternatives.",
                }),
                "cell_adjust": ("INT", {
                    "default": 0, "min": -8, "max": 8, "step": 1,
                    "tooltip": "Grow or shrink by complete 32x32 H3 cells.",
                }),
                "preview_frame": ("INT", {
                    "default": 0, "min": 0, "max": 10000, "step": 1,
                    "tooltip": "Frame displayed by grid_preview. The snapped "
                               "MASK output still contains the complete batch.",
                }),
                "overlay_opacity": ("FLOAT", {
                    "default": 0.38, "min": 0.0, "max": 1.0, "step": 0.01,
                    "tooltip": "Opacity of the orange snapped-generation "
                               "overlay in grid_preview.",
                }),
                "show_grid": ("BOOLEAN", {
                    "default": True,
                    "tooltip": "Draw the effective 32x32 H3 source-pixel "
                               "cell grid over the preview.",
                }),
                "show_source_outline": ("BOOLEAN", {
                    "default": True,
                    "tooltip": "Outline the original unsnapped mask so its "
                               "difference from the effective mask is visible.",
                }),
            },
            "optional": {
                "mask_meaning": (list(MASK_MEANINGS), {
                    "default": MASK_MEANINGS[0],
                    "tooltip": "Use the same white-pixel convention here "
                               "and on Apply Target Mask. The overlay always "
                               "shows the effective generation region.",
                }),
            },
        }

    RETURN_TYPES = ("MASK", "IMAGE", "STRING")
    RETURN_NAMES = ("snapped_mask", "grid_preview", "grid_info")
    OUTPUT_TOOLTIPS = (
        "Complete mask batch snapped to H3's effective causal 32x32 "
        "source-pixel cells, using the selected white-pixel convention.",
        "Selected source frame with the snapped mask and optional grid or "
        "source outline overlaid.",
        "Summary of the selected frame, grid dimensions, and snapped-mask "
        "coverage.",
    )
    FUNCTION = "preview"
    CATEGORY = "conditioning/minimax/context_loop/masking"
    DESCRIPTION = ("Preview and snap a video mask to H3's effective 32x32 "
                   "source-pixel generation cells.")

    def preview(
        self,
        image,
        mask,
        cell_selection,
        cell_adjust,
        preview_frame,
        overlay_opacity,
        show_grid,
        show_source_outline,
        mask_meaning=MASK_MEANINGS[0],
    ):
        if not isinstance(image, torch.Tensor) or image.ndim != 4:
            raise ValueError(
                "H3 mask preview expects IMAGE [frames,H,W,C], got %s." %
                (list(getattr(image, "shape", ())),)
            )
        frames, height, width = (int(v) for v in image.shape[:3])
        generation_mask = normalize_comfy_mask(mask)
        if mask_meaning == "white = preserve":
            generation_mask = 1.0 - generation_mask
        elif mask_meaning != "white = generate":
            raise ValueError("Unknown H3 mask meaning %r." % mask_meaning)
        raw, snapped_generation, cells = quantize_h3_pixel_mask(
            generation_mask,
            frames,
            height,
            width,
            mode=cell_selection,
            cell_adjust=int(cell_adjust),
        )
        selected_frame = min(max(0, int(preview_frame)), frames - 1)
        preview = image[selected_frame:selected_frame + 1, ..., :3].to(
            torch.float32).clamp(0.0, 1.0).clone()
        selected = snapped_generation[selected_frame].to(
            device=preview.device, dtype=preview.dtype)[None, ..., None]
        orange = torch.tensor(
            [1.0, 0.18, 0.0], device=preview.device, dtype=preview.dtype)
        opacity = float(overlay_opacity)
        preview = preview * (1.0 - selected * opacity) + (
            orange * selected * opacity)

        if bool(show_grid):
            grid = torch.zeros(
                (height, width), device=preview.device, dtype=torch.bool)
            grid[::H3_PIXEL_CELL, :] = True
            grid[:, ::H3_PIXEL_CELL] = True
            grid[-1, :] = True
            grid[:, -1] = True
            cyan = torch.tensor(
                [0.0, 0.82, 1.0], device=preview.device,
                dtype=preview.dtype)
            preview[0, grid] = preview[0, grid] * 0.28 + cyan * 0.72

        if bool(show_source_outline):
            source = (raw[selected_frame:selected_frame + 1].to(
                device=preview.device) >= 0.5).to(preview.dtype)
            dilated = F.max_pool2d(
                source, kernel_size=3, stride=1, padding=1)
            eroded = 1.0 - F.max_pool2d(
                1.0 - source, kernel_size=3, stride=1, padding=1)
            outline = ((dilated - eroded) > 0).movedim(1, -1)
            preview = torch.where(outline, torch.ones_like(preview), preview)

        counts = (cells > 0).sum(
            dim=(1, 2, 3)).to(torch.int64).cpu().tolist()
        cells_per_frame = int(cells.shape[-2]) * int(cells.shape[-1])
        if len(counts) <= 8:
            count_text = ", ".join(str(value) for value in counts)
        else:
            count_text = "min %d, max %d, total %d" % (
                min(counts), max(counts), sum(counts))
        info = (
            "H3 grid: %dx%d cells at 32x32 pixels; selected/frame %s / %d; "
            "mode %s; %s; adjust %+d; preview frame %d/%d."
            % (
                int(cells.shape[-1]),
                int(cells.shape[-2]),
                count_text,
                cells_per_frame,
                cell_selection,
                mask_meaning,
                int(cell_adjust),
                selected_frame,
                frames - 1,
            )
        )
        snapped = (
            1.0 - snapped_generation
            if mask_meaning == "white = preserve"
            else snapped_generation
        )
        return snapped.contiguous(), preview, info


NODE_CLASS_MAPPINGS = {
    "MiniMaxH3ContexTrimSourceAV": MiniMaxH3ContexTrimSourceAV,
    "MiniMaxH3ContexMaskedTarget": MiniMaxH3ContexMaskedTarget,
    "MiniMaxH3ContexMaskGridPreview": MiniMaxH3ContexMaskGridPreview,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "MiniMaxH3ContexTrimSourceAV": "MiniMax H3 Masking · Trim Source AV",
    "MiniMaxH3ContexMaskedTarget": "MiniMax H3 Masking · Apply Target Mask",
    "MiniMaxH3ContexMaskGridPreview": "MiniMax H3 Masking · Grid Preview",
}
