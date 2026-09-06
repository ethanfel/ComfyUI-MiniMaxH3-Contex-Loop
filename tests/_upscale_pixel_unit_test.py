#!/usr/bin/env python3
"""CPU pixel-loop integration: real checkpoints/media, fake VAE and CLIP.

Set COMFYUI_PATH when ComfyUI is not adjacent to the checkout. No weights,
external image upscalers, live projects or GPU sampling are used.
"""
import copy
import importlib.util
import json
import os
from pathlib import Path
import sys
import subprocess
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
candidates = [Path(os.environ["COMFYUI_PATH"])] if os.environ.get("COMFYUI_PATH") else []
candidates += [ROOT.parent / "Comfyui", ROOT.parent / "ComfyUI"]
COMFY = next(path for path in candidates if (path / "comfy/options.py").is_file())
sys.path.insert(0, str(COMFY))
sys.argv = ["h3-pixel-test", "--cpu"]
import comfy.options
comfy.options.enable_args_parsing()
import folder_paths
import torch


def fails(call, text):
    try:
        call()
    except ValueError as exc:
        assert text in str(exc), str(exc)
    else:
        raise AssertionError("Expected failure: " + text)


class VideoVAE:
    def decode(self, video):
        assert video.ndim == 5 and video.shape[1] == 24
        assert torch.all(video == 0.75), "must use saved clean x0, not noisy AV"
        return torch.linspace(0, 1, 5).view(5, 1, 1, 1).expand(5, 32, 32, 3)

    def encode(self, images):
        return torch.ones(1, 24, 2, images.shape[1] // 16, images.shape[2] // 16)


class Clip:
    def tokenize(self, prompt, **kwargs):
        return {"prompt": prompt, "presentation": kwargs.get("minimax_ref_items", [])}

    def encode_from_tokens_scheduled(self, tokens):
        return [[torch.zeros(1, 1, 4), {"tokens": tokens}]]


def main():
    spec = importlib.util.spec_from_file_location(
        "h3_pixel_test", ROOT / "__init__.py", submodule_search_locations=[str(ROOT)])
    package = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = package
    spec.loader.exec_module(package)
    chain = sys.modules[spec.name + ".chain_nodes"]
    upscale = sys.modules[spec.name + ".upscale_nodes"]
    for name in ("MiniMaxH3ChainUpscalePixelCurrent", "MiniMaxH3ChainUpscalePixelConditioning"):
        cls = package.NODE_CLASS_MAPPINGS[name]
        assert cls.EXPERIMENTAL and len(cls.OUTPUT_TOOLTIPS) == len(cls.RETURN_TYPES)

    with tempfile.TemporaryDirectory() as temporary:
        folder_paths.output_directory = temporary
        plan = chain.MiniMaxH3ChainPlan().build(
            json.dumps({"shots": [{"id": "pixel_%d" % i, "prompt": "A quiet room.",
                                    "length": 5, "steps": 2, "seed": str(i)}
                                   for i in (1, 2)]}),
            "pixel_test", "pixel-test-cache", 32, 32, 1,
            "video", "head", "disabled", "generated_audio", 1,
            5 / 24, 2, 7, 18, 0, "guide")[0]
        plan = chain._plan_with_source_audio(chain._plan_with_external_context(plan, None), None)
        lineage = []
        source_segments = []
        for index in (1, 2):
            state = chain._initial_state(plan, index)
            delivered = int(plan["shots"][index - 1]["delivered_frames"])
            latent = {"samples": [torch.full((1, 24, 2, 2, 2), 0.75),
                                   torch.full((1, 32, 2, 9), 0.75)]}
            audio = {"waveform": torch.full((1, 2, round(delivered / 24 * 8000)), index * 0.1),
                     "sample_rate": 8000}
            segment = chain.MiniMaxH3ChainSegmentSave().save(
                state, torch.zeros(delivered, 32, 32, 3), latent, audio,
                denoised_latent=latent)["result"][0]
            source_segments.append(segment)
            lineage.append({"scene": index, "revision": segment["revision"]})
        manifest = chain.MiniMaxH3ChainCheckpointManager().passthrough(
            json.dumps({"run_name": "pixel_test", "lineage": lineage}))[0]
        original_files = {p: p.read_bytes() for p in Path(temporary).rglob("*") if p.is_file()}
        pinned = chain.MiniMaxH3ChainCheckpointManager().passthrough(json.dumps({
            "run_name": "pixel_test", "lineage": lineage,
            "output_mode": "workflow_local"}))[0]
        assert pinned == manifest, "local pin must preserve the source recipe and manifests"
        manifest = pinned
        adapter = upscale.MiniMaxH3ChainUpscaleAdapter()
        flow, state, _, _ = adapter.adapt(manifest, "pixel", "pixel", "{}", 1, 0, False, 18)
        reader = upscale.MiniMaxH3ChainUpscalePixelCurrent()
        conditioner = upscale.MiniMaxH3ChainUpscalePixelConditioning()
        current = reader.current(state, VideoVAE())
        assert current[1].shape == (5, 32, 32, 3)
        assert current[2]["sample_rate"] == 8000 and current[4] == 1
        source_tensors = upscale._load_source_tensors(manifest["segments"][0])
        source_tensors.pop("delivered_audio")
        with patch.object(upscale, "_load_source_tensors", return_value=source_tensors):
            assert reader.current(state, VideoVAE())[2] is None
        fails(lambda: reader.current({**state, "profile_config": {"backend": "h3_latent"}}, VideoVAE()),
              "backend=pixel")
        target = torch.zeros(5, 64, 96, 3)
        result = conditioner.condition(state, Clip(), target, VideoVAE())
        assert result[1] is target and result[2:4] == (96, 64)
        assert "x3/y2" in result[-1] and result[5] is False
        for bad, message in ((target[:4], "RAW RGB"), (target[..., :2], "RAW RGB"),
                             (torch.zeros(5, 64, 80, 3), "multiples of 32")):
            fails(lambda: conditioner.condition(state, Clip(), bad, VideoVAE()), message)

        # Real cache-v2 RGB master rebuild, same canvas as latent counterpart,
        # and no double scaling during the integrated sync step.
        chain._cache_reference_scene(
            fingerprint="pixel-test-cache", scene=1, scene_count=2,
            prompt=source_segments[0]["prompt"], compiled_prompt="<Picture 1> in a quiet room.",
            width=32, height=32, length=5, ref_image_size="match",
            vae=VideoVAE(), audio_vae=None, pictures=[torch.ones(1, 64, 128, 3)],
            videos=[], audios=[])
        cached = conditioner.condition(state, Clip(), target, VideoVAE(), missing_cache="error")
        assert cached[5] is True
        latent_conditioning = upscale.MiniMaxH3ChainUpscaleReferenceConditioning().condition(
            state, Clip(), "error", {"samples": torch.zeros(1, 24, 2, 4, 6)}, VideoVAE())
        for actual, expected in zip(cached[0][0][1]["minimax_refs"],
                                    latent_conditioning[0][0][1]["minimax_refs"]):
            assert torch.equal(actual["latent"], expected["latent"])
        assert torch.equal(cached[0][0][1]["tokens"]["presentation"][0]["data"],
                           latent_conditioning[0][0][1]["tokens"]["presentation"][0]["data"])
        # Connected references follow the same target path, not source size.
        refs = chain.MiniMaxH3TaggedPictureReference().add(torch.ones(1, 64, 128, 3), "detail")[0]
        connected = conditioner.condition(state, Clip(), target, VideoVAE(),
            tagged_references=refs, prompt_override="@detail in a quiet room.", override_ref_image_size="match")
        assert "canvas=96x64" in connected[-1]
        assert torch.equal(connected[0][0][1]["minimax_refs"][0]["latent"],
                           cached[0][0][1]["minimax_refs"][0]["latent"])
        maximum = conditioner.condition(state, Clip(), target, VideoVAE(),
            tagged_references=refs, prompt_override="@detail in a quiet room.", override_ref_image_size="max")
        maximum_large = conditioner.condition(state, Clip(), torch.zeros(5, 96, 128, 3), VideoVAE(),
            tagged_references=refs, prompt_override="@detail in a quiet room.", override_ref_image_size="max")
        assert torch.equal(maximum[0][0][1]["minimax_refs"][0]["latent"],
                           maximum_large[0][0][1]["minimax_refs"][0]["latent"])
        # Keyframes/motion scale once; native audio tensor and time stay intact.
        audio_ref = torch.ones(1, 32, 2, 9)
        keyframe = torch.ones(1, 24, 2, 2, 2)
        conditioning = [[torch.zeros(1), {"minimax_keyframes": [{"frame": 3, "latent": keyframe}],
            "minimax_refs": [{"kind": "audio", "latent": audio_ref}]}]]
        with patch.object(upscale.MiniMaxH3ChainUpscaleReferenceConditioning, "condition",
                          return_value=(conditioning, "test", False, "test")):
            synced = conditioner.condition(state, Clip(), target, VideoVAE())[0][0][1]
        assert synced["minimax_keyframes"][0]["latent"].shape == (1, 24, 2, 4, 6)
        assert synced["minimax_keyframes"][0]["frame"] == 3
        assert synced["minimax_refs"][0]["latent"] is audio_ref
        assert conditioning[0][1]["minimax_keyframes"][0]["latent"].shape[-2:] == (2, 2)

        # Drift-Control in a parent must not require an unused pixel HQ latent.
        drift = copy.deepcopy(state)
        drift["source_manifest"]["segments"][1].update(
            raw_frames=44, delivered_frames=5, context_length=39, continuation_mode="drift_control_av")
        drift["profile"] = "pixel-drift"
        assert upscale._next_drift_context_steps(drift, 1) == 0
        assert upscale._load_previous_upscaled_context(drift, 2)[0] is None
        upscale.MiniMaxH3ChainUpscaleSegmentSave().save(drift, target)
        drift["profile_config"]["backend"] = "h3_latent"
        fails(lambda: upscale.MiniMaxH3ChainUpscaleSegmentSave().save(drift, target), "must receive")

        saver = upscale.MiniMaxH3ChainUpscaleSegmentSave()
        saved = saver.save(state, target)["result"][0]
        assert saved["context_steps"] == 0 and saved["latent_saved"] is False
        end = upscale.MiniMaxH3ChainUpscaleLoopEnd()
        with patch.object(end, "_recurse", side_effect=lambda flow, next_state, *a: next_state):
            live_next = end.end(flow, state, target, saved)
        assert live_next["index"] == 2 and live_next["previous_latent"] is None
        # Exercise real GraphBuilder expansion with the distributed workflow.
        # Every scene-dependent pixel node must recurse; the manager and model
        # loaders stay bootstrap-only, and conditioning/images stay paired.
        from comfy_execution.graph import DynamicPrompt
        wf_path, = (ROOT / "example_workflows").glob(
            "Deferred Upscale - Pixel DLSS5 + USDU - EXPERIMENTAL - MiniMax H3*.json")
        wf = json.loads(wf_path.read_text())
        links = {link[0]: link for link in wf["links"]}
        prompt = {str(n["id"]): {"class_type": n["type"], "inputs": {
            s["name"]: [str(links[s["link"]][1]), links[s["link"]][2]]
            for s in n["inputs"] if s["link"] is not None}}
            for n in wf["nodes"] if n["type"] != "Note"}
        def node_id(kind):
            return next(k for k, v in prompt.items() if v["class_type"] == kind)
        expanded = end._recurse(
            [node_id("MiniMaxH3ChainUpscaleAdapter"), 0], live_next,
            DynamicPrompt(prompt), node_id("MiniMaxH3ChainUpscaleLoopEnd"))["expand"]
        kinds = {v["class_type"]: k for k, v in expanded.items()}
        assert {"MiniMaxH3ChainUpscalePixelCurrent", "MiniMaxH3ChainUpscalePixelConditioning",
                "DLSS5EnhanceImages", "BasicGuider", "UltimateSDUpscaleNoUpscaleGuider",
                "MiniMaxH3ChainUpscaleSegmentSave", "MiniMaxH3ChainUpscaleLoopEnd"} <= kinds.keys()
        assert "MiniMaxH3ChainCheckpointManager" not in kinds and "UNETLoader" not in kinds
        assert expanded[kinds["MiniMaxH3ChainUpscaleAdapter"]]["inputs"]["initial_state"]["index"] == 2
        refinement_inputs = expanded[kinds["UltimateSDUpscaleNoUpscaleGuider"]]["inputs"]
        assert refinement_inputs["upscaled_image"] == [kinds["MiniMaxH3ChainUpscalePixelConditioning"], 1]
        assert expanded[kinds["BasicGuider"]]["inputs"]["conditioning"] == [
            kinds["MiniMaxH3ChainUpscalePixelConditioning"], 0]
        _, resumed, _, _ = adapter.adapt(manifest, "pixel", "pixel", "{}", 2, 0, False, 18)
        assert resumed["segments"][0]["revision"] == saved["revision"]
        fails(lambda: adapter.adapt(manifest, "pixel", "h3_latent", "{}", 2, 0, False, 18),
              "different profile settings")
        second = reader.current(resumed, VideoVAE())
        assert second[7] > 0, "fixture must exercise repeated prefix trimming"
        frames = second[1].repeat_interleave(2, dim=1).repeat_interleave(3, dim=2)
        saved2 = saver.save(resumed, frames)["result"][0]
        expected_audio = upscale._load_source_tensors(manifest["segments"][1])["delivered_audio"]
        child_tensors = chain._st_load(chain._absolute_output_path(saved2["checkpoint"]))
        assert torch.equal(child_tensors["delivered_audio"], expected_audio)
        assert saved2["delivered_frames"] == 5 - second[7]
        final = end.end(flow, resumed, frames, saved2)[0]
        assert final["completed_clip_count"] == 2
        assert final["total_delivered_frames"] == sum(s["delivered_frames"] for s in manifest["segments"])
        assembled = chain.MiniMaxH3ChainAssemble().assemble(
            final, "plan", "pixel_test_final", 128, False, "")
        assert Path(chain._absolute_output_path(assembled["result"][0])).is_file()
        streams = json.loads(subprocess.check_output([
            "ffprobe", "-v", "error", "-show_streams", "-of", "json",
            assembled["result"][0]]))["streams"]
        video = next(s for s in streams if s["codec_type"] == "video")
        assert (video["width"], video["height"]) == (96, 64)
        assert int(video["nb_frames"]) == final["total_delivered_frames"]
        assert any(s["codec_type"] == "audio" for s in streams)
        # No original prompt, checkpoint, audio or selection metadata changed.
        assert all(path.read_bytes() == content for path, content in original_files.items())
    print("Pixel upscale: exact/nonuniform target geometry, cache/override/max/keyframes/audio, RAW trim, Drift-Control isolation, save/resume/assembly and immutable source pass")


if __name__ == "__main__":
    main()
