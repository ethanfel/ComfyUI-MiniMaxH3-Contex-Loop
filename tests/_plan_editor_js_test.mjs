#!/usr/bin/env node

import assert from "node:assert/strict";
import fs from "node:fs";
import {
    AV_CONTEXT_LENGTHS,
    AUTO_SCENE_COLORS,
    CONTINUATION_MODES,
    CONTEXT_SPATIAL_PROXY_MODES,
    H3_CONTEXT_LENGTHS,
    SCENE_LORA_ROUTES,
    SCENE_PROMPT_SEED_MODES,
    automaticSceneColor,
    audioContextLeadFrameOptions,
    audioContextWindowStarts,
    calculatePlanTiming,
    derivedSceneSeed,
    duplicateShot,
    h3FrameLength,
    makeChapter,
    nativeContextWindowStarts,
    moveShot,
    orderedChapters,
    parsePlanJson,
    planToJson,
    promptValueToText,
    randomSceneSeed,
    renamePlanShot,
    removePlanShot,
    sceneAudioContextLength,
    sceneAudioContextLeadFrames,
    sceneAudioContextLeadSource,
    sceneAudioContextSource,
    sceneAudioContextStartFrame,
    sceneAudioContextUnlocked,
    sceneContextLength,
    sceneContinuationMode,
    sceneLoRARoute,
    scenePromptSeedMode,
    sceneVisualContextLeadFrames,
    sceneVisualContextLeadSource,
    sceneVisualContextBlocks,
    sceneVisualContextStartFrame,
    sceneVisualContextSource,
    sceneVideoBlendFrames,
    setScenePromptSeedMode,
    setShotLengthMode,
    setSharedPrompt,
    shotLengthMode,
    sharedPrompt,
    validateH3Length,
    visualContextCompositions,
    visualContextBoundaryFrames,
    visualContextDefaultPartition,
    visualContextMaximumBlocks,
    visualContextPartitionFromBoundaries,
} from "../web/h3_chain_plan_core.mjs";

const renamePlan = {
    shots:[
        {id:"scene_1", prompt:["one"]},
        {id:"scene_2", prompt:["two"]},
        {id:"scene_3", prompt:["three"], visual_context_source:"scene_1",
            visual_context_lead_source:"scene_2",
            audio_context_unlocked:true,
            audio_context_source:"scene_1",
            audio_context_lead_source:"scene_2"},
    ],
    chapters:[{id:"chapter_1", title:"One", start_scene_id:"scene_2"}],
};
assert.deepEqual(renamePlanShot(renamePlan, 1, "middle scene"), {
    previousId:"scene_2", id:"middle_scene", changed:true,
});
assert.equal(renamePlan.shots.length, 3);
assert.equal(renamePlan.chapters[0].start_scene_id, "middle_scene");
assert.equal(renamePlan.shots[2].visual_context_lead_source, "middle_scene");
assert.equal(renamePlan.shots[2].audio_context_lead_source, "middle_scene");
const beforeDuplicateRename = JSON.stringify(renamePlan);
assert.throws(
    () => renamePlanShot(renamePlan, 2, "scene_1"),
    /already uses the ID/,
);
assert.equal(JSON.stringify(renamePlan), beforeDuplicateRename);
import {
    PRIMARY_TRANSITION_PRESETS,
    applySceneAudioOverride,
    applySceneTransitionPreset,
    primaryTransitionOptions,
    sceneAudioOverride,
    sceneAudioPolicy,
    sceneTransitionPreset,
    transitionPresetLabel,
} from "../web/h3_policy_core.mjs";

assert.deepEqual(PRIMARY_TRANSITION_PRESETS, [
    "cut", "guide", "hard_av", "soft_av",
]);
assert.deepEqual(
    primaryTransitionOptions().map(({name}) => name),
    PRIMARY_TRANSITION_PRESETS,
);
assert.equal(sceneTransitionPreset({}, "guide", 22), "inherit");
assert.equal(sceneTransitionPreset({
    continuation_mode: "masked_av", context_length: 39,
}, "guide", 22, 22), "custom");
assert.equal(sceneTransitionPreset({
    continuation_mode: "masked_av", context_length: 39,
}, "guide", 22, 39), "hard_av");
const compactBoundary = {};
applySceneTransitionPreset(compactBoundary, "hard_av");
assert.deepEqual(compactBoundary, {
    continuation_mode: "masked_av", context_length: 39,
    audio_context_length: 39,
});
compactBoundary.audio_context_length = 7;
assert.equal(sceneTransitionPreset(compactBoundary), "custom");
applySceneTransitionPreset(compactBoundary, "guide");
assert.deepEqual(compactBoundary, {
    continuation_mode: "guide", context_length: 22,
    audio_context_length: 22,
});
applySceneTransitionPreset(compactBoundary, "inherit");
assert.deepEqual(compactBoundary, {});
assert.equal(transitionPresetLabel("soft_av"), "Soft AV");
assert.equal(
    transitionPresetLabel("color_drift_av"), "Color-Stable Drift AV",
);

const sceneAudio = {};
const planAudio = {
    finalAudio:"generated", sourceReference:"off",
    generatedContinuity:"on", sourceAudioTarget:"off",
};
assert.deepEqual(sceneAudioPolicy(sceneAudio, planAudio), {
    finalAudio:"generated", sourceReference:"off",
    generatedContinuity:"on", sourceAudioTarget:"off",
});
assert.equal(sceneAudioOverride(sceneAudio, "source_reference"), "inherit");
applySceneAudioOverride(sceneAudio, "source_reference", "on");
applySceneAudioOverride(sceneAudio, "generated_continuity", "off");
applySceneAudioOverride(sceneAudio, "source_audio_target", "locked");
assert.deepEqual(sceneAudio, {
    source_reference:"on", generated_continuity:"off",
    source_audio_target:"locked",
});
assert.deepEqual(sceneAudioPolicy(sceneAudio, planAudio), {
    finalAudio:"generated", sourceReference:"off",
    generatedContinuity:"off", sourceAudioTarget:"locked",
});
applySceneAudioOverride(sceneAudio, "source_audio_target", "inherit");
assert.equal(sceneAudio.source_audio_target, undefined);
assert.throws(
    () => applySceneAudioOverride(sceneAudio, "source_reference", "maybe"),
    /Unknown scene source reference override/,
);

