#!/usr/bin/env python3
"""The compact policy is one wire with identical resolved Plan semantics."""

import importlib.util
import json
import pathlib
import sys
import types


ROOT = pathlib.Path(__file__).resolve().parents[1]
PACKAGE = "h3_chain_policy_unit"

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
shared_nodes._claim_inline_patch_ownership = lambda: "test patch owner"
shared_nodes._prepare_native_guide_conditioning = lambda value: value
shared_nodes._resize = lambda *args: None
shared_nodes._streams_from_latent = lambda *args: None
sys.modules[shared_nodes.__name__] = shared_nodes

spec = importlib.util.spec_from_file_location(
    PACKAGE + ".chain_nodes", ROOT / "chain_nodes.py")
chain = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = chain
spec.loader.exec_module(chain)


PLAN_JSON = json.dumps({
    "shots": [
        {"id": "one", "prompt": "First scene.", "length": 73},
        {"id": "two", "prompt": "Second scene.", "length": 73},
    ],
})


def make_plan(*, combined=None, audio_context_length=22):
    return chain._normalize_plan(
        PLAN_JSON, "compact-policy-test", 64, 64, 22,
        "video", "head", "disabled", "generated_audio",
        audio_context_length,
        3.0, 8, 7, 18, "model-stack", 0, "guide",
        combined)


node = chain.MiniMaxH3ChainPolicy()
required = node.INPUT_TYPES()["required"]
assert tuple(required["incoming_transition"][0]) == (
    "cut", "guide", "hard_av", "soft_av")
assert "audio_context_length" not in required
assert list(required)[-1] == "lock_source_audio"
assert required["lock_source_audio"][0] == "BOOLEAN"
assert required["lock_source_audio"][1]["default"] is False
assert node.DEPRECATED is True
combined, status = node.build("soft_av", "source", "on", "off")
assert combined["version"] == chain.CHAIN_POLICY_VERSION
assert combined["audio_policy"] == chain._contract_audio_policy(
    "source", "on", "off")
assert combined["transition_policy"] == chain._contract_transition_policy(
    "soft_av")
assert combined["audio_context_length"] == 39
assert "Soft AV" in status
assert "final=source/ref=on/carry=off" in status
assert "source timeline required" in status
assert "audio context automatic (39f)" in status

locked, locked_status = node.build(
    "soft_av", "source", "on", "on", True)
assert locked["audio_policy"] == chain._contract_audio_policy(
    "source", "off", "off", "locked")
assert "final=source/ref=off/carry=off/target=locked" in locked_status
assert "source timeline required" in locked_status

profile_node = chain.MiniMaxH3GenerationProfile()
profile_inputs = profile_node.INPUT_TYPES()["required"]
assert tuple(profile_inputs["scene_continuity"][0]) == (
    "Visual continuity", "Independent scenes",
    "Hard picture + protected audio",
    "Hard picture + smooth audio")
assert tuple(profile_inputs["audio_profile"][0]) == (
    "Generate audio", "Generate fresh audio per scene",
    "Lip-sync to source audio", "Generate audio from source guide",
    "Use source soundtrack only", "No final audio")
assert profile_inputs["scene_continuity"][1]["display_name"] == (
    "Scene continuity")
assert profile_inputs["audio_profile"][1]["display_name"] == "Audio profile"
generated_profile, generated_profile_status = profile_node.build()
assert generated_profile["audio_policy"] == chain._contract_audio_policy(
    "generated", "off", "on")
assert generated_profile["transition_policy"] == (
    chain._contract_transition_policy("guide"))
assert generated_profile["audio_context_length"] == 22
assert "Generate audio" in generated_profile_status
lip_sync_profile, lip_sync_status = profile_node.build(
    "Hard picture + smooth audio", "Lip-sync to source audio")
assert lip_sync_profile["audio_policy"] == chain._contract_audio_policy(
    "source", "off", "off", "locked")
assert lip_sync_profile["transition_policy"] == (
    chain._contract_transition_policy("soft_av"))
