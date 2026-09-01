#!/usr/bin/env python3
"""Semantic incoming-transition presets resolve to generation fields."""

import importlib.util
import json
import pathlib
import sys
import types

import torch


ROOT = pathlib.Path(__file__).resolve().parents[1]
PACKAGE = "h3_transition_policy_unit"

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
future_anchor_calls = []
explicit_anchor_calls = []


def append_future_end_anchor_stub(
        conditioning, latent, prefix_frames, visual_cond_noise_aug=0.999):
    future_anchor_calls.append({
        "conditioning": conditioning,
        "latent": latent,
        "prefix_frames": prefix_frames,
        "visual_cond_noise_aug": visual_cond_noise_aug,
    })
    return "future-anchor-conditioning"


shared_nodes._append_future_end_anchor = append_future_end_anchor_stub


def append_explicit_future_end_anchor_stub(
        conditioning, latent, anchor_latent,
        visual_cond_noise_aug=0.999):
    explicit_anchor_calls.append({
        "conditioning": conditioning,
        "latent": latent,
        "anchor_latent": anchor_latent,
        "visual_cond_noise_aug": visual_cond_noise_aug,
    })
    return "explicit-boundary-conditioning"


shared_nodes._append_explicit_future_end_anchor = (
    append_explicit_future_end_anchor_stub)
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


PLAN_JSON = json.dumps({
    "shots": [
        {"id": "one", "prompt": "First scene.", "length": 73},
        {"id": "two", "prompt": "Second scene.", "length": 73},
    ],
})


def make_plan(policy=None, *, encode_mode="video", anchor_mode="head",
              context_length=22, continuation_mode="guide"):
    combined = None
    if policy is not None:
        combined = chain._contract_compose_chain_policy(
            chain.migrate_legacy_audio_mode("generated_audio"), policy,
            audio_context_length=int(policy["context_length"]))
    return chain._normalize_plan(
        PLAN_JSON, "transition-policy-test", 64, 64, context_length,
        encode_mode, anchor_mode, "disabled", "generated_audio", 22,
        3.0, 8, 7, 18, "model-stack", 0, continuation_mode,
        combined)


def build_transition(preset="guide", expert_override=False,
                     expert_continuation_mode="guide",
                     expert_context_length=22):
    policy = chain._contract_transition_policy(
        preset, expert_override=expert_override,
        continuation_mode=expert_continuation_mode,
        context_length=expert_context_length)
    status = chain._transition_policy_display({"transition_policy": policy})
    if policy["expert_override"]:
        status += "; expert override"
    elif policy["preset"] in ("tone_guide", "detail_guide"):
        status += "; experimental preset; published baseline 22f"
    elif policy["preset"] == "detail_av":
        status += "; experimental preset; clean-boundary latent taper v2 at 39f"
    elif policy["preset"] == "drift_av":
        status += (
            "; experimental preset; schedule-matched 8+4 mask at 39f; "
            "20-step baseline")
    elif policy["preset"] == "color_drift_av":
        status += (
            "; experimental preset; schedule-matched 8+4 mask plus "
            "scene-one VAE delta at 39f; 20-step baseline")
    else:
        status += "; tested preset"
    return (policy, policy["continuation_mode"],
            int(policy["context_length"]), status)


preset_choices = (
    "cut", "guide", "tone_guide", "latent_guide", "detail_guide",
    "detail_av", "drift_av", "color_drift_av", "hard_av", "soft_av")
assert "soft_av" in preset_choices
assert "detail_av" in preset_choices
assert "drift_av" in preset_choices
assert "color_drift_av" in preset_choices
assert "audio_feather_av" not in preset_choices
expected = {
    "cut": ("guide", 0),
    "guide": ("guide", 22),
    "tone_guide": ("tone_carry_guide", 22),
    "latent_guide": ("latent_guide", 22),
    "detail_guide": ("tapered_guide", 22),
    "detail_av": ("tapered_av", 39),
    "drift_av": ("drift_control_av", 39),
    "color_drift_av": ("color_stable_drift_av", 39),
    "hard_av": ("masked_av", 39),
    "soft_av": ("audio_feathered_av", 39),
    "audio_feather_av": ("audio_feathered_av", 39),
}
for preset, (mode, context) in expected.items():
    policy, output_mode, output_context, status = build_transition(preset)
    assert policy["preset"] == preset
    assert policy["continuation_mode"] == mode
    assert policy["context_length"] == context
    assert policy["expert_override"] is False
    assert output_mode == mode and output_context == context
    assert " -> " in status
    if preset in (
            "tone_guide", "detail_guide", "detail_av", "drift_av",
            "color_drift_av"):
        assert "experimental preset" in status
    else:
        assert "tested preset" in status

