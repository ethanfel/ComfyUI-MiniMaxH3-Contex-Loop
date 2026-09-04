#!/usr/bin/env python3
"""Interrupted-chain manifest recovery regression."""

import importlib.util
import json
import pathlib
import sys
import tempfile
import types


ROOT = pathlib.Path(__file__).resolve().parents[1]
PACKAGE = "h3_manifest_recovery_unit"

folder_paths = types.ModuleType("folder_paths")
folder_paths.output_directory = str(ROOT)
folder_paths.get_output_directory = lambda: folder_paths.output_directory
folder_paths.get_temp_directory = lambda: folder_paths.output_directory
folder_paths.get_input_directory = lambda: folder_paths.output_directory
folder_paths.get_annotated_filepath = lambda value: str(value)
sys.modules["folder_paths"] = folder_paths

package = types.ModuleType(PACKAGE)
package.__path__ = [str(ROOT)]
sys.modules[PACKAGE] = package

shared_nodes = types.ModuleType(PACKAGE + ".nodes")
shared_nodes.MiniMaxH3MotionContext = object
shared_nodes._claim_inline_patch_ownership = lambda _conditioning=None: "test patch owner"
shared_nodes._prepare_native_guide_conditioning = lambda value: value
shared_nodes._resize = lambda *args: None
shared_nodes._streams_from_latent = lambda *args: None
sys.modules[shared_nodes.__name__] = shared_nodes

spec = importlib.util.spec_from_file_location(
    PACKAGE + ".chain_nodes", ROOT / "chain_nodes.py")
chain = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = chain
spec.loader.exec_module(chain)


def make_plan():
    return chain._normalize_plan(
        json.dumps({"shots": [
            {"id": "one", "prompt": "one", "length": 22},
            {"id": "two", "prompt": "two", "length": 22},
            {"id": "three", "prompt": "three", "length": 22},
        ]}),
        "manifest_recovery", 64, 64, 5, "video", "head", "disabled",
        "generated_audio", 5, 1.0, 8, 7, 18, "model-stack", 0,
        "guide")


def fake_segment(plan, index):
    shot = plan["shots"][index - 1]
    return {
        "index": index,
        "delivered_frames": int(shot["delivered_frames"]),
    }


def main():
    with tempfile.TemporaryDirectory() as temporary:
        folder_paths.output_directory = temporary
        plan = make_plan()
        checkpoints = pathlib.Path(
            chain._run_dir(plan), "checkpoints")
        checkpoints.mkdir(parents=True)

        calls = []
        original_loader = chain._load_resume_state

        def fake_loader(requested_plan, start_clip, verify_history=True,
                        source_timeline=None, source_audio=None):
            calls.append((start_clip, source_timeline, source_audio))
            return {
                "plan": requested_plan,
                "index": start_clip,
                "segments": [
                    fake_segment(requested_plan, index)
                    for index in range(1, start_clip)
                ],
            }

        chain._load_resume_state = fake_loader
        try:
            try:
                chain.MiniMaxH3ChainManifestLoad().load(plan)
            except FileNotFoundError as exc:
                assert "found no saved scenes" in str(exc)
            else:
                raise AssertionError("empty run was accepted for recovery")

            (checkpoints / "clip_0001.json").write_text("{}")
            (checkpoints / "clip_0002.json").write_text("{}")
            partial, partial_json, partial_status = (
                chain.MiniMaxH3ChainManifestLoad().load(plan))
            assert calls[-1][0] == 3
            assert partial["format"] == "h3_chain_partial_manifest_v3"
            assert partial["clip_count"] == 2
            assert partial["planned_clip_count"] == 3
            assert partial["last_completed_clip"] == 2
            assert json.loads(partial_json)["segments"] == partial["segments"]
            assert "partial manifest through clip 2/3" in partial_status
            partial_path = pathlib.Path(
                chain._run_dir(plan), "partial",
                "through_clip_0002.manifest.json")
            assert json.loads(partial_path.read_text())["clip_count"] == 2

            # A later orphan does not cross a gap in the active pointer chain.
            (checkpoints / "clip_0002.json").unlink()
            (checkpoints / "clip_0003.json").write_text("{}")
            gap, _gap_json, gap_status = (
                chain.MiniMaxH3ChainManifestLoad().load(plan))
            assert calls[-1][0] == 2
            assert gap["clip_count"] == 1
            assert "partial manifest through clip 1/3" in gap_status

            (checkpoints / "clip_0002.json").write_text("{}")
            complete, _complete_json, complete_status = (
                chain.MiniMaxH3ChainManifestLoad().load(plan))
            assert calls[-1][0] == 4
            assert complete["format"] == "h3_chain_manifest_v3"
            assert complete["clip_count"] == 3
            assert "completed manifest through clip 3/3" in complete_status
            complete_path = pathlib.Path(chain._manifest_path(plan))
            assert json.loads(complete_path.read_text())["clip_count"] == 3

            # A non-owner may inspect and export reconstructed recovery state,
            # but it must not rewrite even the derived manifest on disk.
            claimed = chain.claim_project_ownership(
                temporary, plan["run_name"],
                "manifest-owner-1234567890", "Owning workflow")
            sentinel = {"sentinel": "leave this manifest untouched"}
            complete_path.write_text(json.dumps(sentinel), encoding="utf-8")
            read_only, _read_only_json, read_only_status = (
                chain.MiniMaxH3ChainManifestLoad().load(plan))
            assert read_only["clip_count"] == 3
            assert "read-only workflow" in read_only_status
            assert json.loads(complete_path.read_text()) == sentinel

            owner_plan = dict(plan)
            owner_plan["_project_ownership"] = {
                "owner_id": "manifest-owner-1234567890",
                "epoch": claimed["epoch"],
            }
            chain.MiniMaxH3ChainManifestLoad().load(owner_plan)
            assert json.loads(complete_path.read_text())["clip_count"] == 3

            assert "_project_ownership" not in chain._archivable_plan(
                owner_plan)
            api_prompt = {
                "7": {
                    "class_type": "MiniMaxH3ProjectAssetManager",
                    "inputs": {"ownership_json": "secret proof"},
                },
            }
            sanitized_prompt, _plan_ids = chain._matching_plan_node_ids(
                api_prompt, plan)
            assert sanitized_prompt["7"]["inputs"]["ownership_json"] == ""
            workflow = {
                "nodes": [{
                    "type": "MiniMaxH3ProjectAssetManager",
                    "widgets_values": ["run", "{}", "512", "mode", "", "secret"],
                }],
                "definitions": {"subgraphs": [{"nodes": [{
                    "type": "MiniMaxH3ProjectAssetManager",
                    "widgets_values": ["run", "{}", "512", "mode", "", "nested"],
                }]}]},
            }
            chain._strip_workflow_ownership(workflow)
            assert workflow["nodes"][0]["widgets_values"][5] == ""
            assert (workflow["definitions"]["subgraphs"][0]["nodes"][0]
                    ["widgets_values"][5] == "")
        finally:
            chain._load_resume_state = original_loader

    print("H3 manifest recovery: empty, interrupted, gapped, and complete runs passed")


if __name__ == "__main__":
    main()
