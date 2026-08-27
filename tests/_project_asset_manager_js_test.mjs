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
assert.match(source, /state\.media\?\.pause/);

console.log("H3 Project Asset Carousel: sources, lazy media, editing, and cleanup pass");
