import assert from "node:assert/strict";
import {readFileSync, writeFileSync, mkdtempSync} from "node:fs";
import {tmpdir} from "node:os";
import {join} from "node:path";
import {pathToFileURL} from "node:url";
import {spawnSync} from "node:child_process";
import vm from "node:vm";

// Exercise the real style injector without importing app.js or opening a project.
const source = readFileSync(new URL("../web/h3_project_asset_manager.js", import.meta.url), "utf8");
const inject = source.slice(source.indexOf("function injectStyles()"), source.indexOf("function collapseWidget("));
const styles = [];
vm.runInNewContext(`${inject}; injectStyles(); injectStyles();`, {document: {
    getElementById: (id) => styles.find((style) => style.id === id),
    createElement: () => ({}),
    head: {appendChild: (style) => styles.push(style)},
}});
assert.equal(styles.length, 1, "Style injection must remain idempotent");
const css = styles[0].textContent;
assert.match(css, /\.h3pa-root,\.h3pa-modal\{/);
for (const token of ["text", "bg", "panel", "muted", "border", "danger", "warning", "success"])
    assert.match(css, new RegExp(`--h3pa-${token}:`));
assert.match(css, /\.h3pa-editor label\{[^}]*color:var\(--h3pa-muted\)/);
assert.match(css, /\.h3pa-toggle-copy small\{color:var\(--h3pa-muted\)/);
assert.match(css, /\.h3pa-button\.danger\{[^}]*color:var\(--h3pa-danger\)/);
assert.match(source, /status\.style\.color = error \? "var\(--h3pa-danger\)"/);
assert.doesNotMatch(source, /style\.color = [^;]*#[0-9a-f]/i);
assert.doesNotMatch(css, /var\([^\n;{}]*\)[0-9a-f]{2}/i);
console.log("Carousel theme: palette-scoped text/surfaces, body-mounted dialogs, status colors and idempotent injection pass");

// Optional real-browser regression: H3_TEST_BROWSER=/path/to/chrome node ... --browser
// A fresh temporary profile and file-only fixture never contact the user's ComfyUI.
if (process.argv.includes("--browser")) {
    const out = mkdtempSync(join(tmpdir(), "h3-carousel-theme-"));
    const html = `<!doctype html><meta charset="utf-8"><style>${css}
      body{margin:16px;font:14px system-ui;background:var(--comfy-menu-bg,#202124)}
      .h3pa-root{width:1220px;height:660px}.h3pa-modal{position:static;transform:none;width:1220px;height:auto;margin-top:16px}
      .h3pa-crop-controls{width:500px}
    </style><div class="h3pa-root">
      <div class="h3pa-row"><strong>Project Asset Carousel</strong><input value="theme_example"></div>
      <div class="h3pa-status">1 project asset · image · 204 KiB · 1752×1168</div>
      <div class="h3pa-tabs"><button class="h3pa-button h3pa-tab active">All 1</button><button class="h3pa-button">Images 1</button></div>
      <div class="h3pa-stage"><div class="h3pa-preview"><div class="h3pa-empty">Media preview</div></div>
        <div class="h3pa-editor"><div class="h3pa-status">image · 204.1 KiB · 1752×1168</div>
          <label>Asset use<select><option>picture reference</option></select></label>
          <label>Prompt tag<input value="courier_arrival"></label>
          <label>Folder<select><option>No folder</option></select></label>
          <label class="h3pa-toggle"><input type="checkbox" checked><span class="h3pa-toggle-copy"><strong>Available to prompts</strong><small>@courier_arrival is used only when a scene prompt includes its tag. Turn off to archive it from suggestions without deleting it.</small></span></label>
          <small class="h3pa-status">input/h3_projects/theme_example/arrival.png</small>
          <div class="h3pa-editor-actions"><span class="h3pa-action-label">Asset actions</span><div class="h3pa-action-primary"><button class="h3pa-button">Edit / upscale</button><button class="h3pa-button">Duplicate</button></div><button class="h3pa-button danger">Delete</button></div>
        </div>
      </div>
      <div class="h3pa-row"><button class="h3pa-card"><span class="fallback">♪</span><span>Source audio</span></button><button class="h3pa-folder-card expanded"><span class="h3pa-folder-name">References</span><span class="h3pa-folder-count">2</span></button><span class="h3pa-unassigned">Unassigned</span></div>
      <div class="h3pa-status" style="color:var(--h3pa-danger)">Example error message</div>
      <div class="h3pa-status" style="color:var(--h3pa-success)">Owner: this workflow</div>
      <div class="h3pa-status" style="color:var(--h3pa-warning)">Ownership available</div>
    </div>
    <div class="h3pa-modal"><strong>Edit / upscale</strong><div class="h3pa-crop-controls"><label>Output width<input value="1752"></label><div class="h3pa-size-summary">Final saved asset · 1752×1168</div><small class="h3pa-crop-note">Drag inside the crop to move it.</small><button class="h3pa-button danger">Cancel operation</button></div><div class="h3pa-empty">No matching import sources</div></div>
    <div class="h3pa-root" style="height:400px"><div class="h3pa-preview h3pa-audio-preview"><div class="h3pa-audio-player"><strong>Source track</strong><audio controls></audio></div><div class="h3pa-lyrics"><div class="h3pa-lyrics-head"><strong>Lyrics</strong><small>Saved with the project</small></div><span class="h3pa-lyrics-time">00:00</span><textarea>Theme-aware lyrics and audio controls</textarea></div></div></div>
    <pre id="results"></pre><script>(${browserChecks.toString()})()</script>`;
    const file = join(out, "fixture.html");
    writeFileSync(file, html);
    const browser = process.env.H3_TEST_BROWSER || "/opt/google/chrome/chrome";
    const run = spawnSync(browser, ["--headless", "--disable-gpu", "--no-first-run",
        "--disable-background-networking", "--disable-component-update", "--disable-sync",
        "--host-resolver-rules=MAP * ~NOTFOUND", `--user-data-dir=${join(out, "profile")}`,
        "--window-size=1280,1160", `--screenshot=${join(out, "light.png")}`, "--dump-dom", pathToFileURL(file).href,
    ], {encoding: "utf8", timeout: 25000, maxBuffer: 1024 * 1024});
    assert.equal(run.status, 0, run.error?.message || run.stderr);
    const encoded = run.stdout.match(/data-report="([^"]+)"/)?.[1];
    assert.ok(encoded, "Browser did not complete the fixture checks");
    const report = JSON.parse(Buffer.from(encoded, "base64").toString());
    console.log(JSON.stringify(report, null, 2));
    console.log(`Browser fixture and screenshot: ${out}`);
    assert.deepEqual(report.failures, []);
}

function browserChecks() {
    const canvas = document.createElement("canvas"); canvas.width = canvas.height = 1;
    const ctx = canvas.getContext("2d", {willReadFrequently: true});
    function rgba(color) {
        ctx.clearRect(0, 0, 1, 1); ctx.fillStyle = color; ctx.fillRect(0, 0, 1, 1);
        return [...ctx.getImageData(0, 0, 1, 1).data].map(v => v / 255);
    }
    function composite(top, bottom) {
        return [...top.slice(0, 3).map((c, i) => c * top[3] + bottom[i] * (1 - top[3])), 1];
    }
    function background(node) {
        return node ? composite(rgba(getComputedStyle(node).backgroundColor), background(node.parentElement)) : [1, 1, 1, 1];
    }
    function luminance(rgb) {
        const linear = rgb.slice(0, 3).map(c => c <= .04045 ? c / 12.92 : ((c + .055) / 1.055) ** 2.4);
        return linear[0] * .2126 + linear[1] * .7152 + linear[2] * .0722;
    }
    const selectors = [".h3pa-status", ".h3pa-editor label", ".h3pa-editor input:not([type=checkbox])",
        ".h3pa-editor select", ".h3pa-toggle-copy small", ".h3pa-action-label", ".h3pa-button",
        ".h3pa-card", ".fallback", ".h3pa-folder-name", ".h3pa-folder-count", ".h3pa-unassigned",
        ".h3pa-empty", ".h3pa-crop-controls label", ".h3pa-crop-controls input", ".h3pa-size-summary",
        ".h3pa-crop-note", ".h3pa-audio-player strong", ".h3pa-lyrics-head small", ".h3pa-lyrics-time", ".h3pa-lyrics textarea"];
    // ComfyUI 1.51.9 Light and Dark palette values, with a no-variable fallback.
    const palettes = {light: ["#222", "#FFFFFF", "#C9C9C9", "#888"], dark: ["#ddd", "#171718", "#222", "#4e4e4e"], fallback: []};
    const failures = [], results = [];
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
            if (ratio < 4.5) failures.push({theme, selector, text: node.textContent.slice(0, 35), ratio});
        }
        results.push({theme, checked, minimumContrast: +minimum.toFixed(2)});
    }
    const report = {results, failures};
    document.getElementById("results").setAttribute("data-report", btoa(JSON.stringify(report)));
    document.getElementById("results").textContent = JSON.stringify(report, null, 2);
}
