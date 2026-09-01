"""Merged PR #15439 compatibility: core-owned AV guides with Ref2VA.

The fake layout mirrors the new frame_count-free API closely enough to prove:
  * this pack does not wrap PackedLayout on updated ComfyUI;
  * payload monkey-patching is skipped;
  * one video guide and one start-anchored audio guide carry the continuation;
  * Ref2VA refs remain in place and core merges both payload families;
  * core aligns every guide to the target origin after reference blocks.
"""

import importlib.util
import os
import sys
import types

import numpy as np


_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
_PKG_DIR = os.path.dirname(_TESTS_DIR)
sys.path.insert(0, _TESTS_DIR)
from _mock_harness import (  # noqa: E402
    install_structural_solattn,
    make_torch,
)


FRAME_RESCALE = 5.0 / 3.0
FRAME_PER_TOKEN = (1, 4, 4, 4, 4)


class Array(np.ndarray):
    def clone(self):
        return self.copy().view(Array)


def _array(value):
    return np.asarray(value, dtype=np.float64).view(Array)


class T:
    def __init__(self, value):
        self.a = np.asarray(value)

    @property
    def shape(self):
        return self.a.shape

    @property
    def ndim(self):
        return self.a.ndim

    def __getitem__(self, index):
        return T(self.a[index])

    def movedim(self, source, destination):
        return T(np.moveaxis(self.a, source, destination))

    def unsqueeze(self, dimension):
        return T(np.expand_dims(self.a, dimension))

    def clone(self):
        return T(self.a.copy())


class Nested:
    def __init__(self, parts):
        self.parts = parts

    def unbind(self):
        return list(self.parts)


def _video_frames(latent_t):
    return sum(FRAME_PER_TOKEN[index % 5] for index in range(latent_t))


def _video_span(latent_t):
    return FRAME_RESCALE * _video_frames(latent_t)


def _native_model_module():
    module = types.ModuleType("comfy.ldm.minimax.model")
    module.FRAME_RESCALE = FRAME_RESCALE
    module.FRAME_PER_TOKEN = FRAME_PER_TOKEN
    module._video_t_spans = lambda latent_t: [
        FRAME_RESCALE * FRAME_PER_TOKEN[index % 5]
        for index in range(latent_t)
    ]

    class PackedLayout:
        def __init__(self, text_len, latent_t, latent_h, latent_w, audio_t,
                     keyframes=None, refs=None):
            segments = [("text", text_len)]
            blocks = [np.column_stack((
                np.arange(text_len, dtype=np.float64),
                np.zeros((text_len, 2), dtype=np.float64),
            ))]
            target_origin = float(text_len)
            for ref in refs or []:
                kind = ref["kind"]
                if kind == "image":
                    target_origin += 1.0
                elif kind == "audio":
                    target_origin += float(ref.get("ref_audio_t", 0))
                elif kind in ("video", "video_audio"):
                    target_origin += max(
                        float(ref.get("ref_audio_t", 0)),
                        _video_span(int(ref["latent_t"])))

            for keyframe in keyframes or []:
                start = (target_origin + FRAME_RESCALE
                         * float(keyframe["resolved_frame_index"]))
                video = keyframe.get("latent")
                if video is not None:
                    count = int(video.shape[2])
                    segments.append(("cond", count))
                    times = [start + sum(module._video_t_spans(index))
                             for index in range(count)]
                    blocks.append(np.column_stack((
                        times, np.zeros((count, 2), dtype=np.float64))))
                audio = keyframe.get("audio_latent")
                if audio is not None:
                    steps = int(audio.shape[-1])
                    segments.append(("cond_audio", steps * 2))
                    times = np.tile(np.arange(steps, dtype=np.float64), 2) + start
                    blocks.append(np.column_stack((
                        times, np.zeros((steps * 2, 2), dtype=np.float64))))

            cursor = float(text_len)
            for ref in refs or []:
                kind = ref["kind"]
                if kind == "image":
                    segments.append(("ref_img", 1))
                    blocks.append(np.array([[cursor, 0.0, 0.0]]))
                    cursor += 1.0
                elif kind == "audio":
                    steps = int(ref.get("ref_audio_t", 0))
                    if steps:
                        segments.append(("ref_audio", steps * 2))
                        times = np.tile(np.arange(steps), 2) + cursor
                        blocks.append(np.column_stack((
                            times, np.zeros((steps * 2, 2)))))
                    cursor += steps
                elif kind in ("video", "video_audio"):
                    steps = int(ref.get("ref_audio_t", 0))
                    if steps:
                        segments.append(("ref_audio", steps * 2))
                        times = np.tile(np.arange(steps), 2) + cursor
                        blocks.append(np.column_stack((
                            times, np.zeros((steps * 2, 2)))))
                    video_t = int(ref["latent_t"])
                    segments.append(("ref_img", video_t))
                    blocks.append(np.column_stack((
                        [cursor + sum(module._video_t_spans(index))
                         for index in range(video_t)],
                        np.zeros((video_t, 2)),
                    )))
                    cursor += max(float(steps), _video_span(video_t))

            segments.append(("audio", audio_t * 2))
            blocks.append(np.column_stack((
                np.tile(np.arange(audio_t), 2) + cursor,
                np.zeros((audio_t * 2, 2)),
            )))
            segments.append(("video", latent_t))
            blocks.append(np.column_stack((
                [cursor + sum(module._video_t_spans(index))
                 for index in range(latent_t)],
                np.zeros((latent_t, 2)),
            )))

            absolute = []
            offset = 0
            for kind, count in segments:
                absolute.append((offset, offset + count, kind))
                offset += count
            self.segments = absolute
            self.position_ids = _array(np.concatenate(blocks))

    module.PackedLayout = PackedLayout
    return module


