"""Exact MiniMax H3 PCM-to-latent grid helpers.

Adapted from seitanism/ComfyUI-H3-Motion-Context-MultiRef revision
5839d453efa0346c1da49acc39fc65050c5c48c0 (GPL-3.0). H3 audio latents run
at 40 Hz—normally 800 PCM samples per latent cell at 32 kHz. Preparing an
exact grid before calling the generic ComfyUI VAE wrapper prevents its normal
center crop from shifting the continuation seam.
"""

from __future__ import annotations


AUDIO_HZ = 40.0


def audio_grid_geometry(audio_vae, target_audio_steps,
                        expected_hz=AUDIO_HZ):
    """Return sample rate, samples per latent cell, and required PCM size."""
    sample_rate = int(getattr(audio_vae, "audio_sample_rate", 32000))
    first_stage = getattr(audio_vae, "first_stage_model", None)
    samples_per_latent = getattr(first_stage, "samples_per_latent", None)
    if samples_per_latent is None:
        samples_per_latent = getattr(first_stage, "hop_length", None)
    if samples_per_latent is None:
        nominal = sample_rate / float(expected_hz)
        samples_per_latent = int(round(nominal))
        if abs(samples_per_latent - nominal) > 1e-9:
            raise RuntimeError(
                "H3 audio VAE sample rate %d is not integral on the %.0f Hz "
                "latent grid" % (sample_rate, float(expected_hz)))

    samples_per_latent = int(samples_per_latent)
    if samples_per_latent <= 0:
        raise RuntimeError(
            "invalid H3 audio VAE samples-per-latent %d" %
            samples_per_latent)

    actual_hz = sample_rate / float(samples_per_latent)
    if abs(actual_hz - float(expected_hz)) > 1e-6:
        raise RuntimeError(
            "H3 audio VAE geometry is %d Hz / %d samples = %.6f latent Hz; "
            "expected %.0f" % (
                sample_rate, samples_per_latent, actual_hz,
                float(expected_hz)))

    steps = int(target_audio_steps)
    if steps < 1:
        raise ValueError(
            "target H3 audio grid must contain at least one latent step")
    return sample_rate, samples_per_latent, steps * samples_per_latent


def encode_exact_audio_grid(audio_vae, waveform, target_audio_steps,
                            label="H3 audio"):
    """Encode exact-grid PCM and reject a changed VAE output contract."""
    sample_rate, samples_per_latent, expected_samples = audio_grid_geometry(
        audio_vae, target_audio_steps)
    have = int(waveform.shape[-1])
    if have != expected_samples:
        raise RuntimeError(
            "%s PCM is %d samples; exact H3 grid requires %d (%d x %d)" % (
                label, have, expected_samples, int(target_audio_steps),
                samples_per_latent))

    encoded = audio_vae.encode(waveform.movedim(1, -1))
    if getattr(encoded, "ndim", 0) != 4:
        raise ValueError(
            "%s audio VAE returned %s; expected [B,C,2,T]" % (
                label, tuple(getattr(encoded, "shape", ()))))
    got = int(encoded.shape[-1])
    if got != int(target_audio_steps):
        raise RuntimeError(
            "%s exact-grid PCM (%d samples = %d x %d) encoded to %d latent "
            "steps; expected %d. This is an audio-VAE wrapper/encoder "
            "contract mismatch." % (
                label, expected_samples, int(target_audio_steps),
                samples_per_latent, got, int(target_audio_steps)))
    return encoded, {
        "vae_sample_rate": sample_rate,
        "samples_per_latent": samples_per_latent,
        "grid_samples": expected_samples,
    }


__all__ = ["AUDIO_HZ", "audio_grid_geometry", "encode_exact_audio_grid"]