assert lip_sync_profile["audio_context_length"] == 39
assert "source timeline required" in lip_sync_status
source_guide_profile = profile_node.build(
    "Independent scenes", "Generate audio from source guide")[0]
assert source_guide_profile["audio_policy"] == chain._contract_audio_policy(
    "generated", "on", "off")
assert source_guide_profile["audio_context_length"] == 0

advanced = chain.MiniMaxH3AdvancedPolicy()
advanced_inputs = advanced.INPUT_TYPES()["required"]
assert advanced_inputs["chain_policy"][0] == chain.CHAIN_POLICY_TYPE
assert tuple(advanced_inputs["incoming_transition"][0]) == (
    "cut", "guide", "tone_guide", "latent_guide", "detail_guide",
    "detail_av", "drift_av", "color_drift_av", "hard_av", "soft_av")
drift, drift_status = advanced.apply(combined, "drift_av")
assert drift["audio_policy"] == combined["audio_policy"]
assert drift["transition_policy"] == chain._contract_transition_policy(
    "drift_av")
assert drift["audio_context_length"] == 39
assert "advanced override" in drift_status
assert "audio preserved" in drift_status
locked_drift = advanced.apply(locked, "drift_av")[0]
assert locked_drift["audio_policy"] == locked["audio_policy"]
color_drift, color_status = advanced.apply(combined, "color_drift_av")
assert color_drift["transition_policy"][
    "continuation_mode"] == "color_stable_drift_av"
assert color_drift["audio_policy"] == combined["audio_policy"]
assert "Color-Stable Drift AV" in color_status

combined_plan = make_plan(combined=combined)
assert "chain_policy" not in combined_plan["compatibility"]

legacy = chain.MiniMaxH3Legacy04PolicyAdapter()
legacy_combined, legacy_status = legacy.build(
    "source_plus_timeline", "feathered_av", 39, 33)
assert legacy.RETURN_NAMES == ("chain_policy", "status")
assert legacy_combined["audio_policy"] == chain.migrate_legacy_audio_mode(
    "source_plus_timeline")
assert legacy_combined["transition_policy"]["continuation_mode"] == (
    "feathered_av")
assert legacy_combined["audio_context_length"] == 33
assert "legacy 0.4 migration" in legacy_status
assert legacy.INPUT_TYPES()["optional"]["chain_policy"][0] == (
    chain.CHAIN_POLICY_TYPE)
legacy_overlay, overlay_status = legacy.build(
    "generated_audio", "drift_control_av", 39, 39,
    chain_policy=combined)
assert legacy_overlay["audio_policy"] == combined["audio_policy"]
assert legacy_overlay["transition_policy"] == chain._contract_transition_policy(
    "drift_av")
assert "incoming audio preserved" in overlay_status
legacy_locked = legacy.build(
    "generated_audio", "masked_av", 39, 39,
    chain_policy=locked)[0]
assert legacy_locked["audio_policy"] == locked["audio_policy"]
legacy_plan = make_plan(combined=legacy_combined)
assert legacy_plan["compatibility"]["audio_context_length"] == 33
assert legacy_plan["compatibility"]["continuation_mode"] == "feathered_av"

plan_inputs = chain.MiniMaxH3ChainPlan.INPUT_TYPES()
assert plan_inputs["optional"]["chain_policy"][0] == chain.CHAIN_POLICY_TYPE
assert "audio_policy" not in plan_inputs["optional"]
assert "transition_policy" not in plan_inputs["optional"]
assert chain.CHAIN_NODE_CLASS_MAPPINGS[
    "MiniMaxH3GenerationProfile"] is chain.MiniMaxH3GenerationProfile
assert chain.CHAIN_NODE_CLASS_MAPPINGS[
    "MiniMaxH3ChainPolicy"] is chain.MiniMaxH3ChainPolicy
assert chain.CHAIN_NODE_CLASS_MAPPINGS[
    "MiniMaxH3AdvancedPolicy"] is chain.MiniMaxH3AdvancedPolicy
