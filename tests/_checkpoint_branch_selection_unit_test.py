#!/usr/bin/env python3
"""Chapter branch selection after rerender/rollback, using saved files only."""
import asyncio
import importlib.util
import json
import pathlib
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "branch_selection_helpers", ROOT / "tests/_checkpoint_revision_unit_test.py")
h = importlib.util.module_from_spec(spec)
spec.loader.exec_module(h)


async def check():
    with tempfile.TemporaryDirectory() as directory:
        h.folder_paths.output_directory = directory
        run = pathlib.Path(directory) / "h3_chains" / "branch_selection"
        tokens = {name: char * 32 for name, char in [
            ("root", "1"), ("old", "2"), ("candidate", "3"),
            ("tail", "4"), ("new", "5"), ("chapter", "6")]}

        def save(scene, name, predecessor=None, **kwargs):
            return h.write_revision(run, scene, tokens[name], scene,
                                    active=True, predecessor=predecessor,
                                    run_name=run.name, **kwargs)[0]

        root = save(1, "root")
        old = save(2, "old", root)
        candidate = save(3, "candidate", old, context_length=0,
                         audio_context_length=44, generated_continuity="off")
        tail = save(4, "tail", candidate)
        save(5, "chapter", tail, context_length=0,
             audio_context_length=0, generated_continuity="off")
        (run / "editorial.json").write_text(json.dumps({
            "scene_order": [{"scene":scene, "scene_id":f"scene_{scene}"}
                            for scene in range(1, 6)],
            "chapters": [{"id": "one", "start_scene": 1, "start_scene_id":"scene_1"},
                         {"id": "two", "start_scene": 5, "start_scene_id":"scene_5"}]}))
        save(2, "new", root)
        before = {str(path): path.read_bytes() for path in run.rglob("*") if path.is_file()}
        manager = h.chain.CheckpointGraphManager(directory)
        graph = manager.graph(run.name)
        active = {(row["scene"], row["revision"]) for row in graph["revisions"] if row["active"]}
        assert active == {(1, tokens["root"]), (2, tokens["new"]), (5, tokens["chapter"])}
        branch = next(row for row in graph["branches"] if row["leaf_revision"] == tokens["new"])
        assert branch["attribution_slot"]["candidates"] == [
            {"scene": 3, "revision": tokens["candidate"]}]
        listing = h.chain._saved_checkpoint_listing(run.name, include_graph=False)
        assert [row["scene"] for row in listing["checkpoints"]] == [1, 2, 5]
        assert [row["scene"] for row in listing["inactive_checkpoints"]] == [3, 4]
        assert h.chain._saved_scene_prefix_length({"run_name":run.name, "shots":[{}] * 5}) == 2
        context_sources = h.chain._resume_context_predecessors
        h.chain._resume_context_predecessors = lambda *_args: {"scenes":[]}
        try:
            try:
                h.chain._load_resume_state({"run_name":run.name}, 5, verify_history=False)
            except ValueError as exc:
                assert "inactive" in str(exc)
            else:
                raise AssertionError("resume accepted the old branch despite disabled history checks")
        finally:
            h.chain._resume_context_predecessors = context_sources
        assert all(pathlib.Path(path).read_bytes() == data for path, data in before.items())
        deletion = manager.deletion_preview(run.name, 4, tokens["tail"])
        assert not deletion["allowed"] and any("stale active pointer" in text for text in deletion["blockers"])

        # Roll back to an existing (non-leaf) scene. Retained children must not
        # hide this active tip or candidates from another branch.
        h.write_revision(run, 3, "7" * 32, 7, predecessor={
            "segment": {"revision":tokens["new"], "checkpoint_sha256":"new-parent"}},
            run_name=run.name, context_length=0, audio_context_length=0,
            generated_continuity="off")
        response = await h.chain._restore_checkpoint_revisions(h.JsonRequest({
            "run_name":run.name, "activate_only":True, "resume_scene":3,
            "scope_start_scene":1, "scope_end_scene":4,
            "revisions":[{"scene":1,"revision":tokens["root"]},
                         {"scene":2,"revision":tokens["old"]}]}))
        assert response.status == 200, response.text
        graph = manager.graph(run.name)
        assert any(row["active"] and row["leaf_scene"] == 2 for row in graph["branches"])
        tip = next(row for row in graph["branches"] if row["active"] and row["leaf_scene"] == 2)
        assert {"scene":3, "revision":"7" * 32} in tip["attribution_slot"]["candidates"]
        assert any(row["scene"] == 5 and row["active"] for row in graph["revisions"])
        assert all(pathlib.Path(path).read_bytes() == data for path, data in before.items()
                   if not pathlib.Path(path).name in {"clip_0001.json", "clip_0002.json", "clip_0003.json", "clip_0004.json"})

        record = {"_metadata": {}, "_segment": {
            "resolved_context_length":0, "resolved_audio_context_length":0},
            "context_length":39, "audio_context_length":39}
        assert manager._attributable_without_predecessor(record)
        record["_metadata"]["scene_dependency"] = {"scopes":{"incoming_boundary":{
            "context_length":39, "audio_context_length":39, "generated_continuity":"on"}}}
        assert manager._attributable_without_predecessor(record), "resolved saved lengths beat old defaults"
        record["_segment"]["resolved_audio_context_length"] = 39
        assert not manager._attributable_without_predecessor(record), "audio context remains protected"
        record["_segment"]["generated_continuity"] = "off"
        assert manager._attributable_without_predecessor(record)
        record["_segment"].pop("generated_continuity")
        record["_metadata"] = {}
        assert not manager._attributable_without_predecessor(record), "unknown audio policy is not off"
        record["_segment"]["resolved_context_length"] = "broken"
        assert not manager._attributable_without_predecessor(record)
    print("H3 branch selection: stale pointers, chapters, rollback, reuse and preservation pass")


if __name__ == "__main__":
    asyncio.run(check())
