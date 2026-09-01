#!/usr/bin/env python3
"""Random prompt alternatives stay reproducible and resume-safe."""

import importlib.util
import json
import math
import pathlib
import sys
import types


ROOT = pathlib.Path(__file__).resolve().parents[1]
PACKAGE = "h3_dynamic_prompt_unit"

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


def normalize(prompt="A {wide|close} shot with {rain|sun}.", **shot_overrides):
    shot = {
        "id": "one", "prompt": prompt, "length": 39, "seed": 123,
    }
    shot.update(shot_overrides)
    return chain._normalize_plan(
        json.dumps({"shots": [shot]}),
        "dynamic-prompt-test", 64, 64, 22, "video", "head", "disabled",
        "generated_audio", 22, 2.0, 8, 7, 18, "model-stack", 0,
        "guide", None)


rendered, used = chain._resolve_dynamic_prompt(
    r"Keep \{literal\}, {one|two}, and {outer {left|right}|still}.",
    42, "one")
assert used
assert "{literal}" in rendered
assert "|" not in rendered.replace("{literal}", "")
assert chain._resolve_dynamic_prompt("ordinary {camera note}", 42) == (
    "ordinary {camera note}", False)
assert chain._resolve_dynamic_prompt(r"literal \{one\|two\}", 42) == (
    "literal {one|two}", False)

first = normalize()
assert first["shots"][0]["seed"] == 123
assert first["shots"][0]["scene_prompt_template"] == (
    "A {wide|close} shot with {rain|sun}.")
assert first["shots"][0]["scene_prompt"] != (
    first["shots"][0]["scene_prompt_template"])
assert first["shots"][0]["prompt_choice_seed"] == chain._derived_seed(
    0, 1, "one")

different = None
for candidate_seed in range(1, 100):
    candidate = normalize(
        prompt_seed_mode="fixed", prompt_seed=str(candidate_seed))
    if (candidate["shots"][0]["scene_prompt"] !=
            first["shots"][0]["scene_prompt"]):
        different = candidate
        break
assert different is not None, "prompt seeds did not exercise another alternative"
assert different["shots"][0]["seed"] == first["shots"][0]["seed"]
assert different["plan_hash"] == first["plan_hash"]
assert chain._history_hash(different, 1) == chain._history_hash(first, 1)
assert chain._scene_dependency_diffs(
    chain._scene_dependency_record(first, 1),
    chain._scene_dependency_record(different, 1),
) == []

fixed_scene = normalize(prompt_seed_mode="fixed", prompt_seed="42")
assert fixed_scene["shots"][0]["prompt_seed_mode"] == "fixed"
assert fixed_scene["shots"][0]["prompt_seed"] == 42
assert fixed_scene["shots"][0]["prompt_choice_seed"] == 42
fixed_editor_scene = chain._effective_editor_plan(fixed_scene)["shots"][0]
assert fixed_editor_scene["prompt_seed_mode"] == "fixed"
assert fixed_editor_scene["prompt_seed"] == "42"
assert fixed_scene["plan_hash"] == first["plan_hash"]
assert chain._history_hash(fixed_scene, 1) == chain._history_hash(first, 1)
assert chain._scene_dependency_diffs(
    chain._scene_dependency_record(first, 1),
    chain._scene_dependency_record(fixed_scene, 1),
) == []

legacy_fixed_scene = normalize(prompt_seed="43")
assert legacy_fixed_scene["shots"][0]["prompt_seed_mode"] == "fixed"
assert legacy_fixed_scene["shots"][0]["prompt_choice_seed"] == 43

original_randbits = chain.secrets.randbits
try:
    chain.secrets.randbits = lambda bits: 777
    randomized_scene = normalize(prompt_seed_mode="randomize")
finally:
    chain.secrets.randbits = original_randbits
assert randomized_scene["shots"][0]["prompt_seed_mode"] == "randomize"
assert "prompt_seed" not in randomized_scene["shots"][0]
assert randomized_scene["shots"][0]["prompt_choice_seed"] == 777
randomized_editor_scene = chain._effective_editor_plan(
    randomized_scene)["shots"][0]
assert randomized_editor_scene["prompt_seed_mode"] == "randomize"
assert "prompt_seed" not in randomized_editor_scene
assert randomized_scene["plan_hash"] == first["plan_hash"]
assert chain._history_hash(randomized_scene, 1) == chain._history_hash(first, 1)
assert chain._scene_dependency_diffs(
    chain._scene_dependency_record(first, 1),
    chain._scene_dependency_record(randomized_scene, 1),
) == []

try:
    normalize(prompt_seed_mode="fixed")
except ValueError as exc:
    assert "fixed prompt_seed_mode requires prompt_seed" in str(exc)
else:
    raise AssertionError("fixed prompt seed mode accepted no prompt_seed")

try:
    normalize(prompt_seed_mode="rolling")
except ValueError as exc:
    assert "prompt_seed_mode must be one of" in str(exc)
else:
    raise AssertionError("invalid prompt seed mode was accepted")

changed_template = normalize("A {wide|close} shot at night.")
template_diffs = chain._scene_dependency_diffs(
    chain._scene_dependency_record(first, 1),
    chain._scene_dependency_record(changed_template, 1),
)
assert any(item["field"] == "prompt_template_hash" for item in template_diffs)

rerolled_sampler = chain._plan_with_review_revision(
    first, 1, first["shots"][0]["scene_prompt_template"], 999, 39)
assert rerolled_sampler["shots"][0]["seed"] == 999
assert (rerolled_sampler["shots"][0]["scene_prompt"] ==
        first["shots"][0]["scene_prompt"])
assert (rerolled_sampler["shots"][0]["prompt_choice_seed"] ==
        first["shots"][0]["prompt_choice_seed"])

plain_zero = normalize("A fixed shot.")
plain_random = normalize(
    "A fixed shot.", prompt_seed_mode="fixed", prompt_seed="999")
assert plain_zero["shots"][0]["scene_prompt"] == "A fixed shot."
assert "scene_prompt_template" not in plain_zero["shots"][0]
assert plain_zero["plan_hash"] == plain_random["plan_hash"]

assert "prompt_seed" not in chain.MiniMaxH3ChainPlan.INPUT_TYPES()["optional"]
assert "prompt_seed" not in first
assert chain.MiniMaxH3ChainPlan.IS_CHANGED(
    json.dumps({"shots": [{"prompt": "fixed"}]})) is False
assert math.isnan(chain.MiniMaxH3ChainPlan.IS_CHANGED(json.dumps({
    "shots": [{
        "prompt": "{one|two}", "prompt_seed_mode": "randomize",
    }],
})))

print("dynamic prompt unit test passed")
