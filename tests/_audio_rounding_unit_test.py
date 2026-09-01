#!/usr/bin/env python3
"""Standalone regressions for cumulative H3 audio sample budgeting."""

import importlib.util
import pathlib
import sys
import types

import torch


ROOT = pathlib.Path(__file__).resolve().parents[1]
PACKAGE = "h3_audio_rounding_unit"

folder_paths = types.ModuleType("folder_paths")
folder_paths.get_output_directory = lambda: str(ROOT)
folder_paths.get_temp_directory = lambda: str(ROOT)
folder_paths.get_input_directory = lambda: str(ROOT)
folder_paths.get_annotated_filepath = lambda value: str(value)
sys.modules["folder_paths"] = folder_paths

package = types.ModuleType(PACKAGE)
package.__path__ = [str(ROOT)]
sys.modules[PACKAGE] = package

shared_nodes = types.ModuleType(PACKAGE + ".nodes")
shared_nodes.MiniMaxH3MotionContext = object
shared_nodes._claim_inline_patch_ownership = lambda _conditioning=None: "test patch owner"
shared_nodes._prepare_native_guide_conditioning = lambda *args: None
shared_nodes._resize = lambda *args: None
shared_nodes._streams_from_latent = lambda *args: None
sys.modules[shared_nodes.__name__] = shared_nodes

spec = importlib.util.spec_from_file_location(
    PACKAGE + ".chain_nodes", ROOT / "chain_nodes.py")
chain = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = chain
spec.loader.exec_module(chain)


def generated_audio_case(frames, saved_samples):
    loads = iter([
        {"delivered_audio": torch.ones((1, 2, count))}
        for count in saved_samples
    ])
    chain._st_load = lambda _path: next(loads)
    return chain._generated_audio({"segments": [
        {
            "index": index,
            "checkpoint": "clip_%04d.safetensors" % index,
            "sample_rate": 8000,
            "delivered_frames": frame_count,
        }
        for index, frame_count in enumerate(frames, start=1)
    ]})


def main():
    original_st_load = chain._st_load
    original_prelude_audio = chain._prelude_audio
    try:
        trimmed = generated_audio_case([5, 5], [1667, 1667])
        assert trimmed["waveform"].shape[-1] == round(10 / 24 * 8000)

        padded = generated_audio_case([4, 4], [1333, 1333])
        assert padded["waveform"].shape[-1] == round(8 / 24 * 8000)
        assert torch.count_nonzero(padded["waveform"][..., -1:]) == 0

        # A later masked-AV scene owns its complete decoded overlap. This is
        # the only way Soft AV's audio feather survives Loop Trim into the
        # final generated soundtrack.
        loads = iter([
            {"delivered_audio": torch.ones((1, 1, 100))},
            {
                "delivered_audio": torch.full((1, 1, 61), 3.0),
                "audio_with_overlap": torch.cat((
                    torch.full((1, 1, 39), 2.0),
                    torch.full((1, 1, 61), 3.0),
                ), dim=-1),
            },
        ])
        chain._st_load = lambda _path: next(loads)
        owned = chain._generated_audio({
            "compatibility": {"continuation_mode": "guide"},
            "segments": [
                {"index": 1, "checkpoint": "one", "sample_rate": 24,
                 "raw_frames": 100, "delivered_frames": 100,
                 "continuation_mode": "guide"},
                {"index": 2, "checkpoint": "two", "sample_rate": 24,
                 "raw_frames": 100, "delivered_frames": 61,
                 "continuation_mode": "audio_feathered_av"},
            ],
        })
        assert owned["waveform"].shape[-1] == 161
        assert torch.equal(
            owned["waveform"][0, 0, :61], torch.ones(61))
        assert torch.equal(
            owned["waveform"][0, 0, 61:100], torch.full((39,), 2.0))
        assert torch.equal(
            owned["waveform"][0, 0, 100:], torch.full((61,), 3.0))

        # Scene 1 can itself continue an external video prelude. Carry its
        # private raw AV audio through _generated_audio so the generated scene
        # owns the incoming overlap at that boundary too.
        loads = iter([{
            "delivered_audio": torch.full((1, 1, 61), 3.0),
            "audio_with_overlap": torch.cat((
                torch.full((1, 1, 39), 2.0),
                torch.full((1, 1, 61), 3.0),
            ), dim=-1),
        }])
        chain._st_load = lambda _path: next(loads)
        first_owned = chain._generated_audio({
            "compatibility": {
                "continuation_mode": "audio_feathered_av",
            },
            "segments": [
                {"index": 1, "checkpoint": "first", "sample_rate": 24,
                 "raw_frames": 100, "delivered_frames": 61,
                 "continuation_mode": "audio_feathered_av"},
            ],
        })
        assert first_owned[chain.AUDIO_WITH_OVERLAP_FRAMES_KEY] == 100
        assert first_owned[chain.AUDIO_TRIM_FRAMES_KEY] == 39
        chain._prelude_audio = lambda _record: {
            "waveform": torch.ones((1, 1, 100)), "sample_rate": 24}
        external_owned = chain._audio_with_prelude(
            first_owned, 61, {"frame_count": 100})
        assert external_owned["waveform"].shape[-1] == 161
        assert torch.equal(
            external_owned["waveform"][0, 0, :61], torch.ones(61))
        assert torch.equal(
            external_owned["waveform"][0, 0, 61:100],
            torch.full((39,), 2.0))
        assert torch.equal(
            external_owned["waveform"][0, 0, 100:],
            torch.full((61,), 3.0))

        chain._prelude_audio = lambda _record: {
            "waveform": torch.ones((1, 2, 1667)), "sample_rate": 8000}
        joined = chain._audio_with_prelude(
            {"waveform": torch.ones((1, 2, 1667)), "sample_rate": 8000},
            5, {"frame_count": 5})
        assert joined["waveform"].shape[-1] == round(10 / 24 * 8000)

        one_short = chain._fit_pyav_audio_samples(
            torch.ones((2, 226666)), 226667)
        assert one_short.shape[-1] == 226667
        assert torch.count_nonzero(one_short[..., -1:]) == 0
        try:
            chain._fit_pyav_audio_samples(torch.ones((2, 226665)), 226667)
        except ValueError as exc:
            assert "226665 samples; 226667 are required" in str(exc)
        else:
            raise AssertionError("PyAV accepted an audio deficit above one sample")
    finally:
        chain._st_load = original_st_load
        chain._prelude_audio = original_prelude_audio

    print("H3 audio rounding: cumulative scene and prelude boundaries are exact")


if __name__ == "__main__":
    main()
