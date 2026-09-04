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


def main():
    assert chain.CHAIN_NODE_CLASS_MAPPINGS[
        "MiniMaxH3ProjectAssetManager"] is chain.MiniMaxH3ProjectAssetManager
    assert "asset_0" not in chain.MiniMaxH3ProjectAssetManager.INPUT_TYPES().get(
        "optional", {})
    assert "run_name" in chain.MiniMaxH3ProjectAssetManager.INPUT_TYPES()["required"]
    assert "project_name" not in chain.MiniMaxH3ProjectAssetManager.INPUT_TYPES()["required"]
    assert chain.MiniMaxH3ProjectAssetManager.INPUT_TYPES()["required"][
        "run_name"][1]["default"] == ""
    asset_inputs = chain.MiniMaxH3ProjectAssetManager.INPUT_TYPES()["required"]
    assert asset_inputs["semantic_anchor_size"][0][0] == "inherit"
    assert asset_inputs["semantic_anchor_size"][1]["default"] == "512"
    assert asset_inputs["semantic_anchor_mode"][0][0] == "inherit"
    assert asset_inputs["semantic_anchor_mode"][1]["default"] == (
        "timestamped_video")
    assert "tagged_references" in (
        chain.MiniMaxH3ProjectAssetManager.INPUT_TYPES()["optional"])
    assert chain.MiniMaxH3ProjectAssetManager.INPUT_TYPES()["optional"][
        "upscale_model"][1]["lazy"] is True
    assert "operation_json" in (
        chain.MiniMaxH3ProjectAssetManager.INPUT_TYPES()["required"])
    assert list(chain.MiniMaxH3ProjectAssetManager.INPUT_TYPES()[
        "required"]).index("operation_json") > list(
            chain.MiniMaxH3ProjectAssetManager.INPUT_TYPES()["required"]
        ).index("semantic_anchor_mode")
    assert chain.MiniMaxH3ProjectAssetManager.OUTPUT_NODE is True
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
        hero_result = store.import_file(
            "episode", hero, role="picture", tag="hero")
        store.import_file(
            "episode", door, role="semantic_anchor", tag="door")
        store.import_file(
            "episode", music, role="source_track", tag="music")

        contract_revision = store.load("episode")["revision"]
        folder_result = store.create_folder("episode", "Characters")
        folder_id = folder_result["folder"]["id"]
        assert folder_result["catalog"]["revision"] == contract_revision
        moved = store.update(
            "episode", hero_result["asset"]["id"], {"folder_id": folder_id})
        assert moved["asset"]["folder_id"] == folder_id
        assert moved["catalog"]["revision"] == contract_revision
        duplicate = store.duplicate(
            "episode", hero_result["asset"]["id"])
        assert duplicate["asset"]["relative_path"] == (
            hero_result["asset"]["relative_path"])
        assert duplicate["asset"]["parent_asset_id"] == (
            hero_result["asset"]["id"])
        shared_path = pathlib.Path(temporary) / "input" / "h3_projects" / (
            "episode") / hero_result["asset"]["relative_path"]
        store.delete("episode", duplicate["asset"]["id"])
        assert shared_path.is_file()

        variant = store.derive_image(
            "episode", hero_result["asset"]["id"],
            crop={"x": 10, "y": 8, "width": 40, "height": 24},
            target={"width": 100, "height": 60},
            resample="lanczos", tag="hero_closeup",
            operation_id="unit-crop")
        assert variant["asset"]["parent_asset_id"] == hero_result["asset"]["id"]
        assert variant["asset"]["metadata"]["width"] == 100
        assert variant["asset"]["metadata"]["height"] == 60
        assert variant["asset"]["transform"]["crop"] == {
            "x": 10, "y": 8, "width": 40, "height": 24}
        assert store.register_derived_image(
            "episode", hero_result["asset"]["id"],
            store.asset("episode", variant["asset"]["id"])[1],
            operation_id="unit-crop")["reused"] is True
        renamed = store.update_folder(
            "episode", folder_id, {"name": "Cast"})
        assert renamed["folder"]["name"] == "Cast"

        record, references, token, timeline, status = (
            chain.MiniMaxH3ProjectAssetManager().build(
                "episode", "", "512", "timestamped_video"))
        assert timeline["audio"]["kind"] == "external_path"
        assert record["project"] == "episode"
        assert len(references["entries"]) == 2
        assert len(references["semantic_anchors"]["entries"]) == 1
        assert "2 native, 1 semantic, 0 unassigned, source track on" in status
        assert record["catalog"]["folders"][0]["name"] == "Cast"
        current, lineage = chain._generation_fingerprint_value(token)
        assert current == chain._combined_reference_registry(
            references)["fingerprint"]
        assert lineage["registry_mode"] == "tagged"

        inherited_record, inherited_references, inherited_token, *_rest = (
            chain.MiniMaxH3ProjectAssetManager().build(
                "episode", "", "inherit", "inherit"))
        inherited_bundle = inherited_references["semantic_anchors"]
        assert inherited_bundle["semantic_anchor_size"] == "inherit"
        assert inherited_bundle["semantic_anchor_mode"] == "inherit"
        assert inherited_record["references"] is inherited_references
        explicit_token = chain.MiniMaxH3ProjectAssetManager().build(
            "episode", "", "768", "picture_storyboard")[2]
        assert inherited_token != explicit_token
        assert chain._generation_fingerprint_value(inherited_token)[0] == (
            chain._combined_reference_registry(
                inherited_references)["fingerprint"])

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
            "hero", "hero_closeup", "door"}
        assert all(slot["available"] for slot in template_catalog["reference_slots"])
        assert "0 native, 0 semantic, 3 unassigned" in template_status

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

        operation = json.dumps({
            "mode": "model", "project": "episode",
            "asset_id": hero_result["asset"]["id"],
            "crop": {"x": 0, "y": 0, "width": 80, "height": 48},
            "target": {"width": 160, "height": 96},
        })
        manager = chain.MiniMaxH3ProjectAssetManager()
        assert manager.check_lazy_status(
            "episode", operation_json="", upscale_model=None) == []
        assert manager.check_lazy_status(
            "episode", operation_json=operation, upscale_model=None) == [
                "upscale_model"]

        comfy = types.ModuleType("comfy")
        comfy.__path__ = []
        model_management = types.ModuleType("comfy.model_management")
        model_management.load_models_gpu = lambda *args, **kwargs: None
        model_management.intermediate_device = lambda: chain.torch.device("cpu")
        model_management.raise_non_oom = lambda exc: (_ for _ in ()).throw(exc)
        comfy_utils = types.ModuleType("comfy.utils")
        comfy_utils.get_tiled_scale_steps = lambda *args, **kwargs: 1
        comfy_utils.ProgressBar = lambda _steps: object()
        comfy_utils.tiled_scale = lambda tensor, function, **_kwargs: function(tensor)
        comfy.model_management = model_management
        comfy.utils = comfy_utils
        sys.modules["comfy"] = comfy
        sys.modules["comfy.model_management"] = model_management
        sys.modules["comfy.utils"] = comfy_utils

        class FakeUpscaleModel:
            scale = 2.0
            patcher = types.SimpleNamespace(load_device=chain.torch.device("cpu"))

            def __call__(self, tensor):
                return chain.torch.nn.functional.interpolate(
                    tensor, scale_factor=2, mode="nearest")

        upscaled = chain._project_asset_model_upscale(
            Image.new("RGBA", (10, 6), (10, 20, 30, 128)),
            FakeUpscaleModel())
        assert upscaled.size == (20, 12)
        model_operation = {
            "mode": "model", "project": "episode", "operation_id": "unit-model",
            "asset_id": hero_result["asset"]["id"], "tag": "hero_model",
            "crop": {"x": 5, "y": 4, "width": 50, "height": 30},
            "target": {"width": 120, "height": 72},
        }
        model_variant = chain._execute_project_asset_model_operation(
            store, "episode", model_operation, FakeUpscaleModel())
        assert model_variant["asset"]["metadata"]["width"] == 120
        assert model_variant["asset"]["transform"]["kind"] == (
            "model_upscale_crop")
        assert chain._execute_project_asset_model_operation(
            store, "episode", model_operation, object())["asset"]["id"] == (
                model_variant["asset"]["id"])

    print("H3 Project Asset Manager: registry, metadata template, lazy picture, and Plan pass")


if __name__ == "__main__":
    main()
