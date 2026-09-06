import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import {
    MAX_SHOTS, calculatePlanTiming, duplicateShot, parsePlanJson, planToJson,
    promptTextToLines, promptValueToText, renamePlanShot, sceneVisualContextSource,
} from "../web/h3_chain_plan_core.mjs";

const options = {contextLength:22, videoBlendFrames:5, anchorMode:"head",
    defaultDurationSeconds:5, defaultSteps:20};
const productionPlans = [];
const makePlan = (spelling = "id", count = 10) => ({shots:Array.from({length:count}, (_, i) => ({
    id:`scene_${i + 1}`, prompt:[`Prompt ${i + 1}`], length:90,
    ...(i && spelling !== "implicit" ? {visual_context_source:
        spelling === "id" ? `scene_${i}` : spelling === "number" ? i
            : spelling === "numeric string" ? String(i) : spelling} : {}),
}))});
function valid(plan, name) {
    assert.deepEqual(calculatePlanTiming(plan, options).errors, [], name);
    productionPlans.push({name, plan:structuredClone(plan)});
}

for (const spelling of ["id", "number", "numeric string", "implicit", "previous", "immediate"]) {
    for (const index of [0, 5, 9]) {
        const plan = makePlan(spelling);
        valid(plan, `${spelling} before insertion`);
        const original = [...plan.shots];
        const duplicate = duplicateShot(plan.shots, index);
        assert.equal(plan.shots[index + 1], duplicate);
        assert.deepEqual(duplicate.prompt, [`Prompt ${index + 1}`]);
        assert.notEqual(duplicate.prompt, original[index].prompt, "prompt arrays are deep copied");
        original.forEach((shot, offset) => {
            assert.equal(plan.shots[offset + (offset > index ? 1 : 0)], shot);
            assert.deepEqual(shot.prompt, [`Prompt ${offset + 1}`]);
            assert.equal(shot.id, `scene_${offset + 1}`);
        });
        assert.equal(sceneVisualContextSource(plan, index + 2), index + 1);
        if (index < original.length - 1) assert.equal(sceneVisualContextSource(plan, index + 3), index + 2);
        valid(plan, `${spelling} duplicate at ${index + 1}`);
        duplicateShot(plan.shots, index + 1);
        assert.equal(new Set(plan.shots.map(shot => shot.id)).size, plan.shots.length);
        valid(plan, `${spelling} repeated duplicate at ${index + 2}`);
    }
}

// Explicit single-tail blocks behave like a normal previous-scene source.
const blocks = makePlan();
for (let index = 1; index < blocks.shots.length; index++) {
    const shot = blocks.shots[index];
    shot.visual_context_blocks = [{source:shot.visual_context_source, frames:22}];
    shot.video_blend_frames = 0;
    delete shot.visual_context_source;
}
valid(blocks, "single blocks before insertion");
const blockCopy = duplicateShot(blocks.shots, 5);
assert.equal(blockCopy.visual_context_blocks[0].source, "scene_6");
assert.equal(blocks.shots[7].visual_context_blocks[0].source, blockCopy.id);
valid(blocks, "single blocks after insertion");

// Deliberate older sources and composed contexts keep their original clips.
for (const patch of [
    {visual_context_source:"scene_2"},
    {visual_context_source:"scene_5", visual_context_lead_source:"scene_2", visual_context_lead_frames:5},
    {visual_context_blocks:[{source:"scene_2", frames:5}, {source:"scene_5", frames:17}]},
]) {
    const plan = makePlan();
    delete plan.shots[5].visual_context_source;
    Object.assign(plan.shots[5], patch, {video_blend_frames:0});
    valid(plan, "authored context before insertion");
    const copied = duplicateShot(plan.shots, 5);
    for (const [key, value] of Object.entries(patch)) assert.deepEqual(copied[key], value);
    valid(plan, "authored context after insertion");
}

