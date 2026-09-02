#!/usr/bin/env python3
"""Build the clean 0.6 example-workflow catalog from legacy topology seeds.

The archived workflows are used only as wiring blueprints.  Every output
document receives fresh IDs, compact metadata, current authoring nodes, new
prompts, and a collision-free layout.  This deliberately avoids accumulating
frontend and node-pack metadata from older releases.
"""

from __future__ import annotations

import argparse
import copy
import json
import re
import uuid
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "example_workflows"
LEGACY_05 = EXAMPLES / "Archive" / "0.5"
WORKFLOW_NAMES = (
    "Deferred Upscale + De-Rope - H3 LBH 3D - MiniMax H3.json",
    "Deferred Upscale - H3 LBH 3D - MiniMax H3.json",
    "Deferred Upscale - SeedVR2 Full Chain - MiniMax H3.json",
    "FL2V Normal - MiniMax H3.json",
    "I2V Normal - MiniMax H3.json",
    "I2V Studio - MiniMax H3.json",
    "Masked AV Bridge - Two Clips - MiniMax H3.json",
    "Masked AV Extension - Chain + Reference Image - MiniMax H3.json",
    "Masked AV Extension - Single Clip - MiniMax H3.json",
    "Masked Video Inpaint - MiniMax H3.json",
    "Ref2V Basic - MiniMax H3.json",
    "Ref2V Masked Video Inpaint - MiniMax H3.json",
    "Ref2V Sequential Motion - EXPERIMENTAL - MiniMax H3.json",
    "Ref2V Studio Tagged - MiniMax H3.json",
    "Ref2V Studio Tagged Source Audio - MiniMax H3.json",
    "Ref2V Tagged - MiniMax H3.json",
    "T2V Normal - MiniMax H3.json",
    "T2V Studio - MiniMax H3.json",
)
OUTPUT_RENAMES = {
    name: name.removesuffix(".json") + " 0.6.json"
    for name in WORKFLOW_NAMES
}
OUTPUT_RENAMES.update({
    "Ref2V Studio Tagged - MiniMax H3.json":
        "Ref2V Studio - MiniMax H3 0.6.json",
    "Ref2V Studio Tagged Source Audio - MiniMax H3.json":
        "Ref2V Studio Source Audio - MiniMax H3 0.6.json",
})
NAMESPACE = uuid.UUID("aedf0e28-4e77-4ec8-98d8-7662561e4cf4")

ARRIVAL = "h3_v06_courier_greenhouse_arrival.png"
DELIVERY = "h3_v06_courier_greenhouse_delivery.png"
CANONICAL_H3_MODELS = {
    "minimax_h3_fl2va_pruned_int8_convrot.safetensors",
    "minimax_h3_ref2va_pruned_int8_convrot.safetensors",
    "qwen3vl_32b_minimax_h3_int8_convrot.safetensors",
    "minimax_h3_video_vae_fp16.safetensors",
    "minimax_h3_audio_vae_fp32.safetensors",
}


T2V_PROMPTS = (
    """integrated_multimodal_description:
[Shot 1] A grounded cinematic wide shot at a rain-darkened neighborhood tram stop just before dawn. One elderly watchmaker in a navy wool coat waits beneath the shelter, holding a small paper parcel with both hands. Sodium streetlights glow in wet pavement while an empty tram approaches from deep background. The camera makes a slow, steady push toward him. He hears the rails sing, looks up, and takes one deliberate step toward the curb. Keep exactly one person, natural body mechanics, restrained contrast, fine rain, and realistic lens breathing. End with the tram entering frame and his step still in progress.

overall_soundscape:
Fine rain on glass, distant tires on wet road, a low electrical rail hum, the approaching tram bell, coat fabric, and one measured footstep. Preserve a quiet predawn acoustic space.

non_diegetic_music:
No non-diegetic music.""",
    """integrated_multimodal_description:
[Shot 1] Continue the same unbroken predawn tram-stop moment from the incoming H3 Motion Context. The carried opening overlap already contains the watchmaker's step and the tram entering frame; begin new action only after that overlap. Preserve his identity, navy coat, parcel, lighting direction, rain density, camera height, lens, and left-to-right tram motion. He completes the step, the doors align beside him and open, and warm interior light reaches across the wet pavement. He gives the parcel a protective glance and boards in one calm motion while the camera settles outside. No cut, no extra pedestrian, no reset of the carried movement.

overall_soundscape:
Continue the same rain and rail hum through the boundary. Add braking metal, a soft pneumatic door release, one final pavement step, two hollow tram-floor steps, and subdued interior ventilation without restarting the ambience.

non_diegetic_music:
No non-diegetic music.""",
)

