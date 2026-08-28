#!/usr/bin/env python3
"""Frame-exact cumulative video blend and Plan compatibility regression."""

import importlib.util
import pathlib
import shutil
import sys
import tempfile
import types

import av
import numpy as np
import torch


ROOT = pathlib.Path(__file__).resolve().parents[1]
PACKAGE = "h3_video_blend_unit"

folder_paths = types.ModuleType("folder_paths")
folder_paths.get_output_directory = lambda: folder_paths.output_directory
folder_paths.get_temp_directory = lambda: folder_paths.output_directory
folder_paths.get_input_directory = lambda: folder_paths.output_directory
folder_paths.get_annotated_filepath = lambda value: str(value)
folder_paths.output_directory = str(ROOT)
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


def frames(count, rgb):
    value = torch.zeros((count, 32, 32, 3), dtype=torch.float32)
    value[..., 0] = rgb[0]
    value[..., 1] = rgb[1]
    value[..., 2] = rgb[2]
    return value


def decode(path):
    with av.open(str(path), mode="r") as container:
        return [frame.to_ndarray(format="rgb24")
                for frame in container.decode(container.streams.video[0])]


def normalized(context=90, blend=39, anchor="head"):
    return chain._normalize_plan(
        '{"shots":[{"id":"one","prompt":"one","length":124},'
        '{"id":"two","prompt":"two","length":124}]}',
        "blend_test", 64, 64, context, "video", anchor, "disabled",
        "generated_audio", 22, 5.0, 20, 0, 18,
        generation_fingerprint="test", video_blend_frames=blend)


