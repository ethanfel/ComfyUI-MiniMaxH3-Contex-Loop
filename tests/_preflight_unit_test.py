#!/usr/bin/env python3
"""0.5 preflight is model-free, structured, and shared by Studio/Start."""

import importlib.util
import json
import pathlib
import sys
import tempfile
import types

import torch


ROOT = pathlib.Path(__file__).resolve().parents[1]
PACKAGE = "h3_preflight_unit"

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
shared_nodes._claim_inline_patch_ownership = lambda: "test"
shared_nodes._prepare_native_guide_conditioning = lambda value: value
shared_nodes._resize = lambda *args: None
shared_nodes._streams_from_latent = lambda *args: None
sys.modules[shared_nodes.__name__] = shared_nodes

spec = importlib.util.spec_from_file_location(
    PACKAGE + ".chain_nodes", ROOT / "chain_nodes.py")
chain = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = chain
spec.loader.exec_module(chain)


def make_plan(run_name):
    policy = chain._contract_compose_chain_policy(
        chain._contract_audio_policy("source", "on", "off"),
        chain._contract_transition_policy(
            "guide", expert_override=True,
            continuation_mode="guide", context_length=5),
        audio_context_length=5)
    return chain._normalize_plan(
        json.dumps({"shots": [
            {"id": "one", "prompt": "Opening action.", "length": 22},
            {"id": "two", "prompt": "Continuation action.", "length": 22},
        ]}),
        run_name, 64, 64, 5, "video", "head", "disabled",
        "source_track", 5, 1.0, 8, 7, 18, "stack:auto:v1", 0,
        "guide", policy)


def deferred_timeline(frames):
    sample_rate = 48000
    samples = round(frames / 24 * sample_rate)
    audio = {
        "waveform": torch.linspace(-0.5, 0.5, samples).reshape(1, 1, -1),
        "sample_rate": sample_rate,
    }
    audio_hash = chain._audio_fingerprint(audio)
    timeline_hash = chain._fingerprint({"audio": audio_hash, "frames": frames})
    return {
        "version": chain.SOURCE_TIMELINE_VERSION,
        "kind": "source_timeline",
        "fps": 24,
        "origin": {"source_fps": 24.0, "skip_first_frames": 0,
                   "skip_seconds": 0.0},
        "extent": {"frame_count": frames,
                   "duration_seconds": frames / 24.0},
        "video": None,
        "audio": {"kind": "deferred_tensor", "value": audio,
                  "sample_rate": sample_rate, "channels": 1,
                  "duration_seconds": frames / 24.0,
                  "timeline_offset_seconds": 0.0,
                  "content_sha256": audio_hash},
        "fingerprints": {"video": "", "audio": audio_hash,
                         "timeline": timeline_hash},
        "recovery": {"video_path": "", "audio_path": "",
                     "deferred_audio_requires_materialization": True},
    }


def semantic_plan(prompt):
    policy = chain._contract_compose_chain_policy(
        chain._contract_audio_policy("generated", "off", "on"),
        chain._contract_transition_policy("cut"),
        audio_context_length=0)
    return chain._normalize_plan(
        json.dumps({"shots": [{
            "id": "semantic", "prompt": prompt, "length": 124,
        }]}),
        "semantic_preflight", 64, 64, 1, "video", "head", "disabled",
        "generated_audio", 0, 5.0, 8, 7, 18, "stack:auto:v1", 0,
        "guide", policy)


