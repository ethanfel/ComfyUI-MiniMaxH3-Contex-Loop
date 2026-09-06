#!/usr/bin/env python3
"""Exercise the compact, exact, and idempotent 0.5 workflow migration."""

import copy
import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "h3_migrate_v05", ROOT / "tools" / "migrate_v05_workflows.py")
migration = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migration)


def load(relative):
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


def nodes(workflow, node_type):
    return [node for node in workflow["nodes"] if node.get("type") == node_type]


def input_names(node):
    return [item["name"] for item in node.get("inputs", [])]


def socket(items, name):
    return next(item for item in items if item.get("name") == name)


def origin_for_input(workflow, input_socket):
    link = next(item for item in workflow["links"]
                if item[0] == input_socket["link"])
    return next(item for item in workflow["nodes"] if item["id"] == link[1])


def assert_original_names_first(workflow):
    for item in workflow["nodes"]:
        title = item.get("title")
        if title is None:
            continue
        original = migration.original_node_name(item["type"])
        assert title == original or title.startswith(original + " — "), (
            item["id"], item["type"], title, original)


def main():
    archived = load(
        "example_workflows/Archive/"
        "Ref2V Studio Legacy Scheduled - MiniMax H3.json")
    original_identity = {
        node["id"]: node["type"] for node in archived["nodes"]}
    migrated = migration.migrate(
        copy.deepcopy(archived), "custom-v0.4-studio.json")
    assert_original_names_first(migrated)

    for node_id, node_type in original_identity.items():
        match = next(node for node in migrated["nodes"]
                     if node["id"] == node_id)
        assert match["type"] == node_type
    assert len(nodes(migrated, "MiniMaxH3AudioPolicy")) == 0
    assert len(nodes(migrated, "MiniMaxH3TransitionPolicy")) == 0
    compact = nodes(migrated, "MiniMaxH3ChainPolicy")
    assert len(compact) == 1
    assert compact[0]["widgets_values"] == [
        "guide", "generated", "off", "on"]
    plan = nodes(migrated, "MiniMaxH3ChainPlan")[0]
    assert "audio_policy" not in input_names(plan)
    assert "transition_policy" not in input_names(plan)
    assert next(item for item in plan["inputs"]
                if item["name"] == "chain_policy")["link"] is not None
    studio = nodes(migrated, "MiniMaxH3ChainPlanStudio")[0]
    assert {"source_timeline", "source_audio", "tagged_references",
            "reference_schedule"}.issubset(input_names(studio))
    current = nodes(migrated, "MiniMaxH3ChainCurrent")[0]
    trim = nodes(migrated, "MiniMaxH3LoopTrim")[0]
    state_input = next(item for item in trim["inputs"]
                       if item["name"] == "state")
    state_link = next(item for item in migrated["links"]
                      if item[0] == state_input["link"])
    assert state_link[1:3] == [current["id"], 0]
    assert next(item for item in trim["inputs"]
                if item["name"] == "retain_overlap_frames")["link"] is None

    stable = copy.deepcopy(migrated)
    migration.migrate(migrated, "custom-v0.4-studio.json")
    assert migrated == stable

    source_demo = load(
        "example_workflows/Archive/pre-0.6-nightly/"
        "Ref2V Studio Tagged Source Audio - MiniMax H3.json")
    migration.migrate(source_demo, migration.SOURCE_AUDIO_DEMO)
    assert_original_names_first(source_demo)
    stable_demo = copy.deepcopy(source_demo)
    migration.migrate(source_demo, migration.SOURCE_AUDIO_DEMO)
    assert source_demo == stable_demo

    # Recreate issue #38's old topology and verify migration repairs it: the
    # dynamic Current Shot slice must become the static full Load Audio track,
    # and the complete registry fingerprint must return to Plan.
    legacy_source_demo = copy.deepcopy(stable_demo)
    legacy_loader = nodes(legacy_source_demo, "LoadAudio")[0]
    legacy_audio_ref = nodes(
        legacy_source_demo, "MiniMaxH3TaggedAudioReference")[0]
    legacy_current = nodes(legacy_source_demo, "MiniMaxH3ChainCurrent")[0]
    legacy_plan = nodes(legacy_source_demo, "MiniMaxH3ChainPlan")[0]
    legacy_conditioner = nodes(
        legacy_source_demo, "MiniMaxH3TaggedReferenceToVideo")[0]
    audio_link_id = socket(legacy_audio_ref["inputs"], "audio")["link"]
    audio_link = next(item for item in legacy_source_demo["links"]
                      if item[0] == audio_link_id)
    audio_link[1:3] = [legacy_current["id"], 12]
    socket(legacy_loader["outputs"], "AUDIO")["links"].remove(audio_link_id)
    socket(legacy_current["outputs"],
           "source_audio_slice")["links"] = [audio_link_id]
    legacy_audio_ref["widgets_values"] = ["audio_1", "standalone", False]

    previous_link_id = socket(
        legacy_audio_ref["inputs"], "previous")["link"]
    previous_link = next(item for item in legacy_source_demo["links"]
                         if item[0] == previous_link_id)
    legacy_picture = next(item for item in legacy_source_demo["nodes"]
                          if item["id"] == previous_link[1])
    fingerprint_link_id = socket(
        legacy_plan["inputs"], "generation_fingerprint")["link"]
    fingerprint_link = next(item for item in legacy_source_demo["links"]
                            if item[0] == fingerprint_link_id)
    fingerprint_link[1:3] = [legacy_picture["id"], 1]
    socket(legacy_audio_ref["outputs"],
           "reference_fingerprint")["links"] = None
    socket(legacy_picture["outputs"],
           "reference_fingerprint")["links"] = [fingerprint_link_id]
    legacy_conditioner["widgets_values"].pop()
    legacy_conditioner["outputs"] = [
        item for item in legacy_conditioner["outputs"]
        if item["name"] != "refmod_sources"]
    legacy_studio = nodes(
        legacy_source_demo, "MiniMaxH3ChainPlanStudio")[0]
    preflight_link_id = socket(
        legacy_studio["inputs"], "tagged_references")["link"]
    legacy_source_demo["links"] = [
        item for item in legacy_source_demo["links"]
        if item[0] != preflight_link_id]
    socket(legacy_audio_ref["outputs"], "references")["links"].remove(
        preflight_link_id)
    socket(legacy_studio["inputs"], "tagged_references")["link"] = None
    legacy_source_demo["last_link_id"] = preflight_link_id - 1

    migration.migrate(legacy_source_demo, migration.SOURCE_AUDIO_DEMO)
    assert legacy_source_demo == stable_demo
    assert len(nodes(source_demo, "MiniMaxH3SourceTimeline")) == 1
    assert len(nodes(source_demo, "MiniMaxH3AudioPolicy")) == 0
    assert len(nodes(source_demo, "MiniMaxH3TransitionPolicy")) == 0
    compact = nodes(source_demo, "MiniMaxH3ChainPolicy")
    assert len(compact) == 1
    assert compact[0]["widgets_values"] == [
        "guide", "source", "on", "off"]
    audio_loader = nodes(source_demo, "LoadAudio")[0]
    audio_ref = nodes(source_demo, "MiniMaxH3TaggedAudioReference")[0]
    source_current = nodes(source_demo, "MiniMaxH3ChainCurrent")[0]
    source_plan = nodes(source_demo, "MiniMaxH3ChainPlan")[0]
    source_studio = nodes(source_demo, "MiniMaxH3ChainPlanStudio")[0]
    source_conditioner = nodes(
        source_demo, "MiniMaxH3TaggedReferenceToVideo")[0]
    assert audio_ref["widgets_values"] == [
        "audio_1", "source_timeline", True]
    assert origin_for_input(
        source_demo, socket(audio_ref["inputs"], "audio")) == audio_loader
    assert socket(source_current["outputs"],
                  "source_audio_slice")["links"] is None
    assert origin_for_input(
        source_demo,
        socket(source_plan["inputs"], "generation_fingerprint")) == audio_ref
    assert origin_for_input(
        source_demo,
        socket(source_studio["inputs"], "tagged_references")) == audio_ref
    assert source_conditioner["widgets_values"][-1] == "native_ref2va"
    assert socket(source_conditioner["outputs"],
                  "refmod_sources")["type"] == "H3_REF_LIST"

    drift_plan = {
        "pos": [100, 200],
        "widgets_values": [
            "{}", "drift", "", 960, 544, 39, "video", "head",
            "disabled", "generated_audio", 39, 15.0, 20, 0, 18, 0,
            "drift_control_av",
        ],
    }
    drift_policy, drift_output = migration._chain_policy_node(
        drift_plan, ("generated", "off", "on"),
        "drift_control_av", 39, 39)
    assert drift_policy["type"] == "MiniMaxH3Legacy04PolicyAdapter"
    assert drift_policy["widgets_values"] == [
        "generated_audio", "drift_control_av", 39, 39]
    assert drift_output == 0

    mismatched_audio, mismatch_output = migration._chain_policy_node(
        drift_plan, ("generated", "off", "on"), "masked_av", 39, 22)
    assert mismatched_audio["type"] == "MiniMaxH3Legacy04PolicyAdapter"
    assert mismatched_audio["widgets_values"] == [
        "generated_audio", "masked_av", 39, 22]
    assert mismatch_output == 0

    assert [path.name for path in migration.active_paths()] == list(
        migration.MAINTAINED_DEMOS)
    for path in migration.active_paths():
        maintained = json.loads(path.read_text(encoding="utf-8"))
        stable_maintained = copy.deepcopy(maintained)
        migration.migrate(maintained, path.name)
        assert maintained == stable_maintained, path.name
        assert_original_names_first(maintained)

    print("v0.5 workflow migration: compact, exact, and idempotent")


if __name__ == "__main__":
    main()
