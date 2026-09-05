#!/usr/bin/env node

// Exercise the actual Studio resize/render/request handlers with a small DOM
// fixture. No ComfyUI server, project writes or media generation is involved.
import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import {
    matchingStudioSourceAudio,
    studioNearestH3FrameLength,
    studioSourceAudioSecond,
    studioTimelineSegments,
    studioWaveformIntervalSamples,
} from "../web/h3_chain_plan_studio_core.mjs";

const source = fs.readFileSync(new URL(
    "../web/h3_chain_plan_studio.js", import.meta.url,
), "utf8");
function handler(name) {
    const match = source.match(new RegExp(
        `^    (?:async )?function ${name}\\([^]*?^    }$`, "m",
    ));
    assert.ok(match, `Missing production handler ${name}`);
    return match[0];
}

function element(tag, className = "", textContent = "") {
    const listeners = new Map();
    return {
        tag, className, textContent, children:[], dataset:{},
        style:{setProperty() {}},
        append(...children) { this.children.push(...children); },
        replaceChildren(...children) { this.children = children; },
        addEventListener(type, fn) { listeners.set(type, fn); },
        removeEventListener(type) { listeners.delete(type); },
        dispatch(type, data = {}) {
            listeners.get(type)?.({
                button:0, pointerId:1, preventDefault() {}, stopPropagation() {},
                ...data,
            });
        },
        getBoundingClientRect() { return {width:345}; },
    };
}

const audio = {
    available:true, timeline_available:true, has_audio:true,
    frame_count:690, duration_seconds:690 / 24,
    available_frame_count:2400, available_duration_seconds:100,
    seek_seconds:2,
};
const payload = {run_name:"studio", token:"original", source_audio:audio};
const originalPayload = JSON.stringify(payload);
const state = {
    plan:{shots:[
        {id:"one", length:345, source_audio_target:"on"},
        {id:"two", length:345, audio_reference:"on"},
    ]},
    sourcePreview:payload,
    sourceWaveform:null, sourceWaveformToken:"", sourceWaveformPromise:null,
    sourceAudioTimelineHost:element("div"),
    timelineSegments:[], timelineWidths:[], active:0, disposed:false,
    editorial:{trims:[], placements:[]},
    timelineContent:{dataset:{timelineWidth:690}},
};
let currentRun = "studio";
let workspaceFrames = 690;
let writes = 0;
const requests = [];
const drawn = [];
const node = {properties:{h3_plan_studio_source_audio_mutes:{"studio::two":true}}};
function timing() {
    return {shots:state.plan.shots.map((shot) => ({
        id:shot.id, rawFrames:shot.length, deliveredFrames:shot.length,
        deliveredSeconds:shot.length / 24,
    }))};
}
function timelineModel() {
    const result = timing();
    const segments = studioTimelineSegments(
        result.shots, state.editorial.placements, workspaceFrames,
        state.editorial.trims,
    );
    return {result, segments, totalSeconds:segments.at(-1)?.endSeconds ?? 0};
}
const context = vm.createContext({
    state, node, URLSearchParams, FPS:24, matchingStudioSourceAudio,
    studioWaveformIntervalSamples, studioNearestH3FrameLength,
    SOURCE_AUDIO_MUTES_PROPERTY:"h3_plan_studio_source_audio_mutes",
    timing, timelineModel, runName:() => currentRun,
    element, button:(label) => element("button", "", label),
    formatClock:(value) => String(value), automaticSceneColor:() => "#fff",
    drawSourceWaveform:(_canvas, samples) => drawn.push(samples),
    selectScene() {}, sceneLocked:() => false,
    writePlan() { writes += 1; },
    trailingGapSegment:() => state.timelineSegments.find((item) => item.trailing),
    api:{
        apiURL:(url) => url,
        fetchApi(url) {
            return new Promise((resolve) => requests.push({url, resolve}));
        },
    },
});
vm.runInContext([
    "sourceAudio", "sourceAudioUrl", "sourceWaveformUrl",
    "sourceAudioMuteMap", "sourceAudioMuted", "loadSourceWaveform",
    "renderSourceAudioTimeline", "enableSceneDurationDrag",
].map(handler).join("\n"), context);
function render() {
    state.timelineSegments = timelineModel().segments;
    drawn.length = 0;
    context.renderSourceAudioTimeline();
}
context.renderShell = render;
function waveform(frames) {
    return {
        frame_count:frames, points_per_second:24,
        samples:Array.from({length:frames}, (_, index) => index / 10000),
    };
}
async function respond(request, frames, ok = true) {
    request.responded = true;
    request.resolve({
        ok, status:ok ? 200 : 500,
        json:async () => ok ? waveform(frames) : {error:"waveform unavailable"},
    });
    // Flush the request, JSON read, redraw and loader's finally handler.
    await new Promise((resolve) => setImmediate(resolve));
}

render();
assert.equal(requests.length, 1);
await respond(requests[0], 690);
assert.equal(state.sourceAudioTimelineHost.children.length, 2);
const originalAudioUrl = context.sourceAudioUrl();
assert.ok(originalAudioUrl.includes("token=original"));

