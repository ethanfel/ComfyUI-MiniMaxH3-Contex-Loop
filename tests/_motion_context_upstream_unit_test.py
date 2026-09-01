#!/usr/bin/env python3
"""Standalone tests for transparent upstream Motion Context delegation."""

import importlib.util
import pathlib
import sys
import types


ROOT = pathlib.Path(__file__).resolve().parents[1]
PACKAGE = "h3_motion_context_upstream_unit"

package = types.ModuleType(PACKAGE)
package.__path__ = [str(ROOT)]
sys.modules[PACKAGE] = package

shared_nodes = types.ModuleType(PACKAGE + ".nodes")
shared_nodes.FRAME_RESCALE = 5.0 / 3.0
shared_nodes._pixel_frames = lambda _steps: 100
shared_nodes._video_from_latent = lambda _latent: types.SimpleNamespace(
    shape=(1, 16, 30, 2, 2))
shared_nodes._audio_tail_from_latent = lambda _latent, _frames: (
    "tail", 37, -1.0 / 3.0)
shared_nodes.payload_merge_calls = []


def ensure_payload_merge(**requirements):
    shared_nodes.payload_merge_calls.append(requirements)
    return "test native payload verified"


shared_nodes._ensure_native_payload_merge = ensure_payload_merge
sys.modules[shared_nodes.__name__] = shared_nodes

spec = importlib.util.spec_from_file_location(
    PACKAGE + ".motion_context_upstream",
    ROOT / "motion_context_upstream.py")
adapter = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = adapter
spec.loader.exec_module(adapter)


class Frames:
    def __init__(self, count):
        self.shape = (count, 8, 8, 3)


class UpstreamMotionContext:
    calls = []
    fail_audio_merge = False
    FUNCTION = "apply"

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                name: ("ANY", {}) for name in (
                    "conditioning", "vae", "latent", "context_frames",
                    "context_length", "encode_mode", "anchor_mode", "crop",
                    "audio_context_length", "audio_mode", "target_start")
            },
            "optional": {
                "context_latent": ("LATENT", {}),
                "audio_vae": ("VAE", {}),
                "context_audio": ("AUDIO", {}),
            },
        }

    def apply(self, **kwargs):
        type(self).calls.append(kwargs)
        if type(self).fail_audio_merge:
            raise RuntimeError(
                "h3_motion_context: this graph requires native MiniMax H3 "
                "guide/MultiRef support from ComfyUI PR #15439, but the live "
                "runtime is missing native_keyframe_ref_audio_merge."
            )
        existing = list(kwargs["conditioning"][0][1].get(
            "minimax_keyframes", []))
        visual = {
            "resolved_frame_index": 0,
            "latent": "upstream-visual",
        }
        if kwargs.get("context_latent") is not None:
            visual["audio_latent"] = "upstream-audio"
        existing.append(visual)
        metadata = kwargs["conditioning"][0][1].copy()
        metadata["minimax_keyframes"] = existing
        return ([[kwargs["conditioning"][0][0], metadata]],
                int(kwargs["context_length"]))


class FallbackMotionContext:
    calls = []

    def apply(self, **kwargs):
        type(self).calls.append(kwargs)
        return ("fallback-conditioning", int(kwargs["context_length"]))


def apply(**overrides):
    values = {
        "conditioning": [["embedding", {}]],
        "vae": "video-vae",
        "latent": "target-latent",
        "context_frames": Frames(22),
        "context_length": 22,
        "encode_mode": "video",
        "anchor_mode": "head",
        "crop": "disabled",
        "audio_context_length": 0,
        "audio_mode": "timeline",
        "context_latent": None,
        "audio_vae": None,
        "context_audio": None,
        "video_context_latent": None,
    }
    values.update(overrides)
    return adapter.apply_motion_context(FallbackMotionContext, **values)


