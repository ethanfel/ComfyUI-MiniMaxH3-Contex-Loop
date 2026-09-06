import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import * as core from "../web/h3_checkpoint_manager_core.mjs";

const a = "a".repeat(32), b = "b".repeat(32), c = "c".repeat(32), d = "d".repeat(32);
const payload = {
    revisions:[
        {scene:1, revision:a, active:true, ready:true},
        {scene:2, revision:b, active:true, ready:true, parent:{scene:1, revision:a}},
        {scene:2, revision:c, active:false, ready:true, parent:{scene:1, revision:a}},
        {scene:3, revision:d, active:true, ready:true, parent:{scene:2, revision:b}},
    ],
    scenes:[1, 2, 3].map(scene => ({scene})),
    branches:[
        {label:"Active branch", active:true, path:[{scene:1, revision:a}, {scene:2, revision:b}, {scene:3, revision:d}]},
        {label:"Alternate", active:false, path:[{scene:1, revision:a}, {scene:2, revision:c}]},
    ],
    summary:{scene_count:3, revision_count:4, branch_count:2, bytes:0},
};
const local = core.checkpointLocalSelectionJson(payload, "demo", payload.revisions[2], {start:1, end:3});
assert.equal(core.checkpointLocalSelection(local).output_mode, "workflow_local");
assert.equal(core.checkpointOutputSelectionJson(local, payload, "other", payload.revisions[3]), local);
assert.equal(core.checkpointLocalSelection(""), null);
assert.equal(core.checkpointLocalSelection("invalid"), null);
assert.equal(core.checkpointLocalSelection(core.checkpointSelectionJson(payload, "demo", payload.revisions[1])), null);
assert.throws(() => core.checkpointLocalSelectionJson({...payload, revisions:payload.revisions.map(
    item => item.scene === 1 ? {...item, ready:false} : item)}, "demo", payload.revisions[2]), /available/);
assert.throws(() => core.checkpointLocalSelectionJson(payload, "", payload.revisions[2]), /complete/);
const chapterPin = core.checkpointLocalSelectionJson(payload, "demo", payload.revisions[3], {start:3, end:3});
const switchedPrefix = structuredClone(payload);
switchedPrefix.revisions[1].active = false;
switchedPrefix.revisions[2].active = true;
assert.equal(core.checkpointOutputSelectionJson(chapterPin, switchedPrefix, "demo", payload.revisions[3], {start:3, end:3}), chapterPin,
    "previous chapters are pinned too, not rebuilt from new project pointers");
assert.equal(JSON.parse(chapterPin).lineage[1].revision, b);
const chapterOnlyPin = core.checkpointLocalSelectionJson({
    ...payload, revisions:payload.revisions.map(item => item.scene < 3 ? {...item, ready:false} : item),
}, "demo", payload.revisions[3], {start:3, end:3}, "chapter");
assert.equal(JSON.parse(chapterOnlyPin).output_scope, "chapter");
assert.deepEqual(JSON.parse(chapterOnlyPin).lineage, JSON.parse(chapterPin).lineage,
    "prior immutable timing metadata remains pinned, but its media is not required");
assert.equal(core.checkpointOutputSelectionJson(chapterOnlyPin, switchedPrefix, "demo", payload.revisions[2]), chapterOnlyPin);

// The whole extension is mounted with a lightweight DOM, so these exercise
// the real handlers, async refresh and serialized widget (not extracted mocks).
class Element {
    constructor(tag) {
        this.tag = tag; this.children = []; this.listeners = {}; this.dataset = {};
        this.style = {setProperty(){}}; this.className = ""; this.textContent = "";
        this.classList = {
            add:(name) => { this.className += ` ${name}`; },
            toggle:(name, enabled) => {
                this.className = this.className.split(" ").filter(item => item !== name).join(" ");
                if (enabled) this.className += ` ${name}`;
            },
        };
    }
    append(...items) { this.children.push(...items); }
    replaceChildren(...items) { this.children = items; }
    addEventListener(name, callback) { this.listeners[name] = callback; }
    setAttribute(name, value) { this[name] = value; }
    removeAttribute(name) { delete this[name]; }
    load() {}
    pause() {}
    click() { assert.ok(!this.disabled, `${this.textContent} is disabled`); this.listeners.click(); }
}
const source = fs.readFileSync(new URL("../web/h3_chain_checkpoint_manager.js", import.meta.url), "utf8")
    .replace(/^import\s[\s\S]*?from\s+"[^"]+";\n/gm, "");
