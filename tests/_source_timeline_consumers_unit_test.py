#!/usr/bin/env python3
"""0.5 consumers share one lazy Source Timeline through the full chain."""

import importlib.util
import json
from fractions import Fraction
import pathlib
import sys
import tempfile
import types

import av
import numpy as np
import torch


ROOT = pathlib.Path(__file__).resolve().parents[1]
PACKAGE = "h3_source_timeline_consumers_unit"

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
shared_nodes._prepare_native_guide_conditioning = lambda value: value
shared_nodes._resize = lambda *args: None
shared_nodes._streams_from_latent = lambda *args: None
sys.modules[shared_nodes.__name__] = shared_nodes

spec = importlib.util.spec_from_file_location(
    PACKAGE + ".chain_nodes", ROOT / "chain_nodes.py")
chain = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = chain
spec.loader.exec_module(chain)


def write_fixture(path, frame_count=50, source_fps=25):
    sample_rate = 48000
    sample_count = round(frame_count / source_fps * sample_rate)
    container = av.open(str(path), mode="w")
    video = container.add_stream("libx264rgb", rate=source_fps)
    video.width = video.height = 64
    video.pix_fmt = "rgb24"
    video.options = {"crf": "0", "preset": "ultrafast"}
    audio = container.add_stream("pcm_f32le", rate=sample_rate)
    audio.layout = "mono"
    try:
        for index in range(frame_count):
            image = np.full((64, 64, 3), index * 4, dtype=np.uint8)
            frame = av.VideoFrame.from_ndarray(image, format="rgb24")
            frame.pts = index
            frame.time_base = Fraction(1, source_fps)
            for packet in video.encode(frame):
                container.mux(packet)
        for packet in video.encode():
            container.mux(packet)
        values = np.linspace(-0.8, 0.8, sample_count,
                             dtype=np.float32).reshape(1, -1)
        for start in range(0, sample_count, 2048):
            frame = av.AudioFrame.from_ndarray(
                values[:, start:start + 2048], format="fltp", layout="mono")
            frame.sample_rate = sample_rate
            frame.pts = start
            frame.time_base = Fraction(1, sample_rate)
            for packet in audio.encode(frame):
                container.mux(packet)
        for packet in audio.encode():
            container.mux(packet)
    finally:
        container.close()


def make_plan(run_name, audio_mode="source_track"):
    return chain._normalize_plan(
        json.dumps({"shots": [
            {"id": "one", "prompt": "@motion begins.", "length": 22},
            {"id": "two", "prompt": "@motion continues.", "length": 22},
        ]}),
        run_name, 64, 64, 5, "video", "head", "disabled",
        audio_mode, 5, 1.0, 8, 7, 18, "model-stack", 0,
        "guide")


