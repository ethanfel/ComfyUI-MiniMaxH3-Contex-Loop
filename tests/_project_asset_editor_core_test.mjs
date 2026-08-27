import assert from "node:assert/strict";

import {
    coupledOutputDimensions,
    dimensionsForMegapixels,
    formatMegapixels,
    imageMegapixels,
} from "../web/h3_project_asset_editor_core.mjs";

assert.equal(imageMegapixels(2000, 1000), 2);
assert.deepEqual(dimensionsForMegapixels(2, 2), {width: 2000, height: 1000});
assert.deepEqual(
    dimensionsForMegapixels(1, 1344 / 768, 8),
    {width: 1344, height: 768},
);
assert.deepEqual(
    dimensionsForMegapixels(1, 1344 / 768, 32),
    {width: 1344, height: 768},
);
assert.deepEqual(
    dimensionsForMegapixels(1, 16 / 9, 8),
    {width: 1280, height: 720},
);
assert.deepEqual(
    dimensionsForMegapixels(1, 16 / 9, 32),
    {width: 1536, height: 864},
);
assert.deepEqual(
    dimensionsForMegapixels(1, 1344 / 768, 1),
    {width: 1323, height: 756},
);
assert.deepEqual(
    coupledOutputDimensions(2400, 500, "width", 2, true),
    {width: 2400, height: 1200},
);
assert.deepEqual(
    coupledOutputDimensions(500, 1200, "height", 2, true),
    {width: 2400, height: 1200},
);
assert.deepEqual(
    coupledOutputDimensions(2400, 500, "width", 2, false),
    {width: 2400, height: 500},
);
assert.deepEqual(
    coupledOutputDimensions(1341, 500, "width", 1.75, true, 8),
    {width: 1344, height: 768},
);
assert.equal(formatMegapixels(4), "4.00");
assert.equal(formatMegapixels(0), "0.000");

console.log("H3 Project Asset editor: megapixel sizing and locked output dimensions pass");
