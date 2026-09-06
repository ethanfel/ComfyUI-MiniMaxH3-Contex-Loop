// Real DOM regression for both embedded editors. Never connects to ComfyUI.
import assert from "node:assert/strict";
import {readFileSync, writeFileSync, mkdtempSync} from "node:fs";
import {tmpdir} from "node:os";
import {join} from "node:path";
import {pathToFileURL} from "node:url";
import {spawnSync} from "node:child_process";

const read = name => readFileSync(new URL("../web/" + name, import.meta.url), "utf8");
const functionSource = (source, name, indent = "") => {
    const match = source.match(new RegExp("^" + indent + "function " + name + "\\([^]*?^" + indent + "}", "m"));
    assert.ok(match, name);
    return match[0];
};
const modules = [
    "h3_prompt_schema_core.mjs", "h3_rich_prompt_editor_core.mjs",
    "h3_prompt_completion_core.mjs", "h3_prompt_marker_ui.mjs",
    "h3_prompt_editor_settings_core.mjs",
].map(name => read(name).replace(/^import [^]*?;\n/gm, "").replace(/^export /gm, "")).join("\n");
const fixtures = [];
for (const rich of [false, true]) {
    const source = read(rich ? "h3_chain_rich_scene_prompt_editor.js" : "h3_chain_scene_prompt_editor.js");
    const render = rich ? "renderEditorText" : "renderRichEditorText";
    const functions = [
        ...["editorPlainText", "editorPointTextOffset", "selectionTextOffset", "restoreCaret", "restoreTextSelection", "insertPlainText"]
            .map(name => functionSource(source, name)),
        functionSource(source, rich ? "makeToken" : "makeRichToken", "    "),
        functionSource(source, render, "    "),
    ].join("\n");
    const replacement = source.match(/        const replacePromptText = [^]*?^        };/m)?.[0];
    const controller = source.match(/        state\.completion = createPromptCompletionController\(\{[^]*?^        \}\);/m)?.[0];
    const binding = source.match(/        bindPromptMarkerInteractions\(\{[^]*?^        \}\);/m)?.[0];
    const guard = source.match(/    for \(const eventName of \["keydown", "keyup", "keypress", "copy", "cut", "paste"\]\) \{[^]*?^    }/m)?.[0];
    const capture = source.match(/    root\.addEventListener\("keydown", \(event\) => \{[^]*?^    }, true\);/m)?.[0];
    const paste = source.match(new RegExp("        " + (rich ? "editor" : "richEditor") + '\\.addEventListener\\("paste", [^]*?^        \\}\\);', "m"))?.[0];
    for (const value of [replacement, controller, binding, guard, capture, paste]) assert.ok(value);
    fixtures.push({rich, render, functions, replacement, controller, binding, guard, capture, paste});
}
console.log("Browser fixture: extracted actual DOM helpers, replacement/save path, bindings and shortcut guards from both editors");
if (!process.argv.includes("--browser")) process.exit(0);

const out = mkdtempSync(join(tmpdir(), "h3-prompt-editor-"));
const html = '<!doctype html><meta charset="utf-8"><style>'
    + '[contenteditable]{width:900px;min-height:120px;white-space:pre-wrap;font:16px monospace;border:1px solid #888}'
    + '[data-token]{display:inline-block;background:#ddd;color:black}textarea{width:900px;height:120px}'
    + '</style><pre id="report"></pre><script>\n' + modules + "\n"
    + "(" + browserChecks.toString() + ")(" + JSON.stringify(fixtures).replace(/<\/script/gi, "<\\/script") + ");</script>";
const file = join(out, "fixture.html");
writeFileSync(file, html);
const run = spawnSync(process.env.H3_TEST_BROWSER || "/opt/google/chrome/chrome", [
    "--headless", "--disable-gpu", "--no-first-run", "--disable-background-networking",
    "--disable-component-update", "--disable-sync", "--host-resolver-rules=MAP * ~NOTFOUND",
    "--user-data-dir=" + join(out, "profile"), "--dump-dom", pathToFileURL(file).href,
], {encoding:"utf8", timeout:25000, maxBuffer:2 * 1024 * 1024});
assert.equal(run.status, 0, run.error?.message || run.stderr);
const encoded = run.stdout.match(/data-report="([^"]+)"/)?.[1];
assert.ok(encoded, "Browser fixture did not finish: " + run.stdout.slice(-2000));
const report = JSON.parse(Buffer.from(encoded, "base64").toString());
console.log(report);
console.log("Isolated browser fixture: " + file);
assert.deepEqual(report.failures, []);

