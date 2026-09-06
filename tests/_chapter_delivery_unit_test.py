#!/usr/bin/env python3
"""Chapter delivery, selection, isolation, and recovery regressions."""

import hashlib
import importlib.util
import pathlib
import re
import sys
import tempfile
import types

import torch


ROOT = pathlib.Path(__file__).resolve().parents[1]
PACKAGE = "h3_chapter_delivery_unit"

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


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def make_segment(output, index, delivered=10):
    run = output / "h3_chains" / "chapter_delivery"
    segment_path = run / "segments" / ("clip_%04d.mp4" % index)
    checkpoint_path = run / "checkpoints" / ("clip_%04d.safetensors" % index)
    segment_path.parent.mkdir(parents=True, exist_ok=True)
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    segment_path.write_bytes(("video-%d" % index).encode("ascii"))
    checkpoint_path.write_bytes(("latent-%d" % index).encode("ascii"))
    return {
        "index": index,
        "id": "scene_%02d" % index,
        "revision": ("%032x" % index),
        "segment": str(segment_path.relative_to(output)),
        "segment_sha256": sha256(segment_path),
        "checkpoint": str(checkpoint_path.relative_to(output)),
        "checkpoint_sha256": sha256(checkpoint_path),
        "raw_frames": delivered,
        "delivered_frames": delivered,
        "blend_frames": 0,
    }


def make_manifest(segments, complete):
    total = sum(int(item["delivered_frames"]) for item in segments)
    result = {
        "format": ("h3_chain_manifest_v3" if complete else
                   "h3_chain_partial_manifest_v3"),
        "run_name": "chapter_delivery",
        "plan_hash": "plan-hash",
        "prompt_prefix": "test",
        "compatibility": {"continuation_mode": "guide"},
        "clip_count": len(segments),
        "total_delivered_frames": total,
        "duration_seconds": total / float(chain.FPS),
        "segments": segments,
    }
    if not complete:
        result.update({
            "planned_clip_count": 6,
            "last_completed_clip": len(segments),
        })
    return result


def make_editorial():
    order = [{"scene": index, "scene_id": "scene_%02d" % index}
             for index in range(1, 7)]
    return {
        "format": "h3_chain_editorial_v1",
        "run_name": "chapter_delivery",
        "scene_order": order,
        "chapters": [
            {"id": "opening", "title": "Opening", "start_scene": 1,
             "start_scene_id": "scene_01", "text": "First delivery"},
            {"id": "aftermath", "title": "Aftermath", "start_scene": 4,
             "start_scene_id": "scene_04", "text": "Second delivery"},
        ],
        "placements": [],
        "trims": [],
        "locked_scene_ids": [],
        "subtitles": {"mode": "off", "asset_id": "",
                      "offset_seconds": 0.0},
        "alternate_draft": None,
        "replacements": [],
    }


def expect_error(action, phrase):
    try:
        action()
    except (FileNotFoundError, ValueError) as exc:
        assert phrase in str(exc), str(exc)
    else:
        raise AssertionError("expected error containing %r" % phrase)


