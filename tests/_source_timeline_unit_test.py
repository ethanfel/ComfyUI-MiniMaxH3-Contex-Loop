#!/usr/bin/env python3
"""The 0.5 Source Timeline stays lazy, aligned, and recovery-safe."""

import importlib.util
import json
from fractions import Fraction
import pathlib
import shutil
import sys
import tempfile
import types

import av
import numpy as np
import torch


ROOT = pathlib.Path(__file__).resolve().parents[1]
PACKAGE = "h3_source_timeline_unit"

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


def write_fixture(path, frame_count=30, source_fps=25):
    width = height = 64
    sample_rate = 48000
    sample_count = round(frame_count / source_fps * sample_rate)
    container = av.open(str(path), mode="w")
    video = container.add_stream("libx264rgb", rate=source_fps)
    video.width = width
    video.height = height
    video.pix_fmt = "rgb24"
    video.options = {"crf": "0", "preset": "ultrafast"}
    audio = container.add_stream("pcm_f32le", rate=sample_rate)
    audio.layout = "mono"
    try:
        for index in range(frame_count):
            array = np.full(
                (height, width, 3), index * 7, dtype=np.uint8)
            frame = av.VideoFrame.from_ndarray(array, format="rgb24")
            frame.pts = index
            frame.time_base = Fraction(1, source_fps)
            for packet in video.encode(frame):
                container.mux(packet)
        for packet in video.encode():
            container.mux(packet)

        waveform = np.linspace(
            -0.75, 0.75, sample_count, dtype=np.float32).reshape(1, -1)
        for start in range(0, sample_count, 2048):
            stop = min(sample_count, start + 2048)
            frame = av.AudioFrame.from_ndarray(
                waveform[:, start:stop], format="fltp", layout="mono")
            frame.sample_rate = sample_rate
            frame.pts = start
            frame.time_base = Fraction(1, sample_rate)
            for packet in audio.encode(frame):
                container.mux(packet)
        for packet in audio.encode():
            container.mux(packet)
    finally:
        container.close()