I2V_PROMPTS = (
    f"""integrated_multimodal_description:
[Shot 1] At 0.00 seconds, <Picture 1> is fully referenced as the opening frame. Animate the exact adult bicycle courier, mustard-yellow waterproof jacket, dark teal trousers, charcoal helmet, olive messenger bag, silver bicycle, kraft parcel, glass greenhouse entrance, wet paving, overcast daylight, and photographic rendering shown in <Picture 1>. In one stable landscape shot, he walks the bicycle through the open doorway, checks the parcel, then turns his shoulders toward the workbench inside. Keep exactly one courier and one bicycle; preserve face, wardrobe, proportions, bicycle geometry, parcel size, lighting direction, and camera height. End while he is crossing the threshold so the motion can continue.

overall_soundscape:
Light rain beyond the glass, wet tire noise, a quiet freewheel tick, rubber soles, the metal door hinge, jacket rustle, and soft greenhouse room tone.

non_diegetic_music:
No non-diegetic music.""",
    """integrated_multimodal_description:
[Shot 1] Continue directly from the incoming H3 Motion Context inside the same greenhouse. The carried opening overlap already contains the courier crossing the threshold; begin new action only after it. Preserve the same face, mustard jacket, teal trousers, helmet, olive bag, bicycle, parcel, glass architecture, plant layout, wet floor reflections, camera height, and direction of travel. He rolls the bicycle beside the wooden potting table, stops it with his left hand, and places the parcel on the dry corner of the table with his right hand. He briefly smiles at the completed delivery. No cut, no duplicate person or bicycle, and no motion reset.

overall_soundscape:
Continue the rain-muted greenhouse ambience, freewheel tick, tire roll, footsteps, clothing movement, and a soft cardboard contact on wood without an acoustic restart.

non_diegetic_music:
No non-diegetic music.""",
)

FL2V_PROMPTS = (
    """integrated_multimodal_description:
[Shot 1] <Picture 1> aligns with 0.00 seconds and <Picture 2> aligns with the final target frame. Begin from the exact adult courier, mustard waterproof jacket, teal trousers, charcoal helmet, olive messenger bag, silver bicycle, parcel, glass entrance, wet paving, lighting, lens, and landscape composition in <Picture 1>. In one continuous shot he walks the bicycle through the doorway, turns toward the potting table, and places the parcel down. Progressively match the courier's final pose, bicycle position, parcel placement, warm greenhouse bulbs, plant geometry, reflections, and framing in <Picture 2>. Reach <Picture 2> only on the final frame; do not freeze early, cut, or introduce another person.

overall_soundscape:
Rain on glass, tire roll, freewheel ticks, footsteps, door hinge, jacket rustle, and the parcel touching wood follow the visible action continuously.

non_diegetic_music:
No non-diegetic music.""",
    """integrated_multimodal_description:
[Shot 1] Continue from the incoming greenhouse delivery context. The carried overlap already contains the completed parcel placement; begin new action only after it. The courier checks his bicycle, turns it smoothly toward the open door, and walks back onto the wet paving. Preserve his exact identity and wardrobe, the bicycle, greenhouse layout, parcel remaining on the table, camera height, and screen direction. During the final seconds, progressively align the doorway, exterior reflections, courier stance, bicycle position, and composition with <Picture 1>, reaching that picture only on the final frame without a cut or early hold.

overall_soundscape:
Continue greenhouse room tone and rain, then add the bicycle freewheel, footsteps, door hinge, and brighter exterior rain as he exits.

non_diegetic_music:
No non-diegetic music.""",
)


def ref_prompt(tagged: bool, continuation: bool = False,
               motion: bool = False) -> str:
    first = "@courier_arrival" if tagged else "<Picture 1>"
    second = "@greenhouse_delivery" if tagged else "<Picture 2>"
    motion_line = (
        "\n@courier_motion is a motion-only guide for the walk, turn, and "
        "parcel placement; it must not replace the courier's appearance. "
        "@courier_motion_audio is its synchronized embedded sound guide."
        if motion and tagged else "")
    if not continuation:
        return f"""subject_definitions:
{first} defines <Subject 1>, the exact adult bicycle courier, including his face, mustard-yellow waterproof jacket, dark teal trousers, charcoal helmet, olive messenger bag, silver bicycle, kraft parcel, proportions, and photographic rendering.
{second} defines the greenhouse delivery destination, including the glass structure, wooden potting table, dense plants, warm practical bulbs, wet floor reflections, and the same courier's end pose.{motion_line}
<Subject 1> is the single courier shown by both references. Preserve his identity, clothing, equipment, and scale while allowing the described movement.

summary:
[reference generation] One continuous delivery moves <Subject 1> from the wet greenhouse entrance in {first} toward the completed parcel placement in {second}.

retention_analysis:
<Subject 1> (appears in [Shot 1]): fully_preserved - retain the exact face, adult age, body proportions, mustard jacket, teal trousers, helmet, bag, bicycle, and parcel across the complete shot.
{first}: fully_preserved - use its courier identity, wardrobe, bicycle geometry, exterior doorway, wet paving, camera height, and cool daylight as the opening state.
{second}: reference - use its potting table, plants, warm bulbs, interior reflections, and delivery pose as the destination; do not copy the final pose before the action reaches it.

detailed_description:
[Shot 1] Begin at the greenhouse entrance with exactly one courier and one bicycle. He walks the bicycle through the open glass door, glances down to confirm the parcel, then turns toward the wooden potting table. The camera tracks laterally at walking speed with restrained handheld movement. He stops the bicycle with his left hand and sets the parcel on the clear corner of the table with his right hand. Preserve face, hands, clothing, bicycle structure, parcel dimensions, plant layout, lighting direction, and coherent reflections. End immediately after the parcel makes contact; no cut, duplicate subject, added customer, text, logo, or early freeze.

overall_soundscape:
Light rain on greenhouse glass, wet tire roll, a quiet freewheel tick, rubber soles, door hinge, jacket movement, muted ventilation, and soft cardboard contact on wood. Keep every sound synchronized and spatially plausible.

non_diegetic_music:
No non-diegetic music."""
    continuation_motion = (
        "\n@courier_motion remains the motion-only walk and parcel-placement "
        "guide. @courier_motion_audio remains its synchronized embedded "
        "sound guide."
        if motion and tagged else "")
    return f"""subject_definitions:
{first} preserves the exact identity, clothing, bicycle, parcel, exterior weather, and entrance geography established before the boundary.
{second} defines the same greenhouse interior, potting table, plants, warm bulbs, and final delivery area.
<Subject 1> is the same single adult courier carried by the incoming H3 Motion Context and both references.{continuation_motion}

summary:
[reference generation] The uninterrupted delivery continues inside the greenhouse after the carried overlap and ends with the courier calmly confirming the parcel placement.

retention_analysis:
<Subject 1> (appears in [Shot 1]): fully_preserved - preserve the exact face, mustard jacket, teal trousers, helmet, bag, body proportions, bicycle, and motion phase inherited from context.
{first}: reference - retain its cool exterior light and entrance geometry only where still visible behind the courier.
{second}: fully_preserved - retain the greenhouse table, plant arrangement, warm practical lights, reflections, parcel position, and photographic rendering.

detailed_description:
[Shot 1] Continue directly from the incoming H3 Motion Context. The carried opening overlap already contains the threshold crossing; begin new action only after it and never reset the stride. The courier rolls the same bicycle beside the potting table, steadies it with his left hand, and places the kraft parcel on the dry corner with his right hand. He checks the label area without showing readable text, then gives a small satisfied smile. Keep exactly one person and one bicycle, stable hands, coherent wheels, continuous camera direction, and consistent light. No cut, duplicate, wardrobe change, or early freeze.

overall_soundscape:
Continue rain-muted greenhouse ambience, footsteps, tire roll, freewheel ticks, clothing movement, ventilation, and the soft parcel contact without restarting any sound at the scene boundary.

non_diegetic_music:
No non-diegetic music."""


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _input(node: dict[str, Any], name: str) -> dict[str, Any] | None:
    return next((value for value in node.get("inputs", [])
                 if value.get("name") == name), None)


