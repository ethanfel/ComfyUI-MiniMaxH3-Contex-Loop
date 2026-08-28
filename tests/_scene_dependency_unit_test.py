#!/usr/bin/env python3
"""Structured scene dependencies isolate generation and assembly changes."""

import importlib.util
import json
import pathlib
import sys
import tempfile
import types

import torch


ROOT = pathlib.Path(__file__).resolve().parents[1]
PACKAGE = "h3_scene_dependency_unit"

folder_paths = types.ModuleType("folder_paths")
folder_paths.get_output_directory = lambda: str(ROOT)
folder_paths.get_temp_directory = lambda: str(ROOT)
folder_paths.get_input_directory = lambda: str(ROOT)
folder_paths.get_annotated_filepath = lambda value: str(value)
sys.modules["folder_paths"] = folder_paths

package = types.ModuleType(PACKAGE)
package.__path__ = [str(ROOT)]
sys.modules[PACKAGE] = package
nodes = types.ModuleType(PACKAGE + ".nodes")
nodes.MiniMaxH3MotionContext = object
nodes._claim_inline_patch_ownership = lambda: "test"
nodes._prepare_native_guide_conditioning = lambda value: value
nodes._resize = lambda *args: None
nodes._streams_from_latent = lambda *args: None
sys.modules[nodes.__name__] = nodes

spec = importlib.util.spec_from_file_location(
    PACKAGE + ".chain_nodes", ROOT / "chain_nodes.py")
chain = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = chain
spec.loader.exec_module(chain)


def make_plan(context=5):
    return chain._normalize_plan(
        json.dumps({"shots": [
            {"id": "one", "prompt": "@actor opens.", "length": 39},
            {"id": "two", "prompt": "@actor continues.", "length": 39},
        ]}),
        "dependency-test", 64, 64, context, "video", "head", "disabled",
        "source_track", context, 1.0, 8, 11, 18, "body:auto:v1", 0,
        "guide")


def audio(values):
    return {"waveform": values.reshape(1, 1, -1), "sample_rate": 48000}


plan = make_plan(5)

# Reference registries are incremental. Appending an unused prompt reference
# must not invalidate an already-rendered predecessor, including checkpoints
# saved before lineage metadata existed.
registry_v1 = chain._append_tagged_reference(
    None, kind="picture", tag="actor", value="actor-v1",
    content_hash="actor-hash-v1")
registry_v2 = chain._append_tagged_reference(
    registry_v1, kind="picture", tag="later", value="later-v1",
    content_hash="later-hash-v1")
token_v1 = chain._reference_fingerprint_output(registry_v1)
token_v2 = chain._reference_fingerprint_output(registry_v2)

# Prompt-driven tags define identity. Rewiring the same tag→asset registry in
# another node order must not change its fingerprint or native packing order.
registry_reordered = chain._append_tagged_reference(
    None, kind="picture", tag="later", value="later-v1",
    content_hash="later-hash-v1")
registry_reordered = chain._append_tagged_reference(
    registry_reordered, kind="picture", tag="actor", value="actor-v1",
    content_hash="actor-hash-v1")
assert registry_reordered["fingerprint"] == registry_v2["fingerprint"]
_compiled, _summary, ordered_bindings = (
    chain._compile_tagged_reference_prompt(
        registry_v2, 1, 1, "@later watches @actor."))
_compiled, _summary, reordered_bindings = (
    chain._compile_tagged_reference_prompt(
        registry_reordered, 1, 1, "@later watches @actor."))
assert [entry["tag"] for entry in ordered_bindings["pictures"]] == [
    "actor", "later"]
assert [entry["tag"] for entry in reordered_bindings["pictures"]] == [
    "actor", "later"]
assert ordered_bindings["aliases"] == reordered_bindings["aliases"]


def reference_plan(token, first_prompt="@actor opens."):
    return chain._normalize_plan(
        json.dumps({"shots": [
            {"id": "one", "prompt": first_prompt, "length": 39},
            {"id": "two", "prompt": "@actor continues.", "length": 39},
        ]}),
        "reference-lineage-test", 64, 64, 5, "video", "head",
        "disabled", "generated_audio", 5, 1.0, 8, 11, 18, token,
        0, "guide")


wrapped_token_v1 = chain._plan_studio_generation_fingerprint(
    "model-stack:v2", registry_v1)
wrapped_token_v2 = chain._plan_studio_generation_fingerprint(
    "model-stack:v2", registry_v2)
assert chain._scene_dependency_diffs(
    chain._scene_dependency_record(reference_plan(wrapped_token_v1), 1, None),
    chain._scene_dependency_record(reference_plan(wrapped_token_v2), 1, None),
) == []


old_reference_dependency = chain._scene_dependency_record(
    reference_plan(token_v1), 1, None)
new_reference_dependency = chain._scene_dependency_record(
    reference_plan(token_v2), 1, None)
assert old_reference_dependency["scopes"]["global_generation"][
    "generation_fingerprint"] == registry_v1["fingerprint"]
assert chain._scene_dependency_diffs(
    old_reference_dependency, new_reference_dependency) == []
legacy_reference_dependency = json.loads(json.dumps(old_reference_dependency))
legacy_reference_dependency.pop("generation_fingerprint_lineage", None)
assert chain._scene_dependency_diffs(
    legacy_reference_dependency, new_reference_dependency) == []

# New nodes may be inserted at the beginning or middle of a ComfyUI reference
# chain. Their position must not invalidate old scenes when their tags are
# inactive; the unchanged old registry is still present as an ordered subset.
registry_inserted = chain._append_tagged_reference(
    None, kind="picture", tag="actor", value="actor-v1",
    content_hash="actor-hash-v1")
registry_inserted = chain._append_tagged_reference(
    registry_inserted, kind="picture", tag="stairs", value="stairs-v1",
    content_hash="stairs-hash-v1")
registry_inserted = chain._append_tagged_reference(
    registry_inserted, kind="picture", tag="later", value="later-v1",
    content_hash="later-hash-v1")
inserted_dependency = chain._scene_dependency_record(
    reference_plan(chain._reference_fingerprint_output(registry_inserted)),
    1, None)
assert chain._scene_dependency_diffs(
    new_reference_dependency, inserted_dependency) == []
legacy_v2_dependency = json.loads(json.dumps(new_reference_dependency))
legacy_v2_dependency.pop("generation_fingerprint_lineage", None)
assert chain._scene_dependency_diffs(
    legacy_v2_dependency, inserted_dependency) == []
legacy_reordered_fingerprint = chain._make_reference_schedule(
    registry_reordered["entries"])["fingerprint"]
