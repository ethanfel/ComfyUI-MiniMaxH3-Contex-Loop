#!/usr/bin/env node
"use strict";

import assert from "node:assert/strict";
import {readFile} from "node:fs/promises";

const source = await readFile(
    new URL("../web/h3_project_ownership.mjs", import.meta.url), "utf8",
);

assert.match(source, /activeState\?\.id/);
assert.match(source, /sessionStorage/);
assert.doesNotMatch(source, /localStorage/);
assert.match(source, /const HEARTBEAT_MS = 25000/);
assert.match(source, /async select\(runName\)/);
assert.match(source, /async force\(\)/);
assert.match(source, /async release\(\)/);
assert.match(source, /this\.request\("heartbeat"\)/);
assert.match(source, /X-H3-Workflow-Owner/);
assert.match(source, /X-H3-Ownership-Epoch/);
assert.match(source, /minimax_h3_project_ownership/);
assert.match(source, /controllers\.delete\(this\)/);
assert.doesNotMatch(source, /dispose\(\)[\s\S]{0,220}request\("release"\)/);

console.log("H3 project ownership frontend contract pass");
