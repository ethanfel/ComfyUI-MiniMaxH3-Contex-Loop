#!/usr/bin/env python3
"""CPU regression for exact master-audio latent masking."""

import os
import sys
import types

import torch


TESTS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, TESTS)

import _masked_prefix_unit_test as harness  # noqa: E402


def main():
    harness._install_comfy_stubs()
    package = types.ModuleType(harness.PACKAGE)
    package.__path__ = [harness.ROOT]
    sys.modules[harness.PACKAGE] = package
    harness._load("patch_layout")
    harness._load("patch_payload")
    nodes = harness._load("nodes")
    harness._load("masked_context")
    audio_context = harness._load("master_audio_context")
    audio_context.require_h3_mask_support = lambda _operation: True

    target_frames = 141
    video_steps = 42
    audio_steps = 235
    assert nodes._pixel_frames(video_steps) == target_frames
    target_video = torch.zeros((1, 16, video_steps, 2, 4))
    target_audio = torch.zeros((1, 32, 2, audio_steps))
    latent = {
        "samples": harness.NestedTensor((target_video, target_audio)),
    }

    previous_frames = torch.rand((120, 32, 64, 3))
    master_audio = {
        "waveform": torch.rand((1, 2, 32_000 * 30)),
        "sample_rate": 32_000,
    }

    class VideoVAE:
        def encode(self, frames):
            count = int(frames.shape[0])
            steps = max(1, (count - 5) // 17 * 5 + 2)
            return torch.full((1, 16, steps, 2, 4), 0.25)

    class AudioVAE:
        audio_sample_rate = 32_000

        def encode(self, waveform):
            steps = round(int(waveform.shape[1]) / 32_000 * 40)
            return torch.full((1, 32, 2, steps), 0.5)

    output, prefix, clip_audio = (
        audio_context.MiniMaxH3ContexMasterAudioMaskedAV().prepare(
            latent,
            AudioVAE(),
            master_audio,
            clip_start_seconds=3.25,
            context_length=39,
            source_fps=24.0,
            crop="disabled",
            vae=VideoVAE(),
            source_frames=previous_frames,
        ))
    video, audio = output["samples"].unbind()
    video_mask, audio_mask = output["noise_mask"].unbind()
    assert prefix == 39
    assert torch.allclose(
        video[:, :, :12], torch.full_like(video[:, :, :12], 0.25))
    assert not torch.count_nonzero(video[:, :, 12:])
    assert torch.allclose(audio, torch.full_like(audio, 0.5))
    assert not torch.count_nonzero(video_mask[:, :, :12])
    assert torch.all(video_mask[:, :, 12:] == 1.0)
    assert not torch.count_nonzero(audio_mask)
    assert clip_audio["sample_rate"] == 32_000
    assert int(clip_audio["waveform"].shape[-1]) == round(
        target_frames / 24 * 32_000)

    # Preferred live chaining copies the sampled H3 video tail directly. The
    # source latent's audio stream must not replace the authoritative master.
    source_video = torch.arange(
        video_steps, dtype=torch.float32).reshape(
            1, 1, video_steps, 1, 1).expand_as(target_video).clone()
    source_audio = torch.full_like(target_audio, 0.9)
    source_latent = {
        "samples": harness.NestedTensor((source_video, source_audio)),
    }
    live, live_prefix, _ = (
        audio_context.MiniMaxH3ContexMasterAudioMaskedAV().prepare(
            latent,
            AudioVAE(),
            master_audio,
            clip_start_seconds=3.25,
            context_length=39,
            source_latent=source_latent,
        ))
    live_video, live_audio = live["samples"].unbind()
    live_video_mask, live_audio_mask = live["noise_mask"].unbind()
    assert live_prefix == 39
    assert torch.equal(live_video[:, :, :12], source_video[:, :, -12:])
    assert not torch.count_nonzero(live_video[:, :, 12:])
    assert torch.allclose(live_audio, torch.full_like(live_audio, 0.5))
    assert not torch.count_nonzero(live_video_mask[:, :, :12])
    assert torch.all(live_video_mask[:, :, 12:] == 1.0)
    assert not torch.count_nonzero(live_audio_mask)

    try:
        audio_context.MiniMaxH3ContexMasterAudioMaskedAV().prepare(
            latent,
            AudioVAE(),
            master_audio,
            context_length=39,
            vae=VideoVAE(),
            source_frames=previous_frames,
            source_latent=source_latent,
        )
    except ValueError as exc:
        assert "either source_latent or source_frames" in str(exc)
    else:
        raise AssertionError("both master-audio video sources were accepted")

    assert "source_latent" in (
        audio_context.MiniMaxH3ContexMasterAudioMaskedAV.INPUT_TYPES()[
            "optional"])
    assert "voice" in (
        audio_context.MiniMaxH3ContexMasterAudioMaskedAV.INPUT_TYPES()[
            "optional"])
    assert audio_context.MiniMaxH3ContexMasterAudioMaskedAV.INPUT_TYPES()[
        "required"]["preroll_seconds"][1]["default"] == 0.0

    # Chain Context may already own the protected visual prefix. Replacing
    # the audio target must retain that video mask while making the complete
    # current master-audio stream protected.
    existing_video_mask = torch.ones((1, 1, video_steps, 2, 4))
    existing_video_mask[:, :, :7] = 0.0
    existing_audio_mask = torch.ones((1, 1, 2, audio_steps))
    chained_latent = {
        "samples": harness.NestedTensor((target_video, target_audio)),
        "noise_mask": harness.NestedTensor((
            existing_video_mask, existing_audio_mask)),
    }
    chained, chained_prefix, _ = (
        audio_context.MiniMaxH3ContexMasterAudioMaskedAV().prepare(
            chained_latent,
            AudioVAE(),
            master_audio,
            clip_start_seconds=3.25,
            context_length=0,
        ))
    chained_video_mask, chained_audio_mask = chained["noise_mask"].unbind()
    assert chained_prefix == 0
    assert not torch.count_nonzero(chained_video_mask[:, :, :7])
    assert torch.all(chained_video_mask[:, :, 7:] == 1.0)
    assert not torch.count_nonzero(chained_audio_mask)

    first, first_prefix, _ = (
        audio_context.MiniMaxH3ContexMasterAudioMaskedAV().prepare(
            latent,
            AudioVAE(),
            master_audio,
            clip_start_seconds=0.0,
            context_length=0,
        ))
    first_video_mask, first_audio_mask = first["noise_mask"].unbind()
    assert first_prefix == 0
    assert torch.all(first_video_mask == 1.0)
    assert not torch.count_nonzero(first_audio_mask)

    class FloorAudioVAE:
        """Simulate an audio encoder that floors its temporal output."""

        audio_sample_rate = 32_000

        def __init__(self):
            self.encoded_samples = []

        def encode(self, waveform):
            samples = int(waveform.shape[1])
            self.encoded_samples.append(samples)
            steps = int(samples / self.audio_sample_rate * 40)
            return torch.full((1, 32, 2, steps), 0.75)

    rounding_frames = 124
    rounding_video_steps = 37
    rounding_audio_steps = 207
    assert nodes._pixel_frames(rounding_video_steps) == rounding_frames
    rounding_latent = {
        "samples": harness.NestedTensor((
            torch.zeros((1, 16, rounding_video_steps, 2, 4)),
            torch.zeros((1, 32, 2, rounding_audio_steps)),
        )),
    }
    floor_vae = FloorAudioVAE()
    rounded, rounded_prefix, rounded_clip_audio = (
        audio_context.MiniMaxH3ContexMasterAudioMaskedAV().prepare(
            rounding_latent,
            floor_vae,
            master_audio,
            clip_start_seconds=1.0,
            context_length=0,
        ))
    _, rounded_audio = rounded["samples"].unbind()
    _, rounded_audio_mask = rounded["noise_mask"].unbind()
    picture_samples = round(rounding_frames / 24 * 32_000)
    grid_samples = int(rounding_audio_steps / 40 * 32_000)
    assert floor_vae.encoded_samples == [grid_samples]
    assert grid_samples > picture_samples
    assert int(rounded_audio.shape[-1]) == rounding_audio_steps
    assert torch.allclose(
        rounded_audio, torch.full_like(rounded_audio, 0.75))
    assert not torch.count_nonzero(rounded_audio_mask)
    assert rounded_prefix == 0
    assert int(rounded_clip_audio["waveform"].shape[-1]) == picture_samples

    # Absolute endpoints avoid the occasional one-sample error caused by
    # rounding a relative duration and adding it to an already-rounded start.
    awkward_start = 0.3 / 32_000.0
    absolute_start = round(awkward_start * 32_000)
    absolute_end = round(
        (awkward_start + rounding_frames / 24.0) * 32_000)
    _, _, absolute_clip_audio = (
        audio_context.MiniMaxH3ContexMasterAudioMaskedAV().prepare(
            rounding_latent,
            FloorAudioVAE(),
            master_audio,
            clip_start_seconds=awkward_start,
            context_length=0,
        ))
    assert int(absolute_clip_audio["waveform"].shape[-1]) == (
        absolute_end - absolute_start)

    class ShortFirstAudioVAE(FloorAudioVAE):
        def encode(self, waveform):
            encoded = super().encode(waveform)
            if len(self.encoded_samples) == 1:
                return encoded[..., :-1]
            return encoded

    retry_vae = ShortFirstAudioVAE()
    retried, _, _ = (
        audio_context.MiniMaxH3ContexMasterAudioMaskedAV().prepare(
            rounding_latent,
            retry_vae,
            master_audio,
            clip_start_seconds=1.0,
            context_length=0,
        ))
    _, retried_audio = retried["samples"].unbind()
    assert len(retry_vae.encoded_samples) == 2
    assert retry_vae.encoded_samples[0] == grid_samples
    assert retry_vae.encoded_samples[1] > grid_samples
    assert int(retried_audio.shape[-1]) == rounding_audio_steps
    assert torch.allclose(
        retried_audio, torch.full_like(retried_audio, 0.75))

    class IndexedAudioVAE:
        audio_sample_rate = 32_000

        def __init__(self):
            self.encoded_samples = []

        def encode(self, waveform):
            samples = int(waveform.shape[1])
            self.encoded_samples.append(samples)
            steps = round(samples / self.audio_sample_rate * 40)
            ticks = torch.arange(steps, dtype=torch.float32).reshape(
                1, 1, 1, steps)
            return ticks.expand(1, 32, 2, steps).clone()

    indexed_vae = IndexedAudioVAE()
    contextual, _, contextual_clip = (
        audio_context.MiniMaxH3ContexMasterAudioMaskedAV().prepare(
            rounding_latent,
            indexed_vae,
            master_audio,
            clip_start_seconds=2.0,
            context_length=0,
            preroll_seconds=1.0,
            lookahead_seconds=0.2,
        ))
    _, contextual_audio = contextual["samples"].unbind()
    _, contextual_mask = contextual["noise_mask"].unbind()
    expected_context_steps = 40 + rounding_audio_steps + 8
    assert indexed_vae.encoded_samples == [
        int(expected_context_steps / 40 * 32_000)]
    assert torch.equal(
        contextual_audio[0, 0, 0],
        torch.arange(40, 40 + rounding_audio_steps, dtype=torch.float32))
    assert not torch.count_nonzero(contextual_mask)
    assert int(contextual_clip["waveform"].shape[-1]) == picture_samples

    voice = {
        "waveform": torch.zeros((1, 1, 32_000 * 30)),
        "sample_rate": 32_000,
    }
    voice["waveform"][..., 32_000:64_000] = 1.0
    gated, _, _ = (
        audio_context.MiniMaxH3ContexMasterAudioMaskedAV().prepare(
            latent,
            AudioVAE(),
            master_audio,
            clip_start_seconds=0.0,
            context_length=0,
            audio_denoise=0.0,
            gap_denoise=0.3,
            gate_hold_seconds=0.0,
            voice=voice,
        ))
    _, gated_mask = gated["noise_mask"].unbind()
    assert torch.all(gated_mask[..., 10] == 0.3)
    assert not torch.count_nonzero(gated_mask[..., 50])
    assert torch.all(gated_mask[..., 100] == 0.3)

    softened, _, _ = (
        audio_context.MiniMaxH3ContexMasterAudioMaskedAV().prepare(
            latent,
            AudioVAE(),
            master_audio,
            clip_start_seconds=0.0,
            context_length=0,
            audio_denoise=0.25,
        ))
    _, softened_mask = softened["noise_mask"].unbind()
    assert torch.all(softened_mask == 0.25)

    assert (
        "MiniMaxH3ContexMasterAudioMaskedAV"
        in audio_context.NODE_CLASS_MAPPINGS)
    assert (
        "MiniMaxH3ContexSongMaskedAVContext"
        not in audio_context.NODE_CLASS_MAPPINGS)
    assert (
        "MiniMaxH3SongMaskedAVContext"
        not in audio_context.NODE_CLASS_MAPPINGS)
    print(
        "master-audio masking: absolute-endpoint timeline slice, complete protected audio, "
        "40 Hz target-grid lookahead, contextual tick crop, vocal gate, "
        "fractional song denoise, decoded and direct-latent 39-frame "
        "protected video continuation, "
        "and clip-1 video generation pass")


if __name__ == "__main__":
    main()
