#!/usr/bin/env python3
"""CPU smoke test for H3 chain timing, segments, checkpoints and resume.

Uses the adjacent ComfyUI checkout for its real node/runtime modules, but no
model or GPU.  It encodes two tiny H.264 segments, resumes clip 2 from clip 1's
safetensors checkpoint, and assembles both source-track and generated-audio
outputs with ffmpeg.
"""

import asyncio
import hashlib
import importlib.util
import json
import pathlib
import subprocess
import sys
import tempfile
import threading
import time


ROOT = pathlib.Path(__file__).resolve().parents[1]
COMFY_CANDIDATES = [ROOT.parent / "Comfyui", ROOT.parent / "ComfyUI"]
COMFY = next((path for path in COMFY_CANDIDATES
              if (path / "comfy" / "options.py").is_file()), None)
if COMFY is None:
    raise SystemExit("adjacent ComfyUI checkout not found")

sys.path.insert(0, str(COMFY))
sys.argv = ["h3-chain-smoke", "--cpu"]
import comfy.options  # noqa: E402

comfy.options.enable_args_parsing()
import folder_paths  # noqa: E402
import torch  # noqa: E402
import execution  # noqa: E402
import nodes as comfy_nodes  # noqa: E402
from PIL import Image as PILImage  # noqa: E402
from safetensors import safe_open  # noqa: E402


def load_package():
    spec = importlib.util.spec_from_file_location(
        "h3_chain_smoke_package",
        ROOT / "__init__.py",
        submodule_search_locations=[str(ROOT)],
    )
    package = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = package
    spec.loader.exec_module(package)
    return package, sys.modules[spec.name + ".chain_nodes"]


def av_latent(video_t=1, audio_t=9):
    return {
        "samples": [
            torch.zeros((1, 16, video_t, 2, 2), dtype=torch.float32),
            torch.zeros((1, 32, 2, audio_t), dtype=torch.float32),
        ]
    }


def audio_for_frames(frames, sample_rate=8000):
    samples = round(frames / 24.0 * sample_rate)
    return {
        "waveform": torch.zeros((1, 2, samples), dtype=torch.float32),
        "sample_rate": sample_rate,
    }


class FakeDynamicPrompt:
    def __init__(self, prompt):
        self.prompt = prompt

    def get_node(self, node_id):
        return self.prompt[str(node_id)]

    def get_display_node_id(self, node_id):
        return str(node_id)

    def get_original_prompt(self):
        return self.prompt


