#!/usr/bin/env python3
"""CPU regression test for the parallel checkpoint PNG exporter."""

import hashlib
import importlib.util
import json
import pathlib
import sys
import tempfile
import threading
import time
import types
import wave

from PIL import Image
import torch
from safetensors.torch import save_file


ROOT = pathlib.Path(__file__).resolve().parents[1]
PACKAGE = "h3_png_export_unit"

folder_paths = types.ModuleType("folder_paths")
folder_paths.output_directory = str(ROOT)
folder_paths.get_output_directory = lambda: folder_paths.output_directory
folder_paths.get_temp_directory = lambda: folder_paths.output_directory
folder_paths.get_input_directory = lambda: folder_paths.output_directory
folder_paths.get_annotated_filepath = lambda value: str(value)
sys.modules["folder_paths"] = folder_paths

package = types.ModuleType(PACKAGE)
package.__path__ = [str(ROOT)]
sys.modules[PACKAGE] = package

shared_nodes = types.ModuleType(PACKAGE + ".nodes")
shared_nodes.MiniMaxH3MotionContext = object
shared_nodes._claim_inline_patch_ownership = lambda _conditioning=None: "test"
shared_nodes._prepare_native_guide_conditioning = lambda *args: None
shared_nodes._resize = lambda *args: None
shared_nodes._streams_from_latent = lambda *args: None
sys.modules[shared_nodes.__name__] = shared_nodes

spec = importlib.util.spec_from_file_location(
    PACKAGE + ".chain_nodes", ROOT / "chain_nodes.py")
chain = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = chain
spec.loader.exec_module(chain)


def digest(path):
    value = hashlib.sha256()
    value.update(path.read_bytes())
    return value.hexdigest()


class FakeProgress:
    def __init__(self, total):
        self.total = total
        self.values = []

    def update_absolute(self, value, total=None):
        self.values.append((value, total))


class FakeVAE:
    def decode(self, _video):
        images = torch.zeros((8, 4, 4, 3), dtype=torch.float32)
        for frame in range(8):
            images[frame, ..., 0] = (10 + frame) / 255.0
        return images


class FakeAudioVAE:
    audio_sample_rate = 8000

    def __init__(self):
        self.calls = 0

    def decode(self, _audio):
        self.calls += 1
        # Return one extra sample so the export exercises its real waveform
        # conformance path instead of only the already-exact fast path.
        samples = chain.sample_boundary_from_frames(8, 8000, chain.FPS) + 1
        return torch.linspace(
            -0.5, 0.5, samples, dtype=torch.float32
        ).reshape(1, 1, -1).expand(1, 2, -1).contiguous()


