#!/usr/bin/env python3
"""Type-based H3 example catalog and authoring-level workflow regression."""

import collections
import hashlib
import json
import pathlib


ROOT = pathlib.Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "example_workflows"
ARCHIVE = EXAMPLES / "Archive"
SOURCE_URL = (
    "https://discord.com/channels/1076117621407223829/"
    "1532625331960152124/1536689209761599608"
)
I2V_SOURCE_URL = (
    "https://discord.com/channels/1076117621407223829/"
    "1533677158067736777/1537180042210054226"
)
I2V_ASSET_SHA256 = (
    "7a9993055d71b1e174096f2a2533ae2a0b14a686fdacae0c7bab1faa738ef5f3"
)
FL2V_LAST_ASSET_SHA256 = (
    "e07862c0d5160f06f015b8849dc4b7d2db0524de5ba490fd26c3dff33e196b34"
)
CRAB_VIDEO_SHA256 = (
    "aacef1ac138445311eb61734f8ca92f8dc438b8d9ca3210fd8893aa5e925ee47"
)
CRAB_IMAGE_SHA256 = (
    "432dc2c9b0b9d0c33ed33217247fefcbe551d240959f6eefb7c04dfc99378047"
)
CRAB_MASK_SHA256 = (
    "95cf18228cd3559ad980339fe9d8fccdcef25799368719b8e044cd61c6691fe4"
)


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def node(workflow, node_type):
    matches = [item for item in workflow["nodes"]
               if item.get("type") == node_type]
    assert len(matches) == 1, (node_type, len(matches))
    return matches[0]


def socket(items, name):
    return next(item for item in items if item.get("name") == name)


def link(workflow, link_id):
    return next(item for item in workflow["links"] if item[0] == link_id)


def origin_for_input(workflow, input_value):
    value = link(workflow, input_value["link"])
    return next(item for item in workflow["nodes"] if item["id"] == value[1])


def prompt_text(value):
    return "\n".join(value) if isinstance(value, list) else str(value)


def comparable_plan(plan):
    defaults = plan.get("defaults") or {}
    return {
        "prompt_prefix": str(plan.get("prompt_prefix", "")),
        "shots": [{
            "id": shot["id"],
            "prompt": prompt_text(shot["prompt"]),
            "length": shot["length"],
            "steps": shot.get("steps", defaults.get("steps")),
            "seed": shot["seed"],
        } for shot in plan["shots"]],
    }


def validate_sampling_defaults(path):
    workflow = load(path)
    for item in workflow.get("nodes", []):
        identity = "%s %s %s" % (
            item.get("type", ""), item.get("title", ""),
            json.dumps(item.get("widgets_values", [])))
        assert not (
            item.get("type") == "LoraLoaderModelOnly"
            and ("lightx" in identity.lower()
                 or "turbo" in identity.lower())), path.name
        assert "cache" not in (
            "%s %s" % (item.get("type", ""), item.get("title", ""))
        ).lower(), (path.name, item.get("type"))
        if item.get("type") == "KSamplerSelect":
            assert item["widgets_values"] == ["res_multistep"], path.name
        elif item.get("type") == "BasicScheduler":
            assert item["widgets_values"][:2] == ["simple", 20], path.name
        elif item.get("type") == "H3InjectSchedule":
            assert item["widgets_values"][:2] == ["simple", 20], path.name
        elif item.get("type") == "MiniMaxH3ChainPlan":
            assert item["widgets_values"][12] == 20, path.name
            plan = json.loads(item["widgets_values"][0])
            if plan.get("defaults"):
                assert plan["defaults"]["steps"] == 20, path.name
            for shot in plan.get("shots", []):
                if "steps" in shot:
                    assert shot["steps"] == 20, (path.name, shot.get("id"))


def validate_v05_topology(workflow):
    """Maintained recursive examples teach the 0.5 semantic graph."""
    plan = node(workflow, "MiniMaxH3ChainPlan")
    policy = node(workflow, "MiniMaxH3ChainPolicy")
    assert not [item for item in workflow["nodes"] if item.get("type") in {
        "MiniMaxH3AudioPolicy", "MiniMaxH3TransitionPolicy",
        "MiniMaxH3Legacy04PolicyAdapter",
    }]
    legacy_audio = str(plan["widgets_values"][9])
    expected_audio = {
        "source_track": ["source", "on", "off"],
        "generated_audio": ["generated", "off", "on"],
        "source_plus_timeline": ["source", "on", "on"],
    }[legacy_audio]
    context = int(plan["widgets_values"][5])
    audio_context = int(plan["widgets_values"][10])
    mode = (str(plan["widgets_values"][16])
            if len(plan["widgets_values"]) > 16 else "guide")
    expected_transition = {
        ("guide", 0): "cut",
        ("guide", 22): "guide",
        ("masked_av", 39): "hard_av",
        ("audio_feathered_av", 39): "soft_av",
    }[(mode, context)]
    assert audio_context == context
    assert policy["widgets_values"] == [expected_transition, *expected_audio]
    assert origin_for_input(
        workflow, socket(plan["inputs"], "chain_policy")) == policy
    assert not any(item.get("name") in {"audio_policy", "transition_policy"}
                   for item in plan["inputs"])

    current = node(workflow, "MiniMaxH3ChainCurrent")
    trim = node(workflow, "MiniMaxH3LoopTrim")
    retain = socket(trim["inputs"], "retain_overlap_frames")
    trim_state = socket(trim["inputs"], "state")
    assert retain["link"] is None
    assert origin_for_input(workflow, trim_state) == current
    assert socket(current["outputs"], "video_blend_frames")["links"] is None
    assert socket(plan["outputs"], "video_blend_frames")["links"] is None

    start = node(workflow, "MiniMaxH3ChainLoopStart")
    studios = [item for item in workflow["nodes"]
               if item.get("type") == "MiniMaxH3ChainPlanStudio"]
    preflights = [item for item in workflow["nodes"]
                  if item.get("type") == "MiniMaxH3ChainPreflight"]
    if studios:
        assert not preflights
        assert studios[0]["widgets_values"] == [1, "", True]
        assert {item["name"] for item in studios[0]["inputs"]} >= {
            "plan", "source_timeline", "source_audio",
            "tagged_references", "reference_schedule",
        }
    else:
        assert len(preflights) == 1
        preflight = preflights[0]
        assert preflight["widgets_values"] == [1, "", True]
        assert origin_for_input(workflow, socket(start["inputs"], "plan")) == (
            preflight)
        assert socket(preflight["inputs"], "plan")["link"] is not None


def validate_links(workflow):
    nodes = {item["id"]: item for item in workflow["nodes"]}
    links = {item[0]: item for item in workflow["links"]}
    assert len(nodes) == len(workflow["nodes"])
    assert len(links) == len(workflow["links"])
    assert workflow["last_link_id"] >= max(links)
    for link_id, link in links.items():
        _, origin_id, origin_slot, target_id, target_slot, link_type = link
        assert origin_id in nodes and target_id in nodes
        origin = nodes[origin_id]["outputs"][origin_slot]
        target = nodes[target_id]["inputs"][target_slot]
        assert link_id in (origin.get("links") or [])
        assert target.get("link") == link_id
        # Reroutes and several legacy Comfy workflows serialize the concrete
        # resolved type on the link while retaining "*" or a stale socket type
        # on one endpoint. Structural ownership is the portable invariant.
        assert isinstance(link_type, str) and link_type
    for item in nodes.values():
        for input_value in item.get("inputs") or []:
            link_id = input_value.get("link")
            if link_id is not None:
                assert link_id in links
        for output in item.get("outputs") or []:
            for link_id in output.get("links") or []:
                assert link_id in links


def validate_no_node_overlap(workflow):
    """Release examples keep every visible node rectangle disjoint."""
    rectangles = []
    for item in workflow["nodes"]:
        position = item.get("pos")
        size = item.get("size")
        if not (isinstance(position, list) and isinstance(size, list)
                and len(position) >= 2 and len(size) >= 2):
            continue
        rectangles.append((
            item.get("type"), item.get("id"),
            float(position[0]), float(position[1]),
            float(size[0]), float(size[1]),
        ))
    for index, first in enumerate(rectangles):
        _, _, ax, ay, aw, ah = first
        for second in rectangles[index + 1:]:
            _, _, bx, by, bw, bh = second
            overlaps = (ax < bx + bw and bx < ax + aw
                        and ay < by + bh and by < ay + ah)
            assert not overlaps, (first[:2], second[:2])


