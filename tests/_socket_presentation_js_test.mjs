import assert from "node:assert/strict";
import fs from "node:fs";
import {
    ADVANCED_POLICY_NODE,
    CHAIN_POLICY_NODE,
    PROFILE_POLICY_NODE,
    applySocketPresentation,
    hasSourceTimeline,
    policyPlanConsumers,
    presentationForNode,
    resolveAudioContextLength,
    resolveAudioPolicy,
    resolveTransitionPolicy,
} from "../web/h3_socket_presentation_core.mjs";

class Graph {
    constructor(nodes, links) {
        this._nodes = nodes;
        this.links = links;
        for (const node of nodes) node.graph = this;
    }

    getNodeById(id) {
        return this._nodes.find((node) => node.id === id) ?? null;
    }
}

function node(id, type, inputs = [], outputs = [], widgets = []) {
    return {
        id,
        comfyClass: type,
        inputs: inputs.map(([name, link = null]) => ({name, link})),
        outputs: outputs.map(([name, links = null]) => ({name, links})),
        widgets: widgets.map(([name, value]) => ({name, value})),
        properties: {},
    };
}

const audioPolicy = node(1, CHAIN_POLICY_NODE, [], [["chain_policy", [10]]], [
    ["incoming_transition", "guide"],
    ["final_audio", "generated"],
    ["source_reference", "off"],
    ["generated_continuity", "on"],
    ["lock_source_audio", false],
]);
const plan = node(2, "MiniMaxH3ChainPlan", [
    ["chain_policy", 10],
], [
    ["plan", [11]], ["summary", null], ["clip_count", null],
    ["video_blend_frames", null],
], [
    ["audio_mode", "source_track"], ["continuation_mode", "guide"],
    ["context_length", 22], ["audio_context_length", 22],
    ["encode_mode", "resize"], ["anchor_mode", "head"], ["crop", "center"],
    ["video_blend_frames", 0],
]);
const start = node(3, "MiniMaxH3ChainLoopStart", [
    ["plan", 11], ["source_audio", null], ["source_timeline", null],
], [["flow", null], ["state", [12]], ["status", null]]);
new Graph([audioPolicy, plan, start], {
    10: {origin_id: 1, target_id: 2},
    11: {origin_id: 2, target_id: 3},
});

assert.deepEqual(resolveAudioPolicy(start), {
    known: true,
    finalAudio: "generated",
    sourceReference: "off",
    generatedContinuity: "on",
    source: "compact",
});
assert.equal(hasSourceTimeline(start), false);
const planPresentation = presentationForNode(plan, false);
assert.equal(planPresentation.hiddenWidgets.has("audio_mode"), true);
assert.equal(planPresentation.hiddenWidgets.has("continuation_mode"), true);
assert.equal(planPresentation.hiddenWidgets.has("context_length"), true);
assert.equal(planPresentation.hiddenWidgets.has("audio_context_length"), true);
assert.equal(planPresentation.hiddenWidgets.has("encode_mode"), true);
assert.equal(planPresentation.hiddenWidgets.has("anchor_mode"), true);
assert.equal(planPresentation.hiddenWidgets.has("crop"), true);
assert.equal(planPresentation.hiddenWidgets.has("video_blend_frames"), true);
assert.equal(planPresentation.hiddenOutputs.has("summary"), true);
assert.equal(planPresentation.hiddenOutputs.has("clip_count"), true);
assert.equal(planPresentation.hiddenOutputs.has("video_blend_frames"), true);
assert.equal(presentationForNode(plan, true).hiddenWidgets.size, 0);