def main():
    mm = _native_model_module()
    stock_layout_init = mm.PackedLayout.__init__
    for name in ("comfy", "comfy.ldm", "comfy.ldm.minimax"):
        sys.modules[name] = types.ModuleType(name)
    sys.modules["comfy.ldm.minimax.model"] = mm
    sys.modules["comfy"].ldm = sys.modules["comfy.ldm"]
    sys.modules["comfy.ldm"].minimax = sys.modules["comfy.ldm.minimax"]
    sys.modules["comfy.ldm.minimax"].model = mm
    sys.modules["torch"] = make_torch()

    utils = types.ModuleType("comfy.utils")
    utils.common_upscale = lambda samples, width, height, method, crop: T(
        np.zeros((samples.shape[0], 3, height, width), dtype=np.float32))
    sys.modules["comfy.utils"] = utils
    sys.modules["comfy"].utils = utils

    model_base = types.ModuleType("comfy.model_base")

    class MiniMaxH3:
        def extra_conds(self, **kwargs):
            keyframes = kwargs.get("minimax_keyframes") or []
            refs = kwargs.get("minimax_refs") or []
            payload = {
                "cond_video_latents": [
                    item["latent"] for item in keyframes
                    if item.get("latent") is not None
                ] + [item["latent"] for item in refs if "latent" in item],
                "cond_audio_latents": [
                    item["audio_latent"] for item in keyframes
                    if item.get("audio_latent") is not None
                ] + [item["audio_latent"] for item in refs
                     if item.get("audio_latent") is not None],
            }
            return {"minimax_payload": types.SimpleNamespace(cond=payload)}

    model_base.MiniMaxH3 = MiniMaxH3
    sys.modules["comfy.model_base"] = model_base
    sys.modules["comfy"].model_base = model_base

    captured = {}
    helpers = types.ModuleType("node_helpers")

    def conditioning_set_values(conditioning, values, append=False):
        output = []
        for value, metadata in conditioning:
            metadata = metadata.copy()
            for key, incoming in values.items():
                if append and metadata.get(key) is not None:
                    incoming = metadata[key] + incoming
                metadata[key] = incoming
            output.append([value, metadata])
        captured.clear()
        captured.update(output[0][1])
        return output

    helpers.conditioning_set_values = conditioning_set_values
    sys.modules["node_helpers"] = helpers

    folder_paths = types.ModuleType("folder_paths")
    folder_paths.get_output_directory = lambda: "/tmp"
    sys.modules["folder_paths"] = folder_paths

    safetensors = types.ModuleType("safetensors")
    safetensors_torch = types.ModuleType("safetensors.torch")
    safetensors_torch.load_file = safetensors_torch.save_file = None
    safetensors.torch = safetensors_torch
    sys.modules["safetensors"] = safetensors
    sys.modules["safetensors.torch"] = safetensors_torch

    package = types.ModuleType("h3_native_pkg")
    package.__path__ = [_PKG_DIR]
    sys.modules[package.__name__] = package
    spec = importlib.util.spec_from_file_location(
        package.__name__ + ".nodes", os.path.join(_PKG_DIR, "nodes.py"))
    nodes = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = nodes
    spec.loader.exec_module(nodes)
    layout_patch = sys.modules[package.__name__ + ".patch_layout"]
    payload_patch = sys.modules[package.__name__ + ".patch_payload"]

    latent_t, frame_count, audio_t = 37, 124, 207
    assert _video_frames(latent_t) == frame_count
    height, width = 30, 54
    target = {"samples": Nested([
        T(np.zeros((1, 16, latent_t, height, width))),
        T(np.zeros((1, 32, 2, audio_t))),
    ])}
    previous = {"samples": Nested([
        T(np.zeros((1, 16, latent_t, height, width))),
        T(np.zeros((1, 32, 2, audio_t))),
    ])}
    context = T(np.zeros((124, 480, 864, 3)))

    class VAE:
        def encode(self, images):
            count = int(images.shape[0])
            steps = max(1, (count - 5) // 17 * 5 + 2)
            return T(np.zeros((1, 16, steps, height, width)))

    refs = [
        {"kind": "image", "latent_h": height, "latent_w": width,
         "latent": T(np.zeros((1, 16, 1, height, width)))},
        {"kind": "audio", "ref_audio_t": 3,
         "audio_latent": T(np.zeros((1, 32, 2, 3)))},
    ]
    scene_one_input = [["conditioning", {"minimax_refs": refs}]]
    scene_one = nodes._prepare_native_guide_conditioning(scene_one_input)
    assert scene_one is scene_one_input
    assert "minimax_keyframes" not in scene_one[0][1]
    scene_one_keyframes = [{
        "resolved_frame_index": 60,
        "latent": T(np.zeros((1, 16, 1, height, width))),
    }]
    scene_one_layout = mm.PackedLayout(
        7, latent_t, height, width, audio_t,
        keyframes=scene_one_keyframes, refs=refs)
    scene_one_origin = layout_patch._target_origin(scene_one_layout)
    scene_one_cond = next(
        start for start, _stop, kind in scene_one_layout.segments
        if kind == "cond")
    assert abs(float(scene_one_layout.position_ids[scene_one_cond, 0])
               - (scene_one_origin + FRAME_RESCALE * 60)) < 1e-9

    output, trim = nodes.MiniMaxH3MotionContext().apply(
        conditioning=[["conditioning", {"minimax_refs": refs}]],
        vae=VAE(), latent=target, context_frames=context, context_length=22,
        encode_mode="video", anchor_mode="head", crop="disabled",
        audio_context_length=22, audio_mode="timeline",
        context_latent=previous, visual_cond_noise_aug=0.0,
    )

    assert trim == 22
    assert layout_patch.native_guides_available()
    assert not layout_patch.is_applied()
    assert mm.PackedLayout.__init__ is stock_layout_init
    assert not payload_patch.is_applied()
    priority_status = nodes._claim_inline_patch_ownership()
    assert priority_status == (
        "native guides; core-owned; no compatibility patch required")
    assert mm.PackedLayout.__init__ is stock_layout_init
    output_metadata = output[0][1]
    assert output_metadata["minimax_visual_cond_noise_aug"] == 0.0
    assert "minimax_frame_count" not in output_metadata
    assert output_metadata["minimax_refs"] == refs
    keyframes = output_metadata["minimax_keyframes"]
    assert len(keyframes) == 2
    assert all(nodes.MC_KEY not in value for value in keyframes)
    assert keyframes[0]["resolved_frame_index"] == 0
    assert tuple(keyframes[0]["latent"].shape)[2] == 7
    assert keyframes[0]["h3_chain_context_visual"] is True
    assert keyframes[1].get("latent") is None
    assert "h3_chain_context_visual" not in keyframes[1]
    assert tuple(keyframes[1]["audio_latent"].shape)[-1] == 37
    assert abs(keyframes[1]["resolved_frame_index"]) < 1e-6

    suffix_output, suffix_trim = nodes.MiniMaxH3MotionContext().apply(
        conditioning=[["conditioning", {"minimax_refs": refs}]],
        vae=VAE(), latent=target, context_frames=context, context_length=22,
        encode_mode="video", anchor_mode="head", crop="disabled",
        audio_context_length=0, future_end_anchor=True,
    )
    assert suffix_trim == 22
    suffix_keyframes = suffix_output[0][1]["minimax_keyframes"]
    assert len(suffix_keyframes) == 2
    assert suffix_keyframes[0]["resolved_frame_index"] == 0
    assert suffix_keyframes[0]["h3_chain_context_visual"] is True
    assert suffix_keyframes[1]["resolved_frame_index"] == frame_count
    assert tuple(suffix_keyframes[1]["latent"].shape)[2] == 1
    assert suffix_keyframes[1]["h3_chain_future_end_anchor"] is True
    assert "h3_chain_context_visual" not in suffix_keyframes[1]
    assert all(nodes.MC_KEY not in value for value in suffix_keyframes)
    suffix_layout = mm.PackedLayout(
        7, latent_t, height, width, audio_t,
        keyframes=suffix_keyframes, refs=refs)
    suffix_origin = layout_patch._target_origin(suffix_layout)
    suffix_segments = [
        start for start, _stop, kind in suffix_layout.segments
        if kind == "cond"
    ]
    assert len(suffix_segments) == 2
    assert abs(float(suffix_layout.position_ids[suffix_segments[1], 0])
               - (suffix_origin + FRAME_RESCALE * frame_count)) < 1e-9

    # AV continuation keeps its prefix in the sampler target, then appends
    # the same final prepared prefix step as a separate clean suffix Guide.
    # The latent itself remains byte-for-byte untouched by this helper.
    av_target_video = np.zeros(
        (1, 16, latent_t, height, width), dtype=np.float64)
    av_target_video[:, :, 11:12] = 7.0
    av_target = {"samples": Nested([
        T(av_target_video),
        T(np.zeros((1, 32, 2, audio_t))),
    ])}
    av_video_before = av_target["samples"].parts[0].a.copy()
    av_suffix_output = nodes._append_future_end_anchor(
        [["conditioning", {"minimax_refs": refs}]],
        av_target,
        39,
    )
    assert np.array_equal(av_target["samples"].parts[0].a, av_video_before)
    av_suffix_metadata = av_suffix_output[0][1]
    assert av_suffix_metadata["minimax_visual_cond_noise_aug"] == 0.999
    av_suffix = av_suffix_metadata["minimax_keyframes"][0]
    assert av_suffix["resolved_frame_index"] == frame_count
    assert av_suffix["h3_chain_future_end_anchor"] is True
    assert "h3_chain_context_visual" not in av_suffix
    assert tuple(av_suffix["latent"].shape) == (
        1, 16, 1, height, width)
    assert np.all(av_suffix["latent"].a == 7.0)
    assert nodes.MC_KEY not in av_suffix

    # A precomputed boundary registry supplies its own one-step endpoint
    # latent rather than copying the predecessor prefix. It occupies the same
    # post-target Guide position and is explicitly marked for diagnostics.
    explicit_anchor = T(np.full(
        (1, 16, 1, height, width), 11.0, dtype=np.float64))
    explicit_output = nodes._append_explicit_future_end_anchor(
        [["conditioning", {"minimax_refs": refs}]],
        av_target,
        explicit_anchor,
    )
    explicit_suffix = explicit_output[0][1]["minimax_keyframes"][0]
    assert explicit_suffix["resolved_frame_index"] == frame_count
    assert explicit_suffix["h3_chain_future_end_anchor"] is True
    assert explicit_suffix["h3_chain_boundary_anchor"] is True
    assert tuple(explicit_suffix["latent"].shape) == (
        1, 16, 1, height, width)
    assert np.all(explicit_suffix["latent"].a == 11.0)
    assert nodes.MC_KEY not in explicit_suffix

    audio_only_output, audio_only_trim = nodes.MiniMaxH3MotionContext().apply(
        conditioning=[["conditioning", {"minimax_refs": refs}]],
        vae=VAE(), latent=target, context_frames=context[:0], context_length=0,
        encode_mode="video", anchor_mode="head", crop="disabled",
        audio_context_length=33, audio_mode="timeline",
        context_latent=previous,
    )
    assert audio_only_trim == 0
    audio_only_metadata = audio_only_output[0][1]
    assert audio_only_metadata["minimax_refs"] == refs
    assert len(audio_only_metadata["minimax_keyframes"]) == 1
    assert "audio_latent" in audio_only_metadata["minimax_keyframes"][0]
    assert "latent" not in audio_only_metadata["minimax_keyframes"][0]

    first_anchor = T(np.zeros((1, 16, 1, height, width)))
    last_anchor = T(np.zeros((1, 16, 1, height, width)))
    anchored_output, anchored_trim = nodes.MiniMaxH3MotionContext().apply(
        conditioning=[["conditioning", {
            "minimax_refs": refs,
            "minimax_keyframes": [
                {"resolved_frame_index": 0, "latent": first_anchor},
                {"resolved_frame_index": frame_count - 1,
                 "latent": last_anchor},
            ],
            "minimax_frame_count": frame_count,
        }]],
        vae=VAE(), latent=target, context_frames=context, context_length=22,
        encode_mode="video", anchor_mode="head", crop="disabled",
        audio_context_length=22, audio_mode="timeline",
        context_latent=previous,
    )
    anchored_metadata = anchored_output[0][1]
    anchored_keyframes = anchored_metadata["minimax_keyframes"]
    assert anchored_trim == 22
    assert len(anchored_keyframes) == 3
    assert anchored_keyframes[0]["latent"] is last_anchor
    assert "h3_chain_context_visual" not in anchored_keyframes[0]
    assert anchored_keyframes[0]["resolved_frame_index"] == frame_count - 1
    assert all(nodes.MC_KEY not in value for value in anchored_keyframes)
    assert anchored_keyframes[1]["h3_chain_context_visual"] is True
    assert first_anchor not in [value.get("latent")
                                for value in anchored_keyframes]
    anchored_layout = mm.PackedLayout(
        7, latent_t, height, width, audio_t,
        keyframes=anchored_keyframes, refs=refs)
    anchored_origin = layout_patch._target_origin(anchored_layout)
    anchored_segments = [
        start for start, _stop, kind in anchored_layout.segments
        if kind in ("cond", "cond_audio")]
    assert len(anchored_segments) == len(anchored_keyframes)
    for value, start in zip(anchored_keyframes, anchored_segments):
        expected = (anchored_origin + FRAME_RESCALE
                    * float(value["resolved_frame_index"]))
        assert abs(float(anchored_layout.position_ids[start, 0])
                   - expected) < 1e-9

    # Simulate the official Add Guide node chained after Loop Context.
    keyframes.append({
        "resolved_frame_index": 60,
        "latent": T(np.zeros((1, 16, 1, height, width))),
    })
    layout = mm.PackedLayout(
        7, latent_t, height, width, audio_t,
        keyframes=keyframes, refs=refs)
    target_origin = layout_patch._target_origin(layout)
    guide_segments = [(a, kind) for a, _b, kind in layout.segments
                      if kind in ("cond", "cond_audio")]
    assert len(guide_segments) == 3
    for keyframe, (start, _kind) in zip(keyframes, guide_segments):
        expected = (target_origin + FRAME_RESCALE
                    * float(keyframe["resolved_frame_index"]))
        assert abs(float(layout.position_ids[start, 0]) - expected) < 1e-9

    payload = MiniMaxH3().extra_conds(
        minimax_keyframes=keyframes, minimax_refs=refs,
    )["minimax_payload"].cond
    assert len(payload["cond_video_latents"]) == 3
    assert len(payload["cond_audio_latents"]) == 2
    assert output[0][1]["minimax_refs"] == refs

    # The opt-in stock-reference audio mode remains a reference under the
    # native API. It must append to (not replace) the user's Ref2VA blocks,
    # while the visual continuation still uses a native video guide.
    ref_output, ref_trim = nodes.MiniMaxH3MotionContext().apply(
        conditioning=[["conditioning", {"minimax_refs": refs}]],
        vae=VAE(), latent=target, context_frames=context, context_length=22,
        encode_mode="video", anchor_mode="head", crop="disabled",
        audio_context_length=22, audio_mode="ref",
        context_latent=previous,
    )
    ref_metadata = ref_output[0][1]
    assert ref_trim == 22
    assert len(ref_metadata["minimax_keyframes"]) == 1
    assert len(ref_metadata["minimax_refs"]) == len(refs) + 1
    assert ref_metadata["minimax_refs"][:-1] == refs
    assert ref_metadata["minimax_refs"][-1]["kind"] == "audio"
    ref_payload = MiniMaxH3().extra_conds(
        minimax_keyframes=ref_metadata["minimax_keyframes"],
        minimax_refs=ref_metadata["minimax_refs"],
    )["minimax_payload"].cond
    assert len(ref_payload["cond_video_latents"]) == 2
    assert len(ref_payload["cond_audio_latents"]) == 2

    # Reproduce the real two-run lifecycle: scene 1 establishes that native
    # guides are available, then a PR Kitchen/SolAttn helper lazily installs a
    # process-global observer under an arbitrary custom_nodes folder name.
    # Scene 2 must still see core's constructor through that observer.  A
    # second renamed observer represents duplicate helper checkouts.
    assert layout_patch.native_guides_available()
    observer_a = install_structural_solattn(
        mm,
        r"C:\Comfy\ComfyUI\custom_nodes\sol_attn_minimax_v2",
    )
    first_observer = mm.PackedLayout.__init__
    assert first_observer is not stock_layout_init
    assert layout_patch.native_guides_available()
    assert nodes._activate_inline_patches() == "native"
    observer_b = install_structural_solattn(
        mm,
        "/workspace/custom_nodes/a-user-renamed-sol-attn-copy",
    )
    assert layout_patch.native_guides_available()
    assert layout_patch._already_patched() == "solattn"
    observed_layout = mm.PackedLayout(
        7, latent_t, height, width, audio_t,
        keyframes=scene_one_keyframes, refs=refs)
    assert id(observed_layout.position_ids) in observer_a["_SPANS"]
    assert id(observed_layout.position_ids) in observer_b["_SPANS"]

    # The structural rule is not "has an original_init closure".  A foreign
    # wrapper without the audited span-registration fingerprint still fails
    # closed, even when it captures the recognized observer chain.
    recognized_observer = mm.PackedLayout.__init__

    def install_unknown_wrapper():
        original_init = recognized_observer

        def __init__(self, *args, **kwargs):
            original_init(self, *args, **kwargs)

        __init__.__module__ = "/custom_nodes/unrelated_h3_layout_patch"
        mm.PackedLayout.__init__ = __init__

    install_unknown_wrapper()
    assert not layout_patch.native_guides_available()
    assert layout_patch._already_patched() == "foreign"
    mm.PackedLayout.__init__ = recognized_observer
    assert layout_patch.native_guides_available()

    # Some ComfyUI revisions shipped native arbitrary Guide layout before
    # extra_conds learned to retain Guide audio alongside Ref2VA audio. That
    # produces the real 37-step stereo mismatch: layout reserves 74 more rows
    # than the payload supplies. Internal fallback paths must repair this at
    # Motion Context execution, before the sampler sees the conditioning.
    def partial_native_extra_conds(self, **kwargs):
        keyframes = kwargs.get("minimax_keyframes") or []
        refs_value = kwargs.get("minimax_refs") or []
        payload = {
            "cond_video_latents": [
                item["latent"] for item in keyframes
                if item.get("latent") is not None
            ] + [item["latent"] for item in refs_value if "latent" in item],
            "cond_audio_latents": [
                item["audio_latent"] for item in refs_value
                if item.get("audio_latent") is not None],
        }
        return {"minimax_payload": types.SimpleNamespace(cond=payload)}

    MiniMaxH3.extra_conds = partial_native_extra_conds
    partial_status = payload_patch.native_payload_merge_status()
    assert partial_status["native_keyframe_ref_merge"] is True
    assert partial_status["native_keyframe_ref_audio_merge"] is False
    repaired_output, repaired_trim = nodes.MiniMaxH3MotionContext().apply(
        conditioning=[["conditioning", {"minimax_refs": refs}]],
        vae=VAE(), latent=target, context_frames=context, context_length=22,
        encode_mode="video", anchor_mode="head", crop="disabled",
        audio_context_length=22, audio_mode="timeline",
        context_latent=previous,
    )
    assert repaired_trim == 22
    repaired_metadata = repaired_output[0][1]
    repaired_payload = MiniMaxH3().extra_conds(
        minimax_keyframes=repaired_metadata["minimax_keyframes"],
        minimax_refs=repaired_metadata["minimax_refs"],
    )["minimax_payload"].cond
    assert len(repaired_payload["cond_audio_latents"]) == 2
    assert payload_patch.is_applied()

    print("native guides: core-owned PackedLayout, sentinel-free scene 1, AV "
          "continuation, retained last_frame and chained Add Guide alignment "
          "after Ref2VA; lazy renamed/nested SolAttn observers accepted while "
          "unknown wrappers remain refused; legacy patches skipped")


if __name__ == "__main__":
    main()
