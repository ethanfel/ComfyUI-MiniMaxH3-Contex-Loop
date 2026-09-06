#!/usr/bin/env python3
"""CPU regressions for per-reference cache storage and portable scene manifests."""

import copy
import errno
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from _upscale_chain_unit_test import (
    load_package, folder_paths, torch, legacy_cache_fixture)


class VideoVAE:
    def __init__(self, offset=0, dtype=torch.float32):
        self.offset, self.dtype = offset, dtype

    def encode(self, images):
        return torch.full((1, 24, 2, images.shape[1] // 16, images.shape[2] // 16),
                          float(images.mean()) + self.offset, dtype=self.dtype)


class AudioVAE:
    audio_sample_rate = 32000

    def encode(self, samples):
        return samples.movedim(-1, 1).contiguous()


class ReferenceObjectsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _, cls.chain, cls.upscale = load_package()

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.old_output = folder_paths.output_directory
        self.addCleanup(setattr, folder_paths, "output_directory", self.old_output)
        folder_paths.output_directory = self.temporary.name
        self.root = Path(self.temporary.name)
        self.picture = torch.full((1, 64, 128, 3), 0.75)
        self.other = torch.full((1, 80, 96, 3), 0.25)

    def save(self, **overrides):
        values = dict(fingerprint="catalog", scene=1, scene_count=3,
                      prompt="first scene", compiled_prompt="<Picture 1> walks",
                      width=32, height=32, length=5, ref_image_size="match",
                      vae=VideoVAE(), audio_vae=AudioVAE(),
                      pictures=[self.picture, self.other], videos=[], audios=[])
        values.update(overrides)
        status = self.chain._cache_reference_scene(**values)
        cache = self.chain._find_reference_cache(*[values[key] for key in (
            "fingerprint", "scene", "scene_count", "prompt", "width", "height", "length")])
        self.assertEqual(cache["format"], "h3_reference_cache_v3")
        self.chain._load_reference_cache_descriptor(self.chain._reference_cache_descriptor(cache))
        return cache, status

    def objects(self):
        return {path.name: (path.stat().st_size, path.stat().st_mtime_ns)
                for path in (self.root / "h3_reference_cache/objects").glob("*.safetensors")}

    def record(self, cache, key):
        return cache["tensor_objects"][key]

    def test_reuse_across_scenes_prompts_catalogs_order_and_duplicates(self):
        first, _ = self.save()
        before = self.objects()
        second, _ = self.save(scene=2, prompt="different action", fingerprint="other catalog",
                              compiled_prompt="<Picture 2> sits", pictures=[self.other, self.picture])
        self.assertEqual(before, self.objects(), "scene edits must not rewrite reference objects")
        self.assertNotEqual(first["signature"], second["signature"])
        self.assertEqual(self.record(first, "source_image_000"), self.record(second, "source_image_001"))
        self.assertEqual(self.record(first, "block_000_latent"), self.record(second, "block_001_latent"))
        _, status = self.save()
        self.assertIn("reused", status)
        self.assertEqual(before, self.objects())
        duplicate, _ = self.save(scene=3, pictures=[self.picture, self.picture])
        self.assertEqual(before, self.objects())
        tensors = self.chain._reference_cache_tensors(duplicate)
        self.assertIs(tensors["block_000_latent"], tensors["block_001_latent"])
        presentation, blocks, masters = self.chain._reference_payload_from_cache(second)
        original_blocks = self.chain._reference_payload_from_cache(first)[1]
        self.assertTrue(torch.equal(blocks[0]["latent"], original_blocks[1]["latent"]))
        self.assertTrue(torch.equal(blocks[1]["latent"], original_blocks[0]["latent"]))
        self.assertEqual(tuple(masters[0].shape), tuple(self.other.shape))
        self.assertEqual(len(presentation), 2)
        self.assertFalse(list((self.root / "h3_reference_cache/catalog").glob("*.safetensors")))
        # Quantify real fixture duplication, rather than assume an end-user ratio.
        bundled_bytes = 0
        for cache in (first, second, duplicate):
            for value in self.chain._reference_cache_tensors(cache).values():
                bundled_bytes += value.numel() * value.element_size()
        stored_bytes = sum(size for size, _ in before.values())
        self.assertLess(stored_bytes, bundled_bytes / 2)

    def test_changed_geometry_encoder_dtype_and_content_get_distinct_objects(self):
        first, _ = self.save(pictures=[self.picture])
        larger, _ = self.save(scene=2, width=64, height=64, pictures=[self.picture])
        self.assertEqual(self.record(first, "source_image_000"), self.record(larger, "source_image_000"))
        self.assertNotEqual(self.record(first, "block_000_latent"), self.record(larger, "block_000_latent"))
        for vae in (VideoVAE(offset=1), VideoVAE(dtype=torch.bfloat16)):
            changed, status = self.save(pictures=[self.picture], vae=vae)
            self.assertIn("saved", status)
            self.assertNotEqual(changed["signature"], first["signature"])
            self.assertEqual(self.record(first, "source_image_000"), self.record(changed, "source_image_000"))
            self.assertNotEqual(self.record(first, "block_000_latent"), self.record(changed, "block_000_latent"))
        changed, _ = self.save(scene=3, pictures=[self.picture + 0.1])
        self.assertNotEqual(self.record(first, "source_image_000"), self.record(changed, "source_image_000"))

    def test_video_audio_and_semantic_presentation_round_trip(self):
        video = torch.linspace(0, 1, 22).reshape(22, 1, 1, 1).expand(-1, 32, 32, 3)
        audio = {"waveform": torch.full((1, 2, 300), 0.3), "sample_rate": 32000}
        cache, _ = self.save(pictures=[], videos=[{"video": video, "audio": audio}],
                             audios=[audio], length=22)
        presentation, blocks, masters = self.chain._reference_payload_from_cache(cache)
        self.assertEqual([item["type"] for item in presentation], ["audio", "video", "audio"])
        self.assertEqual(presentation[1]["timestamps"], [0.0, 0.5])
        self.assertEqual(masters, [])
        self.assertEqual(blocks[0]["kind"], "video_audio")
        self.assertTrue(torch.equal(blocks[0]["audio_latent"], blocks[1]["audio_latent"]))
        self.assertEqual(self.record(cache, "block_000_audio_latent"), self.record(cache, "block_001_audio_latent"))
        shorter, _ = self.save(pictures=[], videos=[{"video": video, "audio": audio}], length=5)
        self.assertNotEqual(self.record(cache, "block_000_latent"), self.record(shorter, "block_000_latent"))
        self.assertEqual(self.record(cache, "block_000_audio_latent"), self.record(shorter, "block_000_audio_latent"))
        semantic = {"version": self.chain.SEMANTIC_PRESENTATION_VERSION,
                    "width": 32, "height": 32, "length": 5,
                    "semantic_anchor_mode": "timestamped_video", "semantic_anchor_size": "1280",
                    "pictures": [self.picture],
                    "anchors": [{"tag": "place", "untimed": True, "image": self.other}]}
        cache, _ = self.save(pictures=[self.picture], semantic_presentation=semantic)
        presentation, blocks, _ = self.chain._reference_payload_from_cache(cache)
        self.assertEqual(len(blocks), 1)
        self.assertEqual([item["role"] for item in presentation], ["native_picture", "semantic_presentation"])

    def test_projects_are_deduplicated_and_self_contained_link_and_copy(self):
        first, _ = self.save()
        second, _ = self.save(scene=2, prompt="different scene")
        for run_name, copy_only in (("linked", False), ("copied", True)):
            plan = {"run_name": run_name, "shots": [{}, {}, {}]}
            with patch("os.link", side_effect=OSError(errno.EXDEV, "cross device")) if copy_only else patch(
                    "os.link", wraps=__import__("os").link):
                adopted = [self.chain._adopt_reference_cache_for_run(plan, item) for item in (first, second)]
            local_root = self.root / "h3_chains" / run_name / "reference_cache"
            self.assertEqual(len(list((local_root / "objects").glob("*.safetensors"))), len(self.objects()))
            for cache in adopted:
                for key, record in cache["tensor_objects"].items():
                    path = self.root / record["tensors"]
                    original = self.root / first["tensor_objects"][key]["tensors"]
                    self.assertEqual(path.read_bytes(), original.read_bytes())
                    if not copy_only:
                        self.assertEqual(path.stat().st_ino, original.stat().st_ino)
            # Copy only the project to a new output root, with no shared cache.
            with tempfile.TemporaryDirectory() as relocated:
                shutil.copytree(self.root / "h3_chains" / run_name,
                                Path(relocated) / "h3_chains" / run_name)
                folder_paths.output_directory = relocated
                try:
                    for old_cache in (first, second):
                        restored = self.chain._load_run_reference_cache_descriptor(
                            run_name, old_cache["scene"], self.chain._reference_cache_descriptor(old_cache))
                        self.assertEqual(restored["run_name"], run_name)
                        self.assertEqual(len(self.chain._reference_payload_from_cache(restored)[1]), 2)
                finally:
                    folder_paths.output_directory = self.temporary.name

    def test_corruption_missing_objects_manifest_tampering_and_foreign_paths_fail(self):
        cache, _ = self.save()
        record = self.record(cache, "block_000_latent")
        path = self.root / record["tensors"]
        saved = path.read_bytes()
        path.unlink()
        with self.assertRaisesRegex(ValueError, "integrity"):
            self.chain._reference_payload_from_cache(cache)
        path.write_bytes(saved[:-1] + bytes([saved[-1] ^ 1]))
        with self.assertRaisesRegex(ValueError, "integrity"):
            self.chain._reference_payload_from_cache(cache)
        with self.assertRaisesRegex(ValueError, "integrity"):
            self.save()
        path.write_bytes(saved)
        changed = copy.deepcopy(cache)
        changed["tensor_objects"].pop("block_000_latent")
        with self.assertRaisesRegex(ValueError, "manifest.*integrity"):
            self.chain._reference_payload_from_cache(changed)
        changed = copy.deepcopy(cache)
        changed["tensor_objects"]["block_000_latent"]["tensors"] = "../foreign.safetensors"
        with self.assertRaisesRegex(ValueError, "outside"):
            self.chain._reference_payload_from_cache(changed)
        foreign = self.root / "foreign" / path.name
        foreign.parent.mkdir()
        foreign.write_bytes(saved)
        changed["tensor_objects"]["block_000_latent"]["tensors"] = str(foreign)
        with self.assertRaisesRegex(ValueError, "outside"):
            self.chain._reference_payload_from_cache(changed)

    def test_concurrent_writers_and_failed_manifest_publication(self):
        with ThreadPoolExecutor(max_workers=4) as executor:
            caches = list(executor.map(lambda i: self.save(scene=i + 1), range(3)))
        self.assertEqual(len({cache["tensors_sha256"] for cache, _ in caches}), 1)
        before = self.objects()
        self.assertFalse(list(self.root.rglob("*.tmp")))
        with patch.object(self.chain, "_atomic_json", side_effect=OSError("disk full")):
            with self.assertRaisesRegex(OSError, "disk full"):
                self.save(prompt="unpublished scene")
        self.assertEqual(before, self.objects())
        self.assertIsNone(self.chain._find_reference_cache("catalog", 1, 3, "unpublished scene", 32, 32, 5))
        self.assertEqual(len(self.chain._reference_payload_from_cache(caches[0][0])[1]), 2)

    def test_v1_v2_bundles_still_restore_and_adopt(self):
        for version in ("h3_reference_cache_v1", "h3_reference_cache_v2"):
            cache, _ = self.save(prompt=version)
            legacy = legacy_cache_fixture(self.chain, cache, version)
            self.chain._load_reference_cache_descriptor(self.chain._reference_cache_descriptor(legacy))
            if version.endswith("v1"):
                legacy.pop("source_images", None)
                self.chain._atomic_json(self.chain._absolute_output_path(legacy["metadata"]), legacy)
            restored = self.chain._reference_payload_from_cache(legacy)
            self.assertEqual(len(restored[1]), 2)
            local = self.chain._adopt_reference_cache_for_run(
                {"run_name": "legacy", "shots": [{}, {}, {}]}, legacy)
            self.assertEqual(local["format"], version)
            self.assertEqual(len(self.chain._reference_payload_from_cache(local)[1]), 2)


if __name__ == "__main__":
    unittest.main(argv=["reference-cache-objects"], verbosity=2)
