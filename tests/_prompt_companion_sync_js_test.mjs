#!/usr/bin/env node

import assert from "node:assert/strict";
import fs from "node:fs";
import {
    activeSceneIndexAfterRefresh,
    adjacentPlanCompanions,
    connectedPlanStudios,
    connectedPromptEditors,
    planHasNonPromptChanges,
    publishCompanionPrompt,
    publishCompanionScene,
    publishPlanCompanionScene,
    rebaseScenePrompt,
} from "../web/h3_prompt_companion_sync.mjs";

assert.equal(activeSceneIndexAfterRefresh(
    {shots:[{id:"one"}, {id:"two"}, {id:"three"}]},
    {shots:[{id:"three"}, {id:"one"}, {id:"two"}]},
    1,
), 2);
assert.equal(activeSceneIndexAfterRefresh(
    {shots:[{id:"one"}, {id:"removed"}, {id:"three"}]},
    {shots:[{id:"one"}, {id:"three"}]},
    1,
), 1);
assert.equal(activeSceneIndexAfterRefresh(null, {shots:[{id:"one"}]}, 8), 0);
assert.equal(activeSceneIndexAfterRefresh(null, {shots:[]}, 8), 0);

const plan = {id:1, type:"MiniMaxH3ChainPlan"};
const studio = {id:2, type:"MiniMaxH3ChainPlanStudio", inputs:[{link:10}], outputs:[{links:[11]}]};
const editor = {id:3, type:"MiniMaxH3ChainRichScenePromptEditor", inputs:[{link:11}], outputs:[]};
const nodes = new Map([[1,plan],[2,studio],[3,editor]]);
const links = {
    10:{origin_id:1,target_id:2},
    11:{origin_id:2,target_id:3},
};
const graph = {links, _nodes:[plan, studio, editor], getNodeById:(id) => nodes.get(id)};
for (const node of nodes.values()) node.graph = graph;

assert.deepEqual(adjacentPlanCompanions(studio), [plan, editor]);
assert.deepEqual(connectedPromptEditors(studio), [editor]);
assert.deepEqual(connectedPlanStudios(editor), [studio]);

let received = null;
editor._h3PromptCompanionSetActiveScene = (receivedPlan, index, source) => {
    received = {receivedPlan,index,source};
};
assert.equal(publishCompanionScene(studio, plan, 2.9), 1);
assert.deepEqual(received, {receivedPlan:plan,index:2,source:studio});

editor._h3PromptCompanionSetActiveScene = () => false;
assert.equal(publishCompanionScene(studio, plan, 4), 0);

const review = {id:4, type:"MiniMaxH3ChainReview", graph};
graph._nodes.push(review);
editor._h3PromptCompanionSetActiveScene = (receivedPlan, index, source) => {
    received = {receivedPlan,index,source};
    return receivedPlan === plan;
};
assert.equal(publishPlanCompanionScene(review, plan, 1), 1);
assert.deepEqual(received, {receivedPlan:plan,index:1,source:review});

let promptReceived = null;
editor._h3PromptCompanionSetScenePrompt = (receivedPlan, index, prompt, source) => {
    promptReceived = {receivedPlan,index,prompt,source};
    return receivedPlan === plan;
};
assert.equal(publishCompanionPrompt(review, plan, 1, "Edited\r\nprompt."), 1);
assert.deepEqual(promptReceived, {
    receivedPlan:plan, index:1, prompt:"Edited\nprompt.", source:review,
});

const localPlan = {shared:"old", shots:[
    {id:"one", prompt:["old one"], seed:"1"},
    {id:"two", prompt:["edited two"], seed:"2"},
]};
const editedShot = localPlan.shots[1];
const livePlan = {shared:"new", shots:[
    {id:"two", prompt:["stale two"], seed:"22", steps:20},
    {id:"one", prompt:["live one"], seed:"11"},
]};
assert.equal(rebaseScenePrompt(localPlan, livePlan, 1), 0);
assert.equal(localPlan.shared, "new");
assert.equal(localPlan.shots[0], editedShot, "active shot identity survives rebase");
assert.deepEqual(localPlan.shots[0], {id:"two", prompt:["edited two"], seed:"22", steps:20});
assert.deepEqual(localPlan.shots[1], {id:"one", prompt:["live one"], seed:"11"});
assert.equal(rebaseScenePrompt({shots:[{id:"gone",prompt:[]}]}, livePlan, 0), -1);

assert.equal(planHasNonPromptChanges(
    {shared:"same", shots:[{id:"one", prompt:["old"], seed:"11", length:90}]},
    {shared:"same", shots:[{id:"one", prompt:["new"], seed:"11", length:90}]},
), false, "a prompt-only broadcast can update in place without rerendering");
assert.equal(planHasNonPromptChanges(
    {shared:"same", shots:[{id:"one", prompt:["old"], seed:"11", length:90}]},
    {shared:"same", shots:[{id:"one", prompt:["new"], seed:"22", length:90}]},
), true, "candidate seed acceptance must reload the complete Plan");
assert.equal(planHasNonPromptChanges(
    {shared:"same", shots:[{id:"one", prompt:["old"], seed:"11", length:90}]},
    {shared:"same", shots:[{id:"one", prompt:["new"], seed:"11", length:141}]},
), true, "candidate length acceptance must reload the complete Plan");
assert.equal(planHasNonPromptChanges(
    {shared:"old", shots:[{id:"one", prompt:["same"]}]},
    {shared:"new", shots:[{id:"one", prompt:["same"]}]},
), true, "shared and plan-level fields remain synchronized");

for (const relative of [
    "../web/h3_chain_scene_prompt_editor.js",
    "../web/h3_chain_rich_scene_prompt_editor.js",
    "../web/h3_chain_plan_studio.js",
]) {
    const source = fs.readFileSync(new URL(relative, import.meta.url), "utf8");
    assert.match(source, /import \* as promptCompanionSync/);
    assert.match(source, /promptCompanionSync\.publishCompanionPrompt\?\./);
    assert.match(source, /planHasNonPromptChanges\(state\.plan, livePlan\)/);
    assert.match(source, /loadPlan\(true\)/);
}

const reviewSource = fs.readFileSync(
    new URL("../web/h3_chain_review_final.js", import.meta.url), "utf8");
assert.match(reviewSource, /import \* as promptCompanionSync/);
assert.match(reviewSource, /promptCompanionSync\.publishCompanionPrompt\?\./);
assert.match(reviewSource, /promptCompanionSync\.publishPlanCompanionScene\?\./);
assert.match(reviewSource, /_h3PromptCompanionSetScenePrompt/);
assert.equal(
    reviewSource.match(/refreshRestoredPlanEditors\(planNode\)/g)?.length,
    3,
    "review edits, checkpoint revisions, and saved-input restore all refresh complete Plan data",
);

console.log("H3 prompt companions: active-scene and review prompt synchronization pass");
