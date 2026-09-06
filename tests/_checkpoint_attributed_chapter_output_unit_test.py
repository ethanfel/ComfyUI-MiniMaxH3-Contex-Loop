#!/usr/bin/env python3
"""Attach a legacy zero-context take, then output only its mixed-size chapter."""
import importlib.util
import json
from pathlib import Path
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "attributed_chapter_helpers", ROOT / "tests/_checkpoint_local_output_unit_test.py")
h = importlib.util.module_from_spec(spec)
spec.loader.exec_module(h)
chain = h.chain


def main():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        h.h.folder_paths.output_directory = directory
        run = root / "h3_chains" / "attributed_chapter"
        metadata, lineage = [], []
        for scene in range(1, 10):
            compatibility = {
                "width":1344 if scene < 8 else 960,
                "height":768 if scene < 8 else 544, "fps":24,
                "audio_mode":"generated_audio", "context_length":39,
                "audio_context_length":39, "continuation_mode":"audio_feathered_av",
                "generation_fingerprint":f"catalog-{scene}",
            }
            item, _ = h.h.write_revision(
                run, scene, str(scene) * 32, scene, active=True,
                predecessor=metadata[-1] if metadata else None,
                run_name=run.name, compatibility=compatibility,
                context_length=5 if scene == 9 else 0, audio_context_length=0)
            metadata.append(item)
            lineage.append({"scene":scene, "revision":str(scene) * 32})
        previous, _ = h.h.write_revision(
            run, 9, "a" * 32, 90, run_name=run.name,
            predecessor=metadata[7], compatibility=metadata[8]["compatibility"],
            context_length=0, audio_context_length=0)
        candidate, _ = h.h.write_revision(
            run, 10, "b" * 32, 100, run_name=run.name, predecessor=previous,
            compatibility={**metadata[8]["compatibility"],
                           "generation_fingerprint":"older-catalog"},
            context_length=0, audio_context_length=39, generated_continuity="on")
        # Legacy AV saves retain a 39f audio default although the zero-video
        # early return consumed neither predecessor video nor audio.
        candidate["segment"].update({
            "resolved_context_length":0, "resolved_audio_context_length":39,
            "continuation_mode":"audio_feathered_av",
            "raw_frames":141, "delivered_frames":141})
        (root / candidate["segment"]["revision_metadata"]).write_text(json.dumps(candidate))
        (run / "plan.json").write_text(json.dumps({
            "run_name":run.name, "shots":[{"id":f"scene_{i}"} for i in range(1, 13)]}))
        (run / "editorial.json").write_text(json.dumps({
            "scene_order":[{"scene":i, "scene_id":f"scene_{i}"} for i in range(1, 13)],
            "chapters":[{"id":"one", "start_scene_id":"scene_1"},
                        {"id":"two", "start_scene_id":"scene_8"}],
        }))
        manager = chain.CheckpointGraphManager(directory)
        graph = manager.graph(run.name)
        before = h.snapshot(run)
        parent_branch = next(b for b in graph["branches"] if b["leaf_revision"] == "9" * 32)
        assert {"scene":10, "revision":"b" * 32} in parent_branch["attribution_slot"]["candidates"]
        attached = manager.attribute(run.name, 9, "9" * 32, 10, "b" * 32)
        assert attached["created"]
        after = h.snapshot(run)
        assert len(after) == len(before) + 1, sorted(set(after) - set(before))
        assert all(after[path] == value for path, value in before.items()), \
            "attachment must not rewrite media, original metadata or active pointers"
        alias = json.loads((run / "checkpoints" / f"clip_0010.{attached['revision']}.json").read_text())
        assert alias["segment"]["segment"] == candidate["segment"]["segment"]
        assert alias["segment"]["checkpoint"] == candidate["segment"]["checkpoint"]
        selection = {"run_name":run.name, "output_mode":"workflow_local",
                     "output_scope":"chapter", "scope_start_scene":8, "scope_end_scene":12,
                     "lineage":[*lineage, {"scene":10, "revision":attached["revision"]}]}
        # Calling the real node, not only the graph's candidate listing, is the
        # regression: chapter 1 must not participate in the geometry check.
        with patch.object(chain, "_atomic_json", side_effect=AssertionError("output wrote project files")):
            result = chain.MiniMaxH3ChainCheckpointManager().passthrough(json.dumps(selection))[0]
        assert [s["index"] for s in result["segments"]] == [8, 9, 10]
        assert result["segments"][-1]["revision"] == attached["revision"]
        assert result["segments"][-1]["delivered_frames"] == 141
        assert result["compatibility"]["width"] == 960
        assert h.snapshot(run) == after
        h.rejected(lambda: chain._checkpoint_selection_manifest({
            **selection, "output_scope":"project"}), "compatibility")
        # The unattached original and a genuinely different canvas remain
        # invalid; fixing scope must not remove lineage or geometry checks.
        h.rejected(lambda: chain._checkpoint_selection_manifest({
            **selection, "lineage":[*lineage, {"scene":10, "revision":"b" * 32}]}),
            "depends on")
        alias_path = run / "checkpoints" / f"clip_0010.{attached['revision']}.json"
        alias["compatibility"]["width"] = 1024
        alias_path.write_text(json.dumps(alias))
        h.rejected(lambda: chain._checkpoint_selection_manifest(selection), "compatible takes within this chapter")
    print("Attributed chapter output: 960x544 context-free candidate after 5f take, mixed earlier chapter, immutable media and compatibility guards pass")


if __name__ == "__main__":
    main()