def _output(node: dict[str, Any], name: str) -> dict[str, Any] | None:
    return next((value for value in node.get("outputs", [])
                 if value.get("name") == name), None)


class Graph:
    def __init__(self, workflow: dict[str, Any]):
        self.workflow = workflow
        self.nodes = {node["id"]: node for node in workflow["nodes"]}
        self.links = {link[0]: link for link in workflow["links"]}
        self.next_node = max(self.nodes, default=0) + 1
        self.next_link = max(self.links, default=0) + 1

    def remove_link(self, link_id: int) -> None:
        link = self.links.pop(link_id, None)
        if link is None:
            return
        _, origin_id, origin_slot, target_id, target_slot, _ = link
        origin = self.nodes.get(origin_id)
        target = self.nodes.get(target_id)
        if origin is not None:
            links = origin["outputs"][origin_slot].get("links") or []
            origin["outputs"][origin_slot]["links"] = (
                [value for value in links if value != link_id] or None)
        if target is not None and target_slot < len(target.get("inputs", [])):
            target["inputs"][target_slot]["link"] = None
        self.workflow["links"] = [value for value in self.workflow["links"]
                                  if value[0] != link_id]

    def remove_node(self, node: dict[str, Any]) -> None:
        for value in list(node.get("inputs", [])):
            if value.get("link") is not None:
                self.remove_link(int(value["link"]))
        for value in list(node.get("outputs", [])):
            for link_id in list(value.get("links") or []):
                self.remove_link(int(link_id))
        self.workflow["nodes"] = [value for value in self.workflow["nodes"]
                                  if value is not node]
        self.nodes.pop(node["id"], None)

    def add_node(self, node: dict[str, Any]) -> dict[str, Any]:
        node["id"] = self.next_node
        self.next_node += 1
        self.workflow["nodes"].append(node)
        self.nodes[node["id"]] = node
        return node

    def connect(self, origin: dict[str, Any], output_name: str,
                target: dict[str, Any], input_name: str, kind: str) -> int:
        origin_slot = next(index for index, value in
                           enumerate(origin["outputs"])
                           if value["name"] == output_name)
        target_slot = next(index for index, value in
                           enumerate(target["inputs"])
                           if value["name"] == input_name)
        target_input = target["inputs"][target_slot]
        if target_input.get("link") is not None:
            self.remove_link(int(target_input["link"]))
        link_id = self.next_link
        self.next_link += 1
        link = [link_id, origin["id"], origin_slot,
                target["id"], target_slot, kind]
        self.workflow["links"].append(link)
        self.links[link_id] = link
        links = origin["outputs"][origin_slot].get("links") or []
        origin["outputs"][origin_slot]["links"] = [*links, link_id]
        target_input["link"] = link_id
        return link_id


def _node(node_type: str, title: str, pos: list[float], size: list[float],
          inputs: list[dict[str, Any]], outputs: list[dict[str, Any]],
          widgets: list[Any]) -> dict[str, Any]:
    return {
        "id": 0, "type": node_type, "pos": pos, "size": size,
        "flags": {}, "order": 0, "mode": 0,
        "inputs": inputs, "outputs": outputs, "title": title,
        "properties": {"Node name for S&R": node_type},
        "widgets_values": widgets,
    }


