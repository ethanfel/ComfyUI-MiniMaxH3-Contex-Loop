import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import {
    parsePlanJson, planToJson, normalizeChapterResolution, orderedChapters, safeShotId,
} from "../web/h3_chain_plan_core.mjs";

const input = {
    shots:[{id:"one", prompt:"First"}, {id:"two", prompt:"Next"}],
    chapters:[{id:"opening", title:"Opening", start_scene_id:"one", text:"Notes"},
        {id:"sequel", title:"Sequel", start_scene_id:"two", text:"", resolution:{width:128, height:96}}],
};
const plan = parsePlanJson(JSON.stringify(input));
assert.equal(plan.chapters[0].resolution, undefined, "old chapter markers inherit without new serialized defaults");
assert.deepEqual(parsePlanJson(planToJson(plan)).chapters[1].resolution, {width:128, height:96});
for (const value of ["128x96", {}, {width:65, height:64}, {width:64}, {width:32, height:0},
    {width:true, height:64}, {width:64, height:64, extra:true}, {width:16416, height:64}]) {
    assert.throws(() => normalizeChapterResolution(value));
    assert.throws(() => parsePlanJson(JSON.stringify({...input, chapters:[{...input.chapters[0], resolution:value}]})));
}
assert.equal(normalizeChapterResolution(null), null);

// Exercise the actual chapter-menu change handlers, not just schema helpers.
const source = fs.readFileSync(new URL("../web/h3_chain_plan_studio.js", import.meta.url), "utf8");
const render = source.match(/^    function renderChapterPanel\([^]*?^    }$/m)?.[0];
assert.ok(render);
function element(tag, className="", textContent="") {
    return {tag, className, textContent, children:[], listeners:{}, value:"", disabled:false,
        append(...children) { this.children.push(...children); },
        addEventListener(name, handler) { this.listeners[name] = handler; },
    };
}
const fields = {};
let writes = 0;
const state = {plan, activeChapterId:"sequel"};
const context = vm.createContext({
    state, node:{}, orderedChapters, safeShotId, normalizeChapterResolution, element,
    widget:(_node, key) => ({value:key === "width" ? 64 : 96}),
    field:(label, control) => { fields[label] = control; return control; },
    button:() => element("button"), writePlan:() => { writes++; },
    renderTimeline(){}, renderShell(){}, renderScenePanel(){}, confirm:() => false,
});
vm.runInContext(render, context);
const panel = context.renderChapterPanel();
assert.equal(fields.Resolution.value, "custom");
assert.equal(fields.Width.value, "128");
assert.equal(fields.Height.value, "96");
fields.Width.value = "192";
fields.Width.listeners.change();
assert.equal(state.plan.chapters[1].resolution.width, 192);
assert.equal(writes, 1);
fields.Height.value = "99";
fields.Height.listeners.change();
assert.equal(state.plan.chapters[1].resolution.height, 96, "invalid edits do not corrupt the Plan");
assert.equal(writes, 1);
assert.ok(panel.children.some(child => child.textContent.includes("32")));
fields.Resolution.value = "inherit";
fields.Resolution.listeners.change();
assert.equal(state.plan.chapters[1].resolution, undefined);
assert.equal(fields.Width.disabled, true);
assert.equal(fields.Height.disabled, true);
fields.Height.value = "96";
fields.Resolution.value = "custom";
fields.Resolution.listeners.change();
assert.equal(fields.Width.disabled, false);
assert.deepEqual(JSON.parse(JSON.stringify(state.plan.chapters[1].resolution)), {width:192, height:96});
assert.equal(writes, 3);
assert.equal(state.plan.chapters[0].resolution, undefined, "changing Chapter 2 leaves Chapter 1 alone");
console.log("Chapter resolution: schema round-trip, legacy inheritance and real menu handlers pass");
