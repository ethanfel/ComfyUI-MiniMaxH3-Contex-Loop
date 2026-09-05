import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import {
    locateStudioTimelineSegment, studioEditorialSceneStartSeconds,
    studioPlayerSegmentClock, studioSourceAudioSecond, studioSourceSecond,
    studioTimelineSegments,
} from "../web/h3_chain_plan_studio_core.mjs";

// Exercise the actual seek/audio-mix/source-clock handlers without a server,
// media generation or project writes. Browser timeupdate follows the seek.
const source = fs.readFileSync(new URL("../web/h3_chain_plan_studio.js", import.meta.url), "utf8");
function handler(name) {
    const match = source.match(new RegExp(`^    function ${name}\\([^]*?^    }$`, "m"));
    assert.ok(match, name);
    return match[0];
}
function closure(name) {
    const match = source.match(new RegExp(`^        const ${name} = [^]*?^        };$`, "m"));
    assert.ok(match, name);
    return match[0];
}
function media() {
    const listeners = new Map();
    return {
        dataset:{}, currentTime:0, duration:300, playbackRate:1, paused:true,
        isConnected:true,
        pause() { this.paused = true; },
        play() { this.paused = false; return Promise.resolve(); },
        removeAttribute(name) { delete this[name]; },
        load() { this.currentTime = 0; },
        addEventListener(name, callback) {
            const list = listeners.get(name) ?? [];
            list.push(callback); listeners.set(name, list);
        },
        metadata() {
            const callbacks = listeners.get("loadedmetadata") ?? [];
            listeners.delete("loadedmetadata");
            for (const callback of callbacks) callback();
        },
    };
}
const rows = [
    {id:"written", deliveredFrames:2311},
    {id:"no_video", deliveredFrames:306},
    {id:"rendered", deliveredFrames:240},
];
const segments = studioTimelineSegments(rows, [], 3600);
const model = {result:{shots:rows}, segments, totalSeconds:150};
const video = media();
const generatedAudio = media();
const sourceVideo = media();
const sourceTimelineAudio = media();
const descriptor = {seek_seconds:2, available_duration_seconds:300};
let hasSourceAudio = true;
const slider = {}; const clock = {};
const state = {
    plan:{shots:rows}, active:0, playerIndex:0, playerSegmentKey:"scene:0",
    timelinePosition:0, player:video, playerAudio:generatedAudio,
    sourcePlayer:sourceVideo, sourceAudioPlayer:sourceTimelineAudio,
    playerSlider:slider,
};
let redLine = null; let subtitlePosition = null;
const generatedToggle = {checked:true, dispatchEvent() { context.applyAudioMix(); }};
const context = vm.createContext({
    state, video, generatedAudio, sourceVideo, sourceTimelineAudio, slider, clock,
    generatedToggle, sourceToggle:{checked:true}, motionToggle:{checked:false},
    Event, FPS:24, timelineModel:() => model, timing:() => model.result,
    locateStudioTimelineSegment, studioEditorialSceneStartSeconds,
    studioPlayerSegmentClock, studioSourceAudioSecond, studioSourceSecond,
    sourceAudio:() => hasSourceAudio ? descriptor : null,
    sourceAudioUrl:() => "source.wav", sourceAudioMuted:() => false,
    sourceReference:() => null, sourcePreviewUrl:() => "",
    playerCheckpoint:index => index === 1 ? null : {video:`scene_${index}.mp4`},
    videoUrl:value => value, formatClock:value => String(value),
    root:{querySelector:selector => selector === ".h3studio-audio-generated" ? generatedToggle : null,
        querySelectorAll:() => []},
    persistView(){}, renderSourceTimeline(){}, renderSourceAudioTimeline(){},
    updateTimelineSelection(){}, revealActiveTimelineScene(){}, publishActiveScene(){},
    applyAudioVolumes(){}, synchronizeGeneratedAudio(){},
    positionTimelinePlayhead:value => { redLine = value; },
    updateSubtitleOverlay:value => { subtitlePosition = value; },
});
vm.runInContext([
    handler("seekTimeline"),
    ...["playerTimelineSecond", "synchronizeSourceTimelineAudio", "updateTransportPosition",
        "sourceTimelineSecond", "refreshSourceTransport", "applyAudioMix"].map(closure),
    "globalThis.applyAudioMix = applyAudioMix;",
    "globalThis.refreshSourceTransport = refreshSourceTransport;",
    "globalThis.synchronizeSourceTimelineAudio = synchronizeSourceTimelineAudio;",
    "globalThis.playerTimelineSecond = playerTimelineSecond;",
].join("\n"), context);

function assertPosition(target, label) {
    assert.equal(state.timelinePosition, target, label);
    assert.equal(Number(slider.value), target, `${label}: slider`);
    assert.equal(redLine, target, `${label}: red playhead`);
    assert.equal(subtitlePosition, target, `${label}: subtitles`);
}
function seekAndLoad(target) {
    context.seekTimeline(target);
    video.metadata(); sourceTimelineAudio.metadata();
    // canplay and monitor toggles both use this default synchronization clock.
    context.synchronizeSourceTimelineAudio(false);
    if (hasSourceAudio) context.refreshSourceTransport();
}

seekAndLoad(100.5);
assertPosition(100.5, "an unrendered scene retains the clicked timeline position");
assert.equal(sourceTimelineAudio.currentTime, 102.5, "source offset is preserved");
assert.equal(state.active, 1);
// Repeated seeks and toggling audio must not reset a media-less video to zero.
seekAndLoad(105);
context.applyAudioMix(); context.refreshSourceTransport();
assertPosition(105, "monitor changes preserve an unrendered scene's position");
sourceTimelineAudio.currentTime = 108;
context.refreshSourceTransport();
context.applyAudioMix(); context.refreshSourceTransport();
assertPosition(106, "source playback remains the clock when no video exists");

seekAndLoad(115);
assertPosition(115, "rendered scenes still use the local video clock");
const renderedStart = segments.find(item => item.sceneIndex === 2 && item.kind === "scene").startSeconds;
video.currentTime = 3;
context.synchronizeSourceTimelineAudio(false);
assert.equal(sourceTimelineAudio.currentTime, renderedStart + 3 + descriptor.seek_seconds);

seekAndLoad(135);
assertPosition(135, "black editorial gaps preserve the absolute position too");
hasSourceAudio = false;
seekAndLoad(101);
assert.equal(context.playerTimelineSecond(), 101, "no video and no audio still has a timeline clock");
assertPosition(101, "silent unrendered scene remains seekable");
console.log("Studio seek: unrendered scenes, source audio, monitor changes, video and black gaps pass");
