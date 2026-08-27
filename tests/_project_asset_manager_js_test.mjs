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
assert.doesNotMatch(source, /if \(asset\._unresolved\) return false/);
assert.match(source, /if \(filter === "image"\) return asset\.role === "picture"/);
assert.match(source, /selectedUnassignedSlot\(\)/);
assert.match(source, /state\.bindingSlot = selectedUnassignedSlot\(\)/);
assert.match(source, /asset, "thumbnail"/);
assert.match(source, /Light UI previews — generation uses originals/);
assert.match(source, /this setting never changes generation media/);
assert.match(source, /H3 always uses the original stored asset/);
assert.match(source, /Available to prompts/);
assert.match(source, /Scene prompts still control where it is used/);
assert.match(source, /Active source track/);
assert.match(source, /without exporting a Source Timeline/);
assert.match(source, /width:min\(760px,calc\(100vw - 32px\)\)/);
assert.match(source, /height:min\(520px,calc\(100vh - 48px\)\)/);
assert.match(source, /state\.previewMode === "full" \? "original" : "poster"/);
assert.match(source, /downstreamPlanRunName\(node\)/);
assert.match(source, /sequence !== refreshSequence \|\| project\(\) !== requestedProject/);
assert.match(source, /Enter a Run name, or connect this node to a named Plan/);
assert.match(source, /function adoptConnectedRunName\(\)/);
assert.match(source, /function scheduleGraphRunNameSync\(\)/);
assert.match(source, /\[0, 50, 200, 750\]/);
assert.match(source, /node\.onConnectionsChange/);
assert.match(source, /nodeClass\.prototype\.onGraphConfigured/);
assert.match(source, /async afterConfigureGraph\(\)/);
assert.match(source, /position:absolute;inset:0/);

console.log("H3 Project Asset Carousel: metadata slots, binding, sources, lazy media, editing, and cleanup pass");