soft_status = build_transition("soft_av")[3]
assert soft_status.startswith("Soft AV -> Audio-Feathered AV + 39 frames")
hard_status = build_transition("hard_av")[3]
assert hard_status.startswith("Hard AV -> Masked AV + 39 frames")
detail_av_status = build_transition("detail_av")[3]
assert detail_av_status.startswith("Detail AV -> Tapered AV + 39 frames")
assert "clean-boundary latent taper v2" in detail_av_status
drift_av_status = build_transition("drift_av")[3]
assert drift_av_status.startswith(
    "Drift-Control AV -> Drift-Control AV + 39 frames")
assert "schedule-matched 8+4 mask" in drift_av_status
color_drift_status = build_transition("color_drift_av")[3]
assert color_drift_status.startswith(
    "Color-Stable Drift AV -> Color-Stable Drift AV + 39 frames")
assert "scene-one VAE delta" in color_drift_status
audio_feather_status = build_transition("audio_feather_av")[3]
assert audio_feather_status.startswith(
    "Audio Feather AV (legacy alias) -> Audio-Feathered AV + 39 frames")

legacy = make_plan(None, context_length=39, continuation_mode="masked_av")
assert "transition_policy" not in legacy["compatibility"]
assert legacy["compatibility"]["context_length"] == 39
assert legacy["compatibility"]["continuation_mode"] == "masked_av"
assert chain._transition_policy_summary(legacy) == "hard_av/masked_av/39f"

cut_policy = build_transition("cut")[0]
cut = make_plan(cut_policy)
assert cut["compatibility"]["context_length"] == 0
assert cut["compatibility"].get("continuation_mode", "guide") == "guide"
assert cut["compatibility"]["transition_policy"] == cut_policy
assert chain._plan_context_storage_length(cut) == 0
assert cut["shots"][1]["generation_start_frame"] == 73
assert cut["shots"][1]["delivered_frames"] == 73
assert cut["total_delivered_frames"] == 146
assert "context=0/guide" in cut["summary"]
assert "transition=cut/guide/0f" in cut["summary"]

hard_policy = build_transition("hard_av")[0]
hard = make_plan(hard_policy, context_length=22, continuation_mode="guide")
assert hard["compatibility"]["context_length"] == 39
assert hard["compatibility"]["continuation_mode"] == "masked_av"
assert hard["shots"][1]["generation_start_frame"] == 34
assert hard["shots"][1]["delivered_frames"] == 34
assert hard["total_delivered_frames"] == 107

expert, expert_mode, expert_context, expert_status = build_transition(
    "guide", True, "feathered_av", 39)
assert expert_mode == "feathered_av" and expert_context == 39
assert expert["preset"] == "guide"
assert expert["expert_override"] is True
assert "expert override" in expert_status
expert_plan = make_plan(expert)
assert expert_plan["compatibility"]["context_length"] == 39
assert expert_plan["compatibility"]["continuation_mode"] == "feathered_av"

migrated_expert, migrated_mode, migrated_context, migrated_status = build_transition(
    "soft_av", True, "feathered_av_rgb", 39)
assert migrated_mode == "feathered_av" and migrated_context == 39
assert migrated_expert["expert_override"] is True
assert "Feathered AV" in migrated_status

try:
    build_transition("guide", True, "masked_av", 1)
except ValueError as exc:
    assert "at least 5" in str(exc)
else:
    raise AssertionError("one-frame hard AV expert override was accepted")