let currentGraph = structuredClone(payload), runs = ["demo", "other"], failRequests = false;
let confirms = true, mutations = 0, dirty = 0;
let attachResponse = null;
let extension;
const requests = [];
const context = vm.createContext({
    ...core, URLSearchParams, console,
    document:{head:new Element("head"), getElementById:() => null, createElement:tag => new Element(tag)},
    app:{registerExtension(value){ extension = value; }, graph:{setDirtyCanvas(){}}},
    api:{apiURL:path => path, fetchApi:async (path, options={}) => {
        requests.push({path, options});
        if (failRequests) throw new Error("offline");
        let data;
        if (path.endsWith("/runs")) data = {runs:runs.map(run_name => ({run_name, checkpoint_count:3}))};
        else if (path.includes("/checkpoints?")) data = structuredClone(currentGraph);
        else if (path.endsWith("/delete-preview")) data = {allowed:false, blockers:["test"]};
        else if (path.endsWith("/attribute") && attachResponse) {
            mutations++;
            const request = JSON.parse(options.body);
            assert.equal(request.parent_revision, b);
            assert.equal(request.candidate_revision, d);
            const alias = {...currentGraph.revisions.find(item => item.revision === d),
                revision:attachResponse.revision, parent:{scene:2, revision:b}};
            currentGraph.revisions.push(alias);
            currentGraph.branches[0].path.push({scene:3, revision:alias.revision});
            delete currentGraph.branches[0].attribution_slot;
            data = attachResponse;
        }
        else { mutations++; throw new Error(`Unexpected request ${path}`); }
        return {ok:true, json:async () => data};
    }},
    window:{setTimeout:callback => callback(), confirm:() => confirms},
    projectMutationOptions:(_node, _run, options) => {
        if (attachResponse) return options;
        mutations++; throw new Error("Local output attempted project mutation");
    },
    promptCompanionSync:{},
});
vm.runInContext(source, context);
class NodeType {}
await extension.beforeRegisterNodeDef(NodeType, {name:"MiniMaxH3ChainCheckpointManager"});
const settle = async () => { for (let i = 0; i < 12; i++) await new Promise(setImmediate); };
function makeNode(saved="", properties={}) {
    const node = {properties:{h3_checkpoint_manager_run:"demo", ...properties},
        widgets:[{name:"selection_json", value:saved, callback:() => dirty++}],
        inputs:[], graph:{setDirtyCanvas:() => dirty++}, setSize(){},
        addDOMWidget(_name, _type, root) { this.root = root; return {}; },
    };
    context.mount(node);
    return node;
}
function elements(node) {
    const flatten = item => [item, ...item.children.flatMap(flatten)];
    return flatten(node.root);
}
const byText = (node, text) => elements(node).find(item => item.tag === "button" && item.textContent === text);
const byClass = (node, name) => elements(node).find(item => item.className.split(" ").includes(name));
const select = (node, scene, revision) => byText(node, `S${scene} · ${revision.slice(0, 8)}`).click();
const value = node => node.widgets[0].value;

const scoped = makeNode(chapterOnlyPin);
await settle();
assert.equal(byClass(scoped, "h3cm-output-scope").value, "chapter");
select(scoped, 2, c);
await settle();
const scopeControl = byClass(scoped, "h3cm-output-scope");
scopeControl.value = "project"; scopeControl.listeners.change();
assert.equal(JSON.parse(value(scoped)).lineage.at(-1).revision, d,
    "explicit scope changes retain the pinned tip, not the browsed revision");
scopeControl.value = "chapter"; scopeControl.listeners.change();
assert.match(byClass(scoped, "h3cm-output-summary").textContent, /chapter only, scenes 3–3/);
assert.equal(mutations, 0);

