#!/usr/bin/env python3
"""Legacy shared recovery snapshots must remain readable and never be deleted."""

import importlib.util
import json
import pathlib
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "checkpoint_legacy_archives", ROOT / "checkpoint_manager.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class LegacyArchivesTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.output = pathlib.Path(self.temporary.name)
        self.run = self.output / "h3_chains" / "legacy_run"
        self.manager = module.CheckpointGraphManager(str(self.output))
        self.token = "a" * 32
        self.archives = {}
        for key in ("plan", "workflow", "api_prompt"):
            target = self.run / (key + ".json")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps({"preserve": key}), encoding="utf-8")
            self.archives[key] = str(target.relative_to(self.output))
        self.metadata = self.write_revision(self.token, self.archives)

    def write_revision(self, token, archives):
        stem = "clip_0001." + token
        segment = {"index": 1, "id": "scene_1", "revision": token}
        for key, folder, suffix in (
                ("segment", "segments", ".mp4"),
                ("checkpoint", "checkpoints", ".safetensors"),
                ("prompt_file", "segments", ".prompt.txt")):
            target = self.run / folder / (stem + suffix)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((key + token).encode())
            segment[key] = str(target.relative_to(self.output))
        target = self.run / "checkpoints" / (stem + ".json")
        segment["revision_metadata"] = str(target.relative_to(self.output))
        target.write_text(json.dumps({
            "run_name": "legacy_run", "segment": segment,
            "archives": archives,
        }), encoding="utf-8")
        return target

    def update_metadata(self, change):
        metadata = json.loads(self.metadata.read_text(encoding="utf-8"))
        change(metadata)
        self.metadata.write_text(json.dumps(metadata), encoding="utf-8")

    def test_single_legacy_revision_lists_and_deletes_without_shared_files(self):
        graph = self.manager.graph("legacy_run")
        self.assertEqual(graph["summary"]["revision_count"], 1)
        self.assertEqual(graph["summary"]["broken_count"], 0)
        preview = self.manager.deletion_preview("legacy_run", 1, self.token)
        self.assertTrue(preview["allowed"])
        archives = [item for item in preview["files"]
                    if item["kind"].startswith("archive_")]
        self.assertEqual(len(archives), 3)
        self.assertTrue(all(item["shared"] and not item["owned"]
                            for item in archives))
        before = {value: (self.output / value).read_bytes()
                  for value in self.archives.values()}
        self.manager.delete("legacy_run", 1, self.token, preview["snapshot"])
        self.assertFalse(self.metadata.exists())
        for value, content in before.items():
            self.assertEqual((self.output / value).read_bytes(), content)

    def test_mixed_legacy_and_revision_archives(self):
        token = "b" * 32
        archives = {}
        for key in self.archives:
            target = self.run / "recovery_archives" / token / (key + ".json")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("{}", encoding="utf-8")
            archives[key] = str(target.relative_to(self.output))
        self.write_revision(token, archives)
        graph = self.manager.graph("legacy_run")
        self.assertEqual(graph["summary"]["revision_count"], 2)
        preview = self.manager.deletion_preview("legacy_run", 1, token)
        owned = {item["path"] for item in preview["files"] if item["owned"]}
        self.assertTrue(set(archives.values()).issubset(owned))
        self.manager.delete("legacy_run", 1, token, preview["snapshot"])
        self.assertTrue(all(not (self.output / value).exists()
                            for value in archives.values()))
        self.assertTrue(all((self.output / value).is_file()
                            for value in self.archives.values()))

    def test_missing_legacy_snapshot_does_not_hide_checkpoints(self):
        (self.run / "workflow.json").unlink()
        graph = self.manager.graph("legacy_run")
        self.assertEqual(graph["summary"]["revision_count"], 1)
        self.assertIn("Recovery workflow snapshot",
                      graph["revisions"][0]["missing_files"])

    def test_unexpected_archive_paths_still_rejected(self):
        for value in ("h3_chains/other_run/plan.json",
                      "h3_chains/legacy_run/editorial.json",
                      "h3_chains/legacy_run/workflow.json",
                      "../outside.json"):
            with self.subTest(value=value):
                self.update_metadata(lambda metadata: metadata["archives"].update(
                    plan=value))
                with self.assertRaises(ValueError):
                    self.manager.graph("legacy_run")
                with self.assertRaises(ValueError):
                    self.manager.deletion_preview("legacy_run", 1, self.token)

    def test_shared_snapshot_cannot_be_claimed_as_revision_media(self):
        self.update_metadata(lambda metadata: metadata["segment"].update(
            prompt_file=self.archives["plan"]))
        with self.assertRaises(ValueError):
            self.manager.deletion_preview("legacy_run", 1, self.token)

    def test_shared_snapshot_symlink_does_not_grant_ownership(self):
        target = self.run / "plan.json"
        target.unlink()
        try:
            target.symlink_to(self.run / "workflow.json")
        except OSError as error:
            self.skipTest(str(error))
        with self.assertRaises(ValueError):
            self.manager.deletion_preview("legacy_run", 1, self.token)


if __name__ == "__main__":
    unittest.main()