for off_grid in (5, 22, 56, 73):
    transition = build_transition(
        "soft_av", True, "audio_feathered_av", off_grid)[0]
    source_driven = chain._contract_compose_chain_policy(
        chain.migrate_legacy_audio_mode("source_track"), transition,
        audio_context_length=off_grid)
    assert source_driven["transition_policy"]["context_length"] == off_grid
    try:
        chain._contract_compose_chain_policy(
            chain.migrate_legacy_audio_mode("generated_audio"), transition,
            audio_context_length=off_grid)
    except ValueError as exc:
        assert "exact shared" in str(exc)
    else:
        raise AssertionError(
            "off-grid AV generated-audio carry %d was accepted" % off_grid)

try:
    build_transition("detail_av", True, "tapered_av", 90)
except ValueError as exc:
    assert "exactly 39" in str(exc)
else:
    raise AssertionError("Detail AV accepted a non-v2 90-frame context")

try:
    build_transition("drift_av", True, "drift_control_av", 90)
except ValueError as exc:
    assert "exactly 39" in str(exc)
else:
    raise AssertionError("Drift-Control AV accepted a non-v1 90-frame context")

try:
    build_transition(
        "color_drift_av", True, "color_stable_drift_av", 90)
except ValueError as exc:
    assert "exactly 39" in str(exc)
else:
    raise AssertionError(
        "Color-Stable Drift AV accepted a non-v1 90-frame context")

tapered_expert, tapered_mode, tapered_context, _ = build_transition(
    "detail_guide", True, "tapered_guide", 39)
assert tapered_mode == "tapered_guide" and tapered_context == 39
assert tapered_expert["expert_override"] is True

# The tuned 22-frame recipe keeps the Guide's luma/mouth structure intact,
# uses a milder chroma treatment, and reaches a completely clean final frame.
# The predecessor remains immutable and only the requested tail is returned.
assert chain._tapered_guide_alpha(0, 22) == 0.30
assert chain._tapered_guide_alpha(13, 22) == 0.30
assert abs(chain._tapered_guide_alpha(14, 22) - 0.2625) < 1e-9
assert abs(chain._tapered_guide_alpha(20, 22) - 0.0375) < 1e-9
assert chain._tapered_guide_alpha(21, 22) == 0.0
assert chain._tapered_guide_alpha(30, 39) == 0.30
assert abs(chain._tapered_guide_alpha(31, 39) - 0.2625) < 1e-9
assert chain._tapered_guide_alpha(38, 39) == 0.0
source = torch.linspace(
    0.08, 0.92, 45 * 19 * 31 * 3, dtype=torch.float32,
).reshape(45, 19, 31, 3)
source_copy = source.clone()
noisy_39_a = chain._tapered_guide_context(source, 39, 730002)
noisy_39_b = chain._tapered_guide_context(source, 39, 730002)
noisy_39_c = chain._tapered_guide_context(source, 39, 730003)
assert tuple(noisy_39_a.shape) == (39, 19, 31, 3)
assert torch.equal(source, source_copy)
assert torch.equal(noisy_39_a, noisy_39_b)
assert not torch.equal(noisy_39_a, noisy_39_c)
weights = torch.tensor(chain._TAPERED_GUIDE_LUMA)
assert torch.allclose(
    torch.sum(noisy_39_a * weights, dim=-1),
    torch.sum(source[-39:] * weights, dim=-1),
    atol=2e-6,
)
assert not torch.equal(noisy_39_a[0], source[-39])
assert torch.equal(noisy_39_a[-1], source[-1])
assert float(noisy_39_a.min()) >= 0.0
assert float(noisy_39_a.max()) <= 1.0

captured = {}

context_optional = chain.MiniMaxH3ChainContext.INPUT_TYPES()["optional"]
visual_aug_schema = context_optional["visual_cond_noise_aug"]
assert visual_aug_schema[0] == "FLOAT"
assert visual_aug_schema[1]["default"] == 0.999
assert visual_aug_schema[1]["min"] == 0.0
assert visual_aug_schema[1]["max"] == 1.0
assert visual_aug_schema[1]["step"] == 0.001
assert context_optional["future_end_anchor"][0] == "BOOLEAN"
assert context_optional["future_end_anchor"][1]["default"] is False
assert list(context_optional)[-2:] == ["future_end_anchor", "lip_sync_voice"]
assert context_optional["lip_sync_voice"][0] == "AUDIO"
assert context_optional["boundary_anchors"][0] == chain.BOUNDARY_ANCHORS_TYPE

