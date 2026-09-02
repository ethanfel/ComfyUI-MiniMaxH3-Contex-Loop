#!/usr/bin/env node

import assert from "node:assert/strict";
import fs from "node:fs";
import {
    LEGACY_GUARD_KEY,
    LEGACY_WIDTH_KEY,
    createLegacyWidgetWidthController,
    graphNodes,
} from "../web/h3_legacy_widget_width_fix_core.mjs";

class FakeNode {
    constructor(type = "Other") {
        this.type = type;
        this.comfyClass = type;
        this.widgets = [];
        this.size = [320, 200];
        this.graph = null;
    }

    addWidget(type, name, value, callback, options) {
        const widget = {type, name, value, callback, options, width: 240};
        this.widgets.push(widget);
        return widget;
    }

    addDOMWidget(name, type, element, options) {
        const widget = {name, type, element, options, width: 250};
        this.widgets.push(widget);
        return widget;
    }

    addCustomWidget(widget) {
        this.widgets.push(widget);
        return widget;
    }
}

const frames = [];
const liteGraph = {vueNodesMode: false};
const graph = {
    _nodes: [],
    dirtyCalls: 0,
    setDirtyCanvas() {
        this.dirtyCalls += 1;
    },
};
let relinquished = 0;
const controller = createLegacyWidgetWidthController({
    getGraph: () => graph,
    getLiteGraph: () => liteGraph,
    requestFrame: (callback) => frames.push(callback),
    onRelinquish: () => { relinquished += 1; },
});
controller.installHooks(FakeNode.prototype);

class LateWidgetNode {
    constructor() {
        this.widgets = [];
        this.graph = null;
    }

    addWidget() {
        const widget = {name: "early-method", width: 230};
        this.widgets.push(widget);
        return widget;
    }
}
controller.installHooks(LateWidgetNode.prototype);

const existing = new FakeNode();
existing.graph = graph;
existing.widgets.push({name: "existing", width: 180});
graph._nodes.push(existing);

const host = new FakeNode("MiniMaxH3ChainPlan");
host.graph = graph;
graph._nodes.push(host);
controller.addHost(host);
assert.equal(controller.active, true);
assert.equal(controller.hostCount, 1);
assert.equal(existing.widgets[0].width, undefined);

LateWidgetNode.prototype.addDOMWidget = function addDOMWidget() {
    const widget = {name: "late-method", width: 235};
    this.widgets.push(widget);
    return widget;
};
controller.installHooks(LateWidgetNode.prototype);
const lateNode = new LateWidgetNode();
lateNode.graph = graph;
assert.equal(lateNode.addDOMWidget().width, undefined);

existing.widgets[0].width = 400;
assert.equal(existing.widgets[0].width, undefined, "LiteGraph writes are blocked");
liteGraph.vueNodesMode = true;
existing.widgets[0].width = 410;
assert.equal(existing.widgets[0].width, 410, "Vue renderer writes are preserved");
liteGraph.vueNodesMode = false;

const created = new FakeNode();
created.graph = graph;
graph._nodes.push(created);
const regular = created.addWidget("number", "regular", 0, null, {});
const dom = created.addDOMWidget("dom", "custom", {}, {});
const custom = created.addCustomWidget({name: "custom", width: 260});
assert.equal(regular.width, undefined);
assert.equal(dom.width, undefined);
assert.equal(custom.width, undefined);

const direct = {name: "direct", width: 300};
created.widgets.push(direct);
controller.nodeCreated(created);
assert.equal(direct.width, undefined);
const deferred = {name: "deferred", width: 320};
created.widgets.push(deferred);
frames.splice(0).forEach((callback) => callback());
assert.equal(deferred.width, undefined);

const nested = new FakeNode();
const subgraph = {_nodes: [nested]};
const container = new FakeNode();
container.subgraph = subgraph;
graph._nodes.push(container);
assert.ok(graphNodes(graph).includes(nested));

const foreign = {name: "standalone-owned"};
foreign[LEGACY_WIDTH_KEY] = 275;
Object.defineProperty(foreign, "width", {
    configurable: true,
    enumerable: true,
    get() { return this[LEGACY_WIDTH_KEY]; },
    set(value) { this[LEGACY_WIDTH_KEY] = value; },
});
Object.defineProperty(foreign, LEGACY_GUARD_KEY, {
    configurable: true,
    value: true,
});
created.widgets.push(foreign);
controller.repairNode(created);
assert.equal(controller.ownsWidget(foreign), true);
foreign.width = 500;
assert.equal(foreign.width, undefined, "embedded repair takes ownership safely");

controller.setAllowed(false);
assert.equal(controller.active, false);
assert.equal(relinquished, 1);
existing.widgets[0].width = 430;
assert.equal(existing.widgets[0].width, 430, "disabling restores normal writes");

controller.setAllowed(true);
assert.equal(controller.active, true);
assert.equal(existing.widgets[0].width, undefined);
controller.removeHost(host);
assert.equal(controller.active, false);
assert.equal(relinquished, 2);

const integrationSource = fs.readFileSync(
    new URL("../web/h3_legacy_widget_width_fix.js", import.meta.url),
    "utf8",
);
assert.match(integrationSource, /MiniMaxH3ContexLoop\.legacyWidgetWidthFix/);
assert.match(integrationSource, /LegacyWidgetWidthFix/);
assert.match(integrationSource, /MiniMaxH3ChainScenePromptEditor/);
assert.match(integrationSource, /MiniMaxH3ChainCheckpointManager/);
assert.match(integrationSource, /MiniMaxH3ChainRunManager/);
assert.match(integrationSource, /MiniMaxH3ContexLoopSeamProbe/);
assert.match(integrationSource, /afterConfigureGraph/);
assert.match(integrationSource, /controller\.syncHosts/);

