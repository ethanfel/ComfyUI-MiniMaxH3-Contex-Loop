#!/usr/bin/env node

import assert from "node:assert/strict";
import {
    PROJECT_ASSET_CATALOG_CHANGED_EVENT,
    publishProjectAssetCatalogChanged,
} from "../web/h3_project_asset_sync_core.mjs";

const originalCustomEvent = globalThis.CustomEvent;
const originalDispatchEvent = globalThis.dispatchEvent;
const events = [];
globalThis.CustomEvent = class CustomEvent {
    constructor(type, options = {}) {
        this.type = type;
        this.detail = options.detail;
    }
};
globalThis.dispatchEvent = (event) => {
    events.push(event);
    return true;
};

try {
    const manager = {};
    const catalog = {project:"episode", revision:"revision-1", assets:[]};
    assert.equal(publishProjectAssetCatalogChanged(manager, catalog), true);
    assert.equal(events.length, 1);
    assert.equal(events[0].type, PROJECT_ASSET_CATALOG_CHANGED_EVENT);
    assert.equal(events[0].detail.manager, manager);
    assert.equal(events[0].detail.project, "episode");
    assert.equal(events[0].detail.revision, "revision-1");
    assert.equal(publishProjectAssetCatalogChanged(manager, catalog), false);
    assert.equal(events.length, 1, "unchanged revisions should not wake every editor again");
    assert.equal(publishProjectAssetCatalogChanged(manager, {
        ...catalog, revision:"revision-2",
    }), true);
    assert.equal(events.length, 2);
} finally {
    globalThis.CustomEvent = originalCustomEvent;
    globalThis.dispatchEvent = originalDispatchEvent;
}

console.log("H3 project asset catalog notifications pass");