// Positional references to later original scenes shift, including references
// nested inside a composition. Their authored frame windows do not change.
const positional = makePlan();
Object.assign(positional.shots[9], {
    visual_context_source:8, visual_context_start_frame:0,
    visual_context_lead_source:"7", visual_context_lead_frames:5,
    audio_context_source:8, audio_context_start_frame:12,
    audio_context_lead_source:"7", audio_context_lead_start_frame:3,
});
Object.assign(positional.shots[8], {
    visual_context_blocks:[{source:7, frames:5, start_frame:0}, {source:"8", frames:17}],
});
duplicateShot(positional.shots, 5);
assert.equal(positional.shots[10].visual_context_source, 9);
assert.equal(positional.shots[10].visual_context_lead_source, "8");
assert.equal(positional.shots[10].audio_context_source, 9);
assert.equal(positional.shots[10].audio_context_lead_source, "8");
assert.equal(positional.shots[10].visual_context_start_frame, 0);
assert.equal(positional.shots[10].audio_context_start_frame, 12);
assert.equal(positional.shots[10].audio_context_lead_start_frame, 3);
assert.deepEqual(positional.shots[9].visual_context_blocks,
    [{source:8, frames:5, start_frame:0}, {source:"9", frames:17}]);

for (const patch of [
    {visual_context_source:"scene_5", visual_context_start_frame:0},
    {visual_context_blocks:[{source:"scene_5", frames:22, start_frame:0}]},
    {audio_context_source:"scene_5", audio_context_start_frame:0},
]) {
    const plan = makePlan();
    Object.assign(plan.shots[5], patch);
    const copied = duplicateShot(plan.shots, 5);
    for (const [key, value] of Object.entries(patch)) assert.deepEqual(copied[key], value,
        "an explicitly selected frame window must keep its source clip");
}

const audio = makePlan();
audio.shots[5].audio_context_source = "scene_5";
audio.shots[6].audio_context_source = "scene_6";
const audioCopy = duplicateShot(audio.shots, 5);
assert.equal(audioCopy.audio_context_source, "scene_6");
assert.equal(audio.shots[7].audio_context_source, audioCopy.id);

const legacy = makePlan("number");
legacy.shots.forEach(shot => { delete shot.id; });
duplicateShot(legacy.shots, 5);
assert.equal(legacy.shots[5].id, "clip_0006");
assert.equal(legacy.shots[7].id, "clip_0007", "legacy identities survive insertion");
valid(legacy, "legacy implicit IDs after duplication");
const numericIds = makePlan();
numericIds.shots[5].id = "123";
numericIds.shots[6].visual_context_source = 6;
valid(numericIds, "numeric scene ID before duplication");
const numericCopy = duplicateShot(numericIds.shots, 5);
assert.equal(numericCopy.visual_context_source, 6, "numeric IDs must not be interpreted as source positions");
valid(numericIds, "numeric scene ID after duplication");

const normalizedIds = makePlan();
normalizedIds.shots[5].id = "scene 6";
valid(normalizedIds, "normalized scene ID before duplication");
const normalizedCopy = duplicateShot(normalizedIds.shots, 5);
assert.equal(normalizedCopy.visual_context_source, "scene_6");
valid(normalizedIds, "normalized scene ID after duplication");

const independent = makePlan();
independent.shots[5].context_length = 0;
independent.shots[5].audio_context_length = 0;
independent.chapters = [{id:"chapter_two", title:"Chapter 2", start_scene_id:"scene_7"}];
const independentCopy = duplicateShot(independent.shots, 5);
assert.equal(independentCopy.context_length, 0);
assert.equal(independentCopy.audio_context_length, 0);
assert.equal(independent.chapters[0].start_scene_id, "scene_7");
valid(independent, "independent scene and chapter identity after duplication");

const longIds = [{id:"x".repeat(96), prompt:["Original"]}];
duplicateShot(longIds, 0); duplicateShot(longIds, 0);
assert.equal(new Set(longIds.map(shot => shot.id)).size, 3);
assert.ok(longIds.every(shot => shot.id.length <= 96));
for (const index of [-1, 99, 1.5]) {
    const before = JSON.stringify(longIds);
    assert.throws(() => duplicateShot(longIds, index), /outside the Plan/);
    assert.equal(JSON.stringify(longIds), before);
}

