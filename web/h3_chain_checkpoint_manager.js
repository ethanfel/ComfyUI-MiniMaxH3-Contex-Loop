import {app} from "/scripts/app.js";
import {api} from "/scripts/api.js";
import {
    checkpointBranchRows,
    checkpointChapterBranchRows,
    checkpointDeletionTitle,
    checkpointDependencyText,
    checkpointRevisionKey,
    checkpointRevisionLineage,
    checkpointSelectionJson,
    formatCheckpointBytes,
    selectedCheckpointRevision,
} from "./h3_checkpoint_manager_core.mjs?v=0.6.57";
import {
    parsePlanJson,
    planToJson,
    promptValueToText,
} from "./h3_chain_plan_core.mjs?v=0.6.57";
import {applyCheckpointRevisionSet} from "./h3_chain_review_core.mjs?v=0.6.57";
import * as promptCompanionSync from "./h3_prompt_companion_sync.mjs?v=0.6.57";
import {
    refreshRestoredPlanEditors,
    restoreConnectedPolicyInputs,
} from "./h3_plan_restore_core.mjs?v=0.6.57";

const NODE_NAME = "MiniMaxH3ChainCheckpointManager";
const PLAN_NAME = "MiniMaxH3ChainPlan";
const START_NAME = "MiniMaxH3ChainLoopStart";
const RUN_PROPERTY = "h3_checkpoint_manager_run";
const SCENE_PROPERTY = "h3_checkpoint_manager_scene";
const REVISION_PROPERTY = "h3_checkpoint_manager_revision";
const CHAPTER_PROPERTY = "h3_checkpoint_manager_chapter";
const COLLAPSED_CHAPTERS_PROPERTY = "h3_checkpoint_manager_collapsed_chapters";
const SHARED_COLORS = ["#6ea8ff", "#58c99d", "#bd8cff", "#e8a84f", "#f07f8c", "#55bfd0"];

function nodeType(node) {
    return node?.comfyClass ?? node?.type ?? "";
}

function upstreamPlanNode(start) {
    const queue = [start];
    const seen = new Set();
    while (queue.length) {
        const current = queue.shift();
        if (!current || seen.has(current)) continue;
        seen.add(current);
        if (current !== start && nodeType(current) === PLAN_NAME) return current;
        for (const input of current.inputs ?? []) {
            if (input.link == null) continue;
            const link = graphLink(current.graph, input.link);
            const candidate = link
                ? current.graph?.getNodeById?.(link.origin_id) : null;
            if (candidate) queue.push(candidate);
        }
    }
    return null;
}

function widget(node, name) {
    return node?.widgets?.find((item) => item.name === name);
}

function graphLink(graph, linkId) {
    return graph?.links?.[linkId] ?? graph?.links?.get?.(linkId) ?? null;
}

function connectedNode(start, wantedType) {
    const queue = [start];
    const seen = new Set();
    while (queue.length) {
        const current = queue.shift();
        if (!current || seen.has(current)) continue;
        seen.add(current);
        if (current !== start && nodeType(current) === wantedType) return current;
        for (const input of current.inputs ?? []) {
            if (input.link == null) continue;
            const link = graphLink(current.graph, input.link);
            const candidate = link
                ? current.graph?.getNodeById?.(link.origin_id) : null;
            if (candidate) queue.push(candidate);
        }
        for (const output of current.outputs ?? []) {
            for (const linkId of output.links ?? []) {
                const link = graphLink(current.graph, linkId);
                const candidate = link
                    ? current.graph?.getNodeById?.(link.target_id) : null;
                if (candidate) queue.push(candidate);
            }
        }
    }
    return null;
}

function publishCompanionPrompt(...args) {
    return promptCompanionSync.publishCompanionPrompt?.(...args) ?? 0;
}

function element(tag, className = "", text = undefined) {
    const item = document.createElement(tag);
    if (className) item.className = className;
    if (text !== undefined) item.textContent = text;
    return item;
}

function button(label, title, action, className = "") {
    const item = element("button", className, label);
    item.type = "button";
    item.title = title;
    item.addEventListener("click", action);
    return item;
}

function videoUrl(item) {
    if (!item?.filename) return "";
    const query = new URLSearchParams({
        filename:item.filename,
        subfolder:item.subfolder ?? "",
        type:item.type ?? "output",
    });
    return api.apiURL(`/view?${query.toString()}`);
}

function localTime(value) {
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? String(value || "unknown") : date.toLocaleString();
}

function sharedColor(key) {
    let hash = 0;
    for (const character of String(key ?? "")) {
        hash = ((hash * 31) + character.codePointAt(0)) >>> 0;
    }
    return SHARED_COLORS[hash % SHARED_COLORS.length];
}

async function jsonRequest(path, options = {}) {
    const response = await api.fetchApi(path, options);
    const payload = await response.json();
    if (!response.ok) throw Object.assign(
        new Error(payload.error || `HTTP ${response.status}`), {payload});
    return payload;
}

