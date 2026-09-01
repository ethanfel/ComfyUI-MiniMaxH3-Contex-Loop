#!/usr/bin/env python3
"""Joint boundary anchors stay frame-exact and latent-native."""

import importlib.util
import pathlib
import sys
import types

import torch


ROOT = pathlib.Path(__file__).resolve().parents[1]
PACKAGE = "h3_boundary_anchor_unit"

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


def streams_from_latent(latent):
    return list(latent["samples"])


shared_nodes._streams_from_latent = streams_from_latent
sys.modules[shared_nodes.__name__] = shared_nodes

spec = importlib.util.spec_from_file_location(
    PACKAGE + ".chain_nodes", ROOT / "chain_nodes.py")
chain = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = chain
spec.loader.exec_module(chain)


delivered = [345, 306, 306, 306]
starts = [0, 306, 612, 918]
plan = {
    "version": chain.PLAN_VERSION,
    "plan_hash": "runtime-plan",
    "base_plan_hash": "base-plan",
    "compatibility": {
        "width": 1344,
        "height": 768,
        "source_timeline_fingerprint": "timeline-one",
    },
    "shots": [
        {
            "index": index,
            "id": "scene_%d" % index,
            "raw_frames": 345,
            "delivered_frames": frames,
            "generation_start_frame": starts[index - 1],
        }
        for index, frames in enumerate(delivered, 1)
    ],
}
timeline = {
    "version": chain.SOURCE_TIMELINE_VERSION,
    "kind": "source_timeline",
    "extent": {"frame_count": 1300},
    "video": {"path": "test"},
    "audio": {"kind": "embedded"},
    "fingerprints": {"timeline": "timeline-one"},
}

original_validate = chain._validate_source_timeline
chain._validate_source_timeline = lambda value, require_runtime=False: value
try:
    layout = chain._make_boundary_anchor_prepass(plan, timeline)
finally:
    chain._validate_source_timeline = original_validate

assert layout["output_length"] == 73
assert layout["expected_video_steps"] == 22
assert [item["latent_step"] for item in layout["slots"]] == [6, 11, 16, 21]
assert [item["source_endpoint_frame"] for item in layout["slots"]] == [
    344, 650, 956, 1262]
assert layout["reference_windows"] == [
    {"kind": "lead", "scene": 1, "source_start": 323,
     "source_end": 328},
    {"kind": "endpoint", "scene": 1, "source_start": 328,
     "source_end": 345},
    {"kind": "endpoint", "scene": 2, "source_start": 634,
     "source_end": 651},
    {"kind": "endpoint", "scene": 3, "source_start": 940,
     "source_end": 957},
    {"kind": "endpoint", "scene": 4, "source_start": 1246,
     "source_end": 1263},
]
assert chain._validate_boundary_anchor_prepass(layout) is layout

# The reel preserves exact source ordering. Its hard internal cuts are useful
# only during joint sampling; they never become scene output.
original_prepare = chain._source_timeline_with_motion_short_edge
original_video = chain._source_timeline_scene_video
chain._source_timeline_with_motion_short_edge = lambda value, edge: value
chain._source_timeline_scene_video = lambda value, start, end: (
    torch.arange(start, end, dtype=torch.float32)
    .reshape(-1, 1, 1, 1).expand(-1, 2, 3, 3).clone())
try:
    reel = chain._decode_boundary_anchor_reel(layout, timeline, "384")
finally:
    chain._source_timeline_with_motion_short_edge = original_prepare
    chain._source_timeline_scene_video = original_video

assert tuple(reel.shape) == (73, 2, 3, 3)
assert reel[:, 0, 0, 0].tolist() == (
    list(range(323, 328)) + list(range(328, 345)) +
    list(range(634, 651)) + list(range(940, 957)) +
    list(range(1246, 1263)))

# Audio uses the identical ordered windows. At this synthetic 24 Hz sample
# rate, one source frame maps to exactly one sample, which makes any dropped,
# repeated, or reordered endpoint immediately visible.
original_audio = chain._source_timeline_scene_audio
chain._validate_source_timeline = lambda value, require_runtime=False: value
chain._source_timeline_scene_audio = lambda value, start, end: {
    "waveform": torch.arange(
        start, end, dtype=torch.float32).reshape(1, 1, -1),
    "sample_rate": 24,
}
try:
    reel_audio = chain._decode_boundary_anchor_audio_reel(layout, timeline)
