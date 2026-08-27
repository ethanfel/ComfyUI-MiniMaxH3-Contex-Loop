import {app} from "/scripts/app.js";
import {api} from "/scripts/api.js";
import {
    CONTINUATION_MODES,
    FPS,
    H3_CONTEXT_LENGTHS,
    MAX_H3_FRAMES,
    MAX_SEED,
    MAX_SHOTS,
    SCENE_LORA_ROUTES,
    automaticSceneColor,
    calculatePlanTiming,
    duplicateShot,
    formatClock,
    makeChapter,
    makeShot,
    moveShot,
    nativeContextWindowStarts,
    nearestNativeContextWindowStart,
    parsePlanJson,
    planToJson,
    orderedChapters,
    promptTextToLines,
    promptValueToText,
    randomSceneSeed,
    removePlanShot,
    safeShotId,
    sceneContextLength,
    sceneContinuationMode,
    sceneLoRARoute,
    scenePromptSeedMode,
    sceneVisualContextSource,
    sceneVisualContextLeadFrames,
    sceneVisualContextLeadSource,
    sceneVisualContextStartFrame,
    sceneVideoBlendFrames,
    setScenePromptSeedMode,
    setSharedPrompt,
    setShotLengthMode,
    sharedPrompt,
    shotLengthMode,
    visualContextCompositions,
} from "./h3_chain_plan_core.mjs?v=0.6.47";
import {
    promptRevisionHelp,
    promptRevisionLabel,
    promptRevisionNavigation,
} from "./h3_prompt_history_core.mjs?v=0.6.47";
import {
    availableReferenceRecords,
    convertTaggedPictureReference,
    taggedPictureReferenceMode,
    taggedPictureReferenceToken,
} from "./h3_reference_preview_core.mjs?v=0.6.47";
import {
    applySceneAudioOverride,
    applySceneTransitionPreset,
    primaryTransitionOptions,
    sceneAudioOverride,
    sceneAudioPolicy,
    sceneTransitionPreset,
    transitionPresetLabel,
} from "./h3_policy_core.mjs?v=0.6.47";
import {
    resolveAudioContextLength,
    resolveAudioPolicy,
    resolveTransitionPolicy,
} from "./h3_socket_presentation_core.mjs?v=0.6.47";
import {
    locateStudioTimelineSecond,
    h3StudioGridMarkers,
    matchingStudioCheckpoint,
    matchingStudioSourceAudio,
    matchingStudioSourceScene,
    studioCheckpointSignature,
    studioContextWindowLayout,
    studioContextWindowStartAtRatio,
    studioSceneStartSeconds,
    studioSourceAudioSecond,
    studioSourceSecond,
    studioTimelineLayout,
    studioWaveformSceneSamples,
} from "./h3_chain_plan_studio_core.mjs?v=0.6.47";
import * as promptCompanionSync from "./h3_prompt_companion_sync.mjs?v=0.6.47";

const {connectedPromptEditors, publishCompanionScene} = promptCompanionSync;
function publishCompanionPrompt(...args) {
    return promptCompanionSync.publishCompanionPrompt?.(...args) ?? 0;
}

const NODE_NAME = "MiniMaxH3ChainPlanStudio";
const PLAN_NAME = "MiniMaxH3ChainPlan";
const ACTIVE_PROPERTY = "h3_plan_studio_active_scene";
const ACTIVE_CHAPTER_PROPERTY = "h3_plan_studio_active_chapter";
const VIEW_PROPERTY = "h3_plan_studio_view";
const TIMELINE_ZOOM_PROPERTY = "h3_plan_studio_timeline_zoom";
const ADVANCED_BOUNDARY_OPEN_PROPERTY = "h3_plan_studio_advanced_boundary_open";
const SOURCE_AUDIO_MUTES_PROPERTY = "h3_plan_studio_source_audio_mutes";
const GENERATED_VOLUME_PROPERTY = "h3_plan_studio_generated_volume";
const SOURCE_VOLUME_PROPERTY = "h3_plan_studio_source_volume";
const MOTION_VOLUME_PROPERTY = "h3_plan_studio_motion_volume";
const MIN_WIDTH = 820;
const MIN_HEIGHT = 690;
const PLAN_SETTING_WIDGETS = Object.freeze([
    "plan_json", "run_name", "generation_fingerprint", "width", "height",
    "context_length", "encode_mode", "anchor_mode", "crop", "audio_mode",
    "audio_context_length", "default_duration_seconds", "default_steps",
    "base_seed", "segment_crf", "video_blend_frames", "continuation_mode",
]);

function monitorVolume(value, fallback = 1) {
    const number = Number(value);
    return Number.isFinite(number)
        ? Math.max(0, Math.min(1, number)) : fallback;
}

function normalizedTimelineZoom(value) {
    const number = Number(value);
    return Number.isFinite(number) ? Math.max(1, Math.min(6, number)) : 1;
}

function injectStyles() {
    if (document.getElementById("h3-plan-studio-style")) return;
    const style = document.createElement("style");
    style.id = "h3-plan-studio-style";
    style.textContent = `
        .h3studio {
            --hs-bg:color-mix(in srgb,var(--comfy-menu-bg,#202124) 92%,#101827);
            --hs-panel:color-mix(in srgb,var(--comfy-input-bg,#111827) 84%,#263552);
            --hs-border:color-mix(in srgb,var(--border-color,#555) 68%,#7891bf);
            --hs-text:var(--input-text,#eef1f7); --hs-muted:color-mix(in srgb,var(--hs-text) 57%,transparent);
            --hs-accent:#84aaff; box-sizing:border-box; width:100%; height:100%; min-height:540px;
            display:flex; flex-direction:column; gap:8px; overflow:hidden; padding:10px;
            border:1px solid var(--hs-border); border-radius:8px; background:var(--hs-bg);
            color:var(--hs-text); font:12px/1.35 system-ui,sans-serif;
        }
        .h3studio *, .h3studio *::before, .h3studio *::after { box-sizing:border-box; }
        .h3studio button,.h3studio input,.h3studio select,.h3studio textarea {
            color:var(--hs-text); font:inherit; border:1px solid var(--hs-border);
            border-radius:5px; background:var(--comfy-input-bg,#15171d);
        }
        .h3studio button { padding:5px 8px; cursor:pointer; white-space:nowrap; }
        .h3studio button:hover,.h3studio button.h3studio-active { border-color:var(--hs-accent); }
        .h3studio button.h3studio-active { color:#fff; background:#20375d; }
        .h3studio button:disabled { opacity:.4; cursor:not-allowed; }
        .h3studio input,.h3studio select,.h3studio textarea { width:100%; min-width:0; padding:6px 7px; }
        .h3studio textarea { resize:vertical; line-height:1.5; }
        .h3studio-head,.h3studio-toolbar,.h3studio-statusline,.h3studio-scene-head,
        .h3studio-form,.h3studio-history,.h3studio-json-actions,.h3studio-player-controls {
            display:flex; align-items:center; gap:6px;
        }
        .h3studio-head { justify-content:space-between; }
        .h3studio-title { color:var(--hs-accent); font-size:15px; font-weight:750; }
        .h3studio-run { min-width:0; color:var(--hs-muted); overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
        .h3studio-toolbar { flex-wrap:wrap; }
        .h3studio-spacer { flex:1; }
        .h3studio-statusline { color:var(--hs-muted); flex-wrap:wrap; min-height:18px; }
        .h3studio-statusline strong { color:var(--hs-text); }
        .h3studio-timeline-shell { flex:0 0 auto; padding:7px; border:1px solid var(--hs-border);
            border-radius:7px; background:var(--hs-panel); }
        .h3studio-timeline-tools { display:flex; align-items:center; gap:5px; min-height:28px; color:var(--hs-muted); }
        .h3studio-timeline-tools strong { color:var(--hs-text); }
        .h3studio-timeline-zoom { width:118px !important; padding:0 !important; }
        .h3studio-timeline-grid { display:grid; grid-template-columns:78px minmax(0,1fr); gap:5px; min-width:0; }
        .h3studio-timeline-labels,.h3studio-timeline-content { display:grid;
            grid-template-rows:18px 76px 76px 34px; row-gap:4px; align-items:stretch; }
        .h3studio-timeline-labels { color:var(--hs-muted); font-size:9px; font-weight:750;
            letter-spacing:.06em; text-align:right; }
        .h3studio-timeline-labels span { display:flex; align-items:center; justify-content:flex-end; }
        .h3studio-timeline-viewport { min-width:0; overflow-x:auto; overflow-y:hidden; padding-bottom:2px; }
        .h3studio-timeline-content { min-width:100%; }
        .h3studio-ruler { position:relative; height:18px; width:100%; border-bottom:1px solid var(--hs-border);
            color:var(--hs-muted); font-size:10px; overflow:hidden; cursor:pointer; }
        .h3studio-timeline { position:relative; display:flex; gap:3px; width:100%; min-width:0; min-height:0; overflow:hidden; }
        .h3studio-generated-timeline { overflow:visible; }
        .h3studio-chapter-marker { position:absolute; z-index:8; top:-2px; bottom:0; width:0;
            padding:0 !important; border:0 !important; border-left:2px solid #e8bd68 !important;
            border-radius:0 !important; background:transparent !important; overflow:visible; }
        .h3studio-chapter-marker span { position:absolute; top:3px; left:4px; max-width:112px;
            overflow:hidden; text-overflow:ellipsis; white-space:nowrap; padding:2px 6px;
            border:1px solid #a98242; border-radius:999px; color:#ffe0a2;
            background:color-mix(in srgb,var(--hs-bg) 92%,#6d4b16); font-size:9px; font-weight:750; }
        .h3studio-chapter-marker.h3studio-selected span { color:#fff; border-color:#ffe0a2;
            box-shadow:0 0 0 1px #ffe0a2 inset; }
        .h3studio-card { --scene:#84aaff; position:relative; isolation:isolate;
            flex:0 0 var(--h3-scene-width,138px); min-width:0;
            height:70px; overflow:hidden; padding:0 !important; text-align:left; border:1px solid var(--scene) !important;
            background:color-mix(in srgb,var(--scene) 13%,var(--comfy-input-bg,#15171d)) !important; }
        .h3studio-card.h3studio-selected { box-shadow:0 0 0 2px var(--scene) inset; }
        .h3studio-card video, .h3studio-card-thumbnail { position:absolute; inset:0; width:100%; height:100%; object-fit:cover;
            opacity:.58; z-index:-1; background:#08090c; pointer-events:none; }
        .h3studio-card::after { content:""; position:absolute; inset:0; z-index:-1;
            background:linear-gradient(180deg,transparent 10%,rgba(5,7,12,.88)); }
        .h3studio-card-copy { position:absolute; inset:auto 7px 6px; overflow:hidden; }
        .h3studio-card-title { display:block; font-weight:750; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
        .h3studio-card-meta { display:block; color:#dce5f7; font-size:10px; }
        .h3studio-render-dot { position:absolute; right:6px; top:6px; width:8px; height:8px; border-radius:50%;
            background:#687080; box-shadow:0 0 0 1px #111; }
        .h3studio-rendered .h3studio-render-dot { background:#62d58b; }
        .h3studio-source-card { border-style:dashed !important; }
        .h3studio-source-card .h3studio-render-dot { background:#b58cff; }
        .h3studio-source-empty { display:flex; align-items:center; padding:0 10px; color:var(--hs-muted);
            min-height:48px; border:1px dashed var(--hs-border); border-radius:5px; }
        .h3studio-audio-timeline { min-height:34px; }
        .h3studio-audio-card { --scene:#84aaff; position:relative;
            flex:0 0 var(--h3-scene-width,138px); min-width:0;
            height:34px; overflow:hidden; border:1px solid color-mix(in srgb,var(--scene) 65%,var(--hs-border));
            border-radius:5px; background:color-mix(in srgb,var(--scene) 8%,var(--comfy-input-bg,#15171d)); cursor:pointer; }
        .h3studio-audio-card.h3studio-selected { box-shadow:0 0 0 1px var(--scene) inset; }
        .h3studio-audio-card.h3studio-audio-muted { opacity:.48; }
        .h3studio-waveform { position:absolute; inset:3px 34px 3px 4px; width:calc(100% - 38px); height:28px; }
        .h3studio-audio-mute { position:absolute; z-index:2; right:3px; top:3px; width:28px; height:26px;
            padding:0 !important; display:grid; place-items:center; font-size:13px; }
        .h3studio-playhead { position:absolute; top:0; bottom:0; width:1px; background:#ff626a; pointer-events:none; }
        .h3studio-panel { flex:1 1 auto; min-height:0; overflow:auto; padding:9px;
            border:1px solid var(--hs-border); border-radius:7px; background:var(--hs-panel); }
        .h3studio-scene-head { margin-bottom:7px; }
        .h3studio-grid-markers { display:flex; align-items:center; gap:5px; flex-wrap:wrap; margin-left:auto; }
        .h3studio-grid-marker { padding:2px 6px; border:1px solid var(--hs-border); border-radius:999px;
            color:var(--hs-muted); background:color-mix(in srgb,var(--hs-panel) 82%,transparent); font-size:9px; }
        .h3studio-grid-marker.h3studio-grid-exact { color:#91e5b5; border-color:#4c9c70; }
        .h3studio-grid-marker.h3studio-grid-warning { color:#ffd08a; border-color:#a47738; }
        .h3studio-grid-marker.h3studio-grid-experimental { border-style:dashed; }
        .h3studio-scene-label { color:var(--hs-muted); }
        .h3studio-form { align-items:end; display:grid;
            grid-template-columns:minmax(130px,1.3fr) minmax(175px,1.3fr) minmax(65px,.5fr) minmax(135px,1.1fr) minmax(120px,.85fr) minmax(140px,1fr); margin-bottom:8px; }
        .h3studio-audio-overrides { display:grid; grid-template-columns:repeat(3,minmax(160px,1fr));
            gap:7px; margin:0 0 8px; align-items:end; }
        .h3studio-field { display:flex; min-width:0; flex-direction:column; gap:3px; color:var(--hs-muted); }
        .h3studio-advanced { margin:0 0 8px; padding:6px 8px; border:1px solid var(--hs-border);
            border-radius:6px; color:var(--hs-muted); }
        .h3studio-advanced summary { cursor:pointer; font-weight:700; }
        .h3studio-advanced-grid { display:grid; grid-template-columns:repeat(3,minmax(160px,1fr));
            gap:7px; margin-top:7px; align-items:end; }
        .h3studio-plan-settings { display:grid; grid-template-columns:repeat(3,minmax(170px,1fr));
            gap:9px; align-items:end; }
        .h3studio-plan-settings-section { grid-column:1 / -1; margin-top:5px; padding-top:7px;
            border-top:1px solid var(--hs-border); color:var(--hs-accent); font-weight:750; }
        .h3studio-plan-defaults-help { grid-column:1 / -1; color:var(--hs-muted); font-size:10px; }
        .h3studio-length { display:grid; grid-template-columns:112px minmax(80px,1fr); gap:5px; }
        .h3studio-prompt-seed { display:grid;
            grid-template-columns:132px minmax(90px,1fr) auto; gap:5px; }
        .h3studio-context-pair { display:grid; grid-template-columns:1fr 1fr; gap:5px; }
        .h3studio-prompt { min-height:250px; width:100%; font:15px/1.55 ui-monospace,SFMono-Regular,Consolas,monospace !important; }
        .h3studio-prompt-tools { display:flex; align-items:center; gap:6px; margin:7px 0; flex-wrap:wrap; }
        .h3studio-prompt-delegated { margin-top:10px; padding:12px; border:1px dashed var(--hs-border);
            border-radius:7px; color:var(--hs-muted); background:var(--hs-bg); }
        .h3studio-prompt-delegated strong { display:block; margin-bottom:4px; color:var(--hs-text); }
        .h3studio-hint,.h3studio-message { color:var(--hs-muted); }
        .h3studio-history { justify-content:center; min-height:26px; }
        .h3studio-history-count { min-width:44px; text-align:center; font-variant-numeric:tabular-nums; }
        .h3studio-history-meta { max-width:300px; color:var(--hs-muted); overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
        .h3studio-error { color:#ffb3b3; white-space:pre-wrap; }
        .h3studio-shared { min-height:260px; font:15px/1.55 ui-monospace,SFMono-Regular,Consolas,monospace !important; }
        .h3studio-defaults { display:grid; grid-template-columns:1fr 1fr; gap:8px; margin-top:8px; max-width:390px; }
        .h3studio-json { min-height:360px; font:13px/1.45 ui-monospace,SFMono-Regular,Consolas,monospace !important; }
        .h3studio-json-actions { margin-top:7px; }
        .h3studio-player { display:flex; flex-direction:column; gap:7px; height:100%; min-height:330px; }
        .h3studio-compare-stage { position:relative; flex:1 1 auto; min-height:260px; overflow:hidden;
            background:#050608; border-radius:6px; }
        .h3studio-compare-stage video { position:absolute; inset:0; width:100%; height:100%; background:#050608; object-fit:contain; }
        .h3studio-handoff-frame { position:absolute; inset:0; width:100%; height:100%; opacity:1;
            pointer-events:none; transition:opacity .16s ease-out; }
        .h3studio-handoff-frame.h3studio-handoff-release { opacity:0; }
        .h3studio-source-layer { position:absolute; inset:0; overflow:hidden; pointer-events:none; }
        .h3studio-source-layer video { width:100%; height:100%; }
        .h3studio-wipe-line { position:absolute; top:0; bottom:0; width:2px; background:#d2b8ff;
            box-shadow:0 0 0 1px rgba(0,0,0,.45); pointer-events:none; }
        .h3studio-compare-label { position:absolute; top:7px; z-index:2; padding:3px 6px; border-radius:4px;
            background:rgba(5,7,12,.7); color:#fff; font-size:10px; pointer-events:none; }
        .h3studio-compare-label-generated { right:7px; }
        .h3studio-compare-label-source { left:7px; }
        .h3studio-player-controls input[type=range] { flex:1; padding:0; }
        .h3studio-context-selector { display:flex; flex-direction:column; gap:9px; }
        .h3studio-context-help { color:var(--hs-muted); }
        .h3studio-context-blocks { display:grid; grid-template-columns:repeat(auto-fit,minmax(300px,1fr)); gap:9px; }
        .h3studio-context-block { min-width:0; padding:8px; border:1px solid var(--hs-border);
            border-radius:7px; background:var(--hs-bg); }
        .h3studio-context-block-head { display:flex; align-items:baseline; justify-content:space-between;
            gap:8px; margin-bottom:7px; }
        .h3studio-context-block-head span { color:var(--hs-muted); overflow:hidden;
            text-overflow:ellipsis; white-space:nowrap; }
        .h3studio-context-video { display:block; width:100%; min-height:180px; max-height:330px;
            object-fit:contain; background:#050608; border-radius:6px; }
        .h3studio-context-empty { display:grid; place-items:center; width:100%; min-height:180px;
            padding:18px; color:var(--hs-muted); text-align:center; border:1px dashed var(--hs-border);
            border-radius:6px; background:#050608; }
        .h3studio-context-range { display:flex; flex-direction:column; gap:5px; margin-top:7px; }
        .h3studio-context-movie-track { position:relative; width:100%; height:38px; overflow:hidden;
            border:1px solid var(--hs-border); border-radius:6px; cursor:pointer; touch-action:none;
            background:repeating-linear-gradient(90deg,#151922 0,#151922 11px,#0e1118 11px,#0e1118 13px); }
        .h3studio-context-movie-track:focus-visible { outline:2px solid #79a7ff; outline-offset:2px; }
        .h3studio-context-window { position:absolute; top:3px; bottom:3px; min-width:1px;
            box-sizing:border-box; border:2px solid #7ec8ff; border-radius:5px;
            background:rgba(47,143,220,.42); box-shadow:0 0 0 1px rgba(0,0,0,.55) inset;
            display:grid; place-items:center; overflow:hidden; color:#fff; font-size:10px;
            font-variant-numeric:tabular-nums; cursor:grab; user-select:none; }
        .h3studio-context-movie-track.h3studio-dragging .h3studio-context-window { cursor:grabbing; }
        .h3studio-context-window::before,.h3studio-context-window::after { content:"";
            position:absolute; top:6px; bottom:6px; width:2px; background:rgba(255,255,255,.78); }
        .h3studio-context-window::before { left:4px; }
        .h3studio-context-window::after { right:4px; }
        .h3studio-context-playhead { position:absolute; z-index:2; top:0; bottom:0; width:2px;
            pointer-events:none; background:#ff9a3c; transform:translateX(-1px); }
        .h3studio-context-range-readout { display:flex; justify-content:space-between; gap:8px; }
        .h3studio-context-movie-length { color:var(--hs-muted); font-variant-numeric:tabular-nums; }
        .h3studio-context-range-label { min-width:150px; color:var(--hs-muted);
            font-variant-numeric:tabular-nums; text-align:right; }
        .h3studio-context-actions { display:flex; align-items:center; gap:6px; margin-top:7px;
            flex-wrap:wrap; }
        .h3studio-compare-controls { display:grid; grid-template-columns:auto minmax(100px,1fr) auto; gap:6px; align-items:center; }
        .h3studio-compare-controls.h3studio-no-motion { grid-template-columns:1fr; }
        .h3studio-audio-mix { display:flex; align-items:center; justify-content:flex-end; gap:8px; flex-wrap:wrap; }
        .h3studio-audio-control { display:flex; align-items:center; gap:4px; }
        .h3studio-audio-toggle { display:flex; align-items:center; gap:4px; color:var(--hs-muted); white-space:nowrap; }
        .h3studio-audio-toggle input { width:auto; margin:0; padding:0; }
        .h3studio-audio-volume { width:68px !important; min-width:48px !important; padding:0 !important; }
        .h3studio-audio-level { width:31px; color:var(--hs-muted); font-size:9px; text-align:right; }
        .h3studio-refs { display:none; gap:5px; padding:7px; border:1px solid var(--hs-border);
            border-radius:6px; background:var(--hs-bg); flex-wrap:wrap; }
        .h3studio-refs.h3studio-open { display:flex; }
        .h3studio-ref-entry { display:flex; align-items:stretch; gap:2px; }
        .h3studio-ref-mode { display:flex; gap:1px; }
        .h3studio-ref-mode button { min-width:28px; padding:2px 5px; font-size:10px; }
        .h3studio-ref-mode button.h3studio-selected { border-color:var(--hs-accent);
            color:var(--hs-accent); }
        .h3studio-ref-preview { flex:1 0 100%; display:grid; grid-template-columns:minmax(120px,220px) 1fr;
            gap:8px; align-items:start; color:var(--hs-muted); }
        .h3studio-ref-preview img,.h3studio-ref-preview video { width:100%; max-height:150px; object-fit:contain; background:#08090c; }
        .h3studio-ref-preview audio { width:100%; height:36px; }
        @media(max-width:760px) { .h3studio-form,.h3studio-advanced-grid,.h3studio-plan-settings,
            .h3studio-audio-overrides { grid-template-columns:1fr 1fr; }
            .h3studio-defaults,.h3studio-context-blocks { grid-template-columns:1fr; } }
    `;
    document.head.appendChild(style);
}