def validate_crab_extension(path, expected_shots, tagged):
    workflow = load(path)
    validate_links(workflow)
    loader = node(workflow, "VHS_LoadVideo")
    assert loader["widgets_values"]["video"] == (
        "soldier_crabs_bribie_island_cc0.webm")
    assert loader["widgets_values"]["force_rate"] == 24
    assert (loader["widgets_values"]["custom_width"],
            loader["widgets_values"]["custom_height"]) == (960, 544)
    external = node(workflow, "MiniMaxH3ChainExternalVideo")
    assert socket(external["inputs"], "source_frames")["link"] is not None
    assert socket(external["inputs"], "source_audio")["link"] is not None
    start = node(workflow, "MiniMaxH3ChainLoopStart")
    assert socket(start["inputs"], "external_context")["link"] == (
        socket(external["outputs"], "external_context")["links"][0])
    context = node(workflow, "MiniMaxH3ChainContext")
    assert socket(context["inputs"], "audio_vae")["link"] is not None
    sampler = node(workflow, "SamplerCustomAdvanced")
    assert socket(context["outputs"], "latent")["links"] == [
        socket(sampler["inputs"], "latent_image")["link"]]

    plan_node = node(workflow, "MiniMaxH3ChainPlan")
    plan = json.loads(plan_node["widgets_values"][0])
    assert len(plan["shots"]) == expected_shots
    assert [shot["length"] for shot in plan["shots"]] == [192] * expected_shots
    assert plan_node["widgets_values"][3:6] == [960, 544, 39]
    assert plan_node["widgets_values"][9:11] == ["generated_audio", 39]
    assert plan_node["widgets_values"][15:17] == [
        39, "audio_feathered_av"]
    for shot in plan["shots"]:
        prompt = prompt_text(shot["prompt"])
        if tagged:
            positions = [prompt.index(section) for section in (
                "subject_definitions:", "summary:", "retention_analysis:",
                "detailed_description:", "overall_soundscape:",
                "non_diegetic_music:")]
            assert positions == sorted(positions) and positions[0] == 0
            assert "@crabs" in prompt
        else:
            positions = [prompt.index(section) for section in (
                "integrated_multimodal_description:",
                "overall_soundscape:", "non_diegetic_music:")]
            assert positions == sorted(positions) and positions[0] == 0
    if tagged:
        image = node(workflow, "LoadImage")
        assert image["widgets_values"][0] == "soldier_crabs_reference_cc0.png"
        reference = node(workflow, "MiniMaxH3TaggedPictureReference")
        assert reference["widgets_values"] == ["crabs"]
        conditioner = node(workflow, "MiniMaxH3TaggedReferenceToVideo")
        assert conditioner["widgets_values"][-4:] == [
            "strict", "512", "timestamped_video", True]
        assert socket(
            conditioner["inputs"], "references")["link"] in socket(
                reference["outputs"], "references")["links"]
    return workflow


def validate_crab_bridge(path):
    workflow = load(path)
    validate_links(workflow)
    loaders = [item for item in workflow["nodes"]
               if item["type"] == "VHS_LoadVideo"]
    assert len(loaders) == 2
    values = [item["widgets_values"] for item in loaders]
    assert [item["video"] for item in values] == [
        "soldier_crabs_bribie_island_cc0.webm"] * 2
    assert [(item["skip_first_frames"], item["frame_load_cap"])
            for item in values] == [(0, 99), (213, 100)]
    bridge = node(workflow, "MiniMaxH3ContexMaskedAVBridge")
    assert bridge["widgets_values"] == [24.0, 24.0, 39, "center"]
    assert all(socket(bridge["inputs"], name)["link"] is not None for name in (
        "latent", "vae", "audio_vae", "start_frames", "start_audio",
        "end_frames", "end_audio"))
    conditioner = node(workflow, "MiniMaxH3ImageToVideo")
    assert conditioner["widgets_values"][1:4] == [960, 544, 192]
    prompt = conditioner["widgets_values"][0]
    assert prompt.startswith("integrated_multimodal_description:")
    assert "overall_soundscape:" in prompt
    assert prompt.endswith("non_diegetic_music:\nN/A")
    sampler = node(workflow, "SamplerCustomAdvanced")
    assert socket(bridge["outputs"], "latent")["links"] == [
        socket(sampler["inputs"], "latent_image")["link"]]
    return workflow


def validate_t2v(path, editor_type, expected_blend):
    workflow = load(path)
    validate_links(workflow)
    node_types = {item.get("type") for item in workflow["nodes"]}
    assert "LoadImage" not in node_types
    assert not node_types.intersection({
        "PathchSageAttentionKJ",
        "MiniMaxH3MemoryEfficientSageAttentionPatch",
        "SolAttnPatch",
    })

    attention = node(workflow, "ModelAttentionBackend")
    assert attention["widgets_values"] == ["comfy kitchen attention"]
    assert "LoraLoaderModelOnly" not in node_types
    assert socket(attention["inputs"], "model")["link"] is not None

    conditioner = node(workflow, "MiniMaxH3ImageToVideo")
    assert socket(conditioner["inputs"], "first_frame")["link"] is None
    assert socket(conditioner["inputs"], "last_frame")["link"] is None
    assert conditioner["widgets_values"][1:4] == [544, 960, 243]

    plan_node = node(workflow, "MiniMaxH3ChainPlan")
    plan = json.loads(plan_node["widgets_values"][0])
    assert plan_node["widgets_values"][3:6] == [544, 960, 22]
    assert plan_node["widgets_values"][9] == "generated_audio"
    assert plan_node["widgets_values"][12] == 20
    assert plan_node["widgets_values"][15] == expected_blend
    assert plan["defaults"]["steps"] == 20
    assert node(workflow, "KSamplerSelect")["widgets_values"] == [
        "res_multistep"]
    scheduler = node(workflow, "BasicScheduler")
    assert scheduler["widgets_values"][0:2] == ["simple", 20]
    assert len(plan["shots"]) == 2
    assert [shot["length"] for shot in plan["shots"]] == [243, 243]
    for shot in plan["shots"]:
        prompt = "\n".join(shot["prompt"])
        first = prompt.index("integrated_multimodal_description:")
        sound = prompt.index("overall_soundscape:")
        music = prompt.index("non_diegetic_music:")
        assert first == 0 and first < sound < music
        assert "<Picture" not in prompt and "<Video" not in prompt
    assert "I have to be honest with you. I left Wan." in "\n".join(
        plan["shots"][0]["prompt"])

    editor = node(workflow, editor_type)
    assert socket(editor["inputs"], "plan")["link"] is not None
    assert ("MiniMaxH3ChainPlanStudio" in {
        item.get("type") for item in workflow["nodes"]}) == (
            editor_type == "MiniMaxH3ChainPlanStudio")
    rich_editors = [item for item in workflow["nodes"]
                    if item.get("type") ==
                    "MiniMaxH3ChainRichScenePromptEditor"]
    if editor_type == "MiniMaxH3ChainPlanStudio":
        assert len(rich_editors) == 1
        assert socket(rich_editors[0]["inputs"], "plan")["link"] is not None
    else:
        assert not rich_editors

    trim = node(workflow, "MiniMaxH3LoopTrim")
    saver = node(workflow, "MiniMaxH3ChainSegmentSave")
    assert socket(trim["inputs"], "retain_overlap_frames")["link"] is None
    assert socket(trim["inputs"], "state")["link"] is not None
    assert socket(trim["outputs"], "images_with_overlap")["links"]
    assert socket(saver["inputs"], "images_with_overlap")["link"] is not None

    review = node(workflow, "MiniMaxH3ChainReview")
    assert socket(review["inputs"], "source_audio")["link"] is None
    assert review["size"][1] >= 650

    notes = "\n".join(
        str(item.get("widgets_values", [""])[0])
        for item in workflow["nodes"] if item.get("type") == "Note")
    assert "🦙rishappi" in notes and SOURCE_URL in notes
    assert "Scene 2 is a new continuation" in notes
    if expected_blend:
        assert "blends only 5 frames" in notes
    else:
        assert "video_blend_frames = 0" in notes
    return workflow, plan