function browserChecks(fixtures) {
    const report = {checks:0, failures:[]};
    const test = (condition, message) => {
        report.checks++;
        if (!condition) throw new Error(message);
    };
    for (const fixture of fixtures) {
        try {
            // Production helpers/bindings execute together; only network/Plan
            // persistence and the reference preview surface are replaced.
            const setup = `
                const root = document.createElement("div"); document.body.append(root);
                const editor = document.createElement("div"); editor.contentEditable = "true";
                const richEditor = editor;
                const textarea = document.createElement("textarea"); textarea.hidden = true;
                root.append(editor, textarea);
                const records = [{kind:"picture", tag:"Hero", token:"@Hero", label:"<Picture 2>", active:true}];
                const shot = {id:"one", prompt:[]}, shotId = "one", node = {};
                const state = {editor, richEditor, decorated:true, active:0, referenceMode:"tagged",
                    records, plan:{shots:[shot, {id:"two", prompt:["untouched"]}]},
                    promptUndo:new PromptUndoHistory("")};
                const status = {}, saved = [], drafts = [];
                let referenceEdits = 0, flushes = 0;
                let preferences = h3PromptEditorPreferences();
                const promptEditorPreferences = () => preferences;
                const promptTextToLines = text => text.split("\\n");
                const sharedPrompt = () => ({text:""});
                const availableReferenceRecords = () => ({records, mode:"tagged"});
                const writePlan = () => saved.push(shot.prompt.join("\\n"));
                const scheduleHistoryDraft = (id, text) => drafts.push({id, text});
                const flushPlanEffects = () => flushes++;
                const hidePopover = () => {};
                const showPopover = () => {}, showTokenPopover = () => {};
                const scheduleHidePopover = () => {};
                const showReferenceEditor = () => referenceEdits++;
                const referenceMediaPreview = () => null;
                const element = (tag, cls, text) => {
                    const el = document.createElement(tag);
                    if (cls) el.className = cls; if (text) el.textContent = text; return el;
                };
                const icon = () => element("span", "", "ICON");
                ${fixture.functions}
                const renderText = ${fixture.render};
                const activePromptText = () => state.decorated ? editorPlainText(editor) : textarea.value;
                editor.addEventListener("input", event => {
                    const text = editorPlainText(editor);
                    state.promptUndo.record(text, {inputType:event.inputType || "insertReplacementText"});
                    shot.prompt = promptTextToLines(text); textarea.value = text;
                    writePlan(); scheduleHistoryDraft(shotId, text);
                });
                textarea.addEventListener("input", () => {
                    state.promptUndo.record(textarea.value, {inputType:"insertReplacementText"});
                    shot.prompt = promptTextToLines(textarea.value);
                    writePlan(); scheduleHistoryDraft(shotId, textarea.value);
                });
                state.ownsPromptHistoryTarget = target => target === editor || editor.contains(target) || target === textarea;
                state.applyPromptHistoryShortcut = direction => {
                    const text = state.promptUndo[direction]();
                    if (text != null) { renderText(text); textarea.value = text; shot.prompt = promptTextToLines(text); writePlan(); }
                };
                ${fixture.guard}
                ${fixture.capture}
                ${fixture.paste}
                ${fixture.replacement}
                let activeInput = editor;
                function attach() {
                    ${fixture.controller}
                    ${fixture.binding}
                }
                attach();
                return {
                    root, editor, textarea, state, saved, drafts,
                    render(text, caret = text.length) {
                        editor.focus(); renderText(text, caret); textarea.value = text;
                        shot.prompt = promptTextToLines(text); state.promptUndo.reset(text);
                    },
                    text:activePromptText, getCaret:() => selectionTextOffset(editor),
                    settings(patch) { preferences = {...preferences, ...patch};
                        dispatchEvent(new CustomEvent("h3-prompt-editor-settings-changed")); },
                    plain() { state.completion.destroy(); state.decorated = false; editor.hidden = true;
                        textarea.hidden = false; activeInput = textarea; attach(); },
                    referenceEdits:() => referenceEdits, flushes:() => flushes,
                    teardown() { state.completion.destroy(); root.remove(); },
                };
            `;
            const f = Function(setup)();
            const choose = label => {
                const items = [...document.querySelectorAll(".h3pc-menu:not([hidden]) .h3pc-option")];
                const item = items.find(item => item.querySelector(".h3pc-label").textContent === label);
                test(Boolean(item), "Menu lacks " + label);
                item.click();
            };
            const modifierClick = marker => {
                const walker = document.createTreeWalker(f.editor, NodeFilter.SHOW_TEXT);
                let text;
                while ((text = walker.nextNode()) && !text.textContent.includes(marker)) {}
                test(Boolean(text), "Find unstyled marker " + marker);
                const start = text.textContent.indexOf(marker) + 2;
                const range = document.createRange();
                range.setStart(text, start); range.setEnd(text, start + 1);
                const rect = range.getBoundingClientRect();
                text.parentElement.dispatchEvent(new MouseEvent("click", {
                    bubbles:true, cancelable:true, ctrlKey:true,
                    clientX:rect.left + rect.width / 2, clientY:rect.top + rect.height / 2,
                }));
            };
            f.render("Keep <Subject 1> and @Hero");
            const chip = f.editor.querySelector('[data-token="<Subject 1>"]');
            // Alter text before an existing chip without decoration: offsets
            // must be calculated live, including a preceding newline and icons.
            f.editor.firstChild.textContent = "Before\nKeep ";
            chip.click();
            choose("<Subject 2>");
            test(f.text() === "Before\nKeep <Subject 2> and @Hero", "Live chip replacement offsets");
            test(f.saved.at(-1) === f.text() && f.drafts.at(-1).text === f.text(), "Completion saves through current scene");
            f.editor.querySelector('[data-token="@Hero"]').click();
            test(f.referenceEdits() === 1 && !f.state.completion.visible, "Existing reference popup remains authoritative");
            f.editor.querySelector('[data-token="<Subject 2>"]').click();
            choose("Delete <Subject 2>");
            test(f.text() === "Before\nKeep and @Hero", "Delete token without losing other prompt content");
            f.editor.dispatchEvent(new KeyboardEvent("keydown", {key:"z", ctrlKey:true, bubbles:true, cancelable:true}));
            test(f.text() === "Before\nKeep <Subject 2> and @Hero", "Scene-local undo restores token");
            test(f.state.plan.shots[1].prompt[0] === "untouched", "Other scene unchanged");

            let saves = 0, workflowUndos = 0;
            const globalKeys = event => { if (event.key === "s") saves++; if (event.key === "z") workflowUndos++; };
            document.addEventListener("keydown", globalKeys);
            f.editor.dispatchEvent(new KeyboardEvent("keydown", {key:"s", ctrlKey:true, bubbles:true}));
            f.editor.dispatchEvent(new KeyboardEvent("keydown", {key:"z", ctrlKey:true, bubbles:true, cancelable:true}));
            test(saves === 1 && f.flushes() === 1, "Ctrl+S bubbles after flushing Plan");
            test(workflowUndos === 0, "Prompt undo never reaches workflow undo");
            document.removeEventListener("keydown", globalKeys);

            f.render("detailed_description:\n[Shot 2] At");
            f.state.completion.refresh(); choose("At MM:SS.mmm,");
            test(getSelection().toString() === "00.000", "Timestamp selects seconds/milliseconds");
            test(f.text().endsWith("At 00:00.000, "), "Timestamp punctuation");
            f.render("retention_analysis:\n@Hero: weak_reference - explanation");
            f.editor.click();
            test(!f.state.completion.visible, "Ordinary click never opens mid-word completion");
            modifierClick("weak_reference"); choose("fully_preserved");
            test(f.text() === "retention_analysis:\n@Hero: fully_preserved - explanation", "Ctrl-click retention respects tagged family");
            f.render("summary:\n[reference generation + audio reuse]");
            modifierClick("[reference generation"); choose("[audio reference]");
            test(f.text() === "summary:\n[audio reference]", "Ctrl-click chain-specific directive");
            f.render("detailed_description:\n[Shot 2] At 00:01.000, a courier.");
            modifierClick("[Shot 2]"); choose("[Shot 3]");
            test(f.text().includes("[Shot 3] At 00:01.000,"), "Ctrl-click shot preserves timestamp and prose");

            f.settings({automaticSuggestions:false});
            f.render("<Sub");
            test(!f.state.completion.refresh(), "Automatic suggestions can be disabled");
            f.state.completion.handleKeydown(new KeyboardEvent("keydown", {key:" ", code:"Space", ctrlKey:true}));
            choose("<Subject 3>");
            test(f.text() === "<Subject 3>", "Manual completion remains available");
            f.settings({markerReplacement:false});
            f.editor.querySelector("[data-h3-prompt-marker]").click();
            test(!f.state.completion.visible, "Marker click preference");
            f.settings({markerReplacement:true, automaticSuggestions:true});
            f.editor.contentEditable = "false";
            f.editor.querySelector("[data-h3-prompt-marker]").click();
            test(!f.state.completion.visible && !f.state.completion.refresh({manual:true}), "Optimizer-disabled editor cannot be edited through new menus");
            f.editor.contentEditable = "true";
            f.settings({appendCompletionSpace:true});
            f.render("<Sub"); f.state.completion.refresh(); choose("<Subject 5>");
            test(f.text() === "<Subject 5> ", "Optional completion space");
            f.settings({appendCompletionSpace:false});
            f.render("<Sub");
            f.editor.dispatchEvent(new Event("compositionstart"));
            test(!f.state.completion.refresh({manual:true}), "IME composition suppresses completion");
            f.editor.dispatchEvent(new Event("compositionend"));

            f.render("");
            const paste = new Event("paste", {bubbles:true, cancelable:true});
            Object.defineProperty(paste, "clipboardData", {value:{getData:() => "Use <Subject 4>."}});
            f.editor.dispatchEvent(paste);
            test(f.text() === "Use <Subject 4>.", "Paste keeps exact plain prompt text");
            test(Boolean(f.editor.querySelector('[data-token="<Subject 4>"]')), "Pasted token decorated immediately");
            f.editor.querySelector('[data-token="<Subject 4>"]').click();
            f.editor.replaceChildren(document.createTextNode("External edit"));
            test(!f.state.completion.accept() && f.text() === "External edit", "Stale replacement rejected");
            f.render("");
            const multilinePaste = new Event("paste", {bubbles:true, cancelable:true});
            Object.defineProperty(multilinePaste, "clipboardData", {value:{getData:() => "Café <Subject 1>\n\n"}});
            f.editor.dispatchEvent(multilinePaste);
            test(f.text() === f.saved.at(-1), "Paste decoration never removes another trailing newline");
            test(f.text() === "Café <Subject 1>\n", "Unicode and trailing blank line survive decoration");

            if (!fixture.rich) {
                f.plain(); f.textarea.value = "detailed_description:\n[Shot 2] At";
                f.textarea.focus(); f.textarea.setSelectionRange(f.textarea.value.length, f.textarea.value.length);
                f.state.completion.refresh(); choose("At MM:SS.mmm,");
                test(f.textarea.value.slice(f.textarea.selectionStart, f.textarea.selectionEnd) === "00.000", "Plain editor timestamp selection");
            }
            f.state.completion.refresh({manual:true});
            f.teardown();
            test(document.querySelectorAll(".h3pc-menu").length === 0, "Scene disposal removes completion menu");
        } catch (error) { report.failures.push((fixture.rich ? "rich: " : "regular: ") + error.stack); }
    }
    document.getElementById("report").textContent = JSON.stringify(report);
    document.getElementById("report").dataset.report = btoa(unescape(encodeURIComponent(JSON.stringify(report))));
}