function element(tag, className = "", text) {
    const item = document.createElement(tag);
    if (className) item.className = className;
    if (text !== undefined) item.textContent = text;
    return item;
}

function button(label, title, action) {
    const item = element("button", "", label);
    item.type = "button";
    item.title = title || "";
    item.addEventListener("click", action);
    return item;
}

function nodeType(node) {
    return node?.comfyClass ?? node?.type ?? null;
}

function allNodes(graph, output = []) {
    for (const node of graph?._nodes ?? []) {
        output.push(node);
        if (node.subgraph) allNodes(node.subgraph, output);
    }
    return output;
}

function upstreamPlanNode(start) {
    const queue = [start];
    const seen = new Set();
    while (queue.length) {
        const node = queue.shift();
        if (!node || seen.has(node)) continue;
        seen.add(node);
        if (node !== start && nodeType(node) === PLAN_NAME) return node;
        for (const input of node.inputs ?? []) {
            if (input.link == null) continue;
            const link = node.graph?.links?.[input.link];
            const parent = link ? node.graph?.getNodeById?.(link.origin_id) : null;
            if (parent) queue.push(parent);
        }
    }
    return null;
}

function widget(node, name) {
    return node?.widgets?.find((item) => item.name === name);
}

function inputSource(node, name) {
    const input = node?.inputs?.find((item) => item.name === name);
    const link = input?.link == null ? null : node.graph?.links?.[input.link];
    return link ? node.graph?.getNodeById?.(link.origin_id) ?? null : null;
}

function inputConnected(node, name) {
    const input = node?.inputs?.find((item) => item.name === name);
    return input?.link !== null && input?.link !== undefined;
}

function mediaExtension(kind) {
    if (kind === "image") return /\.(?:avif|bmp|gif|jpe?g|png|webp)$/i;
    if (kind === "video") return /\.(?:m4v|mkv|mov|mp4|webm)$/i;
    return /\.(?:aac|flac|m4a|mp3|ogg|opus|wav)$/i;
}

function widgetAsset(value, kind) {
    if (value && typeof value === "object" && value.filename) {
        return {filename:String(value.filename), subfolder:String(value.subfolder ?? ""), type:String(value.type ?? "input")};
    }
    let text = typeof value === "string" ? value.trim() : "";
    if (!text) return null;
    if (/^(?:blob:|data:|https?:|\/api\/view\?|\/view\?)/i.test(text)) return {url:text};
    let type = "input";
    const annotated = text.match(/\s+\[(input|output|temp)\]\s*$/i);
    if (annotated) { type = annotated[1].toLowerCase(); text = text.slice(0, annotated.index).trim(); }
    text = text.replaceAll("\\", "/").replace(/^\/+/, "");
    if (!mediaExtension(kind).test(text)) return null;
    const slash = text.lastIndexOf("/");
    return {filename:slash >= 0 ? text.slice(slash + 1) : text,
        subfolder:slash >= 0 ? text.slice(0, slash) : "", type};
}

function assetUrl(asset) {
    if (!asset) return null;
    if (asset.url) return asset.url;
    const query = new URLSearchParams({filename:asset.filename, subfolder:asset.subfolder ?? "", type:asset.type ?? "input"});
    return api.apiURL(`/view?${query.toString()}`);
}

function findMediaPreview(start, kind) {
    const queue = [start];
    const seen = new Set();
    while (queue.length) {
        const current = queue.shift();
        if (!current || seen.has(current)) continue;
        seen.add(current);
        if (kind === "image") {
            const rendered = current.imgs?.[0];
            const src = typeof rendered === "string" ? rendered : rendered?.src;
            if (src) return src;
        }
        for (const item of current.widgets ?? []) {
            const value = widgetAsset(item.value, kind);
            if (value) return assetUrl(value);
        }
        for (const input of current.inputs ?? []) {
            const parent = inputSource(current, input.name);
            if (parent) queue.push(parent);
        }
    }
    return null;
}

function videoUrl(item) {
    if (!item) return "";
    const query = new URLSearchParams({
        filename:item.filename, subfolder:item.subfolder ?? "", type:item.type ?? "output",
    });
    return api.apiURL(`/view?${query.toString()}`);
}

function insertText(textarea, text, selectionOffset = text.length) {
    const start = textarea.selectionStart ?? textarea.value.length;
    const end = textarea.selectionEnd ?? start;
    textarea.setRangeText(text, start, end, "end");
    const caret = start + selectionOffset;
    textarea.setSelectionRange(caret, caret);
    textarea.dispatchEvent(new Event("input", {bubbles:true}));
    textarea.focus();
}

function insertDialogue(textarea) {
    const start = textarea.selectionStart ?? textarea.value.length;
    const end = textarea.selectionEnd ?? start;
    const selected = textarea.value.slice(start, end);
    const markup = `<d>${selected}</d>`;
    insertText(textarea, markup, selected ? markup.length : 3);
}

