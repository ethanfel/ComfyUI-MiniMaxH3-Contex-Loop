#!/usr/bin/env node

import assert from "node:assert/strict";
import fs from "node:fs";
import {
    locateStudioTimelineSegment,
    locateStudioTimelineSecond,
    h3StudioGridMarkers,
    matchingStudioCheckpoint,
    matchingStudioSourceAudio,
    matchingStudioSourceScene,
    parseStudioTimecode,
    parseTimedLyrics,
    studioCheckpointSignature,
    studioContextWindowLayout,
    studioContextWindowStartAtRatio,
    studioEditorialSceneStartSeconds,
    studioNearestH3FrameLength,
    studioRulerTicks,
    studioSceneStartSeconds,
    studioSourceAudioSecond,
    studioSourceSecond,
    studioTimelineLayout,
    studioTimelineSegments,
    studioTimelineTotalSeconds,
    studioWaveformIntervalSamples,
    studioWaveformSceneSamples,
    timedLyricAtSecond,
} from "../web/h3_chain_plan_studio_core.mjs";
import {
    applySceneTransitionPreset,
    sceneTransitionPreset,
} from "../web/h3_policy_core.mjs";

const studioBoundary = {};
assert.equal(sceneTransitionPreset(studioBoundary), "inherit");
applySceneTransitionPreset(studioBoundary, "soft_av");
assert.deepEqual(studioBoundary, {
    continuation_mode: "audio_feathered_av", context_length: 39,
    audio_context_length: 39,
});

const rows = [
    {id:"one", deliveredFrames:362, deliveredSeconds:362 / 24},
    {id:"two", deliveredFrames:340, deliveredSeconds:340 / 24},
    {id:"three", deliveredFrames:340, deliveredSeconds:340 / 24},
];
assert.equal(studioSceneStartSeconds(rows, 1), 362 / 24);
assert.equal(locateStudioTimelineSecond(rows, 0).index, 0);
assert.equal(locateStudioTimelineSecond(rows, 362 / 24).index, 1);
assert.equal(locateStudioTimelineSecond(rows, 999).index, 2);
assert.ok(Math.abs(
    locateStudioTimelineSecond(rows, 362 / 24 + 1).localSeconds - 1,
) < 1e-9);

const fittedTimeline = studioTimelineLayout(rows, 600, 1);
assert.equal(fittedTimeline.zoom, 1);
assert.ok(Math.abs(
    fittedTimeline.widths.reduce((total, value) => total + value, 0) - 600,
) < 1e-9);
assert.ok(fittedTimeline.widths[0] > fittedTimeline.widths[1]);
const expandedTimeline = studioTimelineLayout(rows, 600, 2);
assert.equal(expandedTimeline.contentWidth, 1200);
assert.ok(expandedTimeline.widths.every(
    (value, index) => value > fittedTimeline.widths[index],
));
assert.equal(studioTimelineLayout(rows, 600, .25).zoom, 1);
assert.equal(studioTimelineLayout(rows, 600, 20).zoom, 6);

const placedTimeline = studioTimelineSegments(rows, [
    {scene_id:"two", start_frame:480},
]);
assert.deepEqual(placedTimeline.map((segment) => segment.kind), [
    "scene", "gap", "scene", "scene",
]);
assert.equal(placedTimeline[1].startFrame, 362);
assert.equal(placedTimeline[1].durationFrames, 118);
assert.equal(placedTimeline[2].startFrame, 480);
assert.equal(studioEditorialSceneStartSeconds(placedTimeline, 1), 20);
assert.equal(studioTimelineTotalSeconds(placedTimeline), 1160 / 24);
assert.equal(locateStudioTimelineSegment(
    placedTimeline, 18,
).kind, "gap");
assert.equal(locateStudioTimelineSegment(
    placedTimeline, 20,
).sceneIndex, 1);
const placedLayout = studioTimelineLayout(
    rows, 600, 1, [{scene_id:"two", start_frame:480}],
);
assert.equal(placedLayout.segments.length, 4);
assert.ok(Math.abs(
    placedLayout.widths.reduce((total, value) => total + value, 0) - 600,
) < 1e-9);
const openTimeline = studioTimelineLayout(rows, 600, 1, [], 2042);
assert.equal(openTimeline.sceneEndSeconds, 1042 / 24);
assert.equal(openTimeline.totalSeconds, 2042 / 24);
assert.equal(openTimeline.contentWidth, 600 * 2042 / 1042);
assert.equal(openTimeline.segments.at(-1).key, "gap:tail");
assert.equal(openTimeline.segments.at(-1).trailing, true);
assert.ok(Math.abs(
    openTimeline.widths.slice(0, 3).reduce((total, value) => total + value, 0)
        - 600,
) < 1e-9);
assert.equal(locateStudioTimelineSegment(
    openTimeline.segments, 70,
).key, "gap:tail");
assert.equal(studioNearestH3FrameLength(345), 345);
assert.equal(studioNearestH3FrameLength(354), 362);
assert.equal(studioNearestH3FrameLength(6, 23), 39);
assert.equal(parseStudioTimecode("90.5"), 90.5);
assert.equal(parseStudioTimecode("15.000s"), 15);
assert.equal(parseStudioTimecode("1:30.5"), 90.5);
assert.equal(parseStudioTimecode("1:02:03"), 3723);
assert.throws(() => parseStudioTimecode("1:bad"));
assert.ok(studioRulerTicks(90, 900).some((tick) => tick.major));

