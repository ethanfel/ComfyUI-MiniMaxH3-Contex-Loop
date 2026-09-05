import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import {parsePlanJson, calculatePlanTiming} from "../web/h3_chain_plan_core.mjs";

function handler(text, name) {
    const match = text.match(new RegExp(`^    (?:async )?function ${name}\\([^]*?^    }$`, "m"));
    assert.ok(match, name);
    return match[0];
}
const tick = () => new Promise(resolve => setImmediate(resolve));
const blankPrompts = ["", [""], [], null, "  "];
for (const prompt of blankPrompts) {
    const plan = parsePlanJson(JSON.stringify({shots:[
        {id:"written", prompt:"Existing prompt"}, {id:"blank", prompt},
    ]}));
    const timing = calculatePlanTiming(plan);
    assert.equal(plan.shots.length, 2);
    assert.equal(timing.shots.length, 2, "validation must not hide the draft scene");
    assert.ok(timing.shots[1].deliveredFrames > 0);
}

for (const filename of [
    "h3_chain_scene_prompt_editor.js", "h3_chain_rich_scene_prompt_editor.js",
    "h3_chain_plan_studio.js",
]) {
    const source = fs.readFileSync(new URL(`../web/${filename}`, import.meta.url), "utf8");
    const studio = filename === "h3_chain_plan_studio.js";
    const name = studio ? "selectScene" : "navigate";
    const plan = {shots:[
        {id:"written", prompt:["Existing prompt"]},
        {id:"blank", prompt:[""]},
        {id:"other", prompt:["Another prompt"]},
    ]};
    let pending = [];
    let run = "run";
    const published = [];
    const state = {plan, planNode:{}, active:0, view:"scene", disposed:false};
    const context = vm.createContext({
        state, node:{}, console,
        planRunName:() => run, runName:() => run, optimizerBusy:() => false,
        flushPlanEffects(){}, flushPromptAnalysis(){},
        flushHistoryDraft:() => new Promise(resolve => pending.push(resolve)),
        persistView(){}, render(){}, renderPanel(){},
        renderSourceTimeline(){}, renderSourceAudioTimeline(){},
        updateTimelineSelection(){}, revealActiveTimelineScene(){},
        publishCompanionScene:(_node, _plan, index) => published.push(index),
        publishActiveScene:() => published.push(state.active),
    });
    vm.runInContext(handler(source, name), context);
    const select = index => studio ? context.selectScene(index) : context.navigate(0, index);
    // An older selection waiting for prompt-history IO must not pull BOTH
    // editors back to a written scene after the user chooses a blank one.
    select(2);
    select(1);
    pending[1]();
    await tick();
    assert.equal(state.active, 1, `${filename}: blank scene is selectable`);
    pending[0]();
    await tick();
    assert.equal(state.active, 1, `${filename}: delayed old navigation must not replace the blank scene`);
    assert.deepEqual(published, [1], "stale selection must not propagate to companions");
    assert.deepEqual(plan.shots[1].prompt, [""], "navigation must not fill the blank prompt");

    for (const prompt of blankPrompts) {
        pending = [];
        state.plan.shots[1].prompt = prompt;
        select(1);
        pending[0]();
        await tick();
        assert.equal(state.active, 1);
        assert.equal(state.plan.shots[1].prompt, prompt);
    }
    if (!studio) {
        pending = [];
        state.active = 0;
        context.navigate(1);
        context.navigate(1);
        pending[1](); pending[0]();
        await tick();
        assert.equal(state.active, 2, "rapid relative navigation advances twice");
    }

    // A timing/seed refresh can rebuild or reorder the Plan while history IO
    // runs. Follow the selected scene ID, without writing any prompt or seed.
    pending = [];
    select(1);
    state.plan = {shots:[plan.shots[1], plan.shots[0], plan.shots[2]]};
    pending[0]();
    await tick();
    assert.equal(state.active, 0, "selection follows its scene through reordering");
    state.plan = plan;
    state.active = 1;

    // Completion from the old project or a removed node is not navigation.
    pending = [];
    select(0);
    state.planNode = {};
    pending[0]();
    await tick();
    assert.equal(state.active, 1, `${filename}: ignore the old Plan`);
    pending = [];
    select(0);
    run = "other_run";
    pending[0]();
    await tick();
    assert.equal(state.active, 1, `${filename}: ignore the old Run`);
    pending = [];
    select(0);
    state.disposed = true;
    pending[0]();
    await tick();
    assert.equal(state.active, 1, `${filename}: ignore a disposed editor`);

    // Exercise the actual history flush, not just an artificial navigation
    // delay: consuming a draft while history is still loading leaves a window
    // in which the newer selection completes before the older one.
    state.disposed = false;
    let finishLoad;
    state.history = {
        pendingDraft:{key:"old", runName:run, shotId:"written", sceneId:"written", prompt:"Saved draft"},
        sceneKey:"old", loadPromise:new Promise(resolve => { finishLoad = resolve; }),
    };
    const saves = [];
    Object.assign(context, {
        window:{clearTimeout(){}}, clearTimeout(){}, renderHistory(){},
        historyRequest:async (_query, body) => {
            saves.push(body);
            return {history:{active_revision:"revision"}, revision:{id:"revision"}};
        },
    });
    vm.runInContext(handler(source, "flushHistoryDraft"), context);
    const previousPublications = published.length;
    select(2);
    select(1);
    await tick();
    assert.equal(state.active, 1);
    finishLoad({});
    await tick();
    assert.equal(state.active, 1, "actual delayed draft flush cannot bounce selection");
    assert.deepEqual(published.slice(previousPublications), [1]);
    assert.equal(saves.length, 1, "the original prompt draft still saves exactly once");
    assert.equal(saves[0].scene_id, "written");
    assert.equal(saves[0].prompt, "Saved draft");
}
console.log("Scene navigation preserves blank scenes and rejects stale async selections");