function mount(node) {
    if (node._h3PlanStudioMounted || typeof node.addDOMWidget !== "function") return;
    node._h3PlanStudioMounted = true;
    injectStyles();
    node.properties ??= {};

    const root = element("div", "h3studio");
    root.title = "Timeline Plan editor: use it standalone or synchronize it with a connected H3 Chain Plan.";
    for (const name of ["pointerdown","pointerup","mousedown","mouseup","click","dblclick"]) {
        root.addEventListener(name, (event) => event.stopPropagation());
    }
    root.addEventListener("wheel", (event) => event.stopPropagation());

    const state = {
        plan:null, planNode:null, planOwner:null, planWidget:null,
        lastValue:"", lastRunName:"",
        lastSettingsSignature:"",
        active:Math.max(0, Number(node.properties[ACTIVE_PROPERTY]) || 0),
        activeChapterId:String(node.properties[ACTIVE_CHAPTER_PROPERTY] ?? ""),
        view:["scene","shared","settings","context","player","json"].includes(node.properties[VIEW_PROPERTY])
            ? node.properties[VIEW_PROPERTY] : "scene",
        timelineZoom:normalizedTimelineZoom(
            node.properties[TIMELINE_ZOOM_PROPERTY]),
        advancedBoundaryOpen:Boolean(
            node.properties[ADVANCED_BOUNDARY_OPEN_PROPERTY]),
        checkpoints:new Map(), checkpointSignature:"", checkpointError:"", checkpointToken:0,
        checkpointPromise:null, checkpointRefreshQueued:false, disposed:false,
        sourcePreview:null, sourceWaveform:null, sourceWaveformToken:"",
        presentationToken:0,
        sourceWaveformPromise:null,
        pollTimer:null, checkpointTimer:null, timelineHost:null, sourceTimelineHost:null,
        sourceAudioTimelineHost:null, sourceTrack:null, sourceAudioTrack:null,
        timelineViewport:null, timelineContent:null, timelineRuler:null,
        timelineZoomInput:null, timelineZoomLabel:null,
        timelineResizeObserver:null, timelineWidths:[],
        panelHost:null,
        planNotifyTimer:null, editorialTimer:null, lastEditorialSignature:"",
        playhead:null, player:null, playerAudio:null, sourceAudioPlayer:null,
        sourcePlayer:null, sourceLayer:null,
        contextPlayers:[],
        playerSlider:null, playerIndex:-1,
        playerPreloadVideo:null, playerPreloadAudio:null,
        primePlayerNext:null, playPlayerTransport:null,
        togglePlayerPlayback:null, keyboardHover:false,
        generatedVolume:monitorVolume(
            node.properties[GENERATED_VOLUME_PROPERTY]),
        sourceVolume:monitorVolume(node.properties[SOURCE_VOLUME_PROPERTY]),
        motionVolume:monitorVolume(node.properties[MOTION_VOLUME_PROPERTY]),
        timelinePosition:null, pendingSeek:0,
        history:{sceneKey:"", data:null, revisionId:null, host:null, textarea:null,
            status:null, loadToken:0, loadPromise:null, saveTimer:null,
            pendingDraft:null, savePromise:null, error:""},
        promptEditors:[], lastPromptEditorsSignature:"",
        referenceSyntax:new Map(),
    };
    node._h3PlanStudioState = state;

    root.tabIndex = 0;
    root.addEventListener("pointerenter", () => { state.keyboardHover = true; });
    root.addEventListener("pointerleave", () => { state.keyboardHover = false; });
    const pausePlayerMonitors = () => {
        for (const media of [
            state.playerAudio, state.sourceAudioPlayer, state.sourcePlayer,
            ...state.contextPlayers,
        ]) {
            try { media?.pause(); } catch (_error) {}
        }
    };
    const onPlayerKeydown = (event) => {
        if (event.code !== "Space" || event.repeat || state.view !== "player"
                || !state.togglePlayerPlayback) return;
        const target = event.target;
        if (target instanceof Element && target.closest(
            "input,textarea,select,button,[contenteditable=true]")) return;
        if (!state.keyboardHover && !root.contains(document.activeElement)) return;
        event.preventDefault(); event.stopPropagation();
        state.togglePlayerPlayback();
    };
    document.addEventListener("keydown", onPlayerKeydown, true);

    function dirty() {
        node.graph?.setDirtyCanvas?.(true, true);
        app.graph?.setDirtyCanvas?.(true, true);
    }

    function persistView() {
        node.properties[ACTIVE_PROPERTY] = state.active;
        node.properties[ACTIVE_CHAPTER_PROPERTY] = state.activeChapterId;
        node.properties[VIEW_PROPERTY] = state.view;
        node.properties[TIMELINE_ZOOM_PROPERTY] = state.timelineZoom;
        dirty();
    }

    function runName() {
        return String(widget(state.planOwner ?? node, "run_name")?.value ?? "").trim();
    }

    function settings() {
        const owner = state.planOwner ?? node;
        const transition = resolveTransitionPolicy(owner);
        const audioPolicy = resolveAudioPolicy(owner);
        return {
            contextLength:transition.known
                ? transition.contextLength
                : widget(owner, "context_length")?.value ?? 22,
            audioContextLength:resolveAudioContextLength(owner),
            videoBlendFrames:widget(owner, "video_blend_frames")?.value ?? 0,
            encodeMode:widget(owner, "encode_mode")?.value ?? "video",
            anchorMode:widget(owner, "anchor_mode")?.value ?? "head",
            continuationMode:transition.known
                ? transition.continuationMode
                : widget(owner, "continuation_mode")?.value ?? "guide",
            generatedContinuity:audioPolicy.known
                ? audioPolicy.generatedContinuity : "on",
            sourceAudioTarget:audioPolicy.known
                ? audioPolicy.sourceAudioTarget ?? "off" : "off",
            transitionPreset:transition.known ? transition.preset : "custom",
            audioPolicy,
            defaultDurationSeconds:widget(owner, "default_duration_seconds")?.value ?? 15,
            defaultSteps:widget(owner, "default_steps")?.value ?? 20,
        };
    }

    function settingsSignature(planOwner = state.planOwner ?? node) {
        const transition = resolveTransitionPolicy(planOwner);
        const audioPolicy = resolveAudioPolicy(planOwner);
        return JSON.stringify([
            transition.known
                ? transition.contextLength
                : widget(planOwner, "context_length")?.value ?? 22,
            resolveAudioContextLength(planOwner),
            widget(planOwner, "video_blend_frames")?.value ?? 0,
            widget(planOwner, "encode_mode")?.value ?? "video",
            widget(planOwner, "anchor_mode")?.value ?? "head",
            transition.known
                ? transition.continuationMode
                : widget(planOwner, "continuation_mode")?.value ?? "guide",
            audioPolicy.sourceReference,
            audioPolicy.generatedContinuity,
            audioPolicy.sourceAudioTarget ?? "off",
            inputConnected(planOwner, "project_assets"),
            ...PLAN_SETTING_WIDGETS.slice(1).map(
                (name) => widget(planOwner, name)?.value ?? null),
        ]);
    }

    function mirrorConnectedPlan(planNode) {
        if (!planNode) return false;
        let changed = false;
        for (const name of PLAN_SETTING_WIDGETS) {
            const source = widget(planNode, name);
            const target = widget(node, name);
            if (!source || !target || Object.is(source.value, target.value)) continue;
            target.value = source.value;
            changed = true;
        }
        if (changed) dirty();
        return changed;
    }

    function writePlanSetting(name, value, rerender = true) {
        const targets = state.planNode ? [state.planNode, node] : [node];
        for (const target of targets) {
            const targetWidget = widget(target, name);
            if (!targetWidget || Object.is(targetWidget.value, value)) continue;
            targetWidget.value = value;
            targetWidget.callback?.(targetWidget.value);
        }
        state.lastRunName = runName();
        state.lastSettingsSignature = settingsSignature(state.planOwner ?? node);
        dirty();
        if (rerender) renderShell();
    }

    function timing() {
        return calculatePlanTiming(state.plan, settings());
    }

    function promptEditorsSignature(editors = state.promptEditors) {
        return editors.map((editor) => `${nodeType(editor)}:${String(editor.id ?? "")}`).sort().join("|");
    }

    function promptEditorLabel() {
        if (state.promptEditors.length > 1) return `${state.promptEditors.length} linked prompt editors`;
        return nodeType(state.promptEditors[0]) === "MiniMaxH3ChainRichScenePromptEditor"
            ? "Rich Scene Prompt Editor" : "Scene Prompt Editor";
    }

    function preserveDelegatedPrompts() {
        if (!state.promptEditors.length || !state.planWidget || !state.plan) return;
        let live;
        try { live = parsePlanJson(String(state.planWidget.value ?? "")); }
        catch (_error) { return; }
        const byId = new Map();
        for (const shot of live.shots) {
            const id = String(shot?.id ?? "").trim();
            if (id && !byId.has(id)) byId.set(id, shot);
        }
        state.plan.shots.forEach((shot, index) => {
            const id = String(shot?.id ?? "").trim();
            const current = (id ? byId.get(id) : null) ?? live.shots[index];
            if (current) shot.prompt = promptTextToLines(promptValueToText(current.prompt));
        });
    }

    function publishActiveScene() {
        if (state.planNode) publishCompanionScene(node, state.planNode, state.active);
    }

    function editorialPayload() {
        const shots = state.plan?.shots ?? [];
        const sceneOrder = shots.map((shot, index) => ({
            scene:index + 1,
            scene_id:safeShotId(
                shot?.id, `clip_${String(index + 1).padStart(4, "0")}`,
            ),
        }));
        const sceneById = new Map(sceneOrder.map((row) => [row.scene_id, row.scene]));
        return {
            run_name:runName(),
            chapters:orderedChapters(state.plan).map((chapter) => ({
                id:chapter.id,
                title:chapter.title,
                start_scene_id:chapter.start_scene_id,
                start_scene:sceneById.get(chapter.start_scene_id),
                text:chapter.text ?? "",
            })),
            scene_order:sceneOrder,
        };
    }

    function scheduleEditorialSave() {
        if (!state.plan) return;
        const payload = editorialPayload();
        const signature = JSON.stringify(payload);
        if (signature === state.lastEditorialSignature) return;
        state.lastEditorialSignature = signature;
        if (state.editorialTimer != null) clearTimeout(state.editorialTimer);
        if (!payload.run_name) return;
        state.editorialTimer = setTimeout(async () => {
            state.editorialTimer = null;
            try {
                const response = await api.fetchApi(
                    "/minimax_h3_context_loop/editorial",
                    {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(payload)},
                );
                if (!response.ok) {
                    const detail = await response.json().catch(() => ({}));
                    throw new Error(detail.error || `HTTP ${response.status}`);
                }
            } catch (error) {
                if (state.lastEditorialSignature === signature) {
                    state.lastEditorialSignature = "";
                }
                console.warn("H3 Plan Studio could not save chapter presentation data:", error);
            }
        }, 250);
    }

    function writePlan(message = null) {
        if (!state.plan || !state.planWidget) return;
        // A linked dedicated editor owns scene prompts. Re-read those fields at
        // the last possible moment so a Studio seed/length edit cannot overwrite
        // prompt text typed since Studio's 500 ms polling snapshot.
        preserveDelegatedPrompts();
        const value = planToJson(state.plan);
        state.lastValue = value;
        state.planWidget.value = value;
        if (state.planNode) {
            const localPlanWidget = widget(node, "plan_json");
            if (localPlanWidget) localPlanWidget.value = value;
        }
        if (state.planNotifyTimer != null) clearTimeout(state.planNotifyTimer);
        const targetWidget = state.planWidget;
        state.planNotifyTimer = setTimeout(() => {
            state.planNotifyTimer = null;
            if (targetWidget !== state.planWidget) return;
            targetWidget.callback?.(targetWidget.value);
        }, 75);
        state.planOwner?.graph?.setDirtyCanvas?.(true, true);
        if (state.planNode && !state.activeChapterId) {
            publishCompanionPrompt(
                node, state.planNode, state.active,
                promptValueToText(state.plan.shots[state.active]?.prompt));
        }
        if (message) message.textContent = state.planNode
            ? "Saved to connected Plan" : "Saved in standalone Plan Studio";
        scheduleEditorialSave();
        renderStatus();
        dirty();
    }

    function historyKey(sceneId) {
        return `${runName()}\u0000${sceneId}`;
    }

    async function historyRequest(query = {}, body = null) {
        const suffix = new URLSearchParams(query).toString();
        const response = await api.fetchApi(
            `/minimax_h3_context_loop/prompt-history${suffix ? `?${suffix}` : ""}`,
            body == null ? undefined : {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(body)},
        );
        let payload = {};
        try { payload = await response.json(); } catch (_error) {}
        if (!response.ok) throw new Error(payload.error || `Prompt history request failed (HTTP ${response.status}).`);
        return payload;
    }

    function renderHistory() {
        const history = state.history;
        if (!history.host) return;
        history.host.replaceChildren();
        if (history.error) {
            history.host.append(element("span", "h3studio-history-meta h3studio-error", history.error));
            return;
        }
        if (!history.data) {
            history.host.append(element("span", "h3studio-history-meta", "Loading prompt versions…"));
            return;
        }
        const navigation = promptRevisionNavigation(history.data, history.revisionId);
        const previous = button("‹", "Activate previous prompt version in the Plan", () => {
            if (navigation.previous) void selectHistoryRevision(navigation.previous.id);
        });
        const next = button("›", "Activate next prompt version in the Plan", () => {
            if (navigation.next) void selectHistoryRevision(navigation.next.id);
        });
        previous.disabled = !navigation.previous;
        next.disabled = !navigation.next;
        const count = element("span", "h3studio-history-count", `Active ${navigation.position} / ${navigation.total}`);
        const metadata = element("span", "h3studio-history-meta", promptRevisionLabel(navigation));
        metadata.title = promptRevisionHelp(navigation);
        history.host.append(previous, count, next, metadata);
    }

    async function loadHistory(sceneId, prompt, synchronize = true) {
        const history = state.history;
        const currentRun = runName();
        const key = historyKey(sceneId);
        const token = ++history.loadToken;
        history.sceneKey = key; history.data = null; history.revisionId = null; history.error = "";
        renderHistory();
        if (!currentRun) { history.error = "Set a Plan run_name to enable prompt history."; renderHistory(); return; }
        const request = synchronize ? historyRequest({}, {
            action:"save", run_name:currentRun, scene_id:sceneId, prompt, parent_revision:null,
        }) : historyRequest({run_name:currentRun, scene_id:sceneId});
        history.loadPromise = request;
        try {
            const payload = await request;
            if (token !== history.loadToken || history.sceneKey !== key) return;
            history.data = payload.history ?? payload;
            history.revisionId = payload.revision?.id ?? history.data.active_revision ?? null;
        } catch (error) {
            if (token === history.loadToken && history.sceneKey === key) history.error = error?.message || String(error);
        } finally {
            if (history.loadPromise === request) history.loadPromise = null;
            if (token === history.loadToken && history.sceneKey === key) renderHistory();
        }
    }

    function scheduleHistoryDraft(sceneId, prompt) {
        const currentRun = runName();
        if (!currentRun) return;
        const history = state.history;
        history.pendingDraft = {key:historyKey(sceneId), runName:currentRun, sceneId, prompt};
        if (history.saveTimer != null) clearTimeout(history.saveTimer);
        history.saveTimer = setTimeout(() => { history.saveTimer = null; void flushHistoryDraft(); }, 650);
    }

    async function flushHistoryDraft() {
        const history = state.history;
        if (history.saveTimer != null) { clearTimeout(history.saveTimer); history.saveTimer = null; }
        if (history.savePromise) { await history.savePromise; return history.pendingDraft ? flushHistoryDraft() : undefined; }
        const draft = history.pendingDraft;
        if (!draft) return;
        history.pendingDraft = null;
        if (history.loadPromise && history.sceneKey === draft.key) await history.loadPromise;
        const request = historyRequest({}, {action:"save", run_name:draft.runName,
            scene_id:draft.sceneId, prompt:draft.prompt,
            parent_revision:history.sceneKey === draft.key ? history.revisionId : null});
        history.savePromise = request;
        try {
            const payload = await request;
            if (history.sceneKey === draft.key) {
                history.data = payload.history; history.revisionId = payload.revision?.id ?? payload.history?.active_revision;
                history.error = ""; renderHistory();
            }
        } catch (error) {
            if (history.sceneKey === draft.key) { history.error = error?.message || String(error); renderHistory(); }
        } finally { if (history.savePromise === request) history.savePromise = null; }
        if (history.pendingDraft) await flushHistoryDraft();
    }

    async function selectHistoryRevision(revisionId) {
        await flushHistoryDraft();
        const shot = state.plan?.shots?.[state.active];
        const history = state.history;
        if (!shot || !history.textarea) return;
        const sceneId = safeShotId(shot.id, `clip_${String(state.active + 1).padStart(4,"0")}`);
        const key = historyKey(sceneId);
        try {
            const payload = await historyRequest({}, {action:"activate", run_name:runName(), scene_id:sceneId, revision:revisionId});
            if (history.sceneKey !== key) return;
            history.data = payload.history; history.revisionId = payload.revision.id; history.error = "";
            history.textarea.value = String(payload.revision.prompt ?? "");
            shot.prompt = promptTextToLines(history.textarea.value);
            writePlan(history.status); renderHistory(); history.textarea.focus();
        } catch (error) { if (history.sceneKey === key) { history.error = error?.message || String(error); renderHistory(); } }
    }

    async function refreshCheckpointsNow() {
        if (state.disposed) return;
        const currentRun = runName();
        const token = ++state.checkpointToken;
        if (!currentRun) {
            const changed = state.checkpoints.size > 0
                || Boolean(state.checkpointSignature) || Boolean(state.checkpointError);
            state.checkpoints = new Map(); state.checkpointSignature = "";
            state.checkpointError = "";
            if (changed) { refreshTimelineCheckpoints(); renderStatus(); }
            return;
        }
        try {
            const query = new URLSearchParams({
                run_name:currentRun, include_graph:"false",
            });
            const response = await api.fetchApi(`/minimax_h3_context_loop/checkpoints?${query.toString()}`);
            const payload = await response.json();
            if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
            if (state.disposed || token !== state.checkpointToken || currentRun !== runName()) return;
            const records = payload.checkpoints ?? [];
            const signature = studioCheckpointSignature(currentRun, records);
            const recoveredFromError = Boolean(state.checkpointError);
            state.checkpointError = "";
            if (signature === state.checkpointSignature) {
                if (recoveredFromError) renderStatus();
                return;
            }
            state.checkpointSignature = signature;
            state.checkpoints = new Map(records.map((item) => [Number(item.scene), item]));
        } catch (error) {
            if (token !== state.checkpointToken) return;
            state.checkpointError = error?.message || String(error);
            renderStatus();
            return;
        }
        refreshTimelineCheckpoints(); renderStatus();
        if (state.view === "context") renderPanel();
        if (state.view === "player" && state.player?.paused) {
            const media = playerCheckpoint(state.playerIndex);
            const desired = media?.video ? videoUrl(media.video) : "";
            const desiredAudio = media?.audio ? videoUrl(media.audio) : "";
            if (desired !== String(state.player.dataset.source ?? "") ||
                    desiredAudio !== String(
                        state.playerAudio?.dataset.source ?? "")) renderPanel();
        }
    }

    async function refreshCheckpoints() {
        if (state.disposed) return;
        if (state.checkpointPromise) {
            state.checkpointRefreshQueued = true;
            return state.checkpointPromise;
        }
        const request = refreshCheckpointsNow();
        state.checkpointPromise = request;
        try {
            return await request;
        } finally {
            if (state.checkpointPromise === request) state.checkpointPromise = null;
            if (state.checkpointRefreshQueued && !state.disposed) {
                state.checkpointRefreshQueued = false;
                void refreshCheckpoints();
            }
        }
    }

    function renderStatus() {
        const host = root.querySelector(".h3studio-statusline");
        if (!host || !state.plan) return;
        const result = timing();
        const ready = result.shots.filter(
            (row, index) => matchingStudioCheckpoint(state.checkpoints, index, row),
        ).length;
        host.replaceChildren();
        host.append(
            element("strong", "", `${result.shots.length} scenes`),
            document.createTextNode(`${result.totalFrames} delivered frames · ${formatClock(result.totalSeconds)}`),
            document.createTextNode(`${settings().contextLength}f overlap · ${ready}/${result.shots.length} rendered`),
        );
        if (result.errors.length) host.append(element("span", "h3studio-error", `${result.errors.length} plan issue${result.errors.length === 1 ? "" : "s"}`));
        if (state.checkpointError) host.append(element("span", "h3studio-error", state.checkpointError));
    }

    function renderRuler(ruler, totalSeconds) {
        ruler.replaceChildren();
        const intervals = totalSeconds > 90 ? 30 : totalSeconds > 35 ? 10 : 5;
        for (let second = 0; second <= totalSeconds + .001; second += intervals) {
            const label = element("span", "", formatClock(second));
            label.style.position = "absolute";
            label.style.left = `${totalSeconds ? second / totalSeconds * 100 : 0}%`;
            label.style.transform = second ? "translateX(-50%)" : "";
            ruler.append(label);
        }
        const playhead = element("span", "h3studio-playhead");
        playhead.style.left = "0%";
        ruler.append(playhead);
        state.playhead = playhead;
        ruler.addEventListener("click", (event) => {
            if (!totalSeconds) return;
            const rect = ruler.getBoundingClientRect();
            const target = Math.max(0, Math.min(totalSeconds, (event.clientX - rect.left) / rect.width * totalSeconds));
            state.timelinePosition = target;
            state.view = "player"; persistView(); renderToolbarState(); renderPanel();
        });
    }

    function revealActiveTimelineScene() {
        const viewport = state.timelineViewport;
        const card = state.timelineHost?.querySelector(
            `[data-scene-index="${state.active}"]`,
        );
        if (!viewport || !card) return;
        const start = card.offsetLeft;
        const end = start + card.offsetWidth;
        const visibleStart = viewport.scrollLeft;
        const visibleEnd = visibleStart + viewport.clientWidth;
        if (start < visibleStart) viewport.scrollLeft = start;
        else if (end > visibleEnd) {
            viewport.scrollLeft = Math.max(0, end - viewport.clientWidth);
        }
    }

    function layoutTimeline({preserveScroll = true, revealActive = false,
        anchorRatio = .5} = {}) {
        const viewport = state.timelineViewport;
        const content = state.timelineContent;
        if (!viewport || !content || !state.plan) return;
        const oldWidth = Math.max(
            1,
            Number(content.dataset.timelineWidth) ||
                content.scrollWidth || viewport.clientWidth,
        );
        const boundedAnchor = Math.max(0, Math.min(1, Number(anchorRatio) || 0));
        const anchor = preserveScroll
            ? (viewport.scrollLeft + viewport.clientWidth * boundedAnchor) /
                oldWidth
            : 0;
        const result = timing();
        const layout = studioTimelineLayout(
            result.shots, viewport.clientWidth, state.timelineZoom,
        );
        state.timelineZoom = layout.zoom;
        state.timelineWidths = layout.widths;
        content.dataset.timelineWidth = String(layout.contentWidth);
        content.style.width = `${layout.contentWidth}px`;
        for (const host of [
            state.timelineHost, state.sourceTimelineHost,
            state.sourceAudioTimelineHost,
        ]) {
            if (!host) continue;
            [...host.querySelectorAll(
                ".h3studio-card,.h3studio-audio-card",
            )].forEach((card) => {
                const index = Number(card.dataset.sceneIndex);
                card.style.setProperty(
                    "--h3-scene-width",
                    `${layout.widths[index] ?? 0}px`,
                );
            });
        }
        if (state.timelineZoomInput) {
            state.timelineZoomInput.value = String(layout.zoom);
        }
        if (state.timelineZoomLabel) {
            state.timelineZoomLabel.textContent = `${Math.round(layout.zoom * 100)}%`;
        }
        requestAnimationFrame(() => {
            if (!viewport.isConnected) return;
            if (preserveScroll) {
                viewport.scrollLeft = Math.max(
                    0,
                    anchor * layout.contentWidth -
                        viewport.clientWidth * boundedAnchor,
                );
            }
            if (revealActive) revealActiveTimelineScene();
            layoutChapterMarkers();
        });
    }

    function layoutChapterMarkers() {
        if (!state.timelineHost) return;
        for (const marker of state.timelineHost.querySelectorAll(
            ".h3studio-chapter-marker",
        )) {
            const index = Number(marker.dataset.startSceneIndex);
            const card = state.timelineHost.querySelector(
                `[data-scene-index="${index}"]`,
            );
            if (card) marker.style.left = `${card.offsetLeft}px`;
        }
    }

    function setTimelineZoom(value, anchorRatio = .5) {
        state.timelineZoom = normalizedTimelineZoom(value);
        node.properties[TIMELINE_ZOOM_PROPERTY] = state.timelineZoom;
        layoutTimeline({preserveScroll:true, anchorRatio});
        dirty();
    }

    function sourceScene(index) {
        return matchingStudioSourceScene(
            state.sourcePreview, index, timing().shots[index],
        );
    }

    function sourceReference(index) {
        return sourceScene(index)?.references?.[0] ?? null;
    }

    function sourcePreviewUrl(index, reference = sourceReference(index)) {
        if (!state.sourcePreview?.token || !reference) return "";
        const query = new URLSearchParams({
            token:state.sourcePreview.token,
            scene:String(index + 1),
            slot:String(reference.slot ?? 0),
        });
        return api.apiURL(`/minimax_h3_context_loop/plan-studio/source-preview?${query.toString()}`);
    }

    function checkpointThumbnailUrl(index, checkpoint) {
        const revision = String(checkpoint?.revision ?? "").trim().toLowerCase();
        if (!checkpoint?.ready || !/^[0-9a-f]{32}$/.test(revision) || !runName()) {
            return "";
        }
        const query = new URLSearchParams({
            run_name:runName(), scene:String(index + 1), revision,
        });
        return api.apiURL(`/minimax_h3_context_loop/plan-studio/checkpoint-thumbnail?${query.toString()}`);
    }

    function sourceAudio() {
        return matchingStudioSourceAudio(state.sourcePreview, timing().shots);
    }

    function sourceAudioUrl() {
        if (!sourceAudio() || !state.sourcePreview?.token) return "";
        const query = new URLSearchParams({token:state.sourcePreview.token});
        return api.apiURL(`/minimax_h3_context_loop/plan-studio/source-audio?${query.toString()}`);
    }

    function sourceWaveformUrl(payload = state.sourcePreview) {
        if (!payload?.source_audio?.available || !payload?.token) return "";
        const query = new URLSearchParams({token:payload.token});
        return api.apiURL(`/minimax_h3_context_loop/plan-studio/source-waveform?${query.toString()}`);
    }

    function sourceAudioMuteMap() {
        const current = node.properties[SOURCE_AUDIO_MUTES_PROPERTY];
        if (current && typeof current === "object" && !Array.isArray(current)) return current;
        const created = {};
        node.properties[SOURCE_AUDIO_MUTES_PROPERTY] = created;
        return created;
    }

    function sourceAudioMuted(index) {
        const row = timing().shots[index];
        const key = row ? `${runName()}::${String(row.id)}` : "";
        return Boolean(key && sourceAudioMuteMap()[key]);
    }

    function setSourceAudioMuted(index, muted) {
        const row = timing().shots[index];
        if (!row) return;
        const mutes = sourceAudioMuteMap();
        const key = `${runName()}::${String(row.id)}`;
        if (muted) mutes[key] = true;
        else delete mutes[key];
        dirty();
        renderSourceAudioTimeline();
        root.querySelector(".h3studio-audio-generated")?.dispatchEvent(
            new Event("change"),
        );
    }

    function drawSourceWaveform(canvas, samples, color, muted) {
        requestAnimationFrame(() => {
            if (!canvas.isConnected) return;
            const ratio = Math.max(1, window.devicePixelRatio || 1);
            const width = Math.max(1, Math.round(canvas.clientWidth * ratio));
            const height = Math.max(1, Math.round(canvas.clientHeight * ratio));
            canvas.width = width; canvas.height = height;
            const context = canvas.getContext("2d");
            if (!context) return;
            context.clearRect(0, 0, width, height);
            context.strokeStyle = muted ? "rgba(190,198,214,.52)" : color;
            context.lineWidth = Math.max(1, ratio);
            const middle = height / 2;
            context.beginPath();
            if (!samples.length) {
                context.moveTo(0, middle); context.lineTo(width, middle);
            } else {
                for (let x = 0; x < width; x += Math.max(1, Math.round(ratio))) {
                    const sample = Math.max(0, Math.min(1, Number(
                        samples[Math.min(samples.length - 1, Math.floor(
                            x / width * samples.length,
                        ))],
                    ) || 0));
                    const half = Math.max(ratio, sample * (height / 2 - ratio));
                    context.moveTo(x, middle - half); context.lineTo(x, middle + half);
                }
            }
            context.stroke();
        });
    }

    async function loadSourceWaveform(payload = state.sourcePreview) {
        const token = String(payload?.token ?? "");
        const url = sourceWaveformUrl(payload);
        if (!token || !url) return;
        if (state.sourceWaveformToken === token && state.sourceWaveform) return;
        if (state.sourceWaveformToken === token && state.sourceWaveformPromise) {
            return state.sourceWaveformPromise;
        }
        state.sourceWaveformToken = token;
        state.sourceWaveform = null;
        const request = (async () => {
            const response = await api.fetchApi(url);
            const waveform = await response.json();
            if (!response.ok) throw new Error(
                waveform.error || `HTTP ${response.status}`,
            );
            if (state.disposed || state.sourceWaveformToken !== token) return;
            state.sourceWaveform = waveform;
            renderSourceAudioTimeline();
        })();
        state.sourceWaveformPromise = request;
        try { await request; }
        catch (error) {
            if (state.sourceWaveformToken === token) {
                state.sourceWaveform = {samples:[], error:error?.message || String(error)};
                renderSourceAudioTimeline();
            }
        } finally {
            if (state.sourceWaveformPromise === request) {
                state.sourceWaveformPromise = null;
            }
        }
    }

    function applySourcePresentation(payload) {
        if (!payload || String(payload.run_name ?? "") !== runName()) return;
        if (state.sourceWaveformToken !== String(payload.token ?? "")) {
            state.sourceWaveform = null;
            state.sourceWaveformToken = "";
            state.sourceWaveformPromise = null;
        }
        state.sourcePreview = payload;
        renderSourceTimeline();
        renderSourceAudioTimeline();
        if (payload.source_audio?.available) void loadSourceWaveform(payload);
        if (state.view === "player" && state.player) {
            seekTimeline(
                state.timelinePosition ?? studioSceneStartSeconds(
                    timing().shots, state.active),
                false,
            );
        }
    }

    async function restoreSourcePresentation() {
        const currentRun = runName();
        if (!currentRun || state.disposed) return;
        const token = ++state.presentationToken;
        try {
            const query = new URLSearchParams({run_name:currentRun});
            const response = await api.fetchApi(
                `/minimax_h3_context_loop/plan-studio/presentation?${query.toString()}`,
            );
            const payload = await response.json();
            if (response.status === 404) return;
            if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
            if (state.disposed || token !== state.presentationToken
                    || currentRun !== runName()) return;
            applySourcePresentation(payload);
        } catch (error) {
            if (token === state.presentationToken) {
                console.warn("Plan Studio could not restore its saved track", error);
            }
        }
    }

    function updateTimelineCheckpointCard(card, index, result = timing()) {
        if (!card) return;
        const row = result.shots[index];
        const checkpoint = matchingStudioCheckpoint(
            state.checkpoints, index, row,
        );
        card.classList.toggle("h3studio-rendered", Boolean(checkpoint?.ready));
        const url = checkpointThumbnailUrl(index, checkpoint);
        const current = card.querySelector(".h3studio-card-thumbnail");
        if (!url) {
            current?.remove();
            delete card.dataset.checkpointThumbnail;
            return;
        }
        if (card.dataset.checkpointThumbnail === url && current) return;
        current?.remove();
        const image = element("img", "h3studio-card-thumbnail");
        image.alt = "";
        image.loading = "lazy";
        image.decoding = "async";
        image.src = url;
        image.addEventListener("error", () => {
            image.remove();
            if (card.dataset.checkpointThumbnail === url) {
                delete card.dataset.checkpointThumbnail;
            }
        }, {once:true});
        card.dataset.checkpointThumbnail = url;
        card.prepend(image);
    }

    function refreshTimelineCheckpoints() {
        if (!state.timelineHost || !state.plan) return;
        const result = timing();
        for (const card of state.timelineHost.querySelectorAll(
            ".h3studio-card[data-scene-index]",
        )) {
            const index = Number(card.dataset.sceneIndex);
            if (Number.isInteger(index) && index >= 0
                    && index < result.shots.length) {
                updateTimelineCheckpointCard(card, index, result);
            }
        }
    }

    function renderTimeline() {
        const host = state.timelineHost;
        if (!host || !state.plan) return;
        host.replaceChildren();
        const result = timing();
        for (let index = 0; index < state.plan.shots.length; index += 1) {
            const shot = state.plan.shots[index];
            const row = result.shots[index];
            const checkpoint = matchingStudioCheckpoint(state.checkpoints, index, row);
            const card = button("", `Scene ${index + 1}: ${row.id}`, () => void selectScene(index));
            card.dataset.sceneIndex = String(index);
            card.className = `h3studio-card${index === state.active ? " h3studio-selected" : ""}${checkpoint?.ready ? " h3studio-rendered" : ""}`;
            card.style.setProperty("--scene", automaticSceneColor(index));
            if (state.timelineWidths[index] > 0) {
                card.style.setProperty(
                    "--h3-scene-width", `${state.timelineWidths[index]}px`,
                );
            }
            updateTimelineCheckpointCard(card, index, result);
            const copy = element("span", "h3studio-card-copy");
            copy.append(element("span", "h3studio-card-title", `${index + 1}. ${row.id}`),
                element("span", "h3studio-card-meta", `${formatClock(row.deliveredSeconds)} · ${row.rawFrames || "—"}f raw${row.loraRoute === "base" ? "" : ` · LoRA ${row.loraRoute.toUpperCase()}`}`));
            card.append(copy, element("span", "h3studio-render-dot"));
            host.append(card);
        }
        for (const chapter of orderedChapters(state.plan)) {
            const index = state.plan.shots.findIndex((shot, offset) => (
                safeShotId(shot?.id, `clip_${String(offset + 1).padStart(4, "0")}`)
                    === chapter.start_scene_id
            ));
            if (index < 0) continue;
            const marker = button("", `${chapter.title}, before scene ${index + 1}`, () => {
                void selectChapter(chapter.id);
            });
            marker.className = `h3studio-chapter-marker${state.activeChapterId === chapter.id ? " h3studio-selected" : ""}`;
            marker.dataset.startSceneIndex = String(index);
            marker.dataset.chapterId = chapter.id;
            marker.append(element("span", "", chapter.title));
            host.append(marker);
        }
        renderSourceTimeline();
        renderSourceAudioTimeline();
        layoutTimeline({
            preserveScroll:Boolean(state.timelineContent?.dataset.timelineWidth),
            revealActive:true,
        });
    }

    function renderSourceTimeline() {
        const host = state.sourceTimelineHost;
        if (!host || !state.plan) return;
        host.replaceChildren();
        const result = timing();
        const available = result.shots.some((_row, index) => sourceScene(index));
        if (!available) {
            host.append(element(
                "div", "h3studio-source-empty",
                state.sourcePreview
                    ? "No active path-backed motion reference in this Plan."
                    : "Queue Plan Studio once to load motion-reference windows.",
            ));
            return;
        }
        for (let index = 0; index < state.plan.shots.length; index += 1) {
            const row = result.shots[index];
            const scene = sourceScene(index);
            const reference = scene?.references?.[0] ?? null;
            const card = button("", reference
                ? `Scene ${index + 1} source motion @${reference.tag}`
                : `Scene ${index + 1} has no active path-backed motion reference`,
            () => void selectScene(index));
            card.dataset.sceneIndex = String(index);
            card.className = `h3studio-card h3studio-source-card${index === state.active ? " h3studio-selected" : ""}`;
            card.style.setProperty("--scene", automaticSceneColor(index));
            if (state.timelineWidths[index] > 0) {
                card.style.setProperty(
                    "--h3-scene-width", `${state.timelineWidths[index]}px`,
                );
            }
            if (reference && index === state.active && state.view !== "player") {
                const media = element("video");
                media.muted = true; media.playsInline = true; media.preload = "metadata";
                media.src = sourcePreviewUrl(index, reference);
                media.addEventListener("loadedmetadata", () => {
                    try { media.currentTime = studioSourceSecond(reference, 0); }
                    catch (_error) {}
                }, {once:true});
                card.append(media);
            }
            const copy = element("span", "h3studio-card-copy");
            copy.append(
                element("span", "h3studio-card-title", reference
                    ? `@${reference.tag} · ${reference.start_frame}:${reference.end_frame}`
                    : "No active @motion"),
                element("span", "h3studio-card-meta", reference
                    ? `${reference.frame_count}f source · +${reference.compare_offset_frames}f compare offset`
                    : `Scene ${index + 1}`),
            );
            card.append(copy, element("span", "h3studio-render-dot"));
            host.append(card);
        }
    }

    function renderSourceAudioTimeline() {
        const host = state.sourceAudioTimelineHost;
        if (!host || !state.plan) return;
        host.replaceChildren();
        const audio = sourceAudio();
        if (!audio) {
            const descriptor = state.sourcePreview?.source_audio;
            const message = !state.sourcePreview
                ? "Queue Plan Studio once to load Source Timeline audio."
                : descriptor?.timeline_available && !descriptor?.has_audio
                    ? "Source Timeline connected · no audio."
                    : descriptor?.timeline_available
                        ? "Source Timeline audio exists but is not path-backed yet."
                        : "No Source Timeline is connected.";
            host.append(element("div", "h3studio-source-empty", message));
            return;
        }
        const result = timing();
        for (let index = 0; index < result.shots.length; index += 1) {
            const row = result.shots[index];
            const muted = sourceAudioMuted(index);
            const card = element(
                "div",
                `h3studio-audio-card${index === state.active ? " h3studio-selected" : ""}${muted ? " h3studio-audio-muted" : ""}`,
            );
            card.dataset.sceneIndex = String(index);
            card.title = `Scene ${index + 1} Source Timeline audio${muted ? " (muted)" : ""}`;
            card.style.setProperty("--scene", automaticSceneColor(index));
            if (state.timelineWidths[index] > 0) {
                card.style.setProperty(
                    "--h3-scene-width", `${state.timelineWidths[index]}px`,
                );
            }
            card.addEventListener("click", () => void selectScene(index));
            const canvas = element("canvas", "h3studio-waveform");
            const samples = studioWaveformSceneSamples(
                state.sourceWaveform, result.shots, index,
            );
            drawSourceWaveform(
                canvas, samples, automaticSceneColor(index), muted,
            );
            const mute = button(
                muted ? "🔇" : "🔊",
                muted
                    ? `Unmute source audio for scene ${index + 1}`
                    : `Mute source audio for scene ${index + 1}`,
                (event) => {
                    event.stopPropagation();
                    setSourceAudioMuted(index, !muted);
                },
            );
            mute.className = "h3studio-audio-mute";
            card.append(canvas, mute);
            host.append(card);
        }
        if (!state.sourceWaveform && !state.sourceWaveformPromise) {
            void loadSourceWaveform();
        }
    }

    function updateTimelineSelection() {
        for (const host of [
            state.timelineHost, state.sourceTimelineHost,
            state.sourceAudioTimelineHost,
        ]) {
            if (!host) continue;
            [...host.querySelectorAll(".h3studio-card,.h3studio-audio-card")].forEach(
                (card) => card.classList.toggle(
                    "h3studio-selected", Number(card.dataset.sceneIndex) === state.active,
                ),
            );
        }
        for (const marker of state.timelineHost?.querySelectorAll(
            ".h3studio-chapter-marker",
        ) ?? []) {
            marker.classList.toggle(
                "h3studio-selected",
                Boolean(state.activeChapterId)
                    && marker.dataset.chapterId === state.activeChapterId,
            );
        }
    }

    async function selectScene(index, synchronize = true) {
        await flushHistoryDraft();
        state.activeChapterId = "";
        state.active = Math.max(0, Math.min(state.plan.shots.length - 1, Number(index)));
        if (state.view === "player") {
            state.timelinePosition = studioSceneStartSeconds(timing().shots, state.active);
        }
        persistView(); renderSourceTimeline(); renderSourceAudioTimeline();
        updateTimelineSelection();
        revealActiveTimelineScene();
        if (state.view === "player" && state.player) {
            seekTimeline(state.timelinePosition, false);
        } else renderPanel();
        if (synchronize) publishActiveScene();
    }

    async function selectChapter(chapterId) {
        await flushHistoryDraft();
        const chapter = orderedChapters(state.plan).find(
            (candidate) => candidate.id === chapterId,
        );
        if (!chapter) return;
        state.activeChapterId = chapter.id;
        state.view = "scene";
        persistView();
        renderToolbarState();
        renderTimeline();
        renderPanel();
    }

    function field(label, control) {
        const wrap = element("label", "h3studio-field");
        wrap.append(element("span", "", label), control);
        return wrap;
    }

    function renderReferenceTray(tray, textarea) {
        tray.replaceChildren();
        const referenceData = availableReferenceRecords(
            state.planNode ?? node, state.active + 1, {
                includeInactive: true,
                prompt: [
                    sharedPrompt(state.plan).text.trim(), textarea.value.trim(),
                ].filter(Boolean).join("\n\n"),
            },
        );
        const {wrapper} = referenceData;
        const records = referenceData.mode === "tagged"
            ? referenceData.records
            : referenceData.records.filter((record) => record.active);
        if (!records.length) {
            tray.append(element("span", "h3studio-message", wrapper
                ? `No connected references are active in scene ${state.active + 1}.`
                : "No downstream Tagged/Scheduled Ref2VA, core Ref2VA, or I2V references were found."));
            return;
        }
        function syntaxFor(record) {
            const key = `${String(state.plan?.shots?.[state.active]?.id ?? state.active)}:${record.tag}`;
            const usedMode = referenceData.mode === "tagged" && record.supportsSemantic
                ? taggedPictureReferenceMode(textarea.value, record.tag) : "native";
            return {
                key,
                usedMode,
                syntax:["native", "semantic"].includes(usedMode)
                    ? usedMode : state.referenceSyntax.get(key) ?? "native",
            };
        }
        const preview = element("div", "h3studio-ref-preview");
        function show(record) {
            preview.replaceChildren();
            const kind = record.kind === "picture" ? "image" : record.kind;
            const url = record.previewUrl
                ? api.apiURL(record.previewUrl)
                : findMediaPreview(record.source, kind);
            if (url) {
                const media = element(kind === "image" ? "img" : kind);
                media.src = url;
                if (kind !== "image") { media.controls = true; media.preload = "metadata"; }
                preview.append(media);
            }
            const {syntax} = syntaxFor(record);
            const displayToken = syntax === "semantic"
                ? taggedPictureReferenceToken(record.tag, "semantic")
                : record.token;
            preview.append(element("div", "", `${displayToken}${record.label && record.label !== record.token ? ` → ${record.label}` : ""}\n${record.kind} · ${record.selector === "prompt tag" ? "insert to activate" : `scenes ${record.selector}`}`));
        }
        const icons = {picture:"▧",video:"▶",audio:"♫"};
        for (const record of records) {
            const {key, usedMode, syntax} = syntaxFor(record);
            const displayToken = syntax === "semantic"
                ? taggedPictureReferenceToken(record.tag, "semantic")
                : record.token;
            const entry = element("div", "h3studio-ref-entry");
            const chip = button(`${icons[record.kind] ?? "@"} ${displayToken}`, "Insert this connected reference label or alias", () => {
                const start = textarea.selectionStart ?? textarea.value.length;
                insertText(textarea, displayToken);
                if (syntax === "semantic") {
                    textarea.setSelectionRange(
                        start + displayToken.indexOf("[") + 1,
                        start + displayToken.lastIndexOf("s]"),
                    );
                }
                tray.classList.remove("h3studio-open");
            });
            chip.addEventListener("mouseenter", () => show(record));
            chip.addEventListener("focus", () => show(record));
            entry.append(chip);
            if (referenceData.mode === "tagged" && record.supportsSemantic) {
                const modes = element("div", "h3studio-ref-mode");
                for (const [target, label] of [["native", "@"], ["semantic", "#"]]) {
                    const control = button(
                        label,
                        target === "native"
                            ? "Use native @tag and convert semantic anchors in this scene"
                            : "Use semantic #tag[time] and convert native tags in this scene",
                        () => {
                            state.referenceSyntax.set(key, target);
                            const next = convertTaggedPictureReference(
                                textarea.value, record.tag, target,
                            );
                            if (next !== textarea.value) {
                                textarea.value = next;
                                textarea.dispatchEvent(new InputEvent("input", {
                                    bubbles:true, inputType:"insertReplacementText",
                                }));
                            }
                            renderReferenceTray(tray, textarea);
                        },
                    );
                    control.classList.toggle(
                        "h3studio-selected",
                        syntax === target || usedMode === "mixed",
                    );
                    modes.append(control);
                }
                entry.append(modes);
            }
            tray.append(entry);
        }
        tray.append(preview); show(records[0]);
    }

    function renderScenePanel() {
        const shot = state.plan.shots[state.active];
        const row = timing().shots[state.active];
        const panel = element("div");
        const head = element("div", "h3studio-scene-head");
        head.append(element("strong", "", `Scene ${state.active + 1} of ${state.plan.shots.length}`),
            element("span", "h3studio-scene-label", `${row.rawFrames || "—"} raw · ${row.deliveredFrames || "—"} delivered · ${row.videoBlendFrames}f incoming blend · starts at ${formatClock(row.generationStartFrame / 24)}`));
        const grid = h3StudioGridMarkers(
            row.rawFrames, row.contextLength, row.continuationMode,
            row.preservesGeneratedAudioPrefix,
        );
        const gridMarkers = element("span", "h3studio-grid-markers");
        const rawGrid = element(
            "span",
            `h3studio-grid-marker ${grid.raw.onGrid
                ? "h3studio-grid-exact" : "h3studio-grid-warning"}`,
            grid.raw.label,
        );
        rawGrid.title = grid.raw.onGrid
            ? "Raw generation length is on H3's 17n+5 temporal latent grid."
            : "Raw generation length is off H3's 17n+5 temporal latent grid.";
        gridMarkers.append(rawGrid);
        if (grid.av) {
            const avGrid = element(
                "span",
                `h3studio-grid-marker ${grid.av.exact
                    ? "h3studio-grid-exact" : "h3studio-grid-warning"}`,
                grid.av.label,
            );
            avGrid.title = grid.av.exact
                ? (grid.av.audioPreserved
                    ? "The AV context ends on both H3's video latent grid and its 40 Hz audio grid."
                    : "Valid video-only AV context. Generated predecessor audio is not carried, so the 40 Hz audio grid does not constrain this test.")
                : "This AV context is invalid because carried predecessor audio ends between 40 Hz ticks. Exact aligned choices are 39, 90, 141, 192, … frames.";
            gridMarkers.append(avGrid);
        }
        if (grid.cut) {
            const cut = element(
                "span",
                "h3studio-grid-marker h3studio-grid-experimental",
                grid.cut.label,
            );
            cut.title = "Experimental only: nearest reported four-frame 17n−3 cut window for generated-to-real joins. This does not change or validate the Plan.";
            gridMarkers.append(cut);
        }
        head.append(gridMarkers);

        const id = element("input");
        id.value = shot.id ?? "";
        id.addEventListener("change", () => {
            const previousId = safeShotId(shot.id, row.id);
            shot.id = safeShotId(id.value, row.id); id.value = shot.id;
            for (const chapter of state.plan.chapters ?? []) {
                if (chapter.start_scene_id === previousId) {
                    chapter.start_scene_id = shot.id;
                }
            }
            writePlan(); renderShell();
        });
        const mode = element("select");
        for (const [value,label] of [["default","Plan default"],["seconds","Seconds"],["frames","Exact frames"]]) {
            const option = element("option", "", label); option.value = value; mode.append(option);
        }
        const length = element("input"); length.type = "number";
        function refreshLength() {
            const selected = shotLengthMode(shot); mode.value = selected; length.disabled = selected === "default";
            if (selected === "seconds") { length.value = shot.duration_seconds ?? ""; length.min = ".01"; length.max = String(3592 / 24); length.step = ".01"; }
            else if (selected === "frames") { length.value = shot.length ?? shot.frames ?? ""; length.min = "5"; length.max = "3592"; length.step = "17"; }
            else length.value = "";
        }
        mode.addEventListener("change", () => {
            setShotLengthMode(shot, mode.value, settings().defaultDurationSeconds);
            refreshLength(); writePlan(); renderShell();
        });
        length.addEventListener("change", () => {
            if (mode.value === "seconds") shot.duration_seconds = Number(length.value);
            if (mode.value === "frames") { shot.length = Number(length.value); delete shot.frames; }
            writePlan(); renderShell();
        });
        refreshLength();
        const lengthControl = element("span", "h3studio-length"); lengthControl.append(mode, length);
        const steps = element("input"); steps.type = "number"; steps.min = "1"; steps.max = "10000";
        steps.placeholder = String(settings().defaultSteps); steps.value = shot.steps ?? "";
        steps.addEventListener("change", () => { if (steps.value) shot.steps = Number(steps.value); else delete shot.steps; writePlan(); });
        const promptSeedMode = element("select");
        for (const [value, label] of [
            ["inherit", "Stable derived"],
            ["fixed", "Fixed scene seed"],
            ["randomize", "Randomize each queue"],
        ]) {
            const option = element("option", "", label);
            option.value = value;
            promptSeedMode.append(option);
        }
        const promptSeed = element("input");
        promptSeed.type = "text";
        promptSeed.inputMode = "numeric";
        promptSeed.placeholder = "Prompt seed";
        const promptSeedWrap = element("span", "h3studio-prompt-seed");
        const rerollPromptSeed = button(
            "↻", "Store a new fixed prompt-alternative seed for this scene",
            () => {
                shot.prompt_seed_mode = "fixed";
                shot.prompt_seed = randomSceneSeed();
                refreshPromptSeed();
                writePlan();
            },
        );
        function refreshPromptSeed() {
            const selected = scenePromptSeedMode(shot);
            promptSeedMode.value = selected;
            promptSeed.disabled = selected !== "fixed";
            rerollPromptSeed.disabled = selected !== "fixed";
            promptSeed.value = selected === "fixed" ? (shot.prompt_seed ?? "") : "";
            promptSeedWrap.title = selected === "inherit"
                ? "Derive a stable seed from this scene's index and ID for its {one|two} choices."
                : selected === "randomize"
                    ? "Choose fresh prompt alternatives whenever this Plan is queued; the exact choice seed is saved with the checkpoint."
                    : "Exact uint64 seed for this scene's prompt alternatives. This does not change sampler noise.";
        }
        promptSeedMode.addEventListener("change", () => {
            setScenePromptSeedMode(shot, promptSeedMode.value);
            refreshPromptSeed();
            writePlan();
            renderStatus();
        });
        promptSeed.addEventListener("change", () => {
            if (promptSeed.value.trim()) shot.prompt_seed = promptSeed.value.trim();
            else shot.prompt_seed = randomSceneSeed();
            setScenePromptSeedMode(shot, "fixed");
            refreshPromptSeed();
            writePlan();
        });
        promptSeedWrap.append(promptSeedMode, promptSeed, rerollPromptSeed);
        refreshPromptSeed();
        const seed = element("input"); seed.type = "text"; seed.inputMode = "numeric"; seed.placeholder = "Stable derived seed"; seed.value = shot.seed ?? "";
        seed.addEventListener("change", () => { if (seed.value.trim()) shot.seed = seed.value.trim(); else delete shot.seed; writePlan(); });
        const seedWrap = element("span", "h3studio-length");
        const reroll = button("↻", "Store a new random seed for this scene", () => { seed.value = randomSceneSeed(); shot.seed = seed.value; writePlan(); });
        seedWrap.append(seed, reroll);
        const loraRoute = element("select");
        for (const route of SCENE_LORA_ROUTES) {
            const option = element(
                "option", "",
                route === "base" ? "Base model" : `LoRA ${route.toUpperCase()}`,
            );
            option.value = route;
            loraRoute.append(option);
        }
        loraRoute.value = sceneLoRARoute(shot);
        loraRoute.title = "Select the Base or A-D MODEL branch on MiniMax H3 Scene LoRA Scheduler. Branches come from ordinary ComfyUI LoRA loaders.";
        loraRoute.addEventListener("change", () => {
            if (loraRoute.value === "base") delete shot.lora_route;
            else shot.lora_route = loraRoute.value;
            sceneLoRARoute(shot);
            writePlan();
            renderTimeline();
        });
        const planSettings = settings();
        function normalizeVisualLeadSpan() {
            if (!Object.hasOwn(shot, "visual_context_lead_source")) return;
            const resolved = sceneContextLength(
                shot, planSettings.contextLength,
            );
            const allowed = visualContextCompositions()
                .filter((choice) => choice.total === resolved)
                .map((choice) => choice.lead);
            if (!allowed.length) {
                delete shot.visual_context_lead_source;
                delete shot.visual_context_lead_frames;
                delete shot.visual_context_lead_start_frame;
                return;
            }
            try {
                sceneVisualContextLeadFrames(shot, resolved);
            } catch (_error) {
                shot.visual_context_lead_frames = allowed[0];
            }
        }
        const incomingTransition = element("select");
        const inheritOption = element(
            "option", "",
            `Inherit Chain Policy · ${transitionPresetLabel(planSettings.transitionPreset)}`,
        );
        inheritOption.value = "inherit";
        incomingTransition.append(inheritOption);
        for (const preset of primaryTransitionOptions()) {
            const option = element(
                "option", "", `${preset.label} · ${preset.description}`,
            );
            option.value = preset.name;
            incomingTransition.append(option);
        }
        function refreshIncomingTransition() {
            const selected = sceneTransitionPreset(
                shot, planSettings.continuationMode,
                planSettings.contextLength,
                planSettings.audioContextLength,
            );
            let custom = incomingTransition.querySelector(
                'option[value="custom"]',
            );
            if (selected === "custom" && !custom) {
                custom = element(
                    "option", "", transitionPresetLabel("custom"),
                );
                custom.value = "custom";
                incomingTransition.append(custom);
            }
            incomingTransition.value = selected;
        }
        refreshIncomingTransition();
        incomingTransition.title = "One semantic boundary choice. Inherit "
            + "uses the connected Chain Policy. A preset writes its tested "
            + "visual implementation/context pair and restores automatic "
            + "generated-audio context. Custom means raw Advanced "
            + "overrides remain below.";
        incomingTransition.addEventListener("change", () => {
            if (incomingTransition.value === "custom") return;
            applySceneTransitionPreset(shot, incomingTransition.value);
            const nextContext = sceneContextLength(
                shot, planSettings.contextLength,
            );
            if (Object.hasOwn(shot, "video_blend_frames")
                    && Number(shot.video_blend_frames) > nextContext) {
                shot.video_blend_frames = nextContext;
            }
            normalizeVisualLeadSpan();
            delete shot.visual_context_start_frame;
            delete shot.visual_context_lead_start_frame;
            writePlan();
            renderShell();
        });
        const context = element("select");
        for (const [value, label] of [
            ["", `Plan default · ${settings().contextLength}`],
            ["0", "0 · new visual"],
            ...H3_CONTEXT_LENGTHS.map((value) => [String(value), `${value} frames`]),
        ]) {
            const option = element("option", "", label);
            option.value = value;
            context.append(option);
        }
        context.value = Object.hasOwn(shot, "context_length")
            && shot.context_length !== null ? String(shot.context_length) : "";
        context.title = state.active === 0
            ? "Blank inherits the Plan video context. Zero ignores Existing Video Context visually."
            : "Video context entering this scene. Blank inherits the Plan default; zero starts a visually new scene. Audio is controlled beside it.";
        context.addEventListener("change", () => {
            if (context.value === "") delete shot.context_length;
            else shot.context_length = Number(context.value);
            sceneContextLength(shot, settings().contextLength);
            normalizeVisualLeadSpan();
            delete shot.visual_context_start_frame;
            delete shot.visual_context_lead_start_frame;
            refreshBlendControl();
            refreshIncomingTransition();
            writePlan();
            renderShell();
        });
        const visualSource = element("select");
        if (state.active === 0) {
            const option = element(
                "option", "", "Existing Video Context (if connected)",
            );
            option.value = "";
            visualSource.append(option);
            visualSource.disabled = true;
        } else {
            const previousIndex = state.active;
            const previousId = safeShotId(
                state.plan.shots[previousIndex - 1]?.id,
                `clip_${String(previousIndex).padStart(4, "0")}`,
            );
            const previous = element(
                "option", "",
                `Previous scene · ${previousIndex} ${previousId}`,
            );
            previous.value = "";
            visualSource.append(previous);
            for (let sourceOffset = 0;
                sourceOffset < state.active - 1; sourceOffset += 1) {
                const sourceId = safeShotId(
                    state.plan.shots[sourceOffset]?.id,
                    `clip_${String(sourceOffset + 1).padStart(4, "0")}`,
                );
                const option = element(
                    "option", "",
                    `Scene ${sourceOffset + 1} · ${sourceId}`,
                );
                option.value = sourceId;
                visualSource.append(option);
            }
            const rawSource = shot.visual_context_source;
            if (rawSource === undefined || rawSource === null
                    || ["", "previous", "immediate"].includes(
                        String(rawSource).trim().toLowerCase())) {
                visualSource.value = "";
            } else {
                try {
                    const resolved = sceneVisualContextSource(
                        state.plan, state.active + 1,
                    );
                    visualSource.value = resolved === state.active ? ""
                        : safeShotId(
                            state.plan.shots[resolved - 1]?.id,
                            `clip_${String(resolved).padStart(4, "0")}`,
                        );
                } catch (_error) {
                    const invalid = element(
                        "option", "", `Invalid · ${String(rawSource)}`,
                    );
                    invalid.value = String(rawSource);
                    visualSource.append(invalid);
                    visualSource.value = String(rawSource);
                }
            }
        }
        visualSource.title = state.active === 0
            ? "Scene 1 visual context comes from Existing Video Context."
            : "Select any earlier saved scene for video/RGB context. Generated-audio continuity still uses the immediately previous timeline scene. Non-linear visual context forces a hard assembly cut.";
        visualSource.addEventListener("change", () => {
            if (!visualSource.value) {
                delete shot.visual_context_source;
            } else {
                shot.visual_context_source = visualSource.value;
                shot.video_blend_frames = 0;
            }
            delete shot.visual_context_start_frame;
            const recentSource = sceneVisualContextSource(
                state.plan, state.active + 1,
            );
            const leadSource = sceneVisualContextLeadSource(
                state.plan, state.active + 1,
            );
            if (leadSource !== null && leadSource === recentSource) {
                delete shot.visual_context_lead_source;
                delete shot.visual_context_lead_frames;
                delete shot.visual_context_lead_start_frame;
            }
            refreshBlendControl();
            writePlan();
            renderShell();
        });
        const visualLeadSource = element("select");
        const noLead = element("option", "", "Off · one visual source");
        noLead.value = "";
        visualLeadSource.append(noLead);
        const recentSourceIndex = state.active === 0 ? null
            : sceneVisualContextSource(state.plan, state.active + 1);
        if (recentSourceIndex !== null) {
            for (let sourceOffset = 0;
                sourceOffset < state.active; sourceOffset += 1) {
                if (sourceOffset + 1 === recentSourceIndex) continue;
                const sourceId = safeShotId(
                    state.plan.shots[sourceOffset]?.id,
                    `clip_${String(sourceOffset + 1).padStart(4, "0")}`,
                );
                const option = element(
                    "option", "", `Scene ${sourceOffset + 1} · ${sourceId}`,
                );
                option.value = sourceId;
                visualLeadSource.append(option);
            }
        }
        visualLeadSource.disabled = state.active === 0 || state.active < 2;
        try {
            const resolvedLead = sceneVisualContextLeadSource(
                state.plan, state.active + 1,
            );
            visualLeadSource.value = resolvedLead === null ? ""
                : safeShotId(
                    state.plan.shots[resolvedLead - 1]?.id,
                    `clip_${String(resolvedLead).padStart(4, "0")}`,
                );
        } catch (_error) {
            visualLeadSource.value = "";
        }
        visualLeadSource.title = "Optional first scene in one composed visual context. Visual context source supplies the second block nearest generation. Either source may be chronologically newer, but they must differ; generated audio remains continuous from the immediate timeline predecessor.";

        const visualLeadFrames = element("select");
        const resolvedVisualContext = sceneContextLength(
            shot, settings().contextLength,
        );
        const compositionChoices = visualContextCompositions();
        const defaultComposition = compositionChoices.find(
            (choice) => choice.total === resolvedVisualContext,
        ) ?? compositionChoices[0];
        visualLeadSource.disabled = visualLeadSource.disabled
            || !compositionChoices.length;
        for (const total of H3_CONTEXT_LENGTHS) {
            const groupChoices = compositionChoices.filter(
                (choice) => choice.total === total,
            );
            if (!groupChoices.length) continue;
            const group = element("optgroup");
            group.label = `${total} total frames`;
            for (const choice of groupChoices) {
                const option = element("option", "", choice.label);
                option.value = choice.value;
                group.append(option);
            }
            visualLeadFrames.append(group);
        }
        visualLeadFrames.disabled = !visualLeadSource.value
            || !compositionChoices.length;
        if (visualLeadSource.value) {
            try {
                const lead = sceneVisualContextLeadFrames(
                    shot, resolvedVisualContext,
                );
                visualLeadFrames.value = `${resolvedVisualContext}:${lead}`;
            } catch (_error) {
                visualLeadFrames.value = defaultComposition?.value ?? "";
            }
        } else {
            visualLeadFrames.value = defaultComposition?.value ?? "";
        }
        visualLeadFrames.title = "Select the total H3 context and its ordered two-scene split. Both orientations are available: for example, 39 total includes 17+22 and 22+17. Reverse-phase layouts are normalized once through the connected video VAE when required.";
        function applyVisualComposition() {
            const [totalRaw, leadRaw] = visualLeadFrames.value.split(":");
            const total = Number(totalRaw);
            const lead = Number(leadRaw);
            if (!Number.isInteger(total) || !Number.isInteger(lead)) return;
            shot.context_length = total;
            shot.visual_context_lead_frames = lead;
            sceneVisualContextLeadFrames(shot, total);
            shot.video_blend_frames = 0;
        }
        visualLeadSource.addEventListener("change", () => {
            if (!visualLeadSource.value) {
                delete shot.visual_context_lead_source;
                delete shot.visual_context_lead_frames;
                delete shot.visual_context_lead_start_frame;
            } else {
                shot.visual_context_lead_source = visualLeadSource.value;
                applyVisualComposition();
            }
            delete shot.visual_context_start_frame;
            delete shot.visual_context_lead_start_frame;
            refreshBlendControl();
            writePlan();
            renderShell();
        });
        visualLeadFrames.addEventListener("change", () => {
            if (visualLeadSource.value) {
                applyVisualComposition();
            }
            delete shot.visual_context_start_frame;
            delete shot.visual_context_lead_start_frame;
            refreshBlendControl();
            writePlan();
            renderShell();
        });
        const audioContext = element("input");
        audioContext.type = "number";
        audioContext.min = "0";
        audioContext.max = "240";
        audioContext.step = "1";
        audioContext.value = shot.audio_context_length ?? "";
        const planAudioContextLength = Number(settings().audioContextLength);
        audioContext.placeholder = planAudioContextLength
            ? String(planAudioContextLength)
            : `Video ${settings().contextLength}`;
        audioContext.title = "Blank inherits the Plan audio context; an explicit 0 carries no prior generated audio. Positive audio context works with zero video context in guide generated-audio modes. AV mask modes remain synchronized to video.";
        audioContext.addEventListener("change", () => {
            if (audioContext.value === "") delete shot.audio_context_length;
            else shot.audio_context_length = Number(audioContext.value);
            refreshIncomingTransition();
            writePlan();
            renderStatus();
        });
        const contextPair = element("span", "h3studio-context-pair");
        contextPair.append(context, audioContext);
        const blendFrames = element("input");
        blendFrames.type = "number";
        blendFrames.min = "0";
        blendFrames.step = "1";
        blendFrames.value = shot.video_blend_frames ?? "";
        function refreshBlendControl() {
            const resolvedContext = sceneContextLength(
                shot, settings().contextLength,
            );
            blendFrames.max = String(resolvedContext);
            blendFrames.placeholder = String(Math.min(
                Number(settings().videoBlendFrames), resolvedContext,
            ));
        }
        refreshBlendControl();
        blendFrames.title = state.active === 0
            ? "Assembly blend entering scene 1 when Existing Video Context is present. Blank inherits the Plan default, capped to scene context."
            : "Assembly blend from the previous scene into this scene. Blank inherits the Plan default, capped to scene context; zero is a hard cut. It does not change diffusion.";
        blendFrames.addEventListener("change", () => {
            if (blendFrames.value === "") delete shot.video_blend_frames;
            else shot.video_blend_frames = Number(blendFrames.value);
            sceneVideoBlendFrames(
                shot, settings().videoBlendFrames,
                sceneContextLength(shot, settings().contextLength),
            );
            writePlan();
            renderStatus();
        });
        const continuation = element("select");
        for (const [value, label] of [
            ["", `Plan default · ${settings().continuationMode}`],
            ["guide", "Guide · new shot"],
            ["tone_carry_guide", "Tone Carry Guide · corrected RGB context"],
            ["latent_guide", "Latent Guide · direct generated latent"],
            ["tapered_guide", "Detail Guide · color injection"],
            ["tapered_av", "Detail AV · experimental latent taper"],
            ["drift_control_av", "Drift-Control AV · schedule-matched mask"],
            ["color_stable_drift_av", "Color-Stable Drift AV · tapered scene-one latent delta"],
            ["masked_av", "Masked AV · same shot"],
            ["feathered_av", "Feathered AV · experimental dual-stream feather"],
            ["audio_feathered_av", "Audio Feather AV · hard picture, soft sound"],
        ]) {
            const option = element("option", "", label);
            option.value = value;
            continuation.append(option);
        }
        continuation.value = Object.hasOwn(shot, "continuation_mode")
            ? sceneContinuationMode(shot, settings().continuationMode) : "";
        continuation.title = state.active === 0
            ? "Continuation into this scene. Scene 1 uses it only with Existing Video Context. Guide re-encodes RGB; Latent Guide reuses generated latent context and falls back to RGB for imported context; Detail Guide adds luma-preserving tapered chroma injection; Detail AV applies a disposable video-only latent taper; Drift-Control AV applies a scheduler-matched video mask with a clean seam and needs the Chain Context MODEL path; Color-Stable Drift AV additionally carries a weak scene-one color correction as a tapered VAE delta on the copied video latent only."
            : "Guide re-encodes RGB into persistent conditioning; Latent Guide directly conditions on the saved sampled-latent tail; Detail Guide applies luma-preserving tapered chroma injection; Detail AV applies a disposable video-only latent taper; Drift-Control AV applies a scheduler-matched video mask with a clean seam and needs the Chain Context MODEL path; Color-Stable Drift AV additionally carries a weak scene-one color correction as a tapered VAE delta on the copied video latent only; Masked AV preserves an exact prefix; experimental Feathered AV softens both streams; Audio-Feathered AV keeps the picture exact and softens only the final audio ticks.";
        continuation.addEventListener("change", () => {
            if (continuation.value) shot.continuation_mode = continuation.value;
            else delete shot.continuation_mode;
            sceneContinuationMode(shot, settings().continuationMode);
            refreshIncomingTransition();
            writePlan();
            renderStatus();
        });
        const spatialProxy = element("select");
        for (const [value, label] of [
            ["", "Off · native context"],
            ["rgb_5_6", "Low-grid 5/6 proxy · Guide"],
            ["latent_5_6", "Latent 5/6 proxy · AV"],
        ]) {
            const option = element("option", "", label);
            option.value = value;
            spatialProxy.append(option);
        }
        spatialProxy.value = shot.context_spatial_proxy ?? "";
        spatialProxy.title = "Scheduled only on incoming boundaries for scenes 2+. Low-grid 5/6 reduces the full saved predecessor video latent to the proxy grid, VAE-decodes it there, and lets Motion Context restore the selected Guide tail; 1376×768 uses 1152×640 (48×86 → 40×72 latent). This exact low-grid decode costs extra preparation time and peak memory. Latent 5/6 is the cheaper copied-prefix latent filter for AV. Audio, outputs, checkpoints, and assembly stay native size.";
        spatialProxy.addEventListener("change", () => {
            if (spatialProxy.value) shot.context_spatial_proxy = spatialProxy.value;
            else delete shot.context_spatial_proxy;
            writePlan();
            renderStatus();
        });
        const form = element("div", "h3studio-form");
        form.append(
            field("Scene ID", id), field("Length", lengthControl),
            field("Steps", steps),
            field("Prompt alternatives", promptSeedWrap),
            field("Seed", seedWrap),
            field("LoRA route", loraRoute),
            field("Incoming transition", incomingTransition),
            field("Final assembly crossfade frames", blendFrames),
        );
        const planAudioPolicy = settings().audioPolicy;
        const effectiveAudioPolicy = sceneAudioPolicy(shot, planAudioPolicy);
        function audioOverrideSelect(key, inherited, choices, title) {
            const select = element("select");
            const inheritedOption = element(
                "option", "", `Inherit Chain Policy · ${inherited}`,
            );
            inheritedOption.value = "inherit";
            select.append(inheritedOption);
            for (const [value, label] of choices) {
                const option = element("option", "", label);
                option.value = value;
                select.append(option);
            }
            select.value = sceneAudioOverride(shot, key);
            select.title = title;
            select.addEventListener("change", () => {
                applySceneAudioOverride(shot, key, select.value);
                writePlan();
                renderStatus();
            });
            return select;
        }
        const sourceReference = audioOverrideSelect(
            "source_reference",
            planAudioPolicy.sourceReference ?? effectiveAudioPolicy.sourceReference,
            [["on", "On · source window as Ref2VA audio"],
             ["off", "Off · no source audio reference"]],
            "Scene-local source-audio reference. It does not choose final "
                + "soundtrack; Lock source audio wins over this switch.",
        );
        const generatedContinuity = audioOverrideSelect(
            "generated_continuity",
            planAudioPolicy.generatedContinuity
                ?? effectiveAudioPolicy.generatedContinuity,
            [["on", "On · continue prior generated audio"],
             ["off", "Off · independent generated audio"]],
            "Scene-local predecessor generated-audio carry. Lock source audio "
                + "wins over this switch.",
        );
        const inheritedLock = (planAudioPolicy.sourceAudioTarget ?? "off")
            === "locked" ? "on" : "off";
        const lockSourceAudio = audioOverrideSelect(
            "source_audio_target", inheritedLock,
            [["locked", "On · protect exact source window"],
             ["off", "Off · target remains denoisable"]],
            "Locks this scene's exact source waveform into the target audio "
                + "latent. Source reference and generated continuity become "
                + "effectively off; final soundtrack stays global.",
        );
        const audioOverrides = element("div", "h3studio-audio-overrides");
        audioOverrides.append(
            field("Source reference", sourceReference),
            field("Generated continuity", generatedContinuity),
            field("Lock source audio", lockSourceAudio),
        );
        const advanced = element("details", "h3studio-advanced");
        advanced.open = state.advancedBoundaryOpen;
        advanced.addEventListener("toggle", () => {
            state.advancedBoundaryOpen = advanced.open;
            node.properties[ADVANCED_BOUNDARY_OPEN_PROPERTY] = advanced.open;
            dirty();
        });
        advanced.append(element(
            "summary", "", "Advanced boundary controls",
        ));
        const advancedGrid = element("div", "h3studio-advanced-grid");
        advancedGrid.append(
            field("Visual / audio context", contextPair),
            field("Visual context source", visualSource),
            field("Composed context first source", visualLeadSource),
            field("Composed total / split", visualLeadFrames),
            field("Implementation", continuation),
            field("Boundary spatial proxy", spatialProxy),
        );
        advanced.append(advancedGrid);

        if (state.promptEditors.length) {
            const delegated = element("div", "h3studio-prompt-delegated");
            delegated.append(
                element("strong", "", `Prompt editing delegated to ${promptEditorLabel()}`),
                document.createTextNode(
                    "Use the linked editor for prompt text and revision history. " +
                    "Scene selection is synchronized in both directions; Studio keeps scene ID, length, steps, seed, timeline, and playback controls.",
                ),
            );
            panel.append(head, form, audioOverrides, advanced, delegated);
            return panel;
        }

        const prompt = element("textarea", "h3studio-prompt");
        prompt.value = promptValueToText(shot.prompt, `Scene ${state.active + 1} prompt`);
        prompt.placeholder = "Write this scene's action, camera, performance, dialogue, sound, and ending continuity…";
        prompt.spellcheck = true;
        const message = element("span", "h3studio-message", "Synchronized with Plan");
        prompt.addEventListener("input", () => {
            shot.prompt = promptTextToLines(prompt.value); writePlan(message);
            scheduleHistoryDraft(row.id, prompt.value);
        });
        prompt.addEventListener("keydown", (event) => {
            if (event.altKey && event.key === "ArrowLeft") { event.preventDefault(); void selectScene(state.active - 1); }
            else if (event.altKey && event.key === "ArrowRight") { event.preventDefault(); void selectScene(state.active + 1); }
            else if (!event.ctrlKey && !event.metaKey && !event.altKey && event.key === "#") { event.preventDefault(); insertDialogue(prompt); }
        });
        const tools = element("div", "h3studio-prompt-tools");
        const tray = element("div", "h3studio-refs");
        tools.append(
            button("@ Reference", "Show connected reference tags and previews", () => {
                const opening = !tray.classList.contains("h3studio-open");
                if (opening) renderReferenceTray(tray, prompt); tray.classList.toggle("h3studio-open", opening);
            }),
            button("# Dialogue", "Wrap the selected text in <d> dialogue tags", () => insertDialogue(prompt)),
            element("span", "h3studio-hint", "Alt+←/→ scenes"), message,
        );
        const history = element("div", "h3studio-history");
        state.history.host = history; state.history.textarea = prompt; state.history.status = message;
        panel.append(
            head, form, audioOverrides, advanced, prompt, tools, tray, history,
        );
        void loadHistory(row.id, prompt.value);
        return panel;
    }

    function renderChapterPanel() {
        const chapter = orderedChapters(state.plan).find(
            (candidate) => candidate.id === state.activeChapterId,
        );
        if (!chapter) {
            state.activeChapterId = "";
            return renderScenePanel();
        }
        const chapterIndex = state.plan.shots.findIndex((shot, offset) => (
            safeShotId(shot?.id, `clip_${String(offset + 1).padStart(4, "0")}`)
                === chapter.start_scene_id
        ));
        const panel = element("div");
        const head = element("div", "h3studio-scene-head");
        head.append(
            element("strong", "", chapter.title),
            element(
                "span", "h3studio-scene-label",
                `starts before scene ${chapterIndex + 1} · zero-duration editorial note`,
            ),
        );
        const title = element("input");
        title.value = chapter.title;
        title.maxLength = 160;
        title.addEventListener("input", () => {
            chapter.title = title.value.slice(0, 160) || "Untitled chapter";
            writePlan(); renderTimeline();
        });
        const boundary = element("select");
        state.plan.shots.forEach((shot, index) => {
            const sceneId = safeShotId(
                shot?.id, `clip_${String(index + 1).padStart(4, "0")}`,
            );
            const option = element("option", "", `Before scene ${index + 1} · ${sceneId}`);
            option.value = sceneId;
            boundary.append(option);
        });
        boundary.value = chapter.start_scene_id;
        boundary.addEventListener("change", () => {
            const occupied = (state.plan.chapters ?? []).some(
                (candidate) => candidate !== chapter
                    && candidate.start_scene_id === boundary.value,
            );
            if (occupied) {
                boundary.value = chapter.start_scene_id;
                return;
            }
            chapter.start_scene_id = boundary.value;
            writePlan(); renderTimeline();
        });
        const form = element("div", "h3studio-defaults");
        form.append(field("Chapter title", title), field("Timeline marker", boundary));
        const textarea = element("textarea", "h3studio-prompt");
        textarea.value = chapter.text ?? "";
        textarea.placeholder = "Editorial context, lyrics, LLM notes, story intent…";
        textarea.spellcheck = true;
        textarea.addEventListener("input", () => {
            chapter.text = textarea.value;
            writePlan();
        });
        const actions = element("div", "h3studio-prompt-tools");
        actions.append(
            element(
                "span", "h3studio-hint",
                "Notes organize the editor and Checkpoint Manager only. They do not affect playback, generation, resume checks, or branch identity.",
            ),
            button("Delete chapter", "Remove this editorial marker and its notes", () => {
                if (!confirm(`Delete ${chapter.title}?`)) return;
                state.plan.chapters = (state.plan.chapters ?? []).filter(
                    (candidate) => candidate.id !== chapter.id,
                );
                if (!state.plan.chapters.length) delete state.plan.chapters;
                state.activeChapterId = "";
                writePlan(); renderShell();
            }),
        );
        panel.append(head, form, textarea, actions);
        return panel;
    }

    function renderSharedPanel() {
        const panel = element("div");
        panel.append(element("div", "h3studio-scene-head", "Shared prompt — prepended to every scene"));
        const textarea = element("textarea", "h3studio-shared");
        textarea.value = sharedPrompt(state.plan).text;
        textarea.placeholder = "Identity, wardrobe, style, reference definitions, audio rules, and global continuity…";
        textarea.addEventListener("input", () => { setSharedPrompt(state.plan, textarea.value); writePlan(); });
        panel.append(textarea);
        return panel;
    }

    function renderPlanSettingsPanel() {
        const panel = element("div");
        const grid = element("div", "h3studio-plan-settings");
        const owner = state.planOwner ?? node;
        const transition = resolveTransitionPolicy(owner);
        const audioPolicy = resolveAudioPolicy(owner);
        const projectAssetsManaged = inputConnected(owner, "project_assets");
        const value = (name, fallback = "") => widget(owner, name)?.value ?? fallback;
        const section = (title) => element(
            "div", "h3studio-plan-settings-section", title,
        );
        const textControl = (name, fallback = "", placeholder = "") => {
            const control = element("input");
            control.type = "text";
            control.value = String(value(name, fallback));
            control.placeholder = placeholder;
            control.addEventListener("change", () => {
                writePlanSetting(name, control.value.trim());
            });
            return control;
        };
        const numberControl = (
            name, fallback, minimum, maximum, step = 1, integer = true,
        ) => {
            const control = element("input");
            control.type = "number";
            control.min = String(minimum); control.max = String(maximum);
            control.step = String(step); control.value = String(value(name, fallback));
            control.addEventListener("change", () => {
                let parsed = Number(control.value);
                if (!Number.isFinite(parsed)) parsed = Number(fallback);
                parsed = Math.max(Number(minimum), Math.min(Number(maximum), parsed));
                if (integer) parsed = Math.trunc(parsed);
                writePlanSetting(name, parsed);
            });
            return control;
        };
        const selectControl = (name, options, fallback, transform = (item) => item) => {
            const control = element("select");
            for (const [optionValue, label] of options) {
                const option = element("option", "", label);
                option.value = optionValue; control.append(option);
            }
            control.value = String(value(name, fallback));
            control.addEventListener("change", () => {
                writePlanSetting(name, transform(control.value));
            });
            return control;
        };
        const baseSeed = element("input");
        baseSeed.type = "text"; baseSeed.inputMode = "numeric";
        baseSeed.value = String(value("base_seed", 0));
        baseSeed.title = `Unsigned 64-bit seed (0–${MAX_SEED.toString()})`;
        baseSeed.addEventListener("change", () => {
            try {
                const parsed = BigInt(baseSeed.value.trim() || "0");
                if (parsed < 0n || parsed > MAX_SEED) throw new Error();
                writePlanSetting("base_seed", parsed.toString());
            } catch (_error) {
                baseSeed.setCustomValidity("Base seed must be an unsigned 64-bit integer.");
                baseSeed.reportValidity();
                baseSeed.setCustomValidity("");
            }
        });

        const mode = state.planNode
            ? "Connected mode · changes are written to the H3 Chain Plan and mirrored into Studio. Disconnecting keeps this synchronized snapshot."
            : "Standalone mode · this node owns, validates, and outputs the complete H3 Chain Plan.";
        const identityFields = projectAssetsManaged ? [
            element(
                "div", "h3studio-plan-defaults-help",
                "Run name and reference-derived generation fingerprint are managed by connected Project Assets. Their stored widget values are preserved; disconnect Project Assets to edit them.",
            ),
        ] : [
            field("Run name", textControl("run_name", "h3_chain", "h3_chain")),
            field("Generation fingerprint", textControl(
                "generation_fingerprint", "", "optional compatibility tag",
            )),
        ];
        grid.append(
            element("div", "h3studio-plan-defaults-help", mode),
            section("Run identity and canvas"),
            ...identityFields,
            field("Base seed", baseSeed),
            field("Width", numberControl("width", 960, 32, 4096, 32)),
            field("Height", numberControl("height", 544, 32, 4096, 32)),
            field("Segment CRF", numberControl("segment_crf", 18, 0, 51)),
            section("Plan-wide scene defaults"),
            field("Default seconds", numberControl(
                "default_duration_seconds", 15, .1, MAX_H3_FRAMES / FPS, .01, false,
            )),
            field("Default steps", numberControl("default_steps", 20, 1, 10000)),
            field("Default blend frames", numberControl(
                "video_blend_frames", 0, 0, 243,
            )),
            field("Context encoding", selectControl("encode_mode", [
                ["video", "Video clip"], ["frames", "Separate frames"],
            ], "video")),
            field("Anchor placement", selectControl("anchor_mode", [
                ["head", "Head (tested)"], ["before", "Before timeline (experimental)"],
            ], "head")),
            field("Context fit", selectControl("crop", [
                ["disabled", "Resize directly"], ["center", "Preserve aspect + center crop"],
            ], "disabled")),
            section("Legacy policy fallback"),
        );
        const context = selectControl(
            "context_length", H3_CONTEXT_LENGTHS.map((item) => [String(item), `${item} frames`]), "22",
            (item) => Number(item),
        );
        const continuation = selectControl(
            "continuation_mode", CONTINUATION_MODES.map((item) => [item, item]), "guide",
        );
        const audioMode = selectControl("audio_mode", [
            ["generated_audio", "Generated audio"],
            ["source_track", "Source track"],
            ["source_plus_timeline", "Source + generated continuity"],
        ], "generated_audio");
        const audioContext = numberControl("audio_context_length", 22, 0, 240);
        context.disabled = transition.known;
        continuation.disabled = transition.known;
        audioMode.disabled = audioPolicy.known;
        audioContext.disabled = audioPolicy.known;
        grid.append(
            field("Visual context", context),
            field("Continuation implementation", continuation),
            field("Audio mode", audioMode),
            field("Audio context", audioContext),
            element("div", "h3studio-plan-defaults-help",
                transition.known || audioPolicy.known
                    ? "Connected Chain Policy owns the disabled fallback controls. The active policy is used for timing and execution."
                    : "These controls are used only when no Chain Policy is connected. Per-scene Advanced settings can still override them."),
        );
        panel.append(grid);
        return panel;
    }

    function playerCheckpoint(index) {
        const item = matchingStudioCheckpoint(
            state.checkpoints, index, timing().shots[index],
        );
        if (!item) return null;
        return {
            video:item.preview_video ?? item.video,
            // Review previews already contain synchronized audio. Raw saved
            // segments do not, so pair those with their delivered WAV.
            audio:item.preview_video ? null : (item.audio ?? null),
        };
    }

    function renderContextPanel() {
        const panel = element("div", "h3studio-context-selector");
        const result = timing();
        const row = result.shots[state.active];
        const shot = state.plan.shots[state.active];
        const title = element(
            "div", "h3studio-scene-head",
            `Scene ${state.active + 1} selected visual context`,
        );
        panel.append(title);
        if (!row || state.active === 0) {
            panel.append(element(
                "div", "h3studio-context-empty",
                "Scene 1 has no saved predecessor. Existing Video Context remains configured by its dedicated workflow input.",
            ));
            return panel;
        }
        if (!Number(row.contextLength)) {
            panel.append(element(
                "div", "h3studio-context-empty",
                "This scene has 0 visual context. Choose a positive context in Scene settings before selecting a source segment.",
            ));
            return panel;
        }
        panel.append(element(
            "div", "h3studio-context-help",
            "Drag the fixed-width zone between native H3 latent positions. The selector advances on the 17-frame / 5-latent-step lattice and crops saved latent steps directly; it never re-encodes an arbitrary RGB window. Latest aligned is the default. Generated-audio continuity still follows the immediate previous scene.",
        ));
        const blocksHost = element("div", "h3studio-context-blocks");
        const blocks = [];
        if (row.visualContextLeadSource !== null) {
            blocks.push({
                label:"Block 1 · first in composed context",
                sourceIndex:row.visualContextLeadSource - 1,
                span:Number(row.visualContextLeadFrames),
                field:"visual_context_lead_start_frame",
                lead:true,
                prefixFrames:0,
            });
        }
        blocks.push({
            label:row.visualContextLeadSource === null
                ? "Context block" : "Block 2 · nearest generation",
            sourceIndex:row.visualContextSource - 1,
            span:Number(row.contextLength - row.visualContextLeadFrames),
            field:"visual_context_start_frame",
            lead:false,
            prefixFrames:Number(row.visualContextLeadFrames),
        });

        for (const block of blocks) {
            const sourceRow = result.shots[block.sourceIndex];
            const card = element("div", "h3studio-context-block");
            const head = element("div", "h3studio-context-block-head");
            head.append(
                element("strong", "", `${block.label} · ${block.span}f`),
                element(
                    "span", "",
                    sourceRow
                        ? `Scene ${sourceRow.index} · ${sourceRow.id}`
                        : "Missing source scene",
                ),
            );
            card.append(head);
            if (!sourceRow || !Number.isInteger(block.span) || block.span < 1) {
                card.append(element(
                    "div", "h3studio-context-empty",
                    "The selected source or context split is invalid. Fix it in Scene settings.",
                ));
                blocksHost.append(card);
                continue;
            }
            const latest = Math.max(0, sourceRow.deliveredFrames - block.span);
            const validStarts = nativeContextWindowStarts(
                sourceRow.rawFrames, sourceRow.deliveredFrames, block.span,
                block.prefixFrames,
            );
            if (!validStarts.length) {
                card.append(element(
                    "div", "h3studio-context-empty",
                    "This block has no native latent-aligned position in the selected source scene.",
                ));
                blocksHost.append(card);
                continue;
            }
            const defaultStart = validStarts.at(-1);
            let start = defaultStart;
            let rangeError = "";
            try {
                start = sceneVisualContextStartFrame(
                    shot, sourceRow.rawFrames, sourceRow.deliveredFrames,
                    block.span, block.lead, block.prefixFrames,
                );
            } catch (error) {
                rangeError = error?.message || String(error);
                const raw = Number(shot[block.field]);
                start = nearestNativeContextWindowStart(
                    validStarts, Number.isInteger(raw) ? raw : defaultStart,
                );
            }
            const media = playerCheckpoint(block.sourceIndex);
            let video = null;
            if (media?.video) {
                video = element("video", "h3studio-context-video");
                video.controls = true;
                video.playsInline = true;
                video.preload = "metadata";
                video.muted = true;
                video.src = videoUrl(media.video);
                state.contextPlayers.push(video);
                card.append(video);
            } else {
                card.append(element(
                    "div", "h3studio-context-empty",
                    `Scene ${sourceRow.index} has no active saved video yet. The frame window can still be planned now.`,
                ));
            }
            const rangeWrap = element("div", "h3studio-context-range");
            const movieTrack = element("div", "h3studio-context-movie-track");
            movieTrack.tabIndex = 0;
            movieTrack.setAttribute("role", "slider");
            movieTrack.setAttribute("aria-label", `${block.label} position in source movie`);
            movieTrack.setAttribute("aria-valuemin", "0");
            movieTrack.setAttribute("aria-valuemax", String(latest));
            movieTrack.title = `Drag the fixed ${block.span}-frame context zone across ${validStarts.length} native latent-aligned positions`;
            const selectedZone = element(
                "div", "h3studio-context-window", `${block.span}f`,
            );
            const playhead = element("div", "h3studio-context-playhead");
            movieTrack.append(selectedZone, playhead);
            const rangeLabel = element("span", "h3studio-context-range-label");
            const movieLength = element(
                "span", "h3studio-context-movie-length",
                `source movie · ${sourceRow.deliveredFrames}f · ${(sourceRow.deliveredFrames / FPS).toFixed(3)}s`,
            );
            const error = element("div", "h3studio-error", rangeError);
            error.hidden = !rangeError;
            let selectedStart = start;
            const updateSelection = () => {
                const layout = studioContextWindowLayout(
                    sourceRow.deliveredFrames, block.span, selectedStart,
                );
                selectedStart = layout.start;
                selectedZone.style.left = `${layout.leftFraction * 100}%`;
                selectedZone.style.width = `${layout.widthFraction * 100}%`;
                selectedZone.title = `${block.span} context frames · ${layout.start + 1}–${layout.end} · native latent crop`;
                const slot = validStarts.indexOf(layout.start) + 1;
                rangeLabel.textContent = `aligned ${slot}/${validStarts.length} · frames ${layout.start + 1}–${layout.end} · ${(layout.start / FPS).toFixed(3)}–${(layout.end / FPS).toFixed(3)}s`;
                movieTrack.setAttribute("aria-valuenow", String(layout.start));
                movieTrack.setAttribute(
                    "aria-valuetext", `frames ${layout.start + 1} through ${layout.end}`,
                );
            };
            const previewStart = () => {
                if (!video || video.readyState < 1) return;
                try { video.currentTime = selectedStart / FPS; }
                catch (_error) {}
            };
            const commitStart = () => {
                if (selectedStart === defaultStart) delete shot[block.field];
                else {
                    shot[block.field] = selectedStart;
                    shot.video_blend_frames = 0;
                }
                error.hidden = true;
                error.textContent = "";
                writePlan();
                renderStatus();
            };
            const selectStart = (value, {seek = true, commit = false} = {}) => {
                selectedStart = nearestNativeContextWindowStart(
                    validStarts, Math.max(0, Math.min(latest, Math.round(value))),
                );
                updateSelection();
                if (seek) previewStart();
                if (commit) commitStart();
            };
            let drag = null;
            movieTrack.addEventListener("pointerdown", (event) => {
                if (event.button !== 0) return;
                event.preventDefault();
                const bounds = movieTrack.getBoundingClientRect();
                if (event.target !== selectedZone) {
                    selectStart(studioContextWindowStartAtRatio(
                        sourceRow.deliveredFrames,
                        block.span,
                        (event.clientX - bounds.left) / Math.max(1, bounds.width),
                    ));
                }
                drag = {
                    id:event.pointerId,
                    x:event.clientX,
                    start:selectedStart,
                    width:Math.max(1, bounds.width),
                };
                movieTrack.classList.add("h3studio-dragging");
                movieTrack.setPointerCapture(event.pointerId);
            });
            movieTrack.addEventListener("pointermove", (event) => {
                if (!drag || drag.id !== event.pointerId) return;
                const frameDelta = (
                    (event.clientX - drag.x) / drag.width
                ) * sourceRow.deliveredFrames;
                selectStart(drag.start + frameDelta);
            });
            const finishDrag = (event) => {
                if (!drag || drag.id !== event.pointerId) return;
                drag = null;
                movieTrack.classList.remove("h3studio-dragging");
                try { movieTrack.releasePointerCapture(event.pointerId); }
                catch (_error) {}
                commitStart();
            };
            movieTrack.addEventListener("pointerup", finishDrag);
            movieTrack.addEventListener("pointercancel", finishDrag);
            movieTrack.addEventListener("keydown", (event) => {
                let next = null;
                const currentSlot = Math.max(0, validStarts.indexOf(selectedStart));
                const step = event.shiftKey ? 5 : 1;
                if (event.key === "ArrowLeft") {
                    next = validStarts[Math.max(0, currentSlot - step)];
                } else if (event.key === "ArrowRight") {
                    next = validStarts[Math.min(validStarts.length - 1, currentSlot + step)];
                } else if (event.key === "PageUp") {
                    next = validStarts[Math.max(0, currentSlot - 5)];
                } else if (event.key === "PageDown") {
                    next = validStarts[Math.min(validStarts.length - 1, currentSlot + 5)];
                } else if (event.key === "Home") next = validStarts[0];
                else if (event.key === "End") next = defaultStart;
                if (next === null) return;
                event.preventDefault();
                selectStart(next, {commit:true});
            });
            const rangeReadout = element("div", "h3studio-context-range-readout");
            rangeReadout.append(movieLength, rangeLabel);
            rangeWrap.append(movieTrack, rangeReadout);
            card.append(rangeWrap);
            updateSelection();
            if (video) {
                video.addEventListener("loadedmetadata", previewStart, {once:true});
            }
            const actions = element("div", "h3studio-context-actions");
            const usePlayhead = button(
                "Start at playhead",
                "Set the context window's first frame from this player's current position",
                () => {
                    if (!video) return;
                    selectStart(video.currentTime * FPS, {commit:true});
                },
            );
            usePlayhead.disabled = !video;
            const playSelection = button(
                "Play selection",
                "Play only this context window",
                async () => {
                    if (!video) return;
                    for (const item of state.contextPlayers) {
                        if (item !== video) item.pause();
                    }
                    const endSeconds = (
                        selectedStart + block.span
                    ) / FPS;
                    video.dataset.contextEnd = String(endSeconds);
                    video.currentTime = selectedStart / FPS;
                    try { await video.play(); } catch (_error) {}
                },
            );
            playSelection.disabled = !video;
            if (video) {
                video.addEventListener("timeupdate", () => {
                    playhead.style.left = `${Math.max(0, Math.min(
                        1, video.currentTime * FPS / sourceRow.deliveredFrames,
                    )) * 100}%`;
                    const end = Number(video.dataset.contextEnd);
                    if (Number.isFinite(end) && video.currentTime >= end) {
                        delete video.dataset.contextEnd;
                        video.pause();
                        video.currentTime = end;
                    }
                });
            }
            const tail = button(
                defaultStart === latest ? "Tail (default)" : "Latest aligned (default)",
                "Use the latest native latent-aligned crop and remove the stored override",
                () => {
                    selectStart(defaultStart, {commit:true});
                },
            );
            actions.append(usePlayhead, playSelection, tail);
            card.append(actions, error);
            blocksHost.append(card);
        }
        panel.append(blocksHost);
        return panel;
    }

    function disposePlayer() {
        const current = state.player;
        const generatedAudio = state.playerAudio;
        const sourceAudioCurrent = state.sourceAudioPlayer;
        const sourceCurrent = state.sourcePlayer;
        const preloadVideo = state.playerPreloadVideo;
        const preloadAudio = state.playerPreloadAudio;
        state.player = null;
        state.playerAudio = null;
        state.sourceAudioPlayer = null;
        state.sourcePlayer = null;
        state.sourceLayer = null;
        const contextPlayers = state.contextPlayers;
        state.contextPlayers = [];
        state.playerSlider = null;
        state.playerPreloadVideo = null;
        state.playerPreloadAudio = null;
        state.primePlayerNext = null;
        state.playPlayerTransport = null;
        state.togglePlayerPlayback = null;
        for (const media of [
            current, generatedAudio, sourceAudioCurrent, sourceCurrent,
            preloadVideo, preloadAudio, ...contextPlayers,
        ]) {
            if (!media) continue;
            try { media.pause(); } catch (_error) {}
            media.removeAttribute("src");
            delete media.dataset.source;
            try { media.load(); } catch (_error) {}
        }
    }

    function seekTimeline(seconds, autoplay = false) {
        const result = timing();
        const location = locateStudioTimelineSecond(result.shots, seconds);
        if (location.index < 0) return;
        const {index, localSeconds, targetSeconds:target} = location;
        const generatedMedia = playerCheckpoint(index);
        const generated = generatedMedia?.video;
        const reference = sourceReference(index);
        const source = sourcePreviewUrl(index, reference);
        state.playerIndex = index; state.pendingSeek = localSeconds;
        state.timelinePosition = target;
        if (state.active !== index) {
            state.active = index; persistView(); renderSourceTimeline();
            renderSourceAudioTimeline();
            updateTimelineSelection();
            revealActiveTimelineScene();
            publishActiveScene();
        }
        if (state.playerSlider) state.playerSlider.value = String(target);
        if (state.playhead) state.playhead.style.left = `${result.totalSeconds ? target / result.totalSeconds * 100 : 0}%`;
        if (!state.player) return;
        if (!generated) {
            delete state.player.dataset.source;
            state.player.removeAttribute("src"); state.player.load();
            if (state.playerAudio) {
                try { state.playerAudio.pause(); } catch (_error) {}
                delete state.playerAudio.dataset.source;
                state.playerAudio.removeAttribute("src");
                state.playerAudio.load();
            }
        } else {
            const url = videoUrl(generated);
            const targetPlayer = state.player;
            const targetAudio = state.playerAudio;
            const requestedSeek = state.pendingSeek;
            const audioUrl = generatedMedia?.audio ? videoUrl(generatedMedia.audio) : "";
            if (targetAudio && targetAudio.dataset.source !== audioUrl) {
                try { targetAudio.pause(); } catch (_error) {}
                if (audioUrl) {
                    targetAudio.dataset.source = audioUrl;
                    targetAudio.src = audioUrl;
                } else {
                    delete targetAudio.dataset.source;
                    targetAudio.removeAttribute("src");
                }
                targetAudio.load();
            }
            const seekGeneratedAudio = () => {
                if (!targetAudio?.dataset.source) return;
                const duration = Number.isFinite(targetAudio.duration)
                    ? targetAudio.duration : requestedSeek;
                try { targetAudio.currentTime = Math.min(
                    requestedSeek, Math.max(0, duration - .02),
                ); } catch (_error) {}
            };
            const applySeek = () => {
                if (state.player !== targetPlayer || !targetPlayer?.isConnected) return;
                const duration = Number.isFinite(targetPlayer.duration) ? targetPlayer.duration : requestedSeek;
                try { targetPlayer.currentTime = Math.min(requestedSeek, Math.max(0, duration - .02)); }
                catch (_error) {}
                seekGeneratedAudio();
                if (autoplay) void targetPlayer.play().catch(() => {});
            };
            if (targetAudio?.dataset.source) {
                targetAudio.addEventListener(
                    "loadedmetadata", seekGeneratedAudio, {once:true},
                );
            }
            if (targetPlayer.dataset.source !== url) {
                targetPlayer.dataset.source = url; targetPlayer.src = url; targetPlayer.load();
                targetPlayer.addEventListener("loadedmetadata", applySeek, {once:true});
            } else applySeek();
        }
        if (state.sourcePlayer) {
            const targetSource = state.sourcePlayer;
            const requestedSourceSeek = studioSourceSecond(reference, localSeconds);
            const applySourceSeek = () => {
                if (state.sourcePlayer !== targetSource || !targetSource?.isConnected) return;
                try { targetSource.currentTime = requestedSourceSeek; }
                catch (_error) {}
            };
            if (!source) {
                delete targetSource.dataset.source;
                targetSource.removeAttribute("src"); targetSource.load();
            } else if (targetSource.dataset.source !== source) {
                targetSource.dataset.source = source; targetSource.src = source; targetSource.load();
                targetSource.addEventListener("loadedmetadata", applySourceSeek, {once:true});
            } else applySourceSeek();
        }
        if (state.sourceAudioPlayer) {
            const targetSourceAudio = state.sourceAudioPlayer;
            const timelineAudio = sourceAudio();
            const timelineAudioUrl = timelineAudio ? sourceAudioUrl() : "";
            const requestedAudioSeek = timelineAudio
                ? studioSourceAudioSecond(timelineAudio, target) : 0;
            const applySourceAudioSeek = () => {
                if (state.sourceAudioPlayer !== targetSourceAudio ||
                        !targetSourceAudio?.isConnected) return;
                if (Math.abs((Number(targetSourceAudio.currentTime) || 0) -
                        requestedAudioSeek) > .12) {
                    try { targetSourceAudio.currentTime = requestedAudioSeek; }
                    catch (_error) {}
                }
            };
            if (!timelineAudioUrl) {
                targetSourceAudio.pause();
                delete targetSourceAudio.dataset.source;
                targetSourceAudio.removeAttribute("src");
                targetSourceAudio.load();
            } else if (targetSourceAudio.dataset.source !== timelineAudioUrl) {
                targetSourceAudio.dataset.source = timelineAudioUrl;
                targetSourceAudio.src = timelineAudioUrl;
                targetSourceAudio.load();
                targetSourceAudio.addEventListener(
                    "loadedmetadata", applySourceAudioSeek, {once:true},
                );
            } else applySourceAudioSeek();
        }
        const label = root.querySelector(".h3studio-player-label");
        if (label) label.textContent = generated
            ? `Scene ${index + 1} · ${timing().shots[index].id}${reference ? ` ↔ @${reference.tag}` : ""}`
            : `Scene ${index + 1} has no saved segment${sourceAudio() ? " · Source track is ready" : ""}${reference ? ` · @${reference.tag} is ready` : ""}.`;
        const motionAudioToggle = root.querySelector(".h3studio-audio-motion");
        if (motionAudioToggle) {
            motionAudioToggle.disabled = !reference?.has_audio;
            if (!reference?.has_audio) motionAudioToggle.checked = false;
            const wrapper = motionAudioToggle.closest(
                ".h3studio-audio-control");
            if (wrapper) wrapper.hidden = !reference?.has_audio;
        }
        const timelineAudioToggle = root.querySelector(".h3studio-audio-source");
        const timelineAudioAvailable = Boolean(sourceAudio());
        if (timelineAudioToggle) {
            const wasAvailable = timelineAudioToggle.dataset.available === "true";
            timelineAudioToggle.disabled = !timelineAudioAvailable;
            if (timelineAudioAvailable && !wasAvailable) {
                timelineAudioToggle.checked = true;
            } else if (!timelineAudioAvailable) {
                timelineAudioToggle.checked = false;
            }
            timelineAudioToggle.dataset.available = String(timelineAudioAvailable);
            const audioControl = timelineAudioToggle.closest(
                ".h3studio-audio-control");
            const volume = audioControl?.querySelector(
                ".h3studio-audio-volume");
            if (volume) volume.disabled = !timelineAudioAvailable;
            const text = timelineAudioToggle.closest("label")?.querySelector("span");
            if (text) text.textContent = sourceAudioMuted(index)
                ? "Source track (scene muted)" : "Source track";
        }
        const hasMotion = Boolean(reference);
        if (state.sourceLayer) state.sourceLayer.hidden = !hasMotion;
        const compareControls = root.querySelector(".h3studio-compare-controls");
        compareControls?.classList.toggle("h3studio-no-motion", !hasMotion);
        for (const item of root.querySelectorAll(
            ".h3studio-wipe-label,.h3studio-wipe-control,.h3studio-wipe-line,.h3studio-compare-label",
        )) item.hidden = !hasMotion;
        root.querySelector(".h3studio-audio-generated")?.dispatchEvent(
            new Event("change"),
        );
        state.primePlayerNext?.(index + 1);
        if (autoplay && !generated) state.playPlayerTransport?.();
    }

    function renderPlayerPanel() {
        const wrapper = element("div", "h3studio-player");
        const label = element("div", "h3studio-player-label", "Generated playback");
        const stage = element("div", "h3studio-compare-stage");
        const video = element("video"); video.playsInline = true; video.preload = "metadata";
        const handoffFrame = element("canvas", "h3studio-handoff-frame");
        handoffFrame.hidden = true;
        const generatedAudio = element("audio");
        generatedAudio.preload = "metadata"; generatedAudio.hidden = true;
        const sourceTimelineAudio = element("audio");
        sourceTimelineAudio.preload = "metadata"; sourceTimelineAudio.hidden = true;
        const sourceVideo = element("video"); sourceVideo.playsInline = true;
        sourceVideo.preload = "metadata"; sourceVideo.muted = true;
        const sourceLayer = element("div", "h3studio-source-layer");
        sourceLayer.style.clipPath = "inset(0 50% 0 0)";
        sourceLayer.hidden = true;
        const wipeLine = element("span", "h3studio-wipe-line"); wipeLine.style.left = "50%";
        const sourceLabel = element(
            "span", "h3studio-compare-label h3studio-compare-label-source",
            "MOTION REF",
        );
        const generatedLabel = element(
            "span", "h3studio-compare-label h3studio-compare-label-generated",
            "GENERATED",
        );
        wipeLine.hidden = true; sourceLabel.hidden = true;
        generatedLabel.hidden = true;
        sourceLayer.append(sourceVideo);
        stage.append(
            video, handoffFrame, sourceLayer, wipeLine, sourceLabel,
            generatedLabel,
        );
        const preloadVideo = element("video");
        preloadVideo.preload = "auto"; preloadVideo.muted = true;
        preloadVideo.playsInline = true; preloadVideo.hidden = true;
        const preloadAudio = element("audio");
        preloadAudio.preload = "auto"; preloadAudio.muted = true;
        preloadAudio.hidden = true;
        const clearPreload = (media) => {
            if (!media.dataset.source) return;
            delete media.dataset.source;
            media.removeAttribute("src"); media.load();
        };
        const primeNextSegment = (index) => {
            const media = index >= 0 && index < state.plan.shots.length
                ? playerCheckpoint(index) : null;
            const videoSource = media?.video ? videoUrl(media.video) : "";
            const audioSource = media?.audio ? videoUrl(media.audio) : "";
            if (!videoSource) clearPreload(preloadVideo);
            else if (preloadVideo.dataset.source !== videoSource) {
                preloadVideo.dataset.source = videoSource;
                preloadVideo.src = videoSource; preloadVideo.load();
            }
            if (!audioSource) clearPreload(preloadAudio);
            else if (preloadAudio.dataset.source !== audioSource) {
                preloadAudio.dataset.source = audioSource;
                preloadAudio.src = audioSource; preloadAudio.load();
            }
        };
        const captureHandoffFrame = () => {
            if (!video.videoWidth || !video.videoHeight ||
                    !stage.clientWidth || !stage.clientHeight) return;
            const ratio = Math.max(1, Number(window.devicePixelRatio) || 1);
            handoffFrame.width = Math.round(stage.clientWidth * ratio);
            handoffFrame.height = Math.round(stage.clientHeight * ratio);
            const context = handoffFrame.getContext("2d");
            if (!context) return;
            context.fillStyle = "#050608";
            context.fillRect(0, 0, handoffFrame.width, handoffFrame.height);
            const scale = Math.min(
                handoffFrame.width / video.videoWidth,
                handoffFrame.height / video.videoHeight,
            );
            const width = video.videoWidth * scale;
            const height = video.videoHeight * scale;
            try {
                context.drawImage(
                    video,
                    (handoffFrame.width - width) / 2,
                    (handoffFrame.height - height) / 2,
                    width, height,
                );
                handoffFrame.classList.remove("h3studio-handoff-release");
                handoffFrame.hidden = false;
            } catch (_error) {}
        };
        const releaseHandoffFrame = () => {
            if (handoffFrame.hidden) return;
            requestAnimationFrame(() => {
                handoffFrame.classList.add("h3studio-handoff-release");
            });
            window.setTimeout(() => {
                if (!handoffFrame.isConnected) return;
                handoffFrame.hidden = true;
            }, 180);
        };
        state.playerPreloadVideo = preloadVideo;
        state.playerPreloadAudio = preloadAudio;
        state.primePlayerNext = primeNextSegment;
        const controls = element("div", "h3studio-player-controls");
        const play = button(
            "▶",
            "Play or pause the planned timeline from the current position",
            () => state.togglePlayerPlayback?.(),
        );
        const slider = element("input"); slider.type = "range"; slider.min = "0"; slider.max = String(timing().totalSeconds); slider.step = String(1 / 24); slider.value = "0";
        const clock = element("span", "", `0 / ${formatClock(timing().totalSeconds)}`);
        slider.addEventListener("input", () => seekTimeline(Number(slider.value), false));
        const syncSource = () => {
            const reference = sourceReference(state.playerIndex);
            if (!reference || !sourceVideo.dataset.source) return;
            sourceVideo.playbackRate = video.playbackRate;
            const target = studioSourceSecond(reference, video.currentTime);
            if (Math.abs(sourceVideo.currentTime - target) > .055) {
                try { sourceVideo.currentTime = target; } catch (_error) {}
            }
        };
        const synchronizeGeneratedAudio = (playAudio = false) => {
            if (!generatedAudio.dataset.source) return;
            generatedAudio.playbackRate = video.playbackRate;
            if (Math.abs((Number(generatedAudio.currentTime) || 0) -
                    (Number(video.currentTime) || 0)) > .12) {
                try { generatedAudio.currentTime = video.currentTime; }
                catch (_error) {}
            }
            if (playAudio && generatedToggle.checked) {
                void generatedAudio.play().catch(() => {});
            }
        };
        const playerTimelineSecond = () => {
            const result = timing();
            return Math.min(
                result.totalSeconds,
                studioSceneStartSeconds(result.shots, state.playerIndex) +
                    (Number(video.currentTime) || 0),
            );
        };
        const synchronizeSourceTimelineAudio = (
            playAudio = false, timelineSecond = playerTimelineSecond(),
        ) => {
            const timelineAudio = sourceAudio();
            if (!timelineAudio || !sourceTimelineAudio.dataset.source) return;
            sourceTimelineAudio.playbackRate = video.playbackRate;
            const target = studioSourceAudioSecond(
                timelineAudio, timelineSecond,
            );
            if (Math.abs((Number(sourceTimelineAudio.currentTime) || 0) -
                    target) > .12) {
                try { sourceTimelineAudio.currentTime = target; }
                catch (_error) {}
            }
            sourceTimelineAudio.muted =
                !sourceToggle.checked ||
                sourceAudioMuted(state.playerIndex);
            if (playAudio && sourceToggle.checked) {
                void sourceTimelineAudio.play().catch(() => {});
            }
        };
        const updateTransportPosition = (current) => {
            const result = timing();
            const bounded = Math.max(0, Math.min(
                result.totalSeconds, Number(current) || 0,
            ));
            state.timelinePosition = bounded;
            slider.value = String(bounded);
            clock.textContent = `${formatClock(bounded)} / ${formatClock(result.totalSeconds)}`;
            if (state.playhead) state.playhead.style.left = `${result.totalSeconds ? bounded / result.totalSeconds * 100 : 0}%`;
        };
        const playPlayerTransport = () => {
            if (video.dataset.source) {
                return video.play().catch(() => {});
            }
            if (!sourceTimelineAudio.dataset.source) return undefined;
            synchronizeSourceTimelineAudio(
                false, state.timelinePosition ?? 0,
            );
            play.textContent = "❚❚";
            return sourceTimelineAudio.play().catch(() => {
                play.textContent = "▶";
            });
        };
        const togglePlayerPlayback = () => {
            if (video.dataset.source) {
                if (video.paused) void playPlayerTransport();
                else {
                    video.pause();
                    pausePlayerMonitors();
                }
                return;
            }
            if (!sourceTimelineAudio.dataset.source) return;
            if (sourceTimelineAudio.paused) void playPlayerTransport();
            else {
                sourceTimelineAudio.pause();
                generatedAudio.pause(); sourceVideo.pause();
            }
        };
        state.playPlayerTransport = playPlayerTransport;
        state.togglePlayerPlayback = togglePlayerPlayback;
        video.addEventListener("play", () => {
            play.textContent = "❚❚";
            syncSource(); synchronizeGeneratedAudio(true);
            synchronizeSourceTimelineAudio(true);
            if (sourceVideo.dataset.source) void sourceVideo.play().catch(() => {});
        });
        video.addEventListener("playing", releaseHandoffFrame);
        video.addEventListener("pause", () => {
            play.textContent = "▶";
            // The source track is a monitor slaved to the video transport.
            // Always stop it on pause; automatic scene handoff will restart it
            // from the next absolute timeline position when video fires play.
            pausePlayerMonitors();
        });
        video.addEventListener("waiting", () => {
            generatedAudio.pause(); sourceTimelineAudio.pause(); sourceVideo.pause();
        });
        generatedAudio.addEventListener("canplay", () => {
            synchronizeGeneratedAudio(!video.paused);
        });
        sourceVideo.addEventListener("canplay", () => {
            syncSource();
            if (!video.paused) void sourceVideo.play().catch(() => {});
        });
        sourceTimelineAudio.addEventListener("canplay", () => {
            synchronizeSourceTimelineAudio(!video.paused);
        });
        sourceTimelineAudio.addEventListener("play", () => {
            if (!video.dataset.source) play.textContent = "❚❚";
        });
        sourceTimelineAudio.addEventListener("pause", () => {
            if (!video.dataset.source) play.textContent = "▶";
        });
        video.addEventListener("seeking", () => {
            generatedAudio.pause(); sourceTimelineAudio.pause(); sourceVideo.pause();
            synchronizeGeneratedAudio(false); synchronizeSourceTimelineAudio(false);
            syncSource();
        });
        video.addEventListener("seeked", () => {
            synchronizeGeneratedAudio(!video.paused);
            synchronizeSourceTimelineAudio(!video.paused); syncSource();
            if (!video.paused && sourceVideo.dataset.source) {
                void sourceVideo.play().catch(() => {});
            }
        });
        video.addEventListener("ratechange", () => {
            synchronizeGeneratedAudio(false);
            synchronizeSourceTimelineAudio(false); syncSource();
        });
        video.addEventListener("timeupdate", () => {
            const result = timing();
            let prior = 0;
            for (let index = 0; index < state.playerIndex; index += 1) prior += result.shots[index].deliveredSeconds;
            const current = Math.min(result.totalSeconds, prior + video.currentTime);
            updateTransportPosition(current);
            synchronizeGeneratedAudio(false);
            synchronizeSourceTimelineAudio(false, current); syncSource();
        });
        sourceTimelineAudio.addEventListener("timeupdate", () => {
            if (video.dataset.source) return;
            const descriptor = sourceAudio();
            if (!descriptor) return;
            const current = Math.max(
                0,
                (Number(sourceTimelineAudio.currentTime) || 0) -
                    Math.max(0, Number(descriptor.seek_seconds) || 0),
            );
            const result = timing();
            const location = locateStudioTimelineSecond(result.shots, current);
            if (location.index >= 0 && location.index !== state.playerIndex) {
                seekTimeline(current, !sourceTimelineAudio.paused);
                return;
            }
            updateTransportPosition(current);
        });
        sourceTimelineAudio.addEventListener("ended", () => {
            if (video.dataset.source) return;
            updateTransportPosition(timing().totalSeconds);
            play.textContent = "▶";
        });
        video.addEventListener("ended", () => {
            captureHandoffFrame();
            generatedAudio.pause(); sourceVideo.pause();
            const next = state.playerIndex + 1;
            if (next >= state.plan.shots.length) {
                sourceTimelineAudio.pause();
                return;
            }
            const result = timing();
            const start = studioSceneStartSeconds(result.shots, next);
            seekTimeline(start, true);
        });
        const compareControls = element("div", "h3studio-compare-controls");
        const wipeLabel = element("span", "h3studio-wipe-label", "Wipe");
        const wipe = element("input", "h3studio-wipe-control");
        wipe.type = "range"; wipe.min = "0"; wipe.max = "100";
        wipe.step = "1"; wipe.value = "50";
        wipe.addEventListener("input", () => {
            const percent = Number(wipe.value);
            sourceLayer.style.clipPath = `inset(0 ${100 - percent}% 0 0)`;
            wipeLine.style.left = `${percent}%`;
        });
        const audioMix = element("div", "h3studio-audio-mix");
        const applyAudioVolumes = () => {
            video.volume = state.generatedVolume;
            generatedAudio.volume = state.generatedVolume;
            sourceTimelineAudio.volume = state.sourceVolume;
            sourceVideo.volume = state.motionVolume;
        };
        const audioToggle = (
            className, text, checked, propertyName, stateName,
        ) => {
            const control = element("div", "h3studio-audio-control");
            const wrapper = element("label", "h3studio-audio-toggle");
            const input = element("input", className);
            input.type = "checkbox"; input.checked = checked;
            const copy = element("span", "", text);
            wrapper.append(input, copy);
            const volume = element("input", "h3studio-audio-volume");
            volume.type = "range"; volume.min = "0"; volume.max = "1";
            volume.step = ".01"; volume.value = String(state[stateName]);
            volume.title = `${text} monitor volume`;
            const level = element(
                "span", "h3studio-audio-level",
                `${Math.round(state[stateName] * 100)}%`,
            );
            volume.addEventListener("input", () => {
                state[stateName] = Math.max(0, Math.min(1,
                    Number(volume.value) || 0));
                level.textContent = `${Math.round(state[stateName] * 100)}%`;
                applyAudioVolumes();
            });
            volume.addEventListener("change", () => {
                node.properties[propertyName] = state[stateName];
                dirty();
            });
            control.append(wrapper, volume, level);
            return {wrapper:control, input, copy, volume};
        };
        const generatedControl = audioToggle(
            "h3studio-audio-generated", "Generated", true,
            GENERATED_VOLUME_PROPERTY, "generatedVolume",
        );
        const sourceControl = audioToggle(
            "h3studio-audio-source", "Source track", true,
            SOURCE_VOLUME_PROPERTY, "sourceVolume",
        );
        const motionControl = audioToggle(
            "h3studio-audio-motion", "Motion-ref", false,
            MOTION_VOLUME_PROPERTY, "motionVolume",
        );
        const generatedToggle = generatedControl.input;
        const sourceToggle = sourceControl.input;
        const motionToggle = motionControl.input;
        const applyAudioMix = () => {
            applyAudioVolumes();
            video.muted = !generatedToggle.checked ||
                Boolean(generatedAudio.dataset.source);
            generatedAudio.muted = !generatedToggle.checked;
            sourceVideo.muted = !motionToggle.checked;
            sourceTimelineAudio.muted = !sourceToggle.checked ||
                sourceAudioMuted(state.playerIndex);
            if (generatedToggle.checked) {
                synchronizeGeneratedAudio(!video.paused);
            } else {
                generatedAudio.pause();
            }
            if (sourceToggle.checked) {
                synchronizeSourceTimelineAudio(!video.paused);
            } else {
                sourceTimelineAudio.pause();
            }
        };
        for (const control of [
            generatedControl, sourceControl, motionControl,
        ]) {
            control.input.addEventListener("change", applyAudioMix);
            audioMix.append(control.wrapper);
        }
        applyAudioVolumes();
        compareControls.append(wipeLabel, wipe, audioMix);
        state.player = video; state.playerAudio = generatedAudio;
        state.sourceAudioPlayer = sourceTimelineAudio;
        state.sourcePlayer = sourceVideo;
        state.sourceLayer = sourceLayer; state.playerSlider = slider;
        controls.append(play, slider, clock, button("Refresh", "Rescan saved checkpoints and segments", async () => {
            await refreshCheckpoints(); renderPanel();
        }));
        wrapper.append(
            label, stage, generatedAudio, sourceTimelineAudio,
            preloadVideo, preloadAudio,
            compareControls, controls,
            element("div", "h3studio-message", "Generated and Source Track can play together on the planned timeline. Before a scene is rendered, Source Track playback supplies the timeline clock; playback hands back to video automatically when a saved segment begins. Each monitor has independent volume; waveform speaker buttons mute only the Source Track for that scene. Click the player and press Space to play or pause. Motion-ref audio is optional when available."),
        );
        setTimeout(() => {
            if (state.player !== video || !video.isConnected) return;
            const result = timing();
            const start = state.timelinePosition == null
                ? studioSceneStartSeconds(result.shots, state.active)
                : state.timelinePosition;
            seekTimeline(start, false);
        }, 0);
        return wrapper;
    }

    function renderJsonPanel() {
        const panel = element("div");
        const textarea = element("textarea", "h3studio-json"); textarea.value = planToJson(state.plan); textarea.spellcheck = false;
        const status = element("span", "h3studio-message", "Raw JSON escape hatch");
        const actions = element("div", "h3studio-json-actions");
        actions.append(button("Apply JSON", "Validate and replace the current plan JSON", () => {
            try { state.plan = parsePlanJson(textarea.value); state.active = Math.min(state.active, state.plan.shots.length - 1); writePlan(); status.textContent = "JSON applied"; renderShell(); publishActiveScene(); }
            catch (error) { status.textContent = error.message; status.classList.add("h3studio-error"); }
        }), button("Copy", "Copy plan JSON", async () => {
            try { await navigator.clipboard.writeText(textarea.value); status.textContent = "Copied"; }
            catch (_error) { textarea.select(); document.execCommand("copy"); status.textContent = "Copied"; }
        }), status);
        panel.append(textarea, actions); return panel;
    }

    function renderPanel() {
        if (!state.panelHost || !state.plan) return;
        state.history.host = null; state.history.textarea = null; state.history.status = null;
        disposePlayer();
        const content = state.view === "scene" && state.activeChapterId
            ? renderChapterPanel()
            : state.view === "shared" ? renderSharedPanel()
            : state.view === "settings" ? renderPlanSettingsPanel()
            : state.view === "context" ? renderContextPanel()
            : state.view === "player" ? renderPlayerPanel()
              : state.view === "json" ? renderJsonPanel() : renderScenePanel();
        state.panelHost.replaceChildren(content);
    }

    function renderToolbarState() {
        for (const item of root.querySelectorAll("[data-studio-view]")) {
            item.classList.toggle("h3studio-active", item.dataset.studioView === state.view);
        }
    }

    function renderShell() {
        disposePlayer();
        state.timelineResizeObserver?.disconnect();
        state.timelineResizeObserver = null;
        root.replaceChildren();
        const head = element("div", "h3studio-head");
        head.append(element("span", "h3studio-title", "MiniMax H3 Plan Studio"),
            element("span", "h3studio-run", runName()
                ? `${state.planNode ? "linked" : "standalone"} · ${runName()}`
                : "name this run in Plan settings"));
        const toolbar = element("div", "h3studio-toolbar");
        const add = button("+ Scene", "Append a new scene and select it", async () => {
            if (state.plan.shots.length >= MAX_SHOTS) return;
            await flushHistoryDraft();
            state.plan.shots.push(makeShot(state.plan.shots));
            state.activeChapterId = "";
            state.active = state.plan.shots.length - 1;
            state.timelinePosition = null; persistView(); writePlan(); renderShell(); publishActiveScene();
        });
        add.disabled = state.plan.shots.length >= MAX_SHOTS;
        const addChapter = button("+ Chapter", "Add a zero-duration chapter marker before the selected scene", async () => {
            await flushHistoryDraft();
            try {
                const chapter = makeChapter(state.plan, state.active);
                state.activeChapterId = chapter.id;
                state.view = "scene";
                persistView(); writePlan(); renderShell();
            } catch (error) {
                console.warn(error);
            }
        });
        const duplicate = button("Duplicate", "Duplicate the selected scene", async () => {
            if (state.plan.shots.length >= MAX_SHOTS) return;
            await flushHistoryDraft();
            duplicateShot(state.plan.shots, state.active); state.active += 1;
            state.activeChapterId = "";
            state.timelinePosition = null; persistView(); writePlan(); renderShell(); publishActiveScene();
        });
        const remove = button(state.activeChapterId ? "Delete chapter" : "Delete", "Delete the selected scene or chapter", async () => {
            if (state.activeChapterId) {
                const chapter = orderedChapters(state.plan).find(
                    (candidate) => candidate.id === state.activeChapterId,
                );
                if (!chapter || !confirm(`Delete ${chapter.title}?`)) return;
                state.plan.chapters = state.plan.chapters.filter(
                    (candidate) => candidate.id !== chapter.id,
                );
                if (!state.plan.chapters.length) delete state.plan.chapters;
                state.activeChapterId = "";
                persistView(); writePlan(); renderShell();
                return;
            }
            if (state.plan.shots.length <= 1 || !confirm(`Delete scene ${state.active + 1}?`)) return;
            await flushHistoryDraft();
            removePlanShot(state.plan, state.active);
            state.active = Math.min(state.active, state.plan.shots.length - 1);
            state.timelinePosition = null; persistView(); writePlan(); renderShell(); publishActiveScene();
        });
        remove.disabled = !state.activeChapterId && state.plan.shots.length <= 1;
        const left = button("←", "Move selected scene earlier", async () => {
            if (!state.active) return; await flushHistoryDraft();
            moveShot(state.plan.shots, state.active, state.active - 1); state.active -= 1;
            state.timelinePosition = null; persistView(); writePlan(); renderShell(); publishActiveScene();
        }); left.disabled = Boolean(state.activeChapterId) || !state.active;
        const right = button("→", "Move selected scene later", async () => {
            if (state.active >= state.plan.shots.length - 1) return; await flushHistoryDraft();
            moveShot(state.plan.shots, state.active, state.active + 1); state.active += 1;
            state.timelinePosition = null; persistView(); writePlan(); renderShell(); publishActiveScene();
        }); right.disabled = Boolean(state.activeChapterId)
            || state.active >= state.plan.shots.length - 1;
        toolbar.append(add, addChapter, duplicate, remove, left, right, element("span", "h3studio-spacer"));
        const sceneViewLabel = state.activeChapterId
            ? "Chapter notes"
            : state.promptEditors.length ? "Scene settings" : "Scene prompt";
        for (const [value,label] of [["scene",sceneViewLabel],["shared","Shared prompt"],
            ["settings","Plan settings"],["context","Context"],
            ["player","Player"],["json","JSON"]]) {
            const item = button(label, `Open ${label.toLowerCase()} view`, () => {
                void flushHistoryDraft();
                if (value === "player" && state.timelinePosition == null) {
                    state.timelinePosition = studioSceneStartSeconds(timing().shots, state.active);
                }
                state.view = value; persistView(); renderToolbarState();
                renderSourceTimeline(); renderSourceAudioTimeline(); renderPanel();
            });
            item.dataset.studioView = value; toolbar.append(item);
        }
        const status = element("div", "h3studio-statusline");
        const shell = element("div", "h3studio-timeline-shell");
        const timelineTools = element("div", "h3studio-timeline-tools");
        const zoomOut = button(
            "−", "Zoom timeline out", () => setTimelineZoom(
                state.timelineZoom - .25,
            ),
        );
        const zoomInput = element("input", "h3studio-timeline-zoom");
        zoomInput.type = "range";
        zoomInput.min = "1";
        zoomInput.max = "6";
        zoomInput.step = ".05";
        zoomInput.value = String(state.timelineZoom);
        zoomInput.title = "Timeline zoom · Ctrl/Cmd + wheel over the timeline";
        zoomInput.addEventListener("input", () => {
            setTimelineZoom(zoomInput.value);
        });
        const zoomLabel = element(
            "span", "h3studio-zoom-label",
            `${Math.round(state.timelineZoom * 100)}%`,
        );
        const zoomIn = button(
            "+", "Zoom timeline in", () => setTimelineZoom(
                state.timelineZoom + .25,
            ),
        );
        const fit = button("Fit", "Fit timeline to the available width", () => {
            setTimelineZoom(1);
        });
        timelineTools.append(
            element("strong", "", "Timeline"),
            element("span", "h3studio-spacer"),
            zoomOut, zoomInput, zoomLabel, zoomIn, fit,
        );
        const timelineGrid = element("div", "h3studio-timeline-grid");
        const timelineLabels = element("div", "h3studio-timeline-labels");
        timelineLabels.append(
            element("span", "", "TIME"),
            element("span", "", "GENERATED"),
            element("span", "", "MOTION REF"),
            element("span", "", "SOURCE AUDIO"),
        );
        const timelineViewport = element("div", "h3studio-timeline-viewport");
        const timelineContent = element("div", "h3studio-timeline-content");
        const ruler = element("div", "h3studio-ruler");
        const timelineHost = element("div", "h3studio-timeline h3studio-generated-timeline");
        const sourceTimelineHost = element("div", "h3studio-timeline");
        const sourceAudioTimelineHost = element(
            "div", "h3studio-timeline h3studio-audio-timeline",
        );
        timelineContent.append(
            ruler, timelineHost, sourceTimelineHost, sourceAudioTimelineHost,
        );
        timelineViewport.append(timelineContent);
        timelineGrid.append(timelineLabels, timelineViewport);
        shell.append(timelineTools, timelineGrid);
        state.timelineHost = timelineHost;
        state.sourceTimelineHost = sourceTimelineHost;
        state.sourceAudioTimelineHost = sourceAudioTimelineHost;
        state.sourceTrack = sourceTimelineHost;
        state.sourceAudioTrack = sourceAudioTimelineHost;
        state.timelineViewport = timelineViewport;
        state.timelineContent = timelineContent;
        state.timelineRuler = ruler;
        state.timelineZoomInput = zoomInput;
        state.timelineZoomLabel = zoomLabel;
        timelineViewport.addEventListener("wheel", (event) => {
            if (event.ctrlKey || event.metaKey) {
                event.preventDefault();
                const rect = timelineViewport.getBoundingClientRect();
                const anchor = rect.width > 0
                    ? (event.clientX - rect.left) / rect.width : .5;
                setTimelineZoom(
                    state.timelineZoom * Math.exp(-event.deltaY * .0025),
                    anchor,
                );
            } else if (event.shiftKey && event.deltaY) {
                event.preventDefault();
                timelineViewport.scrollLeft += event.deltaY;
            }
        }, {passive:false});
        if (typeof ResizeObserver === "function") {
            state.timelineResizeObserver = new ResizeObserver(() => {
                layoutTimeline({preserveScroll:true});
            });
            state.timelineResizeObserver.observe(timelineViewport);
        }
        const panelHost = element("div", "h3studio-panel"); state.panelHost = panelHost;
        root.append(head, toolbar, status, shell, panelHost);
        renderRuler(ruler, timing().totalSeconds); renderToolbarState(); renderStatus(); renderTimeline(); renderPanel();
    }

    function showFailure(message) {
        disposePlayer();
        root.replaceChildren(element("div", "h3studio-title", "MiniMax H3 Plan Studio"),
            element("div", "h3studio-error", message),
            element("div", "h3studio-message", "Repair the JSON tab or connect a valid H3 Chain Plan. Studio can operate in either mode."));
    }

    function loadPlan(force = false) {
        const planNode = upstreamPlanNode(node);
        if (planNode) mirrorConnectedPlan(planNode);
        const planOwner = planNode ?? node;
        const planWidget = widget(planOwner, "plan_json");
        if (!planWidget) {
            if (force || state.planOwner) {
                state.plan = null; state.planNode = null;
                state.planOwner = null; state.planWidget = null;
                showFailure("Plan Studio's internal Plan fields are unavailable.");
            }
            return;
        }
        const value = String(planWidget.value ?? "");
        const currentRun = String(widget(planOwner, "run_name")?.value ?? "").trim();
        const currentSettings = settingsSignature(planOwner);
        const promptEditors = planNode ? connectedPromptEditors(node).filter(
            (editor) => upstreamPlanNode(editor) === planNode,
        ) : [];
        const currentPromptEditors = promptEditorsSignature(promptEditors);
        if (!force && planOwner === state.planOwner && value === state.lastValue
                && currentRun === state.lastRunName
                && currentSettings === state.lastSettingsSignature
                && currentPromptEditors === state.lastPromptEditorsSignature) return;
        try {
            const runChanged = planOwner !== state.planOwner || currentRun !== state.lastRunName;
            state.plan = parsePlanJson(value); state.planNode = planNode;
            state.planOwner = planOwner; state.planWidget = planWidget;
            state.lastValue = value; state.lastRunName = currentRun;
            state.lastSettingsSignature = currentSettings;
            state.promptEditors = promptEditors;
            state.lastPromptEditorsSignature = currentPromptEditors;
            if (state.activeChapterId && !orderedChapters(state.plan).some(
                (chapter) => chapter.id === state.activeChapterId,
            )) state.activeChapterId = "";
            if (runChanged) {
                state.checkpoints = new Map(); state.checkpointSignature = "";
                state.checkpointError = ""; state.timelinePosition = null;
                state.presentationToken += 1;
                state.sourcePreview = null;
                state.sourceWaveform = null; state.sourceWaveformToken = "";
                state.sourceWaveformPromise = null;
            }
            state.active = Math.min(state.active, state.plan.shots.length - 1);
            if (Object.hasOwn(state.plan, "chapters")) scheduleEditorialSave();
            renderShell(); void refreshCheckpoints();
            if (runChanged && currentRun) void restoreSourcePresentation();
        } catch (error) {
            showFailure(`${planNode ? "Connected Plan" : "Standalone Plan Studio"} JSON is invalid:\n${error.message}`);
        }
    }

    const domWidget = node.addDOMWidget("h3_plan_studio", "h3-plan-studio", root, {
        serialize:false, hideOnZoom:false, getMinHeight:() => 540,
    });
    domWidget.serialize = false;
    node.setSize?.([Math.max(Number(node.size?.[0]) || 0, MIN_WIDTH), Math.max(Number(node.size?.[1]) || 0, MIN_HEIGHT)]);
    const connectionsChanged = node.onConnectionsChange;
    node.onConnectionsChange = function () {
        const result = connectionsChanged?.apply(this, arguments);
        setTimeout(() => { loadPlan(true); publishActiveScene(); }, 0);
        return result;
    };
    const onPromptExecuted = (event) => {
        const sourceValues = event.detail?.output?.h3_plan_studio_source_timeline;
        const sourcePayload = Array.isArray(sourceValues) ? sourceValues.at(-1) : null;
        const displayNode = event.detail?.display_node ?? event.detail?.node;
        if (sourcePayload && String(displayNode ?? "") === String(node.id ?? "")
                && String(sourcePayload.run_name ?? "") === runName()) {
            state.presentationToken += 1;
            applySourcePresentation(sourcePayload);
        }
        const values = event.detail?.output?.h3_chain_active_scene;
        const scene = Array.isArray(values) ? values.at(-1) : null;
        if (!scene || String(scene.run_name ?? "") !== runName()) return;
        const shot = state.plan?.shots?.[state.active];
        const sceneId = safeShotId(
            shot?.id, `clip_${String(state.active + 1).padStart(4, "0")}`,
        );
        if (String(scene.shot_id ?? "") !== sceneId) return;
        setTimeout(() => {
            if (state.view !== "scene" || state.history.sceneKey !== historyKey(sceneId)) return;
            void loadHistory(sceneId, promptValueToText(shot.prompt), false);
        }, 50);
    };
    api.addEventListener("executed", onPromptExecuted);
    const removed = node.onRemoved;
    node.onRemoved = function () {
        state.disposed = true;
        state.checkpointToken += 1;
        state.presentationToken += 1;
        if (state.pollTimer != null) clearInterval(state.pollTimer);
        if (state.checkpointTimer != null) clearInterval(state.checkpointTimer);
        if (state.planNotifyTimer != null) clearTimeout(state.planNotifyTimer);
        if (state.editorialTimer != null) clearTimeout(state.editorialTimer);
        state.timelineResizeObserver?.disconnect();
        api.removeEventListener("executed", onPromptExecuted);
        document.removeEventListener("keydown", onPlayerKeydown, true);
        delete node._h3PromptCompanionSetActiveScene;
        delete node._h3PromptCompanionSetScenePrompt;
        disposePlayer();
        void flushHistoryDraft(); return removed?.apply(this, arguments);
    };
    node._h3PromptCompanionSetActiveScene = (planNode, index) => {
        if (planNode !== state.planNode || !state.plan?.shots?.length) return false;
        void selectScene(index, false);
        return true;
    };
    node._h3PromptCompanionSetScenePrompt = (planNode, index, text) => {
        if (planNode !== state.planNode || !state.plan?.shots?.[index]) return false;
        state.plan.shots[index].prompt = promptTextToLines(text);
        if (index === state.active && state.history.textarea
                && state.history.textarea.value !== text) {
            const textarea = state.history.textarea;
            const focused = document.activeElement === textarea;
            const start = textarea.selectionStart;
            const end = textarea.selectionEnd;
            textarea.value = text;
            if (focused) textarea.setSelectionRange(
                Math.min(start, text.length), Math.min(end, text.length));
            scheduleHistoryDraft(
                String(state.plan.shots[index].id || `clip_${String(index + 1).padStart(4, "0")}`),
                text);
        }
        state.lastValue = String(state.planWidget?.value ?? state.lastValue);
        return true;
    };
    node._h3PlanStudioRefresh = () => {
        loadPlan(true);
        publishActiveScene();
    };
    state.pollTimer = setInterval(() => loadPlan(false), 500);
    state.checkpointTimer = setInterval(() => void refreshCheckpoints(), 5000);
    loadPlan(true);
}

app.registerExtension({
    name:"minimax_h3_context_loop.plan_studio",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== NODE_NAME) return;
        const created = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const result = created?.apply(this, arguments); setTimeout(() => mount(this), 0); return result;
        };
    },
    async nodeCreated(node) { if (nodeType(node) === NODE_NAME) mount(node); },
    async afterConfigureGraph() {
        for (const node of allNodes(app.graph)) if (nodeType(node) === NODE_NAME) setTimeout(() => node._h3PlanStudioRefresh?.(), 0);
    },
});