# A precomputed scene endpoint is valid on scene 1 as well as continuation
# scenes and takes priority over the legacy copied-prefix toggle.
original_anchor_selector = chain._boundary_anchor_for_state
chain._boundary_anchor_for_state = lambda registry, state, latent: "anchor-1"
try:
    scene_one_plan = make_plan()
    scene_one_result = chain.MiniMaxH3ChainContext().apply(
        state={"index": 1, "plan": scene_one_plan, "segments": []},
        conditioning="stock-conditioning",
        vae=object(),
        latent="target-latent",
        boundary_anchors={"kind": "test-registry"},
        future_end_anchor=True,
    )
finally:
    chain._boundary_anchor_for_state = original_anchor_selector
assert scene_one_result == (
    "explicit-boundary-conditioning", 0, False, "target-latent", None)
assert explicit_anchor_calls[-1]["anchor_latent"] == "anchor-1"
assert explicit_anchor_calls[-1]["latent"] == "target-latent"


class CapturingMotionContext:
    def apply(self, **kwargs):
        captured.update(kwargs)
        return ("tapered-conditioning", int(kwargs["context_length"]))


original_motion_context = chain.MiniMaxH3MotionContext
chain.MiniMaxH3MotionContext = CapturingMotionContext
try:
    tapered_plan = make_plan(tapered_expert)
    original_latent = {"samples": [torch.zeros(1), torch.zeros(1)]}
    result = chain.MiniMaxH3ChainContext().apply(
        state={
            "index": 2,
            "plan": tapered_plan,
            "previous_frames": source,
            "previous_latent": original_latent,
            "segments": [],
        },
        conditioning="stock-conditioning",
        vae=object(),
        latent="target-latent",
        visual_cond_noise_aug=0.995,
        future_end_anchor=True,
    )
finally:
    chain.MiniMaxH3MotionContext = original_motion_context

assert result == ("tapered-conditioning", 39, True, "target-latent", None)
assert captured["context_length"] == 39
assert captured["visual_cond_noise_aug"] == 0.995
assert captured["future_end_anchor"] is True
assert tuple(captured["context_frames"].shape) == (39, 19, 31, 3)
assert not torch.equal(captured["context_frames"], source[-39:])
assert captured["context_latent"] is original_latent
assert captured["video_context_latent"] is None

tone_policy = build_transition("tone_guide")[0]
tone_curve = {
    "version": "h3_guide_tone_carry_v1",
    "points": [[0.0, 0.0], [0.25, 0.27], [0.75, 0.77], [1.0, 1.0]],
}
captured.clear()
chain.MiniMaxH3MotionContext = CapturingMotionContext
try:
    tone_plan = make_plan(tone_policy)
    tone_result = chain.MiniMaxH3ChainContext().apply(
        state={
            "index": 2,
            "plan": tone_plan,
            "previous_frames": source,
            "previous_latent": original_latent,
            "segments": [{"guide_tone_carry": tone_curve}],
        },
        conditioning="stock-conditioning",
        vae=object(),
        latent="target-latent",
    )
finally:
    chain.MiniMaxH3MotionContext = original_motion_context

assert tone_result == (
    "tapered-conditioning", 22, True, "target-latent", None)
expected_tone = chain._apply_guide_tone_carry(source, tone_curve)
assert torch.allclose(captured["context_frames"], expected_tone)
assert float(captured["context_frames"].mean()) > float(source.mean())
assert captured["video_context_latent"] is None
assert captured["context_latent"] is original_latent

# The detector stores a direct curve from the raw generated scene to the RGB
# Guide it actually received. The clean first frame followed by a four-level
# exposure step mirrors the real H3 boundary this feature was designed for.
guide_gradient = torch.linspace(
    0.03, 0.73, 32, dtype=torch.float32).reshape(1, 1, 32, 1)
guide_gradient = guide_gradient.expand(1, 32, 32, 3).contiguous()
guide_context = guide_gradient.repeat(8, 1, 1, 1)
guide_generated = torch.cat((
    guide_gradient,
    torch.clamp(guide_gradient - (4.0 / 255.0), 0.0, 1.0).repeat(3, 1, 1, 1),
), dim=0)
detected_tone = chain._detect_guide_tone_carry(
    guide_context, guide_generated)