assert chain.CHAIN_NODE_DISPLAY_NAME_MAPPINGS[
    "MiniMaxH3GenerationProfile"] == "MiniMax H3 Generation Profile"
assert chain.CHAIN_NODE_DISPLAY_NAME_MAPPINGS[
    "MiniMaxH3ChainPolicy"] == "MiniMax H3 Manual Chain Policy (Legacy)"
assert chain.CHAIN_NODE_DISPLAY_NAME_MAPPINGS[
    "MiniMaxH3AdvancedPolicy"] == "MiniMax H3 Advanced Policy Override"
assert chain.CHAIN_NODE_DISPLAY_NAME_MAPPINGS[
    "MiniMaxH3Legacy04PolicyAdapter"] == (
        "MiniMax H3 Legacy 0.4 Policy Adapter")

lora_plan = chain._normalize_plan(
    json.dumps({"shots": [
        {"id": "base", "prompt": "Base scene.", "length": 73,
         "lora_route": "base"},
        {"id": "hero", "prompt": "Hero scene.", "length": 73,
         "lora_route": "A"},
    ]}),
    "lora-route-test", 64, 64, 22, "video", "head", "disabled",
    "generated_audio", 22, 3.0, 8, 7, 18, "model-stack", 0,
    "guide")
assert "lora_route" not in lora_plan["shots"][0]
assert lora_plan["shots"][1]["lora_route"] == "a"
assert chain._effective_editor_plan(lora_plan)["shots"][1][
    "lora_route"] == "a"
assert chain._shot_lora_route(lora_plan["shots"][0]) == "base"
try:
    chain._shot_lora_route({"lora_route": "hero"})
except ValueError as exc:
    assert "base" in str(exc) and "a" in str(exc)
else:
    raise AssertionError("unknown scene LoRA route was accepted")
try:
    chain._normalize_plan(
        json.dumps({"shots": [{
            "id": "invalid", "prompt": "Invalid route.", "length": 73,
            "lora_route": "hero",
        }]}),
        "invalid-lora-route-test", 64, 64, 22, "video", "head",
        "disabled", "generated_audio", 22, 3.0, 8, 7, 18,
        "model-stack", 0, "guide")
except ValueError as exc:
    assert "Shot 1" in str(exc) and "LoRA route" in str(exc)
else:
    raise AssertionError("Plan accepted an unknown scene LoRA route")

scheduler = chain.MiniMaxH3ChainLoRAScheduler()
scheduler_inputs = scheduler.INPUT_TYPES()
assert scheduler_inputs["required"]["base_model"][1]["lazy"] is True
assert scheduler_inputs["optional"]["lora_a"][1]["lazy"] is True
base_state = {"index": 1, "plan": lora_plan}
hero_state = {"index": 2, "plan": lora_plan}
base_model = object()
hero_model = object()
assert scheduler.check_lazy_status(base_state, None) == ["base_model"]
assert scheduler.check_lazy_status(
    hero_state, None, lora_a=None) == ["lora_a"]
assert scheduler.check_lazy_status(
    hero_state, None, lora_a=hero_model) == []
assert scheduler.select(base_state, base_model)[0] is base_model
selected, selected_status = scheduler.select(
    hero_state, None, lora_a=hero_model)
assert selected is hero_model
assert "scene 2" in selected_status and "LoRA A" in selected_status
try:
    scheduler.select(hero_state, None)
except ValueError as exc:
    assert "lora_a input is not connected" in str(exc)
else:
    raise AssertionError("unconnected selected LoRA route was accepted")
assert chain.CHAIN_NODE_CLASS_MAPPINGS[
    "MiniMaxH3ChainLoRAScheduler"] is chain.MiniMaxH3ChainLoRAScheduler
assert chain.CHAIN_NODE_DISPLAY_NAME_MAPPINGS[
    "MiniMaxH3ChainLoRAScheduler"] == "MiniMax H3 Scene LoRA Scheduler"

print(
    "generation profiles, legacy manual policy, and lazy scene LoRA routing: "
    "clear one-wire Plan intent, canonical compatibility, and existing-loader "
    "MODEL selection pass")