assert legacy_reordered_fingerprint != registry_reordered["fingerprint"]
legacy_reordered_dependency = chain._scene_dependency_record(
    reference_plan(legacy_reordered_fingerprint), 1, None)
assert chain._scene_dependency_diffs(
    legacy_reordered_dependency, inserted_dependency) == []
inserted_active_dependency = chain._scene_dependency_record(
    reference_plan(
        chain._reference_fingerprint_output(registry_inserted),
        "@actor enters @stairs."), 1, None)
assert any(item["field"] == "generation_fingerprint"
           for item in chain._scene_dependency_diffs(
               new_reference_dependency, inserted_active_dependency))

# The same append is generation-significant when the old scene prompt activates
# the newly registered tag.
active_old_dependency = chain._scene_dependency_record(
    reference_plan(token_v1, "@actor meets @later."), 1, None)
active_new_dependency = chain._scene_dependency_record(
    reference_plan(token_v2, "@actor meets @later."), 1, None)
active_append_diffs = chain._scene_dependency_diffs(
    active_old_dependency, active_new_dependency)
assert any(item["scope"] == "global_generation"
           and item["field"] == "generation_fingerprint"
           for item in active_append_diffs)

# Replacing an existing reference is not append-compatible and remains blocked.
changed_registry = chain._append_tagged_reference(
    None, kind="picture", tag="actor", value="actor-v2",
    content_hash="actor-hash-v2")
changed_registry = chain._append_tagged_reference(
    changed_registry, kind="picture", tag="later", value="later-v1",
    content_hash="later-hash-v1")
changed_dependency = chain._scene_dependency_record(
    reference_plan(chain._reference_fingerprint_output(changed_registry)),
    1, None)
assert any(item["field"] == "generation_fingerprint"
           for item in chain._scene_dependency_diffs(
               old_reference_dependency, changed_dependency))

# Replacing an image which this completed scene never used is also neutral.
# Unlike append-only growth, this proof uses the saved and current lineage
# entries to compare the scene's effective tag->asset contracts directly.
changed_inactive_registry = chain._append_tagged_reference(
    None, kind="picture", tag="actor", value="actor-v1",
    content_hash="actor-hash-v1")
changed_inactive_registry = chain._append_tagged_reference(
    changed_inactive_registry, kind="picture", tag="later",
    value="later-v2", content_hash="later-hash-v2")
changed_inactive_dependency = chain._scene_dependency_record(
    reference_plan(chain._reference_fingerprint_output(
        changed_inactive_registry)), 1, None)
assert chain._scene_dependency_diffs(
    new_reference_dependency, changed_inactive_dependency) == []
changed_inactive_active_dependency = chain._scene_dependency_record(
    reference_plan(
        chain._reference_fingerprint_output(changed_inactive_registry),
        "@actor meets @later."), 1, None)
assert any(item["field"] == "generation_fingerprint"
           for item in chain._scene_dependency_diffs(
               active_new_dependency,
               changed_inactive_active_dependency))

# Dedicated Qwen-only semantic anchors share the incremental Plan fingerprint
# without becoming native Ref2VA entries. Adding an unused #anchor must remain
# resume-neutral; activating it in the old scene makes the change significant.
semantic_entry = {
    "kind": "semantic_anchor", "tag": "future_beat",
    "activation": "prompt", "value": "semantic-v1",
    "content_hash": "semantic-hash-v1",
}
semantic_bundle = chain._make_semantic_anchor_bundle(
    [semantic_entry], "512", "timestamped_video")
semantic_registry = chain._combined_reference_registry(
    registry_v1, semantic_bundle)
semantic_token = chain._reference_fingerprint_output(semantic_registry)
semantic_inactive_dependency = chain._scene_dependency_record(
    reference_plan(semantic_token), 1, None)
assert chain._scene_dependency_diffs(
    old_reference_dependency, semantic_inactive_dependency) == []
semantic_active_dependency = chain._scene_dependency_record(
    reference_plan(
        semantic_token, "@actor reaches #future_beat[0.50s]."), 1, None)
assert any(item["field"] == "generation_fingerprint"
           for item in chain._scene_dependency_diffs(
               old_reference_dependency, semantic_active_dependency))

# A real migration may have several native refs plus several new semantic
# anchors. Check every direct inactive subset before trying legacy-order
# permutations, whose factorial search can otherwise exhaust the safety cap
# before it reaches the unchanged native-only registry.
large_native_registry = None
for tag in ("actor", "wardrobe", "prop", "later_actor"):
    large_native_registry = chain._append_tagged_reference(
        large_native_registry, kind="picture", tag=tag, value=tag,
        content_hash=tag + "-hash")
large_native_registry = chain._append_tagged_reference(
    large_native_registry, kind="audio", tag="later_audio", value="audio",
    content_hash="later-audio-hash", timeline_mode="source_timeline",
    align_audio_reference=True)
legacy_large_fingerprint = chain._make_reference_schedule(
    large_native_registry["entries"])["fingerprint"]
large_semantic_entries = [{
    "kind": "semantic_anchor", "tag": tag,
    "activation": "prompt", "value": tag,
    "content_hash": tag + "-hash",
} for tag in ("future_a", "future_b", "future_c")]
large_semantic_bundle = chain._make_semantic_anchor_bundle(
    large_semantic_entries, "512", "timestamped_video")
large_combined_registry = chain._combined_reference_registry(
    large_native_registry, large_semantic_bundle)
legacy_large_dependency = chain._scene_dependency_record(
    reference_plan(
        legacy_large_fingerprint,
        "@actor wears @wardrobe and carries @prop."), 1, None)
large_combined_dependency = chain._scene_dependency_record(
    reference_plan(
        chain._reference_fingerprint_output(large_combined_registry),
        "@actor wears @wardrobe and carries @prop."), 1, None)
assert chain._scene_dependency_diffs(
    legacy_large_dependency, large_combined_dependency) == []

# Legacy scheduled references use their scene selectors rather than prompt tags.
scheduled_v1 = chain._append_scheduled_reference(
    None, kind="picture", tag="actor", scenes="all", value="actor",
    content_hash="actor-hash")
scheduled_future = chain._append_scheduled_reference(
    scheduled_v1, kind="picture", tag="future", scenes="3:6",
    value="future", content_hash="future-hash")
scheduled_active = chain._append_scheduled_reference(
    scheduled_v1, kind="picture", tag="now", scenes="1",
    value="now", content_hash="now-hash")
scheduled_old_dependency = chain._scene_dependency_record(
    reference_plan(chain._reference_fingerprint_output(scheduled_v1)), 1,
    None)
scheduled_future_dependency = chain._scene_dependency_record(
    reference_plan(chain._reference_fingerprint_output(scheduled_future)), 1,
    None)
