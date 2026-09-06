#!/usr/bin/env python3
"""Chapter geometry and existing-lock compatibility, using temporary projects."""

import copy
import importlib
import json
import math
import pathlib
import runpy
import tempfile
import unittest
from unittest.mock import patch

import torch

fixture = runpy.run_path(str(pathlib.Path(__file__).with_name(
    "_chapter_delivery_unit_test.py")))
chain = fixture["chain"]
folders = fixture["folder_paths"]


class ChapterResolutionTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        folders.output_directory = self.temp.name
        self.root = pathlib.Path(self.temp.name)
        self.raw = {
            "shots": [{"id": f"scene_{i:02d}", "prompt": f"Scene {i}",
                       "length": 39, "context_length": 0}
                      for i in range(1, 7)],
            "chapters": fixture["make_editorial"]()["chapters"],
        }

    def plan(self, width=64, height=64, raw=None, mode="guide"):
        return chain._normalize_plan(
            json.dumps(self.raw if raw is None else raw), "chapter_delivery",
            width, height, 5, "video", "head", "disabled", "generated_audio",
            5, 1.0, 8, 11, 18, "test-model", 0, mode)

    def locks(self, indices, sizes=None):
        old = self.plan()
        editorial = fixture["make_editorial"]()
        editorial["locked_scene_ids"] = [f"scene_{i:02d}" for i in indices]
        for i in indices:
            metadata = {
                "segment": {"id": f"scene_{i:02d}", "index": i},
                "compatibility": dict(old["compatibility"]),
                "scene_dependency": chain._scene_dependency_record(old, i, None),
            }
            if sizes and i in sizes:
                metadata["scene_dependency"]["scopes"]["global_generation"].update(sizes[i])
            chain._atomic_json(chain._artifact_paths(old, i)["metadata"], metadata)
        chain._atomic_json(chain._run_editorial_path("chapter_delivery"), editorial)
        return old

    def test_inherit_preserves_legacy_hashes(self):
        plan = self.plan()
        plain = copy.deepcopy(self.raw)
        plain.pop("chapters")
        self.assertEqual(plan["plan_hash"], self.plan(raw=plain)["plan_hash"])
        self.assertTrue(all("resolution" not in shot for shot in plan["shots"]))
        self.raw["chapters"][0]["title"] = "Changed notes"
        self.assertEqual(plan["plan_hash"], self.plan()["plan_hash"])

    def test_chapter_dimensions_and_dependency_isolation(self):
        old = self.plan()
        self.raw["chapters"][1]["resolution"] = {"width": 128, "height": 96}
        new = self.plan()
        self.assertEqual(chain.scene_resolution(new, 1), {"width": 64, "height": 64})
        self.assertEqual(chain.scene_resolution(new, 4), {"width": 128, "height": 96})
        for index in range(1, 7):
            diffs = chain._scene_dependency_diffs(
                chain._scene_dependency_record(old, index, None),
                chain._scene_dependency_record(new, index, None))
            self.assertEqual(bool(diffs), index >= 4)
        result = chain.MiniMaxH3ChainCurrent().current({"plan": new, "index": 4})
        self.assertEqual(result["result"][8:10], (128, 96))
        self.assertEqual(new["compatibility"]["width"], 64)

    def test_inherit_is_plan_default_not_previous_chapter(self):
        self.raw["chapters"][0]["resolution"] = {"width": 128, "height": 96}
        self.assertEqual(chain.scene_resolution(self.plan(), 4), {"width": 64, "height": 64})

    def test_old_locks_pin_only_their_chapter_without_writes(self):
        old = self.locks([1, 2, 3])
        before = {path: path.read_bytes() for path in self.root.rglob("*.json")}
        new = self.plan(128, 96)
        for index in range(1, 4):
            self.assertEqual(chain.scene_resolution(new, index), {"width": 64, "height": 64})
            self.assertEqual(chain._scene_dependency_diffs(
                chain._scene_dependency_record(old, index, None),
                chain._scene_dependency_record(new, index, None)), [])
        self.assertEqual(chain.scene_resolution(new, 4), {"width": 128, "height": 96})
        self.assertEqual(before, {path: path.read_bytes() for path in self.root.rglob("*.json")})
        recovered = self.plan(128, 96, raw=chain._effective_editor_plan(new))
        self.assertEqual([chain.scene_resolution(recovered, i) for i in range(1, 7)],
                         [chain.scene_resolution(new, i) for i in range(1, 7)])

    def test_explicit_conflict_rejected_and_unlock_allows_change(self):
        self.locks([1, 2, 3])
        self.raw["chapters"][0]["resolution"] = {"width": 128, "height": 96}
        with self.assertRaisesRegex(ValueError, "pinned.*64x64.*Unlock"):
            self.plan()
        chain._atomic_json(chain._run_editorial_path("chapter_delivery"), fixture["make_editorial"]())
        self.assertEqual(chain.scene_resolution(self.plan(), 1), {"width": 128, "height": 96})

    def test_conflicting_saved_sizes_in_one_chapter_rejected(self):
        self.locks([1, 2], {2: {"width": 128, "height": 96}})
        with self.assertRaisesRegex(ValueError, "locked saved scenes at different resolutions"):
            self.plan()

    def test_lock_does_not_waive_prompt_or_model_identity(self):
        old = self.locks([1])
        self.raw["shots"][0]["prompt"] = "Changed identity"
        new = self.plan(128, 96)
        self.assertTrue(chain._scene_dependency_diffs(
            chain._scene_dependency_record(old, 1, None),
            chain._scene_dependency_record(new, 1, None)))
        new["compatibility"]["generation_fingerprint"] = "other-model"
        self.assertTrue(chain._scene_dependency_diffs(
            chain._scene_dependency_record(old, 2, None),
            chain._scene_dependency_record(new, 2, None)))

    def test_pin_before_first_chapter_survives_recovery(self):
        self.locks([1])
        self.raw["chapters"] = self.raw["chapters"][1:]
        plan = self.plan(128, 96)
        restored_raw = chain._effective_editor_plan(plan)
        self.assertEqual(restored_raw["chapters"][0]["resolution"], {"width": 64, "height": 64})
        chain._atomic_json(chain._run_editorial_path("chapter_delivery"), fixture["make_editorial"]())
        self.assertEqual(chain.scene_resolution(self.plan(128, 96, raw=restored_raw), 1),
                         {"width": 64, "height": 64})

    def test_native_context_cross_size_rejected_in_preflight(self):
        self.raw["chapters"][1]["resolution"] = {"width": 128, "height": 96}
        self.raw["shots"][3]["context_length"] = 5
        self.raw["shots"][3]["audio_context_length"] = 0
        for mode in ("masked_av", "audio_feathered_av", "latent_guide"):
            with self.subTest(mode=mode):
                plan = self.plan(mode=mode)
                with self.assertRaisesRegex(ValueError, "across different chapter resolutions"):
                    chain._validate_scene_resolution_boundary(plan, 4)
                _, report = chain._preflight_chain(plan, scene_range="4", verify_resume_history=False)
                self.assertFalse(report["ok"])
                self.assertIn("across different chapter resolutions", json.dumps(report))
        self.raw["shots"][3]["context_length"] = 0
        chain._validate_scene_resolution_boundary(self.plan(mode="masked_av"), 4)

    def test_new_lock_fences_an_already_queued_plan(self):
        queued = self.plan(128, 96)
        self.locks([1])
        with self.assertRaisesRegex(ValueError, "differs from the queued Plan"):
            chain._require_chapter_resolution_locks(queued)
        # Resolving again picks up the saved Chapter 1 size without changing Chapter 2.
        chain._require_chapter_resolution_locks(self.plan(128, 96))

    def test_missing_geometry_and_stale_identity_are_not_silently_adopted(self):
        plan = self.locks([1])
        path = chain._artifact_paths(plan, 1)["metadata"]
        metadata = chain._read_json(path)
        metadata.pop("scene_dependency")
        metadata.pop("compatibility")
        chain._atomic_json(path, metadata)
        with self.assertRaisesRegex(ValueError, "Cannot verify the saved resolution"):
            self.plan()
        metadata["segment"]["id"] = "wrong_scene"
        chain._atomic_json(path, metadata)
        with self.assertRaisesRegex(ValueError, "no longer matches"):
            self.plan()

    def test_context_rejects_wrong_conditioning_geometry(self):
        self.raw["chapters"][1]["resolution"] = {"width": 128, "height": 96}
        plan = self.plan()
        with patch.object(chain, "_streams_from_latent", return_value=(torch.zeros(1, 4, 2, 4, 4), None)):
            with self.assertRaisesRegex(ValueError, "Wire Current Shot width/height"):
                chain.MiniMaxH3ChainContext().apply({"plan": plan, "index": 4}, [], None, {})
        with self.assertRaisesRegex(ValueError, "decoded dimensions"):
            chain.MiniMaxH3ChainSegmentSave().save(
                {"plan": plan, "index": 4}, torch.zeros(39, 64, 64, 3), {})

    def test_chapter_exports_retain_each_saved_resolution(self):
        segments = [fixture["make_segment"](self.root, i) for i in range(1, 7)]
        for i, segment in enumerate(segments):
            # Existing checkpoints expose geometry through their dependency record.
            segment["scene_dependency"] = {"scopes": {"global_generation": {
                "width": 64 if i < 3 else 128, "height": 64 if i < 3 else 96}}}
        manifest = fixture["make_manifest"](segments, True)
        manifest["compatibility"].update(width=128, height=96)
        chain._atomic_json(chain._run_editorial_path("chapter_delivery"), fixture["make_editorial"]())
        one, path = chain._chapter_manifest_from_manifest(manifest, 1)
        before = pathlib.Path(path).read_bytes()
        two, _ = chain._chapter_manifest_from_manifest(manifest, 2)
        self.assertEqual(one["compatibility"]["width"], 64)
        self.assertEqual(two["compatibility"]["width"], 128)
        self.assertEqual(before, pathlib.Path(path).read_bytes())
        with self.assertRaisesRegex(ValueError, "Export each chapter separately"):
            chain.MiniMaxH3ChainAssemble().assemble(manifest, "none", "mixed", 192)

    def test_real_checkpoints_resume_chapter_exports_and_review_preview(self):
        self.raw["shots"] = [
            {"id": f"scene_{i:02d}", "prompt": f"Scene {i}", "length": 5,
             "context_length": 0, "audio_context_length": 0} for i in (1, 2)]
        self.raw["chapters"][1]["start_scene_id"] = "scene_02"
        self.raw["chapters"][1]["resolution"] = {"width": 128, "height": 96}
        plan = self.plan()
        editorial = {"scene_order": [{"scene": i, "scene_id": f"scene_{i:02d}"} for i in (1, 2)],
                     "chapters": self.raw["chapters"]}
        chain._atomic_json(chain._run_editorial_path("chapter_delivery"), editorial)
        with patch.object(chain, "_streams_from_latent", side_effect=lambda latent: latent["samples"]):
            for index in (1, 2):
                state = chain._initial_state(plan, index)
                width, height = (chain.scene_resolution(plan, index)[key] for key in ("width", "height"))
                latent = {"samples": [torch.zeros(1, 24, 2, height // 16, width // 16),
                                       torch.zeros(1, 32, 2, 9)]}
                audio = {"waveform": torch.zeros(1, 2, round(5 / 24 * 8000)), "sample_rate": 8000}
                segment = chain.MiniMaxH3ChainSegmentSave().save(
                    state, torch.full((5, height, width, 3), index / 3), latent, audio)["result"][0]
                if index == 1:
                    original = pathlib.Path(chain._artifact_paths(plan, 1)["metadata"]).read_bytes()
                else:
                    self.assertEqual(segment["resolution"], {"width": 128, "height": 96})
                    self.assertEqual(original, pathlib.Path(chain._artifact_paths(plan, 1)["metadata"]).read_bytes())
            manifest = chain._partial_manifest(state, segment)
            for number in (1, 2):
                chapter, _ = chain._chapter_manifest_from_manifest(manifest, number)
                result = chain.MiniMaxH3ChainAssemble().assemble(chapter, "none", "chapter-test", 192)
                with chain.av.open(result["result"][0]) as container:
                    frames = list(container.decode(video=0))
                self.assertEqual(len(frames), 5)
                self.assertEqual((frames[0].width, frames[0].height), (64, 64) if number == 1 else (128, 96))
            preview, warning = chain._assemble_review_partial(state, segment, "none", None)
            self.assertFalse(warning)
            with chain.av.open(preview) as container:
                frames = list(container.decode(video=0))
            self.assertEqual(len(frames), 5, "mixed-size review displays the current chapter only")
            self.assertEqual((frames[0].width, frames[0].height), (128, 96))
            self.assertEqual(len(state["segments"]), 1, "review does not truncate execution history")

    def test_deferred_upscale_reads_source_scene_geometry(self):
        upscale = importlib.import_module(chain.__package__ + ".upscale_nodes")
        source = {"index": 1, "raw_frames": 5, "delivered_frames": 5,
                  "resolution": {"width": 64, "height": 96}}
        state = {"index": 1, "source_manifest": {
            "segments": [source], "compatibility": {"width": 128, "height": 128}}}
        streams = [torch.zeros(1, 24, 2, 6, 4), torch.zeros(1, 32, 2, 9)]
        with patch.object(upscale, "_load_source_tensors", return_value={}), \
                patch.object(upscale, "_source_latent", return_value=({"samples": streams}, "test")), \
                patch.object(chain, "_streams_from_latent", return_value=streams):
            result = upscale.MiniMaxH3ChainUpscaleCurrent().current(state)
        self.assertEqual(result[7:9], (64, 96))

    def test_validation_and_cache_invalidation(self):
        for value in ({"width": 65, "height": 64}, {"width": True, "height": 64},
                      {"width": 64}, {"width": 0, "height": 64}, "128x96"):
            self.raw["chapters"][0]["resolution"] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.plan()
        self.raw["chapters"][0].pop("resolution")
        serialized = json.dumps(self.raw)
        self.assertTrue(math.isnan(chain.MiniMaxH3ChainPlan.IS_CHANGED(serialized)))
        self.assertTrue(math.isnan(chain.MiniMaxH3ChainPlanStudio.IS_CHANGED(plan_json=serialized)))


if __name__ == "__main__":
    unittest.main()
