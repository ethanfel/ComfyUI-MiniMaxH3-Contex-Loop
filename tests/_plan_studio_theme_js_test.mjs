import assert from "node:assert/strict";
import {readFileSync, writeFileSync, mkdtempSync} from "node:fs";
import {tmpdir} from "node:os";
import {join} from "node:path";
import {pathToFileURL} from "node:url";
import {spawnSync} from "node:child_process";
import vm from "node:vm";

const source = readFileSync(new URL("../web/h3_chain_plan_studio.js", import.meta.url), "utf8");
const inject = source.match(/^function injectStyles\(\)[^]*?^}/m)?.[0];
assert.ok(inject);
const styles = [];
vm.runInNewContext(`${inject}; injectStyles(); injectStyles();`, {document: {
    getElementById: id => styles.find(style => style.id === id),
    createElement: () => ({}), head: {appendChild: style => styles.push(style)},
}});
assert.equal(styles.length, 1, "Theme styles remain idempotent");
const css = styles[0].textContent;
for (const token of ["muted", "accent", "success", "warning", "danger", "alternate"])
    assert.match(css, new RegExp(`--hs-${token}:color-mix\\(in srgb,var\\(--hs-text\\)`),
        `${token} must adapt to the host foreground, not assume a dark theme`);
assert.match(css, /\.h3studio-error \{ color:var\(--hs-danger\)/);
assert.match(css, /\.h3studio-context-tabs button\.h3studio-context-tab-active \{[^}]*background:var\(--hs-selected\)/);
assert.match(css, /\.h3studio-context-empty \{[^}]*color:var\(--hs-media-muted\)/,
    "Dark preview surfaces must not inherit light-theme form text");
assert.match(css, /\.h3studio-card-copy \{[^}]*color:var\(--hs-media-text\)/,
    "Scene titles remain legible over the dark thumbnail gradient");
console.log("Plan Studio theme: palette-driven text and separate dark-preview colors pass");

// Optional contrast checks in real Chrome, with no connection to ComfyUI:
// node tests/_plan_studio_theme_js_test.mjs --browser
if (process.argv.includes("--browser")) {
    const out = mkdtempSync(join(tmpdir(), "h3-studio-theme-"));
    const file = join(out, "fixture.html");
    writeFileSync(file, `<!doctype html><meta charset="utf-8"><style>${css}
        body{margin:12px;background:var(--comfy-menu-bg,#202124)}
        .h3studio{width:1200px;height:auto;min-height:0}.h3studio-panel{flex:none}
        .theme-examples{display:flex;flex-wrap:wrap;gap:12px;align-items:center;margin:10px 0}
        .h3studio-chapter-marker{position:relative;height:30px;width:120px}
        .h3studio-context-empty{min-height:60px}
        .h3studio-subtitle-cue{position:static}
        </style><body><div class="h3studio">
        <div class="h3studio-head"><strong class="h3studio-title">Plan Studio</strong>
            <span class="h3studio-run">linked · theme_example</span></div>
        <div class="h3studio-toolbar"><button>Scene prompt</button><button class="h3studio-active">Plan settings</button></div>
        <div class="h3studio-panel">
          <div class="h3studio-plan-settings">
            <div class="h3studio-plan-defaults-help">Connected mode · changes are written to the Modern Plan and mirrored into Studio. Disconnecting keeps this synchronized snapshot.</div>
            <div class="h3studio-plan-settings-section">Run identity and canvas</div>
            <div class="h3studio-plan-defaults-help">Run name and reference-derived generation fingerprint are managed by connected Project Assets.</div>
            <label class="h3studio-field"><span>Base seed</span><input value="0"></label>
            <label class="h3studio-field"><span>Width</span><input type="number" value="864"></label>
            <label class="h3studio-field"><span>Height</span><input type="number" value="480"></label>
            <label class="h3studio-field"><span>Segment CRF</span><input type="number" value="20"></label>
            <div class="h3studio-plan-settings-section">Plan-wide scene defaults</div>
            <label class="h3studio-field"><span>Duration</span><select><option>Plan default</option></select></label>
          </div>
          <div class="theme-examples">
            <span class="h3studio-grid-marker">Generated 243f</span>
            <span class="h3studio-grid-marker h3studio-grid-exact">AV context aligned</span>
            <span class="h3studio-grid-marker h3studio-grid-warning">Audio grid warning</span>
            <span class="h3studio-error">Example validation error</span>
            <button class="h3studio-chapter-marker"><span>Chapter 1</span></button>
            <button class="h3studio-chapter-marker h3studio-selected"><span>Chapter 2</span></button>
            <span class="h3studio-subtitle-cue">Subtitle timeline cue</span>
          </div>
          <div class="h3studio-alternate"><strong>Alternate prompt</strong>
            <div class="h3studio-alternate-diff">Saved prompt difference</div></div>
          <div class="h3studio-context-block">
            <div class="h3studio-context-tabs"><button class="h3studio-context-tab-active">Video context</button><button>Audio context</button></div>
            <p class="h3studio-context-help">Choose the context range for the next scene.</p>
            <div class="h3studio-context-phase-note">Experimental context phase</div>
            <div class="h3studio-context-empty">No context video available</div>
          </div>
          <div class="h3studio-ref-mode theme-examples"><button class="h3studio-selected">Tagged references</button><button>Scheduled references</button></div>
          <div class="h3studio-hint">Changes to colors do not modify the Plan.</div>
        </div></div><pre id="results"></pre><script>(${browserChecks.toString()})()</script>`);
    const run = spawnSync(process.env.H3_TEST_BROWSER || "/opt/google/chrome/chrome", [
        "--headless", "--disable-gpu", "--no-first-run", "--disable-background-networking",
        "--disable-component-update", "--disable-sync", "--host-resolver-rules=MAP * ~NOTFOUND",
        `--user-data-dir=${join(out, "profile")}`, "--window-size=1250,1100",
        `--screenshot=${join(out, "light.png")}`, "--dump-dom", pathToFileURL(file).href,
    ], {encoding:"utf8", timeout:25000, maxBuffer:1024 * 1024});
    assert.equal(run.status, 0, run.error?.message || run.stderr);
    const encoded = run.stdout.match(/data-report="([^"]+)"/)?.[1];
    assert.ok(encoded, "Browser did not complete the contrast checks");
    const report = JSON.parse(Buffer.from(encoded, "base64").toString());
    console.log(JSON.stringify(report, null, 2));
    console.log(`Browser fixture and screenshot: ${out}`);
    assert.deepEqual(report.failures, []);
}