scheduled_active_dependency = chain._scene_dependency_record(
    reference_plan(chain._reference_fingerprint_output(scheduled_active)), 1,
    None)
assert chain._scene_dependency_diffs(
    scheduled_old_dependency, scheduled_future_dependency) == []
assert any(item["field"] == "generation_fingerprint"
           for item in chain._scene_dependency_diffs(
               scheduled_old_dependency, scheduled_active_dependency))

samples = round(plan["total_delivered_frames"] / 24 * 48000)
base = torch.linspace(-0.8, 0.8, samples)
changed = base.clone()
# Scene 1 consumes frames 0:39. Scene 2 consumes 34:73; change only after 39.
changed[39 * 2000:] *= -1
audio_a = audio(base)
audio_b = audio(changed)
prepared_a = chain._plan_with_source_audio(plan, audio_a)
prepared_b = chain._plan_with_source_audio(plan, audio_b)

scene1_a = chain._scene_dependency_record(
    prepared_a, 1, chain._canonical_source_reference_dependency(
        prepared_a, 1, None, audio_a))
scene1_b = chain._scene_dependency_record(
    prepared_b, 1, chain._canonical_source_reference_dependency(
        prepared_b, 1, None, audio_b))
assert chain._scene_dependency_diffs(scene1_a, scene1_b) == []

scene2_a = chain._scene_dependency_record(
    prepared_a, 2, chain._canonical_source_reference_dependency(
        prepared_a, 2, None, audio_a))
scene2_b = chain._scene_dependency_record(
    prepared_b, 2, chain._canonical_source_reference_dependency(
        prepared_b, 2, None, audio_b))
audio_diffs = chain._scene_dependency_diffs(scene2_a, scene2_b)
assert any(item["scope"] == "scene_generation"
           and item["field"].endswith("pcm_sha256")
           for item in audio_diffs)
assert all(item["scene"] == 2 and item["regeneration_required"]
           for item in audio_diffs)

locked_policy = chain._contract_compose_chain_policy(
    chain._contract_audio_policy("source", "on", "on", "locked"),
    chain._contract_transition_policy("guide"),
    audio_context_length=22)
locked_plan = chain._normalize_plan(
    json.dumps({"shots": [
        {"id": "one", "prompt": "@actor opens.", "length": 39},
        {"id": "two", "prompt": "@actor continues.", "length": 39},
    ]}),
    "locked-dependency-test", 64, 64, 5, "video", "head", "disabled",
    "generated_audio", 5, 1.0, 8, 11, 18, "body:auto:v1", 0,
    "guide", locked_policy)
locked_prepared = chain._plan_with_source_audio(locked_plan, audio_a)
locked_source_dependency = chain._canonical_source_reference_dependency(
    locked_prepared, 1, None, audio_a)
assert locked_source_dependency is not None
locked_dependency = chain._scene_dependency_record(
    locked_prepared, 1, locked_source_dependency)
assert locked_dependency["scopes"]["global_generation"][
    "source_audio_target"] == "locked"
assert locked_dependency["scopes"]["scene_generation"][
    "source_reference_window"]["pcm_sha256"]

# Final mux choice and whole-source identity are assembly-only.
assembly_changed = json.loads(json.dumps(scene1_a))
assembly_changed["scopes"]["assembly_only"]["final_audio"] = "generated"
assembly_changed["scopes"]["assembly_only"]["source_audio_fingerprint"] = "x"
assert chain._scene_dependency_diffs(scene1_a, assembly_changed) == []

# A scene's selected pre-patched MODEL route remains routing/provenance only.
# It must not invalidate completed predecessors, and the default Base spelling
# remains absent for old checkpoint compatibility.
assert "lora_route" not in scene1_a["scopes"]["scene_generation"]
routed_plan = json.loads(json.dumps(prepared_a))
routed_plan["shots"][0]["lora_route"] = "a"
routed_dependency = chain._scene_dependency_record(
    routed_plan, 1,
    scene1_a["scopes"]["scene_generation"]["source_reference_window"])
route_diffs = chain._scene_dependency_diffs(scene1_a, routed_dependency)
assert route_diffs == []
assert "lora_route" not in chain._history_contract(
    routed_plan, 1)["shots"][0]

# A later incoming context does not retroactively redefine scene 1.
long_context = make_plan(22)
prepared_long = chain._plan_with_source_audio(long_context, audio_a)
long_scene1 = chain._scene_dependency_record(
    prepared_long, 1, chain._canonical_source_reference_dependency(
        prepared_long, 1, None, audio_a))
assert chain._scene_dependency_diffs(scene1_a, long_scene1) == []
long_scene2 = chain._scene_dependency_record(
    prepared_long, 2, chain._canonical_source_reference_dependency(
        prepared_long, 2, None, audio_a))
boundary_diffs = chain._scene_dependency_diffs(scene2_a, long_scene2)
assert any(item["scope"] == "incoming_boundary"
           and item["field"] == "context_length"
           for item in boundary_diffs)
assert chain._resume_context_predecessor(make_plan(5), 2) == 1
independent_start_plan = make_plan(5)
independent_start_plan["shots"][1]["context_length"] = 0
independent_start_plan["shots"][1]["audio_context_length"] = 0
assert chain._resume_context_predecessor(independent_start_plan, 2) is None

# Visual and generated-audio continuity are independent edges. Scene 5 can
# consume scene 3's saved picture state while retaining scene 4's audio latent.
nonlinear_plan = chain._normalize_plan(
    json.dumps({"shots": [
        {"id": name, "prompt": name, "length": 90,
         **({"visual_context_source": "three",
             "video_blend_frames": 0} if name == "five" else {})}
        for name in ("one", "two", "three", "four", "five")
    ]}),
    "nonlinear-context-test", 64, 64, 5, "video", "head", "disabled",
    "generated_audio", 5, 1.0, 8, 11, 18, "body:auto:v1", 0,
    "guide")
assert nonlinear_plan["shots"][4]["visual_context_source"] == "three"
assert chain._shot_visual_context_source(nonlinear_plan, 5) == 3
linear_spelling = json.loads(json.dumps(nonlinear_plan))
linear_spelling["shots"][4]["visual_context_source"] = "four"
assert chain._shot_visual_context_source(linear_spelling, 5) == 4
nonlinear_sources = chain._resume_context_predecessors(nonlinear_plan, 5)
assert nonlinear_sources == {"visual": 3, "audio": 4, "scenes": [3, 4]}
nonlinear_dependency = chain._scene_dependency_record(
    nonlinear_plan, 5, None)