const studio = node(30, "MiniMaxH3ChainPlanStudio", [], [], [
    ["verify_resume_history", true], ["plan_json", "{}"],
    ["run_name", "h3_chain"], ["generation_fingerprint", ""],
    ["width", 960], ["height", 544], ["context_length", 22],
    ["encode_mode", "video"], ["anchor_mode", "head"],
    ["crop", "disabled"], ["audio_mode", "generated_audio"],
    ["audio_context_length", 22], ["default_duration_seconds", 15],
    ["default_steps", 20], ["base_seed", 0], ["segment_crf", 18],
    ["video_blend_frames", 0], ["continuation_mode", "guide"],
]);
const compactStudio = presentationForNode(studio, false);
for (const name of [
    "plan_json", "run_name", "generation_fingerprint", "width", "height",
    "context_length", "encode_mode", "anchor_mode", "crop", "audio_mode",
    "audio_context_length", "default_duration_seconds", "default_steps",
    "base_seed", "segment_crf", "video_blend_frames", "continuation_mode",
]) {
    assert.equal(compactStudio.hiddenWidgets.has(name), true,
        `${name} is edited in Studio's dedicated Plan settings tab`);
}
assert.equal(presentationForNode(studio, true).hiddenWidgets.has("run_name"), false);

const inputOrder = start.inputs.map((slot) => slot.name);
const outputOrder = start.outputs.map((slot) => slot.name);
const linkIds = start.inputs.map((slot) => slot.link);
applySocketPresentation(start, false);
assert.equal(start.inputs[1].hidden, true, "unused legacy AUDIO is compact");
assert.equal(start.outputs[2].hidden, true, "diagnostic status is compact");
assert.deepEqual(start.inputs.map((slot) => slot.name), inputOrder);
assert.deepEqual(start.outputs.map((slot) => slot.name), outputOrder);
assert.deepEqual(start.inputs.map((slot) => slot.link), linkIds);

applySocketPresentation(start, true);
assert.equal(start.inputs[1].hidden, false);
assert.equal(start.outputs[2].hidden, false);

audioPolicy.widgets.find((item) => item.name === "source_reference").value = "on";
assert.equal(presentationForNode(start, false).hiddenInputs.has("source_audio"), false);

const timeline = node(4, "MiniMaxH3SourceTimeline", [], [["source_timeline", [13]]]);
start.inputs.find((slot) => slot.name === "source_timeline").link = 13;
start.graph = new Graph([audioPolicy, plan, timeline, start], {
    10: {origin_id: 1, target_id: 2},
    11: {origin_id: 2, target_id: 3},
    13: {origin_id: 4, target_id: 3},
});
assert.equal(hasSourceTimeline(start), true);
assert.equal(presentationForNode(start, false).hiddenInputs.has("source_audio"), true);

const current = node(5, "MiniMaxH3ChainCurrent", [["state", 12], ["source_audio", null]], [
    ["state", null], ["source_audio_slice", null], ["status", null],
], [["align_audio_reference", false]]);
start.graph._nodes.push(current);
current.graph = start.graph;
start.graph.links[12] = {origin_id: 3, target_id: 5};
const currentPresentation = presentationForNode(current, false);
assert.equal(currentPresentation.hiddenInputs.has("source_audio"), true);
assert.equal(currentPresentation.hiddenOutputs.has("source_audio_slice"), false,
    "source reference is on, so its output stays available");

const upscaleAdapter = node(25, "MiniMaxH3ChainUpscaleAdapter", [], [], [
    ["recipe_json", '{"upscaler":"LBH 3D"}'],
]);
assert.equal(
    presentationForNode(upscaleAdapter, false).hiddenWidgets.has("recipe_json"),
    true,
    "upscale recipe provenance is hidden in the compact view",
);
assert.equal(
    presentationForNode(upscaleAdapter, true).hiddenWidgets.has("recipe_json"),
    false,
    "advanced disclosure keeps the recipe editable",
);

const linkedStatus = node(6, "MiniMaxH3ChainSegmentSave", [], [
    ["segment", null], ["status", [22]],
]);
applySocketPresentation(linkedStatus, false);
assert.equal(linkedStatus.outputs[1].hidden, false,
    "existing diagnostic links stay visible and untouched");
assert.deepEqual(linkedStatus.outputs[1].links, [22]);

assert.deepEqual(resolveTransitionPolicy(plan), {
    known: true,
    preset: "guide",
    continuationMode: "guide",
    contextLength: 22,
    expertOverride: false,
    source: "compact",
});

const unrelatedPlan = node(9, "MiniMaxH3ChainPlan", [
    ["chain_policy", null],
]);
plan.graph._nodes.push(unrelatedPlan);
unrelatedPlan.graph = plan.graph;
assert.deepEqual(policyPlanConsumers(audioPolicy), [plan]);

