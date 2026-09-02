#!/usr/bin/env python3
"""Modern Plan keeps the Plan contract while exposing no legacy controls."""

import importlib.util
import json
import pathlib
import sys
import types


ROOT = pathlib.Path(__file__).resolve().parents[1]
PACKAGE = "h3_modern_plan_unit"

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
shared_nodes._claim_inline_patch_ownership = lambda _conditioning=None: "test"
shared_nodes._prepare_native_guide_conditioning = lambda value: value
shared_nodes._resize = lambda *args: None
shared_nodes._streams_from_latent = lambda *args: None
sys.modules[shared_nodes.__name__] = shared_nodes

spec = importlib.util.spec_from_file_location(
    PACKAGE + ".chain_nodes", ROOT / "chain_nodes.py")
chain = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = chain
spec.loader.exec_module(chain)


required = chain.MiniMaxH3ChainPlanModern.INPUT_TYPES()["required"]
optional = chain.MiniMaxH3ChainPlanModern.INPUT_TYPES()["optional"]
assert tuple(required) == (
    "plan_json", "chain_policy", "run_name", "generation_fingerprint",
    "width", "height", "encode_mode", "crop",
    "default_duration_seconds", "default_steps", "base_seed",
    "segment_crf", "video_blend_frames",
)
for removed in (
    "context_length", "anchor_mode", "audio_mode", "audio_context_length",
    "continuation_mode",
):
    assert removed not in required
    assert removed not in optional
assert required["chain_policy"][0] == chain.CHAIN_POLICY_TYPE
assert tuple(optional) == ("plan_json_input", "project_assets")
assert chain.MiniMaxH3ChainPlanModern.RETURN_TYPES == (
    chain.MiniMaxH3ChainPlan.RETURN_TYPES)
assert chain.MiniMaxH3ChainPlanModern.RETURN_NAMES == (
    chain.MiniMaxH3ChainPlan.RETURN_NAMES)
assert (chain.CHAIN_NODE_CLASS_MAPPINGS["MiniMaxH3ChainPlanModern"]
        is chain.MiniMaxH3ChainPlanModern)

plan_json = json.dumps({
    "prompt_prefix": "Keep identity stable.",
    "shots": [
        {"id": "one", "prompt": "Opening.", "length": 73},
        {"id": "two", "prompt": "Continue.", "length": 73},
    ],
})
policy = chain.MiniMaxH3GenerationProfile().build(
    "Visual continuity", "Generate audio")[0]
modern = chain.MiniMaxH3ChainPlanModern().build(
    plan_json=plan_json,
    chain_policy=policy,
    run_name="modern-plan",
    generation_fingerprint="model-a",
    width=960,
    height=544,
    encode_mode="video",
    crop="center",
    default_duration_seconds=15.0,
    default_steps=20,
    base_seed=7,
    segment_crf=18,
    video_blend_frames=0,
)
legacy = chain.MiniMaxH3ChainPlan().build(
    plan_json=plan_json,
    run_name="modern-plan",
    generation_fingerprint="model-a",
    width=960,
    height=544,
    context_length=22,
    encode_mode="video",
    anchor_mode="head",
    crop="center",
    audio_mode="generated_audio",
    audio_context_length=22,
    default_duration_seconds=15.0,
    default_steps=20,
    base_seed=7,
    segment_crf=18,
    video_blend_frames=0,
    continuation_mode="guide",
    chain_policy=policy,
)
assert modern == legacy
assert modern[0]["compatibility"]["anchor_mode"] == "head"
assert modern[0]["compatibility"]["context_length"] == 22
assert modern[0]["compatibility"]["audio_context_length"] == 22

replacement_json = json.dumps({
    "shots": [{"id": "external", "prompt": "External.", "length": 22}],
})
external = chain.MiniMaxH3ChainPlanModern().build(
    plan_json=plan_json,
    plan_json_input=replacement_json,
    chain_policy=policy,
    run_name="modern-plan",
    generation_fingerprint="model-a",
    width=960,
    height=544,
    encode_mode="video",
    crop="disabled",
    default_duration_seconds=15.0,
    default_steps=20,
    base_seed=7,
    segment_crf=18,
)
assert external[0]["shots"][0]["id"] == "external"

print("Modern Plan: clean inputs and legacy-equivalent Plan output pass")
