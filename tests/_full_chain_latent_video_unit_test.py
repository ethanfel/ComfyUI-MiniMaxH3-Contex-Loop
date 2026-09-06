#!/usr/bin/env python3
"""CPU test for the disk-streamed full-chain VIDEO adapter."""

import hashlib
import importlib.util
import contextlib
import pathlib
import os
import sys
import tempfile


ROOT = pathlib.Path(__file__).resolve().parents[1]
candidates = [pathlib.Path(os.environ["COMFYUI_PATH"])] if os.environ.get("COMFYUI_PATH") else []
candidates += [ROOT.parent / "Comfyui", ROOT.parent / "ComfyUI"]
COMFY = next(path for path in candidates
             if (path / "comfy" / "options.py").is_file())
sys.path.insert(0, str(COMFY))
sys.argv = ["h3-full-chain-video-test", "--cpu"]

import av  # noqa: E402
import comfy.options  # noqa: E402

comfy.options.enable_args_parsing()
import folder_paths  # noqa: E402
import torch  # noqa: E402
from comfy import model_management  # noqa: E402
from safetensors.torch import save_file  # noqa: E402


def load_package():
    spec = importlib.util.spec_from_file_location(
        "h3_full_chain_video_test_package", ROOT / "__init__.py",
        submodule_search_locations=[str(ROOT)])
    package = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = package
    spec.loader.exec_module(package)
    return package, sys.modules[spec.name + ".chain_nodes"]


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class FakeVAE:
    def __init__(self):
        self.calls = 0
        self.fail = False

    def decode(self, video):
        if self.fail:
            raise AssertionError("completed adapter cache was not reused")
        self.calls += 1
        frames = int(video.shape[2])
        value = float(video.flatten()[0])
        return torch.full((frames, 16, 16, 3), value, dtype=torch.float32)


