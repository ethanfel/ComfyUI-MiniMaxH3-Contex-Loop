import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import {sceneLipSyncMode, applySceneLipSync} from "../web/h3_policy_core.mjs";
import {projectAudioTrackBindings, setProjectAudioTrack} from "../web/h3_project_asset_editor_core.mjs";

const shot = {id: "singing", prompt: "Keep me", length: 73};
assert.equal(sceneLipSyncMode(shot), "inherit");
applySceneLipSync(shot, "on");
assert.equal(sceneLipSyncMode(shot), "on");
assert.equal(shot.source_audio_target, "locked");
assert.equal(shot.source_reference, "off");
assert.equal(shot.generated_continuity, "off");
applySceneLipSync(shot, "off");
assert.equal(sceneLipSyncMode(shot), "off");
assert.equal(shot.source_audio_target, "off");
assert.equal(shot.source_reference, "off");
assert.equal(shot.generated_continuity, "off");
shot.source_reference = "on";
assert.equal(sceneLipSyncMode(shot), "custom");
applySceneLipSync(shot, "inherit");
assert.deepEqual(shot, {id: "singing", prompt: "Keep me", length: 73});
assert.throws(() => applySceneLipSync(shot, "custom"));
assert.equal(Object.hasOwn(shot, "final_audio"), false);

const asset = {id: "mix", options: {unrelated: true}};
assert.deepEqual(projectAudioTrackBindings(asset), {full_mix: "mix", vocals: "", instrumental: ""});
asset.options.audio_tracks = setProjectAudioTrack(asset, "vocals", "voice");
assert.deepEqual(projectAudioTrackBindings(asset), {full_mix: "mix", vocals: "voice", instrumental: ""});
asset.options.audio_tracks = setProjectAudioTrack(asset, "full_mix", "");
assert.deepEqual(projectAudioTrackBindings(asset), {full_mix: "", vocals: "voice", instrumental: ""});
assert.throws(() => setProjectAudioTrack(asset, "vocals", ""));
asset.options.audio_tracks = setProjectAudioTrack(asset, "instrumental", "voice");
assert.deepEqual(projectAudioTrackBindings(asset), {full_mix: "", vocals: "", instrumental: "voice"});
assert.equal(asset.options.unrelated, true);
assert.throws(() => setProjectAudioTrack(asset, "unknown", "voice"));
asset.options.audio_tracks = null;
assert.equal(projectAudioTrackBindings(asset).full_mix, "mix");

// Both production editors use the same policy helper and persistence paths;
// no new JSON field or shifted serialized widget is required.
for (const file of ["h3_chain_plan_studio.js", "h3_chain_plan_editor.js"]) {
    const source = fs.readFileSync(new URL(`../web/${file}`, import.meta.url), "utf8");
    assert.match(source, /applySceneLipSync\(shot, lipSync.value\)/);
    assert.match(source, /lipSync.value = sceneLipSyncMode\(shot\)/);
    assert.match(source, /Lip-sync/);
    const start = source.indexOf('const lipSync = element("select");');
    const stop = source.indexOf("function audioOverrideSelect", start);
    const current = {id: "kept", prompt: "Untouched", length: 73};
    const controls = [];
    let saves = 0;
    const sandbox = {
        shot: current, planAudioPolicy: {sourceAudioTarget: "locked"},
        applySceneLipSync, sceneLipSyncMode,
        element: () => {
            const control = {append() {}, addEventListener(event, callback) { this[event] = callback; }};
            controls.push(control); return control;
        },
        form: {append() {}}, field() {},
        syncPlan() { saves++; }, writePlan() { saves++; },
        render() {}, renderScenePanel() {}, renderStatus() {},
    };
    vm.runInNewContext(source.slice(start, stop), sandbox);
    const select = controls[0];
    for (const mode of ["on", "off", "inherit"]) {
        select.value = mode; select.change();
        assert.equal(sceneLipSyncMode(current), mode);
    }
    assert.equal(saves, 3);
    assert.deepEqual(current, {id: "kept", prompt: "Untouched", length: 73});
}
const carousel = fs.readFileSync(new URL("../web/h3_project_asset_manager.js", import.meta.url), "utf8");
assert.match(carousel, /setProjectAudioTrack\(asset, role, select.value\)/);
assert.match(carousel, /audio_tracks: null/);
console.log("Audio tracks UI: shared scene On/Off/Inheritance and safe Carousel role selectors pass");