function browserChecks() {
    const canvas = document.createElement("canvas"); canvas.width = canvas.height = 1;
    const ctx = canvas.getContext("2d", {willReadFrequently:true});
    function rgba(color) {
        ctx.clearRect(0, 0, 1, 1); ctx.fillStyle = color; ctx.fillRect(0, 0, 1, 1);
        return [...ctx.getImageData(0, 0, 1, 1).data].map(value => value / 255);
    }
    const composite = (top, bottom) => [...top.slice(0, 3).map((c, i) => c * top[3] + bottom[i] * (1 - top[3])), 1];
    const background = node => node
        ? composite(rgba(getComputedStyle(node).backgroundColor), background(node.parentElement)) : [1, 1, 1, 1];
    function luminance(rgb) {
        const linear = rgb.slice(0, 3).map(c => c <= .04045 ? c / 12.92 : ((c + .055) / 1.055) ** 2.4);
        return linear[0] * .2126 + linear[1] * .7152 + linear[2] * .0722;
    }
    const selectors = [".h3studio-title", ".h3studio-run", ".h3studio-plan-settings-section",
        ".h3studio-plan-defaults-help", ".h3studio-field > span", ".h3studio-field input",
        ".h3studio-field select", ".h3studio-toolbar button", ".h3studio-grid-marker", ".h3studio-error",
        ".h3studio-chapter-marker span", ".h3studio-subtitle-cue", ".h3studio-alternate-diff",
        ".h3studio-context-tabs button", ".h3studio-context-help", ".h3studio-context-phase-note",
        ".h3studio-context-empty", ".h3studio-ref-mode button", ".h3studio-hint"];
    // Actual ComfyUI palette tokens, plus missing-variable fallback and a theme
    // switch back to light without rebuilding the DOM or re-injecting styles.
    const palettes = {light:["#222", "#fff", "#c9c9c9", "#888"], dark:["#ddd", "#171718", "#222", "#4e4e4e"], fallback:[]};
    const report = {results:[], failures:[]};
    for (const theme of ["light", "dark", "fallback", "light"]) {
        ["input-text", "comfy-menu-bg", "comfy-input-bg", "border-color"].forEach((name, i) => {
            document.documentElement.style.removeProperty(`--${name}`);
            if (palettes[theme][i]) document.documentElement.style.setProperty(`--${name}`, palettes[theme][i]);
        });
        let minimum = Infinity, checked = 0;
        for (const selector of selectors) for (const node of document.querySelectorAll(selector)) {
            const bg = background(node), fg = composite(rgba(getComputedStyle(node).color), bg);
            const a = luminance(bg), b = luminance(fg), ratio = (Math.max(a, b) + .05) / (Math.min(a, b) + .05);
            minimum = Math.min(minimum, ratio); checked++;
            if (ratio < 4.5) report.failures.push({theme, selector, ratio:+ratio.toFixed(2)});
        }
        report.results.push({theme, checked, minimumContrast:+minimum.toFixed(2)});
    }
    document.getElementById("results").setAttribute("data-report", btoa(JSON.stringify(report)));
    document.getElementById("results").textContent = JSON.stringify(report.results, null, 2);
}
