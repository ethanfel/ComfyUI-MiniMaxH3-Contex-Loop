#!/usr/bin/env python3
"""Older active-only Ref2V checkpoints remain usable in Checkpoint Manager."""

import hashlib
import importlib.util
import json
import pathlib
import sys
import tempfile
import types


ROOT = pathlib.Path(__file__).resolve().parents[1]
PACKAGE = "h3_legacy_checkpoint_adoption_unit"

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
shared_nodes._claim_inline_patch_ownership = lambda _conditioning=None: "test patch owner"
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
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_legacy_active(run, scene, token, compatibility):
    segments = run / "segments"
    checkpoints = run / "checkpoints"
    segments.mkdir(parents=True, exist_ok=True)
    checkpoints.mkdir(parents=True, exist_ok=True)
    stem = "clip_%04d.%s" % (scene, token)
    segment_path = segments / (stem + ".mp4")
    checkpoint_path = checkpoints / (stem + ".safetensors")
    segment_path.write_bytes(("legacy-video-%d" % scene).encode())
    checkpoint_path.write_bytes(("legacy-latent-%d" % scene).encode())
    segment = {
        "index": scene,
        "id": "scene_%d" % scene,
        "segment": str(segment_path.relative_to(folder_paths.output_directory)),
        "checkpoint": str(
            checkpoint_path.relative_to(folder_paths.output_directory)),
        "metadata": str((checkpoints / ("clip_%04d.json" % scene)).relative_to(
            folder_paths.output_directory)),
        "raw_frames": 29,
        "delivered_frames": 29,
        "history_hash": "legacy-history-%d" % scene,
        "prompt_prefix": "shared",
        "scene_prompt": "legacy prompt %d" % scene,
        "prompt": "shared\nlegacy prompt %d" % scene,
        "prompt_hash": hashlib.sha256(
            ("shared\nlegacy prompt %d" % scene).encode()).hexdigest(),
        "seed": str(100 + scene),
        "steps": 8,
        "segment_sha256": digest(segment_path),
        "checkpoint_sha256": digest(checkpoint_path),
    }
    metadata = {
        "format": "h3_chain_segment_v2",
        "run_name": "legacy_test",
        "plan_hash": "legacy-plan",
        "history_hash": segment["history_hash"],
        "compatibility": compatibility,
        "segment": segment,
    }
    pointer = checkpoints / ("clip_%04d.json" % scene)
    pointer.write_text(json.dumps(metadata), encoding="utf-8")
    return pointer, segment_path, checkpoint_path


def main():
    with tempfile.TemporaryDirectory() as temporary:
        folder_paths.output_directory = temporary
        run = pathlib.Path(temporary) / "h3_chains" / "legacy_test"
        compatibility = {
            "width": 64,
            "height": 64,
            "fps": 24,
            "context_length": 0,
            "audio_context_length": 0,
            "audio_mode": "source_track",
            "continuation_mode": "guide",
        }
        plan = {
            "format": "h3_chain_plan_v2",
            "run_name": "legacy_test",
            "plan_hash": "legacy-plan",
            "prompt_prefix": "shared",
            "compatibility": compatibility,
            "shots": [
                {"id": "scene_1", "prompt": "legacy prompt 1"},
                {"id": "scene_2", "prompt": "legacy prompt 2"},
            ],
        }
        run.mkdir(parents=True)
        (run / "plan.json").write_text(json.dumps(plan), encoding="utf-8")
        first = "1" * 32
        second = "2" * 32
        artifacts = [
            write_legacy_active(run, 1, first, compatibility),
            write_legacy_active(run, 2, second, compatibility),
        ]
        pointer_bytes = [item[0].read_bytes() for item in artifacts]
        media_bytes = [(item[1].read_bytes(), item[2].read_bytes())
                       for item in artifacts]

        payload = chain._saved_checkpoint_listing("legacy_test")
        assert [item["revision"] for item in payload["checkpoints"]] == [
            first, second]
        assert payload["summary"] == {
            "scene_count": 2,
            "revision_count": 2,
            "branch_count": 1,
            "bytes": payload["summary"]["bytes"],
            "broken_count": 0,
        }
        assert payload["branches"][0]["active"]
        assert payload["branches"][0]["path"] == [
            {"scene": 1, "revision": first},
            {"scene": 2, "revision": second},
        ]
        indexed = {(item["scene"], item["revision"]): item
                   for item in payload["revisions"]}
        assert indexed[(2, second)]["parent"] == {
            "scene": 1, "revision": first}

        sidecars = [
            run / "checkpoints" / ("clip_0001.%s.json" % first),
            run / "checkpoints" / ("clip_0002.%s.json" % second),
        ]
        assert all(path.is_file() for path in sidecars)
        assert all(json.loads(path.read_text())["legacy_adoption"]["version"] == 1
                   for path in sidecars)
        assert [item[0].read_bytes() for item in artifacts] == pointer_bytes
        assert [(item[1].read_bytes(), item[2].read_bytes())
                for item in artifacts] == media_bytes

        selected = chain._checkpoint_selection_manifest({
            "run_name": "legacy_test",
            "lineage": [
                {"scene": 1, "revision": first},
                {"scene": 2, "revision": second},
            ],
            "scope_start_scene": 1,
            "scope_end_scene": 2,
        })
        assert selected["clip_count"] == 2
        assert selected["selection_complete"] is True
        assert [item["revision"] for item in selected["segments"]] == [
            first, second]

        # Refreshing is idempotent and does not create duplicate revisions.
        refreshed = chain._saved_checkpoint_listing("legacy_test")
        assert refreshed["summary"]["revision_count"] == 2
        assert sorted((run / "checkpoints").glob("clip_*.json")) == sorted([
            artifacts[0][0], artifacts[1][0], *sidecars])

    print("H3 legacy checkpoints: active-only Ref2V saves are adopted without copying artifacts")


if __name__ == "__main__":
    main()