with tempfile.TemporaryDirectory() as temporary:
    root = pathlib.Path(temporary)
    chain._output_root = lambda: str(root)
    path = root / "source.mkv"
    write_fixture(path)
    timeline = chain.MiniMaxH3SourceTimeline().build(
        str(path), "", "auto", 0)[0]
    plan = make_plan("timeline-consumers")

    started = chain.MiniMaxH3ChainLoopStart().start(
        plan, 1, source_timeline=timeline)
    state = started[1]
    prepared = state["plan"]
    runtime = state["source_timeline"]
    assert prepared["compatibility"]["source_timeline_fingerprint"] == (
        timeline["fingerprints"]["timeline"])
    assert prepared["compatibility"]["source_audio_hash"] == (
        timeline["fingerprints"]["audio"])
    assert "value" not in prepared["source_timeline"]["audio"]

    first = chain.MiniMaxH3ChainCurrent().current(state)["result"]
    assert tuple(first[12]["waveform"].shape) == (1, 1, 44000)
    state["index"] = 2
    second = chain.MiniMaxH3ChainCurrent().current(state)["result"]
    expected = chain._source_timeline_scene_audio(runtime, 17, 39)
    assert torch.equal(second[12]["waveform"], expected["waveform"])
    assert "Source Timeline frame-exact" in second[13]
    assert second[14] == 0

    scene_override_plan = chain._normalize_plan(
        json.dumps({"shots": [
            {"id": "dry", "prompt": "No source reference.", "length": 22},
            {"id": "ref", "prompt": "Use source reference.", "length": 22,
             "source_reference": "on"},
        ]}),
        "timeline-scene-overrides", 64, 64, 5, "video", "head",
        "disabled", "generated_audio", 5, 1.0, 8, 7, 18,
        "model-stack", 0, "guide")
    override_started = chain.MiniMaxH3ChainLoopStart().start(
        scene_override_plan, 1, source_timeline=timeline)
    override_state = override_started[1]
    assert chain.MiniMaxH3ChainCurrent().current(
        override_state)["result"][12] is None
    override_state["index"] = 2
    override_second = chain.MiniMaxH3ChainCurrent().current(
        override_state)["result"]
    assert tuple(override_second[12]["waveform"].shape) == (1, 1, 44000)
    assert override_second[0]["current_source_reference_dependency"] is not None

    tagged = chain.MiniMaxH3TaggedMotionReferenceTimeline().add(
        runtime, "motion", "<Subject 1>", "the supplied motion", "384",
        "embedded", "", "sequential")
    references, _fingerprint, _status, preview_source = tagged
    entry = references["entries"][0]
    assert chain._is_source_timeline(entry["value"])
    assert entry["paired_audio_policy"] == "embedded"
    scene_video, scene_audio, detail = chain._scheduled_video_reference_slice(
        entry, state, 2, 2, 22)
    assert tuple(scene_video.shape) == (22, 64, 64, 3)
    assert tuple(scene_audio["waveform"].shape) == (1, 1, 44000)
    assert "frames 17:39" in detail

    masked_plan = {
        **prepared,
        "compatibility": {
            **prepared["compatibility"],
            "continuation_mode": "audio_feathered_av",
        },
        "shots": [dict(shot) for shot in prepared["shots"]],
    }
    masked_plan["shots"][1]["continuation_mode"] = "audio_feathered_av"
    masked_video, masked_audio, masked_detail = (
        chain._scheduled_video_reference_slice(
            entry, {**state, "index": 2, "plan": masked_plan}, 2, 2, 22))
    assert tuple(masked_video.shape) == (17, 64, 64, 3)
    assert tuple(masked_audio["waveform"].shape) == (1, 1, 44000)
    assert masked_detail == (
        "@motion sequential delivered video frames 22:39; paired audio raw "
        "frames 17:39 (origin scene 1)")

    lazy_preview = chain.MiniMaxH3LazyMotionScenePreview().preview(
        preview_source, 2, plan=prepared)
    assert tuple(lazy_preview[0].shape) == (22, 64, 64, 3)
    direct_preview = chain.MiniMaxH3SourceTimelineScenePreview().preview(
        runtime, 2, "sequential", "384", True, prepared)
    assert tuple(direct_preview[0].shape) == (22, 64, 64, 3)

    manager_plan, manager_timeline = chain.MiniMaxH3ChainRunManager().passthrough(
        plan, True, True, True, "[]", source_timeline=timeline)
    assert manager_plan["source_timeline"]["fingerprints"] == (
        timeline["fingerprints"])
    assert chain._is_source_timeline(manager_timeline)
    assert pathlib.Path(manager_timeline["video"]["path"]).is_file()
    assert manager_timeline["recovery"]["video_archived"] is True
    assert manager_timeline["audio"]["path"] == (
        manager_timeline["video"]["path"])
    assert (root / "h3_chains" / "timeline-consumers" /
            "source_timeline.json").is_file()

    promoted_plan = make_plan(
        "timeline-promoted-source-track", "generated_audio")
    source_binding = json.dumps([{
        "binding_id": "original-song",
        "label": "Original song",
        "role": "source_track",
        "node_id": "42",
        "node_type": "LoadAudio",
        "node_title": "Original song",
        "output_slot": 0,
        "output_type": "AUDIO",
        "widget_name": "audio",
        "original_value": path.name,
    }])
    original_input_root = chain._input_root
    try:
        chain._input_root = lambda: str(root)
        promoted_plan, promoted_timeline = (
            chain.MiniMaxH3ChainRunManager().passthrough(
                promoted_plan, True, False, False, source_binding))
    finally:
        chain._input_root = original_input_root
    assert chain._is_source_timeline(promoted_timeline)
    assert promoted_timeline["video"] is None
    assert promoted_timeline["audio"]["kind"] == "external_path"
    assert promoted_timeline["recovery"]["source_route"] == (
        "run_manager_source_track")
    assert promoted_plan["source_timeline"]["fingerprints"] == (
        promoted_timeline["fingerprints"])
    studio_source = chain._register_plan_studio_source_previews(
        promoted_plan, {"scenes": []})
    assert studio_source["source_audio"]["available"] is True
    assert studio_source["source_audio"]["timeline_available"] is True

    manifest = chain._manifest_from_segments(prepared, [
        {"index": 1, "id": "one", "delivered_frames": 22},
        {"index": 2, "id": "two", "delivered_frames": 17},
    ], True)
    recovered = chain._source_timeline_from_metadata(manifest)
    chain._validate_source_timeline_hash(
        manifest["compatibility"], recovered, "test assemble")
    assert manifest["source_timeline"]["fingerprints"] == (
        timeline["fingerprints"])

    segment_path = (
        root / "h3_chains" / "timeline-consumers" / "segments" /
        "clip_0001.mp4")
    segment_path.parent.mkdir(parents=True, exist_ok=True)
    segment_path.write_bytes(b"fake segment")
    assembly_manifest = dict(manifest)
    assembly_manifest["format"] = "h3_chain_manifest_v2"
    assembly_manifest["segments"] = [dict(item) for item in manifest["segments"]]
    for item in assembly_manifest["segments"]:
        item["segment"] = chain._relative_output_path(str(segment_path))
    original_validate_manifest = chain._validate_manifest
    original_validate_prelude = chain._validate_prelude
    original_metadata = chain._manifest_media_metadata
    original_which = chain.shutil.which
    original_ffmpeg = chain._run_ffmpeg
    chain._validate_manifest = lambda value: value["segments"]
    chain._validate_prelude = lambda _value: None
    chain._manifest_media_metadata = lambda _value: {}
    chain.shutil.which = lambda executable: (
        "/fake/ffmpeg" if executable == "ffmpeg" else original_which(executable))

    def fake_ffmpeg(command, timeout_seconds=None):
        del timeout_seconds
        if command[-1] == "-version":
            return
        pathlib.Path(command[-1]).write_bytes(b"assembled")

    chain._run_ffmpeg = fake_ffmpeg
    try:
        assembled = chain.MiniMaxH3ChainAssemble().assemble(
            assembly_manifest, "plan", "timeline_source", 96)
    finally:
        chain._validate_manifest = original_validate_manifest
        chain._validate_prelude = original_validate_prelude
        chain._manifest_media_metadata = original_metadata
        chain.shutil.which = original_which
        chain._run_ffmpeg = original_ffmpeg
        chain._FFMPEG_PROBE_CACHE.clear()
    assert pathlib.Path(assembled["result"][0]).is_file()

    tensor_audio = chain._source_timeline_source_audio(timeline)
    deferred = chain.MiniMaxH3SourceTimeline().build(
        str(path), "", "ignore", 0, source_audio=tensor_audio)[0]
    deferred_plan = make_plan("timeline-materialized")
    deferred_prepared, materialized = chain._plan_with_source_timeline(
        deferred_plan, deferred)
    assert materialized["audio"]["kind"] == "external_path"
    assert pathlib.Path(materialized["audio"]["path"]).is_file()
    assert "value" not in deferred_prepared["source_timeline"]["audio"]
    assert chain._source_timeline_from_recovery(
        deferred_prepared["source_timeline"])["audio"]["kind"] == (
            "external_path")

    # A legacy AUDIO connected once at Loop Start is promoted to the same
    # path-backed recovery contract without changing its released raw-audio
    # fingerprint. Downstream nodes no longer need the tensor wire, while an
    # old redundant wire remains valid when it carries the identical track.
    legacy_plan = make_plan("legacy-audio-promoted")
    legacy_started = chain.MiniMaxH3ChainLoopStart().start(
        legacy_plan, 1, source_audio=tensor_audio)
    legacy_state = legacy_started[1]
    legacy_prepared = legacy_state["plan"]
    legacy_timeline = legacy_state["source_timeline"]
    legacy_hash = chain._audio_fingerprint(tensor_audio)
    assert legacy_prepared["compatibility"]["source_audio_hash"] == (
        legacy_hash)
    assert "source_timeline_fingerprint" not in (
        legacy_prepared["compatibility"])
    assert legacy_timeline["audio"]["kind"] == "external_path"
    assert legacy_timeline["recovery"][
        "legacy_loop_start_source_audio_hash"] == legacy_hash
    assert pathlib.Path(legacy_timeline["audio"]["path"]).is_file()
    assert "source audio saved in run state" in legacy_started[2]
    assert chain._canonical_source_reference_dependency(
        legacy_prepared, 1, legacy_timeline, None) == (
            chain._canonical_source_reference_dependency(
                legacy_prepared, 1, None, tensor_audio))
    legacy_current = chain.MiniMaxH3ChainCurrent().current(
        legacy_state, tensor_audio)["result"]
    assert tuple(legacy_current[12]["waveform"].shape) == (1, 1, 44000)
    assert legacy_current[0]["current_source_reference_dependency"][
        "route"] == "legacy_audio"

    legacy_manifest = chain._manifest_from_segments(legacy_prepared, [
        {"index": 1, "id": "one", "delivered_frames": 22},
        {"index": 2, "id": "two", "delivered_frames": 17},
    ], True)
    legacy_recovered = chain._source_timeline_from_metadata(legacy_manifest)
    chain._validate_source_timeline_hash(
        legacy_manifest["compatibility"], legacy_recovered,
        "legacy assembly recovery")
    recovered_audio = chain._full_chain_selected_audio(
        legacy_manifest, "source", None, None)
    redundant_audio = chain._full_chain_selected_audio(
        legacy_manifest, "source", None, tensor_audio)
    assert int(recovered_audio["waveform"].shape[-1]) == 78000
    assert torch.equal(
        recovered_audio["waveform"], redundant_audio["waveform"])

    # Checkpoint Manager must prefer the descriptor persisted with the
    # selected revision, because Run Manager archived the user-facing Plan
    # before Loop Start saw and materialized the legacy AUDIO wire.
    manager_plan_path = root / "h3_chains" / "legacy-audio-promoted" / "plan.json"
    manager_plan_path.write_text(json.dumps({
        "plan_hash": legacy_prepared["plan_hash"],
        "shots": [{"id": "one"}, {"id": "two"}],
    }), encoding="utf-8")
    manager_metadata = [{
        "plan_hash": legacy_prepared["plan_hash"],
        "compatibility": legacy_prepared["compatibility"],
        "source_timeline": legacy_prepared["source_timeline"],
        "segment": {
            "index": index,
            "delivered_frames": delivered,
            "prompt_prefix": "",
        },
    } for index, delivered in ((1, 22), (2, 17))]
    original_load_revision = chain._load_checkpoint_revision
    original_validate_manifest = chain._validate_manifest
    chain._load_checkpoint_revision = lambda _run, index, _revision: (
        manager_metadata[index - 1], "metadata.json")
    chain._validate_manifest = lambda value: value["segments"]
    try:
        selected_manifest = chain._checkpoint_selection_manifest(json.dumps({
            "run_name": "legacy-audio-promoted",
            "lineage": [
                {"scene": 1, "revision": "one"},
                {"scene": 2, "revision": "two"},
            ],
        }))
    finally:
        chain._load_checkpoint_revision = original_load_revision
        chain._validate_manifest = original_validate_manifest
    assert selected_manifest["source_timeline"] == (
        legacy_prepared["source_timeline"])

assert chain.CHAIN_NODE_CLASS_MAPPINGS[
    "MiniMaxH3TaggedMotionReferenceTimeline"] is (
        chain.MiniMaxH3TaggedMotionReferenceTimeline)
assert chain.CHAIN_NODE_CLASS_MAPPINGS[
    "MiniMaxH3SourceTimelineScenePreview"] is (
        chain.MiniMaxH3SourceTimelineScenePreview)

print(
    "Source Timeline consumers: Run Manager source-track promotion, Loop "
    "Start state, Current Shot, Tagged Motion, both previews, manifest "
    "recovery, and deferred-audio materialization pass")