const integrationFrames = [];
const settingValues = new Map();
let registeredSetting = null;
let extension = null;
class IntegrationNode extends FakeNode {}
const integrationGraph = {
    _nodes: [],
    setDirtyCanvas() {},
};
globalThis.LGraphNode = IntegrationNode;
globalThis.LiteGraph = {vueNodesMode: false};
globalThis.requestAnimationFrame = (callback) => integrationFrames.push(callback);
globalThis.__h3WidthTestCore = {
    createLegacyWidgetWidthController,
    graphNodes,
};
globalThis.__h3WidthTestApp = {
    graph: integrationGraph,
    registerExtension(value) {
        extension = value;
    },
    ui: {
        settings: {
            addSetting(value) {
                registeredSetting = value;
                settingValues.set(value.id, value.defaultValue);
            },
            getSettingValue(id) {
                return settingValues.get(id);
            },
        },
    },
};
const mockedIntegrationSource = integrationSource
    .replace(
        'import {app} from "/scripts/app.js";',
        "const app = globalThis.__h3WidthTestApp;",
    )
    .replace(
        /import \{\n    createLegacyWidgetWidthController,\n    graphNodes,\n\} from "\.\/h3_legacy_widget_width_fix_core\.mjs\?v=[^"]+";/,
        "const {createLegacyWidgetWidthController, graphNodes} = globalThis.__h3WidthTestCore;",
    );
await import(`data:text/javascript;base64,${Buffer.from(mockedIntegrationSource).toString("base64")}`);
assert.ok(extension);
extension.init();
assert.equal(registeredSetting.defaultValue, true);

class IntegrationHost extends IntegrationNode {}
extension.beforeRegisterNodeDef(IntegrationHost, {name: "MiniMaxH3ChainPlan"});
const integrationExisting = new IntegrationNode();
integrationExisting.graph = integrationGraph;
integrationExisting.widgets.push({name: "existing", width: 190});
integrationGraph._nodes.push(integrationExisting);
const integrationHost = new IntegrationHost("MiniMaxH3ChainPlan");
integrationHost.graph = integrationGraph;
integrationGraph._nodes.push(integrationHost);
integrationHost.onAdded();
extension.nodeCreated(integrationHost);
assert.equal(integrationExisting.widgets[0].width, undefined);
assert.equal(integrationExisting.addWidget("number", "new", 0).width, undefined);

integrationHost.title = "MiniMax H3 Contex Loop Plan — CUSTOM TITLE";
integrationExisting.title = "MiniMax H3 Contex Loop is mentioned by another node";
extension.afterConfigureGraph();
assert.equal(
    integrationHost.title,
    "MiniMax H3 Context Loop Plan — CUSTOM TITLE",
    "saved H3 titles receive the spelling correction without losing suffixes",
);
assert.equal(
    integrationExisting.title,
    "MiniMax H3 Contex Loop is mentioned by another node",
    "foreign node titles are never migrated",
);

registeredSetting.onChange(false);
integrationExisting.widgets[0].width = 440;
assert.equal(integrationExisting.widgets[0].width, 440);
registeredSetting.onChange(true);
assert.equal(integrationExisting.widgets[0].width, undefined);

class StandaloneFixNode extends IntegrationNode {
    onRemoved() {
        for (const node of integrationGraph._nodes) {
            for (const widget of node.widgets ?? []) {
                const savedWidth = widget[LEGACY_WIDTH_KEY];
                delete widget.width;
                delete widget[LEGACY_WIDTH_KEY];
                delete widget[LEGACY_GUARD_KEY];
                widget.width = savedWidth;
            }
        }
    }
}
extension.beforeRegisterNodeDef(StandaloneFixNode, {name: "LegacyWidgetWidthFix"});
const standalone = new StandaloneFixNode("LegacyWidgetWidthFix");
standalone.graph = integrationGraph;
integrationGraph._nodes.push(standalone);
standalone.onRemoved();
integrationFrames.splice(0).forEach((callback) => callback());
integrationExisting.widgets[0].width = 445;
assert.equal(
    integrationExisting.widgets[0].width,
    undefined,
    "embedded repair reclaims widgets after the standalone node is removed",
);

integrationHost.onRemoved();
integrationExisting.widgets[0].width = 450;
assert.equal(integrationExisting.widgets[0].width, 450);

class StandaloneCheckpointManager extends IntegrationNode {}
extension.beforeRegisterNodeDef(StandaloneCheckpointManager, {
    name: "MiniMaxH3ChainCheckpointManager",
});
const checkpointManager = new StandaloneCheckpointManager(
    "MiniMaxH3ChainCheckpointManager",
);
checkpointManager.graph = integrationGraph;
integrationGraph._nodes.push(checkpointManager);
checkpointManager.onAdded();
extension.nodeCreated(checkpointManager);
assert.equal(
    integrationExisting.widgets[0].width,
    undefined,
    "a standalone Checkpoint Manager activates the embedded repair",
);
checkpointManager.onRemoved();
integrationExisting.widgets[0].width = 455;
assert.equal(integrationExisting.widgets[0].width, 455);

console.log("H3 embedded legacy widget-width repair: lifecycle, all-node coverage, Vue passthrough, and standalone coexistence pass");