def main():
    package, chain = load_package()
    assert "MiniMaxH3ChainLatentVideoAdapter" in package.NODE_CLASS_MAPPINGS
    node = package.NODE_CLASS_MAPPINGS["MiniMaxH3ChainLatentVideoAdapter"]
    schema = node.INPUT_TYPES()
    for section in ("required", "optional"):
        for name, spec in schema.get(section, {}).items():
            options = spec[1] if len(spec) > 1 else {}
            assert str(options.get("tooltip") or "").strip(), name
    assert len(node.RETURN_TYPES) == len(node.OUTPUT_TOOLTIPS)

    with tempfile.TemporaryDirectory() as temporary:
        folder_paths.output_directory = temporary

        class FakeChunkedDecoder:
            comfy_has_chunked_io = True
            latents_mean = torch.zeros(24)

            def decode_output_shape(self, shape):
                return (1, 3, 3, 2, 2)

            def decode(self, samples, output_buffer=None):
                assert output_buffer is not None
                output_buffer.copy_(torch.arange(
                    output_buffer.numel(), dtype=torch.float32).reshape(
                        output_buffer.shape) / output_buffer.numel())
                return output_buffer

        class FakeDiskVAE:
            def __init__(self):
                self.first_stage_model = FakeChunkedDecoder()
                self.patcher = object()
                self.device = "cpu"
                self.vae_dtype = torch.float32
                self.disable_offload = False

            def throw_exception_if_invalid(self):
                return None

            def memory_used_decode(self, shape, dtype):
                return 1

        original_load_models = model_management.load_models_gpu
        original_device_context = model_management.cuda_device_context
        model_management.load_models_gpu = lambda *args, **kwargs: None
        model_management.cuda_device_context = lambda device: contextlib.nullcontext()
        disk_buffer = pathlib.Path(temporary, "decode.buffer")
        try:
            images, mapped, mode = chain._decode_checkpoint_video_for_streaming(
                FakeDiskVAE(), torch.zeros((1, 24, 2, 1, 1)),
                "disk-backed", str(disk_buffer))
            assert mode == "disk-backed mmap"
            assert tuple(images.shape) == (3, 2, 2, 3)
            assert disk_buffer.stat().st_size == mapped.numel() * 4
            del images, mapped
            wrong_vae = FakeDiskVAE()
            wrong_vae.first_stage_model.latents_mean = torch.zeros(32)
            try:
                chain._decode_checkpoint_video_for_streaming(
                    wrong_vae, torch.zeros((1, 24, 2, 1, 1)),
                    "memory", str(disk_buffer))
                raise AssertionError("32-channel audio VAE was accepted")
            except ValueError as exc:
                assert "not the 32-channel MiniMax audio VAE" in str(exc)
        finally:
            model_management.load_models_gpu = original_load_models
            model_management.cuda_device_context = original_device_context
            disk_buffer.unlink(missing_ok=True)

        checkpoint_dir = pathlib.Path(
            temporary, "h3_chains", "seedvr_test", "checkpoints")
        checkpoint_dir.mkdir(parents=True)
        first = checkpoint_dir / "clip_0001.safetensors"
        second = checkpoint_dir / "clip_0002.safetensors"
        save_file({
            "video": torch.zeros((1, 24, 5, 1, 1), dtype=torch.float32),
        }, first)
        save_file({
            "video": torch.ones((1, 24, 7, 1, 1), dtype=torch.float32),
        }, second)

        manifest = {
            "format": "h3_chain_manifest_v3",
            "run_name": "seedvr_test",
            "plan_hash": "test-plan",
            "clip_count": 2,
            "total_delivered_frames": 10,
            "compatibility": {
                "width": 16,
                "height": 16,
                "video_blend_frames": 2,
            },
            "segments": [{
                "index": 1,
                "revision": "1" * 32,
                "checkpoint": chain._relative_output_path(str(first)),
                "checkpoint_sha256": sha256(first),
                "raw_frames": 5,
                "delivered_frames": 5,
                "blend_frames": 0,
            }, {
                "index": 2,
                "revision": "2" * 32,
                "checkpoint": chain._relative_output_path(str(second)),
                "checkpoint_sha256": sha256(second),
                "raw_frames": 7,
                "delivered_frames": 5,
                "blend_frames": 2,
            }],
        }
        original_native = chain._native_video_from_path
        chain._native_video_from_path = lambda path: path
        try:
            vae = FakeVAE()
            video, path, status = node().adapt(
                manifest, vae, "none", "plan", "memory", False, 256)
            assert video == path and pathlib.Path(path).is_file()
            assert vae.calls == 2
            assert "10 frames" in status and "blends [2]" in status

            pixels = []
            with av.open(path, mode="r") as container:
                assert len(container.streams.audio) == 0
                for frame in container.decode(container.streams.video[0]):
                    pixels.append(int(frame.to_ndarray(format="rgb24")[0, 0, 0]))
            assert len(pixels) == 10
            # The two incoming protected frames are blended before the five
            # delivered white frames; duration remains exactly 5 + 5.
            assert pixels[:3] == [0, 0, 0]
            assert abs(pixels[3] - 85) <= 2
            assert abs(pixels[4] - 170) <= 2
            assert all(value >= 253 for value in pixels[5:])

            manifest["segments"][0]["id"] = "one"
            manifest["segments"][1]["id"] = "two"
            editorial_path = pathlib.Path(
                chain._run_editorial_path("seedvr_test"))
            chain._atomic_json(editorial_path, chain._normalize_run_editorial({
                "format": "h3_chain_editorial_v1",
                "run_name": "seedvr_test",
                "scene_order": [
                    {"scene": 1, "scene_id": "one"},
                    {"scene": 2, "scene_id": "two"},
                ],
                "trims": [{
                    "scene": 2, "scene_id": "two", "out_frame": 3,
                }],
            }, "seedvr_test"))
            trimmed_vae = FakeVAE()
            trimmed_video, trimmed_path, trimmed_status = node().adapt(
                manifest, trimmed_vae, "none", "plan", "memory", False, 256)
            assert trimmed_video == trimmed_path
            assert trimmed_path != path
            assert trimmed_vae.calls == 2
            assert "8 frames" in trimmed_status
            with av.open(trimmed_path, mode="r") as container:
                assert sum(1 for _frame in container.decode(
                    container.streams.video[0])) == 8
            chain._atomic_json(editorial_path, chain._normalize_run_editorial({
                "format": "h3_chain_editorial_v1",
                "run_name": "seedvr_test",
                "scene_order": [
                    {"scene": 1, "scene_id": "one"},
                    {"scene": 2, "scene_id": "two"},
                ],
            }, "seedvr_test"))

            partial_manifest = {
                **manifest,
                "clip_count": 1,
                "planned_clip_count": 2,
                "selection_complete": False,
                "total_delivered_frames": 5,
                "segments": manifest["segments"][:1],
            }
            partial_vae = FakeVAE()
            partial_video, partial_path, partial_status = node().adapt(
                partial_manifest, partial_vae, "none", "plan", "memory",
                False, 256)
            assert partial_video == partial_path
            assert partial_vae.calls == 1
            assert "1 scenes / 5 frames" in partial_status

            cached_vae = FakeVAE()
            cached_vae.fail = True
            cached_video, cached_path, cached_status = node().adapt(
                manifest, cached_vae, "none", "plan", "memory", True, 256)
            assert cached_video == cached_path == path
            assert "reused" in cached_status

            source_audio = {
                "waveform": torch.zeros(
                    (1, 2, round(10 / 24 * 8000)), dtype=torch.float32),
                "sample_rate": 8000,
            }
            manifest["compatibility"]["source_audio_hash"] = (
                chain._audio_fingerprint(source_audio))
            manifest["compatibility"]["audio_mode"] = "source_track"
            _audio_video, audio_path, audio_status = node().adapt(
                manifest, FakeVAE(), "plan", "plan", "memory", False,
                256, source_audio=source_audio)
            assert "audio=source" in audio_status
            with av.open(audio_path, mode="r") as container:
                assert len(container.streams.video) == 1
                assert len(container.streams.audio) == 1
        finally:
            chain._native_video_from_path = original_native

    print("full-chain latent VIDEO adapter unit test passed")


if __name__ == "__main__":
    main()
