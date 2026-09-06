#!/usr/bin/env node

import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import {setImmediate} from "node:timers/promises";
import {parsePlanJson, planToJson} from "../web/h3_chain_plan_core.mjs";
import {
    activeSceneFromOutput, applySceneReroll, resumeSelection,
} from "../web/h3_chain_cancel_reroll_core.mjs";

const source = fs.readFileSync(
    new URL("../web/h3_chain_cancel_reroll.js", import.meta.url), "utf8",
).replace(/^import[\s\S]*?;\n/gm, "");

// Execute the real extension event handlers and cancellation flow. Only the
// browser shell, transport and editor refresh are stubbed; no live job is run.
function harness(currentType, {enabled = true, nested = false,
                              planType = "MiniMaxH3ChainPlanModern"} = {}) {
    const calls = [];
    const listeners = new Map();
    const plan = {id: 1, type: planType, inputs: [], widgets: [
        {name: "run_name", value: "project"},
        {name: "plan_json", value: JSON.stringify({shots: [
            {id: "one", prompt: ["First."], seed: "1"},
            {id: "two", prompt: ["Second."], seed: "2"},
            {id: "three", prompt: ["Third."], seed: "3"},
        ]})},
    ]};
    const studio = {id: 2, type: "MiniMaxH3ChainPlanStudio", inputs: [{link: 1}]};
    const start = {id: 3, type: "MiniMaxH3ChainLoopStart", inputs: [{link: 2}],
        widgets: [{name: "start_clip", value: 1}, {name: "scene_range", value: "1:2"}]};
    const current = {id: 4, comfyClass: currentType, inputs: [{link: 3}]};
    const save = {id: 5, type: "MiniMaxH3ChainSegmentSave", inputs: []};
    const nodes = [plan, studio, start, current, save];
    const graph = {links: {1: {origin_id: 1}, 2: {origin_id: 2}, 3: {origin_id: 3}},
        getNodeById: id => nodes.find(node => node.id === id), setDirtyCanvas() {}};
    for (const node of nodes) node.graph = graph;
    let extension, setting;
    const app = {
        graph: nested ? {getNodeById: id => id === 7 ? {subgraph: graph} : null} : graph,
        extensionManager: {workflow: {activeWorkflow: {path: "running.json"}}},
        ui: {settings: {getSettingValue: () => enabled, addSetting: value => { setting = value; }}},
        registerExtension: value => { extension = value; },
        queuePrompt: async (...args) => { calls.push(["queue", ...args]); },
    };
    const fixture = {app, plan, start, current, graph, calls, checkpointReady: true};
    const api = {
        addEventListener: (name, callback) => listeners.set(name, callback),
        async fetchApi(path, options) {
            calls.push([path, options?.method ?? "GET"]);
            const body = path.endsWith("/cancel") ? {cancelled: true} : {
                checkpoints: [{scene: 1, ready: fixture.checkpointReady}],
            };
            return {ok: true, json: async () => body};
        },
    };
    const context = vm.createContext({
        app, api, URLSearchParams, parsePlanJson, planToJson,
        activeSceneFromOutput, applySceneReroll, resumeSelection,
        randomSceneSeed: () => "9007199254740993",
        refreshRestoredPlanEditors: node => { calls.push(["refresh", node.id]); },
        window: {setTimeout() { return 1; }, clearTimeout() {}},
    });
    vm.runInContext(source + `
        root = {hidden: true};
        actionButton = {disabled: false, lastElementChild: {textContent: ""}};
        status = {textContent: "", className: ""};
        globalThis.control = {root, actionButton, status};
        globalThis.reroll = cancelAndReroll;
    `, context);
    extension.init();
    extension.setup();
    fixture.control = context.control;
    fixture.reroll = context.reroll;
    fixture.setEnabled = value => setting.onChange(value);
    fixture.emit = (name, detail) => listeners.get(name)({detail});
    fixture.displayId = id => nested ? `7:${id}` : String(id);
    fixture.scene = () => fixture.emit("executed", {
        node: "4.0.0.CurrentScene", // Backend expansion id; route by display_node.
        display_node: fixture.displayId(4), prompt_id: "prompt-one",
        output: {h3_chain_active_scene: [{run_name: "project", clip_index: 2,
            clip_count: 3, end_clip: 2, shot_id: "two", seed: "2"}]},
    });
    return fixture;
}