assert detected_tone is not None
assert detected_tone["version"] == "h3_guide_tone_carry_v1"
assert detected_tone["start_frame"] == 1
corrected_guide = chain._apply_guide_tone_carry(
    guide_generated, detected_tone)
assert float(corrected_guide[-1].mean()) > float(guide_generated[-1].mean())

latent_policy = build_transition("latent_guide")[0]
captured.clear()
chain.MiniMaxH3MotionContext = CapturingMotionContext
try:
    latent_plan = make_plan(latent_policy)
    latent_result = chain.MiniMaxH3ChainContext().apply(
        state={
            "index": 2,
            "plan": latent_plan,
            "previous_frames": source,
            "previous_latent": original_latent,
            "segments": [],
        },
        conditioning="stock-conditioning",
        vae=object(),
        latent="target-latent",
    )
finally:
    chain.MiniMaxH3MotionContext = original_motion_context

assert latent_result == (
    "tapered-conditioning", 22, True, "target-latent", None)
assert captured["video_context_latent"] is original_latent
assert captured["context_latent"] is original_latent

# Drift-Control AV validates its MODEL path before scene 1 spends sampler time,
# then patches only the active continuation scene after the hard AV prefix is
# prepared. Other modes retain the same appended MODEL passthrough output.
drift_policy = build_transition("drift_av")[0]
drift_plan = make_plan(drift_policy)
drift_plan["shots"][1]["steps"] = 20
masked_stub = types.ModuleType(PACKAGE + ".masked_context")
masked_stub._require_h3_mask_support = lambda: True
masked_calls = []


def apply_masked_stub(**kwargs):
    masked_calls.append(kwargs)
    return (
        "drift-conditioning",
        {"samples": [
            torch.zeros((1, 16, 12, 2, 2)),
            torch.zeros((1, 32, 2, 65)),
        ]},
        39,
    )


masked_stub.apply_masked_prefix = apply_masked_stub
drift_stub = types.ModuleType(PACKAGE + ".drift_control")
drift_calls = []


def mark_drift_latent(latent, prefix_steps):
    marked = dict(latent)
    marked["drift_prefix_steps"] = int(prefix_steps)
    return marked


def drift_prefix_steps(latent):
    return int(latent["drift_prefix_steps"])


def install_drift_model(
        model, _latent, prefix_steps, schedule_override=None):
    drift_calls.append((model, prefix_steps, schedule_override))
    return ("patched-model", model, prefix_steps)


