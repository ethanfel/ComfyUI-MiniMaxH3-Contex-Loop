#!/usr/bin/env python3
"""Focused mixed-policy checkpoint branch activation regression."""

import asyncio
import importlib.util
import json
import pathlib
import tempfile


ROOT = pathlib.Path(__file__).resolve().parents[1]
HELPERS_PATH = ROOT / "tests" / "_checkpoint_revision_unit_test.py"
spec = importlib.util.spec_from_file_location(
    "h3_checkpoint_activation_helpers", HELPERS_PATH)
helpers = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helpers)


async def check():
    with tempfile.TemporaryDirectory() as temporary:
        helpers.folder_paths.output_directory = temporary
        run = pathlib.Path(temporary) / "h3_chains" / "mixed_policy"
        first = "a" * 32
        second = "b" * 32
        first_meta, _ = helpers.write_revision(
            run, 1, first, 1001, active=True, run_name="mixed_policy")
        helpers.write_revision(
            run, 2, second, 1002, predecessor=first_meta,
            run_name="mixed_policy", compatibility={
                "context_length": 39,
                "audio_context_length": 39,
                "audio_mode": "generated_audio",
            })
        selection = {
            "run_name": "mixed_policy",
            "resume_scene": 3,
            "revisions": [
                {"scene": 1, "revision": first},
                {"scene": 2, "revision": second},
            ],
        }

        strict = await helpers.chain._restore_checkpoint_revisions(
            helpers.JsonRequest(selection))
        assert strict.status == 400
        assert "different Plan compatibility" in json.loads(
            strict.text)["error"]
        assert not (run / "checkpoints" / "clip_0002.json").exists()

        promoted = await helpers.chain._restore_checkpoint_revisions(
            helpers.JsonRequest({**selection, "activate_only": True}))
        assert promoted.status == 200
        assert json.loads(promoted.text)["activate_only"] is True
        assert json.loads((
            run / "checkpoints" / "clip_0002.json").read_text())[
                "segment"]["revision"] == second
        graph = helpers.chain.CheckpointGraphManager(
            temporary).graph("mixed_policy")
        assert [item["revision"] for item in graph["revisions"]
                if item["active"]] == [first, second]
        assert graph["branches"][0]["active"] is True

        # Editorial chapters are independent activation scopes. A Chapter 2
        # branch may retain provenance to an inactive Chapter 1 revision, but
        # promoting it must not rewrite Chapter 1's active pointers.
        scoped_run = pathlib.Path(temporary) / "h3_chains" / "chapter_scopes"
        one = "1" * 32
        two_active = "2" * 32
        two_other = "3" * 32
        three_active = "4" * 32
        four_active = "5" * 32
        three_other = "6" * 32
        four_other = "7" * 32
        one_meta, _ = helpers.write_revision(
            scoped_run, 1, one, 2001, active=True,
            run_name="chapter_scopes")
        two_active_meta, _ = helpers.write_revision(
            scoped_run, 2, two_active, 2002, active=True,
            predecessor=one_meta, run_name="chapter_scopes")
        two_other_meta, _ = helpers.write_revision(
            scoped_run, 2, two_other, 2003, predecessor=one_meta,
            run_name="chapter_scopes")
        three_active_meta, _ = helpers.write_revision(
            scoped_run, 3, three_active, 2004, active=True,
            predecessor=two_active_meta, run_name="chapter_scopes")
        helpers.write_revision(
            scoped_run, 4, four_active, 2005, active=True,
            predecessor=three_active_meta, run_name="chapter_scopes")
        three_other_meta, _ = helpers.write_revision(
            scoped_run, 3, three_other, 2006,
            predecessor=two_other_meta, run_name="chapter_scopes",
            context_length=0, audio_context_length=0,
            generated_continuity="off")
        helpers.write_revision(
            scoped_run, 4, four_other, 2007,
            predecessor=three_other_meta, run_name="chapter_scopes")

        (scoped_run / "plan.json").write_text(json.dumps({
            "plan_hash": "chapter-scope-test",
            "shots": [{"id": "scene_%d" % scene} for scene in range(1, 5)],
        }), encoding="utf-8")
        helpers.chain._save_run_editorial_document({
            "run_name": "chapter_scopes",
            "scene_order": [
                {"scene": scene, "scene_id": "scene_%d" % scene}
                for scene in range(1, 5)
            ],
            "chapters": [
                {"id": "chapter_1", "title": "Chapter 1",
                 "start_scene_id": "scene_1"},
                {"id": "chapter_2", "title": "Chapter 2",
                 "start_scene_id": "scene_3"},
            ],
        })

        chapter_two = await helpers.chain._restore_checkpoint_revisions(
            helpers.JsonRequest({
                "run_name": "chapter_scopes",
                "resume_scene": 5,
                "scope_start_scene": 3,
                "scope_end_scene": 4,
                "activate_only": True,
                "revisions": [
                    {"scene": 3, "revision": three_other},
                    {"scene": 4, "revision": four_other},
                ],
            }))
        assert chapter_two.status == 200
        chapter_two_body = json.loads(chapter_two.text)
        assert chapter_two_body["scope_start_scene"] == 3
        assert chapter_two_body["scope_end_scene"] == 4
        assert chapter_two_body["retired_scope_pointers"] == 0
        pointers = {
            scene: json.loads((scoped_run / "checkpoints" /
                               ("clip_%04d.json" % scene)).read_text())["segment"][
                                   "revision"]
            for scene in range(1, 5)
        }
        assert pointers == {
            1: one, 2: two_active, 3: three_other, 4: four_other}

        manifest = helpers.chain._checkpoint_selection_manifest({
            "run_name": "chapter_scopes",
            "lineage": [
                {"scene": 1, "revision": one},
                {"scene": 2, "revision": two_active},
                {"scene": 3, "revision": three_other},
                {"scene": 4, "revision": four_other},
            ],
            "scope_start_scene": 3,
            "scope_end_scene": 4,
        })
        assert [item["revision"] for item in manifest["segments"]] == [
            one, two_active, three_other, four_other]
        assert manifest["selection_scope"] == {
            "start_scene": 3, "end_scene": 4}
        scoped_graph = helpers.chain.CheckpointGraphManager(
            temporary).graph("chapter_scopes")
        active_branches = [branch for branch in scoped_graph["branches"]
                           if branch["active"]]
        assert [[item["scene"] for item in branch["path"]]
                for branch in active_branches] == [[3, 4], [1, 2]]
        chapter_root = next(
            item for item in scoped_graph["revisions"]
            if item["scene"] == 3 and item["revision"] == three_other)
        assert chapter_root["parent"] is None
        assert chapter_root["dependencies"] == []
        explicit_root = next(
            item for item in scoped_graph["revisions"]
            if item["scene"] == 3 and item["revision"] == three_active)
        assert explicit_root["parent"] is None
        assert explicit_root["dependencies"] == [
            {"scene": 2, "revision": two_active}]
        protected = helpers.chain.CheckpointGraphManager(
            temporary).deletion_preview(
                "chapter_scopes", 2, two_active)
        assert not protected["allowed"]
        assert any(item["revision"] == three_active
                   for item in protected["dependents"])

        chapter_one = await helpers.chain._restore_checkpoint_revisions(
            helpers.JsonRequest({
                "run_name": "chapter_scopes",
                "resume_scene": 3,
                "scope_start_scene": 1,
                "scope_end_scene": 2,
                "activate_only": True,
                "revisions": [
                    {"scene": 1, "revision": one},
                    {"scene": 2, "revision": two_other},
                ],
            }))
        assert chapter_one.status == 200
        pointers = {
            scene: json.loads((scoped_run / "checkpoints" /
                               ("clip_%04d.json" % scene)).read_text())["segment"][
                                   "revision"]
            for scene in range(1, 5)
        }
        assert pointers == {
            1: one, 2: two_other, 3: three_other, 4: four_other}
        independent = helpers.chain.CheckpointGraphManager(
            temporary).deletion_preview(
                "chapter_scopes", 2, two_other)
        assert independent["allowed"] and independent["rollback"]

        incompatible_dependency = await (
            helpers.chain._restore_checkpoint_revisions(
                helpers.JsonRequest({
                    "run_name": "chapter_scopes",
                    "resume_scene": 5,
                    "scope_start_scene": 3,
                    "scope_end_scene": 4,
                    "activate_only": True,
                    "revisions": [
                        {"scene": 3, "revision": three_active},
                        {"scene": 4, "revision": four_active},
                    ],
                })))
        assert incompatible_dependency.status == 400
        assert "explicitly depends on scene 2" in json.loads(
            incompatible_dependency.text)["error"]


if __name__ == "__main__":
    asyncio.run(check())
    print("H3 checkpoint activation: mixed policies and independent chapter scopes pass")