function injectStyles() {
    if (document.getElementById("h3-checkpoint-manager-style")) return;
    const style = document.createElement("style");
    style.id = "h3-checkpoint-manager-style";
    style.textContent = `
      .h3cm-root { --h3cm-bg:color-mix(in srgb,var(--comfy-menu-bg,#202124) 93%,#101827);
        --h3cm-panel:var(--comfy-input-bg,#15171d); --h3cm-border:var(--border-color,#586174);
        --h3cm-text:var(--input-text,#edf1f8); --h3cm-muted:color-mix(in srgb,var(--h3cm-text) 58%,transparent);
        --h3cm-accent:color-mix(in srgb,var(--h3cm-text) 38%,#4f83ff);
        --h3cm-danger:color-mix(in srgb,var(--h3cm-text) 40%,#d44747);
        box-sizing:border-box; width:100%; height:100%; min-height:620px; display:flex; flex-direction:column;
        gap:8px; overflow:hidden; padding:10px; border:1px solid var(--h3cm-border); border-radius:9px;
        background:var(--h3cm-bg); color:var(--h3cm-text); font:12px/1.4 system-ui,sans-serif; }
      .h3cm-root *, .h3cm-root *::before, .h3cm-root *::after { box-sizing:border-box; }
      .h3cm-head,.h3cm-run-row,.h3cm-chapter-tabs,.h3cm-scenes,.h3cm-branch-head,.h3cm-branch-path,.h3cm-delete-actions {
        display:flex; align-items:center; gap:6px; }
      .h3cm-head { justify-content:space-between; }
      .h3cm-title { font-size:15px; font-weight:760; color:var(--h3cm-accent); }
      .h3cm-summary,.h3cm-status,.h3cm-muted { color:var(--h3cm-muted); }
      .h3cm-root button,.h3cm-root select { min-height:30px; border:1px solid var(--h3cm-border);
        border-radius:6px; background:var(--h3cm-panel); color:var(--h3cm-text); font:inherit; }
      .h3cm-root button { padding:5px 8px; cursor:pointer; }
      .h3cm-root button:hover,.h3cm-root button:focus-visible { border-color:var(--h3cm-accent); outline:none; }
      .h3cm-root button:disabled { cursor:not-allowed; opacity:.45; }
      .h3cm-run-select { flex:1; min-width:0; padding:5px 7px; }
      .h3cm-scenes { flex:0 0 auto; overflow:auto; padding-bottom:2px; }
      .h3cm-chapter-tabs { flex:0 0 auto; overflow:auto; padding:2px 0; }
      .h3cm-chapter-tab { white-space:nowrap; border-radius:999px !important; }
      .h3cm-chapter-selected { color:#ffe0a2 !important; border-color:#d6a650 !important;
        background:color-mix(in srgb,var(--h3cm-panel) 78%,#6d4b16) !important; }
      .h3cm-scene { white-space:nowrap; }
      .h3cm-scene-selected,.h3cm-revision-selected { border-color:var(--h3cm-accent) !important;
        color:var(--h3cm-accent) !important; }
      .h3cm-main { min-height:0; flex:1 1 auto; display:grid; grid-template-columns:minmax(310px,.9fr) minmax(390px,1.1fr); gap:8px; }
      .h3cm-panel { min-height:0; overflow:auto; padding:8px; border:1px solid var(--h3cm-border);
        border-radius:7px; background:color-mix(in srgb,var(--h3cm-panel) 90%,transparent); }
      .h3cm-panel-title { display:flex; justify-content:space-between; gap:8px; margin-bottom:7px; font-weight:750; }
      .h3cm-shared-legend { color:var(--h3cm-muted); font-size:10px; font-weight:500; }
      .h3cm-branches { position:relative; }
      .h3cm-branch-chapter { margin-bottom:12px; padding:7px; border:1px solid color-mix(in srgb,var(--h3cm-border) 62%,transparent);
        border-radius:8px; background:color-mix(in srgb,var(--h3cm-panel) 70%,transparent); }
      .h3cm-branch-chapter:last-child { margin-bottom:0; }
      .h3cm-branch-chapter-title { width:100%; min-height:0 !important; display:flex; align-items:center;
        justify-content:flex-start; gap:7px; margin:0 0 7px; padding:2px !important; border:0 !important;
        background:transparent !important; color:#ffe0a2 !important; font-size:11px !important;
        font-weight:750 !important; text-align:left; }
      .h3cm-branch-chapter-title:hover,.h3cm-branch-chapter-title:focus-visible {
        color:var(--h3cm-accent) !important; outline:1px solid var(--h3cm-accent) !important; }
      .h3cm-branch-chapter-title .h3cm-muted { margin-left:auto; font-weight:500; }
      .h3cm-branch-chapter-caret { width:11px; color:currentColor; text-align:center; }
      .h3cm-branch-chapter-collapsed { padding-bottom:7px; }
      .h3cm-branch-chapter-collapsed .h3cm-branch-chapter-title { margin-bottom:0; }
      .h3cm-branch { position:relative; z-index:1; margin-bottom:8px; padding:6px;
        border:1px solid color-mix(in srgb,var(--h3cm-border) 75%,transparent); border-radius:6px; }
      .h3cm-branch-head { justify-content:space-between; margin-bottom:5px; }
      .h3cm-branch-head[role="button"] { cursor:pointer; border-radius:4px; }
      .h3cm-branch-head[role="button"]:hover,.h3cm-branch-head[role="button"]:focus-visible {
        color:var(--h3cm-accent); outline:1px solid var(--h3cm-accent); outline-offset:2px; }
      .h3cm-branch-selected { border-color:var(--h3cm-accent) !important; }
      .h3cm-branch-active { color:var(--h3cm-accent); font-weight:700; }
      .h3cm-branch-path { position:relative; z-index:3; align-items:stretch; overflow:auto; padding-bottom:2px; }
      .h3cm-arrow { align-self:center; color:var(--h3cm-muted); }
      .h3cm-revision { position:relative; min-width:112px; text-align:left; white-space:nowrap; }
      .h3cm-revision small { display:block; color:var(--h3cm-muted); font-size:10px; }
      .h3cm-revision-empty { border-style:dashed !important; color:var(--h3cm-muted) !important;
        background:color-mix(in srgb,var(--h3cm-panel) 72%,transparent) !important; }
      .h3cm-revision-empty-selected { border-color:var(--h3cm-accent) !important;
        color:var(--h3cm-accent) !important; }
      .h3cm-revision-shared { border-color:var(--h3cm-shared-color) !important;
        box-shadow:inset 3px 0 0 var(--h3cm-shared-color); }
      .h3cm-shared-label { display:block; width:max-content; margin:2px 0; padding:1px 5px;
        border-radius:999px; background:color-mix(in srgb,var(--h3cm-shared-color) 23%,transparent);
        color:color-mix(in srgb,var(--h3cm-shared-color) 72%,var(--h3cm-text)); font-size:9px; font-weight:750; }
      .h3cm-detail { display:flex; flex-direction:column; gap:8px; }
      .h3cm-preview { width:100%; max-height:280px; min-height:150px; object-fit:contain; border-radius:6px; background:#08090c; }
      .h3cm-audio { width:100%; height:36px; }
      .h3cm-inspector { display:grid; grid-template-columns:auto minmax(0,1fr); gap:3px 9px; }
      .h3cm-inspector dt { color:var(--h3cm-muted); }
      .h3cm-inspector dd { margin:0; overflow-wrap:anywhere; }
      .h3cm-prompt { max-height:90px; overflow:auto; padding:6px; border-radius:5px;
        background:var(--h3cm-panel); white-space:pre-wrap; overflow-wrap:anywhere; }
      .h3cm-attribution { padding:7px; border:1px dashed var(--h3cm-accent);
        border-radius:6px; background:color-mix(in srgb,var(--h3cm-accent) 8%,transparent); }
      .h3cm-attribution-title { margin-bottom:6px; font-weight:750; color:var(--h3cm-accent); }
      .h3cm-attribution-candidates { display:flex; flex-wrap:wrap; gap:5px; margin-bottom:7px; }
      .h3cm-attribution-candidate-selected { border-color:var(--h3cm-accent) !important;
        color:var(--h3cm-accent) !important; }
      .h3cm-delete { flex:0 0 auto; max-height:210px; overflow:auto; padding:8px;
        border:1px solid var(--h3cm-border); border-radius:7px; }
      .h3cm-delete-blocked { border-color:var(--h3cm-danger); }
      .h3cm-delete-title { font-weight:700; }
      .h3cm-files,.h3cm-dependents { margin:5px 0 0; padding-left:18px; }
      .h3cm-dependent { color:var(--h3cm-danger); cursor:pointer; }
      .h3cm-delete-actions { margin-top:7px; }
      .h3cm-delete-actions .h3cm-status { flex:1 1 180px; min-width:120px; }
      .h3cm-delete-button { margin-left:auto; color:var(--h3cm-danger) !important; }
      .h3cm-error { color:var(--h3cm-danger); }
      @media (max-width:760px) { .h3cm-main { grid-template-columns:1fr; }
        .h3cm-root { overflow:auto; } }
    `;
    document.head.append(style);
}