assert nonlinear_dependency["scopes"]["incoming_boundary"][
    "visual_context_source_scene"] == 3
assert nonlinear_dependency["scopes"]["incoming_boundary"][
    "visual_context_source_id"] == "three"

windowed_plan_source = json.loads(json.dumps({"shots": [
    {"id": name, "prompt": name, "length": 90,
     **({"visual_context_source": "three",
         "visual_context_start_frame": 12,
         "video_blend_frames": 0} if name == "five" else {})}
    for name in ("one", "two", "three", "four", "five")
]}))
windowed_plan = chain._normalize_plan(
    json.dumps(windowed_plan_source),
    "windowed-context-test", 64, 64, 5, "video", "head", "disabled",
    "generated_audio", 5, 1.0, 8, 11, 18, "body:auto:v1", 0,
    "latent_guide")
assert windowed_plan["shots"][4]["visual_context_start_frame"] == 12
windowed_boundary = chain._scene_dependency_record(
    windowed_plan, 5, None)["scopes"]["incoming_boundary"]
assert windowed_boundary["visual_context_start_frame"] == 12

# Explicitly spelling the historical tail canonicalizes back to absence.
tail_plan_source = json.loads(json.dumps(windowed_plan_source))
tail_plan_source["shots"][4]["visual_context_start_frame"] = 80
tail_plan = chain._normalize_plan(
    json.dumps(tail_plan_source),
    "tail-context-test", 64, 64, 5, "video", "head", "disabled",
    "generated_audio", 5, 1.0, 8, 11, 18, "body:auto:v1", 0,
    "latent_guide")
assert "visual_context_start_frame" not in tail_plan["shots"][4]

source_frames = torch.full((5, 2, 2, 3), 3.0)
source_video = torch.full((1, 24, 2, 2, 2), 30.0)
immediate_video = torch.full((1, 24, 2, 2, 2), 40.0)
immediate_audio = torch.full((1, 32, 2), 44.0)
original_loader = chain._st_load
original_streams = chain._streams_from_latent
chain._st_load = lambda _path: {
    "context_frames": source_frames, "video": source_video,
}
chain._streams_from_latent = lambda value: value["samples"]
try:
    nonlinear_state = {
        "plan": nonlinear_plan, "index": 5,
        "previous_frames": torch.full((5, 2, 2, 3), 4.0),
        "previous_latent": {
            "samples": [immediate_video, immediate_audio]},
        "segments": [
            {"index": scene, "id": nonlinear_plan["shots"][scene - 1]["id"],
             "checkpoint": "scene_%d.safetensors" % scene,
             "revision": "r%d" % scene,
             "checkpoint_sha256": "h%d" % scene}
            for scene in range(1, 5)
        ],
    }
    selected_state = chain._visual_context_state(nonlinear_state)
    assert selected_state is not nonlinear_state
    assert selected_state["previous_frames"] is source_frames
    assert selected_state["previous_latent"]["samples"][0] is source_video
    assert selected_state["previous_latent"]["samples"][1] is immediate_audio
    assert [item["index"] for item in selected_state["segments"]] == [1, 2, 3]
    assert nonlinear_state["previous_latent"]["samples"][0] is immediate_video
    assert chain._visual_context_state(nonlinear_state) is selected_state
finally:
    chain._st_load = original_loader
    chain._streams_from_latent = original_streams

class WindowVAE:
    def __init__(self):
        self.decoded = None

    def decode(self, video):
        self.decoded = video.detach().clone()
        values = torch.arange(5, dtype=torch.float32).reshape(5, 1, 1, 1)
        return values.expand(5, 2, 2, 3).clone()

    def encode(self, _frames):
        raise AssertionError("native context selection must not re-encode RGB")

window_vae = WindowVAE()
chain._st_load = lambda _path: {
    "context_frames": torch.arange(
        85, 90, dtype=torch.float32,
    ).reshape(5, 1, 1, 1).expand(5, 2, 2, 3).clone(),
    "video": torch.arange(27, dtype=torch.float32).reshape(
        1, 1, 27, 1, 1).expand(1, 24, 27, 2, 2).clone(),
}
chain._streams_from_latent = lambda value: value["samples"]
try:
    windowed_state = chain._visual_context_state({
        "plan": windowed_plan, "index": 5,
        "previous_frames": torch.full((5, 2, 2, 3), 4.0),
        "previous_latent": {
            "samples": [immediate_video, immediate_audio]},
        "segments": [
            {"index": scene,
             "id": windowed_plan["shots"][scene - 1]["id"],
             "checkpoint": "scene_%d.safetensors" % scene,
             "revision": "r%d" % scene,
             "checkpoint_sha256": "h%d" % scene,
             "raw_frames": 90,
             "delivered_frames": 90 if scene == 1 else 85}
            for scene in range(1, 5)
        ],
    }, vae=window_vae)
    assert windowed_state["_visual_context_resolved_start_frame"] == 12
    assert windowed_state["previous_frames"].shape[0] == 0
    selected_video = windowed_state["previous_latent"]["samples"][0]
    assert selected_video.shape[2] == 2
    assert torch.all(selected_video[:, :, 0] == 5.0)
    assert torch.all(selected_video[:, :, 1] == 6.0)
    recovered = chain._previous_context_frames(windowed_state, window_vae, 5)
    assert recovered.shape[0] == 5
    assert torch.equal(window_vae.decoded, selected_video)
    assert windowed_state["previous_latent"]["samples"][1] is immediate_audio
finally:
    chain._st_load = original_loader
    chain._streams_from_latent = original_streams

# Two independent saved picture tails can form one H3-phase-safe prefix. The
# first block may come from a chronologically newer scene than the second;
# their explicit order in the Plan is what matters. Audio stays the complete
# immediate-predecessor latent and is never spliced at the visual seam.
composed_plan = chain._normalize_plan(
    json.dumps({"shots": [
        {"id": name, "prompt": name, "length": 90,
         **({"visual_context_source": "three",
             "visual_context_lead_source": "four",
             "visual_context_lead_frames": 5,
             "video_blend_frames": 0} if name == "five" else {})}
        for name in ("one", "two", "three", "four", "five")
    ]}),
    "composed-context-test", 64, 64, 39, "video", "head", "disabled",
    "generated_audio", 39, 1.0, 8, 11, 18, "body:auto:v1", 0,
    "masked_av")
assert composed_plan["shots"][4]["visual_context_source"] == "three"
assert composed_plan["shots"][4]["visual_context_lead_source"] == "four"
assert composed_plan["shots"][4]["visual_context_lead_frames"] == 5
assert chain._resume_context_predecessors(composed_plan, 5) == {
    "visual": 3, "audio": 4, "scenes": [3, 4], "visual_lead": 4,
}
composed_boundary = chain._scene_dependency_record(
    composed_plan, 5, None)["scopes"]["incoming_boundary"]
