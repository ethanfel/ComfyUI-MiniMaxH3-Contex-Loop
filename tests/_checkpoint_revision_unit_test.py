#!/usr/bin/env python3
"""Standalone Review Gate checkpoint revision recovery and deletion checks."""

import asyncio
import hashlib
import importlib.util
import json
import pathlib
import sys
import tempfile
import types


ROOT = pathlib.Path(__file__).resolve().parents[1]
PACKAGE = "h3_checkpoint_revision_unit"

folder_paths = types.ModuleType("folder_paths")
folder_paths.output_directory = str(ROOT)
folder_paths.get_output_directory = lambda: folder_paths.output_directory
folder_paths.get_temp_directory = lambda: folder_paths.output_directory
folder_paths.get_input_directory = lambda: folder_paths.output_directory
folder_paths.get_annotated_filepath = lambda value: str(value)
sys.modules["folder_paths"] = folder_paths

server = types.ModuleType("server")
server.PromptServer = type("PromptServer", (), {"instance": None})
sys.modules["server"] = server

package = types.ModuleType(PACKAGE)
package.__path__ = [str(ROOT)]
sys.modules[PACKAGE] = package

shared_nodes = types.ModuleType(PACKAGE + ".nodes")
shared_nodes.MiniMaxH3MotionContext = object
shared_nodes._claim_inline_patch_ownership = lambda: "test patch owner"
shared_nodes._prepare_native_guide_conditioning = lambda *args: None
shared_nodes._resize = lambda *args: None
shared_nodes._streams_from_latent = lambda *args: None
sys.modules[shared_nodes.__name__] = shared_nodes

spec = importlib.util.spec_from_file_location(
    PACKAGE + ".chain_nodes", ROOT / "chain_nodes.py")
chain = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = chain
spec.loader.exec_module(chain)


class GetRequest:
    query = {"run_name": "revision_test"}


class JsonRequest:
    def __init__(self, body):
        self.body = body

    async def json(self):
        return self.body


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_revision(run, scene, token, seed, active=False, predecessor=None,
                   run_name="revision_test", compatibility=None,
                   context_length=None, audio_context_length=None,
                   generated_continuity=None):
    segments = run / "segments"
    checkpoints = run / "checkpoints"
    reviews = run / "reviews"
    for directory in (segments, checkpoints, reviews):
        directory.mkdir(parents=True, exist_ok=True)
    stem = "clip_%04d.%s" % (scene, token)
    segment_path = segments / (stem + ".mp4")
    prompt_path = segments / (stem + ".prompt.txt")
    checkpoint_path = checkpoints / (stem + ".safetensors")
    metadata_path = checkpoints / (stem + ".json")
    segment_path.write_bytes(("video-%d-%s" % (scene, token)).encode())
    prompt_path.write_text("prompt %d %s" % (scene, seed), encoding="utf-8")
    checkpoint_path.write_bytes(("latent-%d-%s" % (scene, token)).encode())
    context_length = (0 if scene == 1 else 39) if context_length is None else int(
        context_length)
    audio_context_length = (33 if scene == 1 else 44) if (
        audio_context_length is None) else int(audio_context_length)
    generated_continuity = ("on" if audio_context_length > 0 else "off") if (
        generated_continuity is None) else str(generated_continuity)
    segment = {
        "index": scene,
        "id": "scene_%d" % scene,
        "revision": token,
        "segment": str(segment_path.relative_to(folder_paths.output_directory)),
        "checkpoint": str(
            checkpoint_path.relative_to(folder_paths.output_directory)),
        "metadata": str((checkpoints / ("clip_%04d.json" % scene)).relative_to(
            folder_paths.output_directory)),
        "revision_metadata": str(
            metadata_path.relative_to(folder_paths.output_directory)),
        "prompt_file": str(prompt_path.relative_to(folder_paths.output_directory)),
        "raw_frames": 362,
        "delivered_frames": 340 if scene > 1 else 362,
        "prompt_prefix": "shared",
        "scene_prompt": "prompt %d %s" % (scene, seed),
        "prompt": "shared\nprompt %d %s" % (scene, seed),
        "prompt_hash": hashlib.sha256(
            ("shared\nprompt %d %s" % (scene, seed)).encode()).hexdigest(),
        "seed": str(seed),
        "steps": 8,
        "context_length": context_length,
        "audio_context_length": audio_context_length,
        "segment_sha256": digest(segment_path),
        "checkpoint_sha256": digest(checkpoint_path),
        "prompt_file_sha256": digest(prompt_path),
    }
    if predecessor is not None:
        previous = predecessor["segment"]
        segment["predecessor_revision"] = previous["revision"]
        segment["predecessor_checkpoint_sha256"] = previous[
            "checkpoint_sha256"]
    metadata = {
        "format": "h3_chain_segment_v3",
        "run_name": run_name,
        "compatibility": compatibility or {
            "context_length": 22,
            "audio_context_length": 22,
            "audio_mode": "generated_audio",
        },
        "scene_dependency": {
            "scopes": {
                "incoming_boundary": {
                    "context_length": context_length,
                    "audio_context_length": audio_context_length,
                    "generated_continuity": generated_continuity,
                },
            },
        },
        "segment": segment,
    }
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    review = reviews / (
        "clip_%04d.%s.audio.review.mp4" %
        (scene, segment["segment_sha256"][:12]))
    review.write_bytes(b"preview")
    if active:
        (checkpoints / ("clip_%04d.json" % scene)).write_text(
            json.dumps(metadata), encoding="utf-8")
    return metadata, {segment_path, prompt_path, checkpoint_path, metadata_path, review}