with tempfile.TemporaryDirectory() as temporary:
    root = pathlib.Path(temporary)
    chain._output_root = lambda: str(root)
    plan = make_plan("preflight")
    timeline = deferred_timeline(39)

    prepared, report = chain._preflight_chain(
        plan, source_timeline=timeline)
    assert report["ok"] is True
    assert report["status"] == "warning"  # isolated test lacks Comfy runtime
    assert report["source"]["required_frames"] == 39
    assert report["source"]["last_complete_scene"] == 2
    assert [scene["overlap_trim_frames"] for scene in report["scenes"]] == [0, 5]
    assert report["scenes"][1]["source_start_frame"] == 17
    assert prepared["compatibility"]["source_timeline_fingerprint"] == (
        timeline["fingerprints"]["timeline"])
    assert not root.exists() or not any(root.iterdir())

    studio = chain.MiniMaxH3ChainPlanStudio().passthrough(
        plan, source_timeline=timeline)
    assert studio["result"][0] is plan and studio["result"][2] is True
    assert json.loads(studio["result"][4])["version"] == chain.PREFLIGHT_VERSION
    assert "h3_plan_studio_source_timeline" in studio["ui"]

    studio_inputs = chain.MiniMaxH3ChainPlanStudio.INPUT_TYPES()
    assert studio_inputs["required"] == {}
    assert next(iter(studio_inputs["optional"])) == "plan"
    assert all(name in studio_inputs["optional"] for name in (
        "plan_json", "run_name", "generation_fingerprint", "width",
        "height", "base_seed", "segment_crf", "chain_policy"))
    assert chain.MiniMaxH3ChainPlanStudio.RETURN_NAMES[-5:] == (
        "plan_summary", "clip_count", "width", "height",
        "video_blend_frames")
    preflight_inputs = chain.MiniMaxH3ChainPreflight.INPUT_TYPES()
    assert tuple(preflight_inputs["required"]) == ("plan",)
    assert "plan_json" not in preflight_inputs["optional"]
    assert len(chain.MiniMaxH3ChainPreflight.RETURN_TYPES) == 5

    standalone_policy = chain._contract_compose_chain_policy(
        chain._contract_audio_policy("generated", "off", "on"),
        chain._contract_transition_policy("cut"),
        audio_context_length=0)
    standalone = chain.MiniMaxH3ChainPlanStudio().passthrough(
        plan_json=json.dumps({"shots": [{
            "id": "standalone", "prompt": "Independent shot.",
            "length": 22,
        }]}),
        run_name="studio_standalone", generation_fingerprint="studio:v1",
        width=64, height=96, context_length=1,
        encode_mode="video", anchor_mode="head", crop="disabled",
        audio_mode="generated_audio", audio_context_length=0,
        default_duration_seconds=1.0, default_steps=8,
        base_seed=11, segment_crf=17, video_blend_frames=0,
        continuation_mode="guide", chain_policy=standalone_policy,
    )
    standalone_plan = standalone["result"][0]
    assert standalone_plan["run_name"] == "studio_standalone"
    assert standalone_plan["compatibility"]["width"] == 64
    assert standalone_plan["compatibility"]["height"] == 96
    assert standalone_plan["shots"][0]["id"] == "standalone"
    assert standalone["result"][-4:] == (1, 64, 96, 0)

    tagged = chain._append_tagged_reference(
        None, kind="picture", tag="future", value="future-picture",
        content_hash="future-picture-v1")
    semantic_draft = chain.MiniMaxH3SemanticPictureAnchor().add(
        torch.zeros((1, 2, 2, 3)), "story_beat")[0]
    tagged_with_semantic = chain.MiniMaxH3SemanticAnchorBundle().bundle(
        semantic_draft, "512", "timestamped_video",
        references=tagged)[0]
    semantic_token = chain._plan_studio_generation_fingerprint(
        "", tagged_with_semantic)
    semantic_current, semantic_lineage = (
        chain._generation_fingerprint_value(semantic_token))
    assert semantic_current == tagged_with_semantic[
        "combined_reference_fingerprint"]
    assert [entry["tag"] for entry in semantic_lineage["entries"]] == [
        "future", "story_beat"]
    automatic = chain.MiniMaxH3ChainPlanStudio().passthrough(
        plan_json=json.dumps({"shots": [{
            "id": "automatic", "prompt": "Independent shot.",
            "length": 22,
        }]}),
        run_name="studio_automatic_fingerprint",
        generation_fingerprint="", tagged_references=tagged,
        width=64, height=96, context_length=1,
        encode_mode="video", anchor_mode="head", crop="disabled",
        audio_mode="generated_audio", audio_context_length=0,
        default_duration_seconds=1.0, default_steps=8,
        base_seed=11, segment_crf=17, video_blend_frames=0,
        continuation_mode="guide", chain_policy=standalone_policy,
    )["result"][0]
    assert automatic["compatibility"]["generation_fingerprint"] == (
        tagged["fingerprint"])
    assert automatic["compatibility"][
        "generation_fingerprint_lineage"]["entries"][0]["tag"] == "future"

    combined = chain.MiniMaxH3ChainPlanStudio().passthrough(
        plan_json=json.dumps({"shots": [{
            "id": "combined", "prompt": "Independent shot.", "length": 22,
        }]}),
        run_name="studio_combined_fingerprint",
        generation_fingerprint="model-stack:v2", tagged_references=tagged,
        width=64, height=96, context_length=1,
        encode_mode="video", anchor_mode="head", crop="disabled",
        audio_mode="generated_audio", audio_context_length=0,
        default_duration_seconds=1.0, default_steps=8,
        base_seed=11, segment_crf=17, video_blend_frames=0,
        continuation_mode="guide", chain_policy=standalone_policy,
    )["result"][0]
    combined_compatibility = combined["compatibility"]
    assert combined_compatibility["generation_fingerprint"] != (
        tagged["fingerprint"])
    assert combined_compatibility["generation_fingerprint_lineage"][
        "wrapper"]["contract"]["external_generation_fingerprint"] == (
            "model-stack:v2")

    empty_tagged = chain._make_tagged_references([])
    assert chain._plan_studio_generation_fingerprint("", empty_tagged) == ""

    connected = chain.MiniMaxH3ChainPlanStudio().passthrough(
        plan, source_timeline=timeline, tagged_references=tagged,
        generation_fingerprint="must-not-replace-connected-plan")
    assert connected["result"][0] is plan

    short = deferred_timeline(30)
    _prepared, failed = chain._preflight_chain(
        plan, source_timeline=short)
    assert failed["ok"] is False
    assert failed["source"]["shortfall_frames"] == 9
    assert failed["source"]["last_complete_scene"] == 1
    issue = next(item for item in failed["errors"]
                 if item["code"] == "source_audio_too_short")
    assert issue["action"]

    materialized = []
    original = chain._materialize_source_timeline_audio
    chain._materialize_source_timeline_audio = (
        lambda *args, **kwargs: materialized.append(True))
    try:
        try:
            chain.MiniMaxH3ChainLoopStart().start(
                plan, 1, source_timeline=short)
        except ValueError as exc:
            assert "source_audio_too_short" in str(exc)
        else:
            raise AssertionError("Loop Start accepted failed preflight")
    finally:
        chain._materialize_source_timeline_audio = original
    assert materialized == []

    tagged_picture = chain.MiniMaxH3TaggedPictureReference().add(
        torch.zeros((1, 32, 32, 3)), "replacement")[0]
    _prepared, semantic = chain._preflight_chain(
        semantic_plan(
            "Use @replacement and #replacement[0.00s] plus "
            "#replacement[4.75s]."),
        tagged_references=tagged_picture)
    assert semantic["ok"] is True
    assert semantic["scenes"][0]["semantic_anchors"] == [
        {"tag": "replacement", "timestamp_seconds": 0.0},
        {"tag": "replacement", "timestamp_seconds": 4.75},
    ]
    assert semantic["scenes"][0]["references"][0]["tag"] == "replacement"

    _prepared, bare_semantic = chain._preflight_chain(
        semantic_plan("Use #replacement as an untimed semantic visual."),
        tagged_references=tagged_picture)
    assert bare_semantic["ok"] is True
    assert bare_semantic["scenes"][0]["semantic_anchors"] == [
        {"tag": "replacement", "timestamp_seconds": None},
    ]

    dedicated_draft = chain.MiniMaxH3SemanticPictureAnchor().add(
        torch.zeros((1, 32, 32, 3)), "semantic_only")[0]
    dedicated_references = chain.MiniMaxH3SemanticAnchorBundle().bundle(
        dedicated_draft, "512", "timestamped_video",
        references=tagged_picture)[0]
    _prepared, dedicated = chain._preflight_chain(
        semantic_plan("Use @replacement and #semantic_only[0.00s]."),
        tagged_references=dedicated_references)
    assert dedicated["ok"] is True
    assert dedicated["references"]["semantic_route"] == "bundle"
    assert dedicated["references"]["registered_semantic_tags"] == [
        "semantic_only"]
    assert [item["tag"] for item in dedicated["scenes"][0]["references"]] == [
        "replacement"]

    semantic_only_references = chain.MiniMaxH3SemanticAnchorBundle().bundle(
        dedicated_draft, "512", "timestamped_video")[0]
    _prepared, semantic_only_single_wire = chain._preflight_chain(
        semantic_plan("Use #semantic_only[0.00s]."),
        tagged_references=semantic_only_references)
    assert semantic_only_single_wire["ok"] is True
    assert semantic_only_single_wire["references"]["route"] == "tagged"
    assert semantic_only_single_wire["references"][
        "registered_semantic_tags"] == ["semantic_only"]

    _prepared, unknown_anchor = chain._preflight_chain(
        semantic_plan("Use #missing[1.00s]."),
        tagged_references=tagged_picture)
    assert any(item["code"] == "unresolved_semantic_anchor"
               for item in unknown_anchor["errors"])

    _prepared, late_anchor = chain._preflight_chain(
        semantic_plan("Use #replacement[9.00s]."),
        tagged_references=tagged_picture)
    assert any(item["code"] == "semantic_anchor_out_of_range"
               for item in late_anchor["errors"])

print("H3 preflight: exact timing, source shortfall, semantic anchors, Studio report, and early Loop Start block pass")