def main():
    assemble_optional = chain.MiniMaxH3ChainAssemble.INPUT_TYPES()["optional"]
    assert assemble_optional["color_stabilization"][0] == (
        "off", "scene_1_anchor")
    assert assemble_optional["color_stabilization"][1]["default"] == "off"
    brightness, saturation = chain._scene_color_transform(
        {
            "luma_percentiles": [80.0, 130.0, 190.0],
            "saturation_percentiles": [40.0, 60.0, 80.0],
        }, {
            "luma_percentiles": [70.0, 120.0, 180.0],
            "saturation_percentiles": [44.444, 66.667, 88.889],
        })
    assert abs(brightness - (5.0 / 255.0)) < 1e-6
    assert abs(saturation - 0.95) < 1e-3

    plan = normalized()
    assert plan["compatibility"]["context_length"] == 90
    assert plan["compatibility"]["video_blend_frames"] == 39
    assert plan["shots"][1]["delivered_frames"] == 34
    assert "blend=39" in plan["summary"]
    per_scene = chain._normalize_plan(
        '{"shots":[{"id":"one","prompt":"one","length":124},'
        '{"id":"two","prompt":"two","length":124,'
        '"context_length":39,"video_blend_frames":5},'
        '{"id":"three","prompt":"three","length":124,'
        '"context_length":22,"video_blend_frames":0}]}',
        "scene_blend_test", 64, 64, 90, "video", "head", "disabled",
        "generated_audio", 22, 5.0, 20, 0, 18,
        generation_fingerprint="test", video_blend_frames=39)
    assert per_scene["shots"][1]["video_blend_frames"] == 5
    assert per_scene["shots"][2]["video_blend_frames"] == 0
    assert chain._shot_video_blend_frames(
        per_scene["shots"][1], 39, 39) == 5
    assert chain._scene_dependency_record(
        per_scene, 2)["scopes"]["assembly_only"][
            "video_blend_frames"] == 5
    inherited = {"context_length": 22}
    assert chain._shot_video_blend_frames(inherited, 39, 22) == 22
    history_variant = chain._normalize_plan(
        '{"shots":[{"id":"one","prompt":"one","length":124},'
        '{"id":"two","prompt":"two","length":124,'
        '"context_length":39,"video_blend_frames":30},'
        '{"id":"three","prompt":"three","length":124,'
        '"context_length":22,"video_blend_frames":0}]}',
        "scene_blend_test", 64, 64, 90, "video", "head", "disabled",
        "generated_audio", 22, 5.0, 20, 0, 18,
        generation_fingerprint="test", video_blend_frames=39)
    assert chain._history_hash(per_scene, 2) == chain._history_hash(
        history_variant, 2)
    try:
        chain._normalize_plan(
            '{"shots":[{"prompt":"one","length":124},'
            '{"prompt":"two","length":124,"context_length":22,'
            '"video_blend_frames":23}]}',
            "bad_scene_blend", 64, 64, 90, "video", "head", "disabled",
            "generated_audio", 22, 5.0, 20, 0, 18,
            video_blend_frames=0)
    except ValueError as exc:
        assert "Shot 2" in str(exc)
        assert "between 0 and its context length (22)" in str(exc)
    else:
        raise AssertionError("scene blend larger than scene context was accepted")
    try:
        normalized(context=22, blend=23)
    except ValueError as exc:
        assert "between 0 and context_length" in str(exc)
    else:
        raise AssertionError("blend larger than context was accepted")
    try:
        normalized(context=22, blend=5, anchor="before")
    except ValueError as exc:
        assert "requires anchor_mode=head" in str(exc)
    else:
        raise AssertionError("before-mode blend was accepted")
    assert chain._scheduled_blend_frames("plan", 3, 5) == [5, 5, 5]
    assert chain._scheduled_blend_frames("5,30", 4, 0) == [5, 30, 30, 30]
    assert chain._scheduled_blend_frames("0", 2, 39) == [0, 0]
    assert chain._partial_boundary_tone_match_mode({
        "compatibility": {"continuation_mode": "guide"},
        "segments": [],
    }) == "off"
    assert chain._partial_boundary_tone_match_mode({
        "compatibility": {"continuation_mode": "tone_carry_guide"},
        "segments": [],
    }) == "auto"
    assert chain._partial_boundary_tone_match_mode({
        "compatibility": {"continuation_mode": "guide"},
        "segments": [{"guide_tone_input_applied": True}],
    }) == "auto"
    try:
        chain._scheduled_blend_frames("5,nope", 2, 0)
    except ValueError as exc:
        assert "integer frame counts" in str(exc)
    else:
        raise AssertionError("invalid blend schedule was accepted")

    with tempfile.TemporaryDirectory() as temporary:
        folder_paths.output_directory = temporary
        root = pathlib.Path(temporary)
        base = root / "base.mp4"
        extension = root / "extension.mp4"
        # The extension contains two regenerated context frames followed by
        # four genuinely delivered frames.
        chain._write_segment_video(frames(5, (1, 0, 0)), str(base), 24, 0)
        overlap = torch.cat((frames(2, (0, 1, 0)),
                             frames(4, (0, 0, 1))), dim=0)
        chain._write_segment_video(overlap, str(extension), 24, 0)
        streamed_prefix = root / "streamed_prefix.mp4"
        disposable = frames(3, (0, 0, 1))
        clean_prefix = frames(1, (1, 0, 0))
        chain._write_segment_video(
            disposable, str(streamed_prefix), 24, 0,
            replacement_prefix=clean_prefix)
        streamed_frames = decode(streamed_prefix)
        assert streamed_frames[0][0, 0, 0] > 200
        assert streamed_frames[0][0, 0, 2] < 20
        assert streamed_frames[1][0, 0, 2] > 200
        assert torch.all(disposable[..., 2] == 1.0)
        records = [
            {"path": str(base), "input_frames": 5,
             "delivered_frames": 5, "blend_frames": 0},
            {"path": str(extension), "input_frames": 6,
             "delivered_frames": 4, "blend_frames": 2},
        ]

        pyav_output = root / "pyav.mp4"
        chain._pyav_blend_video(
            records, str(pyav_output), {"title": "blend test"}, 9, 0)
        pyav_frames = decode(pyav_output)
        assert len(pyav_frames) == 9
        # The two join frames contain both old red and regenerated green.
        assert pyav_frames[3][0, 0, 0] > 20
        assert pyav_frames[3][0, 0, 1] > 20
        assert pyav_frames[4][0, 0, 0] > 20
        assert pyav_frames[4][0, 0, 1] > 20
        assert pyav_frames[-1][0, 0, 2] > 200

        # Automatic tone matching detects a coherent exposure step only after
        # the protected overlap, fits a capped percentile curve, and applies
        # it from that generated frame onward. The preceding context remains
        # bit-for-bit on the uncorrected path.
        gradient = torch.linspace(
            0.03, 0.73, 32, dtype=torch.float32).reshape(1, 1, 32, 1)
        gradient = gradient.expand(1, 32, 32, 3).contiguous()
        darker = torch.clamp(gradient - (4.0 / 255.0), 0.0, 1.0)
        tone_base_frames = gradient.repeat(10, 1, 1, 1)
        tone_incoming_frames = torch.cat((
            gradient.repeat(8, 1, 1, 1),
            gradient,
            darker.repeat(3, 1, 1, 1),
        ), dim=0)
        tone_base = root / "tone_base.mkv"
        tone_incoming = root / "tone_incoming.mkv"
        chain._write_lossless_rgb_video(
            tone_base_frames, str(tone_base), 24)
        chain._write_lossless_rgb_video(
            tone_incoming_frames, str(tone_incoming), 24)
        tone_records = [
            {"path": str(tone_base), "input_frames": 10,
             "delivered_frames": 10, "blend_frames": 0,
             "skip_frames": 0},
            {"path": str(tone_incoming), "input_frames": 12,
             "delivered_frames": 4, "blend_frames": 8,
             "skip_frames": 0},
        ]
        matched_records = chain._auto_boundary_tone_match_records(
            tone_records)
        tone_match = matched_records[1].get("tone_match")
        assert tone_match is not None
        assert tone_match["start_frame"] == 9
        assert max(abs(value) for value in
                   tone_match["applied_shifts"]) <= 6.0
        assert "curves=all=" in chain._ffmpeg_boundary_tone_filter(
            tone_match)

        # Optional temporal stabilization anchors generated scene one, keeps
        # the exact boundary at the predecessor's accepted transform, then
        # ramps a capped correction through the incoming delivered frames.
        color_records = chain._auto_scene_color_stabilization_records(
            tone_records)
        color_schedule = color_records[1].get(
            "scene_color_stabilization")
        assert color_schedule is not None
        assert color_schedule["start_frame"] == 8
        assert color_schedule["ramp_frames"] == 4
        assert color_schedule["previous_brightness"] == 0.0
        assert color_schedule["previous_saturation"] == 1.0
        assert 0.0 < color_schedule["brightness"] <= 6.0 / 255.0
        assert "hue=b=" in chain._ffmpeg_scene_color_filter(
            color_schedule)
        probe = np.full((8, 8, 3), 100, dtype=np.uint8)
        unchanged = chain._apply_scene_color_stabilization(
            probe, color_schedule, color_schedule["start_frame"])
        assert np.array_equal(unchanged, probe)
        corrected = chain._apply_scene_color_stabilization(
            probe, color_schedule,
            color_schedule["start_frame"] + color_schedule["ramp_frames"])
        assert float(corrected.mean()) > float(probe.mean())
        color_probe = np.full((8, 8, 3), (180, 100, 50), dtype=np.uint8)
        saturation_probe = {
            **color_schedule,
            "previous_brightness": 0.0,
            "brightness": 0.0,
            "previous_saturation": 1.0,
            "saturation": 0.94,
        }
        desaturated = chain._apply_scene_color_stabilization(
            color_probe, saturation_probe,
            saturation_probe["start_frame"] +
            saturation_probe["ramp_frames"])
        assert int(np.ptp(desaturated[0, 0])) < int(np.ptp(color_probe[0, 0]))

        # An existing-video prelude is not the color reference. The first
        # generated segment remains scene one and receives no grade schedule.
        with_prelude = chain._auto_scene_color_stabilization_records([
            {**tone_records[0], "kind": "prelude"},
            {**tone_records[0], "kind": "segment", "scene_index": 1},
            {**tone_records[1], "kind": "segment", "scene_index": 2},
        ])
        assert "scene_color_stabilization" not in with_prelude[0]
        assert "scene_color_stabilization" not in with_prelude[1]
        assert "scene_color_stabilization" in with_prelude[2]

        color_pyav = root / "color_stabilized_pyav.mp4"
        chain._pyav_blend_video(
            color_records, str(color_pyav), {"title": "color anchor"},
            14, 0)
        assert len(decode(color_pyav)) == 14

        # A resume made before Tone Carry metadata existed recovers the same
        # small curve from its two immutable scene videos. The segment record
        # is enriched in memory; its checkpoint/latent is not touched.
        tone_delivered = root / "tone_delivered.mkv"
        chain._write_lossless_rgb_video(
            torch.cat((gradient, darker.repeat(3, 1, 1, 1))),
            str(tone_delivered), 24)
        legacy_state = {
            "segments": [
                {"index": 1, "segment": str(tone_base)},
                {"index": 2, "segment": str(tone_delivered)},
            ],
        }
        recovered_tone = chain._recover_state_guide_tone_carry(legacy_state)
        assert recovered_tone is not None
        assert recovered_tone["version"] == "h3_guide_tone_carry_v1"
        assert recovered_tone["recovered_from"] == "saved_scene_videos"
        assert recovered_tone["start_frame"] == 1
        assert legacy_state["segments"][1][
            "guide_tone_carry"] is recovered_tone
        assert chain._recover_state_guide_tone_carry(
            legacy_state) is recovered_tone
        tone_third = root / "tone_third.mkv"
        chain._write_lossless_rgb_video(
            darker.repeat(8, 1, 1, 1), str(tone_third), 24)
        propagated_records = chain._auto_boundary_tone_match_records(
            tone_records + [{
                "path": str(tone_third), "input_frames": 8,
                "delivered_frames": 4, "blend_frames": 4,
                "skip_frames": 0,
            }])
        assert len(propagated_records[2]["tone_match_prefix"]) == 1
        assert propagated_records[2].get("tone_match") is None
        tone_carried = root / "tone_carried.mkv"
        chain._write_lossless_rgb_video(
            gradient.repeat(8, 1, 1, 1), str(tone_carried), 24)
        generation_carried_records = chain._auto_boundary_tone_match_records(
            tone_records + [{
                "path": str(tone_carried), "input_frames": 8,
                "delivered_frames": 4, "blend_frames": 4,
                "skip_frames": 0, "generation_tone_carry": True,
            }])
        assert not generation_carried_records[2].get("tone_match_prefix")
        assert generation_carried_records[2].get("tone_match") is None

        def mean_luma(array):
            return float(np.mean(
                array[..., 0] * 0.2126 + array[..., 1] * 0.7152 +
                array[..., 2] * 0.0722))

        tone_off = root / "tone_off.mp4"
        tone_auto = root / "tone_auto.mp4"
        chain._pyav_blend_video(
            tone_records, str(tone_off), {"title": "tone off"}, 14, 0)
        chain._pyav_blend_video(
            matched_records, str(tone_auto), {"title": "tone auto"}, 14, 0)
        tone_off_frames = decode(tone_off)
        tone_auto_frames = decode(tone_auto)
        assert abs(mean_luma(tone_off_frames[11]) -
                   mean_luma(tone_off_frames[10])) > 2.0
        assert abs(mean_luma(tone_auto_frames[11]) -
                   mean_luma(tone_auto_frames[10])) < 1.0
        tone_propagated = root / "tone_propagated.mp4"
        chain._pyav_blend_video(
            propagated_records, str(tone_propagated),
            {"title": "tone propagated"}, 18, 0)
        tone_propagated_frames = decode(tone_propagated)
        assert abs(mean_luma(tone_propagated_frames[14]) -
                   mean_luma(tone_propagated_frames[13])) < 1.0

        ffmpeg = shutil.which("ffmpeg")
        if ffmpeg:
            metadata = root / "metadata.txt"
            chain._write_ffmetadata(str(metadata), {"title": "blend test"})
            ffmpeg_output = root / "ffmpeg.mp4"
            chain._ffmpeg_blend_video(
                ffmpeg, records, str(ffmpeg_output), str(metadata), 9, 0)
            assert len(decode(ffmpeg_output)) == 9
            # A first xfade may advertise 1/0 FPS. The second xfade used to
            # reject that intermediate even though every source was CFR.
            chained_output = root / "ffmpeg_three_segments.mp4"
            chained_records = records + [{**records[1]}]
            chain._ffmpeg_blend_video(
                ffmpeg, chained_records, str(chained_output), str(metadata),
                13, 0)
            assert len(decode(chained_output)) == 13
            ffmpeg_tone = root / "ffmpeg_tone_auto.mp4"
            chain._ffmpeg_blend_video(
                ffmpeg, matched_records, str(ffmpeg_tone), str(metadata),
                14, 0)
            ffmpeg_tone_frames = decode(ffmpeg_tone)
            ffmpeg_tone_delta = abs(
                mean_luma(ffmpeg_tone_frames[11]) -
                mean_luma(ffmpeg_tone_frames[10]))
            assert ffmpeg_tone_delta < 1.5, ffmpeg_tone_delta
            ffmpeg_color = root / "ffmpeg_color_anchor.mp4"
            ffmpeg_color_baseline = root / "ffmpeg_color_baseline.mp4"
            chain._ffmpeg_blend_video(
                ffmpeg, tone_records, str(ffmpeg_color_baseline),
                str(metadata), 14, 0)
            chain._ffmpeg_blend_video(
                ffmpeg, color_records, str(ffmpeg_color), str(metadata),
                14, 0)
            ffmpeg_color_baseline_frames = decode(ffmpeg_color_baseline)
            ffmpeg_color_frames = decode(ffmpeg_color)
            assert len(ffmpeg_color_frames) == 14
            assert mean_luma(ffmpeg_color_frames[-1]) > (
                mean_luma(ffmpeg_color_baseline_frames[-1]) + 0.2)
            seam_mad = float(np.abs(
                ffmpeg_color_frames[10].astype(np.int16) -
                ffmpeg_color_baseline_frames[10].astype(np.int16)).mean())
            assert seam_mad < 1.0, seam_mad

        checkpoint_one = root / "one.safetensors"
        checkpoint_two = root / "two.safetensors"
        checkpoint_one.write_bytes(b"one")
        checkpoint_two.write_bytes(b"two")

        def segment(index, video, checkpoint, delivered, raw, blend_video=None):
            value = {
                "index": index,
                "id": "clip_%04d" % index,
                "segment": str(video),
                "checkpoint": str(checkpoint),
                "raw_frames": raw,
                "delivered_frames": delivered,
                "segment_sha256": chain._file_sha256(str(video)),
                "checkpoint_sha256": chain._file_sha256(str(checkpoint)),
            }
            if blend_video is not None:
                value.update({
                    "blend_segment": str(blend_video),
                    "blend_segment_sha256": chain._file_sha256(
                        str(blend_video)),
                    "blend_frames": raw - delivered,
                })
            return value

        blended_manifest = {
            "format": "h3_chain_manifest_v2",
            "run_name": "assembled_blend",
            "clip_count": 2,
            "total_delivered_frames": 9,
            "compatibility": {
                "audio_mode": "generated_audio", "segment_crf": 0,
                "video_blend_frames": 2,
            },
            "segments": [
                segment(1, base, checkpoint_one, 5, 5),
                segment(2, extension, checkpoint_two, 4, 6, extension),
            ],
        }
        assembled = chain.MiniMaxH3ChainAssemble().assemble(
            blended_manifest, "none", "final", 128)["result"][0]
        assert len(decode(assembled)) == 9

        scheduled_records = chain._blend_video_records(
            blended_manifest, blended_manifest["segments"], None,
            blend_schedule="1")
        assert scheduled_records[1]["blend_frames"] == 1
        assert scheduled_records[1]["skip_frames"] == 1
        assert scheduled_records[1]["input_frames"] == 5
        per_scene_overlap = root / "per_scene_overlap.mp4"
        chain._write_segment_video(
            torch.cat((frames(1, (0, 1, 0)), frames(4, (0, 0, 1))),
                      dim=0),
            str(per_scene_overlap), 24, 0)
        per_scene_manifest = {
            **blended_manifest,
            "segments": [
                blended_manifest["segments"][0],
                {**blended_manifest["segments"][1],
                 "blend_segment": str(per_scene_overlap),
                 "blend_segment_sha256": chain._file_sha256(
                     str(per_scene_overlap)),
                 "blend_frames": 1},
            ],
        }
        plan_records = chain._blend_video_records(
            per_scene_manifest, per_scene_manifest["segments"], None,
            blend_schedule="plan")
        assert plan_records[1]["blend_frames"] == 1
        assert plan_records[1]["skip_frames"] == 0
        scheduled = chain.MiniMaxH3ChainAssemble().assemble(
            blended_manifest, "none", "scheduled_one", 128,
            blend_schedule="1")["result"][0]
        assert len(decode(scheduled)) == 9

        # A larger recovery blend is reconstructed from the existing raw
        # checkpoint latent through the optional VAE. The intermediate is
        # lossless RGB and is deleted after final assembly.
        narrow_overlap = root / "narrow_overlap.mp4"
        chain._write_segment_video(
            torch.cat((frames(1, (0, 1, 0)), frames(4, (0, 0, 1))),
                      dim=0),
            str(narrow_overlap), 24, 0)
        recoverable_checkpoint = root / "recoverable.safetensors"
        chain._st_save(
            {"video": torch.zeros((1, 1), dtype=torch.float32)},
            str(recoverable_checkpoint))
        recoverable_delivered = root / "recoverable_delivered.mp4"
        chain._write_segment_video(
            frames(4, (0, 0, 1)), str(recoverable_delivered), 24, 0)
        recoverable_two = segment(
            2, recoverable_delivered,
            recoverable_checkpoint, 4, 6)
        recoverable_two.update({
            "blend_segment": str(narrow_overlap),
            "blend_segment_sha256": chain._file_sha256(str(narrow_overlap)),
            "blend_frames": 1,
        })
        recoverable_manifest = {
            **blended_manifest,
            "run_name": "assembled_recovered_schedule",
            "compatibility": {
                **blended_manifest["compatibility"],
                "video_blend_frames": 1,
            },
            "segments": [
                segment(1, base, checkpoint_one, 5, 5),
                recoverable_two,
            ],
        }

        class FakeVideoVAE:
            def decode(self, _video):
                return overlap.clone()

        recovered = chain.MiniMaxH3ChainAssemble().assemble(
            recoverable_manifest, "none", "scheduled_recovered", 128,
            blend_schedule="2", blend_video_vae=FakeVideoVAE())["result"][0]
        assert len(decode(recovered)) == 9
        assert not list((root / "h3_chains" /
                         "assembled_recovered_schedule" / "final").glob(
                             ".scheduled_blend_clip_*"))

        delivered_two = root / "delivered_two.mp4"
        chain._write_segment_video(
            frames(4, (0, 0, 1)), str(delivered_two), 24, 0)
        hard_manifest = {
            **blended_manifest,
            "run_name": "assembled_hard",
            "compatibility": {
                **blended_manifest["compatibility"],
                "video_blend_frames": 0,
            },
            "segments": [
                segment(1, base, checkpoint_one, 5, 5),
                segment(2, delivered_two, checkpoint_two, 4, 6),
            ],
        }
        hard = chain.MiniMaxH3ChainAssemble().assemble(
            hard_manifest, "none", "final", 128)["result"][0]
        assert len(decode(hard)) == 9
        forced_hard_records = chain._blend_video_records(
            hard_manifest, hard_manifest["segments"], None,
            force_records=True)
        assert len(forced_hard_records) == 2
        assert not any(record["blend_frames"]
                       for record in forced_hard_records)
        stabilized_hard = chain.MiniMaxH3ChainAssemble().assemble(
            hard_manifest, "none", "color_anchor", 128,
            color_stabilization="scene_1_anchor")["result"][0]
        assert len(decode(stabilized_hard)) == 9

        # Editorial placement does not alter the saved chain. Assemble inserts
        # exact black track time before the later scene and keeps its frames.
        chain._save_run_editorial_document({
            "run_name": "assembled_hard",
            "scene_order": [
                {"scene": 1, "scene_id": "clip_0001"},
                {"scene": 2, "scene_id": "clip_0002"},
            ],
            "chapters": [],
            "placements": [{
                "scene": 2, "scene_id": "clip_0002", "start_frame": 8,
            }],
        })
        editorial_output = chain.MiniMaxH3ChainAssemble().assemble(
            hard_manifest, "none", "editorial_gap", 128)["result"][0]
        editorial_frames = decode(editorial_output)
        assert len(editorial_frames) == 12
        assert all(np.max(frame) == 0 for frame in editorial_frames[5:8])
        assert np.mean(editorial_frames[8][..., 2]) > 200

    print("H3 video blend: extended context validation, scheduled recovery, "
          "automatic boundary tone matching, scene-one temporal color "
          "stabilization, chained xfade CFR, and frame-exact PyAV/ffmpeg "
          "assembly pass")


if __name__ == "__main__":
    main()
