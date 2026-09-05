"""Chapter recovery pins and edited-vs-source timeline regression tests."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from _checkpoint_revision_unit_test import chain, folder_paths, write_revision


class ChapterRecoverySafetyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        folder_paths.output_directory = self.temp.name
        self.run = Path(self.temp.name) / "h3_chains" / "revision_test"
        self.old = "a" * 32
        self.metadata, self.files = write_revision(
            self.run, 1, self.old, 1, active=True, audio_context_length=0)
        segment = self.metadata["segment"]
        self.manifest = {
            "format": "h3_chain_manifest_v3", "run_name": "revision_test",
            "plan_hash": "test", "compatibility": {"continuation_mode": "guide"},
            "clip_count": 1, "segments": [segment],
            "total_delivered_frames": segment["delivered_frames"],
        }
        write_revision(self.run, 1, "b" * 32, 2, active=True, audio_context_length=0)
        self.manager = chain.CheckpointGraphManager(self.temp.name)

    def test_sealing_invalidates_delete_preview_and_preserves_recovery(self):
        before = self.manager.deletion_preview("revision_test", 1, self.old)
        self.assertTrue(before["allowed"])
        snapshot, path = chain._chapter_manifest_from_manifest(self.manifest, 1)
        pinned = self.manager.deletion_preview("revision_test", 1, self.old)
        self.assertFalse(pinned["allowed"])
        self.assertEqual(pinned["chapter_references"][0]["snapshot"], snapshot["chapter_manifest_id"])
        self.assertIn("Sealed Chapter 1", pinned["blockers"][0])
        with self.assertRaises(ValueError):
            self.manager.delete("revision_test", 1, self.old, before["snapshot"])
        recovered, _ = chain._load_chapter_manifest("revision_test", 1, snapshot["chapter_manifest_id"])
        self.assertEqual(recovered["segments"][0]["revision"], self.old)
        self.assertTrue(Path(path).is_file())
        self.assertTrue(self.manager.deletion_preview("revision_test", 1, "b" * 32)["allowed"])

    def test_selected_alternate_and_archive_paths_are_pinned(self):
        snapshot, path = chain._chapter_manifest_from_manifest(self.manifest, 1)
        candidate = "c" * 32
        metadata, _ = write_revision(self.run, 1, candidate, 3, audio_context_length=0,
                                     recovery_archive=True)
        for references in [
            {"editorial": {"replacements": [{"scene": 1, "alternate_revision": candidate, "base_revision": self.old}]}},
            # A legacy snapshot may identify an input by path, without its revision.
            {"archives": {"workflow": metadata["archives"]["workflow"]}},
        ]:
            with self.subTest(references=references):
                modified = copy.deepcopy(snapshot)
                modified.update(references)
                Path(path).write_text(json.dumps(modified))
                preview = self.manager.deletion_preview("revision_test", 1, candidate)
                self.assertFalse(preview["allowed"])
                self.assertTrue(preview["chapter_references"])

    def test_unreadable_snapshot_fails_closed(self):
        _, path = chain._chapter_manifest_from_manifest(self.manifest, 1)
        Path(path).write_text("{incomplete")
        preview = self.manager.deletion_preview("revision_test", 1, "b" * 32)
        self.assertFalse(preview["allowed"])
        self.assertIn("Cannot verify sealed chapter", preview["blockers"][0])

    def test_deleted_input_cannot_be_sealed_from_stale_selection(self):
        preview = self.manager.deletion_preview("revision_test", 1, self.old)
        self.manager.delete("revision_test", 1, self.old, preview["snapshot"])
        scoped = dict(self.manifest, format=chain.CHAPTER_MANIFEST_FORMAT,
                      chapter={"number": 1, "id": "one", "title": "One"})
        with self.assertRaises((ValueError, FileNotFoundError)):
            chain._persist_chapter_manifest(scoped)
        self.assertEqual(list(self.run.glob("chapters/*/manifests/*.json")), [])

    def test_chapter_origin_uses_full_edited_timeline_not_raw_audio_offset(self):
        segments = []
        for index in range(1, 9):
            metadata, _ = write_revision(self.run, index, "%032x" % index, index,
                                         audio_context_length=0)
            segment = metadata["segment"]
            segment["raw_frames"] = segment["delivered_frames"] = 13
            segments.append(segment)
        editorial = {
            "format": "h3_chain_editorial_v1", "run_name": "revision_test",
            "scene_order": [{"scene": i, "scene_id": s["id"]} for i, s in enumerate(segments, 1)],
            "chapters": [{"id": "one", "title": "One", "start_scene": 1, "start_scene_id": segments[0]["id"]},
                         {"id": "two", "title": "Two", "start_scene": 5, "start_scene_id": segments[4]["id"]}],
            "trims": [{"scene": 1, "scene_id": segments[0]["id"], "out_frame": 9}],
            "placements": [],
            "subtitles": {"mode": "preview_srt", "asset_id": "song", "offset_seconds": 0},
        }
        manifest = dict(self.manifest, segments=segments, clip_count=8,
                        total_delivered_frames=104, editorial=editorial)
        for gap in (False, True):
            if gap:
                # Shift the whole timeline: collision resolution pushes all following scenes.
                editorial["placements"] = [{"scene": i, "scene_id": s["id"], "start_frame": 24 + 13 * (i - 1)}
                                            for i, s in enumerate(segments, 1)]
            _, records, _ = chain._editorial_timeline_records("revision_test", segments, editorial)
            expected = next(r["start_frame"] for r in records if r.get("scene") == 5)
            chapter, _ = chain._chapter_manifest_from_manifest(manifest, 2)
            self.assertEqual(chapter["chapter"]["editorial_origin_frame"], expected)
            self.assertEqual(chapter["chapter"]["source_start_frame"], 52)
            if not gap:
                self.assertEqual(expected, 48)
            self.assertEqual(chapter["editorial"]["placements"][0]["start_frame"], 0)
            with patch.object(chain, "ProjectAssetStore") as store:
                store.return_value.load.return_value = {"assets": [{"id": "song", "kind": "audio",
                    "lyrics": "[00:02.50]Line one\n[00:03.50]Line two"}]}
                cues = chain._editorial_subtitle_cues("revision_test", chapter["editorial"], 52,
                                                     timeline_origin_frames=expected)
                if not gap:
                    self.assertAlmostEqual(cues[0]["start"], 0.5)


if __name__ == "__main__":
    unittest.main()