def main():
    package, chain = load_package()

    async def review_route_check():
        token = "review-route-smoke"
        future = asyncio.get_running_loop().create_future()
        chain._PENDING_REVIEWS[token] = {
            "future": future,
            "loop": asyncio.get_running_loop(),
            "public": {"token": token, "prompt_prefix": "Shared only."},
            "current_seed": 7,
        }

        class Request:
            async def json(self):
                return {
                    "token": token,
                    "action": "retry",
                    "scene_prompt": "",
                    "seed": "18446744073709551615",
                }

        try:
            response = await chain._submit_review_decision(Request())
            assert response.status == 200
            decision = await future
            assert decision["action"] == "retry"
            assert decision["scene_prompt"] == ""
            assert decision["seed"] == 18446744073709551615
        finally:
            chain._PENDING_REVIEWS.pop(token, None)

    asyncio.run(review_route_check())
    print("review: async decision route preserves exact uint64 seeds")
    required = {
        "MiniMaxH3ChainPlan", "MiniMaxH3ChainScenePromptEditor",
        "MiniMaxH3ReferenceVideoPrepare",
        "MiniMaxH3ChainExternalVideo",
        "MiniMaxH3ChainLoopStart",
        "MiniMaxH3ChainCurrent", "MiniMaxH3ChainContext",
        "MiniMaxH3ChainSegmentSave", "MiniMaxH3ChainLoopEnd",
        "MiniMaxH3ChainManifestLoad", "MiniMaxH3ChainExportPNG",
        "MiniMaxH3ChainAssemble",
        "MiniMaxH3LoopTrim",
    }
    assert required <= set(package.NODE_CLASS_MAPPINGS)
    upstream_ids = {
        "MiniMaxH3MotionContext",
        "MiniMaxH3MotionContextTrim",
        "MiniMaxH3MotionContextSaveLatent",
        "MiniMaxH3MotionContextLoadLatent",
    }
    assert not upstream_ids.intersection(package.NODE_CLASS_MAPPINGS)
    layout_patch = sys.modules[package.__name__ + ".patch_layout"]
    payload_patch = sys.modules[package.__name__ + ".patch_payload"]
    for module in (layout_patch, payload_patch):
        assert module.MC_KEY == "motion_context_index"
        assert module.MC_AUDIO_KEY == "motion_context_audio_end_frame"
    assert layout_patch.PATCH_MARKER == "_h3_motion_context_layout_patch"
    assert payload_patch.PATCH_MARKER == "_h3_motion_context_payload_patch"
    print("coexistence: node ids are disjoint and runtime patch ABI is shared")
    assert package.WEB_DIRECTORY == "./web"
    assert (ROOT / "web" / "h3_chain_plan_editor.js").is_file()
    assert (ROOT / "web" / "h3_chain_plan_core.mjs").is_file()
    assert (ROOT / "web" / "h3_chain_scene_prompt_editor.js").is_file()
    workflow_path = (ROOT / "example_workflows" /
                     "Looping MiniMax H3 Seamless Chain Global Refs Example.json")
    workflow = json.loads(workflow_path.read_text(encoding="utf-8"))
    workflow_types = {node.get("type") for node in workflow["nodes"]}
    assert "MiniMaxH3LoopTrim" in workflow_types
    assert not upstream_ids.intersection(workflow_types)
    loop_nodes = [
        node for node in workflow["nodes"]
        if node.get("type") == "MiniMaxH3LoopTrim"
        or str(node.get("type", "")).startswith("MiniMaxH3Chain")
    ]
    assert loop_nodes and all(
        node.get("properties", {}).get("aux_id") ==
        "ethanfel/ComfyUI-MiniMaxH3-Contex-Loop"
        for node in loop_nodes)
    workflow_start = next(
        node for node in workflow["nodes"]
        if node.get("type") == "MiniMaxH3ChainLoopStart")
    assert workflow_start.get("widgets_values") == [1, ""]
    assert "SEGMENT" not in str(workflow_start.get("title", "")).upper()
    print("workflow: loop node ids and package metadata use the new namespace")

    angle_workflow_path = (ROOT / "example_workflows" /
                           "EXPERIMENTAL MiniMax H3 Three-Angle Guitar Ref2VA.json")
    angle_workflow = json.loads(
        angle_workflow_path.read_text(encoding="utf-8"))
    angle_types = {node.get("type") for node in angle_workflow["nodes"]}
    assert "MiniMaxH3ReferenceVideoPrepare" in angle_types
    assert "MiniMaxH3ReferenceToVideo" in angle_types
    assert "MiniMaxH3LoopTrim" in angle_types
    assert not any(str(value).startswith("MiniMaxH3ChainLoop")
                   for value in angle_types)
    angle_loader = next(node for node in angle_workflow["nodes"]
                        if node.get("type") == "LoadVideo")
    angle_prep = next(node for node in angle_workflow["nodes"]
                      if node.get("type") == "MiniMaxH3ReferenceVideoPrepare")
    angle_ref = next(node for node in angle_workflow["nodes"]
                     if node.get("type") == "MiniMaxH3ReferenceToVideo")
    assert angle_loader["widgets_values"][0] == "3ClbaJYWVO4_000030.mp4"
    assert angle_prep["widgets_values"] == [209, 24.0]
    prompt = angle_ref["widgets_values"][0]
    sections = ["subject_definitions:", "summary:", "retention_analysis:",
                "detailed_description:", "overall_soundscape:",
                "non_diegetic_music:"]
    positions = [prompt.index(section) for section in sections]
    assert positions == sorted(positions)
    assert "exactly three shots" in prompt
    assert "Tera Echo product card" in prompt
    links = {int(link[0]): link for link in angle_workflow["links"]}
    prep_audio_links = next(
        output["links"] for output in angle_prep["outputs"]
        if output["name"] == "source_audio")
    assert len(prep_audio_links) == 2
    assert {links[link_id][3] for link_id in prep_audio_links} == {110, 132}
    print("workflow: one-pass three-angle Ref2VA copies source audio exactly")

    # Every public socket/widget should explain its role in the graph, and
    # every output should describe what it carries. This keeps newly added
    # controls from silently regressing to opaque ComfyUI labels.
    for node_name, node_class in package.NODE_CLASS_MAPPINGS.items():
        schema = node_class.INPUT_TYPES()
        for section in ("required", "optional"):
            for input_name, input_spec in schema.get(section, {}).items():
                options = input_spec[1] if len(input_spec) > 1 else {}
                assert isinstance(options, dict) and str(
                    options.get("tooltip", "")).strip(), (
                        "%s.%s has no tooltip" % (node_name, input_name))
        output_tooltips = getattr(node_class, "OUTPUT_TOOLTIPS", ())
        assert len(output_tooltips) == len(node_class.RETURN_TYPES), (
            "%s output tooltip count is %d; expected %d" %
            (node_name, len(output_tooltips), len(node_class.RETURN_TYPES)))
        assert all(str(value).strip() for value in output_tooltips), (
            "%s has an empty output tooltip" % node_name)
    print("tooltips: every public input and output is documented")

    readable_prompts = chain._normalize_plan(
        json.dumps({
            "prompt_prefix": ["Shared identity.", "", "Shared wardrobe."],
            "shots": [{
                "id": "multiline",
                "prompt": [
                    "Use <Picture 1> for her facial identity.",
                    "Throughout every scene S1 wears the same dress.",
                    "<Subject 2> enters from camera right.",
                ],
                "length": 39,
            }],
        }),
        "readable", 32, 32, 22, "video", "head", "disabled",
        "source_track", 0, 15, 2, 1, 30,
    )
    assert readable_prompts["shots"][0]["prompt"] == (
        "Shared identity.\n\nShared wardrobe.\n\n"
        "Use <Picture 1> for her facial identity.\n"
        "Throughout every scene S1 wears the same dress.\n"
        "<Subject 2> enters from camera right."
    )
    prompt_editor = package.NODE_CLASS_MAPPINGS[
        "MiniMaxH3ChainScenePromptEditor"]()
    assert prompt_editor.passthrough(readable_prompts)[0] is readable_prompts
    shared_only = chain._normalize_plan(
        json.dumps({
            "prompt_prefix": ["Shared identity.", "", "Shared direction."],
            "shots": [{"id": "shared_only", "prompt": "", "length": 39}],
        }),
        "shared_only", 32, 32, 22, "video", "head", "disabled",
        "source_track", 0, 15, 2, 1, 30,
    )
    assert shared_only["shots"][0]["scene_prompt"] == ""
    assert shared_only["shots"][0]["prompt"] == (
        "Shared identity.\n\nShared direction.")
    shared_only_revision = chain._plan_with_review_revision(
        shared_only, 1, "", 123)
    assert shared_only_revision["shots"][0]["scene_prompt"] == ""
    assert shared_only_revision["shots"][0]["prompt"] == (
        "Shared identity.\n\nShared direction.")
    try:
        chain._normalize_plan(
            json.dumps({"shots": [{"id": "empty", "prompt": ""}]}),
            "empty", 32, 32, 22, "video", "head", "disabled",
            "source_track", 0, 15, 2, 1, 30,
        )
    except ValueError as exc:
        assert "scene prompt or shared prompt" in str(exc)
    else:
        raise AssertionError("plan accepted an empty scene and shared prompt")
    numeric_seed_plan = chain._normalize_plan(
        '{"shots":[{"prompt":"seed test","seed":18446744073709551615}]}',
        "numeric_seed", 32, 32, 22, "video", "head", "disabled",
        "source_track", 0, 15, 2, 1, 30,
    )
    string_seed_plan = chain._normalize_plan(
        '{"shots":[{"prompt":"seed test","seed":"18446744073709551615"}]}',
        "numeric_seed", 32, 32, 22, "video", "head", "disabled",
        "source_track", 0, 15, 2, 1, 30,
    )
    assert numeric_seed_plan["shots"][0]["seed"] == chain.MAX_SEED
    assert numeric_seed_plan["plan_hash"] == string_seed_plan["plan_hash"]
    shorthand_defaults = chain._normalize_plan(
        '{"duration_seconds":8,"steps":10,'
        '"shots":[{"prompt":"top-level defaults"}]}',
        "shorthand_defaults", 32, 32, 22, "video", "head", "disabled",
        "source_track", 0, 15, 20, 1, 30,
    )
    assert shorthand_defaults["shots"][0]["raw_frames"] == 192
    assert shorthand_defaults["shots"][0]["steps"] == 10
    try:
        chain._normalize_plan(
            json.dumps({"shots": [{"prompt": ["valid", 42]}]}),
            "bad_lines", 32, 32, 22, "video", "head", "disabled",
            "source_track", 0, 15, 2, 1, 30,
        )
    except ValueError as exc:
        assert "only strings" in str(exc)
    else:
        raise AssertionError("prompt line array accepted a non-string item")
    print("prompts: multiline and shared-only scenes pass; fully empty prompts fail")

    assert chain._parse_scene_range("", 8, 1) == (1, 8)
    assert chain._parse_scene_range("3", 8, 1) == (3, 3)
    assert chain._parse_scene_range(" 3 : 8 ", 8, 1) == (3, 8)
    assert chain._parse_scene_range("", 8, 4) == (4, 8)
    for invalid in ("1,3", "3:2", "0:2", "2:9", "abc"):
        try:
            chain._parse_scene_range(invalid, 8, 1)
        except ValueError:
            pass
        else:
            raise AssertionError("scene_range accepted %r" % invalid)
    print("scene range: blank, single scene, and one inclusive range validated")

    # ComfyUI rounds H3's 40 Hz audio grid to the nearest step. Depending on
    # frame length, the decoded stream can land 1/3 step above or below the
    # exact 24 fps picture duration. Match Tail must frame-lock both cases.
    trim_node = package.NODE_CLASS_MAPPINGS["MiniMaxH3LoopTrim"]()
    short_images = torch.zeros((260, 1, 1, 3), dtype=torch.float32)
    short_samples = 346400  # 433 audio steps; exact 260f target is 346667
    short_audio = {
        "waveform": torch.ones((1, 2, short_samples), dtype=torch.float32),
        "sample_rate": 32000,
    }
    _, padded = trim_node.trim(short_images, 0, short_audio, 24.0, True)
    assert int(padded["waveform"].shape[-1]) == 346667
    assert torch.count_nonzero(padded["waveform"][..., short_samples:]) == 0
    chain._validate_audio(padded, "260-frame regression", expected_frames=260)

    long_images = torch.zeros((124, 1, 1, 3), dtype=torch.float32)
    long_samples = 165600  # 207 audio steps; exact 124f target is 165333
    long_audio = {
        "waveform": torch.ones((1, 2, long_samples), dtype=torch.float32),
        "sample_rate": 32000,
    }
    _, truncated = trim_node.trim(long_images, 0, long_audio, 24.0, True)
    assert int(truncated["waveform"].shape[-1]) == 165333
    print("trim: 260-frame shortage padded and 124-frame excess truncated")

    giant_plan = chain._normalize_plan(
        json.dumps({
            "shots": [
                {"id": str(index), "prompt": "shot %d" % index}
                for index in range(1, 14)
            ] + [{"id": "14", "prompt": "outro", "duration_seconds": 5}]
        }),
        "timing", 960, 544, 22, "video", "head", "disabled",
        "source_track", 22, 15, 20, 123, 18,
    )
    assert giant_plan["shots"][0]["raw_frames"] == 362
    assert giant_plan["shots"][1]["generation_start_frame"] == 340
    assert giant_plan["shots"][-1]["raw_frames"] == 124
    assert giant_plan["shots"][-1]["generation_start_frame"] == 4420
    assert giant_plan["total_delivered_frames"] == 4544
    print("timing: 14 clips -> 4544 frames / 189.333s; frame-exact starts pass")

    assert chain._h3_frame_length(5 / 24 + 0.001) == 22
    assert chain._h3_frame_length(22 / 24 + 0.001) == 39
    try:
        chain._h3_frame_length(150.0)
    except ValueError as exc:
        assert "largest valid" in str(exc)
    else:
        raise AssertionError("duration-derived length exceeded H3's maximum")
    print("duration grid: always rounds up and rejects over-limit lengths")

    before_plan = chain._normalize_plan(
        json.dumps({"shots": ["first", "second", "third", "fourth"]}),
        "before", 32, 32, 1, "video", "before", "disabled",
        "generated_audio", 1, 0.1, 2, 1, 30,
    )
    assert [shot["delivered_frames"] for shot in before_plan["shots"]] == [5] * 4
    assert before_plan["shots"][1]["generation_start_frame"] == 5

    try:
        chain._normalize_plan(
            json.dumps({"shots": [
                {"prompt": "too short", "length": 5},
                {"prompt": "next", "length": 39},
            ]}),
            "short", 32, 32, 22, "video", "head", "disabled",
            "generated_audio", 22, 1, 2, 1, 30,
        )
    except ValueError as exc:
        assert "next clip requires 22 context frames" in str(exc)
    else:
        raise AssertionError("plan accepted an undersized predecessor context")

    plan = chain._normalize_plan(
        json.dumps({"shots": [
            {"id": "one", "prompt": "first", "length": 5, "seed": 1},
            {"id": "two", "prompt": "second", "length": 5, "seed": 2},
        ]}),
        "smoke", 32, 32, 1, "video", "head", "disabled",
        "source_track", 1, 1, 2, 1, 30,
    )
    assert [shot["delivered_frames"] for shot in plan["shots"]] == [5, 4]

    observed = {}

    class SmokePlan:
        @classmethod
        def INPUT_TYPES(cls):
            return {"required": {}}

        RETURN_TYPES = (chain.PLAN_TYPE,)
        FUNCTION = "make"

        def make(self):
            return (before_plan,)

    class SmokeBody:
        @classmethod
        def INPUT_TYPES(cls):
            return {"required": {"state": (chain.STATE_TYPE,)}}

        RETURN_TYPES = ("IMAGE", "LATENT", chain.SEGMENT_TYPE)
        FUNCTION = "render"

        def render(self, state):
            shot = state["plan"]["shots"][state["index"] - 1]
            images = torch.zeros(
                (shot["delivered_frames"], 32, 32, 3), dtype=torch.float32)
            segment = {"index": state["index"], "id": shot["id"]}
            return (images, av_latent(), segment)

    class SmokeSink:
        @classmethod
        def INPUT_TYPES(cls):
            return {"required": {"manifest": (chain.MANIFEST_TYPE,)}}

        RETURN_TYPES = ("STRING",)
        FUNCTION = "take"
        OUTPUT_NODE = True

        def take(self, manifest):
            observed["manifest"] = manifest
            return ("ok",)

    class SmokeServer:
        client_id = None
        last_node_id = None

        def send_sync(self, *args, **kwargs):
            pass

    runtime_nodes = dict(package.NODE_CLASS_MAPPINGS)
    runtime_nodes.update({
        "H3ChainSmokePlan": SmokePlan,
        "H3ChainSmokeBody": SmokeBody,
        "H3ChainSmokeSink": SmokeSink,
    })
    previous_nodes = {name: comfy_nodes.NODE_CLASS_MAPPINGS.get(name)
                      for name in runtime_nodes}
    comfy_nodes.NODE_CLASS_MAPPINGS.update(runtime_nodes)
    try:
        prompt = {
            "1": {"class_type": "H3ChainSmokePlan", "inputs": {}},
            "2": {"class_type": "MiniMaxH3ChainLoopStart", "inputs": {
                "plan": ["1", 0], "start_clip": 1,
                "scene_range": "1:2",
            }},
            "3": {"class_type": "H3ChainSmokeBody", "inputs": {
                "state": ["2", 1],
            }},
            "4": {"class_type": "MiniMaxH3ChainLoopEnd", "inputs": {
                "flow": ["2", 0], "state": ["2", 1],
                "images": ["3", 0], "sampled_latent": ["3", 1],
                "segment": ["3", 2],
            }},
            "5": {"class_type": "H3ChainSmokeSink", "inputs": {
                "manifest": ["4", 0],
            }},
        }
        executor = execution.PromptExecutor(
            SmokeServer(),
            cache_type=execution.CacheType.CLASSIC,
            cache_args={"ram": 0, "ram_inactive": 0},
        )
        executor.execute(prompt, "h3-chain-recursion-smoke", execute_outputs=["5"])
        assert executor.success
        assert observed["manifest"]["clip_count"] == 2
        assert len(observed["manifest"]["segments"]) == 2
        assert observed["manifest"]["format"] == "h3_chain_partial_manifest_v3"
        assert observed["manifest"]["planned_clip_count"] == 4
        print("runtime recursion: scene_range 1:2 stopped a four-clip plan at 2")
    finally:
        for name, previous in previous_nodes.items():
            if previous is None:
                comfy_nodes.NODE_CLASS_MAPPINGS.pop(name, None)
            else:
                comfy_nodes.NODE_CLASS_MAPPINGS[name] = previous

    previous_output = folder_paths.get_output_directory()
    with tempfile.TemporaryDirectory() as tempdir:
        folder_paths.set_output_directory(tempdir)
        try:
            source = audio_for_frames(9)
            changed_source = audio_for_frames(9)
            changed_source["waveform"][..., 0] = 1.0
            prepared_plan = chain._plan_with_source_audio(plan, source)
            assert prepared_plan["plan_hash"] == chain._fingerprint({
                "base_plan_hash": plan["plan_hash"],
                "source_audio_hash": chain._audio_fingerprint(source),
            })
            started = chain.MiniMaxH3ChainLoopStart().start(plan, 1, source)
            assert started[1]["plan"]["compatibility"]["source_audio_hash"]
            current = chain.MiniMaxH3ChainCurrent().current(started[1], source)
            assert current[1:3] == (1, 2)
            assert current[6:10] == (5, 2, 32, 32)
            assert int(current[12]["waveform"].shape[-1]) == round(5 / 24 * 8000)
            try:
                chain.MiniMaxH3ChainCurrent().current(
                    started[1], changed_source)
            except ValueError as exc:
                assert "different source waveform" in str(exc)
            else:
                raise AssertionError("Current Shot accepted a different source song")
            short_source = audio_for_frames(4)
            short_started = chain.MiniMaxH3ChainLoopStart().start(
                plan, 1, short_source)
            assert short_started[1]["plan"]["compatibility"][
                "source_audio_silent_padding"]
            short_current = chain.MiniMaxH3ChainCurrent().current(
                short_started[1], short_source)
            assert int(short_current[12]["waveform"].shape[-1]) == round(
                5 / 24 * 8000)
            assert not torch.count_nonzero(short_current[12]["waveform"])
            short_non_silent = audio_for_frames(4)
            short_non_silent["waveform"][..., 0] = 0.25
            try:
                chain.MiniMaxH3ChainLoopStart().start(
                    plan, 1, short_non_silent)
            except ValueError as exc:
                assert "Only silent placeholder audio" in str(exc)
            else:
                raise AssertionError("Loop Start accepted a short non-silent song")
            conditioning = [["cond", {}]]
            bypass = chain.MiniMaxH3ChainContext().apply(
                started[1], conditioning, None, av_latent())
            assert bypass == (conditioning, 0, False)
            print("current/context: source window exact; short silence pads safely")

            external_plan = chain._normalize_plan(
                json.dumps({"shots": [
                    {"id": "extension_one", "prompt": "continue", "length": 5},
                    {"id": "extension_two", "prompt": "continue again", "length": 5},
                ]}),
                "external_smoke", 32, 32, 1, "video", "head", "disabled",
                "source_plus_timeline", 5, 1, 2, 11, 30,
            )
            source_frames = torch.zeros((8, 32, 32, 3), dtype=torch.float32)
            for frame_index in range(8):
                source_frames[frame_index, ..., 0] = frame_index / 10.0
            source_video_audio = audio_for_frames(8)
            source_video_audio["waveform"].fill_(0.75)
            adapter = chain.MiniMaxH3ChainExternalVideo()
            external_context, external_status = adapter.prepare(
                external_plan, source_frames, 30.0, True, source_video_audio)
            assert "decoded IMAGE/AUDIO" in external_status
            assert "will be prepended" in external_status
            assert tuple(external_context["context_frames"].shape) == (
                1, 32, 32, 3)
            assert int(external_context["context_audio"][
                "waveform"].shape[-1]) == round(5 / 24 * 8000)
            assert abs(float(external_context["context_frames"][0, 0, 0, 0])
                       - 0.6) < 1e-6
            prelude = external_context["prelude"]
            assert prelude["frame_count"] == 6
            assert pathlib.Path(
                tempdir, prelude["video"]).is_file()
            assert pathlib.Path(
                tempdir, prelude["audio"]).is_file()

            class FakeVideoComponents:
                images = source_frames
                audio = source_video_audio
                frame_rate = 30

            class FakeNativeVideo:
                def get_components(self):
                    return FakeVideoComponents()

            ref_prep = chain.MiniMaxH3ReferenceVideoPrepare()
            ref_frames, ref_audio, ref_length, ref_status = ref_prep.prepare(
                5, 1.0, source_video=FakeNativeVideo())
            assert ref_length == 5
            assert tuple(ref_frames.shape) == (5, 32, 32, 3)
            assert abs(float(ref_frames[-1, 0, 0, 0]) - 0.5) < 1e-6
            assert int(ref_audio["waveform"].shape[-1]) == round(
                5 / 24 * 8000)
            assert torch.all(ref_audio["waveform"] == 0.75)
            assert "native VIDEO" in ref_status
            assert "5 frames at 24 fps" in ref_status
            ref_override_audio = audio_for_frames(8)
            ref_override_audio["waveform"].fill_(0.5)
            decoded_ref = ref_prep.prepare(
                5, 30.0, source_frames=source_frames,
                source_audio=ref_override_audio)
            assert "decoded IMAGE/AUDIO" in decoded_ref[3]
            assert torch.all(decoded_ref[1]["waveform"] == 0.5)
            try:
                ref_prep.prepare(
                    22, 30.0, source_frames=source_frames,
                    source_audio=source_video_audio)
            except ValueError as exc:
                assert "Choose a shorter H3-valid length" in str(exc)
            else:
                raise AssertionError(
                    "reference-video prep accepted an overlong source")
            print("reference prep: native/decoded video and exact audio copy pass")

            native_context, native_status = adapter.prepare(
                external_plan, source_fps=1.0, prepend_original=False,
                source_video=FakeNativeVideo())
            assert "native VIDEO" in native_status
            assert "30.000 fps" in native_status
            assert native_context["prelude"] is None
            assert abs(float(native_context[
                "context_frames"][0, 0, 0, 0]) - 0.6) < 1e-6
            assert int(native_context["context_audio"][
                "waveform"].shape[-1]) == round(5 / 24 * 8000)
            override_audio = audio_for_frames(8)
            override_audio["waveform"].fill_(0.5)
            overridden_context = adapter.prepare(
                external_plan, source_fps=24.0, prepend_original=False,
                source_audio=override_audio,
                source_video=FakeNativeVideo())[0]
            assert torch.allclose(
                overridden_context["context_audio"]["waveform"],
                torch.full_like(
                    overridden_context["context_audio"]["waveform"], 0.5))
            try:
                adapter.prepare(
                    external_plan, source_frames, 30.0, False,
                    source_video=FakeNativeVideo())
            except ValueError as exc:
                assert "both source_video and source_frames" in str(exc)
            else:
                raise AssertionError(
                    "existing-video adapter accepted both video input routes")
            try:
                adapter.prepare(
                    external_plan, source_fps=30.0, prepend_original=False)
            except ValueError as exc:
                assert "requires source_video or source_frames" in str(exc)
            else:
                raise AssertionError(
                    "existing-video adapter accepted no video input")

            extension_audio = audio_for_frames(8)
            extension_audio["waveform"].fill_(0.25)
            external_started = chain.MiniMaxH3ChainLoopStart().start(
                external_plan, 1, extension_audio,
                external_context=external_context)
            external_state1 = external_started[1]
            effective_external_plan = external_state1["plan"]
            assert [shot["delivered_frames"] for shot in
                    effective_external_plan["shots"]] == [4, 4]
            assert effective_external_plan["total_delivered_frames"] == 8
            assert external_state1["external_context"]
            assert tuple(external_state1["previous_frames"].shape) == (
                1, 32, 32, 3)
            first_current = chain.MiniMaxH3ChainCurrent().current(
                external_state1, extension_audio)
            first_slice = first_current[12]["waveform"]
            first_lead_samples = round(1 / 24 * 8000)
            assert int(first_slice.shape[-1]) == round(5 / 24 * 8000)
            assert torch.allclose(
                first_slice[..., :first_lead_samples],
                torch.full_like(first_slice[..., :first_lead_samples], 0.75))
            assert torch.allclose(
                first_slice[..., first_lead_samples:],
                torch.full_like(first_slice[..., first_lead_samples:], 0.25))

            context_call = {}

            class FakeExternalMotionContext:
                def apply(self, **kwargs):
                    context_call.update(kwargs)
                    return ("continued", 1)

            real_motion_context = chain.MiniMaxH3MotionContext
            chain.MiniMaxH3MotionContext = FakeExternalMotionContext
            try:
                external_conditioning = chain.MiniMaxH3ChainContext().apply(
                    external_state1, conditioning, None, av_latent(),
                    audio_vae="audio-vae")
            finally:
                chain.MiniMaxH3MotionContext = real_motion_context
            assert external_conditioning == ("continued", 1, True)
            assert context_call["context_latent"] is None
            assert context_call["audio_vae"] == "audio-vae"
            assert context_call["context_audio"] is external_state1[
                "previous_audio"]

            external_saver = chain.MiniMaxH3ChainSegmentSave()
            external_saver.save(
                external_state1,
                torch.zeros((4, 32, 32, 3), dtype=torch.float32),
                av_latent())["result"][0]
            external_state2 = chain._initial_state(
                effective_external_plan, 2)
            external_segment2 = external_saver.save(
                external_state2,
                torch.zeros((4, 32, 32, 3), dtype=torch.float32),
                av_latent())["result"][0]
            external_complete = dict(external_state2)
            external_complete["segments"] = (
                external_state2["segments"] + [external_segment2])
            external_manifest = chain._manifest_from_state(external_complete)
            assert external_manifest["prelude"]["frame_count"] == 6
            loaded_external = chain.MiniMaxH3ChainManifestLoad().load(
                external_plan, extension_audio, external_context)[0]
            assert loaded_external["plan_hash"] == external_manifest["plan_hash"]

            joined_audio = chain._audio_with_prelude(
                extension_audio, 8, prelude)
            assert int(joined_audio["waveform"].shape[-1]) == round(
                14 / 24 * 8000)
            prelude_samples = round(6 / 24 * 8000)
            assert torch.allclose(
                joined_audio["waveform"][..., :prelude_samples],
                torch.full_like(
                    joined_audio["waveform"][..., :prelude_samples], 0.75))
            external_result = chain.MiniMaxH3ChainAssemble().assemble(
                external_manifest, "source", "extended_with_original", 96,
                extension_audio)
            external_path = pathlib.Path(external_result["result"][0])
            assert external_path.is_file() and external_path.stat().st_size > 0
            external_duration = float(subprocess.check_output([
                "ffprobe", "-v", "error", "-show_entries", "format=duration",
                "-of", "default=nw=1:nk=1", str(external_path),
            ], text=True, encoding="utf-8", errors="replace").strip())
            assert abs(external_duration - 14 / 24) < 0.05
            assert "existing-video prelude" in external_result["ui"]["text"][0]
            external_original_which = chain.shutil.which
            chain.shutil.which = lambda executable: (
                None if executable == "ffmpeg"
                else external_original_which(executable))
            try:
                external_fallback = chain.MiniMaxH3ChainAssemble().assemble(
                    external_manifest, "source", "extended_pyav", 96,
                    extension_audio)
            finally:
                chain.shutil.which = external_original_which
            with chain.av.open(
                    external_fallback["result"][0], mode="r") as media:
                assert len(media.streams.video) == 1
                assert len(media.streams.audio) == 1
                assert sum(1 for _frame in media.decode(video=0)) == 14
            print("existing video: native VIDEO and decoded IMAGE/AUDIO routes "
                  "normalized 30 fps input, scene 1 continued with AV context, "
                  "and original prelude assembled with both media backends")

            saver = chain.MiniMaxH3ChainSegmentSave()
            generated_state = chain._initial_state(
                chain._plan_with_source_audio(before_plan, None), 1)
            try:
                saver.save(
                    generated_state,
                    torch.zeros((5, 32, 32, 3), dtype=torch.float32),
                    av_latent())
            except ValueError as exc:
                assert "requires decoded audio" in str(exc)
            else:
                raise AssertionError("generated_audio saved without decoded audio")
            try:
                saver.save(
                    generated_state,
                    torch.zeros((5, 32, 32, 3), dtype=torch.float32),
                    av_latent(), audio_for_frames(4))
            except ValueError as exc:
                assert "expected exactly" in str(exc)
            else:
                raise AssertionError("Segment Save accepted mistimed audio")
            state1 = chain._initial_state(prepared_plan, 1)
            images1 = torch.zeros((5, 32, 32, 3), dtype=torch.float32)
            queued_prompt = {
                "1700": {
                    "class_type": "MiniMaxH3ChainPlan",
                    "inputs": {
                        "plan_json": '{"shots":["stale"]}',
                        "run_name": "smoke",
                    },
                },
            }
            queued_workflow = {
                "nodes": [{
                    "id": 1700,
                    "type": "MiniMaxH3ChainPlan",
                    "widgets_values": [
                        '{"shots":["stale"]}', "smoke", "fingerprint",
                    ],
                }],
            }
            result1 = saver.save(
                state1, images1, av_latent(), audio_for_frames(5),
                prompt=queued_prompt,
                extra_pnginfo={"workflow": queued_workflow})
            segment1 = result1["result"][0]
            assert pathlib.Path(chain._absolute_output_path(
                segment1["segment"])).is_file()

            assert segment1["prompt_prefix"] == ""
            assert segment1["scene_prompt"] == "first"
            assert segment1["prompt"] == "first"
            prompt_path = pathlib.Path(chain._absolute_output_path(
                segment1["prompt_file"]))
            assert prompt_path.read_text(encoding="utf-8") == "first"
            assert segment1["prompt_file_sha256"] == chain._file_sha256(
                str(prompt_path))
            segment_metadata = json.loads(pathlib.Path(
                chain._absolute_output_path(segment1["metadata"])
            ).read_text(encoding="utf-8"))
            assert segment_metadata["format"] == "h3_chain_segment_v3"
            assert segment_metadata["segment"]["prompt"] == "first"
            assert segment_metadata["archives"] == segment1["archives"]

            run_dir = pathlib.Path(tempdir, "h3_chains", "smoke")
            exact_text_path = run_dir / "exact-lf.txt"
            chain._atomic_text(str(exact_text_path), "line one\nline two")
            assert exact_text_path.read_bytes() == b"line one\nline two"

            legacy_prompt_path = run_dir / "legacy-windows.prompt.txt"
            legacy_prompt_path.write_bytes(b"line one\r\nline two")
            legacy_segment = dict(segment1)
            legacy_segment["prompt_file"] = chain._relative_output_path(
                str(legacy_prompt_path))
            legacy_segment["prompt_hash"] = hashlib.sha256(
                b"line one\nline two").hexdigest()
            legacy_segment.pop("prompt_file_sha256", None)
            chain._verify_segment_artifacts(legacy_segment, 1)
            legacy_prompt_path.write_bytes(b"line one\r\nchanged")
            try:
                chain._verify_segment_artifacts(legacy_segment, 1)
            except ValueError as exc:
                assert "prompt sidecar" in str(exc)
            else:
                raise AssertionError("changed legacy prompt sidecar was accepted")

            archived_plan = json.loads(
                (run_dir / "plan.json").read_text(encoding="utf-8"))
            archived_api = json.loads(
                (run_dir / "api_prompt.json").read_text(encoding="utf-8"))
            archived_workflow = json.loads(
                (run_dir / "workflow.json").read_text(encoding="utf-8"))
            assert archived_plan["format"] == "h3_chain_plan_archive_v1"
            assert archived_plan["shots"][0]["prompt"] == "first"
            assert json.loads(
                archived_api["1700"]["inputs"]["plan_json"]
            )["shots"][0]["prompt"] == "first"
            assert json.loads(
                archived_workflow["nodes"][0]["widgets_values"][0]
            )["shots"][0]["prompt"] == "first"
            embedded_tags = json.loads(subprocess.check_output([
                "ffprobe", "-v", "error", "-show_entries", "format_tags",
                "-of", "json",
                str(chain._absolute_output_path(segment1["segment"])),
            ], text=True, encoding="utf-8", errors="replace"))["format"]["tags"]
            assert embedded_tags["comment"] == "first"
            assert embedded_tags["h3_prompt"] == "first"
            assert json.loads(embedded_tags["workflow"])["nodes"][0][
                "type"] == "MiniMaxH3ChainPlan"
            assert json.loads(embedded_tags["prompt"])["1700"][
                "class_type"] == "MiniMaxH3ChainPlan"
            assert json.loads(embedded_tags["h3_plan"])["shots"][0][
                "prompt"] == "first"
            print("recovery metadata: MP4, prompt sidecar, plan, API prompt, "
                  "and workflow archive exact inputs")

            segment1_path = pathlib.Path(
                chain._absolute_output_path(segment1["segment"]))
            checkpoint1_path = pathlib.Path(
                chain._absolute_output_path(segment1["checkpoint"]))
            with safe_open(checkpoint1_path, framework="pt", device="cpu") as saved:
                checkpoint_metadata = saved.metadata()
            assert checkpoint_metadata["format"] == "h3_chain_checkpoint_v3"
            assert checkpoint_metadata["prompt"] == "first"
            assert checkpoint_metadata["seed"] == "1"
            before_interruption = (
                segment1_path.read_bytes(), checkpoint1_path.read_bytes())
            real_st_save = chain._st_save

            def interrupted_save(*args, **kwargs):
                raise RuntimeError("simulated interrupted checkpoint write")

            chain._st_save = interrupted_save
            try:
                saver.save(
                    state1, torch.ones_like(images1), av_latent(),
                    audio_for_frames(5))
            except RuntimeError as exc:
                assert "simulated interrupted" in str(exc)
            else:
                raise AssertionError("simulated checkpoint interruption did not fire")
            finally:
                chain._st_save = real_st_save
            assert segment1_path.read_bytes() == before_interruption[0]
            assert checkpoint1_path.read_bytes() == before_interruption[1]
            assert chain._initial_state(prepared_plan, 2)["index"] == 2
            replacement = saver.save(
                state1, images1, av_latent(), audio_for_frames(5))["result"][0]
            assert replacement["segment"] != segment1["segment"]
            assert not segment1_path.exists()
            assert not checkpoint1_path.exists()
            segment1 = replacement
            print("atomic save: interruption preserved old pair; retry switched + cleaned")

            review_item, has_audio, warning = chain._review_video(
                prepared_plan, segment1, audio_for_frames(5))
            review_path = pathlib.Path(
                tempdir, review_item["subfolder"], review_item["filename"])
            assert has_audio and not warning and review_path.is_file()
            streams = subprocess.check_output([
                "ffprobe", "-v", "error", "-show_entries", "stream=codec_type",
                "-of", "csv=p=0", str(review_path),
            ], text=True, encoding="utf-8", errors="replace").splitlines()
            assert "video" in streams and "audio" in streams

            fallback_review_audio = audio_for_frames(5)
            fallback_review_audio["waveform"][..., 0] = 0.25
            original_which = chain.shutil.which
            chain.shutil.which = lambda executable: (
                None if executable == "ffmpeg" else original_which(executable))
            try:
                fallback_review, fallback_has_audio, fallback_warning = (
                    chain._review_video(
                        prepared_plan, segment1, fallback_review_audio))
            finally:
                chain.shutil.which = original_which
            fallback_review_path = pathlib.Path(
                tempdir, fallback_review["subfolder"],
                fallback_review["filename"])
            assert (fallback_has_audio and not fallback_warning and
                    fallback_review_path.is_file())
            with chain.av.open(
                    str(fallback_review_path), mode="r") as fallback_media:
                assert len(fallback_media.streams.video) == 1
                assert len(fallback_media.streams.audio) == 1
            print("review: persisted segment muxed with frame-exact audio via "
                  "ffmpeg and the PyAV fallback")

            async def approve_live_review():
                sent = []
                unload_calls = []

                class ReviewServerInstance:
                    client_id = "smoke-client"

                    def send_sync(self, event, payload, client_id):
                        sent.append((event, payload, client_id))

                class ReviewServer:
                    instance = ReviewServerInstance()

                original_server = chain.PromptServer
                import comfy.model_management as model_management
                original_unload = model_management.unload_all_models
                model_management.unload_all_models = lambda: unload_calls.append(True)
                chain.PromptServer = ReviewServer
                try:
                    task = asyncio.create_task(
                        chain.MiniMaxH3ChainReview().review(
                            state1, segment1, True, False, 0.0,
                            True, False, "none",
                            audio_for_frames(5), unique_id="review-node"))
                    for _ in range(100):
                        if chain._PENDING_REVIEWS:
                            break
                        await asyncio.sleep(0.01)
                    assert chain._PENDING_REVIEWS and sent
                    review_events = [
                        payload for event, payload, _client in sent
                        if event == "minimax_h3_context_loop_review"]
                    assert review_events[0]["preview_pending"]
                    assert review_events[0]["preview_revision"] == 0
                    assert not review_events[-1]["preview_pending"]
                    assert review_events[-1]["preview_revision"] == 1
                    assert review_events[-1]["has_audio"]
                    token = review_events[-1]["token"]

                    class ApproveRequest:
                        async def json(self):
                            return {"token": token, "action": "approve"}

                    response = await chain._submit_review_decision(
                        ApproveRequest())
                    assert response.status == 200
                    result = await asyncio.wait_for(task, timeout=5.0)
                    assert result["result"][0]["segment"] == segment1["segment"]
                    assert unload_calls == [True]
                    assert not chain._PENDING_REVIEWS

                    timeout_task = asyncio.create_task(
                        chain.MiniMaxH3ChainReview().review(
                            state1, segment1, True, True, 0.001,
                            False, False, "none",
                            audio_for_frames(5), unique_id="review-node"))
                    timeout_result = await asyncio.wait_for(
                        timeout_task, timeout=2.0)
                    assert "timed out" in timeout_result["result"][1]
                    assert any(event == "minimax_h3_context_loop_review_resolved"
                               for event, _payload, _client in sent)
                    assert not chain._PENDING_REVIEWS

                    # Review muxing is UI-only. Publish the pending token first
                    # and fall back to a silent, actionable review if audio
                    # preview preparation fails.
                    real_review_video = chain._review_video

                    def fail_audio_preview(plan_arg, segment_arg, audio_arg):
                        if audio_arg is None:
                            return real_review_video(
                                plan_arg, segment_arg, audio_arg)
                        raise RuntimeError("simulated review audio failure")

                    chain._review_video = fail_audio_preview
                    event_offset = len(sent)
                    try:
                        fallback_task = asyncio.create_task(
                            chain.MiniMaxH3ChainReview().review(
                                state1, segment1, True, False, 0.0,
                                False, False, "none",
                                audio_for_frames(5), unique_id="review-node"))
                        for _ in range(100):
                            if chain._PENDING_REVIEWS:
                                break
                            await asyncio.sleep(0.01)
                        assert chain._PENDING_REVIEWS
                        fallback_events = [
                            payload for event, payload, _client in sent[event_offset:]
                            if event == "minimax_h3_context_loop_review"]
                        assert fallback_events[0]["preview_pending"]
                        assert not fallback_events[-1]["preview_pending"]
                        assert not fallback_events[-1]["has_audio"]
                        assert "review is silent" in fallback_events[-1]["warning"]
                        fallback_token = fallback_events[-1]["token"]

                        class FallbackApproveRequest:
                            async def json(self):
                                return {"token": fallback_token,
                                        "action": "approve"}

                        fallback_response = await chain._submit_review_decision(
                            FallbackApproveRequest())
                        assert fallback_response.status == 200
                        fallback_result = await asyncio.wait_for(
                            fallback_task, timeout=5.0)
                        assert "approved clip" in fallback_result["result"][1]
                    finally:
                        chain._review_video = real_review_video
                    assert not chain._PENDING_REVIEWS
                finally:
                    chain.PromptServer = original_server
                    model_management.unload_all_models = original_unload

            asyncio.run(approve_live_review())

            def approve_cross_thread_review():
                sent = []
                result = []

                class ReviewServerInstance:
                    client_id = "cross-thread-smoke-client"

                    def send_sync(self, event, payload, client_id):
                        sent.append((event, payload, client_id))

                class ReviewServer:
                    instance = ReviewServerInstance()

                original_server = chain.PromptServer
                chain.PromptServer = ReviewServer
                try:
                    def execute_review():
                        result.append(asyncio.run(
                            chain.MiniMaxH3ChainReview().review(
                                state1, segment1, True, False, 0.0,
                                False, False, "none",
                                audio_for_frames(5), unique_id="review-node")))

                    worker = threading.Thread(target=execute_review, daemon=True)
                    worker.start()
                    for _ in range(200):
                        if chain._PENDING_REVIEWS:
                            break
                        time.sleep(0.01)
                    assert chain._PENDING_REVIEWS and sent
                    token = sent[-1][1]["token"]

                    class ApproveRequest:
                        async def json(self):
                            return {"token": token, "action": "approve"}

                    response = asyncio.run(
                        chain._submit_review_decision(ApproveRequest()))
                    assert response.status == 200
                    worker.join(timeout=5.0)
                    assert not worker.is_alive()
                    assert result and "approved clip" in result[0]["result"][1]
                    assert not chain._PENDING_REVIEWS
                finally:
                    chain.PromptServer = original_server

            approve_cross_thread_review()
            assert chain._review_timeout_seconds(0) == 0
            assert chain._review_timeout_seconds(1.5) == 90
            print("review: same-loop, cross-thread, timeout, and silent-preview "
                  "fallback approvals resume")

            revised = chain._plan_with_review_revision(
                prepared_plan, 2, "Revised second scene.", 999)
            assert revised["base_plan_hash"] == prepared_plan["base_plan_hash"]
            assert revised["shots"][1]["prompt"] == "Revised second scene."
            assert revised["shots"][1]["seed"] == 999
            assert (chain._history_hash(revised, 1) ==
                    chain._history_hash(prepared_plan, 1))
            assert (chain._history_hash(revised, 2) !=
                    chain._history_hash(prepared_plan, 2))
            print("review: prompt/seed retry preserves accepted predecessor history")

            fake_prompt = {
                "1": {"class_type": "MiniMaxH3ChainLoopStart", "inputs": {
                    "plan": plan, "start_clip": 1, "source_audio": source,
                }},
                "2": {"class_type": "MiniMaxH3ChainCurrent", "inputs": {
                    "state": ["1", 1],
                }},
                "3": {"class_type": "MiniMaxH3ChainSegmentSave", "inputs": {
                    "state": ["2", 0],
                }},
                "4": {"class_type": "MiniMaxH3ChainLoopEnd", "inputs": {
                    "flow": ["1", 0], "state": ["2", 0],
                    "images": ["3", 0], "sampled_latent": ["3", 0],
                    "segment": ["3", 0],
                }},
            }
            expanded = chain.MiniMaxH3ChainLoopEnd().end(
                ["1", 0], state1, images1, av_latent(), segment1,
                dynprompt=FakeDynamicPrompt(fake_prompt), unique_id="4")
            assert isinstance(expanded, dict) and expanded.get("expand")
            cloned_starts = [node for node in expanded["expand"].values()
                             if node["class_type"] == "MiniMaxH3ChainLoopStart"]
            assert len(cloned_starts) == 1
            assert cloned_starts[0]["inputs"]["initial_state"]["index"] == 2
            assert all(isinstance(link, list) for link in expanded["result"])
            print("recursion: GraphBuilder cloned the typed H3 body for clip 2")

            retry_segment = dict(segment1)
            retry_segment["_h3_review_decision"] = {
                "action": "retry",
                "scene_prompt": "Try the opening again.",
                "seed": 1234,
            }
            retried = chain.MiniMaxH3ChainLoopEnd().end(
                ["1", 0], state1, images1, av_latent(), retry_segment,
                dynprompt=FakeDynamicPrompt(fake_prompt), unique_id="4")
            retried_starts = [
                node for node in retried["expand"].values()
                if node["class_type"] == "MiniMaxH3ChainLoopStart"
            ]
            retry_state = retried_starts[0]["inputs"]["initial_state"]
            assert retry_state["index"] == 1
            assert retry_state["segments"] == []
            assert retry_state["plan"]["shots"][0]["seed"] == 1234
            assert retry_state["plan"]["shots"][0]["prompt"] == "Try the opening again."
            print("review: rejected clip recurses at the same index")

            state2 = chain._initial_state(prepared_plan, 2)
            assert state2["resumed_from"] == 1
            assert len(state2["segments"]) == 1
            assert tuple(state2["previous_frames"].shape) == (1, 32, 32, 3)
            assert len(state2["previous_latent"]["samples"]) == 2
            print("resume: clip 2 restored clip 1 frame tail + AV latent")

            images2 = torch.zeros((4, 32, 32, 3), dtype=torch.float32)
            result2 = saver.save(
                state2, images2, av_latent(), audio_for_frames(4))
            segment2 = result2["result"][0]

            async def stop_with_partial_review():
                sent = []

                class ReviewServerInstance:
                    client_id = "partial-stop-smoke-client"

                    def send_sync(self, event, payload, client_id):
                        sent.append((event, payload, client_id))

                class ReviewServer:
                    instance = ReviewServerInstance()

                original_server = chain.PromptServer
                chain.PromptServer = ReviewServer
                try:
                    task = asyncio.create_task(
                        chain.MiniMaxH3ChainReview().review(
                            state2, segment2, True, False, 0.0,
                            False, True, "checkpointed", audio_for_frames(4),
                            source, unique_id="review-node"))
                    for _ in range(100):
                        if chain._PENDING_REVIEWS:
                            break
                        await asyncio.sleep(0.01)
                    assert chain._PENDING_REVIEWS and sent
                    token = sent[-1][1]["token"]

                    class StopRequest:
                        async def json(self):
                            return {"token": token, "action": "stop"}

                    response = await chain._submit_review_decision(StopRequest())
                    assert response.status == 200
                    result = await asyncio.wait_for(task, timeout=10.0)
                    assert "partial video" in result["result"][1]
                    resolved = [payload for event, payload, _client in sent
                                if event == "minimax_h3_context_loop_review_resolved"]
                    assert resolved and resolved[-1]["partial_video"]
                    item = resolved[-1]["partial_video"]
                    partial_path = pathlib.Path(
                        tempdir, item["subfolder"], item["filename"])
                    assert partial_path.is_file() and partial_path.stat().st_size > 0
                    streams = subprocess.check_output([
                        "ffprobe", "-v", "error", "-show_entries",
                        "stream=codec_type", "-of", "csv=p=0",
                        str(partial_path),
                    ], text=True, encoding="utf-8", errors="replace").splitlines()
                    assert "video" in streams and "audio" in streams
                finally:
                    chain.PromptServer = original_server

            asyncio.run(stop_with_partial_review())
            partial_manifest = pathlib.Path(
                tempdir, "h3_chains", "smoke", "partial",
                "through_clip_0002.manifest.json")
            assert partial_manifest.is_file()
            partial_data = json.loads(partial_manifest.read_text())
            assert partial_data["format"] == "h3_chain_partial_manifest_v3"
            assert partial_data["clip_count"] == 2
            assert partial_data["segments"][0]["prompt"] == "first"
            assert partial_data["segments"][1]["prompt"] == "second"
            assert partial_data["archives"]["workflow"].endswith(
                "/workflow.json")
            print("review stop: joined partial AV video and checkpoint manifest")

            class CheckpointRequest:
                query = {"run_name": "smoke"}

            checkpoint_response = asyncio.run(
                chain._list_saved_checkpoints(CheckpointRequest()))
            checkpoint_body = json.loads(checkpoint_response.text)
            assert [item["scene"] for item in checkpoint_body["checkpoints"]] == [1, 2]
            assert all(item["ready"] for item in checkpoint_body["checkpoints"])
            assert all(item["video"] for item in checkpoint_body["checkpoints"])
            assert checkpoint_body["checkpoints"][1]["partial_video"]
            print("checkpoint browser: discovered both saved resume slots")

            complete = dict(state2)
            complete["segments"] = state2["segments"] + [segment2]
            manifest = chain._manifest_from_state(complete)

            loaded_manifest = chain.MiniMaxH3ChainManifestLoad().load(
                plan, source)[0]
            assert loaded_manifest["plan_hash"] == manifest["plan_hash"]
            assert len(loaded_manifest["segments"]) == 2
            assert pathlib.Path(tempdir, "h3_chains", "smoke",
                                "manifest.json").is_file()
            manifest = loaded_manifest
            print("manifest load: completed chain restored without rerender")

            class FakeVideoVAE:
                def __init__(self):
                    self.calls = 0

                def decode(self, _video):
                    self.calls += 1
                    images = torch.zeros(
                        (1, 5, 4, 4, 3), dtype=torch.float32)
                    for frame in range(5):
                        images[:, frame, ..., 0] = (
                            self.calls * 10 + frame) / 255.0
                    return images

            fake_vae = FakeVideoVAE()
            png_result = chain.MiniMaxH3ChainExportPNG().export(
                manifest, fake_vae, "archive", 1, 1, True)
            png_dir = pathlib.Path(png_result["result"][0])
            png_files = sorted(png_dir.glob("frame_*.png"))
            assert png_result["result"][1] == 9
            assert len(png_files) == 9
            assert [path.name for path in (png_files[0], png_files[-1])] == [
                "frame_00000001.png", "frame_00000009.png"]
            png_export = json.loads(
                (png_dir / "export.json").read_text(encoding="utf-8"))
            assert png_export["complete"]
            assert png_export["frame_count"] == 9
            assert png_export["clips"][0]["first_frame_number"] == 1
            assert png_export["clips"][1]["first_frame_number"] == 6
            assert png_export["clips"][1]["trim_frames"] == 1
            with PILImage.open(png_files[0]) as first_png:
                assert json.loads(first_png.text["workflow"])["nodes"][0][
                    "type"] == "MiniMaxH3ChainPlan"
                assert json.loads(first_png.text["h3_manifest"])[
                    "clip_count"] == 2
                assert json.loads(first_png.text["h3_scene"])[
                    "prompt"] == "first"
            with PILImage.open(png_files[5]) as second_scene_png:
                assert second_scene_png.text["h3_clip_index"] == "2"
                assert json.loads(second_scene_png.text["h3_scene"])[
                    "prompt"] == "second"
            # The second clip's raw frame 1 is overlap and must be absent: its
            # first delivered PNG therefore carries fake decoded value 21.
            with PILImage.open(png_files[5]) as trimmed_png:
                assert trimmed_png.getpixel((0, 0))[0] == 21
            assert fake_vae.calls == 2
            print("PNG export: checkpoints re-decoded one scene at a time; "
                  "overlap trimmed and workflow metadata preserved")

            assembler = chain.MiniMaxH3ChainAssemble()
            source_result = assembler.assemble(
                manifest, "source", "source_final", 96, source)
            source_path = pathlib.Path(source_result["result"][0])
            assert source_path.is_file() and source_path.stat().st_size > 0
            source_tags = json.loads(subprocess.check_output([
                "ffprobe", "-v", "error", "-show_entries", "format_tags",
                "-of", "json", str(source_path),
            ], text=True, encoding="utf-8", errors="replace"))["format"]["tags"]
            assert json.loads(source_tags["workflow"])["nodes"][0][
                "type"] == "MiniMaxH3ChainPlan"
            assert json.loads(source_tags["h3_manifest"])["clip_count"] == 2
            duration = float(subprocess.check_output([
                "ffprobe", "-v", "error", "-show_entries", "format=duration",
                "-of", "default=nw=1:nk=1", str(source_path),
            ], text=True, encoding="utf-8", errors="replace").strip())
            assert abs(duration - 9 / 24) < 0.05
            short_silent_manifest = dict(manifest)
            short_silent_manifest["compatibility"] = dict(
                short_started[1]["plan"]["compatibility"])
            short_silent_result = assembler.assemble(
                short_silent_manifest, "source", "short_silent_final", 96,
                short_source)
            short_silent_path = pathlib.Path(short_silent_result["result"][0])
            assert short_silent_path.is_file() and short_silent_path.stat().st_size > 0
            try:
                assembler.assemble(
                    manifest, "source", "wrong_source", 96, changed_source)
            except ValueError as exc:
                assert "different source waveform" in str(exc)
            else:
                raise AssertionError("Assemble accepted a different source song")

            generated_result = assembler.assemble(
                manifest, "generated", "generated_final", 96)
            generated_path = pathlib.Path(generated_result["result"][0])
            assert generated_path.is_file() and generated_path.stat().st_size > 0

            original_which = chain.shutil.which
            chain.shutil.which = lambda executable: (
                None if executable == "ffmpeg" else original_which(executable))
            try:
                fallback_result = assembler.assemble(
                    manifest, "generated", "pyav_fallback_final", 96)
            finally:
                chain.shutil.which = original_which
            fallback_path = pathlib.Path(fallback_result["result"][0])
            assert fallback_path.is_file() and fallback_path.stat().st_size > 0
            assert "PyAV fallback" in fallback_result["ui"]["text"][0]
            with chain.av.open(str(fallback_path), mode="r") as fallback_media:
                assert len(fallback_media.streams.video) == 1
                assert len(fallback_media.streams.audio) == 1
                assert json.loads(fallback_media.metadata["h3_manifest"])[
                    "clip_count"] == 2
                fallback_duration = (
                    float(fallback_media.duration) / float(chain.av.time_base))
                assert abs(fallback_duration - 9 / 24) < 0.05
                assert sum(1 for _frame in fallback_media.decode(video=0)) == 9
            print("segments: H.264 save + source/generated audio assembly and "
                  "ffmpeg-free PyAV fallback pass")

            changed = json.loads(json.dumps({"shots": [
                {"id": "one", "prompt": "changed", "length": 5, "seed": 1},
                {"id": "two", "prompt": "second", "length": 5, "seed": 2},
            ]}))
            changed_plan = chain._normalize_plan(
                json.dumps(changed), "smoke", 32, 32, 1, "video", "head",
                "disabled", "source_track", 1, 1, 2, 1, 30)
            try:
                chain._initial_state(
                    chain._plan_with_source_audio(changed_plan, source), 2)
            except ValueError as exc:
                assert "different settings, prompts, seeds, or durations" in str(exc)
            else:
                raise AssertionError("resume accepted a changed predecessor")
            print("resume guard: changed predecessor rejected")

            changed_generation_plan = chain._normalize_plan(
                json.dumps({"shots": [
                    {"id": "one", "prompt": "first", "length": 5, "seed": 1},
                    {"id": "two", "prompt": "second", "length": 5, "seed": 2},
                ]}),
                "smoke", 32, 32, 1, "video", "head", "disabled",
                "source_track", 1, 1, 2, 1, 30, "model-and-refs-v2")
            try:
                chain._initial_state(chain._plan_with_source_audio(
                    changed_generation_plan, source), 2)
            except ValueError as exc:
                assert "different settings" in str(exc)
            else:
                raise AssertionError(
                    "resume accepted a changed generation fingerprint")
            print("resume guard: external generation fingerprint enforced")

            try:
                chain._initial_state(
                    chain._plan_with_source_audio(plan, changed_source), 2)
            except ValueError as exc:
                assert "different settings, prompts, seeds, or durations" in str(exc)
            else:
                raise AssertionError("resume accepted changed source audio")
            print("resume guard: changed source track rejected")
        finally:
            folder_paths.set_output_directory(previous_output)

    print("chain smoke test passed")


if __name__ == "__main__":
    main()