assert.equal(AUTO_SCENE_COLORS.length, 12);
assert.deepEqual(
    CONTINUATION_MODES,
    [
        "guide", "tone_carry_guide", "latent_guide", "tapered_guide",
        "masked_av", "tapered_av", "feathered_av",
        "audio_feathered_av", "drift_control_av",
        "color_stable_drift_av",
    ],
);
assert.equal(H3_CONTEXT_LENGTHS.at(-1), 243);
assert.deepEqual(AV_CONTEXT_LENGTHS, [39, 90, 141, 192, 243]);
assert.deepEqual(CONTEXT_SPATIAL_PROXY_MODES, [
    "off", "rgb_5_6", "latent_5_6",
]);
assert.deepEqual(SCENE_LORA_ROUTES, [
    "base", ..."abcdefghijklmnopqrstuvwxyz",
]);
assert.equal(sceneLoRARoute({}), "base");
assert.equal(sceneLoRARoute({lora_route: " B "}), "b");
assert.equal(sceneLoRARoute({lora_route: " Z "}), "z");
assert.throws(
    () => sceneLoRARoute({lora_route: "hero"}),
    /LoRA route must be one of base, a/,
);
assert.equal(new Set(AUTO_SCENE_COLORS).size, AUTO_SCENE_COLORS.length);
assert.equal(automaticSceneColor(0), AUTO_SCENE_COLORS[0]);
assert.equal(automaticSceneColor(12), AUTO_SCENE_COLORS[0]);
assert.equal(automaticSceneColor(-1), AUTO_SCENE_COLORS.at(-1));
assert.equal(await derivedSceneSeed(0, 1, "intro"), "2670204060324819354");
assert.equal(await derivedSceneSeed(42, 2, "scene_02"), "7780599706863635211");
assert.equal(
    await derivedSceneSeed(42, 2, "scene_02", {}),
    "7780599706863635211",
);
assert.equal(randomSceneSeed({
    getRandomValues(words) {
        words[0] = 0x12345678;
        words[1] = 0x9abcdef0;
        return words;
    },
}), "1311768467463790320");

const exactLengthShot = {length: 209};
assert.equal(shotLengthMode(exactLengthShot), "frames");
setShotLengthMode(exactLengthShot, "seconds", 15);
assert.equal(shotLengthMode(exactLengthShot), "seconds");
assert.equal(exactLengthShot.duration_seconds, 209 / 24);
assert.equal(exactLengthShot.length, undefined);
setShotLengthMode(exactLengthShot, "frames", 15);
assert.deepEqual(exactLengthShot, {length: 209});

const requestedSecondsShot = {duration_seconds: 10};
setShotLengthMode(requestedSecondsShot, "frames", 15);
assert.deepEqual(requestedSecondsShot, {length: 243});
setShotLengthMode(requestedSecondsShot, "seconds", 15);
assert.deepEqual(requestedSecondsShot, {duration_seconds: 243 / 24});

const inheritedLengthShot = {};
setShotLengthMode(inheritedLengthShot, "frames", 15);
assert.deepEqual(inheritedLengthShot, {length: 362});
setShotLengthMode(inheritedLengthShot, "default", 15);
assert.deepEqual(inheritedLengthShot, {});

assert.equal(sceneContinuationMode({}, "guide"), "guide");
assert.equal(
    sceneContinuationMode({continuation_mode: "tapered_guide"}, "guide"),
    "tapered_guide",
);
assert.equal(
    sceneContinuationMode({continuation_mode: "masked_av"}, "guide"),
    "masked_av",
);
assert.equal(
    sceneContinuationMode({continuation_mode: "tapered_av"}, "guide"),
    "tapered_av",
);
assert.equal(
    sceneContinuationMode({continuation_mode: "feathered_av"}, "guide"),
    "feathered_av",
);
assert.equal(
    sceneContinuationMode({continuation_mode: "audio_feathered_av"}, "guide"),
    "audio_feathered_av",
);
assert.equal(
    sceneContinuationMode({continuation_mode: "drift_control_av"}, "guide"),
    "drift_control_av",
);
assert.equal(
    sceneContinuationMode({continuation_mode: "feathered_av_rgb"}, "guide"),
    "feathered_av",
);
assert.throws(
    () => sceneContinuationMode({continuation_mode: "unknown"}, "guide"),
    /Unknown scene continuation mode/,
);
assert.equal(sceneContextLength({}, 22), 22);
assert.equal(sceneContextLength({context_length: ""}, 22), 22);
assert.equal(sceneContextLength({context_length: 0}, 22), 0);
assert.equal(sceneContextLength({context_length: 39}, 22), 39);
assert.throws(() => sceneContextLength({context_length: 2}, 22), /must be 0/);
assert.equal(sceneAudioContextLength({}, 22, 0), 22);
assert.equal(sceneAudioContextLength({}, 0, 39), 39);
assert.equal(sceneAudioContextLength({audio_context_length: 0}, 22, 39), 0);
assert.equal(sceneAudioContextLength({audio_context_length: 33}, 22, 0), 33);
assert.throws(
    () => sceneAudioContextLength({audio_context_length: 241}, 22, 0),
    /between 0 and 240/,
);
assert.equal(sceneAudioContextUnlocked({}), false);
assert.equal(sceneAudioContextUnlocked({audio_context_unlocked:true}), true);
assert.throws(
    () => sceneAudioContextUnlocked({audio_context_unlocked:"true"}),
    /true or false/,
);
const independentAudioPlan = {shots:[
    {id:"one"}, {id:"two"}, {id:"three"},
    {id:"four"},
    {id:"five", audio_context_unlocked:true,
        audio_context_source:"three", audio_context_start_frame:0,
        audio_context_lead_source:"four", audio_context_lead_frames:5,
        audio_context_lead_start_frame:12},
]};
assert.equal(sceneAudioContextSource(independentAudioPlan, 5), 3);
assert.equal(sceneAudioContextLeadSource(independentAudioPlan, 5), 4);
assert.equal(sceneAudioContextLeadFrames(independentAudioPlan.shots[4], 39), 5);
assert.ok(audioContextLeadFrameOptions(39).includes(5));
assert.equal(audioContextLeadFrameOptions(39).at(-1), 38);
assert.deepEqual(audioContextWindowStarts(90, 51, 5).slice(0, 5), [
    0, 1, 3, 4, 6,
]);
assert.equal(sceneAudioContextStartFrame(
    independentAudioPlan.shots[4], 90, 51, 34,
), 0);
assert.equal(sceneAudioContextStartFrame(
    independentAudioPlan.shots[4], 90, 51, 5, true,
), 12);
assert.equal(sceneVideoBlendFrames({}, 5, 22), 5);
assert.equal(sceneVideoBlendFrames({}, 39, 22), 22);
assert.equal(sceneVideoBlendFrames({video_blend_frames: 0}, 5, 22), 0);
assert.equal(sceneVideoBlendFrames({video_blend_frames: 17}, 5, 22), 17);
assert.throws(
    () => sceneVideoBlendFrames({video_blend_frames: 23}, 5, 22),
    /between 0 and its context length \(22\)/,
);