// Pointer resizing changes the generated frame count on the real handler.
const card = element("div");
const handle = element("span");
context.enableSceneDurationDrag(card, handle, 0);
handle.dispatch("pointerdown", {clientX:0});
handle.dispatch("pointermove", {clientX:17});
handle.dispatch("pointerup", {clientX:17});
assert.equal(state.plan.shots[0].length, 362);
assert.equal(writes, 1);
assert.equal(context.sourceAudio(), audio);
assert.equal(context.sourceAudioUrl(), originalAudioUrl);
assert.equal(state.sourceAudioTimelineHost.children.length, 2);
assert.match(state.sourceAudioTimelineHost.children[1].className, /audio-muted/);
assert.equal(requests.length, 2, "Resize must extend cached waveform coverage");
assert.equal(state.sourceWaveform.frame_count, 690, "Keep old coverage visible");
assert.equal(drawn[1][0], 362 / 10000, "Scene 2's waveform follows its new start");
assert.equal(studioSourceAudioSecond(audio, state.timelineSegments[1].startSeconds),
    2 + 362 / 24, "Playback seeks in the original source file, without stretching");
assert.equal(drawn[1].at(-1), 0, "Pending extension must not stretch cached samples");

// Re-rendering while a larger waveform is loading must not duplicate requests.
render();
assert.equal(requests.length, 2);
await respond(requests[1], 707);
render();
assert.equal(drawn[1].at(-1), 706 / 10000);
assert.equal(requests.length, 2, "Successful redraw must not loop requests");

// Numeric frame edits, shrinking, undo/redo and added scenes retain the track.
for (const frames of [175, 396, 345, 396]) {
    state.plan.shots[0].length = frames;
    render();
    assert.equal(context.sourceAudioUrl(), originalAudioUrl);
    assert.equal(state.sourceAudioTimelineHost.children.filter(
        (card) => card.dataset.sceneIndex != null,
    ).length, 2);
}
const inFlight = requests.slice(2);
const newest = inFlight.at(-1);
await respond(newest, 741);
for (const request of inFlight.slice(0, -1).reverse()) {
    await respond(request, Number(new URL(
        request.url, "http://test",
    ).searchParams.get("frame_count")));
}
assert.equal(state.sourceWaveform.frame_count, 741, "Ignore stale resize responses");
state.plan.shots.push({id:"three", length:345});
render();
assert.equal(state.sourceAudioTimelineHost.children.length, 3);
await respond(requests.at(-1), 1086);

// Trim and placement edits realign windows, without changing audio policy.
state.editorial.trims = [{scene_id:"one", out_frame:90}];
render();
assert.equal(state.timelineSegments[1].startFrame, 90);
assert.equal(drawn[1][0], 90 / 10000);
state.editorial.placements = [{scene_id:"two", start_frame:120}];
render();
assert.equal(state.timelineSegments[1].kind, "gap");
assert.equal(drawn[2][0], 120 / 10000);
assert.equal(context.sourceAudioUrl(), originalAudioUrl);
assert.equal(state.plan.shots[0].source_audio_target, "on");
assert.equal(state.plan.shots[1].audio_reference, "on");
assert.equal(JSON.stringify(payload), originalPayload, "Never rewrite source identity");

// A longer workspace requests coverage only through the real source duration.
workspaceFrames = 3000;
render();
assert.equal(new URL(requests.at(-1).url, "http://test").searchParams.get("frame_count"), "2400");
await respond(requests.at(-1), 2400);
const coveredRequestCount = requests.length;
workspaceFrames = 4000;
render();
assert.equal(requests.length, coveredRequestCount);

// Switching runs cannot retain source audio, even while the old payload lingers.
currentRun = "another-run";
render();
assert.equal(context.sourceAudio(), null);
assert.equal(context.sourceAudioUrl(), "");
assert.equal(state.sourceAudioTimelineHost.children.length, 1);
state.sourcePreview = {...payload, run_name:currentRun, token:"replacement"};
render();
assert.equal(state.sourceWaveform, null);
assert.ok(context.sourceAudioUrl().includes("token=replacement"));
render();
await respond(requests.at(-1), 2400, false);
assert.equal(state.sourceWaveform.error, "waveform unavailable");
assert.equal(context.sourceAudio(), audio, "Waveform errors do not disable audio");
const failedRequestCount = requests.length;
render();
assert.equal(requests.length, failedRequestCount, "No error/re-render request loop");

state.sourcePreview = {...payload, run_name:currentRun, source_audio:{available:false}};
render();
assert.equal(context.sourceAudioUrl(), "", "An explicitly removed source stays off");
for (const request of requests.filter((item) => !item.responded)) {
    await respond(request, Number(new URL(
        request.url, "http://test",
    ).searchParams.get("frame_count")));
}
assert.equal(state.sourceWaveform.error, "waveform unavailable",
    "Late responses from the previous source must not repopulate its waveform");

console.log("H3 Plan Studio source audio: resize, waveform, seek and run isolation pass");