const first = makeNode(), second = makeNode();
await settle();
assert.equal(JSON.parse(value(first)).lineage.at(-1).revision, d, "legacy default still follows selection");
select(first, 2, c);
await settle();
byText(first, "Use branch locally").click();
const pin = value(first), otherBefore = value(second);
assert.equal(pin, local);
assert.ok(elements(first).some(item => item.textContent === "local output"));
select(first, 3, d);
await settle();
assert.equal(value(first), pin, "browsing does not move pinned output");
assert.equal(value(second), otherBefore, "other manager unaffected");
assert.equal(mutations, 0);
assert.ok(dirty > 0, "widget changes are serialized and mark the workflow dirty");
const connectedPlan = {type:"MiniMaxH3ChainPlan", widgets:[
    {name:"run_name", value:"other"}, {name:"plan_json", value:"unchanged Plan"},
]};
first.inputs = [{link:1}];
first.graph.links = {1:{origin_id:99}};
first.graph.getNodeById = () => connectedPlan;
first.onConnectionsChange();
await settle();
assert.equal(value(first), pin, "connecting a Plan from another Run must not move the local output");
assert.equal(connectedPlan.widgets[1].value, "unchanged Plan");

currentGraph.revisions[1].active = false;
currentGraph.revisions[2].active = true;
first._h3CheckpointManagerRefresh();
await settle();
assert.equal(value(first), pin, "project-wide active changes do not move local pin");
const reopened = makeNode(pin, {h3_checkpoint_manager_scene:3, h3_checkpoint_manager_revision:d});
await settle();
assert.equal(value(reopened), pin, "shorter pinned branch survives startup's deepest-tip preference");
assert.match(byClass(reopened, "h3cm-output-summary").textContent, /through scene 2 \/ cccccccc/);
// ComfyUI reconfiguration replaces the saved widget value; it remains the
// sole pin authority even when an old browse selection is still in memory.
reopened.widgets[0].value = core.checkpointLocalSelectionJson(payload, "demo", payload.revisions[0], {start:1, end:3});
const newPin = value(reopened);
reopened._h3CheckpointManagerRefresh();
await settle();
assert.equal(value(reopened), newPin);

currentGraph.revisions = currentGraph.revisions.filter(item => item.revision !== c);
first._h3CheckpointManagerRefresh();
await settle();
assert.equal(value(first), pin);
assert.match(byClass(first, "h3cm-output-summary").textContent, /unavailable.*no fallback/);
runs = ["other"];
first._h3CheckpointManagerRefresh();
await settle();
assert.equal(value(first), pin);
assert.equal(byClass(first, "h3cm-run-select").value, "demo", "missing pinned run is not replaced by another run");
failRequests = true;
first._h3CheckpointManagerRefresh();
await settle();
assert.equal(value(first), pin, "transient network errors retain pin");
failRequests = false; runs = ["demo", "other"]; currentGraph = structuredClone(payload);
first._h3CheckpointManagerRefresh();
await settle();
const runSelect = byClass(first, "h3cm-run-select");
confirms = false;
runSelect.value = "other"; runSelect.listeners.change();
assert.equal(runSelect.value, "demo");
assert.equal(value(first), pin);
confirms = true;
runSelect.value = "other"; runSelect.listeners.change();
await settle();
assert.equal(core.checkpointLocalSelection(value(first)), null);
assert.equal(JSON.parse(value(first)).run_name, "other");

select(second, 2, c); await settle();
byText(second, "Use branch locally").click();
select(second, 3, d); await settle();
byText(second, "Follow browsing").click();
assert.equal(core.checkpointLocalSelection(value(second)), null);
assert.equal(JSON.parse(value(second)).lineage.at(-1).revision, d);
assert.equal(mutations, 0, "local use, release, browsing and reload never call project mutation APIs");
assert.ok(requests.every(({path, options}) => !options.method || path.endsWith("/delete-preview")));
console.log("Checkpoint local output: real mounted UI, isolation, pin persistence, missing runs/takes, refresh and release pass");

// ComfyUI mounts nodes before applying the saved widget values. Unpinned
// chapter output must be restored too, not overwritten by the mounted default.
const restoredScope = makeNode();
await settle();
restoredScope.widgets[0].value = core.checkpointSelectionJson(
    payload, "demo", payload.revisions[2], {start:1, end:3}, "chapter");
restoredScope.properties.h3_checkpoint_manager_scene = 2;
restoredScope.properties.h3_checkpoint_manager_revision = c;
NodeType.prototype.onConfigure.call(restoredScope);
await settle();
assert.equal(byClass(restoredScope, "h3cm-output-scope").value, "chapter",
    "un-pinned saved chapter scope must hydrate the mounted selector");