const invalidDurationShot = {duration_seconds: 999};
assert.throws(() => setShotLengthMode(invalidDurationShot, "frames", 15));
assert.deepEqual(invalidDurationShot, {duration_seconds: 999});

const plan = parsePlanJson(JSON.stringify({
    prompt_prefix: ["Identity.", "", "Wardrobe."],
    defaults: {duration_seconds: 15, steps: 20},
    shots: [
        {id: "one", prompt: "Opening.\nKeep moving.", seed: 18446744073709551615n.toString()},
        {id: "two", prompt: ["Continue.", "", "End turning."], length: 260},
    ],
}));

assert.equal(sharedPrompt(plan).text, "Identity.\n\nWardrobe.");
assert.equal(promptValueToText(plan.shots[0].prompt), "Opening.\nKeep moving.");
setSharedPrompt(plan, "New identity.\n\nNew wardrobe.");
assert.deepEqual(plan.prompt_prefix, ["New identity.", "", "New wardrobe."]);
assert.equal(JSON.parse(planToJson(plan)).shots[0].seed, "18446744073709551615");

const chapterPlan = parsePlanJson(JSON.stringify({
    shots:[
        {id:"scene_a", prompt:"A"},
        {id:"scene_b", prompt:"B"},
        {id:"scene_c", prompt:"C"},
    ],
    chapters:[
        {id:"second", title:"Chapter 2", start_scene_id:"scene_c", text:["lyrics", "notes"]},
        {id:"first", title:"Chapter 1", start_scene_id:"scene_a", text:"setup"},
    ],
}));
assert.deepEqual(orderedChapters(chapterPlan).map((chapter) => chapter.id), [
    "first", "second",
]);
assert.equal(chapterPlan.chapters[1].text, "lyrics\nnotes");
const middleChapter = makeChapter(chapterPlan, 1);
assert.equal(middleChapter.start_scene_id, "scene_b");
assert.throws(() => makeChapter(chapterPlan, 1), /already starts before scene 2/);
removePlanShot(chapterPlan, 1);
assert.equal(chapterPlan.shots[1].id, "scene_c");
assert.equal(
    chapterPlan.chapters.filter((chapter) => chapter.start_scene_id === "scene_c").length,
    1,
    "removing a boundary scene never creates duplicate chapter markers",
);
assert.throws(() => parsePlanJson(JSON.stringify({
    shots:[{id:"one", prompt:"x"}],
    chapters:[{id:"bad", start_scene_id:"missing", text:"x"}],
})), /starts at missing scene/);

const numericSeed = parsePlanJson(
    '{"shots":[{"id":"seed","prompt":"x","seed":18446744073709551615}]}',
);
assert.equal(numericSeed.shots[0].seed, "18446744073709551615");
assert.deepEqual(SCENE_PROMPT_SEED_MODES, [
    "inherit", "fixed", "randomize",
]);
assert.equal(scenePromptSeedMode({}), "inherit");
assert.equal(scenePromptSeedMode({prompt_seed:"42"}), "fixed");
const promptSeedShot = {};
setScenePromptSeedMode(promptSeedShot, "fixed", {
    getRandomValues(words) {
        words[0] = 1;
        words[1] = 2;
        return words;
    },
});
assert.deepEqual(promptSeedShot, {
    prompt_seed_mode:"fixed", prompt_seed:"4294967298",
});
setScenePromptSeedMode(promptSeedShot, "randomize");
assert.deepEqual(promptSeedShot, {prompt_seed_mode:"randomize"});
setScenePromptSeedMode(promptSeedShot, "inherit");
assert.deepEqual(promptSeedShot, {});
assert.throws(
    () => setScenePromptSeedMode({}, "rolling"),
    /Prompt seed mode must be one of/,
);
const numericPromptSeed = parsePlanJson(
    '{"shots":[{"id":"prompt-seed","prompt":"x",' +
    '"prompt_seed":18446744073709551615}]}',
);
assert.deepEqual(numericPromptSeed.shots[0], {
    id:"prompt-seed", prompt:["x"], prompt_seed_mode:"fixed",
    prompt_seed:"18446744073709551615",
});
const promptContainingSeedText = parsePlanJson(
    '{"shots":[{"prompt":"Literal \\\"seed\\\": 18446744073709551615 text"}]}',
);
assert.equal(
    promptValueToText(promptContainingSeedText.shots[0].prompt),
    'Literal "seed": 18446744073709551615 text',
);

const shorthandDefaults = parsePlanJson(JSON.stringify({
    duration_seconds: 8,
    steps: 10,
    shots: [{
        id: "imported",
        prompt: "Imported prompt.",
        duration_seconds: 6,
        steps: 12,
    }],
}));
assert.deepEqual(shorthandDefaults.defaults, {duration_seconds: 8, steps: 10});
assert.equal(Object.hasOwn(shorthandDefaults, "duration_seconds"), false);
assert.equal(Object.hasOwn(shorthandDefaults, "steps"), false);
assert.equal(shorthandDefaults.shots[0].duration_seconds, 6);
assert.equal(shorthandDefaults.shots[0].steps, 12);

assert.equal(h3FrameLength(5), 124);
assert.equal(h3FrameLength(10), 243);
assert.equal(h3FrameLength(15), 362);
assert.equal(validateH3Length(260), 260);
assert.throws(() => validateH3Length(240), /length % 17/);