assert composed_boundary["visual_context_source_scene"] == 3
assert composed_boundary["visual_context_lead_source_scene"] == 4
assert composed_boundary["visual_context_lead_source_id"] == "four"
assert composed_boundary["visual_context_lead_frames"] == 5
composed_revision = chain._checkpoint_plan_revision({
    "index": 5, "id": "five", "revision": "r5",
    "seed": "5", "steps": 8, "raw_frames": 90,
    "segment": "scene_5.mp4",
    "visual_context_source_id": "three",
    "visual_context_start_frame": 8,
    "visual_context_lead_source_id": "four",
    "visual_context_lead_frames": 5,
    "visual_context_lead_start_frame": 9,
})
assert composed_revision["visual_context_source"] == "three"
assert composed_revision["visual_context_start_frame"] == 8
assert composed_revision["visual_context_lead_source"] == "four"
assert composed_revision["visual_context_lead_frames"] == 5
assert composed_revision["visual_context_lead_start_frame"] == 9

scene3_frames = torch.full((39, 2, 2, 3), 3.0)
scene4_frames = torch.full((39, 2, 2, 3), 4.0)
scene3_video = (30.0 + torch.arange(27, dtype=torch.float32)).reshape(
    1, 1, 27, 1, 1).expand(1, 24, 27, 2, 2).clone()
scene4_video = (40.0 + torch.arange(27, dtype=torch.float32)).reshape(
    1, 1, 27, 1, 1).expand(1, 24, 27, 2, 2).clone()
full_immediate_audio = torch.full((1, 32, 2, 80), 44.0)

def composed_loader(path):
    scene = 4 if "scene_4" in str(path) else 3
    return {
        "context_frames": scene4_frames if scene == 4 else scene3_frames,
        "video": scene4_video if scene == 4 else scene3_video,
    }

chain._st_load = composed_loader
chain._streams_from_latent = lambda value: value["samples"]
try:
    composed_state = {
        "plan": composed_plan, "index": 5,
        "previous_frames": scene4_frames,
        "previous_latent": {
            "samples": [scene4_video, full_immediate_audio]},
        "segments": [
            {"index": scene, "id": composed_plan["shots"][scene - 1]["id"],
             "checkpoint": "scene_%d.safetensors" % scene,
             "revision": "r%d" % scene,
             "checkpoint_sha256": "h%d" % scene}
            for scene in range(1, 5)
        ],
    }
    composed_state = chain._visual_context_state(composed_state)
    frames = composed_state["previous_frames"]
    video, audio_latent = composed_state["previous_latent"]["samples"]
    assert frames.shape[0] == 39
    assert torch.all(frames[:5] == 4.0)
    assert torch.all(frames[5:] == 3.0)
    assert video.shape[2] == 12
    assert torch.all(video[:, :, 0] == 65.0)
    assert torch.all(video[:, :, 1] == 66.0)
    assert torch.all(video[:, :, 2] == 47.0)
    assert torch.all(video[:, :, -1] == 56.0)
    assert audio_latent is full_immediate_audio
    assert composed_state["visual_context_source_segment"]["index"] == 3
    assert composed_state["visual_context_lead_segment"]["index"] == 4

    # Each side of an addition can independently select a native latent crop.
    # An unavailable RGB mirror is decoded from the assembled crop, never
    # re-encoded into a replacement latent.
    windowed_composed_plan = json.loads(json.dumps(composed_plan))
    windowed_composed_plan["shots"][4]["visual_context_start_frame"] = 0
    windowed_composed_plan["shots"][4][
        "visual_context_lead_start_frame"] = 12

    class WindowedCompositionVAE:
        def __init__(self):
            self.decoded = None

        def decode(self, video):
            self.decoded = video.detach().clone()
            return torch.full((39, 2, 2, 3), 8.0)

        def encode(self, _frames):
            raise AssertionError(
                "native composed context must not re-encode RGB")

    windowed_composition_vae = WindowedCompositionVAE()
    windowed_composed_state = chain._visual_context_state({
        "plan": windowed_composed_plan, "index": 5,
        "previous_frames": scene4_frames,
        "previous_latent": {
            "samples": [scene4_video, full_immediate_audio]},
        "segments": [
            {"index": scene,
             "id": windowed_composed_plan["shots"][scene - 1]["id"],
             "checkpoint": "scene_%d.safetensors" % scene,
             "revision": "r%d" % scene,
             "checkpoint_sha256": "h%d" % scene,
             "raw_frames": 90,
             "delivered_frames": 90 if scene == 1 else 51}
            for scene in range(1, 5)
        ],
    }, vae=windowed_composition_vae)
    assert windowed_composed_state["previous_frames"].shape[0] == 0
    windowed_video = windowed_composed_state[
        "previous_latent"]["samples"][0]
    assert windowed_video.shape[2] == 12
    assert torch.all(windowed_video[:, :, 0] == 55.0)
    assert torch.all(windowed_video[:, :, 1] == 56.0)
    assert torch.all(windowed_video[:, :, 2] == 42.0)
    assert torch.all(windowed_video[:, :, -1] == 51.0)
    windowed_frames = chain._previous_context_frames(
        windowed_composed_state, windowed_composition_vae, 39)
    assert torch.all(windowed_frames == 8.0)
    assert torch.equal(windowed_composition_vae.decoded, windowed_video)

    # The inverse ordered split is equally authorable. Its latest aligned lead
    # crop intentionally stops before the physical tail so both saved latent
    # blocks match their target temporal phases.
    reverse_plan = json.loads(json.dumps(composed_plan))
    reverse_plan["shots"][4]["visual_context_lead_frames"] = 17
    assert chain._shot_visual_context_lead_frames(
        reverse_plan["shots"][4], 39) == 17

    reverse_state = chain._visual_context_state({
        "plan": reverse_plan, "index": 5,
        "previous_frames": scene4_frames,
        "previous_latent": {
            "samples": [scene4_video, full_immediate_audio]},
        "segments": [
            {"index": scene, "id": reverse_plan["shots"][scene - 1]["id"],
             "checkpoint": "scene_%d.safetensors" % scene,
             "revision": "r%d" % scene,
             "checkpoint_sha256": "h%d" % scene}
            for scene in range(1, 5)
        ],
    })
    reverse_frames = reverse_state["previous_frames"]
    reverse_video = reverse_state["previous_latent"]["samples"][0]
    assert torch.all(reverse_frames[:17] == 4.0)
    assert torch.all(reverse_frames[17:] == 3.0)
    assert torch.all(reverse_video[:, :, 0] == 60.0)
    assert torch.all(reverse_video[:, :, 4] == 64.0)
    assert torch.all(reverse_video[:, :, 5] == 50.0)
    assert torch.all(reverse_video[:, :, -1] == 56.0)
    assert reverse_state["previous_latent"]["samples"][1] is full_immediate_audio