def validate_i2v(path, editor_type, expected_blend):
    workflow = load(path)
    validate_links(workflow)
    node_types = {item.get("type") for item in workflow["nodes"]}
    assert not node_types.intersection({
        "PathchSageAttentionKJ",
        "MiniMaxH3MemoryEfficientSageAttentionPatch",
        "SolAttnPatch",
    })

    assert node(workflow, "ModelAttentionBackend")["widgets_values"] == [
        "comfy kitchen attention"]
    assert "LoraLoaderModelOnly" not in node_types
    assert node(workflow, "KSamplerSelect")["widgets_values"] == [
        "res_multistep"]
    assert node(workflow, "BasicScheduler")["widgets_values"][0:2] == [
        "simple", 20]

    loader = node(workflow, "LoadImage")
    assert loader["widgets_values"][0] == (
        "jigen_market_garden_doom_opening.png")
    gate = node(workflow, "MiniMaxH3ChainFirstSceneImage")
    assert socket(gate["inputs"], "state")["link"] is not None
    assert socket(gate["inputs"], "image")["link"] is not None
    assert socket(gate["inputs"], "last_frame")["link"] is None
    assert socket(gate["outputs"], "last_frame")["links"] is None
    conditioner = node(workflow, "MiniMaxH3ImageToVideo")
    assert socket(conditioner["inputs"], "first_frame")["link"] is not None
    assert socket(conditioner["inputs"], "last_frame")["link"] is None
    assert conditioner["widgets_values"][1:4] == [896, 672, 362]
    assert socket(gate["outputs"], "first_frame")["links"] == [
        socket(conditioner["inputs"], "first_frame")["link"]]

    plan_node = node(workflow, "MiniMaxH3ChainPlan")
    plan = json.loads(plan_node["widgets_values"][0])
    assert plan_node["widgets_values"][3:6] == [896, 672, 22]
    assert plan_node["widgets_values"][9] == "generated_audio"
    assert plan_node["widgets_values"][10:13] == [22, 15, 20]
    assert plan_node["widgets_values"][15] == expected_blend
    assert plan["defaults"] == {"duration_seconds": 15, "steps": 20}
    assert [shot["length"] for shot in plan["shots"]] == [362, 362]
    opening = "\n".join(plan["shots"][0]["prompt"])
    continuation = "\n".join(plan["shots"][1]["prompt"])
    assert opening.startswith(
        "For the target video, at 0.00 seconds into the target video, "
        "<Picture 1> (from [Shot 1]) is fully referenced.")
    assert opening.index("integrated_multimodal_description:") < (
        opening.index("overall_soundscape:")) < opening.index(
            "non_diegetic_music:")
    assert "Classic Doom 1993" in opening and "Market Garden" in opening
    assert continuation.startswith("integrated_multimodal_description:")
    assert "incoming H3 Motion Context" in continuation
    assert "<Picture" not in continuation and "<Video" not in continuation
    assert continuation.index("overall_soundscape:") < continuation.index(
        "non_diegetic_music:")

    editor = node(workflow, editor_type)
    assert socket(editor["inputs"], "plan")["link"] is not None
    rich_editors = [item for item in workflow["nodes"]
                    if item.get("type") ==
                    "MiniMaxH3ChainRichScenePromptEditor"]
    if editor_type == "MiniMaxH3ChainPlanStudio":
        assert len(rich_editors) == 1
        assert socket(rich_editors[0]["inputs"], "plan")["link"] is not None
    else:
        assert not rich_editors

    trim = node(workflow, "MiniMaxH3LoopTrim")
    saver = node(workflow, "MiniMaxH3ChainSegmentSave")
    assert socket(trim["inputs"], "retain_overlap_frames")["link"] is None
    assert socket(trim["inputs"], "state")["link"] is not None
    assert socket(saver["inputs"], "images_with_overlap")["link"] is not None
    notes = "\n".join(
        str(item.get("widgets_values", [""])[0])
        for item in workflow["nodes"] if item.get("type") == "Note")
    assert "ᴊɪɢᴇɴ" in notes and I2V_SOURCE_URL in notes
    assert "Scene 2 is a new continuation" in notes
    assert ("video_blend_frames = 5" if expected_blend
            else "video_blend_frames = 0") in notes
    return workflow, plan


def validate_fl2v(path):
    workflow = load(path)
    validate_links(workflow)
    loaders = [item for item in workflow["nodes"]
               if item.get("type") == "LoadImage"]
    assert {item["widgets_values"][0] for item in loaders} == {
        "jigen_market_garden_doom_opening.png",
        "jigen_market_garden_doom_last.png",
    }

    current = node(workflow, "MiniMaxH3ChainCurrent")
    switch = node(workflow, "MiniMaxH3ChainFrameIndexSwitch")
    gate = node(workflow, "MiniMaxH3ChainFirstSceneImage")
    conditioner = node(workflow, "MiniMaxH3ImageToVideo")
    assert socket(current["outputs"], "clip_index")["links"] == [
        socket(switch["inputs"], "clip_index")["link"]]
    assert socket(switch["inputs"], "frame_1")["link"] is not None
    assert socket(switch["inputs"], "frame_2")["link"] is not None
    assert socket(switch["outputs"], "image")["links"] == [
        socket(gate["inputs"], "last_frame")["link"]]
    assert socket(gate["outputs"], "first_frame")["links"] == [
        socket(conditioner["inputs"], "first_frame")["link"]]
    assert socket(gate["outputs"], "last_frame")["links"] == [
        socket(conditioner["inputs"], "last_frame")["link"]]

    plan_node = node(workflow, "MiniMaxH3ChainPlan")
    plan = json.loads(plan_node["widgets_values"][0])
    assert [shot["length"] for shot in plan["shots"]] == [362, 362]
    first = "\n".join(plan["shots"][0]["prompt"])
    second = "\n".join(plan["shots"][1]["prompt"])
    assert first.startswith(
        "How the reference pictures align with the target video — "
        "Picture 1 (from Shot 1) aligns with the 0.00-second mark")
    assert "Picture 2 (from Shot 1) aligns with the 15.08-second mark" in first
    assert second.startswith(
        "How the reference pictures align with the target video — "
        "<Picture 1> (from [Shot 1]) aligns with the 15.08-second mark")
    for prompt in (first, second):
        assert prompt.index("integrated_multimodal_description:") < (
            prompt.index("overall_soundscape:")) < prompt.index(
                "non_diegetic_music:")
    notes = "\n".join(
        str(item.get("widgets_values", [""])[0])
        for item in workflow["nodes"] if item.get("type") == "Note")
    assert "A→B→A" in notes and "ᴊɪɢᴇɴ" in notes
    assert I2V_SOURCE_URL in notes
    return workflow, plan