const lrcCues = parseTimedLyrics(
    "[00:01.5]First line\n[00:03.25]Second line",
);
assert.equal(lrcCues[0].startSeconds, 1.5);
assert.equal(lrcCues[0].endSeconds, 3.25);
assert.equal(timedLyricAtSecond(lrcCues, 2)?.text, "First line");
assert.equal(timedLyricAtSecond(lrcCues, 4)?.text, "Second line");
const srtCues = parseTimedLyrics(
    "1\n00:00:02,000 --> 00:00:04,500\nA subtitle\n",
);
assert.deepEqual(srtCues, [{
    startSeconds:2, endSeconds:4.5, text:"A subtitle",
}]);

const contextWindow = studioContextWindowLayout(340, 39, 100);
assert.deepEqual(contextWindow, {
    delivered:340, span:39, latest:301, start:100, end:139,
    leftFraction:100 / 340, widthFraction:39 / 340,
});
assert.equal(studioContextWindowLayout(340, 39, 999).start, 301);
assert.equal(studioContextWindowStartAtRatio(340, 39, 0), 0);
assert.equal(studioContextWindowStartAtRatio(340, 39, .5), 151);
assert.equal(studioContextWindowStartAtRatio(340, 39, 1), 301);

const checkpoints = new Map([[1, {
    scene:1, scene_id:"one", ready:true, delivered_frames:362,
    video:{filename:"one.mp4"}, audio:{filename:"one.wav"},
}]]);
assert.equal(matchingStudioCheckpoint(checkpoints, 0, rows[0]).scene_id, "one");
assert.equal(matchingStudioCheckpoint(checkpoints, 0, {...rows[0], id:"renamed"}), null);
assert.equal(matchingStudioCheckpoint(checkpoints, 0, {...rows[0], deliveredFrames:340}), null);
assert.notEqual(
    studioCheckpointSignature("run-a", [...checkpoints.values()]),
    studioCheckpointSignature("run-b", [...checkpoints.values()]),
);
assert.notEqual(
    studioCheckpointSignature("run-a", [...checkpoints.values()]),
    studioCheckpointSignature("run-a", [{
        ...checkpoints.get(1), audio:{filename:"changed.wav"},
    }]),
);

const sourceTimeline = {token:"opaque", source_audio:{
    available:true, frame_count:1042, seek_seconds:2,
    duration_seconds:1042 / 24, available_frame_count:2000,
    available_duration_seconds:2000 / 24,
}, scenes:[{
    scene:2, scene_id:"two", delivered_frames:340,
    references:[{frame_count:362, compare_offset_frames:22}],
}]};
assert.equal(
    matchingStudioSourceScene(sourceTimeline, 1, rows[1]).scene_id, "two",
);
assert.equal(matchingStudioSourceScene(sourceTimeline, 0, rows[0]), null);
assert.equal(
    matchingStudioSourceScene(sourceTimeline, 1, {...rows[1], deliveredFrames:339}),
    null,
);
assert.ok(Math.abs(studioSourceSecond(
    sourceTimeline.scenes[0].references[0], 1,
) - (22 / 24 + 1)) < 1e-9);
assert.equal(
    matchingStudioSourceAudio(sourceTimeline, rows).frame_count, 1042,
);
assert.equal(
    matchingStudioSourceAudio(
        sourceTimeline, [{...rows[0], deliveredFrames:361}, ...rows.slice(1)],
    ),
    null,
);
assert.ok(Math.abs(
    studioSourceAudioSecond(sourceTimeline.source_audio, 3) - 5,
) < 1e-9);
assert.deepEqual(
    studioWaveformSceneSamples(
        {points_per_second:2, samples:Array.from({length:90}, (_value, index) => index)},
        rows, 1,
    ).slice(0, 2),
    [30, 31],
);
assert.deepEqual(
    studioWaveformIntervalSamples(
        {points_per_second:2, samples:Array.from({length:90}, (_value, index) => index)},
        2.5, 1.5,
    ),
    [5, 6, 7],
);

