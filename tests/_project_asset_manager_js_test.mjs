import assert from "node:assert/strict";
import {readFile} from "node:fs/promises";

const source = await readFile(
    new URL("../web/h3_project_asset_manager.js", import.meta.url), "utf8",
);

assert.match(source, /MiniMaxH3ProjectAssetManager/);
assert.match(source, /ComfyUI input/);
assert.match(source, /Server path/);
assert.match(source, /H3 backups/);
assert.match(source, /project-assets\/upload/);
assert.match(source, /project-assets\/import/);
assert.match(source, /project-assets\/update/);
assert.match(source, /video\.controls = true/);
assert.match(source, /video\.preload = "metadata"/);
assert.match(source, /serialize: false/);
assert.match(source, /getMinHeight: \(\) => 560/);
assert.match(source, /flex:1 1 auto/);
assert.doesNotMatch(source, /dom\.computeSize/);
assert.match(source, /state\.media\?\.pause/);
assert.match(source, /Unassigned/);
assert.match(source, /reference_slots/);
assert.match(source, /Choose from ComfyUI Input/);
assert.match(source, /slot_id/);
assert.match(source, /node\.onExecuted/);
assert.match(source, /widget\(node, "run_name"\)/);
assert.match(source, /placeholder = "Run name"/);
assert.match(source, /enter it here only/);
assert.match(source, /asset\?\.role === "semantic_anchor" \? "#" : "@"/);
assert.match(source, /if \(asset\._unresolved\) return false/);
assert.match(source, /if \(filter === "image"\) return asset\.role === "picture"/);

console.log("H3 Project Asset Carousel: metadata slots, binding, sources, lazy media, editing, and cleanup pass");