const timing = calculatePlanTiming(plan, {
    contextLength: 22,
    videoBlendFrames: 5,
    encodeMode: "video",
    anchorMode: "head",
    continuationMode: "guide",
    defaultDurationSeconds: 5,
    defaultSteps: 10,
});
assert.deepEqual(timing.shots.map((shot) => shot.rawFrames), [362, 260]);
assert.deepEqual(timing.shots.map((shot) => shot.deliveredFrames), [362, 238]);
assert.equal(timing.shots[1].generationStartFrame, 340);
assert.equal(timing.totalFrames, 600);
assert.deepEqual(timing.errors, []);
assert.deepEqual(
    timing.shots.map((shot) => shot.continuationMode),
    ["guide", "guide"],
);
assert.deepEqual(timing.shots.map((shot) => shot.videoBlendFrames), [5, 5]);
assert.deepEqual(timing.shots.map((shot) => shot.loraRoute), ["base", "base"]);

const loraPlan = parsePlanJson(JSON.stringify({shots: [
    {id: "base", prompt: "Base scene.", lora_route: "base"},
    {id: "hero", prompt: "Hero LoRA.", lora_route: "A"},
    {id: "style", prompt: "Style LoRA.", lora_route: "d"},
    {id: "final", prompt: "Final LoRA.", lora_route: "Z"},
]}));
assert.equal(Object.hasOwn(loraPlan.shots[0], "lora_route"), false);
assert.equal(loraPlan.shots[1].lora_route, "a");
assert.deepEqual(calculatePlanTiming(loraPlan, {
    contextLength: 22,
    encodeMode: "video",
    anchorMode: "head",
    continuationMode: "guide",
    defaultDurationSeconds: 5,
}).shots.map((shot) => shot.loraRoute), ["base", "a", "d", "z"]);
assert.match(calculatePlanTiming({shots: [
    {id: "bad", prompt: "Bad route.", lora_route: "hero"},
]}, {
    contextLength: 22,
    encodeMode: "video",
    anchorMode: "head",
    continuationMode: "guide",
    defaultDurationSeconds: 5,
}).errors.join("\n"), /LoRA route must be one of base, a/);

const perSceneBlendTiming = calculatePlanTiming({shots: [
    {id: "one", prompt: "One.", length: 124},
    {id: "two", prompt: "Two.", length: 124, context_length: 39,
        video_blend_frames: 5},
    {id: "three", prompt: "Three.", length: 124, context_length: 22,
        video_blend_frames: 0},
]}, {
    contextLength: 39,
    videoBlendFrames: 30,
    encodeMode: "video",
    anchorMode: "head",
    continuationMode: "guide",
    defaultDurationSeconds: 5,
});
assert.deepEqual(
    perSceneBlendTiming.shots.map((shot) => shot.videoBlendFrames),
    [30, 5, 0],
);
assert.deepEqual(perSceneBlendTiming.errors, []);

const mixedContinuationPlan = parsePlanJson(JSON.stringify({
    shots: [
        {id: "new_shot", prompt: "Flexible transition."},
        {id: "same_shot", prompt: "Exact continuation.", continuation_mode: "masked_av"},
    ],
}));
const mixedContinuationTiming = calculatePlanTiming(mixedContinuationPlan, {
    contextLength: 39,
    encodeMode: "video",
    anchorMode: "head",
    continuationMode: "guide",
    defaultDurationSeconds: 5,
});
assert.deepEqual(
    mixedContinuationTiming.shots.map((shot) => shot.continuationMode),
    ["guide", "masked_av"],
);
assert.deepEqual(mixedContinuationTiming.errors, []);
assert.equal(
    JSON.parse(planToJson(mixedContinuationPlan)).shots[1].continuation_mode,
    "masked_av",
);
assert.match(calculatePlanTiming(mixedContinuationPlan, {
    contextLength: 1,
    encodeMode: "frames",
    anchorMode: "before",
    continuationMode: "guide",
    defaultDurationSeconds: 5,
}).errors.join("\n"), /AV mask continuation requires/);
assert.match(calculatePlanTiming(mixedContinuationPlan, {
    contextLength: 22,
    encodeMode: "video",
    anchorMode: "head",
    continuationMode: "guide",
    defaultDurationSeconds: 5,
}).errors.join("\n"), /exact shared video\/audio boundary/);

const fiveFrameVideoOnlyAv = calculatePlanTiming({shots: [
    {id: "one", prompt: "Opening.", length: 90},
    {id: "two", prompt: "Continue.", length: 90},
]}, {
    contextLength: 5,
    audioContextLength: 5,
    encodeMode: "video",
    anchorMode: "head",
    continuationMode: "masked_av",
    generatedContinuity: "off",
});
assert.deepEqual(fiveFrameVideoOnlyAv.errors, []);
assert.equal(fiveFrameVideoOnlyAv.shots[1].contextLength, 5);
assert.equal(fiveFrameVideoOnlyAv.shots[1].audioContextLength, 0);
assert.equal(
    fiveFrameVideoOnlyAv.shots[1].preservesGeneratedAudioPrefix, false,
);
assert.match(calculatePlanTiming({shots: [
    {id: "one", prompt: "Opening.", length: 90},
    {id: "two", prompt: "Continue.", length: 90},
]}, {
    contextLength: 5,
    audioContextLength: 5,
    encodeMode: "video",
    anchorMode: "head",
    continuationMode: "masked_av",
    generatedContinuity: "on",
}).errors.join("\n"), /exact shared video\/audio boundary/);

const featheredContinuationPlan = parsePlanJson(JSON.stringify({
    shots: [
        {id: "one", prompt: "Opening."},
        {id: "two", prompt: "Continue.", continuation_mode: "feathered_av"},
    ],
}));
const featheredContinuationTiming = calculatePlanTiming(
    featheredContinuationPlan,
    {
        contextLength: 39,
        encodeMode: "video",
        anchorMode: "head",
        continuationMode: "guide",
        defaultDurationSeconds: 5,
    },
);
assert.equal(
    featheredContinuationTiming.shots[1].continuationMode,
    "feathered_av",
);
assert.equal(featheredContinuationTiming.shots[1].audioContextLength, 39);
assert.deepEqual(featheredContinuationTiming.errors, []);

const driftControlPlan = parsePlanJson(JSON.stringify({
    shots: [
        {id: "one", prompt: "Opening."},
        {id: "two", prompt: "Continue.", continuation_mode: "drift_control_av"},
    ],
}));
const driftControlTiming = calculatePlanTiming(driftControlPlan, {
    contextLength: 39,
    encodeMode: "video",
    anchorMode: "head",
    continuationMode: "guide",
    defaultDurationSeconds: 5,
});
assert.equal(
    driftControlTiming.shots[1].continuationMode,
    "drift_control_av",
);
assert.deepEqual(driftControlTiming.errors, []);
assert.match(calculatePlanTiming(driftControlPlan, {
    contextLength: 90,
    encodeMode: "video",
    anchorMode: "head",
    continuationMode: "guide",
    defaultDurationSeconds: 5,
}).errors.join("\n"), /Drift-Control AV.*require exactly 39/);

