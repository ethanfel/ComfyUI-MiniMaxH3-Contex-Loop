#!/usr/bin/env python3
"""CPU regression: base Plan fingerprint resolves a semantic Ref2VA cache."""
import copy
import json
from pathlib import Path
import tempfile
from unittest.mock import patch

from _upscale_chain_unit_test import (
    load_package, folder_paths, torch, av_latent, audio_for_frames)


class VideoVAE:
    def encode(self, images):
        return torch.full((1, 24, 2, images.shape[1] // 16,
                           images.shape[2] // 16), 0.625)


class Clip:
    def tokenize(self, prompt, **kwargs):
        return {"prompt": prompt, "presentation": kwargs.get("minimax_ref_items", [])}

    def encode_from_tokens_scheduled(self, tokens):
        return [[torch.zeros(1, 1, 4), {"tokens": tokens}]]


def main():
    _, chain, upscale = load_package()
    base = "c6d52ece407c8565c7e060d90106ea662eedd551df5fff32a3682169f71ba0d7"
    wrapped = chain._fingerprint({
        "tagged_reference_fingerprint": base,
        "semantic_anchor_mode": "timestamped_video",
        "semantic_anchor_size": "1280",
    })
    assert wrapped == "5f3dccb342fd638217fd17956dea7d22fa9ef3d465a277d1c377ba940af612c9"
    prompt = "@subject stands beside #setting."
    args = (base, 8, 13, prompt, 32, 32, 5)
    picture = torch.ones(1, 32, 32, 3)

    with tempfile.TemporaryDirectory() as temporary:
        folder_paths.output_directory = temporary

        def save_cache(fingerprint, mode="timestamped_video", size="1280",
                       scene=8, scene_count=13):
            chain._cache_reference_scene(
                fingerprint=fingerprint, scene=scene, scene_count=scene_count,
                prompt=prompt, compiled_prompt="<Picture 1> beside <Picture 2>.",
                width=32, height=32, length=5, ref_image_size="match",
                vae=VideoVAE(), audio_vae=None, pictures=[picture], videos=[], audios=[],
                semantic_presentation={
                    "version": chain.SEMANTIC_PRESENTATION_VERSION,
                    "width": 32, "height": 32, "length": 5,
                    "semantic_anchor_mode": mode, "semantic_anchor_size": size,
                    "pictures": [picture],
                    "anchors": [{"tag": "setting", "untimed": True, "image": picture}],
                })

        save_cache(wrapped)
        root = Path(chain._reference_cache_paths(base, 8, "lookup")["root"])
        assert not root.exists(), "reported bug has no base-fingerprint directory"
        cached = chain._find_reference_cache(*args)
        assert cached is not None, "semantic-wrapped cache must match its base fingerprint"
        assert cached["reference_fingerprint"] == wrapped
        descriptor = chain._reference_cache_descriptor(cached)
        assert chain._load_reference_cache_descriptor(descriptor) == cached
        assert chain._find_reference_cache(wrapped, *args[1:]) == cached

        # Still find it when an unrelated scene has already created the base root.
        root.mkdir()
        (root / "scene_0001.unrelated.json").write_text("{}")
        assert chain._find_reference_cache(*args) == cached
        for index, replacement in enumerate(("wrong-catalog", 9, 12, "changed prompt", 64, 64, 22)):
            changed = list(args)
            changed[index] = replacement
            assert chain._find_reference_cache(*changed) is None, changed
        assert chain._find_reference_cache("", *args[1:]) is None

        # Chapter-only output preserves scene 8 / original scene count 13.
        state = {"index": 8, "source_manifest": {
            "run_name": "semantic_cache_test", "source_scene_count": 13,
            "chapter": {"start_scene": 8, "end_scene": 8},
            "compatibility": {"generation_fingerprint": "other-chapter", "width": 64, "height": 64},
            "segments": [{"index": 8, "generation_fingerprint": base,
                          "prompt": prompt, "raw_frames": 5,
                          "resolution": {"width": 32, "height": 32}}],
        }}
        original = copy.deepcopy(state)
        before = {p: p.read_bytes() for p in Path(temporary).rglob("*") if p.is_file()}
        target = torch.zeros(5, 64, 64, 3)
        node = upscale.MiniMaxH3ChainUpscalePixelConditioning()
        restored = node.condition(state, Clip(), target, VideoVAE(), missing_cache="error")
        assert restored[5] is True and "restored Ref2VA cache" in restored[-1]
        assert len(restored[0][0][1]["minimax_refs"]) == 1
        assert len(restored[0][0][1]["tokens"]["presentation"]) == 2
        assert state == original
        assert before == {p: p.read_bytes() for p in Path(temporary).rglob("*") if p.is_file()}

        # The new discovery path must not bypass the existing tensor integrity check.
        with patch.object(chain, "_file_sha256", return_value="corrupt"):
            try:
                node.condition(state, Clip(), target, VideoVAE(), missing_cache="error")
            except ValueError as exc:
                assert "SHA-256" in str(exc) or "integrity" in str(exc), str(exc)
            else:
                raise AssertionError("corrupt cache was accepted")

        # Malformed JSON / contracts and foreign fingerprints must not be accepted.
        metadata_path = Path(chain._absolute_output_path(cached["metadata"]))
        for mutation in ({"scene": None}, {"reference_fingerprint": base},
                         {"presentation_contract": None},
                         {"presentation_contract": {"semantic_anchor_size": "512",
                                                    "semantic_anchor_mode": "timestamped_video"}}):
            chain._atomic_json(str(metadata_path), {**cached, **mutation})
            assert chain._find_reference_cache(*args) is None
        metadata_path.write_text("[]")
        assert chain._find_reference_cache(*args) is None
        chain._atomic_json(str(metadata_path), cached)

        # More than one semantic recipe cannot be guessed from the base fingerprint.
        alternate = chain._fingerprint({"tagged_reference_fingerprint": base,
                                       "semantic_anchor_mode": "picture_storyboard",
                                       "semantic_anchor_size": "source"})
        save_cache(alternate, "picture_storyboard", "source")
        try:
            chain._find_reference_cache(*args)
        except ValueError as exc:
            assert "different semantic-anchor settings" in str(exc), str(exc)
        else:
            raise AssertionError("ambiguous semantic recipes must not be chosen by mtime")
        assert chain._find_reference_cache(wrapped, *args[1:]) == cached

        # Segment Save's run-local adoption can pin the resolved object unchanged.
        adopted = chain._adopt_reference_cache_for_run(
            {"run_name": "semantic_cache_test", "shots": [{}] * 13}, cached)
        assert adopted["reference_fingerprint"] == wrapped
        assert adopted["tensors_sha256"] == cached["tensors_sha256"]
        pinned = copy.deepcopy(state)
        pinned["source_manifest"]["segments"][0]["reference_cache"] = chain._reference_cache_descriptor(adopted)
        assert node.condition(pinned, Clip(), target, VideoVAE(), missing_cache="error")[5] is True

        # An exact fingerprint match remains preferred, including legacy V1 caches.
        save_cache(base)
        exact = chain._find_reference_cache(*args)
        assert exact["reference_fingerprint"] == base
        exact["format"] = "h3_reference_cache_v1"
        chain._atomic_json(chain._absolute_output_path(exact["metadata"]), exact)
        assert chain._find_reference_cache(*args)["format"] == "h3_reference_cache_v1"

        # Future Segment Save must discover and pin the wrapped cache too.
        plan = chain.MiniMaxH3ChainPlan().build(
            json.dumps({"shots": [{"id": "saved_scene", "prompt": prompt,
                                   "length": 5, "steps": 2, "seed": "7"}]}),
            "semantic_saved", base, 32, 32, 1, "video", "head", "disabled",
            "generated_audio", 1, 5 / 24, 2, 7, 18, 0, "guide")[0]
        plan = chain._plan_with_source_audio(chain._plan_with_external_context(plan, None), None)
        save_cache(wrapped, scene=1, scene_count=1)
        save_state = chain._initial_state(plan, 1)

        def save_segment():
            return chain.MiniMaxH3ChainSegmentSave().save(
                save_state, torch.zeros(5, 32, 32, 3), av_latent(0.25),
                audio_for_frames(5), denoised_latent=av_latent(0.75))["result"][0]

        segment = save_segment()
        assert segment["reference_cache"]["reference_fingerprint"] == wrapped
        assert segment["reference_cache"]["metadata"].startswith(
            "h3_chains/semantic_saved/reference_cache/")
        chain._load_reference_cache_descriptor(segment["reference_cache"])
        # An ambiguous cache must not prevent saving the generated video itself.
        save_cache(alternate, "picture_storyboard", "source", scene=1, scene_count=1)
        with patch.object(chain._LOG, "warning") as warning:
            assert "reference_cache" not in save_segment()
            assert "different semantic-anchor settings" in str(warning.call_args)

    print("Reference-cache fingerprint lookup: semantic fallback, chapter pixel restore, "
          "strict identity/integrity, ambiguity, exact pins and run-local adoption pass")


if __name__ == "__main__":
    main()