function mount(node) {
    if (node._h3CheckpointManagerMounted) return;
    node._h3CheckpointManagerMounted = true;
    injectStyles();
    node.properties ??= {};
    const selectionWidget = widget(node, "selection_json");
    if (selectionWidget) {
        selectionWidget.hidden = true;
        selectionWidget.type = "hidden";
        selectionWidget.computeSize = () => [0, -4];
    }
    const state = {
        runs:[], runName:String(node.properties[RUN_PROPERTY] ?? ""), payload:null,
        scene:Number(node.properties[SCENE_PROPERTY]) || null,
        revision:String(node.properties[REVISION_PROPERTY] ?? ""),
        chapterTab:String(node.properties[CHAPTER_PROPERTY] ?? "all"),
        collapsedChapters:new Set(
            Array.isArray(node.properties[COLLAPSED_CHAPTERS_PROPERTY])
                ? node.properties[COLLAPSED_CHAPTERS_PROPERTY].map(String) : [],
        ),
        selected:null, deletion:null, busy:false, requestToken:0,
        initialRefresh:true, attribution:null, attributionButton:null,
    };
    const root = element("div", "h3cm-root");
    const head = element("div", "h3cm-head");
    const title = element("div", "h3cm-title", "Checkpoint Manager");
    const summary = element("div", "h3cm-summary", "Select a saved run");
    head.append(title, summary);
    const runRow = element("div", "h3cm-run-row");
    const runSelect = element("select", "h3cm-run-select");
    const refresh = button("Refresh", "Rescan saved runs and checkpoint revisions", () => void refreshRuns());
    const open = button("Open folder", "Open the selected run folder on the ComfyUI host", () => void openFolder());
    runRow.append(runSelect, refresh, open);
    const chapterTabs = element("div", "h3cm-chapter-tabs");
    const scenes = element("div", "h3cm-scenes");
    const main = element("div", "h3cm-main");
    const branchesPanel = element("section", "h3cm-panel");
    const branchesTitle = element("div", "h3cm-panel-title", "Revision branches");
    branchesTitle.append(element("span", "h3cm-shared-legend", "matching color = same saved clip"));
    const branches = element("div", "h3cm-branches");
    branchesPanel.append(branchesTitle, branches);
    const detail = element("section", "h3cm-panel h3cm-detail");
    const preview = element("video", "h3cm-preview");
    preview.controls = true;
    preview.preload = "metadata";
    const audio = element("audio", "h3cm-audio");
    audio.controls = true;
    audio.preload = "metadata";
    audio.hidden = true;
    const inspector = element("dl", "h3cm-inspector");
    const attributionPanel = element("div", "h3cm-attribution");
    attributionPanel.hidden = true;
    const prompt = element("div", "h3cm-prompt");
    detail.append(preview, audio, attributionPanel, inspector, prompt);
    main.append(branchesPanel, detail);
    const deletion = element("section", "h3cm-delete");
    const deletionTitle = element("div", "h3cm-delete-title", "Select a checkpoint revision.");
    const deletionBody = element("div");
    const deletionActions = element("div", "h3cm-delete-actions");
    const status = element("div", "h3cm-status");
    const load = button("Load selected branch", "Restore this revision and its chapter lineage into the connected Plan", () => void loadSelected());
    const activate = button("Make branch active", "Promote this revision inside its chapter without changing other chapters", () => void activateSelected());
    const remove = button("Delete selected revision", "Delete an inactive leaf or roll back the active branch tip after confirmation", () => void deleteSelected(), "h3cm-delete-button");
    load.disabled = true;
    activate.disabled = true;
    remove.disabled = true;
    deletionActions.append(load, activate, status, remove);
    deletion.append(deletionTitle, deletionBody, deletionActions);
    root.append(head, runRow, chapterTabs, scenes, main, deletion);

    function activePlanRun() {
        const plan = upstreamPlanNode(node);
        return String(widget(plan, "run_name")?.value ?? "").trim();
    }

    function persistSelection() {
        const previousRun = node.properties[RUN_PROPERTY];
        const previousScene = node.properties[SCENE_PROPERTY];
        const previousRevision = node.properties[REVISION_PROPERTY];
        const previousChapter = node.properties[CHAPTER_PROPERTY];
        node.properties[RUN_PROPERTY] = state.runName;
        node.properties[SCENE_PROPERTY] = state.scene;
        node.properties[REVISION_PROPERTY] = state.revision;
        node.properties[CHAPTER_PROPERTY] = state.chapterTab;
        let changed = previousRun !== state.runName ||
            previousScene !== state.scene ||
            previousRevision !== state.revision ||
            previousChapter !== state.chapterTab;
        if (selectionWidget) {
            const value = checkpointSelectionJson(
                state.payload, state.runName, state.selected,
                selectedChapterRange());
            if (selectionWidget.value !== value) {
                selectionWidget.value = value;
                selectionWidget.callback?.(value);
                changed = true;
            }
        }
        if (changed) node.graph?.setDirtyCanvas?.(true, true);
    }

    function setBusy(value, message = "") {
        state.busy = Boolean(value);
        runSelect.disabled = state.busy;
        refresh.disabled = state.busy;
        open.disabled = state.busy || !state.runName;
        load.disabled = state.busy || Boolean(state.attribution) || !canLoadSelected();
        activate.disabled = state.busy || Boolean(state.attribution) || !canActivateSelected();
        remove.disabled = state.busy || Boolean(state.attribution) || !state.deletion?.allowed;
        if (state.attributionButton) state.attributionButton.disabled = state.busy;
        if (message) status.textContent = message;
    }

    function selectedLineage() {
        return checkpointRevisionLineage(
            state.payload, state.selected, selectedChapterRange());
    }

    function canLoadSelected() {
        const lineage = selectedLineage();
        const scope = selectedChapterRange();
        return Boolean(state.selected?.ready &&
            lineage.length === Number(state.selected.scene) - scope.start + 1);
    }

    function canActivateSelected() {
        if (!canLoadSelected()) return false;
        return selectedLineage().some((selection) => {
            const revision = selectedCheckpointRevision(
                state.payload, selection.scene, selection.revision);
            return !revision?.active;
        });
    }

    function selectRevision(record, requestDeletion = true) {
        state.attribution = null;
        state.selected = record;
        state.scene = record ? Number(record.scene) : null;
        state.revision = record ? String(record.revision) : "";
        state.deletion = null;
        persistSelection();
        render();
        if (record && requestDeletion) void refreshDeletionPreview();
    }

    function selectAttribution(parent, slot) {
        const candidates = slot?.candidates ?? [];
        if (!parent || !candidates.length) return;
        state.selected = parent;
        state.scene = Number(parent.scene);
        state.revision = String(parent.revision);
        state.attribution = {
            parent,
            scene:Number(slot.scene),
            candidates,
            candidate:candidates[0],
        };
        persistSelection();
        render();
    }

    function chapterRanges() {
        const chapters = Array.isArray(state.payload?.editorial?.chapters)
            ? state.payload.editorial.chapters : [];
        const ordered = chapters.slice().sort(
            (left, right) => Number(left.start_scene) - Number(right.start_scene),
        );
        const maximum = Math.max(
            0,
            ...(state.payload?.scenes ?? []).map((scene) => Number(scene.scene) || 0),
            ...(state.payload?.editorial?.scene_order ?? []).map(
                (scene) => Number(scene.scene) || 0,
            ),
        );
        const ranges = ordered.map((chapter, index) => ({
            id:String(chapter.id),
            title:String(chapter.title || `Chapter ${index + 1}`),
            text:String(chapter.text || ""),
            start:Number(chapter.start_scene),
            end:index + 1 < ordered.length
                ? Number(ordered[index + 1].start_scene) - 1 : maximum,
        })).filter((chapter) => Number.isFinite(chapter.start) && chapter.start > 0);
        if (ranges.length && ranges[0].start > 1) {
            ranges.unshift({id:"unassigned", title:"Unassigned", text:"", start:1, end:ranges[0].start - 1});
        }
        return ranges;
    }

    function activeChapterRange() {
        if (state.chapterTab === "all") return null;
        return chapterRanges().find((chapter) => chapter.id === state.chapterTab) ?? null;
    }

    function selectedChapterRange() {
        const scene = Number(state.selected?.scene);
        const ranges = chapterRanges();
        const selected = ranges.find((range) =>
            scene >= range.start && scene <= range.end);
        if (selected) return selected;
        const maximum = Math.max(
            1,
            ...(state.payload?.scenes ?? []).map(
                (item) => Number(item.scene) || 0),
        );
        return {id:"all", title:"All scenes", text:"", start:1, end:maximum};
    }

    function sceneVisible(scene) {
        const range = activeChapterRange();
        const number = Number(scene);
        return !range || (number >= range.start && number <= range.end);
    }

    function chapterCollapseKey(range) {
        return `${state.runName}:${String(range.id)}`;
    }

    function setChapterCollapsed(range, collapsed) {
        const key = chapterCollapseKey(range);
        if (collapsed) state.collapsedChapters.add(key);
        else state.collapsedChapters.delete(key);
        node.properties[COLLAPSED_CHAPTERS_PROPERTY] = [
            ...state.collapsedChapters,
        ].sort();
        node.graph?.setDirtyCanvas?.(true, true);
        renderBranches();
    }

    function selectChapterTab(chapterId) {
        state.chapterTab = chapterId;
        const visibleScenes = (state.payload?.scenes ?? []).filter(
            (scene) => sceneVisible(scene.scene),
        );
        if (!sceneVisible(state.selected?.scene) && visibleScenes.length) {
            const scene = visibleScenes.at(-1);
            state.selected = selectedCheckpointRevision(state.payload, scene.scene);
            state.scene = Number(state.selected?.scene ?? scene.scene);
            state.revision = String(state.selected?.revision ?? "");
            state.deletion = null;
        }
        persistSelection();
        render();
        if (state.selected) void refreshDeletionPreview();
    }

    function renderChapterTabs() {
        chapterTabs.replaceChildren();
        const ranges = chapterRanges();
        chapterTabs.hidden = !ranges.length;
        if (!ranges.length) {
            state.chapterTab = "all";
            return;
        }
        const valid = new Set(["all", ...ranges.map((chapter) => chapter.id)]);
        if (!valid.has(state.chapterTab)) state.chapterTab = "all";
        const tabs = [{id:"all", title:"All scenes", text:""}, ...ranges];
        for (const chapter of tabs) {
            const item = button(
                chapter.title,
                chapter.text || (chapter.id === "all"
                    ? "Show every saved scene" : `Show scenes ${chapter.start}–${chapter.end}`),
                () => selectChapterTab(chapter.id),
                "h3cm-chapter-tab",
            );
            if (chapter.id === state.chapterTab) {
                item.classList.add("h3cm-chapter-selected");
            }
            chapterTabs.append(item);
        }
    }

    function renderScenes() {
        scenes.replaceChildren();
        for (const scene of state.payload?.scenes ?? []) {
            if (!sceneVisible(scene.scene)) continue;
            const label = `${scene.scene} · ${scene.scene_id} · ${scene.revision_count} take${scene.revision_count === 1 ? "" : "s"}`;
            const item = button(label, `${formatCheckpointBytes(scene.bytes)} saved for this scene`, () => {
                selectRevision(selectedCheckpointRevision(state.payload, scene.scene));
            }, "h3cm-scene");
            if (Number(scene.scene) === Number(state.scene)) item.classList.add("h3cm-scene-selected");
            scenes.append(item);
        }
    }

    function renderBranchRows(container, rows) {
        const occurrences = new Map();
        for (const branch of rows) {
            for (const revision of branch.revisions) {
                const key = checkpointRevisionKey(revision.scene, revision.revision);
                occurrences.set(key, (occurrences.get(key) ?? 0) + 1);
            }
        }
        for (const branch of rows) {
            const row = element("div", "h3cm-branch");
            const header = element("div", "h3cm-branch-head");
            const tip = branch.revisions.at(-1) ?? null;
            const selectedTip = Boolean(tip &&
                Number(state.selected?.scene) === Number(tip.scene) &&
                String(state.selected?.revision) === String(tip.revision));
            if (selectedTip) row.classList.add("h3cm-branch-selected");
            if (tip) {
                header.role = "button";
                header.tabIndex = 0;
                header.title = `Select this branch through scene ${tip.scene}`;
                header.addEventListener("click", () => selectRevision(tip));
                header.addEventListener("keydown", (event) => {
                    if (event.key !== "Enter" && event.key !== " ") return;
                    event.preventDefault();
                    selectRevision(tip);
                });
            }
            const name = element("span", branch.active ? "h3cm-branch-active" : "", branch.label);
            const count = element("span", "h3cm-muted", `${branch.revisions.length} visible scene${branch.revisions.length === 1 ? "" : "s"}`);
            header.append(name, count);
            const path = element("div", "h3cm-branch-path");
            branch.revisions.forEach((revision, index) => {
                if (index) path.append(element("span", "h3cm-arrow", "→"));
                const key = checkpointRevisionKey(revision.scene, revision.revision);
                const sharedCount = occurrences.get(key) ?? 1;
                const card = button(
                    `S${revision.scene} · ${revision.revision.slice(0, 8)}`,
                    revision.prompt_preview || revision.scene_id,
                    () => selectRevision(revision), "h3cm-revision",
                );
                const selected = state.selected?.scene === revision.scene &&
                    state.selected?.revision === revision.revision;
                if (sharedCount > 1) {
                    card.classList.add("h3cm-revision-shared");
                    card.dataset.sharedKey = key;
                    card.style.setProperty("--h3cm-shared-color", sharedColor(key));
                    card.append(element(
                        "span", "h3cm-shared-label",
                        `shared ×${sharedCount}`,
                    ));
                }
                card.append(element("small", "", `${selected ? "selected · " : ""}${revision.active ? "saved active" : "saved inactive"}${revision.ready ? "" : " · broken"}`));
                if (selected) {
                    card.classList.add("h3cm-revision-selected");
                }
                path.append(card);
            });
            const slot = branch.attribution_slot;
            if (slot?.candidates?.length && tip && sceneVisible(slot.scene)) {
                path.append(element("span", "h3cm-arrow", "→"));
                const count = slot.candidates.length;
                const empty = button(
                    `S${slot.scene} · empty`,
                    `${count} independent saved candidate${count === 1 ? "" : "s"} can be attributed here`,
                    () => selectAttribution(tip, slot),
                    "h3cm-revision h3cm-revision-empty",
                );
                empty.append(element(
                    "small", "", `${count} attributable candidate${count === 1 ? "" : "s"}`,
                ));
                if (state.attribution &&
                        state.attribution.parent.revision === tip.revision) {
                    empty.classList.add("h3cm-revision-empty-selected");
                }
                path.append(empty);
            }
            row.append(header, path);
            container.append(row);
        }
    }

    function renderBranches() {
        branches.replaceChildren();
        const ranges = chapterRanges();
        if (!ranges.length) {
            const rows = checkpointBranchRows(state.payload);
            if (rows.length) renderBranchRows(branches, rows);
            else branches.append(element(
                "div", "h3cm-muted", "No versioned checkpoints were found.",
            ));
            return;
        }
        const visibleRanges = state.chapterTab === "all"
            ? ranges : ranges.filter((range) => range.id === state.chapterTab);
        let rendered = 0;
        for (const range of visibleRanges) {
            const rows = checkpointChapterBranchRows(state.payload, range);
            if (!rows.length) continue;
            if (state.chapterTab === "all") {
                const section = element("section", "h3cm-branch-chapter");
                const collapseKey = chapterCollapseKey(range);
                const collapsed = state.collapsedChapters.has(collapseKey);
                section.classList.toggle(
                    "h3cm-branch-chapter-collapsed", collapsed);
                const heading = button(
                    "",
                    `${collapsed ? "Expand" : "Collapse"} ${range.title}`,
                    () => setChapterCollapsed(range, !collapsed),
                    "h3cm-branch-chapter-title",
                );
                heading.setAttribute("aria-expanded", String(!collapsed));
                heading.append(
                    element("span", "h3cm-branch-chapter-caret", collapsed ? "▸" : "▾"),
                    element("span", "", range.title),
                    element("span", "h3cm-muted", `Scenes ${range.start}–${range.end}`),
                );
                const body = element("div", "h3cm-branch-chapter-body");
                body.hidden = collapsed;
                if (!collapsed) renderBranchRows(body, rows);
                section.append(heading, body);
                branches.append(section);
            } else renderBranchRows(branches, rows);
            rendered += rows.length;
        }
        if (!rendered) {
            branches.append(element(
                "div", "h3cm-muted", "No versioned checkpoints were found in this chapter.",
            ));
        }
    }

    function addInspector(label, value) {
        inspector.append(element("dt", "", label), element("dd", "", value));
    }

    function renderDetail() {
        inspector.replaceChildren();
        attributionPanel.replaceChildren();
        attributionPanel.hidden = !state.attribution;
        state.attributionButton = null;
        const record = state.attribution?.candidate ?? state.selected;
        if (!record) {
            preview.removeAttribute("src");
            delete preview.dataset.source;
            preview.load();
            audio.hidden = true;
            audio.removeAttribute("src");
            delete audio.dataset.source;
            prompt.textContent = "Select a revision from the branch graph.";
            return;
        }
        if (state.attribution) {
            const attribution = state.attribution;
            attributionPanel.append(element(
                "div", "h3cm-attribution-title",
                `Attribute an existing scene ${attribution.scene} candidate to branch ${attribution.parent.revision.slice(0, 8)}`,
            ));
            const candidates = element("div", "h3cm-attribution-candidates");
            for (const candidate of attribution.candidates) {
                const choice = button(
                    `${candidate.revision.slice(0, 8)} · seed ${candidate.seed || "?"}`,
                    candidate.prompt_preview || candidate.scene_id,
                    () => {
                        attribution.candidate = candidate;
                        renderDetail();
                    },
                );
                if (candidate.revision === record.revision) {
                    choice.classList.add("h3cm-attribution-candidate-selected");
                }
                candidates.append(choice);
            }
            const attach = button(
                "Attach selected candidate",
                "Create a metadata-only lineage link; saved media and checkpoint files remain shared",
                () => void attributeCandidate(),
            );
            attach.disabled = state.busy;
            state.attributionButton = attach;
            attributionPanel.append(
                candidates,
                element("div", "h3cm-muted",
                    "This candidate uses no predecessor video or generated-audio context. Attribution creates a new lineage link without regeneration or media duplication."),
                attach,
            );
        }
        const media = record.preview_video ?? record.video;
        const nextVideo = videoUrl(media);
        if (nextVideo && preview.dataset.source !== nextVideo) {
            preview.src = nextVideo;
            preview.dataset.source = nextVideo;
            preview.load();
        } else if (!nextVideo) {
            preview.removeAttribute("src");
            delete preview.dataset.source;
            preview.load();
        }
        const audioUrl = videoUrl(record.audio);
        audio.hidden = !audioUrl;
        if (audioUrl && audio.dataset.source !== audioUrl) {
            audio.src = audioUrl;
            audio.dataset.source = audioUrl;
            audio.load();
        } else if (!audioUrl) {
            audio.removeAttribute("src");
            delete audio.dataset.source;
        }
        addInspector("Identity", `${state.attribution ? "Candidate " : ""}Scene ${record.scene} · ${record.scene_id} · ${record.revision}`);
        addInspector("State", `${record.active ? "Active" : "Inactive"} · ${record.ready ? "Ready" : "Broken"}`);
        addInspector("Branches", (record.branches ?? []).map((item) => item.label).join(", ") || "Unresolved lineage");
        addInspector("Created", localTime(record.created_at));
        addInspector("Frames", `${record.raw_frames} raw · ${record.delivered_frames} delivered`);
        addInspector("Sampling", `seed ${record.seed || "unknown"} · ${record.steps || "?"} steps`);
        addInspector("Incoming", `${record.continuation_mode} · Video ${record.context_length}f · Audio ${record.audio_context_length}f`);
        addInspector("Parent", state.attribution
            ? `Will become Scene ${state.attribution.parent.scene} · ${state.attribution.parent.revision.slice(0, 8)}`
            : record.parent ? `Scene ${record.parent.scene} · ${record.parent.revision.slice(0, 8)}` : record.lineage_status);
        addInspector("Following", (record.children ?? []).length
            ? record.children.map(checkpointDependencyText).join(" · ") : "No dependent revision");
        addInspector("Storage", `${formatCheckpointBytes(record.size_bytes)}` +
            `${record.shared_size_bytes ? ` · ${formatCheckpointBytes(record.shared_size_bytes)} shared` : ""}` +
            ` · ${(record.missing_files ?? []).length ? `missing ${record.missing_files.join(", ")}` : "complete"}`);
        const compatibility = record.compatibility ?? {};
        addInspector("Canvas", compatibility.width && compatibility.height
            ? `${compatibility.width}×${compatibility.height} @ ${compatibility.fps ?? 24} fps` : "Unknown");
        addInspector("Audio mode", compatibility.audio_mode ?? "Unknown");
        addInspector("Encoding", [compatibility.encode_mode, compatibility.anchor_mode,
            compatibility.crop].filter(Boolean).join(" · ") || "Unknown");
        addInspector("Metadata", record.metadata_path ?? "Unknown");
        prompt.textContent = record.prompt || record.prompt_preview || "No saved scene prompt.";
    }

    function renderDeletion() {
        deletionBody.replaceChildren();
        deletion.classList.toggle("h3cm-delete-blocked", Boolean(state.deletion && !state.deletion.allowed));
        deletionTitle.textContent = checkpointDeletionTitle(state.deletion);
        load.disabled = state.busy || !canLoadSelected();
        activate.disabled = state.busy || !canActivateSelected();
        remove.disabled = state.busy || !state.deletion?.allowed;
        if (state.attribution) {
            load.disabled = true;
            activate.disabled = true;
            remove.disabled = true;
        }
        if (!state.deletion) return;
        const files = (state.deletion.files ?? []).filter((item) => item.exists);
        if (files.length) {
            const list = element("ul", "h3cm-files");
            for (const file of files) {
                list.append(element("li", file.shared ? "h3cm-muted" : "",
                    `${file.label} · ${formatCheckpointBytes(file.size_bytes)} · ${file.path}` +
                    `${file.shared ? " · shared, kept" : ""}`));
            }
            deletionBody.append(list);
        }
        if (state.deletion.dependents?.length) {
            const heading = element("div", "h3cm-error", "Delete dependent leaves first:");
            const list = element("ul", "h3cm-dependents");
            for (const dependent of state.deletion.dependents) {
                const action = dependent.leaf
                    ? (dependent.active
                        ? " · active tip: select to roll back"
                        : " · leaf: delete this first")
                    : "";
                const item = element("li", "h3cm-dependent",
                    `${checkpointDependencyText(dependent)}${action}`);
                item.title = dependent.leaf && !dependent.active
                    ? "Select this deletable leaf checkpoint"
                    : dependent.leaf
                        ? "Select this active branch tip to inspect its rollback"
                        : "Select this dependent checkpoint to inspect its own descendants";
                item.addEventListener("click", () => {
                    const revision = selectedCheckpointRevision(
                        state.payload, dependent.scene, dependent.revision);
                    if (revision) selectRevision(revision);
                });
                list.append(item);
            }
            deletionBody.append(heading, list);
        }
        if (state.deletion.not_deleted?.length) {
            const kept = element("details", "h3cm-muted");
            kept.append(element("summary", "", "Always kept by this deletion"));
            const list = element("ul", "h3cm-files");
            for (const label of state.deletion.not_deleted) {
                list.append(element("li", "", label));
            }
            kept.append(list);
            deletionBody.append(kept);
        }
    }

    function render() {
        const total = state.payload?.summary;
        summary.textContent = total
            ? `${total.scene_count} scenes · ${total.revision_count} revisions · ${total.branch_count} branches · ${formatCheckpointBytes(total.bytes)}`
            : "Select a saved run";
        renderChapterTabs();
        renderScenes();
        renderBranches();
        renderDetail();
        renderDeletion();
    }

    async function refreshDeletionPreview() {
        const record = state.selected;
        const token = ++state.requestToken;
        if (!record || !state.runName) return;
        deletionTitle.textContent = "Inspecting owned files and dependencies…";
        remove.disabled = true;
        try {
            const payload = await jsonRequest(
                "/minimax_h3_context_loop/checkpoint-revisions/delete-preview", {
                    method:"POST", headers:{"Content-Type":"application/json"},
                    body:JSON.stringify({run_name:state.runName, scene:record.scene, revision:record.revision}),
                });
            if (token !== state.requestToken) return;
            state.deletion = payload;
        } catch (error) {
            if (token !== state.requestToken) return;
            state.deletion = null;
            status.className = "h3cm-status h3cm-error";
            status.textContent = error.message;
        }
        renderDeletion();
    }

    async function refreshCheckpoints() {
        if (!state.runName) {
            state.payload = null;
            selectRevision(null, false);
            return;
        }
        setBusy(true, "Scanning checkpoint metadata…");
        try {
            const query = new URLSearchParams({
                run_name:state.runName,
                cache_bust:String(Date.now()),
            });
            state.payload = await jsonRequest(
                `/minimax_h3_context_loop/checkpoints?${query}`,
                {cache:"no-store"},
            );
            let selected = selectedCheckpointRevision(
                state.payload, state.scene, state.revision);
            if (state.initialRefresh) {
                const activeTip = selectedCheckpointRevision(state.payload);
                if (checkpointRevisionLineage(
                        state.payload, activeTip).length >
                        checkpointRevisionLineage(
                            state.payload, selected).length) {
                    selected = activeTip;
                }
                state.initialRefresh = false;
            }
            status.className = "h3cm-status";
            status.textContent = state.payload.summary?.broken_count
                ? `${state.payload.summary.broken_count} broken revision${state.payload.summary.broken_count === 1 ? "" : "s"} found`
                : "Checkpoint graph is current";
            selectRevision(selected, false);
            if (selected) void refreshDeletionPreview();
        } catch (error) {
            state.payload = null;
            state.selected = null;
            state.deletion = null;
            status.className = "h3cm-status h3cm-error";
            status.textContent = error.message;
            render();
        } finally {
            setBusy(false);
        }
    }

    async function refreshRuns() {
        setBusy(true, "Scanning output/h3_chains…");
        try {
            const payload = await jsonRequest("/minimax_h3_context_loop/runs");
            state.runs = payload.runs ?? [];
            const connected = activePlanRun();
            const preferred = state.runName || connected;
            state.runName = state.runs.some((item) => item.run_name === preferred)
                ? preferred : state.runs[0]?.run_name ?? "";
            runSelect.replaceChildren();
            for (const run of state.runs) {
                const option = element("option", "", `${run.run_name} · ${run.checkpoint_count} active checkpoints`);
                option.value = run.run_name;
                runSelect.append(option);
            }
            runSelect.value = state.runName;
            persistSelection();
        } catch (error) {
            state.runs = [];
            state.runName = "";
            runSelect.replaceChildren();
            status.className = "h3cm-status h3cm-error";
            status.textContent = error.message;
        } finally {
            setBusy(false);
        }
        await refreshCheckpoints();
    }

    async function openFolder() {
        if (!state.runName) return;
        setBusy(true, "Opening run folder…");
        try {
            const payload = await jsonRequest("/minimax_h3_context_loop/open-run-folder", {
                method:"POST", headers:{"Content-Type":"application/json"},
                body:JSON.stringify({run_name:state.runName}),
            });
            status.textContent = payload.opened ? "Opened on ComfyUI host" : payload.path;
        } catch (error) {
            status.className = "h3cm-status h3cm-error";
            status.textContent = error.message;
        } finally {
            setBusy(false);
        }
    }

    function restoreSavedPlanInputs(inputs, policyInputs = {}) {
        const planNode = upstreamPlanNode(node);
        if (!planNode || !inputs || typeof inputs !== "object") {
            throw new Error("The saved run has no Plan inputs to restore.");
        }
        const names = Object.keys(inputs).sort((left, right) =>
            Number(left === "plan_json") - Number(right === "plan_json"));
        const graph = planNode.graph ?? app.graph;
        const applied = [];
        graph?.beforeChange?.();
        try {
            for (const name of names) {
                const target = widget(planNode, name);
                if (!target) continue;
                target.value = inputs[name];
                target.callback?.(inputs[name]);
                applied.push(name);
            }
        } finally {
            graph?.afterChange?.();
        }
        if (!applied.includes("plan_json")) {
            throw new Error("The connected Plan does not expose an editable plan_json widget.");
        }
        restoreConnectedPolicyInputs(planNode, policyInputs);
        refreshRestoredPlanEditors(planNode);
        app.graph?.setDirtyCanvas?.(true, true);
        return planNode;
    }

    function applyLoadedRevisions(planNode, revisions) {
        const target = widget(planNode, "plan_json");
        if (!target) throw new Error("The connected Plan has no plan_json control.");
        const plan = applyCheckpointRevisionSet(
            parsePlanJson(String(target.value ?? "")), revisions,
        );
        const value = planToJson(plan);
        target.value = value;
        target.callback?.(value);
        refreshRestoredPlanEditors(planNode);
        planNode.graph?.setDirtyCanvas?.(true, true);
        for (const revision of revisions ?? []) {
            const sceneIndex = Number(revision.scene) - 1;
            if (sceneIndex < 0 || sceneIndex >= plan.shots.length) continue;
            publishCompanionPrompt(
                node, planNode, sceneIndex,
                promptValueToText(plan.shots[sceneIndex]?.prompt),
            );
        }
        return plan;
    }

    function applyActivatedRevisions(planNode, revisions) {
        const target = widget(planNode, "plan_json");
        if (!target) return false;
        const plan = applyCheckpointRevisionSet(
            parsePlanJson(String(target.value ?? "")), revisions, {
                useEffectivePrompts: true,
                useTipSharedPrompt: true,
            },
        );
        const value = planToJson(plan);
        target.value = value;
        target.callback?.(value);
        refreshRestoredPlanEditors(planNode);
        planNode.graph?.setDirtyCanvas?.(true, true);
        for (const revision of revisions ?? []) {
            const sceneIndex = Number(revision.scene) - 1;
            if (sceneIndex < 0 || sceneIndex >= plan.shots.length) continue;
            publishCompanionPrompt(
                node, planNode, sceneIndex,
                promptValueToText(plan.shots[sceneIndex]?.prompt),
            );
        }
        return true;
    }

    function prepareResume(scene) {
        const start = connectedNode(node, START_NAME);
        const startClip = widget(start, "start_clip");
        if (!startClip) return false;
        startClip.value = scene;
        startClip.callback?.(scene);
        const range = widget(start, "scene_range");
        if (range) {
            range.value = "";
            range.callback?.("");
        }
        start.graph?.setDirtyCanvas?.(true, true);
        return true;
    }

    async function attributeCandidate() {
        const attribution = state.attribution;
        const candidate = attribution?.candidate;
        const parent = attribution?.parent;
        if (!candidate || !parent || state.busy) return;
        const confirmed = window.confirm(
            `Attribute scene ${candidate.scene} candidate ${candidate.revision.slice(0, 8)} after scene ${parent.scene} revision ${parent.revision.slice(0, 8)}?\n\n` +
            "The candidate has no predecessor video or generated-audio dependency. A new immutable lineage record will be created; its existing video, audio, prompt, and checkpoint files remain shared. Nothing is regenerated or copied.",
        );
        if (!confirmed) return;
        setBusy(true, "Attributing saved candidate to branch…");
        try {
            const payload = await jsonRequest(
                "/minimax_h3_context_loop/checkpoint-revisions/attribute", {
                    method:"POST", headers:{"Content-Type":"application/json"},
                    body:JSON.stringify({
                        run_name:state.runName,
                        parent_scene:parent.scene,
                        parent_revision:parent.revision,
                        candidate_scene:candidate.scene,
                        candidate_revision:candidate.revision,
                    }),
                });
            state.attribution = null;
            state.scene = Number(payload.scene);
            state.revision = String(payload.revision);
            await refreshCheckpoints();
            status.className = "h3cm-status";
            status.textContent = payload.message;
        } catch (error) {
            status.className = "h3cm-status h3cm-error";
            status.textContent = error.message;
        } finally {
            setBusy(false);
        }
    }

    async function loadSelected() {
        const record = state.selected;
        const lineage = selectedLineage();
        const scope = selectedChapterRange();
        if (!record || !canLoadSelected() || state.busy) return;
        const planNode = upstreamPlanNode(node);
        if (!planNode || !widget(planNode, "plan_json")) {
            status.className = "h3cm-status h3cm-error";
            status.textContent = "Connect the Checkpoint Manager to an editable H3 Chain Plan first.";
            return;
        }
        const confirmed = window.confirm(
            `Load ${state.runName} through scene ${record.scene} revision ${record.revision.slice(0, 8)}?\n\n` +
            `${scope.title} scenes ${scope.start}–${scope.end} will use this branch. Other chapters keep their active checkpoint branches. Saved revision files are kept.`,
        );
        if (!confirmed) return;
        setBusy(true, "Loading saved Plan and checkpoint lineage…");
        try {
            const runQuery = new URLSearchParams({
                run_name: state.runName,
                include_assets: "false",
            });
            const runBody = await jsonRequest(
                `/minimax_h3_context_loop/run?${runQuery.toString()}`,
            );
            const sameConnectedRun = activePlanRun() === state.runName;
            const savedPlan = parsePlanJson(String(sameConnectedRun
                ? widget(planNode, "plan_json")?.value ?? ""
                : runBody.plan_inputs?.plan_json ?? ""));
            const chapters = state.payload?.editorial?.chapters ?? [];
            if (chapters.length) {
                savedPlan.chapters = chapters.map((chapter) => ({
                    id:chapter.id,
                    title:chapter.title,
                    start_scene_id:chapter.start_scene_id,
                    text:chapter.text ?? "",
                }));
            }
            if (savedPlan.shots.length < Number(record.scene)) {
                throw new Error(
                    `The saved Plan has only ${savedPlan.shots.length} scenes.`,
                );
            }
            const resumeScene = Number(record.scene) + 1;
            if (resumeScene <= savedPlan.shots.length &&
                    !widget(connectedNode(node, START_NAME), "start_clip")) {
                throw new Error("Could not find the connected H3 Chain Loop Start node.");
            }
            const restored = await jsonRequest(
                "/minimax_h3_context_loop/checkpoint-revisions/restore", {
                    method:"POST", headers:{"Content-Type":"application/json"},
                    body:JSON.stringify({
                        run_name:state.runName,
                        resume_scene:resumeScene,
                        revisions:lineage,
                        scope_start_scene:scope.start,
                        scope_end_scene:scope.end,
                    }),
                });
            const activePlan = sameConnectedRun ? planNode
                : restoreSavedPlanInputs(
                    {...runBody.plan_inputs, plan_json:planToJson(savedPlan)},
                    restored.policy_inputs ?? runBody.policy_inputs,
                );
            const plan = applyLoadedRevisions(activePlan, restored.restored ?? []);
            const canResume = resumeScene <= plan.shots.length &&
                resumeScene <= scope.end;
            if (canResume && !prepareResume(resumeScene)) {
                throw new Error("Loaded the branch, but could not arm H3 Chain Loop Start.");
            }
            await refreshCheckpoints();
            status.className = "h3cm-status";
            status.textContent = canResume
                ? `Loaded ${scope.title} scenes ${scope.start}–${record.scene}; Loop Start is armed for scene ${resumeScene}.`
                : `Loaded ${scope.title} through scene ${record.scene}; other chapters were preserved.`;
        } catch (error) {
            status.className = "h3cm-status h3cm-error";
            status.textContent = error.message;
        } finally {
            setBusy(false);
        }
    }

    async function activateSelected() {
        const record = state.selected;
        const lineage = selectedLineage();
        const scope = selectedChapterRange();
        if (!record || !canActivateSelected() || state.busy) return;
        const confirmed = window.confirm(
            `Make ${scope.title} active through scene ${record.scene} revision ${record.revision.slice(0, 8)}?\n\n` +
            `Only scenes ${scope.start}–${scope.end} are affected. Other chapters keep their active branches. If a Plan is connected, the selected chapter's saved scene settings are restored. No saved revision, workflow, reference, or assembled video is deleted.`,
        );
        if (!confirmed) return;
        setBusy(true, "Promoting selected checkpoint lineage…");
        try {
            const payload = await jsonRequest(
                "/minimax_h3_context_loop/checkpoint-revisions/restore", {
                    method:"POST", headers:{"Content-Type":"application/json"},
                    body:JSON.stringify({
                        run_name:state.runName,
                        resume_scene:Number(record.scene) + 1,
                        revisions:lineage,
                        activate_only:true,
                        scope_start_scene:scope.start,
                        scope_end_scene:scope.end,
                    }),
                });
            const planNode = upstreamPlanNode(node);
            const planUpdated = Boolean(planNode &&
                applyActivatedRevisions(planNode, payload.restored ?? []));
            await refreshCheckpoints();
            status.className = "h3cm-status";
            status.textContent = `${scope.title} scene ${record.scene} revision ${record.revision.slice(0, 8)} is now its active branch tip. ` +
                `${payload.retired_scope_pointers || 0} later pointer${payload.retired_scope_pointers === 1 ? " was" : "s were"} cleared inside this chapter; other chapters were preserved; all immutable revisions were kept` +
                `${planUpdated ? "; connected Plan scene settings were restored." : "."}`;
        } catch (error) {
            status.className = "h3cm-status h3cm-error";
            status.textContent = error.message;
        } finally {
            setBusy(false);
        }
    }

    async function deleteSelected() {
        const record = state.selected;
        const plan = state.deletion;
        if (!record || !plan?.allowed || state.busy) return;
        const confirmed = window.confirm(
            `${plan.rollback ? "Roll back and permanently delete" : "Permanently delete"} scene ${record.scene} revision ${record.revision.slice(0, 8)}?\n\n` +
            `${plan.owned_file_count} owned files · ${formatCheckpointBytes(plan.reclaimed_bytes)}\n` +
            `${plan.rollback ? (plan.rollback_to_scene > 0
                ? `The active chain will roll back through scene ${plan.rollback_to_scene}. `
                : "The run will have no active checkpoint scenes. ") : ""}` +
            "Run archives, references, prompt history, and assembled exports are kept. This cannot be undone.",
        );
        if (!confirmed) return;
        setBusy(true, "Deleting staged revision files…");
        try {
            const payload = await jsonRequest(
                "/minimax_h3_context_loop/checkpoint-revisions/delete", {
                    method:"POST", headers:{"Content-Type":"application/json"},
                    body:JSON.stringify({run_name:state.runName, scene:record.scene,
                        revision:record.revision, snapshot:plan.snapshot}),
                });
            state.scene = payload.rollback ? payload.rollback_to_scene : state.scene;
            state.revision = "";
            await refreshCheckpoints();
            status.className = "h3cm-status";
            status.textContent = `${payload.message} Reclaimed ${formatCheckpointBytes(payload.reclaimed_bytes)}.`;
        } catch (error) {
            state.deletion = error.payload?.preview ?? state.deletion;
            status.className = "h3cm-status h3cm-error";
            status.textContent = error.message;
            renderDeletion();
        } finally {
            setBusy(false);
        }
    }

    runSelect.addEventListener("change", () => {
        state.runName = runSelect.value;
        state.scene = null;
        state.revision = "";
        persistSelection();
        void refreshCheckpoints();
    });

    const domWidget = node.addDOMWidget("h3_checkpoint_manager", "h3-checkpoint-manager", root, {
        serialize:false, hideOnZoom:false, getMinHeight:() => 620,
    });
    domWidget.serialize = false;
    node.setSize?.([
        Math.max(Number(node.size?.[0]) || 0, 900),
        Math.max(Number(node.size?.[1]) || 0, 760),
    ]);
    const connectionsChanged = node.onConnectionsChange;
    node.onConnectionsChange = function () {
        const result = connectionsChanged?.apply(this, arguments);
        window.setTimeout(() => {
            const connected = activePlanRun();
            if (connected && connected !== state.runName) {
                state.runName = connected;
                void refreshRuns();
            }
        }, 0);
        return result;
    };
    node._h3CheckpointManagerRefresh = () => void refreshRuns();
    const removed = node.onRemoved;
    node.onRemoved = function () {
        return removed?.apply(this, arguments);
    };
    void refreshRuns();
}

app.registerExtension({
    name:"minimax_h3_context_loop.checkpoint_manager",
    async beforeRegisterNodeDef(nodeTypeClass, nodeData) {
        if (nodeData.name !== NODE_NAME) return;
        const created = nodeTypeClass.prototype.onNodeCreated;
        nodeTypeClass.prototype.onNodeCreated = function () {
            const result = created?.apply(this, arguments);
            window.setTimeout(() => mount(this), 0);
            return result;
        };
        const configured = nodeTypeClass.prototype.onConfigure;
        nodeTypeClass.prototype.onConfigure = function () {
            const result = configured?.apply(this, arguments);
            window.setTimeout(() => this._h3CheckpointManagerRefresh?.(), 0);
            return result;
        };
    },
    async nodeCreated(node) {
        if (nodeType(node) === NODE_NAME) mount(node);
    },
});