const colorDriftPlan = parsePlanJson(JSON.stringify({
    shots: [
        {id: "one", prompt: "Opening."},
        {id: "two", prompt: "Continue.",
            continuation_mode: "color_stable_drift_av"},
    ],
}));
const colorDriftTiming = calculatePlanTiming(colorDriftPlan, {
    contextLength: 39,
    encodeMode: "video",
    anchorMode: "head",
    continuationMode: "guide",
    defaultDurationSeconds: 5,
});
assert.deepEqual(colorDriftTiming.errors, []);
assert.equal(colorDriftTiming.shots[1].audioContextLength, 39);
const colorDriftProxyTiming = calculatePlanTiming({shots: [
    {id: "one", prompt: "Opening."},
    {id: "two", prompt: "Continue.",
        continuation_mode: "color_stable_drift_av",
        context_spatial_proxy: "latent_5_6"},
]}, {
    contextLength: 39,
    encodeMode: "video",
    anchorMode: "head",
    continuationMode: "guide",
    defaultDurationSeconds: 5,
});
assert.deepEqual(colorDriftProxyTiming.errors, []);
assert.match(calculatePlanTiming(colorDriftPlan, {
    contextLength: 90,
    encodeMode: "video",
    anchorMode: "head",
    continuationMode: "guide",
    defaultDurationSeconds: 5,
}).errors.join("\n"), /Color-Stable Drift AV currently require exactly 39/);

const latentGuideTiming = calculatePlanTiming({shots: [
    {id: "one", prompt: "Opening."},
    {id: "two", prompt: "Continue.", continuation_mode: "latent_guide"},
]}, {
    contextLength: 22,
    encodeMode: "video",
    anchorMode: "head",
    continuationMode: "guide",
    defaultDurationSeconds: 5,
});
assert.equal(latentGuideTiming.shots[1].continuationMode, "latent_guide");
assert.deepEqual(latentGuideTiming.errors, []);
assert.match(calculatePlanTiming({shots: [
    {id: "one", prompt: "Opening."},
    {id: "two", prompt: "Continue.", continuation_mode: "latent_guide"},
]}, {
    contextLength: 1,
    encodeMode: "video",
    anchorMode: "head",
    continuationMode: "guide",
    defaultDurationSeconds: 5,
}).errors.join("\n"), /Latent Guide requires/);

const mixedContextTiming = calculatePlanTiming({shots: [
    {id: "one", prompt: "One.", length: 192},
    {id: "clean", prompt: "Clean.", length: 192, context_length: 0,
        continuation_mode: "masked_av"},
    {id: "continued", prompt: "Continue.", length: 192, context_length: 39},
]}, {
    contextLength: 22,
    encodeMode: "frames",
    anchorMode: "before",
    continuationMode: "guide",
});
assert.deepEqual(
    mixedContextTiming.shots.map((shot) => shot.contextLength), [22, 0, 39],
);
assert.deepEqual(
    mixedContextTiming.shots.map((shot) => shot.deliveredFrames), [192, 192, 192],
);
assert.deepEqual(mixedContextTiming.errors, []);

const audioOnlyTiming = calculatePlanTiming({shots: [
    {id: "one", prompt: "One.", length: 192},
    {id: "audio_only", prompt: "New picture, continuous sound.", length: 192,
        context_length: 0, audio_context_length: 33},
]}, {
    contextLength: 22,
    audioContextLength: 22,
    encodeMode: "video",
    anchorMode: "head",
    continuationMode: "guide",
});
assert.equal(audioOnlyTiming.shots[1].contextLength, 0);
assert.equal(audioOnlyTiming.shots[1].audioContextLength, 33);
assert.equal(audioOnlyTiming.shots[1].deliveredFrames, 192);
assert.deepEqual(audioOnlyTiming.errors, []);

const scheduledProxyTiming = calculatePlanTiming({shots: [
    {id: "one", prompt: "One.", length: 90},
    {id: "two", prompt: "Two.", length: 90},
    {id: "three", prompt: "Three.", length: 90},
    {id: "four", prompt: "Four.", length: 90,
        context_spatial_proxy: "latent_5_6"},
]}, {
    contextLength: 39,
    audioContextLength: 39,
    encodeMode: "video",
    anchorMode: "head",
    continuationMode: "masked_av",
});
assert.deepEqual(scheduledProxyTiming.errors, []);
assert.deepEqual(
    scheduledProxyTiming.shots.map((shot) => shot.contextSpatialProxy),
    ["off", "off", "off", "latent_5_6"],
);
const invalidProxyTiming = calculatePlanTiming({shots: [
    {id: "one", prompt: "One.", length: 90},
    {id: "two", prompt: "Two.", length: 90,
        context_spatial_proxy: "rgb_5_6"},
]}, {
    contextLength: 39,
    audioContextLength: 39,
    encodeMode: "video",
    anchorMode: "head",
    continuationMode: "masked_av",
});
assert.match(
    invalidProxyTiming.errors.join("\n"),
    /Low-grid 5\/6 boundary proxy/,
);

const sceneOneProxyTiming = calculatePlanTiming({shots: [
    {id: "one", prompt: "One.", length: 90,
        context_spatial_proxy: "rgb_5_6"},
    {id: "two", prompt: "Two.", length: 90},
]}, {
    contextLength: 5,
    audioContextLength: 5,
    encodeMode: "video",
    anchorMode: "head",
    continuationMode: "guide",
});
assert.match(
    sceneOneProxyTiming.errors.join("\n"),
    /Scene 1 cannot use a 5\/6 boundary proxy/,
);

const sharedOnlyPlan = parsePlanJson(JSON.stringify({
    prompt_prefix: "Shared identity and direction.",
    shots: [{id: "shared_only", prompt: ""}],
}));
const sharedOnlyTiming = calculatePlanTiming(sharedOnlyPlan, {
    contextLength: 22,
    anchorMode: "head",
    defaultDurationSeconds: 5,
    defaultSteps: 10,
});
assert.deepEqual(sharedOnlyTiming.errors, []);