const compactPolicy = node(10, CHAIN_POLICY_NODE, [], [
    ["chain_policy", [31]], ["status", null],
], [
    ["incoming_transition", "hard_av"], ["final_audio", "source"],
    ["source_reference", "on"], ["generated_continuity", "off"],
    ["lock_source_audio", false],
]);
const compactPlan = node(11, "MiniMaxH3ChainPlan", [
    ["chain_policy", 31],
], [["plan", [32]]], [
    ["audio_context_length", 91],
]);
const compactStart = node(12, "MiniMaxH3ChainLoopStart", [
    ["plan", 32], ["source_audio", null], ["source_timeline", null],
]);
new Graph([compactPolicy, compactPlan, compactStart], {
    31: {origin_id: 10, target_id: 11},
    32: {origin_id: 11, target_id: 12},
});
assert.deepEqual(resolveAudioPolicy(compactStart), {
    known: true,
    finalAudio: "source",
    sourceReference: "on",
    generatedContinuity: "off",
    source: "compact",
});
assert.deepEqual(resolveTransitionPolicy(compactStart), {
    known: true,
    preset: "hard_av",
    continuationMode: "masked_av",
    contextLength: 39,
    expertOverride: false,
    source: "compact",
});
assert.equal(resolveAudioContextLength(compactStart), 39,
    "compact 0.5 policy owns the automatic audio context default");
assert.deepEqual(policyPlanConsumers(compactPolicy), [compactPlan]);
assert.equal(
    presentationForNode(compactPolicy, false).hiddenOutputs.has("status"), true,
);
compactPolicy.widgets.find(
    (item) => item.name === "lock_source_audio").value = true;
assert.deepEqual(resolveAudioPolicy(compactStart), {
    known: true,
    finalAudio: "source",
    sourceReference: "off",
    generatedContinuity: "off",
    source: "compact",
    sourceAudioTarget: "locked",
});
assert.equal(
    presentationForNode(compactStart, false).hiddenInputs.has("source_audio"),
    false,
    "locked source target still needs legacy source audio without a timeline",
);

const generationProfile = node(40, PROFILE_POLICY_NODE, [], [
    ["chain_policy", [41]], ["status", null],
], [
    ["scene_continuity", "Smooth picture + audio continuity"],
    ["audio_profile", "Lip-sync to source audio"],
]);
const profilePlan = node(41, "MiniMaxH3ChainPlan", [
    ["chain_policy", 41],
], [["plan", [42]]]);
const profileStart = node(42, "MiniMaxH3ChainLoopStart", [
    ["plan", 42], ["source_audio", null], ["source_timeline", null],
]);
new Graph([generationProfile, profilePlan, profileStart], {
    41: {origin_id: 40, target_id: 41},
    42: {origin_id: 41, target_id: 42},
});
assert.deepEqual(resolveAudioPolicy(profileStart), {
    known: true,
    finalAudio: "source",
    sourceReference: "off",
    generatedContinuity: "off",
    source: "profile",
    sourceAudioTarget: "locked",
});
assert.deepEqual(resolveTransitionPolicy(profileStart), {
    known: true,
    preset: "soft_av",
    continuationMode: "audio_feathered_av",
    contextLength: 39,
    expertOverride: false,
    source: "profile",
});
assert.equal(resolveAudioContextLength(profileStart), 39);
assert.deepEqual(policyPlanConsumers(generationProfile), [profilePlan]);
assert.equal(
    presentationForNode(generationProfile, false).hiddenOutputs.has("status"),
    true,
);

const legacyAdapter = node(8, "MiniMaxH3Legacy04PolicyAdapter", [], [
    ["chain_policy", null], ["status", null],
], [
    ["audio_mode", "source_plus_timeline"],
    ["continuation_mode", "masked_av"], ["context_length", 56],
    ["audio_context_length", 91],
]);
assert.deepEqual(resolveAudioPolicy(legacyAdapter), {
    known: true,
    finalAudio: "source",
    sourceReference: "on",
    generatedContinuity: "on",
    source: "legacy_adapter",
});
assert.equal(
    presentationForNode(legacyAdapter, false).hiddenWidgets.has("audio_mode"),
    false,
    "standalone legacy migration still exposes its 0.4 audio mode",
);
assert.deepEqual(resolveTransitionPolicy(legacyAdapter), {
    known: true,
    preset: "custom",
    continuationMode: "masked_av",
    contextLength: 56,
    expertOverride: true,
    source: "legacy_adapter",
});
assert.equal(resolveAudioContextLength(legacyAdapter), 91);