def main():
    schema = chain.MiniMaxH3ChainExportPNG.INPUT_TYPES()
    assert schema["required"]["png_compression"][1]["default"] == 1
    assert "video_vae" not in schema["required"]
    assert "video_vae" in schema["optional"]
    assert "audio_vae" in schema["optional"]
    assert schema["optional"]["save_workers"][1]["default"] == 0
    assert schema["optional"]["checkpoint_verification"][0] == [
        "cached", "strict"]
    assert chain._png_export_worker_count(1) == 1
    assert 1 <= chain._png_export_worker_count(0) <= 8

    packed, packed_frames = chain._png_export_packed_audio_records(
        [
            {"index": 1, "id": "one", "delivered_frames": 8},
            {"index": 2, "id": "two", "delivered_frames": 8},
        ],
        [
            {"index": 2, "id": "two", "delivered_frames": 8,
             "_editorial_out_frames": 4},
            {"index": 1, "id": "one", "delivered_frames": 8},
        ])
    assert packed_frames == 12
    reordered = chain._audio_with_editorial_timeline({
        "waveform": torch.cat((
            torch.ones((1, 1, 8)), torch.full((1, 1, 8), 2.0)), dim=-1),
        "sample_rate": 24,
    }, packed, 16, 12, "PNG/WAV test audio")
    assert reordered["waveform"].reshape(-1).tolist() == (
        [2.0] * 4 + [1.0] * 8)

    with tempfile.TemporaryDirectory() as temporary:
        folder_paths.output_directory = temporary
        checkpoint = pathlib.Path(
            temporary, "h3_chains", "pngfast", "checkpoints",
            "clip_0001.safetensors")
        checkpoint.parent.mkdir(parents=True)
        save_file({
            "video": torch.zeros((1, 24, 2, 1, 1), dtype=torch.float32),
            "audio": torch.zeros((1, 32, 2, 14), dtype=torch.float32),
        }, checkpoint)
        manifest = {
            "format": "h3_chain_manifest_v3",
            "run_name": "pngfast",
            "plan_hash": "plan",
            "clip_count": 1,
            "total_delivered_frames": 8,
            "segments": [{
                "index": 1,
                "id": "scene_one",
                "checkpoint": chain._relative_output_path(str(checkpoint)),
                "checkpoint_sha256": digest(checkpoint),
                "raw_frames": 8,
                "delivered_frames": 8,
                "prompt": "test prompt",
                "prompt_hash": "prompt-hash",
                "seed": 7,
            }],
            "archives": {},
        }

        originals = {
            "load_editorial": chain._load_run_editorial,
            "trim": chain._editorial_trimmed_segment,
            "dependencies": chain._require_current_editorial_dependencies,
            "presentation": chain._editorial_presentation_segments,
            "delivered": chain._editorial_segment_delivered_frames,
            "progress": chain._png_export_progress,
            "write": chain._write_png,
            "atomic": chain._atomic_json,
        }
        fake_progress = FakeProgress(40)
        partial_snapshots = []
        active = 0
        max_active = 0
        lock = threading.Lock()

        def tracked_write(*args, **kwargs):
            nonlocal active, max_active
            with lock:
                active += 1
                max_active = max(max_active, active)
            try:
                time.sleep(0.01)
                return originals["write"](*args, **kwargs)
            finally:
                with lock:
                    active -= 1

        def tracked_atomic(path, value):
            if str(path).endswith("export.partial.json"):
                partial_snapshots.append(json.loads(json.dumps(value)))
            return originals["atomic"](path, value)

        chain._load_run_editorial = lambda _run: {}
        chain._editorial_trimmed_segment = lambda segment, _editorial: dict(
            segment)
        chain._require_current_editorial_dependencies = lambda *_args: None
        chain._editorial_presentation_segments = (
            lambda _run, segments, _editorial: list(segments))
        chain._editorial_segment_delivered_frames = (
            lambda segment: int(segment["delivered_frames"]))
        chain._png_export_progress = lambda _total: fake_progress
        chain._write_png = tracked_write
        chain._atomic_json = tracked_atomic
        try:
            audio_vae = FakeAudioVAE()
            result = chain.MiniMaxH3ChainExportPNG().export(
                manifest, FakeVAE(), "sequence", 1, 1, False,
                save_workers=4, checkpoint_verification="cached",
                audio_vae=audio_vae)
        finally:
            chain._load_run_editorial = originals["load_editorial"]
            chain._editorial_trimmed_segment = originals["trim"]
            chain._require_current_editorial_dependencies = originals[
                "dependencies"]
            chain._editorial_presentation_segments = originals["presentation"]
            chain._editorial_segment_delivered_frames = originals["delivered"]
            chain._png_export_progress = originals["progress"]
            chain._write_png = originals["write"]
            chain._atomic_json = originals["atomic"]

        output = pathlib.Path(result["result"][0])
        files = sorted(output.glob("frame_*.png"))
        assert len(files) == result["result"][1] == 8
        audio_path = pathlib.Path(result["result"][3])
        assert audio_path == output / "audio.wav" and audio_path.is_file()
        assert audio_vae.calls == 1
        with wave.open(str(audio_path), "rb") as saved_audio:
            assert saved_audio.getframerate() == 8000
            assert saved_audio.getnchannels() == 2
            assert saved_audio.getnframes() == chain.sample_boundary_from_frames(
                8, 8000, chain.FPS)
        assert max_active > 1, "PNG files were not written concurrently"
        with Image.open(files[0]) as image:
            assert image.getpixel((0, 0))[0] == 10
            assert image.text["h3_clip_index"] == "1"
            assert json.loads(image.text["h3_scene"])["prompt"] == "test prompt"
        record = json.loads((output / "export.json").read_text())
        assert record["complete"]
        assert record["settings"]["save_workers"] == 4
        assert record["settings"]["png_compression"] == 1
        assert record["settings"]["export_video"] is True
        assert record["settings"]["export_audio"] is True
        assert record["audio"]["file"] == "audio.wav"
        assert record["audio"]["sample_rate"] == 8000
        assert record["timings"][0]["verification"] == "verified SHA-256"
        assert record["timings"][0]["png_save_seconds"] >= 0
        assert not (output / "export.partial.json").exists()
        phases = [snapshot["phase"] for snapshot in partial_snapshots]
        assert "verifying checkpoint" in phases
        assert "decoding VAE on GPU" in phases
        assert "saving PNG frames" in phases
        assert "decoding audio VAE on GPU" in phases
        assert "assembling synchronized WAV" in phases
        assert "audio complete" in phases
        assert any(
            snapshot["phase"] == "saving PNG frames"
            and snapshot["current_clip_frames"] == 8
            for snapshot in partial_snapshots)
        assert fake_progress.values[-1] == (40, 40)

        cache_path, cache = chain._load_png_export_hash_cache(manifest)
        assert pathlib.Path(cache_path).is_file()
        result_name, changed = chain._verify_png_export_checkpoint(
            str(checkpoint), manifest["segments"][0]["checkpoint_sha256"],
            "cached", cache)
        assert result_name == "cached SHA-256" and not changed

        audio_only_vae = FakeAudioVAE()
        audio_only = chain.MiniMaxH3ChainExportPNG().export(
            manifest, None, "audio_only", 1, 1, False,
            checkpoint_verification="cached", audio_vae=audio_only_vae)
        audio_only_dir = pathlib.Path(audio_only["result"][0])
        assert audio_only["result"][1] == 0
        assert not list(audio_only_dir.glob("frame_*.png"))
        assert pathlib.Path(audio_only["result"][3]).is_file()
        audio_only_record = json.loads(
            (audio_only_dir / "export.json").read_text())
        assert audio_only_record["frame_count"] == 0
        assert audio_only_record["timeline_frame_count"] == 8
        assert audio_only_record["settings"]["export_video"] is False
        assert audio_only_record["settings"]["export_audio"] is True
        assert audio_only_vae.calls == 1

        try:
            chain.MiniMaxH3ChainExportPNG().export(
                manifest, None, "nothing", 1, 1, False)
        except ValueError as exc:
            assert "video_vae, audio_vae, or both" in str(exc)
        else:
            raise AssertionError("export accepted no connected VAE")

    print("H3 PNG/WAV export: independent video/audio VAEs, synchronized WAV, "
          "audio-only mode, cached integrity, parallel saves, progress, and "
          "partial recovery pass")


if __name__ == "__main__":
    main()