const fullyEmptyPlan = parsePlanJson(JSON.stringify({
    shots: [{id: "empty", prompt: ""}],
}));
const fullyEmptyTiming = calculatePlanTiming(fullyEmptyPlan, {
    contextLength: 22,
    anchorMode: "head",
    defaultDurationSeconds: 5,
    defaultSteps: 10,
});
assert.match(fullyEmptyTiming.errors.join("\n"), /scene and shared prompts are both empty/i);

const longPlan = parsePlanJson(JSON.stringify({
    defaults: {duration_seconds: 15, steps: 5},
    shots: Array.from({length: 14}, (_, index) => ({
        id: `clip_${String(index + 1).padStart(2, "0")}`,
        prompt: `Scene ${index + 1}`,
        ...(index === 13 ? {duration_seconds: 5} : {}),
    })),
}));
const longTiming = calculatePlanTiming(longPlan, {
    contextLength: 22,
    anchorMode: "head",
    defaultDurationSeconds: 15,
    defaultSteps: 20,
});
assert.equal(longTiming.totalFrames, 4544);
assert.equal(longTiming.totalSeconds, 189 + 1 / 3);
assert.deepEqual(longTiming.errors, []);

const nonlinearPlan = parsePlanJson(JSON.stringify({
    shots: [
        {id:"one", prompt:"one", length:39},
        {id:"two", prompt:"two", length:39},
        {id:"three", prompt:"three", length:39},
        {id:"four", prompt:"four", length:39},
        {id:"five", prompt:"five", length:39,
         visual_context_source:"three", video_blend_frames:0},
    ],
}));
assert.equal(sceneVisualContextSource(nonlinearPlan, 4), 3);
assert.equal(sceneVisualContextSource(nonlinearPlan, 5), 3);
const nonlinearTiming = calculatePlanTiming(nonlinearPlan, {
    contextLength:5, videoBlendFrames:0, anchorMode:"head",
    defaultDurationSeconds:5, defaultSteps:10,
});
assert.deepEqual(nonlinearTiming.errors, []);
assert.equal(nonlinearTiming.shots[4].visualContextSource, 3);
assert.equal(nonlinearTiming.shots[4].visualContextSourceId, "three");
const invalidNonlinearPlan = structuredClone(nonlinearPlan);
invalidNonlinearPlan.shots[4].visual_context_source = "missing";
assert.match(calculatePlanTiming(invalidNonlinearPlan, {
    contextLength:5, videoBlendFrames:0, anchorMode:"head",
    defaultDurationSeconds:5, defaultSteps:10,
}).errors.join("\n"), /does not match a scene ID/i);
const blendedNonlinearPlan = structuredClone(nonlinearPlan);
blendedNonlinearPlan.shots[4].video_blend_frames = 2;
assert.match(calculatePlanTiming(blendedNonlinearPlan, {
    contextLength:5, videoBlendFrames:0, anchorMode:"head",
    defaultDurationSeconds:5, defaultSteps:10,
}).errors.join("\n"), /non-linear, composed, or windowed visual context requires 0 assembly blend/i);