finally:
    chain._st_load = original_loader
    chain._streams_from_latent = original_streams

short_scene3_frames = scene3_frames[-5:]
short_scene4_frames = scene4_frames[-5:]

def short_composed_loader(path):
    scene = 4 if "scene_4" in str(path) else 3
    return {
        "context_frames": (
            short_scene4_frames if scene == 4 else short_scene3_frames),
        "video": scene4_video if scene == 4 else scene3_video,
    }

class ComposedDecodeVAE:
    def __init__(self):
        self.input = None

    def decode(self, latent):
        self.input = latent
        return torch.full((39, 2, 2, 3), 9.0)

chain._st_load = short_composed_loader
chain._streams_from_latent = lambda value: value["samples"]
try:
    short_state = chain._visual_context_state({
        "plan": composed_plan, "index": 5,
        "previous_frames": short_scene4_frames,
        "previous_latent": {
            "samples": [scene4_video, full_immediate_audio]},
        "segments": [
            {"index": scene, "id": composed_plan["shots"][scene - 1]["id"],
             "checkpoint": "scene_%d.safetensors" % scene}
            for scene in range(1, 5)
        ],
    })
    assert short_state["previous_frames"].shape[0] == 0
    decoder = ComposedDecodeVAE()
    recovered = chain._previous_context_frames(short_state, decoder, 39)
    assert recovered.shape[0] == 39
    assert torch.all(recovered == 9.0)
    assert decoder.input is short_state["previous_latent"]["samples"][0]
    assert short_state["previous_frames"] is recovered
finally:
    chain._st_load = original_loader
    chain._streams_from_latent = original_streams

for invalid_patch, expected in (
        # This start fits inside the movie, but it bisects an H3 temporal
        # latent block and therefore cannot be represented as a direct crop.
        ({"visual_context_start_frame": 11}, "native temporal latent lattice"),
        ({"visual_context_lead_source": "three",
          "visual_context_lead_frames": 5}, "different from"),
        ({"visual_context_lead_source": "four",
          "visual_context_lead_frames": 6}, "must be one of"),
        ({"visual_context_lead_source": "four",
          "visual_context_lead_frames": 5,
          "visual_context_lead_start_frame": 47}, "must be between"),
        ({"visual_context_lead_source": "four",
          "visual_context_lead_frames": 5,
          "video_blend_frames": 2}, "video_blend_frames must be 0")):
    invalid_shots = [
        {"id": name, "prompt": name, "length": 90,
         **({"visual_context_source": "three", **invalid_patch}
            if name == "five" else {})}
        for name in ("one", "two", "three", "four", "five")
    ]
    try:
        chain._normalize_plan(
            json.dumps({"shots": invalid_shots}),
            "invalid-composed-context", 64, 64, 39, "video", "head",
            "disabled", "generated_audio", 39, 1.0, 8, 11, 18,
            "body:auto:v1", 0, "masked_av")
    except ValueError as exc:
        assert expected in str(exc)
    else:
        raise AssertionError("invalid composed visual context was accepted")

try:
    chain._normalize_plan(
        json.dumps({"shots": [
            {"id": name, "prompt": name, "length": 39,
             **({"visual_context_source": "three",
                 "video_blend_frames": 2} if name == "five" else {})}
            for name in ("one", "two", "three", "four", "five")
        ]}),
        "invalid-nonlinear-blend", 64, 64, 5, "video", "head",
        "disabled", "generated_audio", 5, 1.0, 8, 11, 18,
        "body:auto:v1", 0, "guide")
except ValueError as exc:
    assert "video_blend_frames must be 0" in str(exc)
else:
    raise AssertionError("non-linear visual context accepted an assembly blend")

formatted = chain._format_dependency_mismatches(boundary_diffs)
assert "scene 2 incoming_boundary.context_length" in formatted
assert chain._scene_dependency_diffs({"version": "legacy"}, scene1_a) == []
assert set(scene1_a["scopes"]) == set(chain.DEPENDENCY_SCOPES)
assert scene1_a["version"] == chain.SCENE_DEPENDENCY_VERSION

masked_plan = chain._normalize_plan(
    json.dumps({"shots": [
        {"id": "one", "prompt": "@actor opens.", "length": 90},
        {"id": "two", "prompt": "@actor continues.", "length": 90},
    ]}),
    "masked-dependency-test", 64, 64, 39, "video", "head", "disabled",
    "source_track", 39, 1.0, 8, 11, 18, "body:auto:v1", 0,
    "audio_feathered_av")
masked_dependency = chain._scene_dependency_record(masked_plan, 2, None)
assert masked_dependency["scopes"]["incoming_boundary"][
    "masked_audio_contract"] == "raw_source_window_v2"
legacy_masked_dependency = json.loads(json.dumps(masked_dependency))
del legacy_masked_dependency["scopes"]["incoming_boundary"][
    "masked_audio_contract"]
contract_diffs = chain._scene_dependency_diffs(
    legacy_masked_dependency, masked_dependency)
assert contract_diffs == [{
    "scope": "incoming_boundary",
    "scene": 2,
    "field": "masked_audio_contract",
    "saved": None,
    "current": "raw_source_window_v2",
    "regeneration_required": True,
}]

detail_plan = chain._normalize_plan(
    json.dumps({"shots": [
        {"id": "one", "prompt": "@actor opens.", "length": 90},
        {"id": "two", "prompt": "@actor continues.", "length": 90},
    ]}),
    "detail-av-dependency-test", 64, 64, 39, "video", "head", "disabled",
    "source_track", 39, 1.0, 8, 11, 18, "body:auto:v1", 0,
    "tapered_av")
detail_dependency = chain._scene_dependency_record(detail_plan, 2, None)
assert detail_dependency["scopes"]["incoming_boundary"][
    "detail_av_recipe"] == chain.DETAIL_AV_RECIPE
changed_detail_dependency = json.loads(json.dumps(detail_dependency))
changed_detail_dependency["scopes"]["incoming_boundary"][
    "detail_av_recipe"]["alpha"] = 0.40
detail_diffs = chain._scene_dependency_diffs(
    changed_detail_dependency, detail_dependency)
assert detail_diffs == [{
    "scope": "incoming_boundary",
    "scene": 2,
    "field": "detail_av_recipe.alpha",
    "saved": 0.4,
    "current": 0.30,
    "regeneration_required": True,
}]