def main():
    assert chain.CHAIN_NODE_CLASS_MAPPINGS[
        "MiniMaxH3ChainChapterDelivery"] is chain.MiniMaxH3ChainChapterDelivery
    assert chain.CHAIN_NODE_CLASS_MAPPINGS[
        "MiniMaxH3ChainChapterLoad"] is chain.MiniMaxH3ChainChapterLoad
    schema = chain.MiniMaxH3ChainChapterDelivery.INPUT_TYPES()
    assert schema["required"]["chapter_number"][1]["default"] == 0

    with tempfile.TemporaryDirectory() as temporary:
        output = pathlib.Path(temporary)
        folder_paths.output_directory = temporary
        segments = [make_segment(output, index) for index in range(1, 7)]
        chain._atomic_json(
            chain._run_editorial_path("chapter_delivery"), make_editorial())

        partial_three = make_manifest(segments[:3], complete=False)
        chapter_one, chapter_one_path = chain._chapter_manifest_from_manifest(
            partial_three, 0)
        assert chapter_one["format"] == chain.CHAPTER_MANIFEST_FORMAT
        assert chapter_one["chapter"]["number"] == 1
        assert chapter_one["scene_start"] == 1
        assert chapter_one["scene_end"] == 3
        assert chapter_one["chapter"]["complete"] is True
        assert chapter_one["chapter"]["planned_end_scene"] == 3
        assert [item["index"] for item in chapter_one["segments"]] == [1, 2, 3]
        assert pathlib.Path(chapter_one_path).is_file()
        assert "/chapters/01_opening/manifests/" in chapter_one_path
        assert re.fullmatch(
            r"[0-9a-f]{32}", chapter_one["chapter_manifest_id"])
        chapter_one_again, chapter_one_again_path = (
            chain._chapter_manifest_from_manifest(partial_three, 0))
        assert (chapter_one_again["chapter_manifest_id"] ==
                chapter_one["chapter_manifest_id"])
        assert chapter_one_again_path == chapter_one_path

        complete = make_manifest(segments, complete=True)
        completed_chapter_one, _completed_chapter_one_path = (
            chain._chapter_manifest_from_manifest(complete, 1))
        assert completed_chapter_one["chapter"]["number"] == 1
        assert [item["index"] for item in
                completed_chapter_one["segments"]] == [1, 2, 3]
        chapter_two, chapter_two_path = chain._chapter_manifest_from_manifest(
            complete, 2)
        assert chapter_two["chapter"]["number"] == 2
        assert chapter_two["chapter"]["source_start_frame"] == 30
        assert chapter_two["chapter"]["editorial_origin_frame"] == 30
        assert chapter_two["scene_start"] == 4
        assert chapter_two["scene_end"] == 6
        assert [item["index"] for item in chapter_two["segments"]] == [4, 5, 6]
        assert "prelude" not in chapter_two
        assert "/chapters/02_aftermath/manifests/" in chapter_two_path
        assert chain._validate_manifest(chapter_two) == chapter_two["segments"]

        auto_two, _auto_two_path = chain._chapter_manifest_from_manifest(
            complete, 0)
        assert auto_two["chapter"]["number"] == 2

        partial_four = make_manifest(segments[:4], complete=False)
        partial_two, partial_two_path = chain._chapter_manifest_from_manifest(
            partial_four, 0)
        assert partial_two["chapter"]["number"] == 2
        assert partial_two["chapter"]["complete"] is False
        assert partial_two["chapter"]["planned_end_scene"] == 6
        assert partial_two["scene_start"] == partial_two["scene_end"] == 4
        assert chain._validate_manifest(partial_two) == partial_two["segments"]
        explicit_one, _explicit_one_path = (
            chain._chapter_manifest_from_manifest(partial_four, 1))
        assert explicit_one["chapter"]["number"] == 1
        explicit_two, explicit_two_path = chain._chapter_manifest_from_manifest(
            partial_four, 2)
        assert explicit_two == partial_two and explicit_two_path == partial_two_path
        expect_error(
            lambda: chain._chapter_manifest_from_manifest(partial_three, 2),
            "no generated scenes yet")
        expect_error(
            lambda: chain._chapter_manifest_from_manifest(complete, 3),
            "does not exist")

        loaded, loaded_path = chain._load_chapter_manifest(
            "chapter_delivery", 2)
        assert loaded["chapter_manifest_id"] == partial_two[
            "chapter_manifest_id"]
        assert loaded_path == partial_two_path
        exact, exact_path = chain._load_chapter_manifest(
            "chapter_delivery", 2, chapter_two["chapter_manifest_id"])
        assert exact == chapter_two and exact_path == chapter_two_path
        media_metadata = chain._manifest_media_metadata(chapter_two)
        assert "Chapter 2 Aftermath" in media_metadata["title"]
        assert "Chapter 2 scenes 4-6" in media_metadata["comment"]

        delivery = chain.MiniMaxH3ChainChapterDelivery()
        passed, _json, number, path, status = delivery.select(
            complete, enabled=False, chapter_number=2)
        assert passed == complete and number == 0 and path == ""
        assert "disabled" in status

        export_dir = chain._new_export_directory(chapter_two, "plates")
        assert "/chapters/02_aftermath/frames/plates" in export_dir

        source_audio = {
            "waveform": torch.arange(60, dtype=torch.float32).reshape(1, 1, 60),
            "sample_rate": 24,
        }
        chapter_two["compatibility"]["source_audio_hash"] = (
            chain._audio_fingerprint(source_audio))
        selected = chain._full_chain_selected_audio(
            chapter_two, "source", None, source_audio)
        assert torch.equal(
            selected["waveform"], source_audio["waveform"][..., 30:60])

        expect_error(
            lambda: chain._load_chapter_manifest("chapter_delivery", 3),
            "No sealed Chapter 3")

    print("H3 chapter delivery: explicit/auto selection, isolated output, "
          "source-audio offset, immutable recovery, and pass-through passed")


if __name__ == "__main__":
    main()