const exactGrid = h3StudioGridMarkers(345, 39, "masked_av");
assert.deepEqual(exactGrid.raw, {
    frames:345, onGrid:true, index:20, label:"345f = 17×20+5",
});
assert.equal(exactGrid.av.exact, true);
assert.equal(exactGrid.av.audioTicks, 65);
assert.deepEqual(exactGrid.cut, {
    start:337, end:340, experimental:true, label:"cut test 337–340f",
});
const fractionalGrid = h3StudioGridMarkers(362, 22, "feathered_av");
assert.equal(fractionalGrid.raw.onGrid, true);
assert.equal(fractionalGrid.av.exact, false);
assert.equal(fractionalGrid.av.label, "22f AV = 36.667 audio ticks");
const fiveFrameVideoOnlyGrid = h3StudioGridMarkers(
    345, 5, "masked_av", false,
);
assert.equal(fiveFrameVideoOnlyGrid.av.exact, true);
assert.equal(fiveFrameVideoOnlyGrid.av.audioAligned, false);
assert.equal(fiveFrameVideoOnlyGrid.av.audioPreserved, false);
assert.equal(fiveFrameVideoOnlyGrid.av.label, "5f video-only AV");
const audioFeatherGrid = h3StudioGridMarkers(345, 39, "audio_feathered_av");
assert.equal(audioFeatherGrid.av.exact, true);
assert.equal(audioFeatherGrid.av.audioTicks, 65);
const detailAvGrid = h3StudioGridMarkers(345, 39, "tapered_av");
assert.equal(detailAvGrid.av.exact, true);
assert.equal(detailAvGrid.av.audioTicks, 65);
const driftAvGrid = h3StudioGridMarkers(345, 39, "drift_control_av");
assert.equal(driftAvGrid.av.exact, true);
assert.equal(driftAvGrid.av.audioTicks, 65);
assert.equal(h3StudioGridMarkers(344, 39, "guide").raw.onGrid, false);
assert.equal(h3StudioGridMarkers(344, 39, "guide").av, null);

const source = fs.readFileSync(
    new URL("../web/h3_chain_plan_studio.js", import.meta.url),
    "utf8",
);