const layeredBase = node(20, CHAIN_POLICY_NODE, [], [
    ["chain_policy", [41]], ["status", null],
], [
    ["incoming_transition", "guide"], ["final_audio", "source"],
    ["source_reference", "on"], ["generated_continuity", "on"],
    ["lock_source_audio", false],
]);
const layeredAdvanced = node(21, ADVANCED_POLICY_NODE, [
    ["chain_policy", 41],
], [["chain_policy", [42]], ["status", null]], [
    ["incoming_transition", "drift_av"],
]);
const layeredPlan = node(22, "MiniMaxH3ChainPlan", [
    ["chain_policy", 42],
], [["plan", [43]]], [
    ["audio_mode", "generated_audio"],
    ["continuation_mode", "guide"],
    ["context_length", 5],
    ["audio_context_length", 5],
]);
const layeredStart = node(23, "MiniMaxH3ChainLoopStart", [
    ["plan", 43], ["source_audio", null], ["source_timeline", null],
]);
new Graph([layeredBase, layeredAdvanced, layeredPlan, layeredStart], {
    41: {origin_id: 20, target_id: 21},
    42: {origin_id: 21, target_id: 22},
    43: {origin_id: 22, target_id: 23},
});
assert.deepEqual(resolveAudioPolicy(layeredStart), {
    known: true,
    finalAudio: "source",
    sourceReference: "on",
    generatedContinuity: "on",
    source: "compact",
});
assert.deepEqual(resolveTransitionPolicy(layeredStart), {
    known: true,
    preset: "drift_av",
    continuationMode: "drift_control_av",
    contextLength: 39,
    expertOverride: false,
    source: "advanced",
});
assert.equal(resolveAudioContextLength(layeredStart), 39);
assert.deepEqual(policyPlanConsumers(layeredBase), [layeredPlan]);
assert.deepEqual(policyPlanConsumers(layeredAdvanced), [layeredPlan]);

const legacyOverlay = node(24, "MiniMaxH3Legacy04PolicyAdapter", [
    ["chain_policy", 44],
], [["chain_policy", null]], [
    ["audio_mode", "generated_audio"],
    ["continuation_mode", "feathered_av"], ["context_length", 39],
    ["audio_context_length", 17],
]);
layeredBase.outputs[0].links.push(44);
layeredBase.graph._nodes.push(legacyOverlay);
legacyOverlay.graph = layeredBase.graph;
layeredBase.graph.links[44] = {origin_id: 20, target_id: 24};
assert.deepEqual(resolveAudioPolicy(legacyOverlay), {
    known: true,
    finalAudio: "source",
    sourceReference: "on",
    generatedContinuity: "on",
    source: "compact",
});
assert.equal(
    presentationForNode(legacyOverlay, false).hiddenWidgets.has("audio_mode"),
    true,
    "a chained legacy boundary does not expose its ignored audio mode",
);
assert.equal(
    presentationForNode(legacyOverlay, true).hiddenWidgets.has("audio_mode"),
    true,
    "the ignored legacy audio mode stays hidden in the advanced view",
);

const extensionSource = fs.readFileSync(
    new URL("../web/h3_socket_presentation.js", import.meta.url), "utf8");
assert.match(extensionSource, /Show advanced H3 controls/);
assert.match(extensionSource, /Hide advanced H3 controls/);
assert.match(extensionSource, /refreshPolicyConsumers\(node\)/);
assert.match(extensionSource, /_h3ChainEditorConnectionRefresh/);
assert.match(extensionSource, /_h3PlanStudioRefresh/);
assert.match(extensionSource, /scene_continuity:"Scene continuity"/);
assert.match(extensionSource, /audio_profile:"Audio profile"/);
assert.doesNotMatch(extensionSource, /removeInput|removeOutput/);

console.log("H3 socket presentation: positional compatibility and policy visibility pass");
