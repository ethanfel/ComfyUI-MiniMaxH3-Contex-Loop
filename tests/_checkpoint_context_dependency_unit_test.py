#!/usr/bin/env python3
"""Legacy AV audio defaults must not invent a predecessor dependency."""
import importlib.util
import json
from pathlib import Path
import tempfile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "context_dependency_helpers", ROOT / "tests/_checkpoint_revision_unit_test.py")
h = importlib.util.module_from_spec(spec)
spec.loader.exec_module(h)


def main():
    with tempfile.TemporaryDirectory() as directory:
        h.folder_paths.output_directory = directory
        run = Path(directory) / "h3_chains" / "context_dependency"
        manager = h.chain.CheckpointGraphManager(directory)
        parent, _ = h.write_revision(run, 1, "1" * 32, 1, run_name=run.name)
        target, _ = h.write_revision(run, 1, "2" * 32, 2, run_name=run.name, active=True)
        candidate, _ = h.write_revision(
            run, 2, "3" * 32, 3, predecessor=parent, run_name=run.name,
            context_length=0, audio_context_length=39, generated_continuity="on")
        segment = candidate["segment"]
        segment.update({"resolved_context_length":0,
                        "resolved_audio_context_length":39,
                        "continuation_mode":"audio_feathered_av"})
        candidate["scene_dependency"]["scopes"]["incoming_boundary"].update({
            "continuation_mode":"audio_feathered_av"})
        path = Path(directory) / segment["revision_metadata"]
        path.write_text(json.dumps(candidate))
        before = {p:p.read_bytes() for p in run.rglob("*") if p.is_file()}
        graph = manager.graph(run.name)
        record = next(row for row in graph["revisions"] if row["revision"] == "3" * 32)
        assert record["context_length"] == record["audio_context_length"] == 0
        branch = next(row for row in graph["branches"] if row["leaf_revision"] == "2" * 32)
        assert {"scene":2, "revision":"3" * 32} in branch["attribution_slot"]["candidates"]
        source = {"index":1, "delivered_frames":141, "_editorial_out_frames":90}
        assert h.chain._editorial_dependency_mismatches(segment, 2, {1:source}) == []
        assert h.chain._editorial_dependency_sources(segment, 2) == set()
        saved_record = {"_metadata":candidate, "_segment":segment}
        for mode in h.chain.MASKED_CONTINUATION_MODES:
            segment["continuation_mode"] = mode
            assert manager._attributable_without_predecessor(saved_record), mode
        for mode in (*h.chain.GUIDE_CONTINUATION_MODES, "unknown_future_mode"):
            segment["continuation_mode"] = mode
            assert not manager._attributable_without_predecessor(saved_record), mode
        segment["continuation_mode"] = "guide"
        assert h.chain._editorial_dependency_mismatches(segment, 2, {1:source})
        assert h.chain._editorial_dependency_sources(segment, 2) == {1}
        segment["continuation_mode"] = "audio_feathered_av"
        segment["resolved_context_length"] = 39
        assert not manager._attributable_without_predecessor(saved_record)
        segment["resolved_context_length"] = 0
        # Explicit legacy source fields must not create phantom dependencies
        # when the saved AV early-return proves no audio was consumed.
        explicit = {**segment, "audio_context_source_scene":1,
                    "audio_context_lead_source_scene":1}
        assert h.chain._editorial_dependency_mismatches(explicit, 2, {1:source}) == []
        assert h.chain._editorial_dependency_sources(explicit, 2) == set()
        # But missing lengths on old records are not proof of independence.
        explicit.pop("resolved_audio_context_length")
        assert h.chain._editorial_dependency_mismatches(explicit, 2, {1:source})
        assert h.chain._editorial_dependency_sources(explicit, 2) == {1}
        assert all(p.read_bytes() == data for p, data in before.items())

        # The actual attach operation uses the same eligibility check and
        # shares immutable media. It must not make the new take project-active.
        attached = manager.attribute(run.name, 1, "2" * 32, 2, "3" * 32)
        assert attached["created"] is True
        assert all(p.read_bytes() == data for p, data in before.items())
        adopted = json.loads((run / "checkpoints" /
            ("clip_0002.%s.json" % attached["revision"])).read_text())
        assert adopted["segment"]["segment"] == segment["segment"]
        assert adopted["segment"]["checkpoint"] == segment["checkpoint"]
        assert not (run / "checkpoints/clip_0002.json").exists()
    print("Checkpoint audio dependency: legacy zero-prefix AV reuse, Guide protection, safe attribution pass")


if __name__ == "__main__":
    main()
