import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import {fileURLToPath} from "node:url";

import {
    SCENE_DATA_FIELDS,
    sceneDataFieldPresentation,
} from "../web/h3_scene_data_core.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const extensionSource = fs.readFileSync(
    path.join(HERE, "..", "web", "h3_scene_data_extract.js"), "utf8");

assert.deepEqual(sceneDataFieldPresentation("RefMod sources"), {
    name: "refmod_sources",
    type: "H3_REF_LIST",
});
assert.deepEqual(sceneDataFieldPresentation("Noise seed"), {
    name: "noise_seed",
    type: "INT",
});
assert.deepEqual(sceneDataFieldPresentation("Source audio slice"), {
    name: "source_audio_slice",
    type: "AUDIO",
});
assert.deepEqual(sceneDataFieldPresentation("unknown"),
    SCENE_DATA_FIELDS["RefMod sources"]);
assert.match(extensionSource, /output\.type = presentation\.type/);
assert.match(extensionSource, /output\.name = presentation\.name/);
assert.match(extensionSource, /widget\.callback/);
assert.match(extensionSource, /onConfigure/);

console.log("H3 scene data extractor: dropdown socket presentation passes");
