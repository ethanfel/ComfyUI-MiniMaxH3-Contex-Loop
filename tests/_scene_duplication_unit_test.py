#!/usr/bin/env python3
"""Validate JSON produced by the actual browser helper with the Python Plan parser."""

import importlib.util
import json
import pathlib
import subprocess
import sys
import tempfile
import types


ROOT = pathlib.Path(__file__).resolve().parents[1]
PACKAGE = "h3_scene_duplication_unit"
fixtures = json.loads(subprocess.check_output(
    ["node", str(ROOT / "tests" / "_scene_duplication_js_test.mjs"), "--plans"],
    cwd=ROOT, text=True))

with tempfile.TemporaryDirectory(prefix="h3-duplicate-") as directory:
    folders = types.ModuleType("folder_paths")
    folders.get_output_directory = lambda: directory
    folders.get_temp_directory = lambda: directory
    folders.get_input_directory = lambda: directory
    folders.get_annotated_filepath = lambda value: str(value)
    sys.modules["folder_paths"] = folders
    package = types.ModuleType(PACKAGE)
    package.__path__ = [str(ROOT)]
    sys.modules[PACKAGE] = package
    nodes = types.ModuleType(PACKAGE + ".nodes")
    nodes.MiniMaxH3MotionContext = object
    nodes._claim_inline_patch_ownership = lambda _conditioning=None: "test"
    nodes._prepare_native_guide_conditioning = lambda value: value
    nodes._resize = lambda *args: None
    nodes._streams_from_latent = lambda *args: None
    sys.modules[nodes.__name__] = nodes
    spec = importlib.util.spec_from_file_location(
        PACKAGE + ".chain_nodes", ROOT / "chain_nodes.py")
    chain = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = chain
    spec.loader.exec_module(chain)

    for fixture in fixtures:
        try:
            plan = chain._normalize_plan(
                json.dumps(fixture["plan"]), "duplication-test", 64, 64, 22,
                "video", "head", "disabled", "source_track", 22, 5.0, 20,
                11, 18, "test-model", 5, "guide")
        except Exception as exc:
            raise AssertionError(fixture["name"]) from exc
        assert len(plan["shots"]) == len(fixture["plan"]["shots"])

print("Scene duplication: %d frontend-generated Plans pass the production Python validator" % len(fixtures))