for (const currentType of ["MiniMaxH3ChainCurrent", "MiniMaxH3CurrentTaggedReferenceScene"]) {
    for (const nested of [false, true]) {
        for (const planType of ["MiniMaxH3ChainPlan", "MiniMaxH3ChainPlanModern"]) {
            const h = harness(currentType, {nested, planType});
            h.scene();
            assert.equal(h.control.root.hidden, false, `${currentType} must show the control`);
            assert.match(h.control.actionButton.lastElementChild.textContent, /scene 2/);
            h.emit("executed", {display_node: h.displayId(4), prompt_id: "prompt-one",
                output: {other_ui: []}});
            assert.equal(h.control.root.hidden, false, "other compact-node outputs must not hide it");
            const original = JSON.parse(h.plan.widgets[1].value);
            const pending = h.reroll();
            await setImmediate();
            assert.deepEqual(h.calls.filter(call => call[1] === "POST"),
                [["/api/jobs/prompt-one/cancel", "POST"]]);
            assert.equal(h.calls.some(call => call[0] === "queue"), false,
                "never requeue before interruption is confirmed");
            h.emit("execution_interrupted", {prompt_id: "prompt-one"});
            await pending;
            const updated = JSON.parse(h.plan.widgets[1].value);
            assert.deepEqual(updated.shots[0], original.shots[0]);
            assert.deepEqual(updated.shots[2], original.shots[2]);
            assert.deepEqual(updated.shots[1], {...original.shots[1], seed: "9007199254740993"});
            assert.equal(h.start.widgets[0].value, 2);
            assert.equal(h.start.widgets[1].value, "2");
            assert.deepEqual(h.calls.filter(call => call[0] === "queue"), [["queue", 0, 1]]);
            assert.deepEqual(h.calls.filter(call => call[0] === "refresh"), [["refresh", 1]]);
        }
    }
    const disabled = harness(currentType, {enabled: false});
    disabled.scene();
    assert.equal(disabled.control.root.hidden, true);
    await disabled.reroll();
    assert.deepEqual(disabled.calls, []);
    disabled.setEnabled(true);
    assert.equal(disabled.control.root.hidden, false);

    for (const mismatch of ["workflow", "run", "node", "checkpoint"]) {
        const h = harness(currentType);
        h.scene();
        if (mismatch === "workflow") h.app.extensionManager.workflow.activeWorkflow.path = "other.json";
        if (mismatch === "run") h.plan.widgets[0].value = "other-project";
        if (mismatch === "node") h.current.comfyClass = "UnrelatedNode";
        if (mismatch === "checkpoint") h.checkpointReady = false;
        const original = h.plan.widgets[1].value;
        await h.reroll();
        assert.equal(h.calls.some(call => call[1] === "POST" || call[0] === "queue"), false,
            `${mismatch} mismatch must block cancellation and requeue`);
        assert.equal(h.plan.widgets[1].value, original);
        assert.match(h.control.status.className, /h3cr-error/);
    }

    for (const event of ["execution_success", "execution_error", "execution_interrupted", "executing"]) {
        const h = harness(currentType);
        h.scene();
        const detail = {prompt_id: "other-prompt", display_node: h.displayId(5)};
        h.emit(event, detail);
        assert.equal(h.control.root.hidden, false, "unrelated prompts cannot hide the control");
        h.emit(event, {...detail, prompt_id: "prompt-one"});
        assert.equal(h.control.root.hidden, true, "save or terminal event hides the control");
    }

    const race = harness(currentType);
    race.scene();
    const original = race.plan.widgets[1].value;
    const pending = race.reroll();
    await setImmediate();
    race.emit("execution_success", {prompt_id: "prompt-one"});
    await pending;
    assert.equal(race.calls.some(call => call[0] === "queue"), false);
    assert.equal(race.plan.widgets[1].value, original);
    assert.match(race.control.status.textContent, /completed before cancellation/);

    const switched = harness(currentType);
    switched.scene();
    const switching = switched.reroll();
    await setImmediate();
    switched.app.extensionManager.workflow.activeWorkflow.path = "other.json";
    switched.emit("execution_interrupted", {prompt_id: "prompt-one"});
    await switching;
    assert.equal(switched.calls.some(call => call[0] === "queue"), false,
        "switching tabs during cancellation must not queue the wrong graph");
    assert.match(switched.control.status.textContent, /Return to the running H3 workflow/);
}

const unrelated = harness("UnrelatedNode");
unrelated.scene();
assert.equal(unrelated.control.root.hidden, true);
await unrelated.reroll();
assert.deepEqual(unrelated.calls, []);

console.log("H3 cancel-and-reroll events: legacy/compact nodes, nested graphs, settings, targeted cancellation and safety guards pass");