def validate_ref2v(path, variant):
    workflow = load(path)
    validate_links(workflow)
    node_types = {item.get("type") for item in workflow["nodes"]}
    assert not node_types.intersection({
        "PathchSageAttentionKJ",
        "MiniMaxH3MemoryEfficientSageAttentionPatch",
        "SolAttnPatch",
    })
    assert node(workflow, "ModelAttentionBackend")["widgets_values"] == [
        "comfy kitchen attention"]
    assert node(workflow, "UNETLoader")["widgets_values"][0] == (
        "MiniMax-H3/minimax_h3_ref2va_pruned_int8_convrot.safetensors")
    assert "LoraLoaderModelOnly" not in node_types
    assert node(workflow, "KSamplerSelect")["widgets_values"] == [
        "res_multistep"]
    assert node(workflow, "BasicScheduler")["widgets_values"][0:2] == [
        "simple", 20]

    loaders = [item for item in workflow["nodes"]
               if item.get("type") == "LoadImage"]
    assert len(loaders) == 2
    assert {item["widgets_values"][0] for item in loaders} == {
        "jigen_market_garden_doom_opening.png",
        "jigen_market_garden_doom_last.png",
    }

    plan_node = node(workflow, "MiniMaxH3ChainPlan")
    plan = json.loads(plan_node["widgets_values"][0])
    expected_context = 39 if variant == "studio" else 22
    assert plan_node["widgets_values"][3:6] == [
        896, 672, expected_context]
    expected_audio_mode = (
        "source_track" if variant == "source_audio" else "generated_audio")
    assert plan_node["widgets_values"][9:13] == [
        expected_audio_mode, expected_context, 10, 20]
    defaults = plan.get("defaults")
    if defaults is not None:
        assert defaults == {"duration_seconds": 10, "steps": 20}
    else:
        # Saving through Plan Studio expands defaults into each scene and
        # stores prompts as strings. This is equivalent runtime Plan JSON.
        assert all(shot.get("steps") == 20 for shot in plan["shots"])
    assert [shot["length"] for shot in plan["shots"]] == [243, 243]
    assert [shot["seed"] for shot in plan["shots"]] == ["4201", "4202"]
    for shot in plan["shots"]:
        prompt = prompt_text(shot["prompt"])
        positions = [prompt.index(section) for section in (
            "subject_definitions:", "summary:", "retention_analysis:",
            "detailed_description:", "overall_soundscape:",
            "non_diegetic_music:")]
        assert positions == sorted(positions)
        assert positions[0] == 0

    if variant == "basic":
        conditioner = node(workflow, "MiniMaxH3ReferenceToVideo")
        assert "MiniMaxH3ScheduledReferenceToVideo" not in node_types
        assert "MiniMaxH3TaggedReferenceToVideo" not in node_types
        assert not any(item.get("type") ==
                       "MiniMaxH3ScheduledPictureReference"
                       for item in workflow["nodes"])
        assert socket(conditioner["inputs"],
                      "ref_images.ref_image_0")["link"] is not None
        assert socket(conditioner["inputs"],
                      "ref_images.ref_image_1")["link"] is not None
        prompts = [prompt_text(shot["prompt"]) for shot in plan["shots"]]
        assert all("<Picture 1>" in prompt and "<Picture 2>" in prompt
                   for prompt in prompts)
        assert all("@style_base" not in prompt for prompt in prompts)
        assert "MiniMaxH3ChainRunManager" not in node_types
        editor = node(workflow, "MiniMaxH3ChainScenePromptEditor")
        assert socket(editor["inputs"], "plan")["link"] is not None
    else:
        conditioner = node(workflow, "MiniMaxH3TaggedReferenceToVideo")
        assert conditioner["widgets_values"][-4:] == [
            "strict", "512", "timestamped_video", True]
        tagged_refs = [item for item in workflow["nodes"]
                       if item.get("type") ==
                       "MiniMaxH3TaggedPictureReference"]
        assert len(tagged_refs) == 2
        assert {tuple(item["widgets_values"]) for item in tagged_refs} == {
            ("style_base",), ("interior",)}
        assert not any(item.get("type", "").startswith(
            "MiniMaxH3Scheduled") for item in workflow["nodes"])
        base = next(item for item in tagged_refs
                    if item["widgets_values"][0] == "style_base")
        interior = next(item for item in tagged_refs
                        if item["widgets_values"][0] == "interior")
        assert socket(base["inputs"], "image")["link"] is not None
        assert socket(base["inputs"], "previous")["link"] is None
        assert socket(interior["inputs"], "image")["link"] is not None
        assert socket(interior["inputs"], "previous")["link"] is not None
        assert socket(conditioner["inputs"],
                      "references")["link"] is not None
        current = node(workflow, "MiniMaxH3ChainCurrent")
        assert socket(current["outputs"], "clip_index")["links"] == [
            socket(conditioner["inputs"], "clip_index")["link"]]
        assert socket(current["outputs"], "clip_count")["links"] == [
            socket(conditioner["inputs"], "clip_count")["link"]]
        assert socket(plan_node["inputs"],
                      "generation_fingerprint")["link"] is not None
        prompts = [prompt_text(shot["prompt"]) for shot in plan["shots"]]
        assert "@style_base" in prompts[0] and "@interior" not in prompts[0]
        assert "@style_base" in prompts[1] and "@interior" in prompts[1]
        assert all("<Picture" not in prompt for prompt in prompts)

        if variant == "tagged":
            assert "MiniMaxH3ChainRunManager" not in node_types
            editor = node(workflow, "MiniMaxH3ChainScenePromptEditor")
            assert socket(editor["inputs"], "plan")["link"] is not None
        else:
            studio = node(workflow, "MiniMaxH3ChainPlanStudio")
            rich = node(workflow, "MiniMaxH3ChainRichScenePromptEditor")
            manager = node(workflow, "MiniMaxH3ChainRunManager")
            loop_start = node(workflow, "MiniMaxH3ChainLoopStart")
            assert socket(studio["inputs"], "plan")["link"] is not None
            assert socket(rich["inputs"], "plan")["link"] is not None
            assert socket(manager["inputs"], "plan")["link"] is not None
            assert socket(rich["outputs"], "plan")["links"] == [
                socket(manager["inputs"], "plan")["link"]]
            assert socket(loop_start["inputs"], "plan")["link"] == (
                socket(manager["outputs"], "plan")["links"][0])
            assert socket(manager["inputs"], "asset_0")["link"] is not None
            assert socket(manager["inputs"], "asset_1")["link"] is not None
            assert manager["widgets_values"][0:3] == [True, True, False]
            if variant == "studio":
                assert plan_node["widgets_values"][-1] == "masked_av"
                context = node(workflow, "MiniMaxH3ChainContext")
                sampler = node(workflow, "SamplerCustomAdvanced")
                assert socket(context["outputs"], "latent")["links"] == [
                    socket(sampler["inputs"], "latent_image")["link"]]
            bindings = json.loads(manager["widgets_values"][3])
            assert len(bindings) == (3 if variant == "source_audio" else 2)
            assert {item["original_value"] for item in bindings} == {
                "jigen_market_garden_doom_opening.png",
                "jigen_market_garden_doom_last.png",
                *({"SELECT_FULL_SOURCE_TRACK.wav"}
                  if variant == "source_audio" else set()),
            }
            expected_roles = (
                {"picture", "source_track"}
                if variant == "source_audio" else {"picture"})
            assert {item["role"] for item in bindings} == expected_roles
            assert all(loader.get("properties", {}).get(
                "h3_asset_binding_ids", {}).get("0")
                for loader in loaders)

    assert conditioner["widgets_values"][1:4] == [896, 672, 243]
    assert socket(conditioner["inputs"], "audio_vae")["link"] is not None
    notes = "\n".join(
        str(item.get("widgets_values", [""])[0])
        for item in workflow["nodes"] if item.get("type") == "Note")
    assert "ᴊɪɢᴇɴ" in notes and I2V_SOURCE_URL in notes
    assert "subject_definitions:" in notes and "non_diegetic_music:" in notes
    return workflow, plan


def validate_ref2v_source_audio(path):
    workflow, plan = validate_ref2v(path, "source_audio")
    audio_loader = node(workflow, "LoadAudio")
    audio_ref = node(workflow, "MiniMaxH3TaggedAudioReference")
    conditioner = node(workflow, "MiniMaxH3TaggedReferenceToVideo")
    plan_node = node(workflow, "MiniMaxH3ChainPlan")
    current = node(workflow, "MiniMaxH3ChainCurrent")
    loop_start = node(workflow, "MiniMaxH3ChainLoopStart")
    manifest_load = node(workflow, "MiniMaxH3ChainManifestLoad")
    manager = node(workflow, "MiniMaxH3ChainRunManager")
    timeline = node(workflow, "MiniMaxH3SourceTimeline")
    studio = node(workflow, "MiniMaxH3ChainPlanStudio")
    assembles = [item for item in workflow["nodes"]
                 if item.get("type") == "MiniMaxH3ChainAssemble"]
    assert len(assembles) == 2

    assert audio_loader["widgets_values"][0] == "SELECT_FULL_SOURCE_TRACK.wav"
    assert audio_ref["widgets_values"] == ["audio_1", "standalone", False]
    assert origin_for_input(
        workflow, socket(audio_ref["inputs"], "audio")) == current
    assert socket(current["outputs"], "source_audio_slice")["links"] == [
        socket(audio_ref["inputs"], "audio")["link"]]
    assert current["widgets_values"] == [True]
    assert socket(audio_ref["inputs"], "previous")["link"] is not None
    assert socket(conditioner["inputs"], "references")["link"] == (
        socket(audio_ref["outputs"], "references")["links"][0])
    assert socket(conditioner["inputs"], "state")["link"] in (
        socket(current["outputs"], "state")["links"])
    picture_registry = origin_for_input(
        workflow, socket(audio_ref["inputs"], "previous"))
    assert origin_for_input(
        workflow, socket(plan_node["inputs"], "generation_fingerprint")) == (
            picture_registry)

    assert timeline["widgets_values"] == ["", "", "ignore", 0]
    assert origin_for_input(
        workflow, socket(timeline["inputs"], "source_audio")) == audio_loader
    assert socket(timeline["inputs"], "source_video")["link"] is None
    assert origin_for_input(
        workflow, socket(loop_start["inputs"], "source_timeline")) == timeline
    assert origin_for_input(
        workflow, socket(studio["inputs"], "source_timeline")) == timeline
    assert origin_for_input(
        workflow, socket(manifest_load["inputs"], "source_timeline")) == (
            timeline)
    source_consumers = [loop_start, current, manifest_load, *assembles]
    assert all(socket(item["inputs"], "source_audio")["link"] is None
               for item in source_consumers)
    assert set(socket(audio_loader["outputs"], "AUDIO")["links"]) == {
        socket(timeline["inputs"], "source_audio")["link"],
        socket(manager["inputs"], "asset_2")["link"],
    }
    assert audio_loader["properties"]["h3_asset_binding_ids"]["0"] == (
        "ref2v-source-audio-v1")
    assert manager["properties"]["h3_asset_roles"][
        "ref2v-source-audio-v1"] == "source_track"
    assert all("@audio_1 is the exact current-scene source-track slice"
               in prompt_text(shot["prompt"])
               for shot in plan["shots"])
    return workflow, plan