assert.equal(JSON.parse(value(restoredScope)).output_scope, "chapter");
assert.equal(JSON.parse(value(restoredScope)).lineage.at(-1).revision, c);

// A late widget restore must not queue whole-project output while the visible
// selector still says chapter. Check both API and saved-workflow serialization.
const staleScope = core.checkpointSelectionJson(payload, "demo", payload.revisions[2]);
restoredScope.widgets[0].value = staleScope;
assert.equal(byClass(restoredScope, "h3cm-output-scope").value, "chapter");
assert.equal(JSON.parse(await restoredScope.widgets[0].serializeValue()).output_scope, "chapter");
restoredScope.widgets[0].value = staleScope;
const savedScope = {widgets_values:[staleScope], widgets_values_named:{selection_json:staleScope}, properties:{}};
restoredScope.onSerialize(savedScope);
assert.equal(JSON.parse(savedScope.widgets_values[0]).output_scope, "chapter");
assert.equal(JSON.parse(savedScope.widgets_values_named.selection_json).output_scope, "chapter");
assert.equal(savedScope.properties.h3_checkpoint_manager_output_scope, "chapter");
const emptyScope = makeNode("", {h3_checkpoint_manager_output_scope:"chapter"});
await settle();
assert.equal(byClass(emptyScope, "h3cm-output-scope").value, "chapter",
    "scope survives saving while no checkpoint lineage is available");
// Replacing widgets during reconfiguration must not leave handlers writing
// into the old closed-over widget instead of the one ComfyUI queues.
const detachedWidget = restoredScope.widgets[0];
restoredScope.widgets[0] = {name:"selection_json", value:staleScope};
restoredScope.properties.h3_checkpoint_manager_output_scope = "project";
NodeType.prototype.onConfigure.call(restoredScope);
await settle();
const reboundScope = byClass(restoredScope, "h3cm-output-scope");
assert.equal(reboundScope.value, "project");
reboundScope.value = "chapter";
reboundScope.listeners.change();
assert.equal(JSON.parse(await restoredScope.widgets[0].serializeValue()).output_scope, "chapter");
assert.notEqual(restoredScope.widgets[0], detachedWidget);
const malformed = '{"output_scope":"unknown","lineage":[]}';
restoredScope.widgets[0].value = malformed;
assert.equal(await restoredScope.widgets[0].serializeValue(), malformed, "do not hide invalid selection data");
console.log("Checkpoint scope: configure, API serialization, workflow save and empty selection pass");

// Follow the actual candidate card -> attach -> refreshed alias -> queued
// output path. Earlier chapters remain timing-only when scope is chapter.
currentGraph = structuredClone(payload);
currentGraph.editorial = {chapters:[
    {id:"one", title:"Chapter 1", start_scene:1},
    {id:"two", title:"Chapter 2", start_scene:2},
]};
currentGraph.revisions[3].parent = {scene:2, revision:c};
currentGraph.revisions[3].active = false;
currentGraph.branches[0].path.pop();
currentGraph.branches[0].attribution_slot = {
    scene:3, parent_scene:2, parent_revision:b, candidates:[{scene:3, revision:d}],
};
currentGraph.branches[1].path.push({scene:3, revision:d});
const attaching = makeNode(core.checkpointSelectionJson(
    currentGraph, "demo", currentGraph.revisions[1], {start:2, end:3}, "chapter"));
await settle();
byText(attaching, "S3 · reuse saved clip").click();
assert.equal(byClass(attaching, "h3cm-output-scope").value, "chapter");
attachResponse = {scene:3, revision:"e".repeat(32), message:"Attached"};
byText(attaching, "Attach selected candidate").click();
await settle();
const attachedOutput = JSON.parse(await attaching.widgets[0].serializeValue());
assert.equal(attachedOutput.output_scope, "chapter");
assert.equal(attachedOutput.scope_start_scene, 2);
assert.equal(attachedOutput.lineage.at(-1).revision, attachResponse.revision);
assert.equal(mutations, 1, "only explicit attachment writes; no automatic project activation");
console.log("Checkpoint attachment: candidate -> alias -> chapter-only API output passes");
