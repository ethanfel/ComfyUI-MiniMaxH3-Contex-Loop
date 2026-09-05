#!/usr/bin/env python3
"""Validate release widgets and socket wiring against this checkout, offline."""
from __future__ import annotations
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from workflow_schema import load_schemas, fields, is_widget, widget_fields, validate_value


def validate_workflow(workflow, schemas):
    links = {link[0]: link for link in workflow["links"]}
    for node in workflow["nodes"]:
        if node["type"] == "Note":
            continue
        schema = schemas[node["type"]]
        saved = node["widgets_values"]
        values = {}
        index = 0
        for name, spec in widget_fields(schema, values):
            if isinstance(saved, dict):
                assert name in saved, (node["type"], name, "missing widget")
                value = saved[name]
            else:
                assert index < len(saved), (node["type"], name, "missing widget")
                value = saved[index]
            validate_value(value, spec, (node["id"], node["type"], name))
            values[name] = value
            index += 1
        assert len(saved) == index, (node["type"], "stale extra widgets")
        inputs = {s["name"]: s for s in node["inputs"]}
        specs = fields(schema)
        for name, socket in inputs.items():
            if "." in name and name.split(".")[0] in specs:
                assert specs[name.split(".")[0]][0] == "COMFY_AUTOGROW_V3"
                continue
            assert name in specs, (node["type"], name, "unknown input")
            if is_widget(specs[name]):
                assert socket.get("widget") == {"name": name}, (node["type"], name, "converted widget metadata")
            if socket["link"] is not None:
                link = links[socket["link"]]
                assert link[3] == node["id"] and node["inputs"][link[4]] is socket
        for name, spec in schema["input"].get("required", {}).items():
            if not is_widget(spec):
                assert name in inputs and inputs[name]["link"] is not None, (node["type"], name, "missing required connection")
        assert [o["name"] for o in node["outputs"]] == schema["output_name"], node["type"]
        assert [o["type"] for o in node["outputs"]] == schema["output"], node["type"]


def main():
    schemas = load_schemas()
    paths = sorted((ROOT / "example_workflows").glob("*.json"))
    for path in paths:
        try:
            validate_workflow(json.loads(path.read_text()), schemas)
        except Exception as exc:
            raise AssertionError(path.name) from exc
    # The old audit passed this real broken array: prompt -> clip_index,
    # "match" -> height. Ensure it can never pass release checks again.
    wf = json.loads((ROOT / "example_workflows/Ref2V Studio - MiniMax H3 0.6.json").read_text())
    tagged = next(n for n in wf["nodes"] if n["type"] == "MiniMaxH3TaggedReferenceToVideo")
    tagged["widgets_values"] = tagged["widgets_values"][2:]
    try:
        validate_workflow(wf, schemas)
    except AssertionError:
        pass
    else:
        raise AssertionError("Shifted Tagged Ref2VA widget regression was not caught")
    print("H3 0.6 schemas: all 18 workflows; local H3 + external contracts, widget types/choices/ranges, required sockets and converted inputs pass")


if __name__ == "__main__":
    main()
