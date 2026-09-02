#!/usr/bin/env python3
"""Check active workflow sockets against the current custom-node classes."""

from __future__ import annotations

import importlib.util
import json
import pathlib
import sys
import types


ROOT = pathlib.Path(__file__).resolve().parents[1]
PACKAGE = "h3_workflow_schema_unit"

folder_paths = types.ModuleType("folder_paths")
folder_paths.get_output_directory = lambda: str(ROOT)
folder_paths.get_temp_directory = lambda: str(ROOT)
folder_paths.get_input_directory = lambda: str(ROOT)
folder_paths.get_annotated_filepath = lambda value: str(value)
sys.modules["folder_paths"] = folder_paths

package = types.ModuleType(PACKAGE)
package.__path__ = [str(ROOT)]
sys.modules[PACKAGE] = package

shared_nodes = types.ModuleType(PACKAGE + ".nodes")
shared_nodes.MiniMaxH3MotionContext = object
shared_nodes._claim_inline_patch_ownership = lambda _conditioning=None: "test"
shared_nodes._prepare_native_guide_conditioning = lambda value: value
shared_nodes._resize = lambda *args: None
shared_nodes._streams_from_latent = lambda *args: None
sys.modules[shared_nodes.__name__] = shared_nodes

spec = importlib.util.spec_from_file_location(
    PACKAGE + ".chain_nodes", ROOT / "chain_nodes.py")
chain = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = chain
spec.loader.exec_module(chain)


def main() -> None:
    for path in sorted((ROOT / "example_workflows").glob("*.json")):
        workflow = json.loads(path.read_text(encoding="utf-8"))
        for node in workflow["nodes"]:
            node_class = chain.CHAIN_NODE_CLASS_MAPPINGS.get(node["type"])
            if node_class is None:
                continue
            schema = node_class.INPUT_TYPES()
            valid_inputs = (set(schema.get("required", {}))
                            | set(schema.get("optional", {})))
            for value in node.get("inputs", []):
                assert value["name"] in valid_inputs, (
                    path.name, node["type"], value["name"])
            expected_outputs = list(getattr(node_class, "RETURN_NAMES", ()))
            if expected_outputs:
                actual_outputs = [value["name"]
                                  for value in node.get("outputs", [])]
                assert actual_outputs == expected_outputs[:len(actual_outputs)], (
                    path.name, node["type"], actual_outputs, expected_outputs)
    print("H3 0.6 workflow schemas: custom-node inputs and output slots pass")


if __name__ == "__main__":
    main()
