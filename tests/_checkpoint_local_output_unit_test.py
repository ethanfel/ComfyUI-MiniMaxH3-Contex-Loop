#!/usr/bin/env python3
"""Local manager output uses exact saved takes without promoting any pointer."""
import importlib.util
import json
import math
from pathlib import Path
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "local_output_helpers", ROOT / "tests/_checkpoint_revision_unit_test.py")
h = importlib.util.module_from_spec(spec)
spec.loader.exec_module(h)
chain = h.chain


def snapshot(root):
    return {str(path.relative_to(root)): path.read_bytes()
            for path in root.rglob("*") if path.is_file()}


def rejected(call, text):
    try:
        call()
    except (OSError, ValueError) as exc:
        assert text in str(exc), str(exc)
    else:
        raise AssertionError("Expected failure: " + text)


def main():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        h.folder_paths.output_directory = temporary
        run = root / "h3_chains" / "local_test"
        old1, _ = h.write_revision(run, 1, "1" * 32, 11, run_name=run.name)
        old2, _ = h.write_revision(run, 2, "2" * 32, 12, predecessor=old1, run_name=run.name)
        new1, _ = h.write_revision(run, 1, "3" * 32, 21, active=True, run_name=run.name)
        new2, _ = h.write_revision(run, 2, "4" * 32, 22, active=True, predecessor=new1, run_name=run.name)
        (run / "plan.json").write_text(json.dumps({
            "run_name":run.name, "shots":[{"id":f"scene_{i}"} for i in range(1, 4)],
        }))
        (run / "manifest.json").write_text('{"keep": "project final"}')
        (run / "editorial.json").write_text(json.dumps({
            "scene_order":[{"scene":i, "scene_id":f"scene_{i}"} for i in range(1, 4)],
        }))
        chain.claim_project_ownership(temporary, run.name, "owner-of-another-workflow")
        selection = {"run_name":run.name, "output_mode":"workflow_local",
                     "scope_start_scene":1, "scope_end_scene":3,
                     "lineage":[{"scene":1, "revision":"1" * 32},
                                {"scene":2, "revision":"2" * 32}]}
        node = chain.MiniMaxH3ChainCheckpointManager()
        assert math.isnan(node.IS_CHANGED())
        assert node.passthrough() == (None,)
        before = snapshot(root)
        with patch.object(chain, "_atomic_json", side_effect=AssertionError("local output wrote JSON")):
            result = node.passthrough(json.dumps(selection))[0]
        assert [row["revision"] for row in result["segments"]] == ["1" * 32, "2" * 32]
        assert result["selection_complete"] is False and result["planned_clip_count"] == 3
        assert snapshot(root) == before, "local selection modified project files or ownership"
        assert node.passthrough({k:v for k, v in selection.items() if k != "output_mode"})[0] == result, \
            "pinning alone does not change upscale source hashes"

        # A second workflow's exact output and the project's active state remain
        # independent. Changing shared pointers after the pin does not move it.
        second = {**selection, "lineage":[{"scene":1,"revision":"3" * 32},
                                         {"scene":2,"revision":"4" * 32}]}
        assert node.passthrough(second)[0]["segments"][1]["revision"] == "4" * 32
        for i, metadata in enumerate((old1, old2), start=1):
            (run / "checkpoints" / f"clip_{i:04d}.json").write_text(json.dumps(metadata))
        changed = snapshot(root)
        assert node.passthrough(second)[0]["segments"][1]["revision"] == "4" * 32
        assert node.passthrough(selection)[0] == result
        assert snapshot(root) == changed

        rejected(lambda: node.passthrough({**selection, "output_mode":"global"}), "unknown output")
        rejected(lambda: node.passthrough({**selection, "lineage":[
            {"scene":1,"revision":"3" * 32}, {"scene":2,"revision":"2" * 32}]}), "depends on")
        rejected(lambda: node.passthrough({**selection, "lineage":[
            {"scene":1,"revision":"../escape"}]}), "32-character")
        rejected(lambda: node.passthrough({**selection, "lineage":[selection["lineage"][1]]}), "contiguous")

        # Legacy reference caches can be read in place, but a local output must
        # not adopt/copy them into this protected run as a side effect.
        descriptor = {"format":"h3_reference_cache_v2", "signature":"cache-test",
                      "reference_fingerprint":"refs", "metadata":"cache/ref.json",
                      "tensors":"cache/ref.safetensors", "tensors_sha256":"0" * 64}
        metadata_path = root / old2["segment"]["revision_metadata"]
        old2["segment"]["reference_cache"] = descriptor
        metadata_path.write_text(json.dumps(old2))
        changed = snapshot(root)
        with patch.object(chain, "_run_local_reference_cache", return_value=None), \
             patch.object(chain, "_load_reference_cache_descriptor", return_value=descriptor), \
             patch.object(chain, "_adopt_reference_cache_for_run", side_effect=AssertionError("local cache migration")):
            assert node.passthrough(selection)[0]["segments"][1]["reference_cache"] == descriptor
        assert snapshot(root) == changed

        # Canonical pointers still exist. They must not serve as fallback when
        # an immutable selection is removed or fails integrity verification.
        metadata_path.unlink()
        changed = snapshot(root)
        rejected(lambda: node.passthrough(selection), "no longer available")
        assert snapshot(root) == changed
        metadata_path.write_text(json.dumps(old2))
        video = root / old2["segment"]["segment"]
        video.write_bytes(b"corrupt")
        changed = snapshot(root)
        rejected(lambda: node.passthrough(selection), "integrity")
        assert snapshot(root) == changed
    print("Checkpoint local output: protected-run read-only, exact revisions, stable source hash, legacy cache and fail-closed checks pass")


if __name__ == "__main__":
    main()