const composedPlan = structuredClone(nonlinearPlan);
for (const shot of composedPlan.shots) shot.length = 90;
Object.assign(composedPlan.shots[4], {
    visual_context_lead_source:"four",
    visual_context_lead_frames:5,
});
assert.equal(sceneVisualContextLeadSource(composedPlan, 5), 4);
assert.equal(sceneVisualContextLeadFrames(composedPlan.shots[4], 39), 5);
const contextCompositions = visualContextCompositions();
assert.deepEqual(
    contextCompositions.filter((choice) => choice.total === 39)
        .map((choice) => choice.label),
    [
        "39 total · 5 + 34",
        "39 total · 17 + 22",
        "39 total · 22 + 17",
        "39 total · 34 + 5",
    ],
);
assert.deepEqual(
    contextCompositions.filter((choice) => choice.total === 56)
        .map((choice) => choice.label),
    [
        "56 total · 5 + 51",
        "56 total · 17 + 39",
        "56 total · 22 + 34",
        "56 total · 34 + 22",
        "56 total · 39 + 17",
        "56 total · 51 + 5",
    ],
);
assert.equal(sceneVisualContextLeadFrames({
    visual_context_lead_frames:17,
}, 39), 17);
assert.deepEqual(nativeContextWindowStarts(90, 85, 22, 0), [
    12, 29, 46, 63,
]);
assert.deepEqual(nativeContextWindowStarts(90, 85, 17, 22), [
    0, 17, 34, 51, 68,
]);
assert.equal(sceneVisualContextStartFrame({}, 90, 85, 22), 63);
assert.equal(sceneVisualContextStartFrame({
    visual_context_start_frame:12,
}, 90, 85, 22), 12);
assert.equal(sceneVisualContextStartFrame({
    visual_context_lead_start_frame:12,
}, 90, 85, 17, true), 12);
assert.throws(() => sceneVisualContextStartFrame({
    visual_context_start_frame:64,
}, 90, 85, 22), /must be between 0 and 63/i);
assert.throws(() => sceneVisualContextStartFrame({
    visual_context_start_frame:10,
}, 90, 85, 22), /native temporal latent lattice/i);
assert.equal(contextCompositions.at(-1).total, 243);
assert.deepEqual(visualContextBoundaryFrames(39), [5, 17, 22, 34]);
assert.equal(visualContextMaximumBlocks(39), 5);
assert.deepEqual(visualContextPartitionFromBoundaries(39, [5, 17]), [
    5, 12, 22,
]);
assert.deepEqual(visualContextDefaultPartition(22, 3), [5, 12, 5]);
const multiContextPlan = structuredClone(nonlinearPlan);
for (const shot of multiContextPlan.shots) shot.length = 90;
Object.assign(multiContextPlan.shots[4], {
    context_length:39,
    visual_context_blocks:[
        {source:"one", frames:5},
        {source:"four", frames:12, start_frame:0},
        {source:"three", frames:22},
    ],
});
delete multiContextPlan.shots[4].visual_context_source;
const multiBlocks = sceneVisualContextBlocks(multiContextPlan, 5, 39);
assert.deepEqual(multiBlocks.map((block) => [
    block.source, block.frames, block.startFrame,
]), [[1, 5, null], [4, 12, 0], [3, 22, null]]);
const multiTiming = calculatePlanTiming(multiContextPlan, {
    contextLength:39, videoBlendFrames:0, anchorMode:"head",
    defaultDurationSeconds:5, defaultSteps:10,
});
assert.deepEqual(multiTiming.errors, []);
assert.deepEqual(multiTiming.shots[4].visualContextBlocks.map((block) => [
    block.source, block.frames,
]), [[1, 5], [4, 12], [3, 22]]);
assert.throws(() => sceneVisualContextBlocks({shots:[
    {id:"one"}, {id:"two", visual_context_blocks:[
        {source:"one", frames:6}, {source:"one", frames:16},
    ]},
]}, 2, 22), /not an H3 latent boundary/i);
const composedTiming = calculatePlanTiming(composedPlan, {
    contextLength:39, videoBlendFrames:0, anchorMode:"head",
    defaultDurationSeconds:5, defaultSteps:10,
});
assert.deepEqual(composedTiming.errors, []);
assert.equal(composedTiming.shots[4].visualContextSource, 3);
assert.equal(composedTiming.shots[4].visualContextLeadSource, 4);
assert.equal(composedTiming.shots[4].visualContextLeadSourceId, "four");
assert.equal(composedTiming.shots[4].visualContextLeadFrames, 5);
assert.equal(composedTiming.shots[4].visualContextStartFrame, 17);
assert.equal(composedTiming.shots[4].visualContextLeadStartFrame, 46);
const independentAudioTimingPlan = structuredClone(composedPlan);
Object.assign(independentAudioTimingPlan.shots[4], {
    audio_context_unlocked:true,
    audio_context_source:"three",
    audio_context_start_frame:0,
    audio_context_lead_source:"four",
    audio_context_lead_frames:5,
    audio_context_lead_start_frame:12,
});
const independentAudioTiming = calculatePlanTiming(
    independentAudioTimingPlan, {
        contextLength:39, audioContextLength:39,
        continuationMode:"masked_av", generatedContinuity:"on",
        videoBlendFrames:0, anchorMode:"head", encodeMode:"video",
        defaultDurationSeconds:5, defaultSteps:10,
    },
);
assert.deepEqual(independentAudioTiming.errors, []);
assert.equal(independentAudioTiming.shots[4].audioContextUnlocked, true);
assert.equal(independentAudioTiming.shots[4].audioContextSource, 3);
assert.equal(independentAudioTiming.shots[4].audioContextLeadSource, 4);
assert.equal(independentAudioTiming.shots[4].audioContextLeadFrames, 5);
assert.equal(independentAudioTiming.shots[4].audioContextStartFrame, 0);
assert.equal(independentAudioTiming.shots[4].audioContextLeadStartFrame, 12);
const disabledIndependentAudioTiming = calculatePlanTiming(
    independentAudioTimingPlan, {
        contextLength:39, audioContextLength:39,
        continuationMode:"masked_av", generatedContinuity:"off",
        videoBlendFrames:0, anchorMode:"head", encodeMode:"video",
        defaultDurationSeconds:5, defaultSteps:10,
    },
);
assert.ok(disabledIndependentAudioTiming.errors.some((message) => (
    message.includes("requires Generated continuity")
)));
const lockedIndependentAudioTiming = calculatePlanTiming(
    independentAudioTimingPlan, {
        contextLength:39, audioContextLength:39,
        continuationMode:"masked_av", generatedContinuity:"on",
        sourceAudioTarget:"locked", videoBlendFrames:0,
        anchorMode:"head", encodeMode:"video",
        defaultDurationSeconds:5, defaultSteps:10,
    },
);
assert.ok(lockedIndependentAudioTiming.errors.some((message) => (
    message.includes("cannot be combined with Lip-sync")
)));
const windowedComposition = structuredClone(composedPlan);
windowedComposition.shots[4].visual_context_start_frame = 0;
windowedComposition.shots[4].visual_context_lead_start_frame = 29;
const windowedTiming = calculatePlanTiming(windowedComposition, {
    contextLength:39, videoBlendFrames:0, anchorMode:"head",
    defaultDurationSeconds:5, defaultSteps:10,
});
assert.deepEqual(windowedTiming.errors, []);
assert.equal(windowedTiming.shots[4].visualContextStartFrame, 0);
assert.equal(windowedTiming.shots[4].visualContextLeadStartFrame, 29);

const sameSourceComposition = structuredClone(composedPlan);
Object.assign(sameSourceComposition.shots[4], {
    visual_context_lead_source:"three",
    visual_context_start_frame:0,
    visual_context_lead_start_frame:29,
});
const sameSourceTiming = calculatePlanTiming(sameSourceComposition, {
    contextLength:39, videoBlendFrames:0, anchorMode:"head",
    defaultDurationSeconds:5, defaultSteps:10,
});
assert.deepEqual(sameSourceTiming.errors, []);
assert.equal(sameSourceTiming.shots[4].visualContextSource, 3);
assert.equal(sameSourceTiming.shots[4].visualContextLeadSource, 3);
assert.equal(sameSourceTiming.shots[4].visualContextLeadFrames, 5);
assert.equal(sameSourceTiming.shots[4].visualContextStartFrame, 0);
assert.equal(sameSourceTiming.shots[4].visualContextLeadStartFrame, 29);
const invalidCompositionSpan = structuredClone(composedPlan);
invalidCompositionSpan.shots[4].visual_context_lead_frames = 6;
assert.match(calculatePlanTiming(invalidCompositionSpan, {
    contextLength:39, videoBlendFrames:0, anchorMode:"head",
    defaultDurationSeconds:5, defaultSteps:10,
}).errors.join("\n"), /composed context lead frames must be one of 5, 17, 22, 34/i);
const blendedComposition = structuredClone(composedPlan);
blendedComposition.shots[4].video_blend_frames = 2;
assert.match(calculatePlanTiming(blendedComposition, {
    contextLength:39, videoBlendFrames:0, anchorMode:"head",
    defaultDurationSeconds:5, defaultSteps:10,
}).errors.join("\n"), /non-linear, composed, or windowed visual context requires 0 assembly blend/i);

duplicateShot(plan.shots, 0);
assert.equal(plan.shots.length, 3);
assert.equal(plan.shots[1].id, "one_copy");
moveShot(plan.shots, 1, 2);
assert.equal(plan.shots[2].id, "one_copy");

const readable = JSON.parse(planToJson(plan));
assert.deepEqual(readable.prompt_prefix, ["New identity.", "", "New wardrobe."]);
assert.deepEqual(readable.shots[0].prompt, ["Opening.", "Keep moving."]);