finally:
    chain._source_timeline_scene_audio = original_audio
    chain._validate_source_timeline = original_validate

assert reel_audio["sample_rate"] == 24
assert reel_audio["waveform"].reshape(-1).tolist() == (
    list(range(323, 328)) + list(range(328, 345)) +
    list(range(634, 651)) + list(range(940, 957)) +
    list(range(1246, 1263)))

# The temporary video reference carries that audio as a paired native source;
# the ordinary identity/environment references remain in the same registry.
prepared_references = chain._boundary_anchor_references(
    None, reel, reel_audio, "boundary_reel", "<Subject 1>",
    "endpoint pose and synchronized movement cadence", "384")
boundary_entry = prepared_references["entries"][-1]
assert boundary_entry["tag"] == "boundary_reel"
assert boundary_entry["audio_tag"] == "boundary_reel_audio"
assert boundary_entry["paired_audio_policy"] == "embedded"
assert boundary_entry["audio"] is reel_audio
assert boundary_entry["semantic_role"] == "motion"

# Extract directly from the sampled video latent; no decoder/VAE is involved.
video = torch.stack([
    torch.full((16, 4, 7), float(step)) for step in range(22)
], dim=1).unsqueeze(0)
audio = torch.zeros((1, 32, 2, 122))
sampled = {"samples": [video, audio]}
registry, status = chain.MiniMaxH3ExtractBoundaryAnchors().extract(
    sampled, layout)
assert "6, 2:11, 3:16, 4:21" in status
assert len(registry["anchors"]) == 4
for expected, anchor in zip((6, 11, 16, 21), registry["anchors"]):
    assert tuple(anchor.shape) == (1, 16, 1, 4, 7)
    assert torch.all(anchor == float(expected))

target = {
    "samples": [torch.zeros((1, 16, 102, 4, 7)),
                torch.zeros((1, 32, 2, 680))],
}
for scene, expected in enumerate((6, 11, 16, 21), 1):
    selected = chain._boundary_anchor_for_state(
        registry, {"index": scene, "plan": plan}, target)
    assert torch.all(selected == float(expected))

wrong_timeline = dict(timeline)
wrong_timeline["fingerprints"] = dict(timeline["fingerprints"])
wrong_timeline["fingerprints"]["timeline"] = "timeline-two"
try:
    chain._boundary_anchor_for_state(
        registry,
        {"index": 2, "plan": plan, "source_timeline": wrong_timeline},
        target)
except ValueError as exc:
    assert "different Source Timeline" in str(exc)
else:
    raise AssertionError("stale Source Timeline was accepted")

changed_registry = dict(registry)
changed_registry["anchors"] = list(registry["anchors"])
changed_registry["anchors"][1] = changed_registry["anchors"][1].clone()
changed_registry["anchors"][1][..., 0, 0] += 1
try:
    chain._boundary_anchor_for_state(
        changed_registry, {"index": 2, "plan": plan}, target)
except ValueError as exc:
    assert "changed after extraction" in str(exc)
else:
    raise AssertionError("mutated boundary latent was accepted")

changed_plan = dict(plan)
changed_plan["shots"] = [dict(item) for item in plan["shots"]]
changed_plan["shots"][2]["delivered_frames"] = 289
try:
    chain._boundary_anchor_for_state(
        registry, {"index": 3, "plan": changed_plan}, target)
except ValueError as exc:
    assert "different scene lengths" in str(exc)
else:
    raise AssertionError("stale boundary registry was accepted")

assert chain.CHAIN_NODE_CLASS_MAPPINGS[
    "MiniMaxH3BoundaryAnchorPrepass"] is chain.MiniMaxH3BoundaryAnchorPrepass
assert chain.CHAIN_NODE_CLASS_MAPPINGS[
    "MiniMaxH3ExtractBoundaryAnchors"] is chain.MiniMaxH3ExtractBoundaryAnchors
context_schema = chain.MiniMaxH3ChainContext.INPUT_TYPES()["optional"]
assert context_schema["boundary_anchors"][0] == chain.BOUNDARY_ANCHORS_TYPE

print(
    "boundary anchors: cumulative delivered endpoints, synchronized 73-frame "
    "AV reel, paired native audio, phase-matched latent steps, direct "
    "extraction, stale Plan/Timeline/latent refusal, and typed Chain Context "
    "registration pass")