drift_stub.mark_drift_control_latent = mark_drift_latent
drift_stub.drift_control_latent_prefix_steps = drift_prefix_steps
drift_stub.install_drift_control_av_model = install_drift_model
sys.modules[masked_stub.__name__] = masked_stub
sys.modules[drift_stub.__name__] = drift_stub
try:
    try:
        chain.MiniMaxH3ChainContext().apply(
            state={"index": 1, "plan": drift_plan},
            conditioning="stock-conditioning",
            vae=object(),
            latent="target-latent",
        )
    except ValueError as exc:
        assert "connect it to Chain Context" in str(exc)
    else:
        raise AssertionError(
            "Drift-Control AV accepted a disconnected MODEL path")

    first_result = chain.MiniMaxH3ChainContext().apply(
        state={"index": 1, "plan": drift_plan},
        conditioning="stock-conditioning",
        vae=object(),
        latent="target-latent",
        model="h3-model",
    )
    assert first_result == (
        "stock-conditioning", 0, False, "target-latent", "h3-model")
    full_sigmas = torch.tensor([1.0, 0.8, 0.5, 0.2, 0.0])
    split_first_result = chain.MiniMaxH3ChainContext().apply(
        state={"index": 1, "plan": drift_plan},
        conditioning="stock-conditioning",
        vae=object(),
        latent="target-latent",
        drift_sigmas=full_sigmas,
    )
    assert split_first_result == (
        "stock-conditioning", 0, False, "target-latent", None)
    second_state = {
            "index": 2,
            "plan": drift_plan,
            "previous_frames": source,
            "previous_latent": original_latent,
            "segments": [],
        }
    second_result = chain.MiniMaxH3ChainContext().apply(
        state=second_state,
        conditioning="stock-conditioning",
        vae=object(),
        latent="target-latent",
        model="h3-model",
        drift_sigmas=full_sigmas,
    )
    assert second_result[:3] == ("drift-conditioning", 39, True)
    assert tuple(second_result[3]["samples"][0].shape) == (
        1, 16, 12, 2, 2)
    assert second_result[4] == ("patched-model", "h3-model", 12)
    assert drift_calls[-1] == ("h3-model", 12, full_sigmas)

    anchored_second_result = chain.MiniMaxH3ChainContext().apply(
        state=second_state,
        conditioning="stock-conditioning",
        vae=object(),
        latent="target-latent",
        model="h3-model",
        drift_sigmas=full_sigmas,
        future_end_anchor=True,
    )
    assert anchored_second_result[:3] == (
        "future-anchor-conditioning", 39, True)
    assert future_anchor_calls[-1]["conditioning"] == "drift-conditioning"
    # Drift-Control adds private schedule metadata after the anchor is read,
    # but both routes retain the exact same prepared nested samples.
    assert (future_anchor_calls[-1]["latent"]["samples"]
            is anchored_second_result[3]["samples"])
    assert future_anchor_calls[-1]["prefix_frames"] == 39
    assert future_anchor_calls[-1]["visual_cond_noise_aug"] == 0.999

    split_second_result = chain.MiniMaxH3ChainContext().apply(
        state=second_state,
        conditioning="stock-conditioning",
        vae=object(),
        latent="target-latent",
        drift_sigmas=full_sigmas,
    )
    assert split_second_result[:3] == (
        "drift-conditioning", 39, True)
    assert split_second_result[4] is None

    # A switched second model is patched inline from the same Chain Context
    # latent and full unsplit schedule. The first scene remains a passthrough.
    inline = chain.MiniMaxH3DriftControlModelPatch()
    assert inline.patch(
        "second-h3-model",
        {"index": 1, "plan": drift_plan},
        "stock-latent",
        full_sigmas,
    ) == ("second-h3-model",)
    inline_result = inline.patch(
        "second-h3-model",
        second_state,
        split_second_result[3],
        full_sigmas,
    )
    assert inline_result == (
        ("patched-model", "second-h3-model", 12),)
    assert drift_calls[-1] == ("second-h3-model", 12, full_sigmas)

    color_policy = build_transition("color_drift_av")[0]
    color_plan = make_plan(color_policy)
    color_plan["shots"][1]["steps"] = 20
    color_plan["shots"].append({
        **color_plan["shots"][1], "id": "three", "steps": 20,
    })
    anchor_stats = {
        "version": "h3_latent_color_stats_v1",
        "luma_percentiles": [100.0, 100.0, 100.0],
        "saturation_percentiles": [80.0, 80.0, 80.0],
        "sampled_frames": 12,
    }
    source_stats = {
        **anchor_stats,
        "luma_percentiles": [110.0, 110.0, 110.0],
    }
    color_state = {
        "index": 3,
        "plan": color_plan,
        "previous_frames": source,
        "previous_latent": original_latent,
        "segments": [
            {"index": 1, "latent_color_stats": anchor_stats},
            {"index": 2, "latent_color_stats": source_stats},
        ],
    }
    color_result = chain.MiniMaxH3ChainContext().apply(
        state=color_state,
        conditioning="stock-conditioning",
        vae=object(),
        latent="target-latent",
        model="h3-model",
        drift_sigmas=full_sigmas,
    )
    assert color_result[:3] == ("drift-conditioning", 39, True)
    assert color_result[4] == ("patched-model", "h3-model", 12)
    assert masked_calls[-1]["latent_color_carry"] == {
        "anchor_stats": anchor_stats,
        "current_stats": source_stats,
        "anchor_scene": 1,
        "source_scene": 2,
    }
    assert inline.patch(
        "second-h3-model", color_state, color_result[3], full_sigmas,
    ) == (("patched-model", "second-h3-model", 12),)
finally:
    sys.modules.pop(masked_stub.__name__, None)
    sys.modules.pop(drift_stub.__name__, None)