def validate_sequential_motion_ref(path):
    workflow = load(path)
    validate_links(workflow)
    assert "EXPERIMENTAL" in path.name
    assert node(workflow, "UNETLoader")["widgets_values"][0] == (
        "MiniMax-H3/minimax_h3_ref2va_pruned_int8_convrot.safetensors")

    loader = node(workflow, "LoadVideo")
    prep = node(workflow, "MiniMaxH3ReferenceVideoPrepare")
    motion = node(workflow, "MiniMaxH3TaggedVideoReference")
    wrapper = node(workflow, "MiniMaxH3TaggedReferenceToVideo")
    current = node(workflow, "MiniMaxH3ChainCurrent")
    priority = node(workflow, "MiniMaxH3PatchPriority")
    context = node(workflow, "MiniMaxH3ChainContext")
    plan_node = node(workflow, "MiniMaxH3ChainPlan")
    plan = json.loads(plan_node["widgets_values"][0])

    assert loader["widgets_values"][0] == (
        "SELECT_LONG_MOTION_REFERENCE_WITH_AUDIO.mp4")
    assert prep["widgets_values"] == [464, 24]
    assert socket(prep["inputs"], "source_video")["link"] == (
        socket(loader["outputs"], "VIDEO")["links"][0])
    assert socket(motion["inputs"], "video")["link"] == (
        socket(prep["outputs"], "ref_video")["links"][0])
    assert socket(motion["inputs"], "audio")["link"] == (
        socket(prep["outputs"], "source_audio")["links"][0])
    assert motion["widgets_values"] == [
        "motion", "motion_audio", "sequential"]
    assert socket(motion["inputs"], "previous")["link"] is not None
    assert socket(wrapper["inputs"], "references")["link"] == (
        socket(motion["outputs"], "references")["links"][0])
    assert origin_for_input(
        workflow, socket(wrapper["inputs"], "state")) == current
    assert socket(wrapper["inputs"], "clip_index")["link"] is not None
    assert socket(wrapper["inputs"], "clip_count")["link"] is not None
    assert socket(plan_node["inputs"], "generation_fingerprint")["link"] == (
        socket(motion["outputs"], "reference_fingerprint")["links"][0])

    assert socket(priority["inputs"], "conditioning")["link"] == (
        socket(wrapper["outputs"], "positive")["links"][0])
    assert socket(context["inputs"], "conditioning")["link"] == (
        socket(priority["outputs"], "conditioning")["links"][0])

    assert [shot["length"] for shot in plan["shots"]] == [243, 243]
    assert plan_node["widgets_values"][5] == 22
    assert plan_node["widgets_values"][9] == "generated_audio"
    prompts = ["\n".join(shot["prompt"]) for shot in plan["shots"]]
    for prompt in prompts:
        assert "@motion" in prompt and "@motion_audio" in prompt
        positions = [prompt.index(section) for section in (
            "subject_definitions:", "summary:", "retention_analysis:",
            "detailed_description:", "overall_soundscape:",
            "non_diegetic_music:")]
        assert positions == sorted(positions) and positions[0] == 0
    assert "source frame 0" in prompts[0]
    assert "source frame 221" in prompts[1]
    notes = "\n".join(
        str(item.get("widgets_values", [""])[0])
        for item in workflow["nodes"] if item.get("type") == "Note")
    assert "EXPERIMENTAL" in notes
    assert "0:243" in notes and "221:464" in notes
    assert "19.333" in notes and "embedded audio" in notes
    return workflow, plan


def validate_deferred_h3_upscale(path):
    workflow = load(path)
    validate_links(workflow)
    validate_no_node_overlap(workflow)
    node_types = {item.get("type") for item in workflow["nodes"]}
    required = {
        "MiniMaxH3ChainCheckpointManager",
        "MiniMaxH3ChainUpscaleAdapter",
        "MiniMaxH3ChainUpscaleCurrent",
        "MiniMaxH3UpscaleReferencePromptOverride",
        "MiniMaxH3ChainUpscaleReferenceConditioning",
        "H3ConditioningSyncFromLatents",
        "MinimaxH3LatentUpscaler3D",
        "MiniMaxH3ChainPass2Prepare",
        "BasicScheduler",
        "SamplerCustomAdvanced",
        "MiniMaxH3ChainUpscaleSegmentSave",
        "MiniMaxH3ChainUpscaleLoopEnd",
        "MiniMaxH3ChainAssemble",
    }
    assert required <= node_types
    assert "MiniMaxH3ChainPlan" not in node_types
    assert "MiniMaxH3ChainPolicy" not in node_types
    assert "MiniMaxH3ChainLoopStart" not in node_types
    assert "MiniMaxH3ChainContext" not in node_types

    manager = node(workflow, "MiniMaxH3ChainCheckpointManager")
    assert manager["size"][0] >= 1200 and manager["size"][1] >= 1000
    adapter = node(workflow, "MiniMaxH3ChainUpscaleAdapter")
    current = node(workflow, "MiniMaxH3ChainUpscaleCurrent")
    learned = node(workflow, "MinimaxH3LatentUpscaler3D")
    sync = node(workflow, "H3ConditioningSyncFromLatents")
    prepare = node(workflow, "MiniMaxH3ChainPass2Prepare")
    scheduler = node(workflow, "BasicScheduler")
    sampler = node(workflow, "SamplerCustomAdvanced")
    saver = node(workflow, "MiniMaxH3ChainUpscaleSegmentSave")
    loop_end = node(workflow, "MiniMaxH3ChainUpscaleLoopEnd")
    assembler = node(workflow, "MiniMaxH3ChainAssemble")

    assert manager["inputs"] == []
    assert [item["name"] for item in manager["outputs"]] == [
        "selected_manifest"]
    assert socket(manager["outputs"], "selected_manifest")["links"] == [
        socket(adapter["inputs"], "source_manifest")["link"]]
    assert adapter["widgets_values"][0:2] == ["h3_lbh_3d", "h3_latent"]
    assert adapter["widgets_values"][3:7] == [1, 0, False, 18]
    assert socket(adapter["outputs"], "flow")["links"] == [
        socket(loop_end["inputs"], "flow")["link"]]
    assert socket(current["outputs"], "source_latent")["links"] is None
    assert socket(current["outputs"], "source_video_latent")["links"] == [
        socket(learned["inputs"], "latent")["link"],
        socket(sync["inputs"], "original_latent")["link"]]
    assert socket(current["outputs"], "source_audio_latent")["links"] == [
        socket(prepare["inputs"], "source_audio")["link"]]
    conditioner = node(
        workflow, "MiniMaxH3ChainUpscaleReferenceConditioning")
    override = node(workflow, "MiniMaxH3UpscaleReferencePromptOverride")
    assert socket(conditioner["inputs"], "state")["link"] in socket(
        current["outputs"], "state")["links"]
    assert socket(prepare["inputs"], "state")["link"] in socket(
        current["outputs"], "state")["links"]
    assert conditioner["widgets_values"][:2] == [
        "text_only", "exclude_video_keep_audio"]
    assert conditioner["widgets_values"][2:] == ["", "inherit", "strict"]
    assert override["widgets_values"] == ["", ""]
    assert socket(override["inputs"], "references")["link"] is None
    assert socket(conditioner["inputs"], "tagged_references")["link"] == (
        socket(override["outputs"], "references")["links"][0])
    assert socket(conditioner["inputs"], "prompt_override")["link"] == (
        socket(override["outputs"], "prompt_override")["links"][0])
    assert socket(conditioner["outputs"], "positive")["links"] == [
        socket(sync["inputs"], "positive")["link"]]
    assert socket(conditioner["inputs"], "target_video_latent")["link"] is None
    assert origin_for_input(
        workflow, socket(conditioner["inputs"], "video_vae"))["type"] == (
            "VAELoader")
    assert socket(learned["outputs"], "latent")["links"] == [
        socket(prepare["inputs"], "upscaled_video")["link"],
        socket(sync["inputs"], "upscaled_latent")["link"]]
    assert sync["widgets_values"] == [
        "bilinear", "conditioning_policy"]
    assert scheduler["widgets_values"] == ["simple", 20, 0.24]
    assert learned["widgets_values"] == [
        "minimax_h3_latent_upscaler_3d_fp16.safetensors", "megapixels",
        1.5, 32, "cuda", "fp16"]
    attention = node(workflow, "ModelAttentionBackend")
    assert attention["mode"] == 4
    for functional in workflow["nodes"]:
        if functional.get("type") != "Note":
            assert "title" not in functional, functional.get("type")
    guider = node(workflow, "BasicGuider")
    assert socket(sync["outputs"], "positive")["links"] == [
        socket(guider["inputs"], "conditioning")["link"]]
    assert socket(prepare["outputs"], "latent")["links"] == [
        socket(sampler["inputs"], "latent_image")["link"]]
    assert node(workflow, "KSamplerSelect")["widgets_values"] == [
        "res_multistep"]
    assert socket(sampler["outputs"], "output")["links"]
    assert socket(saver["inputs"], "images")["link"] is not None
    assert socket(saver["inputs"], "upscaled_latent")["link"] is not None
    assert socket(loop_end["inputs"], "images")["link"] is not None
    assert socket(loop_end["inputs"], "upscaled_latent")["link"] is not None
    assert socket(loop_end["outputs"], "manifest")["links"] == [
        socket(assembler["inputs"], "manifest")["link"]]
    assert socket(loop_end["outputs"], "manifest")["type"] == (
        "H3_CHAIN_MANIFEST")
    assert socket(assembler["inputs"], "manifest")["type"] == (
        "H3_CHAIN_MANIFEST")
    notes = "\n".join(
        str(item.get("widgets_values", [""])[0])
        for item in workflow["nodes"] if item.get("type") == "Note")
    assert "selected_manifest cable is the complete parent-chain contract" in notes
    assert "No Plan, Source Timeline, source audio" in notes
    assert "normal H3 Tagged Ref line" in notes
    assert "H3 Conditioning Sync From Latents" in notes
    assert "resizes match picture minimax_refs plus minimax_keyframes" in notes
    assert "keeping max picture refs at their cached geometry" in notes
    assert "excludes both the Qwen motion-video presentation" in notes
    assert "prompt override" in notes
    assert "OPTIONAL NEUTRAL REPLACEMENT PROMPT" in notes
    assert "Preserve the existing video's identity" in notes
    assert "12-step pass-2 prefix" in notes
    assert "small 12-step HQ context tail" in notes
    assert "save_latent is OFF" in notes
    assert "Comfyui_Minimax_h3_latent_Upscaler" in notes
    h3_video_vae = node(workflow, "VAELoader")
    assert h3_video_vae["widgets_values"] == [
        "MiniMaw-H3/minimax_h3_video_vae_fp16.safetensors"]
    return workflow