async def check():
    with tempfile.TemporaryDirectory() as temporary:
        folder_paths.output_directory = temporary
        run = pathlib.Path(temporary) / "h3_chains" / "revision_test"
        executable_source = {
            "shots": [{"id": "scene_1", "prompt": "first", "length": 39}],
        }
        executable = chain._normalize_plan(
            json.dumps(executable_source), "revision_test", 64, 64, 22,
            "video", "head", "disabled", "generated_audio", 22,
            2.0, 8, 7, 18, "model-stack", 0, "guide", None)
        executable_with_chapter = chain._normalize_plan(
            json.dumps({**executable_source, "chapters": [{
                "id": "chapter_1", "title": "Chapter 1",
                "start_scene_id": "scene_1", "text": "editorial only",
            }]}), "revision_test", 64, 64, 22, "video", "head",
            "disabled", "generated_audio", 22, 2.0, 8, 7, 18,
            "model-stack", 0, "guide", None)
        assert executable_with_chapter["plan_hash"] == executable["plan_hash"]
        assert "chapters" not in executable_with_chapter
        editorial = chain._save_run_editorial_document({
            "run_name": "revision_test",
            "scene_order": [
                {"scene": 1, "scene_id": "scene_1"},
                {"scene": 2, "scene_id": "scene_2"},
            ],
            "chapters": [{
                "id": "chapter_1", "title": "Chapter 1",
                "start_scene_id": "scene_1", "text": "lyrics and notes",
            }],
        })
        assert editorial["chapters"][0]["start_scene"] == 1
        old_one = "1" * 32
        new_one = "2" * 32
        old_two = "3" * 32
        new_two = "4" * 32
        old_one_meta, old_one_files = write_revision(run, 1, old_one, 101)
        new_one_meta, new_one_files = write_revision(
            run, 1, new_one, 201, active=True)
        old_two_meta, old_two_files = write_revision(
            run, 2, old_two, 102, predecessor=old_one_meta)
        new_two_meta, new_two_files = write_revision(
            run, 2, new_two, 202, active=True, predecessor=new_one_meta)

        # Exercise the listing worker synchronously in this fake server; the
        # route's asyncio.to_thread wakeup depends on ComfyUI's real event loop.
        payload = chain._saved_checkpoint_listing("revision_test")
        assert payload["editorial"]["chapters"][0]["text"] == "lyrics and notes"
        assert [item["revision"] for item in payload["checkpoints"]] == [
            new_one, new_two]
        assert len(payload["revisions"]) == 4
        assert sorted(item["revision"] for item in payload["revisions"]
                      if item["active"]) == [new_one, new_two]
        assert all(item["size_bytes"] > 0 for item in payload["revisions"])
        assert all(item.get("preview_video") for item in payload["revisions"])
        assert payload["summary"]["branch_count"] == 2
        assert len(payload["branches"]) == 2
        indexed = {(item["scene"], item["revision"]): item
                   for item in payload["revisions"]}
        assert indexed[(1, new_one)]["context_length"] == 0
        assert indexed[(1, new_one)]["audio_context_length"] == 0
        assert indexed[(1, new_one)]["children"] == [{
            "scene": 2,
            "scene_id": "scene_2",
            "revision": new_two,
            "continuation_mode": "guide",
            "context_length": 39,
            "audio_context_length": 44,
        }]
        assert indexed[(2, new_two)]["parent"] == {
            "scene": 1, "revision": new_one}

        future = "5" * 32
        _future_meta, future_files = write_revision(
            run, 3, future, 303, active=True, predecessor=new_two_meta)

        mismatched = await chain._restore_checkpoint_revisions(JsonRequest({
            "run_name": "revision_test",
            "resume_scene": 3,
            "revisions": [
                {"scene": 1, "revision": old_one},
                {"scene": 2, "revision": new_two},
            ],
        }))
        assert mismatched.status == 400
        assert "different scene 1 revision" in json.loads(
            mismatched.text)["error"]

        restore = await chain._restore_checkpoint_revisions(JsonRequest({
            "run_name": "revision_test",
            "resume_scene": 3,
            "revisions": [
                {"scene": 1, "revision": old_one},
                {"scene": 2, "revision": old_two},
            ],
        }))
        assert restore.status == 200
        restored = json.loads(restore.text)
        assert [item["seed"] for item in restored["restored"]] == ["101", "102"]
        assert [item["context_length"] for item in restored["restored"]] == [0, 39]
        assert [item["audio_context_length"] for item in
                restored["restored"]] == [33, 44]
        active_one = json.loads((run / "checkpoints" / "clip_0001.json").read_text())
        active_two = json.loads((run / "checkpoints" / "clip_0002.json").read_text())
        assert active_one["segment"]["revision"] == old_one
        assert active_two["segment"]["revision"] == old_two
        assert restored["retired_later_pointers"] == 1
        assert not (run / "checkpoints" / "clip_0003.json").exists()
        assert (run / "checkpoints" / ("clip_0003.%s.json" % future)).is_file()
        assert (run / "checkpoints" / ("clip_0001.%s.json" % new_one)).is_file()

        future_preview = await chain._preview_checkpoint_revision_deletion(
            JsonRequest({
                "run_name": "revision_test", "scene": 3,
                "revision": future,
            }))
        future_body = json.loads(future_preview.text)
        assert future_body["allowed"] and not future_body["rollback"]
        future_delete = await chain._delete_checkpoint_revision(JsonRequest({
            "run_name": "revision_test", "scene": 3,
            "revision": future, "snapshot": future_body["snapshot"],
        }))
        assert future_delete.status == 200
        assert not any(path.exists() for path in future_files)

        active_delete = await chain._delete_checkpoint_revision(JsonRequest({
            "run_name": "revision_test", "scene": 1, "revision": old_one,
        }))
        assert active_delete.status == 409
        assert "active" in json.loads(active_delete.text)["error"]

        preview = await chain._preview_checkpoint_revision_deletion(JsonRequest({
            "run_name": "revision_test", "scene": 1, "revision": new_one,
        }))
        assert preview.status == 200
        preview_body = json.loads(preview.text)
        assert not preview_body["allowed"]
        assert [(item["scene"], item["revision"])
                for item in preview_body["dependents"]] == [(2, new_two)]
        blocked = await chain._delete_checkpoint_revision(JsonRequest({
            "run_name": "revision_test", "scene": 1, "revision": new_one,
            "snapshot": preview_body["snapshot"],
        }))
        assert blocked.status == 409
        assert "depend" in json.loads(blocked.text)["error"]
        assert all(path.exists() for path in new_one_files)

        leaf_preview = await chain._preview_checkpoint_revision_deletion(
            JsonRequest({
                "run_name": "revision_test", "scene": 2,
                "revision": new_two,
            }))
        leaf_body = json.loads(leaf_preview.text)
        assert leaf_body["allowed"]
        assert leaf_body["owned_file_count"] == len(new_two_files)
        unpreviewed = await chain._delete_checkpoint_revision(JsonRequest({
            "run_name": "revision_test", "scene": 2, "revision": new_two,
        }))
        assert unpreviewed.status == 409
        assert "Preview" in json.loads(unpreviewed.text)["error"]

        # Even an immutable sidecar changing between preview and confirmation
        # invalidates the snapshot and requires the user to inspect it again.
        prompt_path = next(path for path in new_two_files
                           if path.name.endswith(".prompt.txt"))
        prompt_path.write_text("changed after preview", encoding="utf-8")
        stale = await chain._delete_checkpoint_revision(JsonRequest({
            "run_name": "revision_test", "scene": 2, "revision": new_two,
            "snapshot": leaf_body["snapshot"],
        }))
        assert stale.status == 409
        assert "changed" in json.loads(stale.text)["error"]
        leaf_preview = await chain._preview_checkpoint_revision_deletion(
            JsonRequest({
                "run_name": "revision_test", "scene": 2,
                "revision": new_two,
            }))
        leaf_body = json.loads(leaf_preview.text)
        leaf_delete = await chain._delete_checkpoint_revision(JsonRequest({
            "run_name": "revision_test", "scene": 2, "revision": new_two,
            "snapshot": leaf_body["snapshot"],
        }))
        assert leaf_delete.status == 200
        assert not any(path.exists() for path in new_two_files)

        parent_preview = await chain._preview_checkpoint_revision_deletion(
            JsonRequest({
                "run_name": "revision_test", "scene": 1,
                "revision": new_one,
            }))
        parent_body = json.loads(parent_preview.text)
        assert parent_body["allowed"]
        delete = await chain._delete_checkpoint_revision(JsonRequest({
            "run_name": "revision_test", "scene": 1, "revision": new_one,
            "snapshot": parent_body["snapshot"],
        }))
        assert delete.status == 200
        deleted = json.loads(delete.text)
        assert deleted["reclaimed_bytes"] > 0
        assert deleted["deleted_files"] == len(new_one_files)
        assert not any(path.exists() for path in new_one_files)
        assert (run / "checkpoints" / "clip_0001.json").is_file()
        assert json.loads((run / "checkpoints" / "clip_0001.json").read_text())[
            "segment"]["revision"] == old_one

        # A failed prefix selection must not alter either canonical pointer.
        bad = await chain._restore_checkpoint_revisions(JsonRequest({
            "run_name": "revision_test",
            "resume_scene": 3,
            "revisions": [{"scene": 2, "revision": old_two}],
        }))
        assert bad.status == 400
        assert "exactly scenes 1 through 2" in json.loads(bad.text)["error"]
        assert json.loads((run / "checkpoints" / "clip_0001.json").read_text())[
            "segment"]["revision"] == old_one

        active_tip_preview = await chain._preview_checkpoint_revision_deletion(
            JsonRequest({
                "run_name": "revision_test", "scene": 2,
                "revision": old_two,
            }))
        active_tip_body = json.loads(active_tip_preview.text)
        assert active_tip_body["allowed"]
        assert active_tip_body["rollback"]
        assert active_tip_body["rollback_to_scene"] == 1
        assert active_tip_body["owned_file_count"] == len(old_two_files) + 1
        active_tip_delete = await chain._delete_checkpoint_revision(JsonRequest({
            "run_name": "revision_test", "scene": 2,
            "revision": old_two, "snapshot": active_tip_body["snapshot"],
        }))
        assert active_tip_delete.status == 200
        active_tip_deleted = json.loads(active_tip_delete.text)
        assert active_tip_deleted["rollback"]
        assert active_tip_deleted["rollback_to_scene"] == 1
        assert not (run / "checkpoints" / "clip_0002.json").exists()
        assert not any(path.exists() for path in old_two_files)

        root_tip_preview = await chain._preview_checkpoint_revision_deletion(
            JsonRequest({
                "run_name": "revision_test", "scene": 1,
                "revision": old_one,
            }))
        root_tip_body = json.loads(root_tip_preview.text)
        assert root_tip_body["allowed"] and root_tip_body["rollback"]
        assert root_tip_body["rollback_to_scene"] == 0
        root_tip_delete = await chain._delete_checkpoint_revision(JsonRequest({
            "run_name": "revision_test", "scene": 1,
            "revision": old_one, "snapshot": root_tip_body["snapshot"],
        }))
        assert root_tip_delete.status == 200
        assert not (run / "checkpoints" / "clip_0001.json").exists()
        assert not any(path.exists() for path in old_one_files)
        empty_graph = chain.CheckpointGraphManager(
            folder_paths.output_directory).graph("revision_test")
        assert empty_graph["summary"]["revision_count"] == 0

        # A next-scene take with no predecessor picture or generated-audio
        # dependency can be attributed to another empty branch slot without
        # copying its immutable media/checkpoint artifacts.
        attribution_run = pathlib.Path(temporary) / "h3_chains" / "attrib_test"
        parent_a = "6" * 32
        parent_b = "7" * 32
        candidate_token = "8" * 32
        blocked_token = "9" * 32
        parent_a_meta, _parent_a_files = write_revision(
            attribution_run, 1, parent_a, 601, active=True,
            run_name="attrib_test")
        _parent_b_meta, _parent_b_files = write_revision(
            attribution_run, 1, parent_b, 701, run_name="attrib_test")
        candidate_meta, candidate_files = write_revision(
            attribution_run, 2, candidate_token, 801,
            predecessor=parent_a_meta, run_name="attrib_test",
            context_length=0, audio_context_length=44,
            generated_continuity="off")
        write_revision(
            attribution_run, 2, blocked_token, 901,
            predecessor=parent_a_meta, run_name="attrib_test",
            context_length=12, audio_context_length=0,
            generated_continuity="off")

        manager = chain.CheckpointGraphManager(folder_paths.output_directory)
        attribution_graph = manager.graph("attrib_test")
        parent_b_branch = next(
            branch for branch in attribution_graph["branches"]
            if branch["leaf_revision"] == parent_b)
        slot = parent_b_branch["attribution_slot"]
        assert slot["scene"] == 2
        assert [item["revision"] for item in slot["candidates"]] == [
            candidate_token]

        attached = manager.attribute(
            "attrib_test", 1, parent_b, 2, candidate_token)
        assert attached["created"]
        alias_token = attached["revision"]
        alias_path = attribution_run / "checkpoints" / (
            "clip_0002.%s.json" % alias_token)
        alias = json.loads(alias_path.read_text(encoding="utf-8"))
        assert alias["segment"]["predecessor_revision"] == parent_b
        assert alias["segment"]["adopted_from_revision"] == candidate_token
        assert alias["segment"]["segment"] == candidate_meta["segment"]["segment"]
        assert alias["segment"]["checkpoint"] == candidate_meta["segment"]["checkpoint"]

        repeated = manager.attribute(
            "attrib_test", 1, parent_b, 2, candidate_token)
        assert not repeated["created"]
        assert repeated["revision"] == alias_token

        attached_graph = manager.graph("attrib_test")
        alias_record = next(item for item in attached_graph["revisions"]
                            if item["revision"] == alias_token)
        assert alias_record["parent"] == {
            "scene": 1, "revision": parent_b}
        assert alias_record["adopted_from_revision"] == candidate_token
        assert not any(
            branch.get("attribution_slot")
            for branch in attached_graph["branches"]
            if branch["leaf_revision"] == parent_b)

        activate_alias = await chain._restore_checkpoint_revisions(JsonRequest({
            "run_name": "attrib_test",
            "resume_scene": 3,
            "activate_only": True,
            "revisions": [
                {"scene": 1, "revision": parent_b},
                {"scene": 2, "revision": alias_token},
            ],
        }))
        assert activate_alias.status == 200
        assert json.loads((attribution_run / "checkpoints" /
                           "clip_0002.json").read_text())["segment"][
                               "revision"] == alias_token

        # The original metadata can be removed while the attributed lineage
        # continues to reference and preview the same media files.
        original_preview = manager.deletion_preview(
            "attrib_test", 2, candidate_token)
        assert original_preview["allowed"]
        assert any(item["shared"] for item in original_preview["files"])
        manager.delete(
            "attrib_test", 2, candidate_token,
            original_preview["snapshot"])
        assert all(path.exists() for path in candidate_files
                   if path.name != "clip_0002.%s.json" % candidate_token)
        assert manager.graph("attrib_test")["summary"]["revision_count"] == 4

        try:
            manager.attribute(
                "attrib_test", 1, parent_b, 2, blocked_token)
        except ValueError as exc:
            assert "context" in str(exc)
        else:
            raise AssertionError("dependent candidate attribution was accepted")

        alias_preview = manager.deletion_preview(
            "attrib_test", 2, alias_token)
        assert alias_preview["allowed"] and alias_preview["rollback"]
        manager.delete(
            "attrib_test", 2, alias_token, alias_preview["snapshot"])
        assert not alias_path.exists()
        assert not any(path.exists() for path in candidate_files)

if __name__ == "__main__":
    asyncio.run(check())
    print("H3 checkpoint revisions: discovery, prefix restore, and guarded deletion pass")