// Execute the real Studio button, delegated-prompt merge and write path.
// This reproduces both the reported overwrite and a source prompt edited
// since Studio's latest polling snapshot, without touching a live workflow.
const studio = fs.readFileSync(new URL("../web/h3_chain_plan_studio.js", import.meta.url), "utf8");
const functions = ["preserveDelegatedPrompts", "writePlan"].map(name => {
    const code = studio.match(new RegExp(`^    function ${name}\\([^]*?^    }`, "m"))?.[0];
    assert.ok(code, name); return code;
}).join("\n");
const buttonCode = studio.match(/const duplicate = button\("Duplicate", "Duplicate the selected scene", async \(\) => \{[^]*?^        \}\);/m)?.[0];
assert.ok(buttonCode);
const renameCode = studio.match(/id\.addEventListener\("change", \(\) => \{[^]*?^        \}\);/m)?.[0];
assert.ok(renameCode);
for (const linked of [false, true]) for (const implicitIds of [false, true]) {
    const local = makePlan("implicit"), live = structuredClone(local);
    if (implicitIds) for (const plan of [local, live]) plan.shots.forEach(shot => { delete shot.id; });
    live.shots[5].prompt = ["Latest source prompt"];
    const state = {plan:local, active:5, promptEditors:linked ? [{}] : [],
        planWidget:{value:JSON.stringify(live)}, planNode:{}, activeChapterId:"chapter", planNotifyTimer:null};
    const published = [], callbacks = [];
    const context = vm.createContext({state, node:{}, MAX_SHOTS, duplicateShot,
        parsePlanJson, planToJson, promptTextToLines, promptValueToText,
        button:(_label, _title, action) => action, flushHistoryDraft:async () => {},
        widget:() => null, setTimeout:action => { callbacks.push(action); return 1; }, clearTimeout() {},
        persistView() {}, renderShell() {}, publishActiveScene() {}, scheduleEditorialSave() {}, renderStatus() {}, dirty() {},
        publishCompanionPrompt:(_node, _planNode, index, prompt) => published.push({index, prompt}),
    });
    await vm.runInContext(`${functions}\n${buttonCode}\nduplicate();`, context);
    callbacks.forEach(action => action());
    const expected = linked ? "Latest source prompt" : "Prompt 6";
    const saved = JSON.parse(state.planWidget.value);
    assert.deepEqual(saved.shots[6].prompt, [expected]);
    assert.deepEqual(saved.shots[5].prompt, [expected]);
    assert.deepEqual(saved.shots[7].prompt, ["Prompt 7"]);
    assert.deepEqual(saved.shots[8].prompt, ["Prompt 8"]);
    assert.equal(state.active, 6);
    assert.equal(state.activeChapterId, "");
    assert.deepEqual(published, [{index:6, prompt:expected}]);

    // Removing the unsafe positional fallback must not regress renames: pull
    // a recent delegated edit before replacing the original scene ID.
    const changed = JSON.parse(state.planWidget.value);
    changed.shots[6].prompt = ["Latest before rename"];
    state.planWidget.value = JSON.stringify(changed);
    let rename;
    Object.assign(context, {shot:state.plan.shots[6], renamePlanShot,
        id:{value:"renamed_copy", setCustomValidity() {}, addEventListener:(_type, action) => { rename = action; }},
        remapStudioEditorialSceneId() {},
    });
    vm.runInContext(renameCode, context);
    rename();
    const renamed = JSON.parse(state.planWidget.value);
    assert.equal(renamed.shots[6].id, "renamed_copy");
    assert.deepEqual(renamed.shots[6].prompt, [linked ? "Latest before rename" : expected]);
    assert.deepEqual(renamed.shots[7].prompt, ["Prompt 7"]);
}

if (process.argv.includes("--plans")) console.log(JSON.stringify(productionPlans));
else console.log("Scene duplication: context remapping, stable identities, source prompt freshness and real Studio save path pass");
