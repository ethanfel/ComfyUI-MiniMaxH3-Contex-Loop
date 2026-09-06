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
    # Nightly's extra controls must be explicitly serialized. A straight 0.6
    # copy can pass link checks while losing/offsetting these widget values.
    for path in paths:
        recipe = json.loads((ROOT / "tools/v06/recipes" / path.name).read_text())
        for node in recipe["nodes"]:
            if node["type"] == "MiniMaxH3ChainContext":
                assert node["settings"]["visual_cond_noise_aug"] == 0.999
                assert node["settings"]["future_end_anchor"] is False
                assert "boundary_anchors" not in node["inputs"]
            if node["type"] == "MiniMaxH3ProjectAssetManager":
                assert node["settings"]["ownership_json"] == ""
            if node["type"] == "MiniMaxH3ChainReview":
                assert "pending_review" not in node["inputs"]
    wf = json.loads((ROOT / "example_workflows/T2V Normal - MiniMax H3 0.6.json").read_text())
    context = next(n for n in wf["nodes"] if n["type"] == "MiniMaxH3ChainContext")
    context["widgets_values"] = context["widgets_values"][:-2]
    try:
        validate_workflow(wf, schemas)
    except AssertionError:
        pass
    else:
        raise AssertionError("Missing nightly Context widgets were not caught")
    print(f"H3 nightly schemas: all {len(paths)} workflows; local H3 + external contracts, widget types/choices/ranges, required sockets, converted inputs and safe nightly defaults pass")


if __name__ == "__main__":
    main()