with tempfile.TemporaryDirectory() as temporary:
    path = pathlib.Path(temporary) / "source.mkv"
    write_fixture(path)
    node = chain.MiniMaxH3SourceTimeline()

    timeline, status = node.build(
        str(path), "", "auto", 10)
    assert timeline["version"] == chain.SOURCE_TIMELINE_VERSION
    assert timeline["kind"] == "source_timeline"
    assert timeline["audio"]["kind"] == "embedded"
    assert "waveform" not in timeline["audio"]
    assert timeline["origin"]["skip_first_frames"] == 10
    assert abs(timeline["origin"]["skip_seconds"] - 0.4) < 1e-9
    assert timeline["extent"]["frame_count"] == 20
    assert "lazy embedded audio" in status
    assert len(timeline["fingerprints"]["timeline"]) == 64

    video = chain._source_timeline_scene_video(timeline, 0, 5)
    audio = chain._source_timeline_scene_audio(timeline, 0, 5)
    assert tuple(video.shape) == (5, 64, 64, 3)
    assert tuple(audio["waveform"].shape) == (1, 1, 10000)
    for target_index, source_index in enumerate([10, 11, 12, 13, 14]):
        expected = source_index * 7 / 255
        assert abs(
            float(video[target_index, 0, 0, 0]) - expected) < 1e-6
    full_track = chain._source_timeline_source_audio(timeline)
    assert tuple(full_track["waveform"].shape) == (1, 1, 40000)

    recovery = chain._source_timeline_recovery_record(timeline)
    json.dumps(recovery)
    assert recovery["fingerprints"] == timeline["fingerprints"]
    relocated_path = pathlib.Path(temporary) / "relocated.mkv"
    shutil.copyfile(path, relocated_path)
    relocated = chain._source_timeline_from_recovery(
        recovery, video_path=str(relocated_path))
    assert relocated["video"]["path"] == str(relocated_path)
    assert relocated["audio"]["path"] == str(relocated_path)
    assert relocated["fingerprints"] == timeline["fingerprints"]
    relocated_video = chain._source_timeline_scene_video(relocated, 0, 5)
    assert torch.equal(video, relocated_video)

    external, external_status = node.build(
        str(path), str(path), "ignore", 10)
    assert external["audio"]["kind"] == "external_path"
    assert "lazy external-path audio" in external_status
    external_audio = chain._source_timeline_scene_audio(external, 0, 5)
    assert tuple(external_audio["waveform"].shape) == (1, 1, 10000)
    assert torch.allclose(
        audio["waveform"], external_audio["waveform"], atol=1e-6)

    deferred, deferred_status = node.build(
        str(path), "", "ignore", 10, source_audio=full_track)
    assert deferred["audio"]["kind"] == "deferred_tensor"
    assert "deferred aligned AUDIO" in deferred_status
    deferred_record = chain._source_timeline_recovery_record(deferred)
    assert "value" not in deferred_record["audio"]
    assert deferred_record["audio"]["requires_materialization"] is True
    unresolved = chain._source_timeline_from_recovery(deferred_record)
    assert unresolved["audio"]["kind"] == "deferred_tensor"
    try:
        chain._source_timeline_scene_audio(unresolved, 0, 5)
    except ValueError as exc:
        assert "must provide ComfyUI AUDIO" in str(exc)
    else:
        raise AssertionError("unmaterialized deferred audio was decoded")
    restored = chain._source_timeline_from_recovery(
        deferred_record, deferred_audio=full_track)
    restored_audio = chain._source_timeline_scene_audio(restored, 0, 5)
    assert tuple(restored_audio["waveform"].shape) == (1, 1, 10000)

    # Independent 24 fps boundaries can differ by one PCM sample when an
    # imported-video lead and extension soundtrack are recombined. That
    # harmless quantization remainder is conformed, while a truly short
    # extension remains an error.
    quantized_extension = {
        "waveform": torch.linspace(-0.5, 0.5, 1333).reshape(1, 1, -1),
        "sample_rate": 8000,
    }
    imported_lead = {
        "waveform": torch.full((1, 1, 333), 0.75),
        "sample_rate": 8000,
    }
    recombined = chain._slice_audio_after_external_context(
        quantized_extension, imported_lead, 5, 1, False)
    assert int(recombined["waveform"].shape[-1]) == round(5 / 24 * 8000)
    try:
        chain._slice_audio_after_external_context({
            "waveform": torch.zeros((1, 1, 1000)),
            "sample_rate": 8000,
        }, imported_lead, 5, 1, False)
    except ValueError as exc:
        assert "extension soundtrack" in str(exc)
    else:
        raise AssertionError("materially short extension audio was conformed")

    wrong_audio = {
        "waveform": torch.zeros_like(full_track["waveform"]),
        "sample_rate": full_track["sample_rate"],
    }
    try:
        chain._source_timeline_from_recovery(
            deferred_record, deferred_audio=wrong_audio)
    except ValueError as exc:
        assert "does not match" in str(exc)
    else:
        raise AssertionError("mismatched recovered audio was accepted")

    audio_only, audio_only_status = node.build(
        "", str(path), "ignore", 0)
    assert audio_only["video"] is None
    assert audio_only["audio"]["kind"] == "external_path"
    assert audio_only["extent"]["frame_count"] == 28
    assert "audio-only" in audio_only_status

    lazy = chain._source_timeline_to_lazy_motion_descriptor(timeline)
    assert chain._is_lazy_motion_descriptor(lazy)
    adapted = chain._source_timeline_from_lazy_motion_descriptor(lazy)
    assert adapted["fingerprints"] == timeline["fingerprints"]
    assert chain.CHAIN_NODE_CLASS_MAPPINGS[
        "MiniMaxH3SourceTimeline"] is chain.MiniMaxH3SourceTimeline
    assert node.RETURN_TYPES == (chain.SOURCE_TIMELINE_TYPE, "STRING")

print(
    "source timeline: lazy embedded/external AV windows, native-frame origin, "
    "audio-only extent, deferred AUDIO recovery, content-verified relinking, "
    "legacy adaptation, and typed node registration pass")