def validate_deferred_h3_derope(path):
    workflow = load(path)
    validate_links(workflow)
    validate_no_node_overlap(workflow)
    node_types = {item.get("type") for item in workflow["nodes"]}
    assert {
        "MiniMaxH3ChainCheckpointManager",
        "MiniMaxH3ChainUpscaleAdapter",
        "MiniMaxH3ChainUpscaleCurrent",
        "MiniMaxH3ChainDeropeGuard",
        "MiniMaxH3ChainDeropeFreezeMask",
        "MiniMaxH3ChainDeropeContinuity",
        "MiniMaxH3ChainRecoveredAV",
        "MiniMaxH3ChainUpscaleReferenceConditioning",
        "H3ConditioningSyncFromLatents",
        "H3JerkOracle", "H3TimeSmear", "H3AudioSmear", "H3V2VInit",
        "H3InjectSchedule", "H3ExactRecover", "H3AudioRecover",
        "MinimaxH3LatentUpscaler3D",
        "MiniMaxH3ChainUpscaleSegmentSave",
        "MiniMaxH3ChainUpscaleLoopEnd",
        "MiniMaxH3ChainAssemble",
    } <= node_types
    assert not node_types.intersection({
        "MiniMaxH3ChainPlan", "MiniMaxH3ChainPass2Prepare",
        "BasicScheduler", "DisableNoise", "H3TemporalInsert",
    })
    for item in workflow["nodes"]:
        if item["type"] != "Note":
            assert not str(item.get("title") or "").strip(), item["type"]

    adapter = node(workflow, "MiniMaxH3ChainUpscaleAdapter")
    current = node(workflow, "MiniMaxH3ChainUpscaleCurrent")
    oracle = node(workflow, "H3JerkOracle")
    guard = node(workflow, "MiniMaxH3ChainDeropeGuard")
    smear = node(workflow, "H3TimeSmear")
    freeze = node(workflow, "MiniMaxH3ChainDeropeFreezeMask")
    learned = node(workflow, "MinimaxH3LatentUpscaler3D")
    continuity = node(workflow, "MiniMaxH3ChainDeropeContinuity")
    conditioner = node(
        workflow, "MiniMaxH3ChainUpscaleReferenceConditioning")
    sync = node(workflow, "H3ConditioningSyncFromLatents")
    init = node(workflow, "H3V2VInit")
    schedule = node(workflow, "H3InjectSchedule")
    recover = node(workflow, "H3ExactRecover")
    recover_audio = node(workflow, "H3AudioRecover")
    recovered_av = node(workflow, "MiniMaxH3ChainRecoveredAV")
    saver = node(workflow, "MiniMaxH3ChainUpscaleSegmentSave")
    loop_end = node(workflow, "MiniMaxH3ChainUpscaleLoopEnd")
    assembler = node(workflow, "MiniMaxH3ChainAssemble")

    assert adapter["widgets_values"][0:2] == [
        "h3_lbh_3d_derope", "h3_latent"]
    assert adapter["widgets_values"][3:7] == [1, 0, False, 18]
    assert origin_for_input(workflow, socket(oracle["inputs"], "samples")) == (
        current)
    assert origin_for_input(workflow, socket(oracle["inputs"], "length")) == (
        current)
    assert origin_for_input(workflow, socket(guard["inputs"], "hold_map")) == (
        oracle)
    assert origin_for_input(
        workflow, socket(smear["inputs"], "hold_map")) == guard
    assert origin_for_input(
        workflow, socket(smear["inputs"], "expand_to_end")) == guard
    assert origin_for_input(
        workflow, socket(freeze["inputs"], "hold_map_used")) == smear
    smear_encode = origin_for_input(
        workflow, socket(learned["inputs"], "latent"))
    assert smear_encode["type"] == "VAEEncode"
    assert origin_for_input(
        workflow, socket(smear_encode["inputs"], "pixels")) == smear
    assert origin_for_input(
        workflow, socket(continuity["inputs"], "video_latent")) == learned
    assert origin_for_input(
        workflow, socket(conditioner["inputs"], "target_video_latent")) == (
            continuity)
    assert origin_for_input(
        workflow, socket(sync["inputs"], "upscaled_latent")) == continuity
    assert origin_for_input(
        workflow, socket(init["inputs"], "samples")) == continuity
    assert origin_for_input(workflow, socket(init["inputs"], "length")) == (
        smear)
    assert origin_for_input(workflow, socket(init["inputs"], "mask")) == (
        freeze)
    assert init["widgets_values"][5] is True
    assert init["widgets_values"][6] == (
        "follow the original performance (0.5)")
    assert schedule["widgets_values"] == [
        "simple", 20, 0.5, "20-step simple schedule"]
    assert node(workflow, "KSamplerSelect")["widgets_values"] == [
        "res_multistep"]
    assert recover_audio["widgets_values"][-1] == (
        "keep the original performance (safe default)")
    assert origin_for_input(
        workflow, socket(recovered_av["inputs"], "video_latent"))["type"] == (
            "VAEEncode")
    assert origin_for_input(
        workflow, socket(recovered_av["inputs"], "audio_latent"))["type"] == (
            "VAEEncodeAudio")
    assert origin_for_input(workflow, socket(saver["inputs"], "images")) == (
        recover)
    assert origin_for_input(
        workflow, socket(saver["inputs"], "recovered_audio")) == recover_audio
    assert origin_for_input(
        workflow, socket(saver["inputs"], "upscaled_latent")) == recovered_av
    assert origin_for_input(
        workflow, socket(loop_end["inputs"], "upscaled_latent")) == (
            recovered_av)
    assert socket(loop_end["outputs"], "manifest")["links"] == [
        socket(assembler["inputs"], "manifest")["link"]]
    return workflow


def validate_seedvr2_full_chain(path):
    workflow = load(path)
    validate_links(workflow)
    validate_no_node_overlap(workflow)
    node_types = {item.get("type") for item in workflow["nodes"]}
    assert {
        "MiniMaxH3ChainCheckpointManager",
        "MiniMaxH3ChainLatentVideoAdapter",
        "VAELoader",
        "SeedVR2LoadDiTModel",
        "SeedVR2LoadVAEModel",
        "SeedVR2DirectVideoUpscaler",
        "SaveVideo",
    } <= node_types
    assert not {
        "MiniMaxH3ChainPlan", "MiniMaxH3ChainLoopStart",
        "MiniMaxH3ChainUpscaleAdapter", "SamplerCustomAdvanced",
        "VAEDecode", "CreateVideo",
    }.intersection(node_types)
    manager = node(workflow, "MiniMaxH3ChainCheckpointManager")
    adapter = node(workflow, "MiniMaxH3ChainLatentVideoAdapter")
    direct = node(workflow, "SeedVR2DirectVideoUpscaler")
    assert manager["size"][0] >= 1200 and manager["size"][1] >= 1000
    assert direct["size"][0] >= 600 and direct["size"][1] >= 700
    saver = node(workflow, "SaveVideo")
    assert socket(manager["outputs"], "selected_manifest")["links"] == [
        socket(adapter["inputs"], "manifest")["link"]]
    assert node(workflow, "VAELoader")["widgets_values"] == [
        "MiniMaw-H3/minimax_h3_video_vae_fp16.safetensors"]
    assert adapter["widgets_values"] == [
        "plan", "plan", "disk-backed", True, 256]
    assert socket(adapter["outputs"], "video")["links"] == [
        socket(direct["inputs"], "video")["link"]]
    assert direct["widgets_values"][5:8] == [21, 2, False]
    assert socket(direct["outputs"], "video")["links"] == [
        socket(saver["inputs"], "video")["link"]]
    notes = "\n".join(
        str(item.get("widgets_values", [""])[0])
        for item in workflow["nodes"] if item.get("type") == "Note")
    assert "disk-backed" in notes
    assert "Do not select minimax_h3_audio_vae" in notes
    assert "No Plan, Source Timeline" in notes
    return workflow