drift_plan = chain._normalize_plan(
    json.dumps({"shots": [
        {"id": "one", "prompt": "@actor opens.", "length": 90},
        {"id": "two", "prompt": "@actor continues.", "length": 90},
    ]}),
    "drift-av-dependency-test", 64, 64, 39, "video", "head", "disabled",
    "source_track", 39, 1.0, 20, 11, 18, "body:auto:v1", 0,
    "drift_control_av")
drift_dependency = chain._scene_dependency_record(drift_plan, 2, None)
assert drift_dependency["scopes"]["incoming_boundary"][
    "drift_control_av_recipe"] == chain.DRIFT_CONTROL_AV_RECIPE
changed_drift_dependency = json.loads(json.dumps(drift_dependency))
changed_drift_dependency["scopes"]["incoming_boundary"][
    "drift_control_av_recipe"]["taper_steps"] = 3
drift_diffs = chain._scene_dependency_diffs(
    changed_drift_dependency, drift_dependency)
assert drift_diffs == [{
    "scope": "incoming_boundary",
    "scene": 2,
    "field": "drift_control_av_recipe.taper_steps",
    "saved": 3,
    "current": 4,
    "regeneration_required": True,
}]

color_drift_plan = chain._normalize_plan(
    json.dumps({"shots": [
        {"id": "one", "prompt": "@actor opens.", "length": 90},
        {"id": "two", "prompt": "@actor continues.", "length": 90},
    ]}),
    "color-drift-av-dependency-test", 64, 64, 39, "video", "head",
    "disabled", "source_track", 39, 1.0, 20, 11, 18, "body:auto:v1",
    0, "color_stable_drift_av")
color_drift_dependency = chain._scene_dependency_record(
    color_drift_plan, 2, None)
color_boundary = color_drift_dependency["scopes"]["incoming_boundary"]
assert color_boundary[
    "drift_control_av_recipe"] == chain.DRIFT_CONTROL_AV_RECIPE
assert color_boundary[
    "latent_color_carry_recipe"] == chain.LATENT_COLOR_CARRY_RECIPE
changed_color_dependency = json.loads(json.dumps(color_drift_dependency))
changed_color_dependency["scopes"]["incoming_boundary"][
    "latent_color_carry_recipe"]["strength"] = 0.25
color_diffs = chain._scene_dependency_diffs(
    changed_color_dependency, color_drift_dependency)
assert color_diffs == [{
    "scope": "incoming_boundary",
    "scene": 2,
    "field": "latent_color_carry_recipe.strength",
    "saved": 0.25,
    "current": 0.50,
    "regeneration_required": True,
}]

# Spatial reset is scheduled on the incoming scene, not inherited globally.
proxy_plan = chain._normalize_plan(
    json.dumps({"shots": [
        {"id": "one", "prompt": "one", "length": 90},
        {"id": "two", "prompt": "two", "length": 90},
        {"id": "three", "prompt": "three", "length": 90},
        {"id": "four", "prompt": "four", "length": 90,
         "context_spatial_proxy": "latent_5_6"},
    ]}),
    "scheduled-proxy-test", 1376, 768, 39, "video", "head", "disabled",
    "source_track", 39, 1.0, 8, 11, 18, "body:auto:v1", 0,
    "masked_av")
assert all("context_spatial_proxy" not in shot
           for shot in proxy_plan["shots"][:3])
assert proxy_plan["shots"][3]["context_spatial_proxy"] == "latent_5_6"
assert chain._context_spatial_proxy_size(1376, 768) == (1152, 640)
scene3_proxy_dependency = chain._scene_dependency_record(proxy_plan, 3, None)
scene4_proxy_dependency = chain._scene_dependency_record(proxy_plan, 4, None)
assert "context_spatial_proxy" not in scene3_proxy_dependency[
    "scopes"]["incoming_boundary"]
assert scene4_proxy_dependency["scopes"]["incoming_boundary"][
    "context_spatial_proxy"] == "latent_5_6"
assert scene4_proxy_dependency["scopes"]["incoming_boundary"][
    "context_spatial_proxy_recipe"] == chain.CONTEXT_SPATIAL_PROXY_RECIPE

native_plan = chain._normalize_plan(
    json.dumps({"shots": [
        {"id": name, "prompt": name, "length": 90}
        for name in ("one", "two", "three", "four")
    ]}),
    "scheduled-proxy-test", 1376, 768, 39, "video", "head", "disabled",
    "source_track", 39, 1.0, 8, 11, 18, "body:auto:v1", 0,
    "masked_av")
assert chain._history_hash(proxy_plan, 3) == chain._history_hash(native_plan, 3)
assert chain._history_hash(proxy_plan, 4) != chain._history_hash(native_plan, 4)
assert chain._scene_dependency_diffs(
    chain._scene_dependency_record(native_plan, 3, None),
    scene3_proxy_dependency) == []
proxy_diffs = chain._scene_dependency_diffs(
    chain._scene_dependency_record(native_plan, 4, None),
    scene4_proxy_dependency)
assert proxy_diffs
assert all(item["scene"] == 4 and item["scope"] == "incoming_boundary"
           and item["regeneration_required"] for item in proxy_diffs)

guide_proxy_plan = chain._normalize_plan(
    json.dumps({"shots": [
        {"id": "one", "prompt": "one", "length": 39},
        {"id": "two", "prompt": "two", "length": 39,
         "context_spatial_proxy": "rgb_5_6"},
    ]}),
    "rgb-proxy-test", 1376, 768, 5, "video", "head", "disabled",
    "source_track", 5, 1.0, 8, 11, 18, "body:auto:v1", 0,
    "guide")
assert guide_proxy_plan["shots"][1]["context_spatial_proxy"] == "rgb_5_6"

for invalid_proxy, mode, expected in (
        ("rgb_5_6", "masked_av", "low-grid 5/6"),
        ("latent_5_6", "guide", "latent 5/6")):
    try:
        chain._normalize_plan(
            json.dumps({"shots": [
                {"id": "one", "prompt": "one", "length": 90},
                {"id": "two", "prompt": "two", "length": 90,
                 "context_spatial_proxy": invalid_proxy},
            ]}),
            "invalid-proxy", 64, 64, 39, "video", "head", "disabled",
            "source_track", 39, 1.0, 8, 11, 18, "body:auto:v1", 0,
            mode)
    except ValueError as exc:
        assert expected in str(exc)
    else:
        raise AssertionError("incompatible context spatial proxy was accepted")

print("H3 scene dependencies: scene-local PCM, boundary isolation, assembly exclusion, and structured diffs pass")


