#!/usr/bin/env node

import assert from "node:assert/strict";
import {readFile} from "node:fs/promises";
import {
    LORA_ROUTE_LETTERS,
    availableLoRARoutes,
    connectedLoRARoutes,
    loraInputRoute,
    loraRouteLabel,
    nextLoRARoute,
} from "../web/h3_lora_scheduler_core.mjs";

const plan = {id: 1, type: "MiniMaxH3ChainPlan", inputs: []};
const current = {
    id: 2,
    type: "MiniMaxH3ChainCurrentShot",
    inputs: [{name: "state", link: 11}],
};
const scheduler = {
    id: 3,
    type: "MiniMaxH3ChainLoRAScheduler",
    inputs: [
        {name: "state", link: 12},
        {name: "base_model", link: 13},
        {name: "lora_a", link: 14},
        {name: "lora_b", link: null},
        {name: "lora_d", link: 15},
    ],
};
const unrelatedPlan = {id: 4, type: "MiniMaxH3ChainPlan", inputs: []};
const nodes = [plan, current, scheduler, unrelatedPlan];
const graph = {
    _nodes: nodes,
    links: {
        11: {origin_id: 1},
        12: {origin_id: 2},
        13: {origin_id: 20},
        14: {origin_id: 21},
        15: {origin_id: 22},
    },
    getNodeById(id) { return nodes.find((node) => node.id === id) ?? null; },
};
for (const node of nodes) node.graph = graph;

assert.equal(LORA_ROUTE_LETTERS.length, 26);
assert.equal(loraInputRoute("lora_z"), "z");
assert.equal(loraInputRoute("base_model"), null);
assert.deepEqual(connectedLoRARoutes(scheduler), ["a", "d"]);
assert.equal(nextLoRARoute(scheduler), "b");
assert.equal(loraRouteLabel("base"), "Base model");
assert.equal(loraRouteLabel("z"), "LoRA Z");
assert.deepEqual(availableLoRARoutes(graph, [plan]), ["base", "a", "d"]);
assert.deepEqual(
    availableLoRARoutes(graph, [plan], "z"),
    ["base", "a", "d", "z"],
);
assert.deepEqual(
    availableLoRARoutes(graph, [unrelatedPlan]),
    ["base"],
);

const frontend = await readFile(
    new URL("../web/h3_chain_lora_scheduler.js", import.meta.url), "utf8",
);
assert.match(frontend, /function stabilizeRouteInputs\(node\)/);
assert.match(frontend, /node\.removeInput\(index\)/);
assert.match(frontend, /node\.addInput\(`lora_\$\{next\}`, "MODEL"\)/);
assert.match(frontend, /Connect next LoRA route/);
assert.match(frontend, /h3-lora-routes-changed/);
assert.match(frontend, /onConnectionsChange/);
assert.match(frontend, /onGraphConfigured/);

console.log("H3 dynamic LoRA scheduler: progressive A-Z inputs and Plan route discovery pass");