def main():
    for path in EXAMPLES.rglob("*.json"):
        validate_sampling_defaults(path)
    assert EXAMPLES.joinpath("README.md").is_file()
    assert ARCHIVE.joinpath("README.md").is_file()
    assert len(list(ARCHIVE.glob("*.json"))) == 9
    for path in ARCHIVE.glob("*.json"):
        validate_links(load(path))

    t2v_normal_path = EXAMPLES / "T2V Normal - MiniMax H3.json"
    t2v_studio_path = EXAMPLES / "T2V Studio - MiniMax H3.json"
    i2v_normal_path = EXAMPLES / "I2V Normal - MiniMax H3.json"
    i2v_studio_path = EXAMPLES / "I2V Studio - MiniMax H3.json"
    fl2v_normal_path = EXAMPLES / "FL2V Normal - MiniMax H3.json"
    ref2v_basic_path = EXAMPLES / "Ref2V Basic - MiniMax H3.json"
    ref2v_tagged_path = EXAMPLES / "Ref2V Tagged - MiniMax H3.json"
    ref2v_studio_path = EXAMPLES / "Ref2V Studio Tagged - MiniMax H3.json"
    ref2v_source_audio_path = (
        EXAMPLES / "Ref2V Studio Tagged Source Audio - MiniMax H3.json")
    sequential_path = (
        EXAMPLES / "Ref2V Sequential Motion - EXPERIMENTAL - MiniMax H3.json")
    deferred_upscale_path = (
        EXAMPLES / "Deferred Upscale - H3 LBH 3D - MiniMax H3.json")
    deferred_derope_path = (
        EXAMPLES /
        "Deferred Upscale + De-Rope - H3 LBH 3D - MiniMax H3.json")
    seedvr2_full_chain_path = (
        EXAMPLES / "Deferred Upscale - SeedVR2 Full Chain - MiniMax H3.json")
    masked_inpaint_path = (
        EXAMPLES / "Masked Video Inpaint - MiniMax H3.json")
    masked_ref_inpaint_path = (
        EXAMPLES / "Ref2V Masked Video Inpaint - MiniMax H3.json")
    masked_single_extension_path = (
        EXAMPLES / "Masked AV Extension - Single Clip - MiniMax H3.json")
    masked_chain_extension_path = (
        EXAMPLES /
        "Masked AV Extension - Chain + Reference Image - MiniMax H3.json")
    masked_bridge_path = (
        EXAMPLES / "Masked AV Bridge - Two Clips - MiniMax H3.json")
    assert set(path.name for path in EXAMPLES.glob("*.json")) == {
        t2v_normal_path.name, t2v_studio_path.name,
        i2v_normal_path.name, i2v_studio_path.name,
        fl2v_normal_path.name, ref2v_basic_path.name,
        ref2v_tagged_path.name, ref2v_studio_path.name,
        ref2v_source_audio_path.name,
        sequential_path.name,
        deferred_upscale_path.name,
        deferred_derope_path.name,
        seedvr2_full_chain_path.name,
        masked_inpaint_path.name,
        masked_ref_inpaint_path.name,
        masked_single_extension_path.name,
        masked_chain_extension_path.name,
        masked_bridge_path.name,
    }
    for path in EXAMPLES.glob("*.json"):
        workflow = load(path)
        if path in {
                deferred_upscale_path, deferred_derope_path,
                seedvr2_full_chain_path}:
            continue
        if path == masked_bridge_path:
            validate_links(workflow)
            continue
        validate_v05_topology(workflow)
        if path in {masked_inpaint_path, masked_ref_inpaint_path}:
            validate_links(workflow)
            continue
        context = node(workflow, "MiniMaxH3ChainContext")
        sampler = node(workflow, "SamplerCustomAdvanced")
        assert socket(context["outputs"], "latent")["links"] == [
            socket(sampler["inputs"], "latent_image")["link"]], path.name
    t2v_normal, t2v_normal_plan = validate_t2v(
        t2v_normal_path, "MiniMaxH3ChainScenePromptEditor", 0)
    t2v_studio, t2v_studio_plan = validate_t2v(
        t2v_studio_path, "MiniMaxH3ChainPlanStudio", 5)
    assert t2v_normal_plan == t2v_studio_plan
    i2v_normal, i2v_normal_plan = validate_i2v(
        i2v_normal_path, "MiniMaxH3ChainScenePromptEditor", 0)
    i2v_studio, i2v_studio_plan = validate_i2v(
        i2v_studio_path, "MiniMaxH3ChainPlanStudio", 5)
    assert i2v_normal_plan == i2v_studio_plan
    fl2v_normal, _fl2v_normal_plan = validate_fl2v(fl2v_normal_path)
    ref2v_basic, _ref2v_basic_plan = validate_ref2v(
        ref2v_basic_path, "basic")
    ref2v_tagged, ref2v_tagged_plan = validate_ref2v(
        ref2v_tagged_path, "tagged")
    ref2v_studio, ref2v_studio_plan = validate_ref2v(
        ref2v_studio_path, "studio")
    ref2v_source_audio, ref2v_source_audio_plan = (
        validate_ref2v_source_audio(ref2v_source_audio_path))
    assert comparable_plan(ref2v_tagged_plan) == comparable_plan(
        ref2v_studio_plan)
    assert [
        (shot["id"], shot["length"], shot["steps"], shot["seed"])
        for shot in ref2v_studio_plan["shots"]
    ] == [
        (shot["id"], shot["length"], shot["steps"], shot["seed"])
        for shot in ref2v_source_audio_plan["shots"]
    ]
    sequential, _sequential_plan = validate_sequential_motion_ref(
        sequential_path)
    deferred_upscale = validate_deferred_h3_upscale(deferred_upscale_path)
    deferred_derope = validate_deferred_h3_derope(deferred_derope_path)
    seedvr2_full_chain = validate_seedvr2_full_chain(
        seedvr2_full_chain_path)
    masked_inpaint = load(masked_inpaint_path)
    masked_types = {item["type"] for item in masked_inpaint["nodes"]}
    assert {
        "MiniMaxH3ChainLoopStart",
        "MiniMaxH3ChainLoopEnd",
        "MiniMaxH3ContexLoopSourceAVTarget",
        "MiniMaxH3ContexLoopMaskSlice",
        "MiniMaxH3ContexMaskGridPreview",
        "MiniMaxH3ContexMaskedTarget",
    } <= masked_types
    assert not masked_types.intersection({
        "LTXVConcatAVLatent", "LTXVSeparateAVLatent"})
    assert "MiniMaxH3PerRowMaskPatch" not in masked_types
    source_loader = node(masked_inpaint, "VHS_LoadVideo")
    assert source_loader["widgets_values"]["video"] == (
        "soldier_crabs_bribie_island_cc0.webm")
    assert source_loader["widgets_values"]["force_rate"] == 24
    source_target = node(
        masked_inpaint, "MiniMaxH3ContexLoopSourceAVTarget")
    chain_context = node(masked_inpaint, "MiniMaxH3ChainContext")
    conditioner = node(masked_inpaint, "MiniMaxH3ImageToVideo")
    assert socket(source_target["inputs"], "latent")["link"] == (
        socket(conditioner["outputs"], "LATENT")["links"][0])
    assert socket(source_target["inputs"], "source_frames")["link"] == (
        socket(source_loader["outputs"], "IMAGE")["links"][0])
    assert socket(source_target["inputs"], "source_audio")["link"] == (
        socket(source_loader["outputs"], "audio")["links"][0])
    masked_target = node(masked_inpaint, "MiniMaxH3ContexMaskedTarget")
    assert socket(source_target["outputs"], "source_target")["links"] == [
        socket(chain_context["inputs"], "latent")["link"]]
    assert socket(chain_context["outputs"], "latent")["links"] == [
        socket(masked_target["inputs"], "target_latent")["link"]]
    assert masked_target["widgets_values"] == [
        "white = generate", "preserve source audio",
        "H3 exact (causal/token max)"]
    masked_sampler = node(masked_inpaint, "SamplerCustomAdvanced")
    assert socket(masked_target["outputs"], "masked_target")["links"] == [
        socket(masked_sampler["inputs"], "latent_image")["link"]]
    mask_loader = node(masked_inpaint, "LoadImageMask")
    assert mask_loader["widgets_values"][0] == (
        "soldier_crabs_inpaint_mask.png")
    mask_slice = node(masked_inpaint, "MiniMaxH3ContexLoopMaskSlice")
    grid_preview = node(masked_inpaint, "MiniMaxH3ContexMaskGridPreview")
    assert socket(mask_loader["outputs"], "MASK")["links"] == [
        socket(mask_slice["inputs"], "mask")["link"]]
    assert socket(mask_slice["outputs"], "scene_mask")["links"] == [
        socket(grid_preview["inputs"], "mask")["link"]]
    assert mask_slice["widgets_values"] == [24.0]
    assert grid_preview["widgets_values"][-1] == "white = generate"
    masked_plan_node = node(masked_inpaint, "MiniMaxH3ChainPlan")
    masked_plan = json.loads(masked_plan_node["widgets_values"][0])
    assert [shot["length"] for shot in masked_plan["shots"]] == [175, 175]
    assert masked_plan_node["widgets_values"][5] == 39
    assert masked_plan_node["widgets_values"][16] == "masked_av"

    masked_ref_inpaint = load(masked_ref_inpaint_path)
    masked_ref_types = {
        item["type"] for item in masked_ref_inpaint["nodes"]}
    assert {
        "MiniMaxH3ReferenceToVideo",
        "MiniMaxH3ContexLoopSourceAVTarget",
        "MiniMaxH3ContexLoopMaskSlice",
        "MiniMaxH3ContexMaskGridPreview",
        "MiniMaxH3ContexMaskedTarget",
    } <= masked_ref_types
    assert not masked_ref_types.intersection({
        "MiniMaxH3ImageToVideo", "LTXVConcatAVLatent",
        "LTXVSeparateAVLatent", "MVEx_MaskToLatentSpace",
        "MVEx_SubjectCrop", "MVEx_SubjectUncrop",
    })
    ref_model = node(masked_ref_inpaint, "UNETLoader")
    assert ref_model["widgets_values"][0] == (
        "MiniMax-H3/minimax_h3_ref2va_pruned_int8_convrot.safetensors")
    ref_picture = node(masked_ref_inpaint, "LoadImage")
    assert ref_picture["widgets_values"][0] == (
        "soldier_crabs_reference_cc0.png")
    ref_conditioner = node(masked_ref_inpaint, "MiniMaxH3ReferenceToVideo")
    ref_image_input = socket(
        ref_conditioner["inputs"], "ref_images.ref_image_0")
    assert ref_image_input["link"] == (
        socket(ref_picture["outputs"], "IMAGE")["links"][0])
    assert socket(ref_conditioner["inputs"], "ref_videos.ref_video_0")[
        "link"] is None
    assert socket(ref_conditioner["inputs"], "audio_vae")["link"] is not None
    ref_source_target = node(
        masked_ref_inpaint, "MiniMaxH3ContexLoopSourceAVTarget")
    assert socket(ref_conditioner["outputs"], "LATENT")["links"] == [
        socket(ref_source_target["inputs"], "latent")["link"]]
    ref_context = node(masked_ref_inpaint, "MiniMaxH3ChainContext")
    assert socket(ref_conditioner["outputs"], "positive")["links"] == [
        socket(ref_context["inputs"], "conditioning")["link"]]
    assert socket(ref_source_target["outputs"], "source_target")["links"] == [
        socket(ref_context["inputs"], "latent")["link"]]
    ref_masked_target = node(
        masked_ref_inpaint, "MiniMaxH3ContexMaskedTarget")
    assert socket(ref_context["outputs"], "latent")["links"] == [
        socket(ref_masked_target["inputs"], "target_latent")["link"]]
    assert ref_masked_target["widgets_values"] == [
        "white = generate", "preserve source audio",
        "H3 exact (causal/token max)"]
    ref_sampler = node(masked_ref_inpaint, "SamplerCustomAdvanced")
    assert socket(ref_masked_target["outputs"], "masked_target")["links"] == [
        socket(ref_sampler["inputs"], "latent_image")["link"]]
    ref_plan_node = node(masked_ref_inpaint, "MiniMaxH3ChainPlan")
    ref_plan = json.loads(ref_plan_node["widgets_values"][0])
    assert [shot["length"] for shot in ref_plan["shots"]] == [175, 175]
    assert ref_plan_node["widgets_values"][1:3] == [
        "cc0_soldier_crabs_ref2v_inpaint",
        "cc0-crab-source-av-v1+picture1-ref2v+static-mask-h3-exact-v1",
    ]
    for shot in ref_plan["shots"]:
        prompt = prompt_text(shot["prompt"])
        positions = [prompt.index(section) for section in (
            "subject_definitions:", "summary:", "retention_analysis:",
            "detailed_description:", "overall_soundscape:",
            "non_diegetic_music:")]
        assert positions == sorted(positions) and positions[0] == 0
        assert "<Subject 1>" in prompt and "<Picture 1>" in prompt
        assert "<Video 1>" not in prompt and "<Audio 1>" not in prompt
        assert "source target" in prompt
        assert "[reference generation + video editing + audio reuse]" in prompt
        assert "Preserve" in prompt or "preserve" in prompt
    masked_single_extension = validate_crab_extension(
        masked_single_extension_path, 1, False)
    masked_chain_extension = validate_crab_extension(
        masked_chain_extension_path, 3, True)
    masked_bridge = validate_crab_bridge(masked_bridge_path)

    def generation_types(workflow):
        return collections.Counter(
            item.get("type")
            for item in workflow["nodes"]
            if item.get("type") not in {
                "MiniMaxH3ChainScenePromptEditor",
                "MiniMaxH3ChainPlanStudio",
                "MiniMaxH3ChainRichScenePromptEditor",
                "MiniMaxH3ChainRunManager",
                "MiniMaxH3ChainPreflight",
                "MiniMaxH3ChainPolicy",
            })

    assert generation_types(t2v_normal) == generation_types(t2v_studio)
    assert generation_types(i2v_normal) == generation_types(i2v_studio)
    assert generation_types(ref2v_tagged) == generation_types(ref2v_studio)
    uuids = {
        workflow["extra"]["comfyui_mcp"]["workflow_uuid"]
        for workflow in (
            t2v_normal, t2v_studio, i2v_normal, i2v_studio, fl2v_normal,
            ref2v_basic, ref2v_tagged, ref2v_studio, ref2v_source_audio,
            sequential, masked_inpaint, masked_ref_inpaint,
            masked_single_extension,
            masked_chain_extension, masked_bridge, deferred_upscale,
            deferred_derope, seedvr2_full_chain)
    }
    assert len(uuids) == 18

    asset = EXAMPLES / "assets" / "jigen_market_garden_doom_opening.png"
    assert asset.is_file()
    assert hashlib.sha256(asset.read_bytes()).hexdigest() == I2V_ASSET_SHA256
    last_asset = EXAMPLES / "assets" / "jigen_market_garden_doom_last.png"
    assert last_asset.is_file()
    assert hashlib.sha256(last_asset.read_bytes()).hexdigest() == (
        FL2V_LAST_ASSET_SHA256)
    crab_video = (
        EXAMPLES / "assets" / "soldier_crabs_bribie_island_cc0.webm")
    assert crab_video.is_file()
    assert hashlib.sha256(crab_video.read_bytes()).hexdigest() == (
        CRAB_VIDEO_SHA256)
    crab_image = EXAMPLES / "assets" / "soldier_crabs_reference_cc0.png"
    assert crab_image.is_file()
    assert hashlib.sha256(crab_image.read_bytes()).hexdigest() == (
        CRAB_IMAGE_SHA256)
    crab_mask = EXAMPLES / "assets" / "soldier_crabs_inpaint_mask.png"
    assert crab_mask.is_file()
    assert hashlib.sha256(crab_mask.read_bytes()).hexdigest() == (
        CRAB_MASK_SHA256)
    print("H3 workflow catalog: T2VA, I2VA, indexed A-B-A FL2VA, Basic / "
          "Tagged / Studio Tagged / source-timeline audio Ref2VA, "
          "experimental sequential-motion Ref2VA, masked video inpaint, "
          "picture-conditioned masked Ref2VA inpaint, "
          "looped masked AV extension, two-ended masked AV bridge, and "
          "deferred LBH 3D H3, chain-aware MAINodes de-rope, and "
          "whole-chain SeedVR2; "
          "valid links, bundled "
          "assets, timeline wiring, six-section prompts, restoration, and "
          "attribution pass")


if __name__ == "__main__":
    main()
