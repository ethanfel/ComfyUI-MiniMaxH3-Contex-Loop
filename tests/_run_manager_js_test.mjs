#!/usr/bin/env node

import assert from "node:assert/strict";
import fs from "node:fs";
import {
    runArchiveOptionLabel,
    runManagerIdentity,
} from "../web/h3_run_manager_core.mjs";

const different = runManagerIdentity("active_project", {
    run_name: "saved_project",
});
assert.equal(different.same, false);
assert.equal(different.activeLabel, "Active Plan: active_project");
assert.equal(
    different.selectedLabel,
    "Selected archive: saved_project (not loaded)",
);
assert.equal(different.loadLabel, "Load selected archive into Plan");
assert.match(different.saveLabel, /active_project/);

const same = runManagerIdentity("saved_project", {run_name: "saved_project"});
assert.equal(same.same, true);
assert.equal(same.loadLabel, "Reload selected archive");
assert.match(runArchiveOptionLabel({
    run_name: "saved_project", scene_count: 2, restorable: true,
}, "saved_project"), /2 scenes · ACTIVE PLAN$/);
assert.match(runArchiveOptionLabel({
    run_name: "asset_project", scene_count: null, restorable: false,
}, ""), /assets only$/);

const source = fs.readFileSync(
    new URL("../web/h3_chain_run_manager.js", import.meta.url), "utf8",
);

assert.match(source, /MiniMaxH3ChainRunManager/);
assert.match(source, /MiniMaxH3ChainPlan/);
assert.match(source, /\/minimax_h3_context_loop\/runs/);
assert.match(source, /\/minimax_h3_context_loop\/run\?/);
assert.match(source, /\/minimax_h3_context_loop\/run-assets/);
assert.match(source, /window\.confirm\(message\)/);
assert.match(source, /This replaces all active scene prompts, archived Plan settings, and connected 0\.5 policies/);
assert.match(source, /function applyPlanInputs/);
assert.match(source, /planNode, policyInputs, inputs/);
assert.match(source, /payload\.policy_inputs/);
assert.match(source, /refreshRestoredPlanEditors\(planNode\)/);
assert.match(source, /left === "plan_json"/);
assert.match(source, /widget\.callback\?\.\(inputs\[name\]\)/);
assert.match(source, /refreshRestoredPlanEditors\(planNode\)/);
assert.match(source, /output\/h3_chains/);
assert.match(source, /Open selected folder/);
assert.match(source, /navigator\.clipboard\.writeText\(payload\.path\)/);
assert.match(source, /collectAssetBindings\(node\)/);
assert.match(source, /applyAssetBinding\(graph, binding\)/);
assert.match(source, /Connect loader asset/);
assert.match(source, /Archive video/);
assert.match(source, /Reference assets →/);
assert.match(source, /_h3RunManagerWatchers/);
assert.match(source, /refreshRuns\(savedRunName\)/);
assert.match(source, /Saved \$\{payload\.asset_count\} bindings to/);
assert.match(source, /Active Plan is now/);
assert.match(source, /selectedIdentity\.textContent = runIdentity\.selectedLabel/);
assert.doesNotMatch(source, /option\.disabled = !run\.restorable/);
assert.match(source, /Recovery blocked:/);
assert.match(source, /committed immutable checkpoint snapshot/);
assert.match(source, /removeLegacyStatusOutput/);
assert.match(source, /output\.name === "asset_status"/);
assert.match(source, /widget\.hidden = true/);
assert.match(source, /widget\.draw = \(\) => \{\}/);
assert.match(source, /pointer-events[^\n]+none[^\n]+important/);
assert.match(source, /widget\.onRemove\(\)/);
const backend = fs.readFileSync(
    new URL("../chain_nodes.py", import.meta.url), "utf8",
);
assert.match(backend, /"rawLink": True/);
assert.match(backend, /"lazy": True/);

console.log("H3 Run Manager frontend: discovery, confirmation and Plan restore wiring pass");
