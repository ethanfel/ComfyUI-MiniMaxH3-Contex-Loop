#!/usr/bin/env python3
"""CPU regressions for general MiniMax H3 masked-target nodes."""

import importlib.util
import json
import os
import sys
import types

import torch


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACKAGE = "h3_general_mask_test_pkg"


class NestedTensor:
    def __init__(self, parts):
        self.parts = tuple(parts)
        self.is_nested = True

    def unbind(self):
        return list(self.parts)


def _load(name):
    path = os.path.join(ROOT, "%s.py" % name)
    spec = importlib.util.spec_from_file_location(
        "%s.%s" % (PACKAGE, name), path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def main():
    package = types.ModuleType(PACKAGE)
    package.__path__ = [ROOT]
    sys.modules[PACKAGE] = package

    comfy = types.ModuleType("comfy")
    comfy.__path__ = []
    nested = types.ModuleType("comfy.nested_tensor")
    nested.NestedTensor = NestedTensor
    comfy.nested_tensor = nested
    sys.modules["comfy"] = comfy
    sys.modules["comfy.nested_tensor"] = nested

    ops = _load("masking_ops")
    _load("masking_support")
    nodes = _load("masking_nodes")
    support_calls = []
    nodes.require_h3_mask_support = lambda operation: support_calls.append(
        operation)

    assert ops.floor_h3_frame_count(140) == 124
    assert ops.h3_pixel_frames_for_video_latents(1) == 1
    assert ops.h3_pixel_frames_for_video_latents(2) == 5
    assert ops.h3_pixel_frames_for_video_latents(7) == 22
    assert ops.h3_pixel_frames_for_video_latents(12) == 39
    assert ops.h3_pixel_frames_for_video_latents(102) == 345
    assert ops.h3_video_latents_for_pixel_frames(1) == 1
    assert ops.h3_video_latents_for_pixel_frames(5) == 2
    assert ops.h3_video_latents_for_pixel_frames(22) == 7
    assert ops.h3_video_latent_frame_groups(7) == (
        (0, 1), (1, 5), (5, 9), (9, 13),
        (13, 17), (17, 18), (18, 22),
    )
    frames = torch.zeros((140, 32, 64, 3))
    audio = {
        "waveform": torch.zeros((1, 2, 300_000)),
        "sample_rate": 48_000,
    }
    trimmed_frames, trimmed_audio, length, info = (
        nodes.MiniMaxH3ContexTrimSourceAV().trim(frames, audio))
    assert trimmed_frames.shape[0] == 124
    assert trimmed_audio["waveform"].shape[-1] == 248_000
    assert length == 124 and "dropped 16" in info

    pixel_mask = torch.zeros((1, 64, 64))
    pixel_mask[:, :16, :16] = 1.0
    _raw, snapped, cells = ops.quantize_h3_pixel_mask(
        pixel_mask, 1, 64, 64)
    assert cells[0, 0].tolist() == [[1.0, 0.0], [0.0, 0.0]]
    assert torch.all(snapped[:, :32, :32] == 1.0)

    moving_preview_mask = torch.zeros((5, 64, 64))
    moving_preview_mask[4, 0, 0] = 1.0
    _raw, causal_preview, _cells = ops.quantize_h3_pixel_mask(
        moving_preview_mask, 5, 64, 64)
    assert not torch.count_nonzero(causal_preview[0])
    assert torch.all(causal_preview[1:, :32, :32] == 1.0)
    assert not torch.count_nonzero(causal_preview[1:, 32:, :])

    video = torch.zeros((1, 16, 2, 4, 4))
    source_audio = torch.zeros((1, 32, 2, 6))
    target = {"samples": NestedTensor((video, source_audio))}
    edit_mask = torch.zeros((1, 64, 64))
    edit_mask[:, :32, :32] = 1.0
    masked, mask_info = nodes.MiniMaxH3ContexMaskedTarget().apply(
        target,
        edit_mask,
        "white = generate",
        "preserve source audio",
    )
    video_mask, audio_mask = masked["noise_mask"].unbind()
    assert video_mask.shape == (1, 1, 2, 4, 4)
    assert audio_mask.shape == (1, 1, 2, 6)
    assert torch.all(video_mask[..., :2, :2] == 1.0)
    assert torch.all(video_mask[..., 2:, :] == 0.0)
    assert not torch.count_nonzero(audio_mask)
    assert "existing mask none" in mask_info
    assert support_calls == ["general masked-target generation"]
    assert "H3 exact causal/token max" in mask_info

    tracked = torch.zeros((22, 64, 64))
    tracked[4, 0, 0] = 1.0
    tracked[5, -1, -1] = 0.5
    tracked[21, 0, -1] = 1.0
    exact_video = torch.zeros((1, 16, 7, 4, 4))
    exact = ops.reduce_h3_mask_to_video_latent(tracked, exact_video)
    assert exact.shape == (1, 1, 7, 4, 4)
    assert not torch.count_nonzero(exact[:, :, 0])
    assert torch.all(exact[:, :, 1, :2, :2] == 1.0)
    assert torch.all(exact[:, :, 2, 2:, 2:] == 0.5)
    assert not torch.count_nonzero(exact[:, :, 3:6])
    assert torch.all(exact[:, :, 6, :2, 2:] == 1.0)

    static = ops.reduce_h3_mask_to_video_latent(
        torch.ones((1, 64, 64)), exact_video)
    assert torch.all(static == 1.0)
    try:
        ops.reduce_h3_mask_to_video_latent(
            torch.ones((21, 64, 64)), exact_video)
    except ValueError as exc:
        assert "exactly 22 tracked masks" in str(exc)
        assert "Loop Mask Slice" in str(exc)
    else:
        raise AssertionError("off-grid tracked mask batch was accepted")
    legacy = ops.resize_mask_to_video_latent(
        torch.stack((torch.zeros((8, 8)), torch.ones((8, 8)))),
        exact_video,
    )
    assert legacy.shape == (1, 1, 7, 4, 4)
    legacy_target, legacy_info = nodes.MiniMaxH3ContexMaskedTarget().apply(
        target,
        torch.stack((torch.zeros((8, 8)), torch.ones((8, 8)))),
        "white = generate",
        "preserve source audio",
        mask_conversion="legacy trilinear",
    )
    assert legacy_target["noise_mask"].unbind()[0].shape == (
        1, 1, 2, 4, 4)
    assert "mask legacy trilinear" in legacy_info

    old_video_mask = torch.ones((1, 1, 2, 4, 4))
    old_video_mask[:, :, :1] = 0.0
    old_audio_mask = torch.ones((1, 1, 2, 6))
    old_audio_mask[..., :2] = 0.0
    prefixed = {
        "samples": target["samples"],
        "noise_mask": NestedTensor((old_video_mask, old_audio_mask)),
    }
    combined, combined_info = nodes.MiniMaxH3ContexMaskedTarget().apply(
        prefixed,
        torch.ones((1, 64, 64)),
        "white = generate",
        "generate all audio",
    )
    combined_video, combined_audio = combined["noise_mask"].unbind()
    assert not torch.count_nonzero(combined_video[:, :, :1])
    assert torch.all(combined_video[:, :, 1:] == 1.0)
    assert not torch.count_nonzero(combined_audio[..., :2])
    assert torch.all(combined_audio[..., 2:] == 1.0)
    assert "existing mask intersected" in combined_info

    temporal = torch.cat((
        torch.zeros((1, 8, 8)),
        torch.ones((4, 8, 8)),
    ))
    followed, _ = nodes.MiniMaxH3ContexMaskedTarget().apply(
        target,
        temporal,
        "white = generate",
        "follow video mask",
    )
    followed_audio = followed["noise_mask"].unbind()[1]
    assert float(followed_audio[..., 0].max()) == 0.0
    assert float(followed_audio[..., -1].min()) == 1.0

    try:
        nodes.MiniMaxH3ContexMaskedTarget().apply(
            target,
            edit_mask,
            "white = generate",
            "custom audio mask",
        )
    except ValueError as exc:
        assert "requires the optional audio_mask" in str(exc)
    else:
        raise AssertionError("custom audio mode accepted a missing audio mask")

    preview_mask, preview, preview_info = (
        nodes.MiniMaxH3ContexMaskGridPreview().preview(
            torch.zeros((5, 64, 64, 3)),
            edit_mask,
            "runtime exact (latent max)",
            0,
            2,
            0.38,
            True,
            True,
        ))
    assert preview_mask.shape == (5, 64, 64)
    assert preview.shape == (1, 64, 64, 3)
    assert "preview frame 2/4" in preview_info

    preserve_input = torch.ones((5, 64, 64))
    preserve_input[:, :16, :16] = 0.0
    preserve_snapped, _preview, preserve_info = (
        nodes.MiniMaxH3ContexMaskGridPreview().preview(
            torch.zeros((5, 64, 64, 3)),
            preserve_input,
            "runtime exact (latent max)",
            0,
            0,
            0.38,
            False,
            False,
            "white = preserve",
        ))
    assert torch.all(preserve_snapped[:, :32, :32] == 0.0)
    assert torch.all(preserve_snapped[:, 32:, :] == 1.0)
    assert "white = preserve" in preserve_info

    mask_schema = nodes.MiniMaxH3ContexMaskedTarget.INPUT_TYPES()
    conversion = mask_schema["optional"]["mask_conversion"]
    assert conversion[0] == list(ops.MASK_CONVERSION_MODES)
    assert conversion[1]["default"] == ops.MASK_CONVERSION_MODES[0]

    expected_ids = {
        "MiniMaxH3ContexTrimSourceAV",
        "MiniMaxH3ContexMaskedTarget",
        "MiniMaxH3ContexMaskGridPreview",
    }
    assert expected_ids == set(nodes.NODE_CLASS_MAPPINGS)
    old_pack_ids = {
        "MiniMaxH3TrimSourceAV",
        "MiniMaxH3SetGenerationMask",
        "MiniMaxH3MaskGridPreview",
        "MiniMaxH3PerRowMaskPatch",
    }
    assert not old_pack_ids.intersection(nodes.NODE_CLASS_MAPPINGS)

    workflow_path = os.path.join(
        ROOT, "example_workflows", "Masked Video Inpaint - MiniMax H3 0.6.json")
    with open(workflow_path, "r", encoding="utf-8") as handle:
        workflow = json.load(handle)
    workflow_nodes = {item["id"]: item for item in workflow["nodes"]}
    workflow_types = {item["type"] for item in workflow["nodes"]}
    assert {
        "MiniMaxH3ContexMaskedTarget",
        "MiniMaxH3ContexMaskGridPreview",
        "MiniMaxH3ContexLoopSourceAVTarget",
        "MiniMaxH3ContexLoopMaskSlice",
        "MiniMaxH3ChainLoopStart",
        "MiniMaxH3ChainLoopEnd",
    } <= workflow_types
    assert not workflow_types.intersection({
        "LTXVConcatAVLatent", "LTXVSeparateAVLatent"})
    assert not old_pack_ids.intersection(workflow_types)
    seen_links = set()
    for link in workflow["links"]:
        link_id, source_id, source_slot, target_id, target_slot, link_type = link
        assert link_id not in seen_links
        seen_links.add(link_id)
        source = workflow_nodes[source_id]["outputs"][source_slot]
        target_input = workflow_nodes[target_id]["inputs"][target_slot]
        assert link_id in source["links"]
        assert target_input["link"] == link_id
        assert isinstance(link_type, str) and link_type
    assert workflow["last_link_id"] == max(seen_links)
    assert workflow["last_node_id"] == max(workflow_nodes)

    masked_node = next(
        item for item in workflow["nodes"]
        if item["type"] == "MiniMaxH3ContexMaskedTarget")
    sampler = next(
        item for item in workflow["nodes"]
        if item["type"] == "SamplerCustomAdvanced")
    mask_link = next(
        link for link in workflow["links"]
        if link[0] == sampler["inputs"][4]["link"])
    assert mask_link[1:3] == [masked_node["id"], 0]
    source_target = next(
        item for item in workflow["nodes"]
        if item["type"] == "MiniMaxH3ContexLoopSourceAVTarget")
    chain_context = next(
        item for item in workflow["nodes"]
        if item["type"] == "MiniMaxH3ChainContext")
    source_target_link = next(
        link for link in workflow["links"]
        if link[0] == chain_context["inputs"][3]["link"])
    assert source_target_link[1:3] == [source_target["id"], 0]
    masked_source_link = next(
        link for link in workflow["links"]
        if link[0] == masked_node["inputs"][0]["link"])
    assert masked_source_link[1:3] == [chain_context["id"], 3]

    sigma = next(
        item for item in workflow["nodes"]
        if item["type"] == "MiniMaxH3SigmaShift")
    guider = next(
        item for item in workflow["nodes"] if item["type"] == "BasicGuider")
    scheduler = next(
        item for item in workflow["nodes"] if item["type"] == "BasicScheduler")
    links_by_id = {link[0]: link for link in workflow["links"]}

    def model_origin(item):
        link = links_by_id[item["inputs"][0]["link"]]
        source = workflow_nodes[link[1]]
        while source["type"] == "Reroute":
            link = links_by_id[source["inputs"][0]["link"]]
            source = workflow_nodes[link[1]]
        return source["id"], link[2]

    assert model_origin(guider) == (sigma["id"], 0)
    assert model_origin(scheduler) == (sigma["id"], 0)
    print(
        "general H3 masking: AV trim, 32px grid, spatial/temporal masks, "
        "custom audio control, prefix-safe intersection, and synchronized "
        "Chain Loop example wiring pass")


if __name__ == "__main__":
    main()