# Preflight exposes the same field-level mismatch against saved metadata.
with tempfile.TemporaryDirectory() as temporary:
    root = pathlib.Path(temporary)
    chain._output_root = lambda: str(root)
    resume_plan = chain._normalize_plan(
        json.dumps({"shots": [
            {"id": "one", "prompt": "saved prompt", "length": 22},
            {"id": "two", "prompt": "next prompt", "length": 22},
        ]}),
        "dependency-resume", 64, 64, 5, "video", "head", "disabled",
        "generated_audio", 5, 1.0, 8, 9, 18, "body:auto:v1", 0,
        "guide")
    resume_plan = chain._plan_with_source_audio(resume_plan, None)
    saved_dependency = chain._scene_dependency_record(resume_plan, 1, None)
    paths = chain._artifact_paths(resume_plan, 1)
    pathlib.Path(paths["segment"]).parent.mkdir(parents=True)
    pathlib.Path(paths["checkpoint"]).parent.mkdir(parents=True)
    pathlib.Path(paths["segment"]).write_bytes(b"video")
    pathlib.Path(paths["checkpoint"]).write_bytes(b"checkpoint")
    prompt_path = pathlib.Path(paths["segment"]).with_suffix(".prompt.txt")
    prompt_path.write_text("saved prompt", encoding="utf-8")
    history = chain._history_hash(resume_plan, 1)
    segment = {
        "index": 1,
        "segment": chain._relative_output_path(paths["segment"]),
        "checkpoint": chain._relative_output_path(paths["checkpoint"]),
        "prompt_file": chain._relative_output_path(str(prompt_path)),
        "segment_sha256": chain._file_sha256(paths["segment"]),
        "checkpoint_sha256": chain._file_sha256(paths["checkpoint"]),
        "prompt_file_sha256": chain._file_sha256(str(prompt_path)),
        "prompt_hash": resume_plan["shots"][0]["prompt_hash"],
        "history_hash": history,
    }
    pathlib.Path(paths["metadata"]).write_text(json.dumps({
        "history_hash": history,
        "compatibility": resume_plan["compatibility"],
        "scene_dependency": saved_dependency,
        "segment": segment,
    }), encoding="utf-8")
    changed_plan = json.loads(json.dumps(resume_plan))
    changed_plan["shots"][0]["prompt"] = "changed prompt"
    changed_plan["shots"][0]["prompt_hash"] = chain.hashlib.sha256(
        b"changed prompt").hexdigest()
    diagnostic = {"errors": [], "warnings": []}
    resume = chain._preflight_resume(
        changed_plan, 2, True, diagnostic)
    assert resume["eligible"] is False
    mismatch = resume["predecessors"][0]["mismatches"][0]
    assert mismatch == {
        "scope": "scene_generation", "scene": 1,
        "field": "prompt_hash",
        "saved": resume_plan["shots"][0]["prompt_hash"],
        "current": changed_plan["shots"][0]["prompt_hash"],
        "regeneration_required": True,
    }

    # An explicitly independent selected scene consumes no predecessor state.
    # Its earlier clips retain their saved identity for assembly, so editing a
    # prior prompt cannot block the new zero-context sample.
    independent_plan = json.loads(json.dumps(changed_plan))
    independent_plan["shots"][1]["context_length"] = 0
    independent_plan["shots"][1]["audio_context_length"] = 0
    independent_report = {"errors": [], "warnings": []}
    independent_resume = chain._preflight_resume(
        independent_plan, 2, True, independent_report)
    assert independent_resume["eligible"] is True
    assert independent_resume["context_predecessor"] is None
    assert independent_resume["predecessors"][0]["mismatches"] == []

print("H3 structured resume preflight: field-level saved/current mismatch pass")


with tempfile.TemporaryDirectory() as temporary:
    root = pathlib.Path(temporary)
    chain._output_root = lambda: str(root)
    saved_plan = chain._plan_with_source_audio(nonlinear_plan, None)
    for scene in range(1, 5):
        paths = chain._artifact_paths(saved_plan, scene)
        pathlib.Path(paths["segment"]).parent.mkdir(parents=True, exist_ok=True)
        pathlib.Path(paths["checkpoint"]).parent.mkdir(
            parents=True, exist_ok=True)
        pathlib.Path(paths["segment"]).write_bytes(
            ("video-%d" % scene).encode())
        pathlib.Path(paths["checkpoint"]).write_bytes(
            ("checkpoint-%d" % scene).encode())
        history = chain._history_hash(saved_plan, scene)
        segment = {
            "index": scene,
            "id": saved_plan["shots"][scene - 1]["id"],
            "segment": chain._relative_output_path(paths["segment"]),
            "checkpoint": chain._relative_output_path(paths["checkpoint"]),
            "segment_sha256": chain._file_sha256(paths["segment"]),
            "checkpoint_sha256": chain._file_sha256(paths["checkpoint"]),
            "history_hash": history,
            "revision": "r%d" % scene,
        }
        pathlib.Path(paths["metadata"]).write_text(json.dumps({
            "history_hash": history,
            "compatibility": saved_plan["compatibility"],
            "scene_dependency": chain._scene_dependency_record(
                saved_plan, scene, None),
            "segment": segment,
        }), encoding="utf-8")

    changed_unconsumed = json.loads(json.dumps(saved_plan))
    changed_unconsumed["shots"][1]["prompt"] = "changed scene two"
    changed_unconsumed["shots"][1]["prompt_hash"] = (
        chain.hashlib.sha256(b"changed scene two").hexdigest())
    report = {"errors": [], "warnings": []}
    preflight = chain._preflight_resume(
        changed_unconsumed, 5, True, report)
    assert preflight["eligible"] is True
    assert preflight["context_sources"] == {
        "visual": 3, "audio": 4, "scenes": [3, 4]}
    assert preflight["predecessors"][1]["mismatches"] == []

    for consumed_scene in (3, 4):
        changed_consumed = json.loads(json.dumps(saved_plan))
        changed_consumed["shots"][consumed_scene - 1]["prompt"] = (
            "changed scene %d" % consumed_scene)
        changed_consumed["shots"][consumed_scene - 1]["prompt_hash"] = (
            chain.hashlib.sha256(
                changed_consumed["shots"][consumed_scene - 1][
                    "prompt"].encode()).hexdigest())
        report = {"errors": [], "warnings": []}
        blocked = chain._preflight_resume(
            changed_consumed, 5, True, report)
        assert blocked["eligible"] is False
        assert blocked["predecessors"][consumed_scene - 1]["mismatches"]

print("H3 non-linear resume preflight: visual scene 3 + audio scene 4 dependencies pass")