for invalid_context, invalid_encode, expected_message in (
        (1, "video", "at least 5"),
        (22, "frames", "encode_mode=video")):
    try:
        make_plan(
            None, context_length=invalid_context,
            encode_mode=invalid_encode, continuation_mode="latent_guide")
    except ValueError as exc:
        assert expected_message in str(exc)
    else:
        raise AssertionError(
            "Latent Guide accepted invalid %s-frame/%s configuration" %
            (invalid_context, invalid_encode))

try:
    make_plan(hard_policy, anchor_mode="before")
except ValueError as exc:
    assert "anchor_mode=head" in str(exc)
else:
    raise AssertionError("hard AV preset accepted before anchoring")

plan_inputs = chain.MiniMaxH3ChainPlan.INPUT_TYPES()
assert "transition_policy" not in plan_inputs["optional"]
assert "MiniMaxH3TransitionPolicy" not in chain.CHAIN_NODE_CLASS_MAPPINGS

legacy_adapter = chain.MiniMaxH3Legacy04PolicyAdapter()
legacy_combined, legacy_status = legacy_adapter.build(
    "source_plus_timeline", "feathered_av", 39, 33)
legacy_audio = legacy_combined["audio_policy"]
legacy_transition = legacy_combined["transition_policy"]
assert legacy_audio == chain.migrate_legacy_audio_mode("source_plus_timeline")
assert legacy_transition["continuation_mode"] == "feathered_av"
assert legacy_transition["context_length"] == 39
assert legacy_transition["expert_override"] is True
assert legacy_combined["audio_policy"] == legacy_audio
assert legacy_combined["transition_policy"] == legacy_transition
assert legacy_combined["audio_context_length"] == 33
assert "legacy 0.4 migration" in legacy_status
matched = legacy_adapter.build(
    "generated_audio", "masked_av", 39)[0]
matched_audio = matched["audio_policy"]
matched_transition = matched["transition_policy"]
assert matched_audio == chain.migrate_legacy_audio_mode("generated_audio")
assert matched_transition["preset"] == "hard_av"
assert matched_transition["expert_override"] is False
matched_audio_feather = legacy_adapter.build(
    "generated_audio", "audio_feathered_av", 39)[0]["transition_policy"]
assert matched_audio_feather["preset"] == "soft_av"
assert matched_audio_feather["expert_override"] is False
assert chain.CHAIN_NODE_CLASS_MAPPINGS[
    "MiniMaxH3Legacy04PolicyAdapter"] is (
        chain.MiniMaxH3Legacy04PolicyAdapter)
assert len(legacy_adapter.OUTPUT_TOOLTIPS) == len(legacy_adapter.RETURN_TYPES)
assert all(legacy_adapter.OUTPUT_TOOLTIPS)

advanced_policy = chain.MiniMaxH3AdvancedPolicy()
advanced_base = chain.MiniMaxH3ChainPolicy().build(
    "guide", "source", "on", "on")[0]
advanced_drift, advanced_status = advanced_policy.apply(
    advanced_base, "drift_av")
assert advanced_drift["audio_policy"] == advanced_base["audio_policy"]
assert advanced_drift["transition_policy"]["preset"] == "drift_av"
assert advanced_drift["transition_policy"]["continuation_mode"] == (
    "drift_control_av")
assert advanced_drift["audio_context_length"] == 39
assert "advanced override" in advanced_status

legacy_overlay = legacy_adapter.build(
    "generated_audio", "feathered_av", 39, 33,
    chain_policy=advanced_base)[0]
assert legacy_overlay["audio_policy"] == advanced_base["audio_policy"]
assert legacy_overlay["transition_policy"]["continuation_mode"] == (
    "feathered_av")
assert legacy_overlay["audio_context_length"] == 33

print(
    "transition policy: Cut/Guide/Tone Carry Guide/Latent Guide/Detail Guide/"
    "Detail AV/Drift-Control AV/Color-Stable Drift AV/Hard AV/Soft AV/"
    "Audio Feather AV presets, "
    "advanced/raw "
    "overrides, zero-context delivery, AV safety validation, legacy fallback "
    "and adapter, Plan resolution, and one-wire registration pass")
