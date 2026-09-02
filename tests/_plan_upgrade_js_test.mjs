#!/usr/bin/env node

import assert from "node:assert/strict";
import {
    MODERN_PLAN_NODE,
    MODERN_PLAN_WIDGET_NAMES,
    upgradeLegacyPlanNode,
} from "../web/h3_plan_upgrade_core.mjs";


function widget(name, value = null) {
    return {name, value};
}

const policy = {
    id:1,
    connections:[],
    connect(slot, target, targetSlot) {
        this.connections.push({slot, target, targetSlot});
    },
};
const project = {
    id:2,
    connections:[],
    connect(slot, target, targetSlot) {
        this.connections.push({slot, target, targetSlot});
    },
};
const target = {id:4};
const legacy = {
    id:3,
    pos:[120, 340],
    size:[760, 910],
    properties:{h3_chain_plan_layout:{advanced:true}},
    color:"#123456",
    bgcolor:"#222222",
    mode:0,
    inputs:[
        {name:"chain_policy", link:10},
        {name:"project_assets", link:11},
        {name:"plan_json_input", link:null},
    ],
    outputs:[
        {name:"plan", links:[12]},
        {name:"summary", links:null},
    ],
    widgets:[
        widget("plan_json", '{"shots":[{"id":"one"}]}'),
        widget("run_name", "upgrade_test"),
        widget("generation_fingerprint", "model-a"),
        widget("width", 1280),
        widget("height", 704),
        widget("context_length", 39),
        widget("encode_mode", "video"),
        widget("anchor_mode", "before"),
        widget("crop", "center"),
        widget("audio_mode", "source_track"),
        widget("audio_context_length", 90),
        widget("default_duration_seconds", 10),
        widget("default_steps", 30),
        widget("base_seed", "18446744073709551615"),
        widget("segment_crf", 17),
        widget("video_blend_frames", 5),
        widget("continuation_mode", "drift_control_av"),
    ],
};
const graph = {
    _nodes:[policy, project, legacy, target],
    links:{
        10:{origin_id:1, origin_slot:0, target_id:3, target_slot:0},
        11:{origin_id:2, origin_slot:0, target_id:3, target_slot:1},
        12:{origin_id:3, origin_slot:0, target_id:4, target_slot:0},
    },
    added:[], removed:[], dirty:false,
    add(node) { this.added.push(node); this._nodes.push(node); node.graph = this; },
    remove(node) { this.removed.push(node); this._nodes = this._nodes.filter((item) => item !== node); },
    getNodeById(id) { return this._nodes.find((item) => item.id === id) ?? null; },
    setDirtyCanvas() { this.dirty = true; },
};
legacy.graph = graph;

let replacement = null;
function createNode(type) {
    assert.equal(type, MODERN_PLAN_NODE);
    replacement = {
        id:5,
        inputs:[
            {name:"chain_policy", link:null},
            {name:"project_assets", link:null},
            {name:"plan_json_input", link:null},
        ],
        outputs:[{name:"plan", links:null}, {name:"summary", links:null}],
        widgets:MODERN_PLAN_WIDGET_NAMES.map((name) => widget(name)),
        connections:[],
        connect(slot, destination, targetSlot) {
            this.connections.push({slot, destination, targetSlot});
        },
        setSize(size) { this.size = size; },
    };
    return replacement;
}

const result = upgradeLegacyPlanNode(legacy, {
    createNode,
    confirmUpgrade:() => true,
});
assert.equal(result.ok, true);
assert.equal(result.node, replacement);
assert.deepEqual(replacement.pos, [120, 340]);
assert.deepEqual(replacement.size, [760, 910]);
assert.notEqual(replacement.properties, legacy.properties);
assert.deepEqual(replacement.properties, legacy.properties);
assert.equal(replacement.color, legacy.color);
assert.equal(replacement.widgets.find((item) => item.name === "run_name").value,
    "upgrade_test");
assert.equal(replacement.widgets.find((item) => item.name === "base_seed").value,
    "18446744073709551615");
assert.equal(replacement.widgets.some((item) => item.name === "context_length"), false);
assert.deepEqual(graph.removed, [legacy]);
assert.equal(policy.connections[0].target, replacement);
assert.equal(policy.connections[0].targetSlot, 0);
assert.equal(project.connections[0].target, replacement);
assert.equal(project.connections[0].targetSlot, 1);
assert.equal(replacement.connections[0].destination, target);
assert.equal(replacement.connections[0].targetSlot, 0);
assert.equal(graph.dirty, true);

const withoutPolicy = {
    graph,
    inputs:[{name:"chain_policy", link:null}],
};
assert.deepEqual(upgradeLegacyPlanNode(withoutPolicy, {createNode}), {
    ok:false, reason:"policy_required",
});
assert.deepEqual(upgradeLegacyPlanNode({...withoutPolicy, inputs:[
    {name:"chain_policy", link:10},
]}, {createNode, confirmUpgrade:() => false}), {
    ok:false, reason:"cancelled",
});

console.log("H3 Plan upgrade: named values and graph links survive replacement")
