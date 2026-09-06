import assert from "node:assert/strict";
import {readFileSync, writeFileSync, mkdtempSync} from "node:fs";
import {tmpdir} from "node:os";
import {join} from "node:path";
import {pathToFileURL} from "node:url";
import {spawnSync} from "node:child_process";
import vm from "node:vm";

const source = readFileSync(new URL("../web/h3_chain_plan_studio.js", import.meta.url), "utf8");
const extract = pattern => {
    const match = source.match(pattern);
    assert.ok(match, String(pattern));
    return match[0];
};
const inject = extract(/^function injectStyles\(\)[^]*?^}/m);
const styles = [];
vm.runInNewContext(`${inject}; injectStyles(); injectStyles();`, {document: {
    getElementById: id => styles.find(style => style.id === id),
    createElement: () => ({}), head: {appendChild: style => styles.push(style)},
}});
assert.equal(styles.length, 1, "Style injection remains idempotent");
const css = styles[0].textContent;
assert.match(css, /\.h3studio-form \{[^}]*repeat\(auto-fit,minmax\(min\(100%,\d+px\),1fr\)\)/,
    "The form reflows at the node width, including widths below the minimum cell size");
assert.doesNotMatch(css, /@media[^}]*\.h3studio-form/,
    "Viewport breakpoints must not override the node-responsive form");
assert.match(css, /\.h3studio-length \{[^}]*grid-template-columns:minmax\(0,1fr\) auto/,
    "Reset buttons reserve their own width without forcing the main control outside its cell");
// Use the production field order, wrapper classes, and DOM helpers. Only the
// control values are synthetic; this fixture never loads or saves a project.
const helpers = [
    extract(/^function element\([^]*?^}/m),
    extract(/^    function field\([^]*?^    }/m),
].join("\n");
const wrappers = ["lengthControl", "promptSeedWrap", "seedWrap", "sceneStartWrap", "usedEndWrap"]
    .map(name => [
        extract(new RegExp(`const ${name} = element\\("span", "[^"]+"\\);`)),
        extract(new RegExp(`${name}\\.append\\([^;]+;`)),
    ].join("\n")).join("\n");
const form = extract(/const form = element\("div", "h3studio-form"\);\s*form\.append\([^]*?\n        \);/);
console.log("Plan Studio form: extracted production styles, field order and composite controls");

// Optional real layout regression: node tests/_plan_studio_form_layout_js_test.mjs --browser
// Uses an isolated, file-only Chrome profile with all network lookups blocked.
if (process.argv.includes("--browser")) {
    const out = mkdtempSync(join(tmpdir(), "h3-studio-form-"));
    const file = join(out, "fixture.html");
    writeFileSync(file, `<!doctype html><meta charset="utf-8">
        <style>${styles[0].textContent} body{margin:12px;background:#aaa}
        .h3studio{height:auto;min-height:0}.h3studio-panel{flex:none}</style><body>
        <script>(${browserChecks.toString()})(${JSON.stringify({helpers, wrappers, form})})</script>`);
    for (const viewport of [1800, 700]) {
        const run = spawnSync(process.env.H3_TEST_BROWSER || "/opt/google/chrome/chrome", [
            "--headless", "--disable-gpu", "--no-first-run", "--disable-background-networking",
            "--disable-component-update", "--disable-sync", "--host-resolver-rules=MAP * ~NOTFOUND",
            `--user-data-dir=${join(out, `profile-${viewport}`)}`, `--window-size=${viewport},1000`,
            `--screenshot=${join(out, `light-${viewport}.png`)}`, "--dump-dom", pathToFileURL(file).href,
        ], {encoding:"utf8", timeout:25000, maxBuffer:1024 * 1024});
        assert.equal(run.status, 0, run.error?.message || run.stderr);
        const encoded = run.stdout.match(/data-report="([^"]+)"/)?.[1];
        assert.ok(encoded, "Browser did not finish the layout checks");
        const report = JSON.parse(Buffer.from(encoded, "base64").toString());
        console.log(`Viewport ${viewport}: ${report.checks} checks; fixture: ${out}`);
        assert.deepEqual(report.failures, []);
    }
}