const editorSource = fs.readFileSync(
    new URL("../web/h3_chain_plan_editor.js", import.meta.url),
    "utf8",
);
const upgradeSource = fs.readFileSync(
    new URL("../web/h3_plan_upgrade_core.mjs", import.meta.url),
    "utf8",
);
assert.match(editorSource, /collapseWidget\(planWidget\)/);
assert.match(upgradeSource, /MiniMaxH3ChainPlanModern/);
assert.match(editorSource, /Upgrade to Modern Plan/);
assert.match(editorSource, /replaceWithModernPlan/);
assert.match(editorSource, /Generation Profile required/);
assert.match(editorSource, /Project/);
assert.match(editorSource, /Canvas & context fitting/);
assert.match(editorSource, /Generation defaults/);
assert.match(editorSource, /Delivery/);
assert.match(editorSource, /collapseModernBackingWidgets/);
assert.match(editorSource, /display[^\n]+none[^\n]+important/);
assert.match(editorSource, /pointer-events[^\n]+none[^\n]+important/);
assert.match(editorSource, /widget\.onRemove\(\)/);
assert.match(editorSource, /const onAdded = nodeType\.prototype\.onAdded/);
assert.match(editorSource, /onGraphConfigured/);
assert.match(editorSource, /scheduleResponsiveSize\(\)/);
assert.doesNotMatch(editorSource, /height: \$\{EDITOR_HEIGHT\}px/);
assert.match(editorSource, /height: 100%/);
assert.match(editorSource, /contain: layout paint/);
assert.match(editorSource, /widget\.hidden = true/);
assert.match(editorSource, /widget\.draw = \(\) => \{\}/);
assert.match(editorSource, /node\.size\?\.\[1\][^\n]+0,/);
assert.doesNotMatch(editorSource, /const computed = node\.computeSize/);
assert.match(editorSource, /h3_chain_plan_layout/);
assert.match(editorSource, /removePlanShot/);
assert.match(editorSource, /new ResizeObserver/);
assert.match(editorSource, /"pointerdown", "pointerup", "mousedown", "mouseup", "click"/);
assert.match(editorSource, /availableReferenceRecords/);
assert.doesNotMatch(editorSource, /\[\["Picture", 9\], \["Video", 3\], \["Audio", 6\]\]/);
assert.match(editorSource, /Derived seed:/);
assert.match(editorSource, /New random/);
assert.match(editorSource, /Use derived/);
assert.match(editorSource, /Prompt alternatives/);
assert.match(editorSource, /Stable derived/);
assert.doesNotMatch(editorSource, /Inherit Plan seed/);
assert.match(editorSource, /Randomize each queue/);
assert.match(editorSource, /setScenePromptSeedMode/);
assert.match(editorSource, /Scene LoRA route/);
assert.match(editorSource, /MiniMax H3 Scene LoRA Scheduler/);
assert.match(editorSource, /availableLoRARoutes/);
assert.match(editorSource, /h3-lora-routes-changed/);
assert.match(editorSource, /delete shot\.lora_route/);
assert.match(editorSource, /Incoming transition/);
assert.match(editorSource, /Final assembly crossfade frames/);
assert.match(editorSource, /field\("Source reference", sourceReference\)/);
assert.match(editorSource, /field\("Generated continuity", generatedContinuity\)/);
assert.match(editorSource, /field\("Lock source audio", lockSourceAudio\)/);
assert.match(editorSource, /applySceneAudioOverride/);
assert.match(editorSource, /Advanced visual context/);
assert.match(editorSource, /Context block 1 source/);
assert.match(editorSource, /same scene, separate window/);
assert.match(editorSource, /Composed total \/ split/);
assert.match(editorSource, /visualContextCompositions/);
assert.match(editorSource, /Visual context source/);
assert.match(editorSource, /Advanced audio context/);
assert.match(editorSource, /Advanced implementation/);
assert.match(editorSource, /applySceneTransitionPreset/);
assert.match(editorSource, /Boundary spatial proxy/);
assert.match(editorSource, /Low-grid 5\/6 proxy · Guide/);
assert.match(editorSource, /Latent 5\/6 proxy · AV/);
assert.match(editorSource, /context_spatial_proxy/);
assert.match(editorSource, /Guide · new shot/);
assert.match(editorSource, /Latent Guide · direct generated latent/);
assert.match(editorSource, /Detail Guide · color injection/);
assert.match(editorSource, /Masked AV · same shot/);
assert.match(editorSource, /Feathered AV · experimental dual-stream feather/);
assert.match(editorSource, /0 · new visual/);
assert.match(editorSource, /grid-template-columns:repeat\(4/);
assert.match(editorSource, /Hide advanced/);
assert.match(editorSource, /Show advanced/);
assert.doesNotMatch(editorSource, /Hide steps|Show steps/);
assert.match(editorSource, /h3_chain_scene_colors/);
assert.match(editorSource, /type = "color"/);
assert.match(editorSource, /minimax_h3_context_loop\.chain_plan_editor/);
assert.match(editorSource, /function folderOpenIcon\(\)/);
assert.match(editorSource, /createElementNS\(namespace, "svg"\)/);
assert.match(editorSource, /h3c-folder-icon/);
assert.match(editorSource, /minimax_h3_context_loop\/open-run-folder/);
assert.match(editorSource, /navigator\.clipboard\.writeText\(payload\.path\)/);
assert.match(editorSource, /plan_json_input/);
assert.doesNotMatch(editorSource, /field\("Default seconds"/);
assert.doesNotMatch(editorSource, /field\("Default steps"/);
assert.doesNotMatch(editorSource, /Uses JSON defaults/);
assert.match(editorSource, /External plan input connected/);
assert.match(editorSource, /non-empty upstream string controls execution/);
assert.match(editorSource, /onConnectionsChange/);
assert.match(editorSource, /setProjectAssetManagedWidget/);
assert.match(editorSource, /inputConnected\(node, "project_assets"\)/);
assert.match(editorSource, /item\.name === "run_name"/);
assert.match(editorSource, /item\.name === "generation_fingerprint"/);
assert.match(editorSource, /widget\._h3ProjectAssetOriginal/);
assert.match(editorSource, /style\.removeProperty\("display"\)/);
assert.doesNotMatch(editorSource, /h3_motion_context\.chain_plan_editor/);

console.log("H3 Chain Plan editor core: parsing, uint64 seeds, timing and edits pass");