assert.match(source, /MiniMaxH3ChainPlanStudio/);
assert.match(source, /MiniMaxH3ChainPlan/);
assert.match(source, /item\.name === name/);
assert.match(source, /state\.planWidget\.value = value/);
assert.match(source, /h3studio-timeline/);
assert.match(source, /h3studio-chapter-marker/);
assert.match(source, /\+ Chapter/);
assert.match(source, /function renderChapterPanel/);
assert.match(source, /zero-duration editorial note/);
assert.match(source, /Editorial context, lyrics, LLM notes/);
assert.match(source, /minimax_h3_context_loop\/editorial/);
assert.match(source, /scheduleEditorialSave/);
assert.match(source, /TIMELINE_ZOOM_PROPERTY/);
assert.match(source, /studioTimelineLayout/);
assert.match(source, /Fit timeline/);
assert.match(source, /Ctrl\/Cmd \+ wheel/);
assert.match(source, /Scene prompt/);
assert.match(source, /Shared prompt/);
assert.match(source, /Plan settings/);
assert.match(source, /\["context","Context"\]/);
assert.match(source, /renderContextPanel/);
assert.match(source, /Tail \(default\)/);
assert.match(source, /Start at playhead/);
assert.match(source, /Play selection/);
assert.match(source, /h3studio-context-window/);
assert.match(source, /studioContextWindowStartAtRatio/);
assert.match(source, /nativeContextWindowStarts/);
assert.match(source, /native latent crop/);
assert.match(source, /visual_context_start_frame/);
assert.match(source, /visual_context_lead_start_frame/);
assert.match(source, /Composed context first source/);
assert.match(source, /Composed total \/ split/);
assert.match(source, /visualContextCompositions/);
assert.match(source, /Standalone mode · this node owns, validates, and outputs/);
assert.match(source, /Connected mode · changes are written to the H3 Chain Plan and mirrored into Studio/);
assert.match(source, /const planOwner = planNode \?\? node/);
assert.match(source, /mirrorConnectedPlan\(planNode\)/);
assert.match(source, /state\.planOwner = planOwner/);
assert.match(source, /writePlanSetting\("base_seed", parsed\.toString\(\)\)/);
assert.match(source, /field\("Run name"/);
assert.match(source, /field\("Generation fingerprint"/);
assert.match(source, /inputConnected\(owner, "project_assets"\)/);
assert.match(source, /reference-derived generation fingerprint are managed by connected Project Assets/);
assert.match(source, /disconnect Project Assets to edit them/);
assert.equal((source.match(/field\("Default seconds"/g) ?? []).length, 1);
assert.equal((source.match(/field\("Default steps"/g) ?? []).length, 1);
assert.doesNotMatch(source, /blank = Plan widget/);
assert.match(source, /field\("Context encoding"/);
assert.match(source, /field\("Continuation implementation"/);
assert.match(source, /Generated playback/);
assert.match(source, /MOTION REF/);
assert.match(source, /plan-studio\/source-preview/);
assert.match(source, /plan-studio\/source-audio/);
assert.match(source, /plan-studio\/source-waveform/);
assert.match(source, /plan-studio\/presentation/);
assert.match(source, /plan-studio\/checkpoint-thumbnail/);
assert.match(source, /function refreshTimelineCheckpoints/);
assert.match(source, /h3studio-card-thumbnail/);
assert.match(source, /image\.loading = "lazy"/);
assert.doesNotMatch(
    source,
    /const preview = checkpoint\?\.preview_video[\s\S]{0,800}element\("video"\)/,
);
assert.match(source, /SOURCE AUDIO/);
assert.match(source, /SOURCE_AUDIO_MUTES_PROPERTY/);
assert.match(source, /studioSourceAudioSecond/);
assert.match(source, /studioWaveformIntervalSamples/);
assert.match(source, /Editorial start/);
assert.match(source, /Black editorial gap/);
assert.match(source, /OPEN TIMELINE/);
assert.match(source, /extendTimelineWorkspace/);
assert.match(source, /locked_scene_ids/);
assert.match(source, /h3studio-resize-handle/);
assert.match(source, /17n\+5 frame grid/);
assert.match(source, /Unlock all/);
assert.match(source, /Unlock scene/);
assert.match(source, /requestedStart > previousEnd/);
assert.match(source, /meaningfulPlacements/);
assert.match(source, /card\.addEventListener\("pointerdown", startDrag\)/);
assert.match(source, /window\.addEventListener\("pointermove", onMove, true\)/);
assert.match(source, /Drag the clip or this Move handle/);
assert.doesNotMatch(source, /locked \? "🔒" : "🔓"/);
assert.match(source, /SUBTITLES/);
assert.match(source, /Source Timeline connected · no audio/);
assert.match(source, /No active path-backed motion reference in this Plan/);
assert.match(source, /state\.sourceLayer\.hidden = !hasMotion/);
assert.match(source, /h3studio-audio-generated/);
assert.match(source, /h3studio-audio-source/);
assert.match(source, /GENERATED_VOLUME_PROPERTY/);
assert.match(source, /h3studio-audio-volume/);
assert.match(source, /primeNextSegment/);
assert.match(source, /h3studio-handoff-frame/);
assert.match(source, /event\.code !== "Space"/);
assert.match(source, /const pausePlayerMonitors = \(\) =>/);
assert.match(source, /state\.togglePlayerPlayback/);
assert.match(source, /const playPlayerTransport = \(\) =>/);
assert.match(source, /sourceTimelineAudio\.addEventListener\("timeupdate"/);
assert.match(source, /autoplay && !generated/);
assert.match(source, /state\.sourceAudioPlayer/);
assert.doesNotMatch(source, /const handingOff = video\.ended/);
assert.match(source, /document\.removeEventListener\("keydown", onPlayerKeydown/);
assert.match(source, /Generated and Source Track can play together/);
assert.doesNotMatch(source, /h3studio-audio-choice/);
assert.match(source, /h3_plan_studio_source_timeline/);
assert.match(source, /\/minimax_h3_context_loop\/checkpoints/);
assert.match(source, /include_graph:"false"/);
assert.match(source, /state\.checkpointPromise/);
assert.match(source, /state\.checkpointRefreshQueued/);
assert.match(source, /\/minimax_h3_context_loop\/prompt-history/);
assert.match(source, /promptRevisionNavigation/);
assert.match(source, /availableReferenceRecords/);
assert.match(source, /state\.planNode \?\? node/);
assert.match(source, /preview_video/);
assert.match(source, /item\.preview_video \? null : \(item\.audio \?\? null\)/);
assert.match(source, /playerAudio/);
assert.match(source, /synchronizeGeneratedAudio/);
assert.match(source, /Source Track playback supplies the timeline clock/);
assert.match(source, /currentSettings === state\.lastSettingsSignature/);
assert.match(source, /state\.timelinePosition = target/);
assert.match(source, /state\.view !== "player"/);
assert.match(source, /renderSourceTimeline\(\); renderSourceAudioTimeline\(\)/);
assert.match(source, /updateTimelineSelection\(\)/);
assert.match(source, /h3_chain_active_scene/);
assert.match(source, /api\.removeEventListener\("executed", onPromptExecuted\)/);
assert.match(source, /renderShell\(\)/);
assert.match(source, /serialize:false/);
assert.match(source, /connectedPromptEditors/);
assert.match(source, /Prompt editing delegated to/);
assert.match(source, /preserveDelegatedPrompts\(\)/);
assert.match(source, /convertTaggedPictureReference/);
assert.match(source, /taggedPictureReferenceMode/);
assert.match(source, /h3studio-ref-mode/);
assert.match(source, /Use semantic #tag\[time\]/);
assert.match(source, /publishCompanionScene/);
assert.match(source, /Append a new scene and select it/);
assert.match(source, /state\.plan\.shots\.push\(makeShot\(state\.plan\.shots\)\)/);
assert.match(source, /state\.active = state\.plan\.shots\.length - 1/);
assert.match(source, /field\("Incoming transition", incomingTransition\)/);
assert.match(source, /field\("Prompt alternatives", promptSeedWrap\)/);
assert.match(source, /Stable derived/);
assert.doesNotMatch(source, /Inherit Plan seed/);
assert.match(source, /Randomize each queue/);
assert.match(source, /setScenePromptSeedMode/);
assert.match(source, /field\("Final assembly crossfade frames", blendFrames\)/);
assert.match(source, /field\("Source reference", sourceReference\)/);
assert.match(source, /field\("Generated continuity", generatedContinuity\)/);
assert.match(source, /field\("Lock source audio", lockSourceAudio\)/);
assert.match(source, /applySceneAudioOverride/);
assert.match(source, /field\("LoRA route", loraRoute\)/);
assert.match(source, /MiniMax H3 Scene LoRA Scheduler/);
assert.match(source, /row\.loraRoute/);
assert.match(source, /Advanced boundary controls/);
assert.match(source, /advanced\.open = state\.advancedBoundaryOpen/);
assert.match(source, /ADVANCED_BOUNDARY_OPEN_PROPERTY/);
assert.match(source, /field\("Implementation", continuation\)/);
assert.match(source, /applySceneTransitionPreset/);
assert.match(source, /field\("Boundary spatial proxy", spatialProxy\)/);
assert.match(source, /Low-grid 5\/6 proxy · Guide/);
assert.match(source, /Latent 5\/6 proxy · AV/);
assert.match(source, /context_spatial_proxy/);
assert.match(source, /field\("Visual \/ audio context", contextPair\)/);
assert.match(source, /audio_context_length/);
assert.match(source, /video_blend_frames/);
assert.match(source, /Guide · new shot/);
assert.match(source, /Latent Guide · direct generated latent/);
assert.match(source, /Detail Guide · color injection/);
assert.match(source, /Masked AV · same shot/);
assert.match(source, /Feathered AV · experimental dual-stream feather/);
assert.doesNotMatch(source, /Feathered AV \+ RGB/);
assert.match(source, /17n\+5 temporal latent grid/);
assert.match(source, /Exact aligned choices are 39, 90, 141, 192/);
assert.match(source, /Experimental only: nearest reported four-frame 17n−3 cut window/);

console.log("H3 Plan Studio: separate timeline editor contract passes");