def _socket(name: str, kind: str, *, shape: int | None = None,
            link: int | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {"name": name, "type": kind, "link": link}
    if shape is not None:
        result["shape"] = shape
    return result


def _out(name: str, kind: str) -> dict[str, Any]:
    return {"name": name, "type": kind, "links": None}


def _profile_values(old: list[Any]) -> list[str]:
    transition = str(old[0]) if old else "guide"
    scene = {
        "cut": "Independent scenes",
        "hard_av": "Hard picture + protected audio",
        "soft_av": "Hard picture + smooth audio",
    }.get(transition, "Visual continuity")
    final = str(old[1]) if len(old) > 1 else "generated"
    source = str(old[2]) if len(old) > 2 else "off"
    continuity = str(old[3]) if len(old) > 3 else "on"
    if final == "none":
        audio = "No final audio"
    elif final == "source":
        audio = "Lip-sync to source audio"
    elif source == "on":
        audio = "Generate audio from source guide"
    elif continuity == "off":
        audio = "Generate fresh audio per scene"
    else:
        audio = "Generate audio"
    return [scene, audio]


def _fresh_plan(name: str, old_plan: dict[str, Any]) -> dict[str, Any]:
    old_shots = list(old_plan.get("shots") or [])
    count = max(1, len(old_shots))
    if name.startswith("T2V"):
        prompts = T2V_PROMPTS
        ids = ("tram_stop_arrival", "tram_boarding")
    elif name.startswith("I2V"):
        prompts = I2V_PROMPTS
        ids = ("greenhouse_arrival", "greenhouse_delivery")
    elif name.startswith("FL2V"):
        prompts = FL2V_PROMPTS
        ids = ("arrival_to_delivery", "delivery_to_arrival")
    elif name.startswith("Ref2V") and "Masked" not in name:
        tagged = ("Tagged" in name or "Studio" in name
                  or "Sequential Motion" in name)
        motion = "Sequential Motion" in name
        prompts = (ref_prompt(tagged, False, motion),
                   ref_prompt(tagged, True, motion))
        ids = ("reference_delivery", "reference_confirmation")
    else:
        return old_plan
    shots = []
    for index in range(count):
        old = old_shots[index] if index < len(old_shots) else {}
        prompt = prompts[min(index, len(prompts) - 1)]
        length = int(old.get("length") or 243)
        shots.append({
            "id": ids[min(index, len(ids) - 1)],
            "prompt": prompt,
            "length": length,
            "steps": 20,
            "seed": str(6101 + index),
        })
    return {"defaults": {"steps": 20}, "shots": shots}


def _replace_loader_assets(workflow: dict[str, Any], name: str) -> None:
    if not (name.startswith(("I2V", "FL2V", "Ref2V"))
            and "Masked" not in name):
        return
    loaders = [node for node in workflow["nodes"]
               if node.get("type") == "LoadImage"]
    for index, loader in enumerate(loaders[:2]):
        values = loader.get("widgets_values")
        old_filename = ""
        if isinstance(values, list) and values:
            old_filename = str(values[0])
        elif isinstance(values, dict):
            old_filename = str(values.get("image") or "")
        if "opening" in old_filename:
            filename = ARRIVAL
        elif "last" in old_filename:
            filename = DELIVERY
        else:
            filename = ARRIVAL if index == 0 else DELIVERY
        if isinstance(values, list) and values:
            values[0] = filename
        elif isinstance(values, dict):
            values["image"] = filename
        loader["title"] = "Load Image — 0.6 %s" % (
            "COURIER ARRIVAL" if index == 0 else "GREENHOUSE DELIVERY")


def _normalize_model_widgets(workflow: dict[str, Any]) -> None:
    """Remove legacy, machine-specific model subfolder prefixes.

    ComfyUI's canonical H3 package places these files directly in their
    respective diffusion_models, text_encoders, and vae directories.  Older
    examples carried both a local ``MiniMax-H3/`` convention and the misspelled
    ``MiniMaw-H3/`` VAE folder; neither belongs in a portable release file.
    """
    for node in workflow["nodes"]:
        if node.get("type") not in {"UNETLoader", "CLIPLoader", "VAELoader"}:
            continue
        values = node.get("widgets_values")
        if not isinstance(values, list) or not values:
            continue
        basename = str(values[0]).replace("\\", "/").rsplit("/", 1)[-1]
        if basename in CANONICAL_H3_MODELS:
            values[0] = basename


def _refresh_release_guidance(workflow: dict[str, Any], name: str) -> None:
    if not (name.startswith(("T2V", "I2V", "FL2V", "Ref2V"))
            and "Masked" not in name):
        return
    tagged_pictures = [node for node in workflow["nodes"]
                       if node.get("type") ==
                       "MiniMaxH3TaggedPictureReference"]
    for index, node in enumerate(tagged_pictures[:2]):
        tag = "courier_arrival" if index == 0 else "greenhouse_delivery"
        node["widgets_values"] = [tag]
        node["title"] = "MiniMax H3 Tagged Picture Ref — @%s" % tag
    for node in workflow["nodes"]:
        if node.get("type") == "MiniMaxH3TaggedVideoReference":
            values = list(node.get("widgets_values") or [])
            timeline = values[2] if len(values) > 2 else "sequential"
            node["widgets_values"] = [
                "courier_motion", "courier_motion_audio", timeline]
            node["title"] = (
                "MiniMax H3 Tagged Video Ref — @courier_motion / SEQUENTIAL")
        title = str(node.get("title") or "")
        node["title"] = title.replace("0.5 PREFLIGHT", "0.6 PREFLIGHT")

    if name.startswith("T2V"):
        guidance = [
            "0.6 ORIGINAL PROMPT\n\nThis quiet predawn tram-stop example was "
            "written for the 0.6 release catalog. It uses concrete physical "
            "action, one counted subject, restrained camera movement, and no "
            "third-party character or brand.",
            "T2VA PROMPT FORMAT\n\nEach scene uses the exact three-section H3 "
            "shape: integrated_multimodal_description, overall_soundscape, "
            "and non_diegetic_music. Scene 2 explicitly treats the carried "
            "overlap as already elapsed before new action begins.",
            "T2V 0.6 QUICK START\n\nSelect installed H3 model, text encoder, "
            "video VAE, and audio VAE files. Edit the two scene columns, keep "
            "Generation Profile on Visual continuity + Generate audio, then "
            "queue and approve each checkpointed scene.",
        ]
    elif name.startswith("I2V"):
        guidance = [
            f"0.6 REFERENCE ASSET\n\n{ARRIVAL} was generated specifically for "
            "this release catalog. Copy it from example_workflows/assets to "
            "ComfyUI/input before loading the workflow.",
            "I2VA PROMPT FORMAT\n\nScene 1 declares <Picture 1> as the opening "
            "frame inside the three-section H3 prompt. Scene 2 relies on the "
            "incoming H3 Motion Context and begins new action only after the "
            "carried overlap.",
            "I2V 0.6 QUICK START\n\nSelect the courier arrival image and keep "
            "Frame Gate connected: it applies Picture 1 only to scene 1. "
            "Select installed H3 model/VAE files, edit the Plan, then queue.",
        ]
    elif name.startswith("FL2V"):
        guidance = [
            f"0.6 A→B REFERENCES\n\nCopy {ARRIVAL} and {DELIVERY} from "
            "example_workflows/assets to ComfyUI/input. They were created as "
            "a coherent opening/destination pair for this release catalog.",
            "FL2VA PROMPT FORMAT\n\nEach three-section prompt identifies the "
            "opening and final target inside integrated_multimodal_description. "
            "The action converges on the target only at the final frame.",
            "FL2V 0.6 QUICK START\n\nKeep delivery on Frame Index Switch "
            "frame_1 and arrival on frame_2. Frame Gate supplies arrival as "
            "scene 1's opening and alternates B→A end targets for the loop.",
        ]
    else:
        studio = "Studio" in name
        sequential = "Sequential Motion" in name
        guidance = [
            "0.6 ORIGINAL REFERENCE EXAMPLE\n\nThe matching courier and "
            "greenhouse pictures were generated specifically for this catalog. "
            "They replace the old community demonstration assets and prompts.",
            "REF2VA PROMPT FORMAT — SIX SECTIONS\n\nKeep subject_definitions, "
            "summary, retention_analysis, detailed_description, "
            "overall_soundscape, and non_diegetic_music in that order. "
            "References define identity; the prompt defines the new action.",
            (
                "REF2V STUDIO 0.6 QUICK START\n\nImport both courier images "
                "through Project Asset Carousel. Assign Picture and tags "
                "courier_arrival / greenhouse_delivery. Use Plan Studio for "
                "timeline edits and Checkpoint Manager for takes, trims, and "
                "branch restoration."
                if studio else
                "REF2V 0.6 QUICK START\n\nCopy both courier PNGs to "
                "ComfyUI/input. The two picture references are activated as "
                "courier_arrival and greenhouse_delivery. Edit the Plan, "
                "then queue and approve each checkpointed scene."
            ),
        ]
        if sequential:
            guidance[2] = (
                "SEQUENTIAL MOTION 0.6 QUICK START\n\nCopy both courier PNGs "
                "to ComfyUI/input and select a motion video with embedded "
                "audio lasting at least 19.333 seconds. Keep tags "
                "@courier_arrival, @greenhouse_delivery, @courier_motion, "
                "and @courier_motion_audio in the prompts. The motion window "
                "advances with each scene.")
    note_nodes = [node for node in workflow["nodes"]
                  if node.get("type") == "Note"
                  and "recovery nodes are MUTED" not in str(
                      (node.get("widgets_values") or [""])[0])]
    for node, text in zip(note_nodes[:3], guidance):
        node["widgets_values"] = [text]
        node["title"] = text.split("\n", 1)[0]


def _modernize_plan(workflow: dict[str, Any], name: str) -> None:
    graph = Graph(workflow)
    plans = [node for node in workflow["nodes"]
             if node.get("type") == "MiniMaxH3ChainPlan"]
    for plan in plans:
        values = list(plan.get("widgets_values") or [])
        raw = json.loads(str(values[0]))
        fresh = _fresh_plan(name, raw)
        policy_input = _input(plan, "chain_policy")
        policy = None
        if policy_input and policy_input.get("link") is not None:
            link = graph.links[int(policy_input["link"])]
            policy = graph.nodes[link[1]]
        if policy is None:
            raise ValueError(f"{name}: Plan has no Chain Policy")
        policy["type"] = "MiniMaxH3GenerationProfile"
        policy["title"] = "MiniMax H3 Generation Profile — RELEASE DEFAULTS"
        policy["size"] = [400, 190]
        policy["inputs"] = []
        policy["outputs"] = [
            _out("chain_policy", "H3_CHAIN_POLICY"), _out("status", "STRING")]
        # Preserve the existing link after recreating the output socket.
        policy["outputs"][0]["links"] = [int(policy_input["link"])]
        policy["widgets_values"] = _profile_values(
            list(policy.get("widgets_values") or []))
        policy["properties"] = {
            "Node name for S&R": "MiniMaxH3GenerationProfile"}

        optional_links = {}
        for value in plan.get("inputs", []):
            if value.get("name") == "plan_json_input" and value.get("link"):
                optional_links["plan_json_input"] = value["link"]
            if (value.get("name") == "generation_fingerprint"
                    and value.get("link")):
                optional_links["generation_fingerprint"] = value["link"]
        plan["type"] = "MiniMaxH3ChainPlanModern"
        plan["title"] = "MiniMax H3 Production Plan — 0.6 SCENE COLUMNS"
        plan["size"] = [1040, 1040]
        plan["inputs"] = [_socket(
            "chain_policy", "H3_CHAIN_POLICY", shape=7,
            link=int(policy_input["link"]))]
        # Keep a connected fingerprint carrier in non-Carousel workflows.
        if optional_links.get("generation_fingerprint"):
            plan["inputs"].append({
                "name": "generation_fingerprint", "type": "STRING",
                "widget": {"name": "generation_fingerprint"},
                "link": int(optional_links["generation_fingerprint"]),
            })
        if optional_links.get("plan_json_input"):
            plan["inputs"].append(_socket(
                "plan_json_input", "STRING", shape=7,
                link=int(optional_links["plan_json_input"])))
        # Input slots are positional in UI workflow links.  Repoint every
        # preserved link after replacing the legacy Plan's input surface.
        for slot, value in enumerate(plan["inputs"]):
            if value.get("link") is not None:
                graph.links[int(value["link"])][4] = slot
        run_name = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
        run_name = re.sub(r"_minimax_h3_json$", "", run_name)
        width = int(values[3]) if len(values) > 3 else 960
        height = int(values[4]) if len(values) > 4 else 544
        encode = str(values[6]) if len(values) > 6 else "video"
        crop = str(values[8]) if len(values) > 8 else "disabled"
        duration = float(values[11]) if len(values) > 11 else 10.0
        base_seed = int(values[13]) if len(values) > 13 else 0
        crf = int(values[14]) if len(values) > 14 else 18
        blend = int(values[15]) if len(values) > 15 else 0
        fingerprint = "" if "Studio" in name else "h3-v06-release-example"
        plan["widgets_values"] = [
            json.dumps(fresh, ensure_ascii=False, indent=2), run_name,
            fingerprint, width, height, encode, crop, duration, 20,
            base_seed, crf, blend,
        ]
        plan["properties"] = {
            "Node name for S&R": "MiniMaxH3ChainPlanModern"}

        first_prompt = str(fresh["shots"][0]["prompt"])
        for conditioning in workflow["nodes"]:
            if conditioning.get("type") in {
                    "MiniMaxH3ImageToVideo", "MiniMaxH3ReferenceToVideo",
                    "MiniMaxH3TaggedReferenceToVideo"}:
                widget_values = conditioning.get("widgets_values")
                if isinstance(widget_values, list) and widget_values:
                    widget_values[0] = first_prompt


def _remove_studio_legacy_assets(graph: Graph, source_audio: bool) -> None:
    remove_types = {"MiniMaxH3ChainRunManager",
                    "MiniMaxH3TaggedPictureReference"}
    if source_audio:
        remove_types.update({"LoadAudio", "MiniMaxH3TaggedAudioReference",
                             "MiniMaxH3SourceTimeline"})
    candidates = [node for node in list(graph.workflow["nodes"])
                  if node.get("type") in remove_types]
    upstream_ids = set()
    for node in candidates:
        if node.get("type") == "MiniMaxH3TaggedPictureReference":
            image_input = _input(node, "image")
            if image_input and image_input.get("link") is not None:
                upstream_ids.add(graph.links[int(image_input["link"])][1])
    for node in candidates:
        if node["id"] in graph.nodes:
            graph.remove_node(node)
    for node_id in upstream_ids:
        node = graph.nodes.get(node_id)
        if node and not any(value.get("links") for value in node["outputs"]):
            graph.remove_node(node)


def _studio_nodes(workflow: dict[str, Any], name: str) -> None:
    studios = [node for node in workflow["nodes"]
               if node.get("type") == "MiniMaxH3ChainPlanStudio"]
    if not studios:
        return
    graph = Graph(workflow)
    source_audio = "Source Audio" in name
    _remove_studio_legacy_assets(graph, source_audio)
    studio = studios[0]
    plan = next(node for node in workflow["nodes"]
                if node.get("type") == "MiniMaxH3ChainPlanModern")
    plan["inputs"] = [value for value in plan.get("inputs", [])
                      if not (value.get("name") == "generation_fingerprint"
                              and value.get("link") is None)]
    studio["title"] = "MiniMax H3 Plan Studio — TIMELINE / TAKES / TRIMS"
    studio["size"] = [1600, 1100]
    studio["properties"] = {"Node name for S&R": studio["type"]}
    # Discard obsolete empty slots, then retain the live Plan connection.
    plan_link = (_input(studio, "plan") or {}).get("link")
    for value in list(studio.get("inputs", [])):
        if value.get("name") != "plan" and value.get("link") is not None:
            graph.remove_link(int(value["link"]))
    studio["inputs"] = [_socket(
        "plan", "H3_CHAIN_PLAN", shape=7,
        link=int(plan_link) if plan_link is not None else None)]
    if plan_link is not None:
        graph.links[int(plan_link)][4] = 0
    studio["widgets_values"] = []

    run_name = str(plan["widgets_values"][1])
    carousel = graph.add_node(_node(
        "MiniMaxH3ProjectAssetManager",
        "MiniMax H3 Project Asset Carousel — IMPORT RELEASE REFERENCES",
        [0, 0], [1240, 920], [], [
            _out("project_assets", "H3_PROJECT_ASSETS"),
            _out("references", "H3_TAGGED_REFERENCES"),
            _out("reference_fingerprint", "STRING"),
            _out("source_timeline", "H3_SOURCE_TIMELINE"),
            _out("status", "STRING"),
        ], [run_name, "", "512", "timestamped_video", ""]))
    checkpoint = graph.add_node(_node(
        "MiniMaxH3ChainCheckpointManager",
        "MiniMax H3 Checkpoint Manager — BRANCHES / PREVIEWS / RESTORE",
        [0, 0], [1320, 980], [
            _socket("plan", "H3_CHAIN_PLAN", shape=7)], [
            _out("selected_manifest", "H3_CHAIN_MANIFEST")], [""]))

    plan["inputs"].append(_socket(
        "project_assets", "H3_PROJECT_ASSETS", shape=7))
    studio["inputs"].extend([
        _socket("tagged_references", "H3_TAGGED_REFERENCES", shape=7),
        _socket("project_assets", "H3_PROJECT_ASSETS", shape=7),
    ])
    graph.connect(carousel, "project_assets", plan, "project_assets",
                  "H3_PROJECT_ASSETS")
    graph.connect(carousel, "references", studio, "tagged_references",
                  "H3_TAGGED_REFERENCES")
    graph.connect(carousel, "project_assets", studio, "project_assets",
                  "H3_PROJECT_ASSETS")
    graph.connect(studio, "plan", checkpoint, "plan", "H3_CHAIN_PLAN")

    wrappers = [node for node in workflow["nodes"]
                if node.get("type") == "MiniMaxH3TaggedReferenceToVideo"]
    for wrapper in wrappers:
        references = _input(wrapper, "references")
        if references is None:
            wrapper["inputs"].insert(3, _socket(
                "references", "H3_TAGGED_REFERENCES"))
        graph.connect(carousel, "references", wrapper, "references",
                      "H3_TAGGED_REFERENCES")

    if name.startswith("Ref2V Studio"):
        asset_steps = (
            f"2. Import {ARRIVAL}; tag courier_arrival (Picture).\n"
            f"3. Import {DELIVERY}; tag greenhouse_delivery (Picture).\n")
        next_step = 4
    elif "Chain + Reference Image" in name:
        asset_steps = (
            "2. Import soldier_crabs_reference_cc0.png; tag crabs "
            "(Picture).\n")
        next_step = 3
    elif name.startswith("I2V Studio"):
        asset_steps = (
            f"2. Keep {ARRIVAL} selected in the opening Load Image node.\n"
            "3. Use the Carousel for additional project references when "
            "needed.\n")
        next_step = 4
    elif name.startswith("T2V Studio"):
        asset_steps = (
            "2. No reference asset is required; the Carousel can remain "
            "empty or hold later project media.\n")
        next_step = 3
    else:
        asset_steps = (
            "2. Keep the bundled source media selected in the existing "
            "loader nodes; use the Carousel for additional project assets.\n")
        next_step = 3
    source_step = ""
    if source_audio:
        source_step = (
            f"{next_step}. Import one audio file and assign Source track.\n")
        next_step += 1
    note = graph.add_node(_node(
        "Note", "0.6 STUDIO QUICK START", [0, 0], [620, 330], [], [], [
            "0.6 Studio quick start\n\n"
            f"1. Open the Project Asset Carousel.\n"
            + asset_steps + source_step
            + f"{next_step}. Edit scenes in Production Plan or Plan Studio.\n"
            + f"{next_step + 1}. Queue; inspect, branch, trim, or restore in "
              "Checkpoint Manager."
        ]))
    note["color"] = "#20354a"
    note["bgcolor"] = "#10202f"


def _clean_node(node: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "id", "type", "pos", "size", "flags", "order", "mode",
        "inputs", "outputs", "title", "properties", "widgets_values",
        "color", "bgcolor",
    }
    result = {key: copy.deepcopy(value) for key, value in node.items()
              if key in allowed}
    result.setdefault("pos", [0, 0])
    result.setdefault("size", [320, 180])
    result.setdefault("flags", {})
    result.setdefault("order", 0)
    result.setdefault("mode", 0)
    result.setdefault("inputs", [])
    result.setdefault("outputs", [])
    result["properties"] = {"Node name for S&R": str(result["type"])}
    result.setdefault("widgets_values", [])
    for value in result["inputs"]:
        for key in list(value):
            if key not in {"name", "type", "link", "shape", "widget",
                           "label", "dir"}:
                del value[key]
    for value in result["outputs"]:
        for key in list(value):
            if key not in {"name", "type", "links", "shape", "slot_index",
                           "label"}:
                del value[key]
    return result


def _canonicalize(workflow: dict[str, Any], name: str) -> dict[str, Any]:
    nodes = [_clean_node(node) for node in workflow["nodes"]]
    node_ids = {old["id"]: index + 1 for index, old in
                enumerate(workflow["nodes"])}
    link_ids = {old[0]: index + 1 for index, old in
                enumerate(workflow["links"])}
    for node in nodes:
        node["id"] = node_ids[node["id"]]
        node["order"] = node["id"] - 1
        for value in node["inputs"]:
            value["link"] = (link_ids.get(value.get("link"))
                             if value.get("link") is not None else None)
        for value in node["outputs"]:
            links = [link_ids[item] for item in (value.get("links") or [])
                     if item in link_ids]
            value["links"] = links or None
    links = []
    for old in workflow["links"]:
        links.append([
            link_ids[old[0]], node_ids[old[1]], int(old[2]),
            node_ids[old[3]], int(old[4]), str(old[5]),
        ])
    workflow_id = str(uuid.uuid5(NAMESPACE, name))
    result = {
        "id": workflow_id,
        "revision": 0,
        "last_node_id": len(nodes),
        "last_link_id": len(links),
        "nodes": nodes,
        "links": links,
        "groups": [],
        "config": {},
        "extra": {
            "ds": {"scale": 0.55, "offset": [320.0, 160.0]},
            "comfyui_mcp": {"workflow_uuid": workflow_id},
        },
        "version": 0.4,
    }
    _layout(result)
    return result


AUTHOR_TYPES = {
    "MiniMaxH3GenerationProfile", "MiniMaxH3ChainPlanModern",
    "MiniMaxH3ChainPlanStudio", "MiniMaxH3ChainScenePromptEditor",
    "MiniMaxH3ChainRichScenePromptEditor", "MiniMaxH3ProjectAssetManager",
    "MiniMaxH3ChainCheckpointManager",
}


def _layout(workflow: dict[str, Any]) -> None:
    author = [node for node in workflow["nodes"]
              if node["type"] in AUTHOR_TYPES
              or node.get("title") == "0.6 STUDIO QUICK START"]
    runtime = [node for node in workflow["nodes"] if node not in author]
    # Make all inherited runtime rectangles collision-free while retaining the
    # recognizable left-to-right graph.  Authoring interfaces receive their
    # own row below the runtime graph.
    placed: list[dict[str, Any]] = []
    for node in sorted(runtime, key=lambda value: (
            float(value["pos"][1]), float(value["pos"][0]), value["id"])):
        node["pos"] = [round(float(node["pos"][0]) / 32) * 32,
                       round(float(node["pos"][1]) / 32) * 32]
        _nudge(node, placed)
        placed.append(node)
    bottom = max((float(node["pos"][1]) + float(node["size"][1])
                  for node in runtime), default=0) + 320
    order = {
        "Note": 0,
        "MiniMaxH3ProjectAssetManager": 1,
        "MiniMaxH3GenerationProfile": 2,
        "MiniMaxH3ChainPlanModern": 3,
        "MiniMaxH3ChainPlanStudio": 4,
        "MiniMaxH3ChainScenePromptEditor": 5,
        "MiniMaxH3ChainRichScenePromptEditor": 5,
        "MiniMaxH3ChainCheckpointManager": 6,
    }
    x = min((float(node["pos"][0]) for node in runtime), default=0)
    for node in sorted(author, key=lambda value: (order.get(value["type"], 9),
                                                   value["id"])):
        width, height = map(float, node["size"][:2])
        node["pos"] = [x, bottom]
        x += width + 128
    workflow["groups"] = []
    if runtime:
        workflow["groups"].append(_group(1, "0.6 GENERATION RUNTIME",
                                          runtime, "#744c8c"))
    if author:
        workflow["groups"].append(_group(2, "0.6 AUTHORING + PROJECT",
                                          author, "#3f789e"))


def _nudge(node: dict[str, Any], placed: list[dict[str, Any]]) -> None:
    while True:
        conflict = None
        ax, ay = map(float, node["pos"][:2])
        aw, ah = map(float, node["size"][:2])
        for other in placed:
            bx, by = map(float, other["pos"][:2])
            bw, bh = map(float, other["size"][:2])
            if (ax < bx + bw + 48 and bx < ax + aw + 48
                    and ay < by + bh + 48 and by < ay + ah + 48):
                conflict = other
                break
        if conflict is None:
            return
        node["pos"][1] = (float(conflict["pos"][1])
                           + float(conflict["size"][1]) + 64)


def _group(group_id: int, title: str, nodes: list[dict[str, Any]],
           color: str) -> dict[str, Any]:
    left = min(float(node["pos"][0]) for node in nodes) - 64
    top = min(float(node["pos"][1]) for node in nodes) - 96
    right = max(float(node["pos"][0]) + float(node["size"][0])
                for node in nodes) + 64
    bottom = max(float(node["pos"][1]) + float(node["size"][1])
                 for node in nodes) + 64
    return {"id": group_id, "title": title,
            "bounding": [left, top, right - left, bottom - top],
            "color": color, "font_size": 24, "flags": {}}


def build(source: Path, output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    for source_name in WORKFLOW_NAMES:
        workflow = _load(source / source_name)
        output_name = OUTPUT_RENAMES.get(source_name, source_name)
        _normalize_model_widgets(workflow)
        _replace_loader_assets(workflow, output_name)
        _refresh_release_guidance(workflow, output_name)
        if any(node.get("type") == "MiniMaxH3ChainPlan"
               for node in workflow["nodes"]):
            _modernize_plan(workflow, output_name)
        _studio_nodes(workflow, output_name)
        clean = _canonicalize(workflow, output_name)
        (output / output_name).write_text(
            json.dumps(clean, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=LEGACY_05)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    build(args.source, args.output)


if __name__ == "__main__":
    main()