def main():
    original_nodes = sys.modules.get("nodes")
    comfy_nodes = types.ModuleType("nodes")
    comfy_nodes.NODE_CLASS_MAPPINGS = {
        adapter.UPSTREAM_NODE_ID: UpstreamMotionContext,
    }
    sys.modules["nodes"] = comfy_nodes
    original_native = adapter._native_guides_available
    adapter._native_guides_available = lambda: True
    try:
        # Normal Guide scenes delegate. The adapter arbitrates an incoming
        # first-frame collision and restores Loop-private output metadata.
        conditioning = [["embedding", {
            "minimax_keyframes": [
                {"resolved_frame_index": 0, "latent": "first"},
                {"resolved_frame_index": 70, "latent": "last"},
            ],
            "minimax_frame_count": 100,
        }]]
        output, trim = apply(conditioning=conditioning)
        assert trim == 22
        assert not FallbackMotionContext.calls
        assert len(UpstreamMotionContext.calls) == 1
        delegated = UpstreamMotionContext.calls[-1]
        assert delegated["target_start"] == 0
        assert [value["resolved_frame_index"] for value in
                delegated["conditioning"][0][1]["minimax_keyframes"]] == [70]
        metadata = output[0][1]
        assert [value["resolved_frame_index"] for value in
                metadata["minimax_keyframes"]] == [70, 0]
        assert metadata["minimax_keyframes"][-1][
            "h3_chain_context_visual"] is True
        assert conditioning[0][1]["minimax_keyframes"][0]["latent"] == "first"

        # The upstream latent-audio slice is retained, while the adapter
        # restores the signed H3 grid position without moving its visual Guide.
        output, _trim = apply(context_latent="previous-av-latent")
        keyframes = output[0][1]["minimax_keyframes"]
        assert len(keyframes) == 2
        assert keyframes[0]["resolved_frame_index"] == 0
        assert "audio_latent" not in keyframes[0]
        assert keyframes[0]["h3_chain_context_visual"] is True
        assert abs(keyframes[1]["resolved_frame_index"] + 0.4) < 1e-9
        assert keyframes[1]["audio_latent"] == "upstream-audio"

        # Provider versions predating their own compatibility guard must not
        # bypass Chain's live payload verification. Ref-mode audio adds a
        # keyframe payload that must merge with Ref2VA video; visual-only
        # Ref2VA needs video merge; timeline carry needs both payload merges.
        apply(context_latent="previous-av-latent", audio_mode="ref")
        assert shared_nodes.payload_merge_calls[-1] == {
            "require_video": True, "require_audio": False}
        ref_conditioning = [["embedding", {
            "minimax_refs": [{"kind": "image", "latent": "reference"}],
        }]]
        apply(conditioning=ref_conditioning)
        assert shared_nodes.payload_merge_calls[-1] == {
            "require_video": True, "require_audio": False}
        apply(
            conditioning=ref_conditioning,
            context_latent="previous-av-latent")
        assert shared_nodes.payload_merge_calls[-1] == {
            "require_video": True, "require_audio": True}

        # Loop-only modes remain lossless through the internal engine.
        result = apply(video_context_latent="previous-video-latent")
        assert result == ("fallback-conditioning", 22)
        assert FallbackMotionContext.calls[-1][
            "video_context_latent"] == "previous-video-latent"

        result = apply(
            context_frames=Frames(0), context_length=0,
            audio_context_length=33, context_latent="previous-av-latent")
        assert result == ("fallback-conditioning", 0)

        result = apply(
            audio_context_length=39,
            context_latent="previous-av-latent")
        assert result == ("fallback-conditioning", 22)

        original_repair = adapter._enable_internal_payload_merge
        adapter._enable_internal_payload_merge = lambda: (
            True, "test payload compatibility enabled")
        UpstreamMotionContext.fail_audio_merge = True
        result = apply(context_latent="previous-av-latent")
        assert result == ("fallback-conditioning", 22)
        assert FallbackMotionContext.calls[-1][
            "context_latent"] == "previous-av-latent"
        UpstreamMotionContext.fail_audio_merge = False
        adapter._enable_internal_payload_merge = original_repair

        # Older ComfyUI falls back even when the provider itself is installed.
        adapter._native_guides_available = lambda: False
        result = apply()
        assert result == ("fallback-conditioning", 22)

        # Missing provider is also a safe internal fallback.
        adapter._native_guides_available = lambda: True
        comfy_nodes.NODE_CLASS_MAPPINGS.clear()
        result = apply()
        assert result == ("fallback-conditioning", 22)
    finally:
        adapter._native_guides_available = original_native
        if original_nodes is None:
            sys.modules.pop("nodes", None)
        else:
            sys.modules["nodes"] = original_nodes

    print("upstream Motion Context: transparent delegation and guarded "
          "feature fallbacks passed")


if __name__ == "__main__":
    main()
