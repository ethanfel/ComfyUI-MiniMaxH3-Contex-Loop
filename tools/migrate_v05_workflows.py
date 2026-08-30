#!/usr/bin/env python3
"""Migrate maintained H3 demo workflow JSON to the compact 0.5 topology.

The sampling body and existing generation settings stay untouched. Normal
audio and boundary intent is collapsed to one Chain Policy wire. Settings that
cannot be represented by the four supported compact transition presets are
preserved exactly through one Legacy 0.4 Policy Adapter node. The source-audio
reference demo also adopts the single typed Source Timeline route. Every
custom demo title starts with the node's registered display name so the graph
still teaches the real node names.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "example_workflows"
SOURCE_AUDIO_DEMO = "Ref2V Studio Tagged Source Audio - MiniMax H3.json"
MAINTAINED_DEMOS = (
    "Ref2V Sequential Motion - EXPERIMENTAL - MiniMax H3.json",
    "Masked AV Bridge - Two Clips - MiniMax H3.json",
    "Masked AV Extension - Chain + Reference Image - MiniMax H3.json",
    "Masked AV Extension - Single Clip - MiniMax H3.json",
    "Masked Video Inpaint - MiniMax H3.json",
    "FL2V Normal - MiniMax H3.json",
    "I2V Normal - MiniMax H3.json",
    "I2V Studio - MiniMax H3.json",
    "Ref2V Basic - MiniMax H3.json",
    "Ref2V Masked Video Inpaint - MiniMax H3.json",
    SOURCE_AUDIO_DEMO,
    "Ref2V Studio Tagged - MiniMax H3.json",
    "Ref2V Tagged - MiniMax H3.json",
    "T2V Normal - MiniMax H3.json",
    "T2V Studio - MiniMax H3.json",
)

# Exact display names exposed by ComfyUI's /object_info for every node type
# used by the maintained demos when this migration was authored. Types whose
# display_name is null (and frontend-only nodes such as Note) intentionally
# fall back to their canonical class type below.
NODE_DISPLAY_NAMES = {
    "BasicGuider": "Basic Guider",
    "CLIPLoader": "Load CLIP",
    "LoadAudio": "Load Audio",
    "LoadImage": "Load Image",
    "LoadImageMask": "Load Image (as Mask)",
    "LoadVideo": "Load Video",
    "LoraLoaderModelOnly": "Load LoRA",
    "MiniMaxH3ChainAssemble": "MiniMax H3 Contex Loop Assemble",
    "MiniMaxH3ChainContext": "MiniMax H3 Contex Loop Context",
    "MiniMaxH3ChainCurrent": "MiniMax H3 Contex Loop Current Shot",
    "MiniMaxH3ChainExternalVideo": "MiniMax H3 Existing Video Context",
    "MiniMaxH3ChainFirstSceneImage": "MiniMax H3 Frame Gate",
    "MiniMaxH3ChainFrameIndexSwitch": "MiniMax H3 Frame Index Switch",
    "MiniMaxH3ChainLoopEnd": "MiniMax H3 Contex Loop End",
    "MiniMaxH3ChainLoopStart": "MiniMax H3 Contex Loop Start",
    "MiniMaxH3ChainManifestLoad": "MiniMax H3 Contex Loop Load Manifest",
    "MiniMaxH3ChainPlan": "MiniMax H3 Contex Loop Plan",
    "MiniMaxH3ChainPlanStudio": "MiniMax H3 Plan Studio (Experimental)",
    "MiniMaxH3ChainPolicy": "MiniMax H3 Manual Chain Policy (Legacy)",
    "MiniMaxH3AdvancedPolicy": "MiniMax H3 Advanced Policy Override",
    "MiniMaxH3Legacy04PolicyAdapter": (
        "MiniMax H3 Legacy 0.4 Policy Adapter"),
    "MiniMaxH3ChainPreflight": "MiniMax H3 Chain Preflight",
    "MiniMaxH3ChainReview": "MiniMax H3 Contex Loop Review Gate",
    "MiniMaxH3ChainRunManager": "MiniMax H3 Run Manager",
    "MiniMaxH3ChainScenePromptEditor": "MiniMax H3 Scene Prompt Editor",
    "MiniMaxH3ChainSegmentSave": (
        "MiniMax H3 Contex Loop Segment + Checkpoint"),
    "MiniMaxH3ContexLoopMaskSlice": (
        "MiniMax H3 Masking · Loop Mask Slice"),
    "MiniMaxH3ContexLoopSourceAVTarget": (
        "MiniMax H3 Masking · Loop Source AV Target"),
    "MiniMaxH3ContexMaskGridPreview": (
        "MiniMax H3 Masking · Grid Preview"),
    "MiniMaxH3ContexMaskedAVBridge": (
        "MiniMax H3 Masking · Two-Clip AV Bridge"),
    "MiniMaxH3ContexMaskedTarget": (
        "MiniMax H3 Masking · Apply Target Mask"),
    "MiniMaxH3ImageToVideo": "MiniMax H3 Image to Video",
    "MiniMaxH3LoopTrim": "MiniMax H3 Contex Loop Trim",
    "MiniMaxH3PatchPriority": "MiniMax H3 Patch Priority",
    "MiniMaxH3ReferenceToVideo": "MiniMax H3 Reference to Video",
    "MiniMaxH3ReferenceVideoPrepare": "MiniMax H3 Reference Video Prep",
    "MiniMaxH3SourceTimeline": "MiniMax H3 Source Timeline",
    "MiniMaxH3TaggedAudioReference": "MiniMax H3 Tagged Audio Ref",
    "MiniMaxH3TaggedPictureReference": "MiniMax H3 Tagged Picture Ref",
    "MiniMaxH3TaggedReferenceToVideo": "MiniMax H3 Tagged Ref2VA",
    "MiniMaxH3TaggedVideoReference": "MiniMax H3 Tagged Video Ref",
    "PreviewAny": "Preview as Text",
    "PreviewImage": "Preview Image",
    "UNETLoader": "Load Diffusion Model",
    "VAEDecode": "VAE Decode",
    "VAEDecodeAudio": "VAE Decode Audio",
    "VAELoader": "Load VAE",
    "VHS_LoadVideo": "Load Video (Upload) 🎥🅥🅗🅢",
}


def original_node_name(node_type: str) -> str:
    """Return the registered display name, or the canonical class type."""
    return NODE_DISPLAY_NAMES.get(node_type, node_type)


def _prefix_custom_titles(workflow: dict[str, Any]) -> None:
    """Keep demo guidance while making the real node name visible first."""
    for node in workflow.get("nodes", []):
        if "title" not in node:
            continue
        original = original_node_name(str(node.get("type", "Node")))
        custom = str(node.get("title", "")).strip()
        prefix = original + " — "
        if custom == original or custom.startswith(prefix):
            continue
        node["title"] = original if not custom else prefix + custom


def _node(workflow: dict[str, Any], node_type: str) -> dict[str, Any] | None:
    return next((item for item in workflow["nodes"]
                 if item.get("type") == node_type), None)


def _input(node: dict[str, Any], name: str) -> dict[str, Any]:
    return next(item for item in node.get("inputs", [])
                if item.get("name") == name)


def _output(node: dict[str, Any], name: str) -> dict[str, Any]:
    return next(item for item in node.get("outputs", [])
                if item.get("name") == name)


class Graph:
    def __init__(self, workflow: dict[str, Any]):
        self.workflow = workflow
        self.nodes = {item["id"]: item for item in workflow["nodes"]}
        self.links = {item[0]: item for item in workflow["links"]}
        self.next_node = max(self.nodes, default=0) + 1
        self.next_link = max(self.links, default=0) + 1
        self.order = max((int(item.get("order", 0))
                          for item in self.nodes.values()), default=0) + 1

    def add_node(self, node: dict[str, Any]) -> dict[str, Any]:
        node["id"] = self.next_node
        node["order"] = self.order
        self.next_node += 1
        self.order += 1
        self.workflow["nodes"].append(node)
        self.nodes[node["id"]] = node
        return node

    def add_input(self, node: dict[str, Any], name: str, kind: str,
                  *, shape: int | None = 7) -> dict[str, Any]:
        existing = next((item for item in node.get("inputs", [])
                         if item.get("name") == name), None)
        if existing is not None:
            return existing
        value: dict[str, Any] = {"name": name, "type": kind, "link": None}
        if shape is not None:
            value["shape"] = shape
        node.setdefault("inputs", []).append(value)
        return value

    def connect(self, origin: dict[str, Any], origin_slot: int,
                target: dict[str, Any], target_slot: int,
                kind: str) -> int:
        target_input = target["inputs"][target_slot]
        if target_input.get("link") is not None:
            self.remove_link(int(target_input["link"]))
        link_id = self.next_link
        self.next_link += 1
        link = [link_id, origin["id"], origin_slot,
                target["id"], target_slot, kind]
        self.workflow["links"].append(link)
        self.links[link_id] = link
        if origin["outputs"][origin_slot].get("links") is None:
            origin["outputs"][origin_slot]["links"] = []
        origin["outputs"][origin_slot]["links"].append(link_id)
        target_input["link"] = link_id
        return link_id

    def remove_link(self, link_id: int) -> None:
        link = self.links.pop(link_id, None)
        if link is None:
            return
        _link_id, origin_id, origin_slot, target_id, target_slot, _kind = link
        origin_links = self.nodes[origin_id]["outputs"][origin_slot].get(
            "links") or []
        self.nodes[origin_id]["outputs"][origin_slot]["links"] = [
            item for item in origin_links if item != link_id] or None
        self.nodes[target_id]["inputs"][target_slot]["link"] = None
        self.workflow["links"] = [
            item for item in self.workflow["links"] if item[0] != link_id]

    def remove_input(self, node: dict[str, Any], name: str) -> None:
        index = next((slot for slot, item in enumerate(node.get("inputs", []))
                      if item.get("name") == name), None)
        if index is None:
            return
        value = node["inputs"][index]
        if value.get("link") is not None:
            self.remove_link(int(value["link"]))
        del node["inputs"][index]
        for link in self.workflow["links"]:
            if int(link[3]) == int(node["id"]) and int(link[4]) > index:
                link[4] = int(link[4]) - 1

    def retarget(self, link_id: int, target: dict[str, Any],
                 target_slot: int) -> None:
        link = self.links[link_id]
        old_target = self.nodes[link[3]]
        old_target["inputs"][link[4]]["link"] = None
        link[3] = target["id"]
        link[4] = target_slot
        target["inputs"][target_slot]["link"] = link_id

    def reorigin(self, link_id: int, origin: dict[str, Any],
                 origin_slot: int) -> None:
        link = self.links[link_id]
        old_origin = self.nodes[link[1]]
        old_links = old_origin["outputs"][link[2]].get("links") or []
        old_origin["outputs"][link[2]]["links"] = [
            item for item in old_links if item != link_id] or None
        link[1] = origin["id"]
        link[2] = origin_slot
        if origin["outputs"][origin_slot].get("links") is None:
            origin["outputs"][origin_slot]["links"] = []
        origin["outputs"][origin_slot]["links"].append(link_id)

    def finish(self) -> None:
        self.workflow["last_node_id"] = max(self.nodes)
        self.workflow["last_link_id"] = max(self.links, default=0)


def _base_node(node_type: str, title: str, pos: list[float],
               size: list[float]) -> dict[str, Any]:
    return {
        "id": 0,
        "type": node_type,
        "pos": pos,
        "size": size,
        "flags": {},
        "order": 0,
        "mode": 0,
        "inputs": [],
        "outputs": [],
        "title": title,
        "properties": {"Node name for S&R": node_type},
        "widgets_values": [],
    }


_AUDIO_FROM_LEGACY = {
    "source_track": ("source", "on", "off"),
    "generated_audio": ("generated", "off", "on"),
    "source_plus_timeline": ("source", "on", "on"),
}
_LEGACY_FROM_AUDIO = {value: key for key, value in _AUDIO_FROM_LEGACY.items()}
_PRIMARY_TRANSITIONS = {
    "cut": ("guide", 0),
    "guide": ("guide", 22),
    "hard_av": ("masked_av", 39),
    "soft_av": ("audio_feathered_av", 39),
}


def _resolved_policy_values(plan: dict[str, Any]) -> tuple[
                                tuple[str, str, str], str, int, int]:
    audio = _AUDIO_FROM_LEGACY[str(plan["widgets_values"][9])]
    context = int(plan["widgets_values"][5])
    mode = (str(plan["widgets_values"][16])
            if len(plan["widgets_values"]) > 16 else "guide")
    audio_context = int(plan["widgets_values"][10])
    return audio, mode, context, audio_context


def _chain_policy_node(plan: dict[str, Any], audio: tuple[str, str, str],
                       mode: str, context: int,
                       audio_context: int) -> tuple[dict[str, Any], int]:
    primary = next((name for name, pair in _PRIMARY_TRANSITIONS.items()
                    if pair == (mode, context)), None)
    x, y = plan["pos"]
    if primary is not None and audio_context == context:
        result = _base_node(
            "MiniMaxH3ChainPolicy", "0.5 CHAIN POLICY",
            [x - 420, y + 160], [340, 190])
        result["outputs"] = [
            {"name": "chain_policy", "type": "H3_CHAIN_POLICY", "links": []},
            {"name": "status", "type": "STRING", "links": None},
        ]
        result["widgets_values"] = [primary, *audio]
        return result, 0

    legacy_mode = _LEGACY_FROM_AUDIO.get(audio)
    if legacy_mode is None:
        raise ValueError("Cannot preserve unsupported legacy audio policy %r." %
                         (audio,))
    result = _base_node(
        "MiniMaxH3Legacy04PolicyAdapter", "0.4 LEGACY POLICY ADAPTER",
        [x - 420, y + 160], [360, 220])
    result["outputs"] = [
        {"name": "chain_policy", "type": "H3_CHAIN_POLICY", "links": []},
        {"name": "status", "type": "STRING", "links": None},
    ]
    result["widgets_values"] = [
        legacy_mode, mode, int(context), int(audio_context)]
    return result, 0


def _preflight_node(start: dict[str, Any]) -> dict[str, Any]:
    x, y = start["pos"]
    result = _base_node(
        "MiniMaxH3ChainPreflight", "0.5 PREFLIGHT — BLOCKS BEFORE MODELS",
        [x - 448, y + 256], [384, 260])
    result["inputs"] = [
        {"name": "plan", "type": "H3_CHAIN_PLAN", "link": None},
        {"name": "source_timeline", "shape": 7,
         "type": "H3_SOURCE_TIMELINE", "link": None},
        {"name": "source_audio", "shape": 7,
         "type": "AUDIO", "link": None},
        {"name": "tagged_references", "shape": 7,
         "type": "H3_TAGGED_REFERENCES", "link": None},
        {"name": "reference_schedule", "shape": 7,
         "type": "H3_REFERENCE_SCHEDULE", "link": None},
    ]
    result["outputs"] = [
        {"name": "plan", "type": "H3_CHAIN_PLAN", "links": []},
        {"name": "preflight", "type": "H3_PREFLIGHT", "links": None},
        {"name": "ready", "type": "BOOLEAN", "links": None},
        {"name": "status", "type": "STRING", "links": None},
        {"name": "report_json", "type": "STRING", "links": None},
    ]
    result["widgets_values"] = [1, "", True]
    return result


def _source_timeline_node(audio_loader: dict[str, Any]) -> dict[str, Any]:
    x, y = audio_loader["pos"]
    result = _base_node(
        "MiniMaxH3SourceTimeline", "0.5 SOURCE TIMELINE — SELECT ONCE",
        [x + 416, y], [352, 230])
    result["inputs"] = [
        {"name": "source_video", "shape": 7, "type": "VIDEO", "link": None},
        {"name": "source_audio", "shape": 7, "type": "AUDIO", "link": None},
    ]
    result["outputs"] = [
        {"name": "source_timeline", "type": "H3_SOURCE_TIMELINE", "links": []},
        {"name": "status", "type": "STRING", "links": None},
    ]
    result["widgets_values"] = ["", "", "ignore", 0]
    return result


def _replace_text(value: Any, old: str, new: str) -> Any:
    if isinstance(value, str):
        return value.replace(old, new)
    if isinstance(value, list):
        return [_replace_text(item, old, new) for item in value]
    if isinstance(value, dict):
        return {key: _replace_text(item, old, new)
                for key, item in value.items()}
    return value


def _reference_registry(workflow: dict[str, Any], graph: Graph
                        ) -> tuple[dict[str, Any], int, str] | None:
    for wrapper_type, input_name, kind in (
        ("MiniMaxH3TaggedReferenceToVideo", "references",
         "H3_TAGGED_REFERENCES"),
        ("MiniMaxH3ScheduledReferenceToVideo", "reference_schedule",
         "H3_REFERENCE_SCHEDULE"),
    ):
        wrapper = _node(workflow, wrapper_type)
        if wrapper is None:
            continue
        value = _input(wrapper, input_name)
        if value.get("link") is None:
            continue
        link = graph.links[int(value["link"])]
        origin = graph.nodes[link[1]]
        # Legacy timeline demos fed Current Shot's dynamic slice into Tagged
        # Audio. Returning that registry to preflight or Plan would close an
        # execution cycle. A current source_timeline node instead receives the
        # static full Load Audio track and is safe to return.
        if origin.get("type") == "MiniMaxH3TaggedAudioReference":
            values = origin.get("widgets_values") or []
            if len(values) < 2 or values[1] != "source_timeline":
                return None
            audio_input = _input(origin, "audio")
            audio_link_id = audio_input.get("link")
            if audio_link_id is None:
                return None
            audio_link = graph.links.get(int(audio_link_id))
            if audio_link is None:
                return None
            audio_origin = graph.nodes[int(audio_link[1])]
            if audio_origin.get("type") == "MiniMaxH3ChainCurrent":
                return None
        return origin, int(link[2]), kind
    return None


def _add_chain_policy(workflow: dict[str, Any], graph: Graph) -> None:
    plan = _node(workflow, "MiniMaxH3ChainPlan")
    assert plan is not None
    compact_input = graph.add_input(
        plan, "chain_policy", "H3_CHAIN_POLICY")
    graph.remove_input(plan, "audio_policy")
    graph.remove_input(plan, "transition_policy")
    if compact_input.get("link") is not None:
        return

    audio, mode, context, audio_context = _resolved_policy_values(plan)
    policy, output_slot = _chain_policy_node(
        plan, audio, mode, context, audio_context)

    policy = graph.add_node(policy)
    graph.connect(policy, output_slot, plan,
                  plan["inputs"].index(compact_input), "H3_CHAIN_POLICY")


def _add_preflight(workflow: dict[str, Any], graph: Graph) -> None:
    start = _node(workflow, "MiniMaxH3ChainLoopStart")
    assert start is not None
    studio = _node(workflow, "MiniMaxH3ChainPlanStudio")
    registry = _reference_registry(workflow, graph)
    if studio is not None:
        for name, kind in (
            ("source_timeline", "H3_SOURCE_TIMELINE"),
            ("source_audio", "AUDIO"),
            ("tagged_references", "H3_TAGGED_REFERENCES"),
            ("reference_schedule", "H3_REFERENCE_SCHEDULE"),
        ):
            graph.add_input(studio, name, kind)
        if len(studio.get("widgets_values", [])) < 3:
            studio["widgets_values"] = [1, "", True]
        if registry is not None:
            origin, slot, kind = registry
            name = ("tagged_references" if kind == "H3_TAGGED_REFERENCES"
                    else "reference_schedule")
            target_input = _input(studio, name)
            if target_input.get("link") is None:
                graph.connect(origin, slot, studio,
                              studio["inputs"].index(target_input), kind)
        return

    if _node(workflow, "MiniMaxH3ChainPreflight") is not None:
        return
    preflight = graph.add_node(_preflight_node(start))
    plan_socket = _input(start, "plan")
    old_link = int(plan_socket["link"])
    graph.retarget(old_link, preflight, 0)
    graph.connect(preflight, 0, start, start["inputs"].index(plan_socket),
                  "H3_CHAIN_PLAN")
    if registry is not None:
        origin, slot, kind = registry
        target_name = ("tagged_references"
                       if kind == "H3_TAGGED_REFERENCES"
                       else "reference_schedule")
        graph.connect(origin, slot, preflight,
                      preflight["inputs"].index(_input(preflight, target_name)),
                      kind)


def _wire_scene_resolved_trim(
        workflow: dict[str, Any], graph: Graph) -> None:
    """Make Loop Trim resolve blend policy from the active scene state.

    Plan's integer output is only the inherited default. Current Shot's old
    integer output is scene-resolved, but maintaining two same-typed wires made
    it easy to connect the default and silently lose a scene override. The 0.5
    route carries state instead, so Loop Trim owns the one authoritative
    resolution step.
    """
    current = _node(workflow, "MiniMaxH3ChainCurrent")
    trim = _node(workflow, "MiniMaxH3LoopTrim")
    if current is None or trim is None:
        return
    state_input = graph.add_input(trim, "state", "H3_CHAIN_STATE")
    state_link_id = state_input.get("link")
    state_link = (graph.links.get(int(state_link_id))
                  if state_link_id is not None else None)
    already_resolved = bool(
        state_link is not None
        and int(state_link[1]) == int(current["id"])
        and int(state_link[2]) == 0)
    if not already_resolved:
        graph.connect(
            current, 0, trim, trim["inputs"].index(state_input),
            "H3_CHAIN_STATE")
    retain = next((item for item in trim.get("inputs", [])
                   if item.get("name") == "retain_overlap_frames"), None)
    if retain is not None and retain.get("link") is not None:
        graph.remove_link(int(retain["link"]))
    trim["title"] = "TRIM CONTEXT / AUTO-RESOLVE SCENE BLEND"


def _migrate_source_audio_demo(workflow: dict[str, Any], graph: Graph) -> None:
    revised = _replace_text(
        workflow,
        "@audio_1 is the full source-track audio reference; preserve its exact "
        "scene-local timing and performance identity.",
        "@audio_1 is the exact current-scene source-track slice; preserve its "
        "timing and performance identity.",
    )
    workflow.clear()
    workflow.update(revised)
    graph.workflow = workflow
    graph.nodes = {item["id"]: item for item in workflow["nodes"]}
    graph.links = {item[0]: item for item in workflow["links"]}
    loader = _node(workflow, "LoadAudio")
    audio_ref = _node(workflow, "MiniMaxH3TaggedAudioReference")
    conditioner = _node(workflow, "MiniMaxH3TaggedReferenceToVideo")
    current = _node(workflow, "MiniMaxH3ChainCurrent")
    start = _node(workflow, "MiniMaxH3ChainLoopStart")
    studio = _node(workflow, "MiniMaxH3ChainPlanStudio")
    manifest = _node(workflow, "MiniMaxH3ChainManifestLoad")
    plan = _node(workflow, "MiniMaxH3ChainPlan")
    assert all(item is not None for item in (
        loader, audio_ref, conditioner, current, start, studio, manifest,
        plan))

    timeline = _node(workflow, "MiniMaxH3SourceTimeline")
    if timeline is None:
        timeline = graph.add_node(_source_timeline_node(loader))
    timeline_audio = _input(timeline, "source_audio")
    timeline_audio_link = timeline_audio.get("link")
    if timeline_audio_link is None:
        graph.connect(loader, 0, timeline,
                      timeline["inputs"].index(timeline_audio), "AUDIO")
    else:
        link = graph.links[int(timeline_audio_link)]
        if int(link[1]) != int(loader["id"]) or int(link[2]) != 0:
            graph.reorigin(int(timeline_audio_link), loader, 0)

    # Replace the legacy full-track fan-out. The typed descriptor is carried
    # in recursive state and saved metadata; Current Shot exposes only the
    # scene-local reference window.
    for consumer in (start, current, manifest, *[
            item for item in workflow["nodes"]
            if item.get("type") == "MiniMaxH3ChainAssemble"]):
        legacy = next((item for item in consumer.get("inputs", [])
                       if item.get("name") == "source_audio"), None)
        if legacy is not None and legacy.get("link") is not None:
            graph.remove_link(int(legacy["link"]))

    for consumer in (start, studio, manifest):
        timeline_input = graph.add_input(
            consumer, "source_timeline", "H3_SOURCE_TIMELINE")
        timeline_link_id = timeline_input.get("link")
        timeline_link = (graph.links.get(int(timeline_link_id))
                         if timeline_link_id is not None else None)
        if not (timeline_link is not None
                and int(timeline_link[1]) == int(timeline["id"])
                and int(timeline_link[2]) == 0):
            graph.connect(
                timeline, 0, consumer,
                consumer["inputs"].index(timeline_input),
                "H3_SOURCE_TIMELINE")

    # source_timeline mode deliberately receives the same static full track as
    # Loop Start. Tagged Audio derives the current scene window internally,
    # keeping the registry safe to fingerprint and pass to preflight.
    audio_input = _input(audio_ref, "audio")
    audio_link_id = audio_input.get("link")
    if audio_link_id is None:
        graph.connect(loader, 0, audio_ref,
                      audio_ref["inputs"].index(audio_input), "AUDIO")
    else:
        audio_link = graph.links[int(audio_link_id)]
        if (int(audio_link[1]) != int(loader["id"])
                or int(audio_link[2]) != 0):
            graph.reorigin(int(audio_link_id), loader, 0)
    loader_audio_links = loader["outputs"][0].get("links") or []
    loader["outputs"][0]["links"] = sorted(loader_audio_links) or None
    audio_ref["widgets_values"] = ["audio_1", "source_timeline", True]
    audio_ref["title"] = "3 — @audio_1 / FULL TRACK → CURRENT SCENE"
    current["widgets_values"] = [True]

    # The full registry is now static and can fingerprint both pictures and
    # source audio without routing Current Shot back into Plan.
    fingerprint_link = _input(plan, "generation_fingerprint").get("link")
    if fingerprint_link is None:
        graph.connect(
            audio_ref, 1, plan,
            plan["inputs"].index(_input(plan, "generation_fingerprint")),
            "STRING")
    else:
        fingerprint = graph.links[int(fingerprint_link)]
        if (int(fingerprint[1]) != int(audio_ref["id"])
                or int(fingerprint[2]) != 1):
            graph.reorigin(int(fingerprint_link), audio_ref, 1)

    outputs = conditioner.setdefault("outputs", [])
    if not any(item.get("name") == "refmod_sources" for item in outputs):
        outputs.append({
            "name": "refmod_sources", "type": "H3_REF_LIST", "links": None})
    conditioner_values = conditioner.setdefault("widgets_values", [])
    if len(conditioner_values) == 9:
        conditioner_values.append("native_ref2va")


def migrate(workflow: dict[str, Any], name: str) -> dict[str, Any]:
    if _node(workflow, "MiniMaxH3ChainPlan") is not None:
        graph = Graph(workflow)
        _add_chain_policy(workflow, graph)
        if name == SOURCE_AUDIO_DEMO:
            _migrate_source_audio_demo(workflow, graph)
        _add_preflight(workflow, graph)
        _wire_scene_resolved_trim(workflow, graph)
        graph.finish()
    _prefix_custom_titles(workflow)
    return workflow


def active_paths() -> list[Path]:
    return [EXAMPLES / name for name in MAINTAINED_DEMOS]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", type=Path,
                        help="Workflow JSON paths (defaults to maintained examples)")
    parser.add_argument("--check", action="store_true",
                        help="Report workflows that still need migration")
    args = parser.parse_args()
    paths = args.paths or active_paths()
    changed = []
    for path in paths:
        source = path.read_text(encoding="utf-8")
        workflow = migrate(json.loads(source), path.name)
        rendered = json.dumps(workflow, ensure_ascii=False, indent=2) + "\n"
        if rendered != source:
            changed.append(path)
            if not args.check:
                path.write_text(rendered, encoding="utf-8")
    if args.check and changed:
        for path in changed:
            print(path)
        return 1
    print(("would migrate" if args.check else "migrated"),
          len(changed), "workflow(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
