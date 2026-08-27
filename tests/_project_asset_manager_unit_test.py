#!/usr/bin/env python3
"""Project Asset Manager registry, lazy picture, and Plan integration checks."""

import importlib.util
import json
import pathlib
import sys
import tempfile
import types
import wave

from PIL import Image


ROOT = pathlib.Path(__file__).resolve().parents[1]
PACKAGE = "h3_project_asset_manager_unit"
ACTIVE = {"root": str(ROOT)}

folder_paths = types.ModuleType("folder_paths")
folder_paths.get_output_directory = lambda: str(
    pathlib.Path(ACTIVE["root"]) / "output")
folder_paths.get_temp_directory = lambda: str(
    pathlib.Path(ACTIVE["root"]) / "temp")
folder_paths.get_input_directory = lambda: str(
    pathlib.Path(ACTIVE["root"]) / "input")
folder_paths.get_annotated_filepath = lambda value: str(value)
sys.modules["folder_paths"] = folder_paths

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


def main():
    assert chain.CHAIN_NODE_CLASS_MAPPINGS[
        "MiniMaxH3ProjectAssetManager"] is chain.MiniMaxH3ProjectAssetManager
    assert "asset_0" not in chain.MiniMaxH3ProjectAssetManager.INPUT_TYPES().get(
        "optional", {})
    assert "run_name" in chain.MiniMaxH3ProjectAssetManager.INPUT_TYPES()["required"]
    assert "project_name" not in chain.MiniMaxH3ProjectAssetManager.INPUT_TYPES()["required"]
    assert chain.MiniMaxH3ProjectAssetManager.INPUT_TYPES()["required"][
        "run_name"][1]["default"] == ""
    assert "tagged_references" in (
        chain.MiniMaxH3ProjectAssetManager.INPUT_TYPES()["optional"])
    with tempfile.TemporaryDirectory() as temporary:
        ACTIVE["root"] = temporary
        root = pathlib.Path(temporary)
        loose = root / "input" / "loose"
        loose.mkdir(parents=True)
        hero = loose / "hero.png"
        door = loose / "door.png"
        music = loose / "music.wav"
        Image.new("RGB", (80, 48), (120, 40, 30)).save(hero)
        Image.new("RGB", (64, 64), (20, 60, 100)).save(door)
        with wave.open(str(music), "wb") as handle:
            handle.setnchannels(2)
            handle.setsampwidth(2)
            handle.setframerate(32000)
            handle.writeframes(b"\x00\x00\x00\x00" * 3200)
        store = chain.ProjectAssetStore(
            folder_paths.get_input_directory(),
            folder_paths.get_output_directory())
        store.import_file("episode", hero, role="picture", tag="hero")
        store.import_file(
            "episode", door, role="semantic_anchor", tag="door")
        store.import_file(
            "episode", music, role="source_track", tag="music")

        record, references, token, timeline, status = (
            chain.MiniMaxH3ProjectAssetManager().build(
                "episode", "", "512", "timestamped_video"))
        assert timeline["audio"]["kind"] == "external_path"
        assert record["project"] == "episode"
        assert len(references["entries"]) == 1
        assert len(references["semantic_anchors"]["entries"]) == 1
        assert "1 native, 1 semantic, 0 unassigned, source track on" in status
        current, lineage = chain._generation_fingerprint_value(token)
        assert current == chain._combined_reference_registry(
            references)["fingerprint"]
        assert lineage["registry_mode"] == "tagged"

        picture = chain._project_asset_image(
            references["entries"][0]["value"])
        assert tuple(picture.shape) == (1, 48, 80, 3)
        plan = chain.MiniMaxH3ChainPlan().build(
            json.dumps({"shots": [{"id": "one", "prompt": "Use @hero."}]}),
            "wrong_name", "", 960, 544, 22, "video", "head", "disabled",
            "generated_audio", 22, 15.0, 20, 0, 18,
            project_assets=record,
        )[0]
        assert plan["run_name"] == "episode"
        assert plan["compatibility"]["generation_fingerprint"] == current
        assert plan["source_timeline"]["kind"] == "source_timeline"
        recovered_timeline = chain._source_timeline_from_recovery(
            plan["source_timeline"])
        assert recovered_timeline["audio"]["kind"] == "external_path"
        studio_timeline = chain._plan_studio_runtime_source_timeline(plan)
        assert studio_timeline["fingerprints"]["timeline"] == (
            timeline["fingerprints"]["timeline"])

        template_record, template_refs, _token, _timeline, template_status = (
            chain.MiniMaxH3ProjectAssetManager().build(
                "template_only", "", "512", "timestamped_video",
                tagged_references=references))
        template_catalog = template_record["catalog"]
        assert template_refs["entries"] == []
        assert template_catalog["assets"] == []
        assert {slot["tag"] for slot in template_catalog["reference_slots"]} == {
            "hero", "door"}
        assert all(slot["available"] for slot in template_catalog["reference_slots"])
        assert "0 native, 0 semantic, 2 unassigned" in template_status

        tagged_audio = chain._append_tagged_reference(
            None, kind="audio", tag="dialogue", value={"test": "audio"},
            content_hash="audio-source-hash",
            timeline_mode="source_timeline", align_audio_reference=True)
        audio_record, audio_refs, _token, _timeline, _status = (
            chain.MiniMaxH3ProjectAssetManager().build(
                "audio_template", "", "512", "timestamped_video",
                tagged_references=tagged_audio))
        audio_slot = audio_record["catalog"]["reference_slots"][0]
        assert audio_slot["role"] == "audio_reference"
        assert audio_slot["options"]["timeline_mode"] == "source_timeline"
        assert audio_slot["options"]["align_audio_reference"] is True
        store.bind_reference_slot(
            "audio_template", audio_slot["id"], music,
            source_kind="input")
        _record, audio_refs, _token, _timeline, _status = (
            chain.MiniMaxH3ProjectAssetManager().build(
                "audio_template", "", "512", "timestamped_video",
                tagged_references=tagged_audio))
        audio_entry = audio_refs["entries"][0]
        assert audio_entry["kind"] == "audio"
        assert audio_entry["tag"] == "dialogue"
        assert audio_entry["timeline_mode"] == "source_timeline"
        assert audio_entry["align_audio_reference"] is True

    print("H3 Project Asset Manager: registry, metadata template, lazy picture, and Plan pass")


if __name__ == "__main__":
    main()