function browserChecks(fixture) {
    const report = {checks:0, failures:[]};
    const test = (ok, message) => { report.checks++; if (!ok) report.failures.push(message); };
    const root = document.createElement("div"); root.className = "h3studio";
    const panel = document.createElement("div"); panel.className = "h3studio-panel";
    root.append(panel); document.body.append(root);
    const form = new Function("document", `${fixture.helpers}
        const input = (value, type="text") => {
            const item = element("input"); item.type = type; item.value = value; return item;
        };
        const select = text => { const item = element("select"); item.append(element("option", "", text)); return item; };
        const id = input("scene_11"), length = input("243", "number"), steps = input("20", "number");
        const mode = select("Plan default"), promptSeedMode = select("Randomize each queue");
        const promptSeed = input("18446744073709551615"), seed = input("18446744073709551615");
        const rerollPromptSeed = element("button", "", "↻"), reroll = element("button", "", "↻");
        const loraRoute = select("Inherit Plan LoRA route"), sceneLockControl = element("button", "", "Unlock scene");
        const sceneStart = input("1:40.000"), resetStart = element("button", "", "Auto");
        const usedEnd = select("Full · 243f · 10.125s"), resetUsedEnd = element("button", "", "Full");
        const incomingTransition = select("Protected 39-frame AV context"), blendFrames = input("0", "number");
        ${fixture.wrappers}
        ${fixture.form}
        return form;
    `)(document);
    panel.append(form);
    const savedValues = () => JSON.stringify([...form.querySelectorAll("input,select")].map(item => item.value));
    const before = savedValues();
    const rect = item => item.getBoundingClientRect();
    const inside = (inner, outer) => inner.left >= outer.left - 1 && inner.right <= outer.right + 1
        && inner.top >= outer.top - 1 && inner.bottom <= outer.bottom + 1;
    const overlap = (a, b) => a.left < b.right - 1 && a.right > b.left + 1
        && a.top < b.bottom - 1 && a.bottom > b.top + 1;
    for (const [theme, palette] of Object.entries({
        dark:{"--comfy-menu-bg":"#202124", "--comfy-input-bg":"#15171d", "--input-text":"#eef1f7", "--border-color":"#555"},
        light:{"--comfy-menu-bg":"#eee", "--comfy-input-bg":"#fff", "--input-text":"#222", "--border-color":"#aaa"},
    })) {
        for (const [key, value] of Object.entries(palette)) root.style.setProperty(key, value);
        for (const width of [360, 640, 820, 1100, 1600]) {
            root.style.width = `${width}px`;
            const label = `${theme}/${width}px`;
            test(form.scrollWidth <= form.clientWidth + 1, `${label}: horizontal form overflow`);
            const fields = [...form.children];
            for (const field of fields) {
                const name = field.firstElementChild.textContent;
                test(inside(rect(field), rect(form)), `${label}/${name}: field outside form`);
                for (const control of field.querySelectorAll("input,select,button")) {
                    test(inside(rect(control), rect(field)), `${label}/${name}: control outside its field`);
                    test(rect(control).width >= 24, `${label}/${name}: unusably narrow control`);
                }
                const controls = [...field.querySelectorAll("input,select,button")];
                for (let i = 0; i < controls.length; i++) for (let j = i + 1; j < controls.length; j++)
                    test(!overlap(rect(controls[i]), rect(controls[j])), `${label}/${name}: overlapping controls`);
            }
            for (let i = 0; i < fields.length; i++) for (let j = i + 1; j < fields.length; j++)
                test(!overlap(rect(fields[i]), rect(fields[j])), `${label}: overlapping fields ${i}/${j}`);
            test(savedValues() === before, `${label}: changing layout altered a control value`);
        }
    }
    root.style.width = `${Math.min(1100, window.innerWidth - 24)}px`;
    document.documentElement.setAttribute("data-report", btoa(JSON.stringify(report)));
}
