import {app} from "/scripts/app.js";
import {api} from "/scripts/api.js";

const NODE_NAME = "MiniMaxH3ProjectAssetManager";
const PLAN_TYPES = new Set([
    "MiniMaxH3ChainPlan", "MiniMaxH3ChainPlanStudio",
]);
const ROLES = {
    image: ["picture", "semantic_anchor"],
    video: ["video", "motion", "source_track"],
    audio: ["audio_reference", "source_track"],
};
const ROLE_LABELS = {
    picture: "picture reference",
    semantic_anchor: "semantic anchor",
    video: "video reference",
    motion: "motion reference",
    audio_reference: "tagged audio reference",
    source_track: "source track",
};

function displayRole(role) {
    return ROLE_LABELS[role] ?? String(role || "").replaceAll("_", " ");
}

function nodeType(node) {
    return node?.comfyClass ?? node?.type ?? "";
}

function widget(node, name) {
    return node?.widgets?.find((item) => item.name === name) ?? null;
}

function partialExecutionId(node) {
    const graph = node?.graph;
    const root = graph?.rootGraph ?? app.graph;
    if (!graph || !root || graph === root || graph.isRootGraph) return String(node.id);
    function pathTo(target, current) {
        for (const candidate of current?.nodes ?? current?._nodes ?? []) {
            const subgraph = candidate?.subgraph;
            if (!subgraph) continue;
            if (subgraph === target) return String(candidate.id);
            const child = pathTo(target, subgraph);
            if (child !== undefined) return `${candidate.id}:${child}`;
        }
        return undefined;
    }
    const parent = pathTo(graph, root);
    if (parent === undefined) {
        throw new Error("Could not resolve this Carousel inside its subgraph.");
    }
    return `${parent}:${node.id}`;
}

function el(tag, className = "", text = null) {
    const item = document.createElement(tag);
    if (className) item.className = className;
    if (text !== null) item.textContent = text;
    return item;
}

function button(label, action, title = "") {
    const item = el("button", "h3pa-button", label);
    item.type = "button";
    item.title = title;
    item.addEventListener("click", action);
    return item;
}

async function jsonRequest(route, options = {}) {
    const response = await api.fetchApi(route, options);
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.error || `${response.status}`);
    return payload;
}

function mediaUrl(project, asset, variant) {
    const query = new URLSearchParams({
        project, asset: String(asset.id), variant,
    });
    return api.apiURL(
        `/minimax_h3_context_loop/project-assets/media?${query}`,
    );
}

function formatBytes(value) {
    let number = Number(value) || 0;
    const units = ["B", "KiB", "MiB", "GiB", "TiB"];
    let index = 0;
    while (number >= 1024 && index < units.length - 1) {
        number /= 1024;
        index += 1;
    }
    return `${number.toFixed(index ? 1 : 0)} ${units[index]}`;
}

function assetDetail(asset) {
    const meta = asset.metadata ?? {};
    const pieces = [asset.kind, formatBytes(asset.size)];
    if (meta.width && meta.height) pieces.push(`${meta.width}×${meta.height}`);
    if (meta.duration_seconds) pieces.push(`${Number(meta.duration_seconds).toFixed(2)}s`);
    if (meta.fps) pieces.push(`${Number(meta.fps).toFixed(3)} fps`);
    if (meta.sample_rate) pieces.push(`${meta.sample_rate} Hz`);
    if (meta.has_audio) pieces.push("embedded audio");
    return pieces.join(" · ");
}

function promptTag(asset) {
    const prefix = asset?.role === "semantic_anchor" ? "#" : "@";
    return `${prefix}${asset?.tag ?? ""}`;
}

function matchesTab(asset, filter) {
    if (filter === "all") return true;
    // Assignment is an orthogonal status. Unresolved templates stay visible
    // in their declared media/role category as well as the Unassigned queue.
    if (filter === "unassigned") return Boolean(asset._unresolved);
    if (filter === "semantic") return asset.role === "semantic_anchor";
    if (filter === "image") return asset.role === "picture";
    if (filter === "video") return ["video", "motion"].includes(asset.role);
    if (filter === "audio") return asset.role === "audio_reference";
    if (filter === "source_track") return asset.role === "source_track";
    return false;
}

function injectStyles() {
    if (document.getElementById("h3-project-assets-style")) return;
    const style = document.createElement("style");
    style.id = "h3-project-assets-style";
    style.textContent = `
        .h3pa-root{box-sizing:border-box;height:100%;min-height:520px;padding:12px;
          display:flex;flex-direction:column;gap:10px;overflow:hidden;color:var(--input-text,#eee);
          background:color-mix(in srgb,var(--comfy-menu-bg,#202124) 92%,#0b1120);font:12px/1.35 system-ui}
        .h3pa-root *{box-sizing:border-box}.h3pa-row{display:flex;gap:7px;align-items:center;min-width:0}
        .h3pa-row input,.h3pa-row select,.h3pa-editor input,.h3pa-editor select,.h3pa-editor textarea{
          min-width:0;padding:6px 8px;border:1px solid var(--border-color,#566174);border-radius:6px;
          background:var(--comfy-input-bg,#151820);color:inherit}.h3pa-project{flex:1;font-weight:650}
        .h3pa-button{padding:6px 9px;border:1px solid var(--border-color,#566174);border-radius:6px;
          background:var(--comfy-input-bg,#20242d);color:inherit;cursor:pointer}.h3pa-button:hover{border-color:#79a9ff}
        .h3pa-status{min-height:18px;color:#9eabc0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
        .h3pa-tabs{display:flex;gap:5px;overflow-x:auto;align-items:center;flex:0 0 auto}.h3pa-tab.active{background:#284d7e;border-color:#70a9ff}
        .h3pa-folder-tools{display:flex;gap:5px;align-items:center;margin-left:auto;padding-left:7px;border-left:1px solid #465064;flex:0 0 auto}.h3pa-folder-tools select{max-width:190px;min-width:110px;padding:6px 8px;border:1px solid var(--border-color,#566174);border-radius:6px;background:var(--comfy-input-bg,#151820);color:inherit}
        .h3pa-stage{flex:1 1 auto;min-height:230px;display:grid;grid-template-columns:minmax(0,1fr) 260px;gap:10px;overflow:hidden}
        .h3pa-preview{position:relative;display:grid;place-items:center;min-width:0;min-height:220px;
          overflow:hidden;border:1px solid var(--border-color,#566174);border-radius:9px;background:#090b10}
        .h3pa-preview>img,.h3pa-preview>video{position:absolute;inset:0;display:block;width:100%;height:100%;
          min-width:0;min-height:0;object-fit:contain}
        .h3pa-preview audio{width:min(94%,650px)}.h3pa-empty{color:#738097;text-align:center;padding:24px}
        .h3pa-editor{display:flex;flex-direction:column;gap:8px;padding:10px;overflow:auto;border:1px solid
          var(--border-color,#566174);border-radius:9px;background:var(--comfy-input-bg,#151820)}
        .h3pa-editor label{display:flex;flex-direction:column;gap:3px;color:#aeb7c8}.h3pa-editor textarea{min-height:62px;resize:vertical}
        .h3pa-editor label.h3pa-toggle,.h3pa-crop-controls label.h3pa-toggle{display:grid;grid-template-columns:18px minmax(0,1fr);gap:8px;align-items:start;
          padding:8px;border:1px solid color-mix(in srgb,var(--border-color,#566174) 72%,transparent);border-radius:7px;
          background:color-mix(in srgb,var(--comfy-input-bg,#151820) 78%,#263247);cursor:pointer}
        .h3pa-editor .h3pa-toggle input,.h3pa-crop-controls .h3pa-toggle input{width:16px;height:16px;min-width:16px;margin:2px 0 0;padding:0;cursor:pointer}
        .h3pa-toggle-copy{display:flex;flex-direction:column;gap:2px;min-width:0}.h3pa-toggle-copy strong{color:inherit}
        .h3pa-toggle-copy small{color:#8f9bb0;font-size:11px;line-height:1.3}
        .h3pa-carousel{display:flex;gap:8px;overflow-x:auto;overflow-y:hidden;padding:4px 1px 7px;min-height:126px}
        .h3pa-card{position:relative;flex:0 0 150px;height:112px;padding:0;border:1px solid #495466;border-radius:8px;
          overflow:hidden;background:#11141a;color:inherit;text-align:left;cursor:pointer}.h3pa-card.selected{border:2px solid #76aaff}
        .h3pa-card[draggable="true"]{cursor:grab}.h3pa-card.dragging{opacity:.42;cursor:grabbing}
        .h3pa-card.drag-over{border-color:#82d7a0;box-shadow:0 0 0 2px #82d7a066}
        .h3pa-card.unresolved{border-style:dashed;background:#171922}.h3pa-card.unresolved.stale{opacity:.58}
        .h3pa-card.unresolved .fallback{color:#d7a95c}.h3pa-unassigned{color:#e6b76a;font-weight:650}
        .h3pa-card img{width:100%;height:78px;object-fit:cover;background:#090b10}.h3pa-card .fallback{height:78px;display:grid;
          place-items:center;font-size:24px;color:#81a8dc}.h3pa-card span{display:block;padding:4px 6px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
        .h3pa-badge{position:absolute;top:5px;left:5px;padding:2px 5px!important;border-radius:4px;background:#111c;color:#fff;font-size:10px}
        .h3pa-drag-handle{position:absolute;top:4px;right:4px;width:24px;padding:2px 4px!important;border-radius:4px;
          background:#111c;color:#dce8ff;text-align:center;font-size:14px;line-height:16px}
        .h3pa-editor-actions{display:flex;flex-direction:column;gap:6px;margin-top:auto;padding-top:8px;
          border-top:1px solid color-mix(in srgb,var(--border-color,#566174) 55%,transparent)}
        .h3pa-editor-actions .h3pa-button{height:30px;padding:3px 7px;min-width:0;white-space:nowrap}
        .h3pa-action-label{color:#8f9bb0;font-size:11px}.h3pa-action-primary{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:6px}
        .h3pa-action-primary>.h3pa-button:only-child{grid-column:1/-1}
        .h3pa-action-manage{display:grid;grid-template-columns:34px 34px minmax(0,1fr);gap:6px}
        .h3pa-editor-actions .h3pa-button:disabled{opacity:.35;cursor:default}
        .h3pa-button.danger{border-color:#9a5151;color:#ffb4b4}.h3pa-button.danger:hover{border-color:#ff7777}
        .h3pa-modal{position:fixed;z-index:100000;left:50%;top:50%;transform:translate(-50%,-50%);
          width:min(760px,calc(100vw - 32px));height:min(520px,calc(100vh - 48px));
          display:flex;flex-direction:column;gap:8px;padding:14px;
          border:1px solid #65738a;border-radius:10px;background:#141820;color:#eee;box-shadow:0 20px 70px #000b}
        .h3pa-source-list{overflow:auto;display:flex;flex-direction:column;gap:5px}.h3pa-source-item{display:grid;
          grid-template-columns:1fr auto auto;gap:8px;align-items:center;padding:7px;border:1px solid #3d4655;border-radius:6px}
        .h3pa-crop-modal{width:min(1180px,calc(100vw - 28px));height:min(780px,calc(100vh - 32px))}
        .h3pa-crop-layout{display:grid;grid-template-columns:minmax(0,1fr) 290px;gap:12px;min-height:0;flex:1}
        .h3pa-crop-canvas-wrap{min-width:0;min-height:0;display:grid;place-items:center;overflow:hidden;border:1px solid #48556a;border-radius:8px;background:#080a0f}
        .h3pa-crop-canvas{display:block;width:100%;height:100%;touch-action:none;cursor:crosshair;outline:none;user-select:none}
        .h3pa-crop-controls{display:flex;flex-direction:column;gap:9px;min-height:0;overflow:auto;padding:10px;border:1px solid #48556a;border-radius:8px;background:#11151d}
        .h3pa-crop-controls label{display:flex;flex-direction:column;gap:3px;color:#aeb7c8}.h3pa-crop-grid{display:grid;grid-template-columns:1fr 1fr;gap:7px}
        .h3pa-crop-controls input,.h3pa-crop-controls select{width:100%;min-width:0;padding:6px 7px;border:1px solid #566174;border-radius:6px;background:#151820;color:inherit}
        .h3pa-crop-actions{display:flex;flex-wrap:wrap;gap:6px;margin-top:auto}.h3pa-crop-note{color:#8f9bb0;font-size:11px}
        @media(max-width:850px){.h3pa-crop-layout{grid-template-columns:1fr}.h3pa-crop-controls{max-height:320px}}
        @media(max-width:800px){.h3pa-stage{grid-template-columns:1fr}.h3pa-editor{max-height:190px}}
    `;
    document.head.appendChild(style);
}

function collapseWidget(item) {
    if (!item || item._h3paCollapsed) return;
    item._h3paCollapsed = true;
    item.hidden = true;
    item.computeSize = () => [0, -4];
    item.type = "hidden";
}

function syncDownstreamPlan(node, runName) {
    for (const output of node.outputs ?? []) {
        for (const linkId of output.links ?? []) {
            const link = node.graph?.links?.[linkId];
            const target = link ? node.graph?.getNodeById?.(link.target_id) : null;
            if (!target || !PLAN_TYPES.has(nodeType(target))) continue;
            const run = widget(target, "run_name");
            if (run && run.value !== runName) {
                run.value = runName;
                run.callback?.(runName);
            }
        }
    }
}

function downstreamPlanRunName(node) {
    for (const output of node.outputs ?? []) {
        for (const linkId of output.links ?? []) {
            const link = node.graph?.links?.[linkId];
            const target = link ? node.graph?.getNodeById?.(link.target_id) : null;
            if (!target || !PLAN_TYPES.has(nodeType(target))) continue;
            const value = String(widget(target, "run_name")?.value ?? "").trim();
            if (value) return value;
        }
    }
    return "";
}

function mount(node) {
    if (node._h3ProjectAssetMounted) return;
    node._h3ProjectAssetMounted = true;
    injectStyles();
    const runNameWidget = widget(node, "run_name");
    const catalogWidget = widget(node, "catalog_json");
    const operationWidget = widget(node, "operation_json");
    const semanticSize = widget(node, "semantic_anchor_size");
    const semanticMode = widget(node, "semantic_anchor_mode");
    [runNameWidget, catalogWidget, operationWidget, semanticSize, semanticMode].forEach(collapseWidget);

    const root = el("div", "h3pa-root");
    const top = el("div", "h3pa-row");
    const runNameInput = el("input", "h3pa-project");
    runNameInput.placeholder = "Run name";
    runNameInput.title = "Authoritative H3 chain Run name. When this node is connected to Plan, the Plan run_name is synchronized automatically; enter it here only.";
    runNameInput.setAttribute("aria-label", "Run name");
    const savedRunName = String(runNameWidget?.value ?? "").trim();
    const connectedRunName = downstreamPlanRunName(node);
    runNameInput.value = (
        savedRunName && savedRunName !== "h3_project"
            ? savedRunName
            : (connectedRunName || (savedRunName === "h3_project" ? "" : savedRunName))
    );
    if (runNameWidget && runNameWidget.value !== runNameInput.value) {
        runNameWidget.value = runNameInput.value;
        runNameWidget.callback?.(runNameInput.value);
    }
    const sourceSelect = el("select");
    for (const [value, label] of [
        ["project", "Project assets"], ["input", "ComfyUI input"],
        ["path", "Server path"], ["chains", "H3 backups"],
    ]) {
        const option = el("option", "", label); option.value = value;
        sourceSelect.append(option);
    }
    const previewSelect = el("select");
    for (const [value, label] of [
        ["light", "Light previews"],
        ["full", "Full previews"],
    ]) {
        const option = el("option", "", label); option.value = value;
        previewSelect.append(option);
    }
    previewSelect.value = String(
        node.properties?.h3_project_asset_preview_mode ?? "light");
    previewSelect.title = "Display quality for this Carousel only. Generation always uses the original stored asset. Light uses cached thumbnails and bounded JPEG previews; Full loads the selected original into the Carousel UI.";
    previewSelect.setAttribute("aria-label", "Carousel display preview quality; generation always uses original assets");
    top.append(el("span", "", "Run name"), runNameInput, sourceSelect, previewSelect);
    const fileInput = el("input");
    fileInput.type = "file"; fileInput.accept = "image/*,video/*,audio/*";
    fileInput.hidden = true;
    top.append(
        button("Upload", () => {
            state.bindingSlot = selectedUnassignedSlot();
            fileInput.click();
        }, "Bind the selected Unassigned slot, or import a new asset when no slot is selected"),
        button("Browse source", () => browseSource(selectedUnassignedSlot()),
            "Bind the selected Unassigned slot, or import a new asset when no slot is selected"),
        button("Refresh", () => refresh()), fileInput,
    );
    const status = el("div", "h3pa-status", "Loading project assets…");
    const tabs = el("div", "h3pa-tabs");
    const stage = el("div", "h3pa-stage");
    const preview = el("div", "h3pa-preview");
    const editor = el("div", "h3pa-editor");
    stage.append(preview, editor);
    const carousel = el("div", "h3pa-carousel");
    root.append(top, status, tabs, stage, carousel);
    const dom = node.addDOMWidget("project_asset_carousel", "div", root, {
        serialize: false, hideOnZoom: false, getMinHeight: () => 560,
    });
    dom.serialize = false;
    node.setSize?.([Math.max(node.size?.[0] ?? 680, 760), Math.max(node.size?.[1] ?? 650, 700)]);

    const state = {
        catalog: {assets: [], reference_slots: [], folders: []}, selected: "",
        filter: "all", folder: "all", media: null, bindingSlot: null,
        dragging: "",
        previewMode: previewSelect.value === "full" ? "full" : "light",
    };
    const project = () => String(runNameInput.value || "").trim();
    let refreshSequence = 0;
    const graphSyncTimers = new Set();
    function setStatus(text, error = false) {
        status.textContent = text;
        status.style.color = error ? "#ff8d8d" : "";
    }
    function stopMedia() {
        if (state.media?.pause) state.media.pause();
        state.media = null;
        preview.replaceChildren();
    }
    function persistCatalog(catalog) {
        state.catalog = catalog ?? {assets: [], reference_slots: [], folders: []};
        state.catalog.folders ??= [];
        const canonicalProject = String(state.catalog.project || project());
        runNameInput.value = canonicalProject;
        if (catalogWidget) {
            catalogWidget.value = JSON.stringify(state.catalog);
            catalogWidget.callback?.(catalogWidget.value);
        }
        runNameWidget.value = canonicalProject;
        runNameWidget.callback?.(canonicalProject);
        syncDownstreamPlan(node, canonicalProject);
        node.graph?.setDirtyCanvas?.(true, true);
    }
    function allItems() {
        return [
            ...(state.catalog.assets ?? []),
            ...(state.catalog.reference_slots ?? []).map((slot) => ({
                ...slot, _unresolved: true,
            })),
        ];
    }
    function selectedUnassignedSlot() {
        return allItems().find((asset) => (
            asset.id === state.selected && asset._unresolved
        )) ?? null;
    }
    function filteredAssets() {
        return allItems().filter((asset) => {
            if (!matchesTab(asset, state.filter)) return false;
            if (state.folder === "all") return true;
            if (state.folder === "unfiled") {
                return asset._unresolved || !String(asset.folder_id ?? "");
            }
            return !asset._unresolved && asset.folder_id === state.folder;
        });
    }
    function renderTabs() {
        tabs.replaceChildren();
        for (const [key, label] of [["all", "All"], ["image", "Images"],
            ["semantic", "Semantic"], ["video", "Video"],
            ["audio", "Audio"], ["unassigned", "Unassigned"],
            ["source_track", "Source track"]]) {
            const count = allItems().filter((asset) => matchesTab(asset, key)).length;
            const item = button(`${label} ${count}`, () => {
                state.filter = key; render();
            });
            item.classList.add("h3pa-tab");
            item.classList.toggle("active", state.filter === key);
            tabs.append(item);
        }
    }
    async function folderRequest(body, success) {
        try {
            setStatus("Saving asset folders…");
            const result = await jsonRequest(
                "/minimax_h3_context_loop/project-assets/folder", {
                    method: "POST", headers: {"Content-Type": "application/json"},
                    body: JSON.stringify({project: project(), ...body}),
                });
            persistCatalog(result.catalog); render(); setStatus(success);
            return result;
        } catch (error) { setStatus(error.message, true); return null; }
    }
    function renderFolders() {
        const assetList = state.catalog.assets ?? [];
        const folderList = state.catalog.folders ?? [];
        const tools = el("div", "h3pa-folder-tools");
        const addFolder = button("+ Folder", async () => {
            const name = window.prompt("New asset folder name");
            if (!name?.trim()) return;
            const result = await folderRequest(
                {action: "create", name}, `Created folder ${name.trim()}.`,
            );
            if (result?.folder?.id) { state.folder = result.folder.id; render(); }
        }, "Create a presentation-only folder. Folders never affect prompts, fingerprints, or generation.");
        tools.append(addFolder);
        if (!folderList.length) {
            state.folder = "all";
            tabs.append(tools);
            return;
        }
        const noFolderCount = allItems().filter(
            (asset) => asset._unresolved || !String(asset.folder_id ?? ""),
        ).length;
        const folderSelect = el("select");
        folderSelect.title = "Presentation folders only organize this Carousel; they never affect prompts or generation. No folder means an asset has not been placed in one.";
        for (const folder of [
            {id: "all", name: "All folders", count: allItems().length},
            {id: "unfiled", name: "No folder", count: noFolderCount},
            ...folderList.map((folder) => ({
                ...folder,
                count: assetList.filter((asset) => asset.folder_id === folder.id).length,
            })),
        ]) {
            const option = el("option", "", `${folder.name} (${folder.count})`);
            option.value = folder.id;
            folderSelect.append(option);
        }
        folderSelect.value = state.folder;
        folderSelect.addEventListener("change", () => {
            state.folder = folderSelect.value;
            render();
        });
        tools.append(folderSelect);
        const active = folderList.find(
            (folder) => folder.id === state.folder,
        );
        if (active) {
            tools.append(
                button("Rename", async () => {
                    const name = window.prompt("Rename asset folder", active.name);
                    if (!name?.trim() || name.trim() === active.name) return;
                    await folderRequest({
                        action: "update", folder_id: active.id,
                        changes: {name: name.trim()},
                    }, `Renamed folder to ${name.trim()}.`);
                }),
                button("Remove folder", async () => {
                    if (!window.confirm(
                        `Remove folder ${active.name}? Its assets will move to No folder; no media is deleted.`,
                    )) return;
                    const result = await folderRequest({
                        action: "delete", folder_id: active.id,
                    }, `Removed folder ${active.name}.`);
                    if (result) { state.folder = "unfiled"; render(); }
                }),
            );
        }
        tabs.append(tools);
    }
    function renderPreview(asset) {
        stopMedia();
        if (!asset) {
            preview.append(el("div", "h3pa-empty", "Upload or import a project asset."));
            return;
        }
        if (asset._unresolved) {
            preview.append(el(
                "div", "h3pa-empty",
                asset.available === false
                    ? `${promptTag(asset)} is no longer present on the connected reference line.`
                    : `${promptTag(asset)} is unassigned. Choose its ${asset.kind} from ComfyUI input or upload it.`,
            ));
            return;
        }
        if (asset.kind === "image") {
            const image = el("img");
            image.alt = asset.tag;
            image.src = mediaUrl(
                project(), asset,
                state.previewMode === "full" ? "original" : "poster",
            );
            preview.append(image); state.media = image;
        } else if (asset.kind === "video") {
            const video = el("video");
            video.controls = true; video.preload = "metadata";
            video.poster = mediaUrl(project(), asset, "poster");
            video.src = mediaUrl(project(), asset, "preview");
            preview.append(video); state.media = video;
        } else {
            const audio = el("audio");
            audio.controls = true; audio.preload = "metadata";
            audio.src = mediaUrl(project(), asset, "original");
            preview.append(audio); state.media = audio;
        }
    }
    async function updateAsset(asset, changes) {
        try {
            setStatus(`Updating ${promptTag(asset)}…`);
            const result = await jsonRequest(
                "/minimax_h3_context_loop/project-assets/update", {
                    method: "POST", headers: {"Content-Type": "application/json"},
                    body: JSON.stringify({project: project(), asset_id: asset.id, changes}),
                });
            persistCatalog(result.catalog); render();
            setStatus(`Updated ${promptTag(result.asset)}.`);
        } catch (error) { setStatus(error.message, true); }
    }
    async function reorderAssets(assetIds) {
        try {
            setStatus("Saving asset order…");
            const result = await jsonRequest(
                "/minimax_h3_context_loop/project-assets/reorder", {
                    method: "POST", headers: {"Content-Type": "application/json"},
                    body: JSON.stringify({project: project(), asset_ids: assetIds}),
                });
            persistCatalog(result.catalog); render();
            setStatus("Asset order saved.");
        } catch (error) { setStatus(error.message, true); }
    }
    function moveAsset(asset, offset) {
        const assetIds = (state.catalog.assets ?? []).map((item) => item.id);
        const index = assetIds.indexOf(asset.id);
        const target = Math.max(0, Math.min(assetIds.length - 1, index + offset));
        if (index < 0 || index === target) return;
        assetIds.splice(index, 1);
        assetIds.splice(target, 0, asset.id);
        void reorderAssets(assetIds);
    }
    async function deleteAsset(asset) {
        const confirmed = window.confirm(
            `Delete ${promptTag(asset)} from this project?\n\n` +
            "This removes the Carousel-owned input copy and its H3 backup. " +
            "The original file you imported is not touched.",
        );
        if (!confirmed) return;
        const previous = state.catalog.assets ?? [];
        const previousIndex = previous.findIndex((item) => item.id === asset.id);
        try {
            setStatus(`Deleting ${promptTag(asset)}…`);
            const result = await jsonRequest(
                "/minimax_h3_context_loop/project-assets/delete", {
                    method: "POST", headers: {"Content-Type": "application/json"},
                    body: JSON.stringify({project: project(), asset_id: asset.id}),
                });
            persistCatalog(result.catalog);
            const remaining = result.catalog.assets ?? [];
            state.selected = remaining[
                Math.min(Math.max(previousIndex, 0), remaining.length - 1)
            ]?.id ?? "";
            render();
            setStatus(`Deleted ${promptTag(result.asset)}.`);
        } catch (error) { setStatus(error.message, true); }
    }
    async function duplicateAsset(asset) {
        try {
            setStatus(`Duplicating ${promptTag(asset)}…`);
            const result = await jsonRequest(
                "/minimax_h3_context_loop/project-assets/duplicate", {
                    method: "POST", headers: {"Content-Type": "application/json"},
                    body: JSON.stringify({project: project(), asset_id: asset.id}),
                });
            persistCatalog(result.catalog); state.selected = result.asset.id; render();
            setStatus(`Duplicated ${promptTag(asset)} as ${promptTag(result.asset)} without copying media bytes.`);
        } catch (error) { setStatus(error.message, true); }
    }
    function openImageEditor(asset) {
        const modal = el("div", "h3pa-modal h3pa-crop-modal");
        const heading = el("div", "h3pa-row");
        heading.append(
            el("strong", "h3pa-project", `Crop / resize variant · ${promptTag(asset)}`),
            button("Close", () => modal.remove()),
        );
        const layout = el("div", "h3pa-crop-layout");
        const canvasWrap = el("div", "h3pa-crop-canvas-wrap");
        const canvas = el("canvas", "h3pa-crop-canvas"); canvas.tabIndex = 0;
        canvas.setAttribute("aria-label", "Crop selector; drag outside the crop to draw, drag inside to move, drag any corner to resize, arrow keys nudge");
        canvasWrap.append(canvas);
        const controls = el("div", "h3pa-crop-controls");
        layout.append(canvasWrap, controls); modal.append(heading, layout); document.body.append(modal);

        const image = new Image(); image.decoding = "async";
        const crop = {x: 0, y: 0, width: 1, height: 1};
        let sourceWidth = 1; let sourceHeight = 1;
        let drawScale = 1; let drawX = 0; let drawY = 0;
        let drag = null;
        const cropInputs = {};
        function numberField(name, label, value, minimum = 0) {
            const wrapper = el("label", "", label);
            const input = el("input"); input.type = "number"; input.step = "1";
            input.min = String(minimum); input.value = String(value);
            wrapper.append(input); cropInputs[name] = input; return wrapper;
        }
        const cropGrid = el("div", "h3pa-crop-grid");
        cropGrid.append(
            numberField("x", "Crop X", 0), numberField("y", "Crop Y", 0),
            numberField("width", "Crop width", 1, 1),
            numberField("height", "Crop height", 1, 1),
        );
        const targetGrid = el("div", "h3pa-crop-grid");
        targetGrid.append(
            numberField("targetWidth", "Output width", 1, 1),
            numberField("targetHeight", "Output height", 1, 1),
        );
        const ratioLabel = el("label", "h3pa-toggle");
        const ratioLock = el("input"); ratioLock.type = "checkbox"; ratioLock.checked = true;
        const ratioCopy = el("span", "h3pa-toggle-copy");
        ratioCopy.append(el("strong", "", "Lock output ratio"), el("small", "", "Resizing the crop keeps the output aspect ratio."));
        ratioLabel.append(ratioLock, ratioCopy);
        const resampleLabel = el("label", "", "Resampling");
        const resample = el("select");
        for (const value of ["lanczos", "bicubic", "bilinear", "nearest"]) {
            const option = el("option", "", value); option.value = value; resample.append(option);
        }
        resampleLabel.append(resample);
        const tagLabel = el("label", "", "Variant prompt tag");
        const variantTag = el("input"); variantTag.value = `${asset.tag}_variant`;
        tagLabel.append(variantTag);
        const cropStatus = el("div", "h3pa-crop-note", "Loading full source image…");
        controls.append(
            el("div", "h3pa-crop-note", "Coordinates are oriented source-image pixels. Drag anywhere to draw a crop; drag inside it to move; drag any corner to resize. Arrow keys nudge by 1 px (Shift: 10 px)."),
            cropGrid, targetGrid, ratioLabel, resampleLabel, tagLabel, cropStatus,
        );
        const actions = el("div", "h3pa-crop-actions");
        const reset = button("Use full image", () => {
            crop.x = 0; crop.y = 0; crop.width = sourceWidth; crop.height = sourceHeight;
            cropInputs.targetWidth.value = String(sourceWidth);
            cropInputs.targetHeight.value = String(sourceHeight);
            syncInputs(); draw();
        });
        const startCrop = button("Start centered crop", () => {
            const ratio = outputRatio();
            let width = Math.max(1, Math.round(sourceWidth * 0.8));
            let height = Math.max(1, Math.round(width / ratio));
            if (height > sourceHeight * 0.8) {
                height = Math.max(1, Math.round(sourceHeight * 0.8));
                width = Math.max(1, Math.round(height * ratio));
            }
            crop.width = Math.min(sourceWidth, width);
            crop.height = Math.min(sourceHeight, height);
            crop.x = Math.round((sourceWidth - crop.width) / 2);
            crop.y = Math.round((sourceHeight - crop.height) / 2);
            syncInputs(); draw();
        }, "Create a visible centered crop using the selected output ratio");
        const save = button("Save crop / resize", async () => {
            const payload = operationPayload("resample"); if (!payload) return;
            try {
                save.disabled = true; modelButton.disabled = true;
                cropStatus.textContent = "Creating full-resolution variant…";
                const result = await jsonRequest(
                    "/minimax_h3_context_loop/project-assets/derive", {
                        method: "POST", headers: {"Content-Type": "application/json"},
                        body: JSON.stringify({...payload, resample: resample.value}),
                    });
                persistCatalog(result.catalog); state.selected = result.asset.id;
                modal.remove(); render();
                setStatus(`Created ${promptTag(result.asset)} from the full stored image.`);
            } catch (error) {
                cropStatus.textContent = error.message; save.disabled = false;
                modelButton.disabled = !modelConnected();
            }
        }, "Create a new full-quality PNG variant; the source asset remains unchanged");
        const modelButton = button("Model upscale", async () => {
            const payload = operationPayload("model"); if (!payload) return;
            if (!modelConnected()) {
                cropStatus.textContent = "Connect a core UPSCALE_MODEL to the Carousel first."; return;
            }
            try {
                operationWidget.value = JSON.stringify(payload);
                operationWidget.callback?.(operationWidget.value);
                node.graph?.setDirtyCanvas?.(true, true);
                save.disabled = true; modelButton.disabled = true;
                cropStatus.textContent = "Queued asset-only model upscale…";
                await app.queuePrompt(0, 1, [partialExecutionId(node)]);
                // queuePrompt has already serialized and submitted this one-shot
                // operation. Clear the workflow state immediately so a failed
                // model run cannot poison the user's next normal H3 queue.
                operationWidget.value = ""; operationWidget.callback?.("");
                modal.remove();
                setStatus("Asset-only model upscale queued; the H3 chain was not queued.");
            } catch (error) {
                operationWidget.value = ""; operationWidget.callback?.("");
                save.disabled = false; modelButton.disabled = !modelConnected();
                cropStatus.textContent = error.message;
            }
        }, "Run only this Carousel and its connected core upscale model; downstream H3 nodes are excluded");
        function modelConnected() {
            return (node.inputs ?? []).some((input) => (
                input.name === "upscale_model" && input.link != null
            ));
        }
        modelButton.disabled = !modelConnected();
        if (!modelConnected()) modelButton.title += " (No UPSCALE_MODEL is connected.)";
        actions.append(startCrop, reset, save, modelButton); controls.append(actions);

        function operationPayload(mode) {
            applyNumericInputs();
            const targetWidth = Math.round(Number(cropInputs.targetWidth.value));
            const targetHeight = Math.round(Number(cropInputs.targetHeight.value));
            if (!targetWidth || !targetHeight) {
                cropStatus.textContent = "Output width and height must be positive."; return null;
            }
            return {
                project: project(), asset_id: asset.id, mode,
                operation_id: globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random()}`,
                crop: {x: crop.x, y: crop.y, width: crop.width, height: crop.height},
                target: {width: targetWidth, height: targetHeight},
                tag: variantTag.value, folder_id: asset.folder_id ?? "",
            };
        }
        function outputRatio() {
            return Math.max(1, Number(cropInputs.targetWidth.value) || 1)
                / Math.max(1, Number(cropInputs.targetHeight.value) || 1);
        }
        function isFullCrop() {
            return crop.x === 0 && crop.y === 0
                && crop.width === sourceWidth && crop.height === sourceHeight;
        }
        function clampCrop(preference = "size") {
            if (preference === "position") {
                crop.width = Math.max(1, Math.min(sourceWidth, Math.round(crop.width)));
                crop.height = Math.max(1, Math.min(sourceHeight, Math.round(crop.height)));
                crop.x = Math.max(0, Math.min(sourceWidth - crop.width, Math.round(crop.x)));
                crop.y = Math.max(0, Math.min(sourceHeight - crop.height, Math.round(crop.y)));
                return;
            }
            // Numeric X/Y are authoritative: when a full-width crop is moved,
            // shorten it to the remaining source area instead of resetting X/Y.
            crop.x = Math.max(0, Math.min(sourceWidth - 1, Math.round(crop.x)));
            crop.y = Math.max(0, Math.min(sourceHeight - 1, Math.round(crop.y)));
            crop.width = Math.max(1, Math.min(sourceWidth - crop.x, Math.round(crop.width)));
            crop.height = Math.max(1, Math.min(sourceHeight - crop.y, Math.round(crop.height)));
        }
        function syncInputs(preference = "size") {
            clampCrop(preference);
            for (const key of ["x", "y", "width", "height"]) cropInputs[key].value = String(crop[key]);
            cropStatus.textContent = `${sourceWidth}×${sourceHeight} source → ${cropInputs.targetWidth.value}×${cropInputs.targetHeight.value} variant`;
        }
        function applyNumericInputs(changed = "") {
            for (const key of ["x", "y", "width", "height"]) {
                const value = Math.round(Number(cropInputs[key].value));
                if (Number.isFinite(value)) crop[key] = value;
            }
            if (ratioLock.checked && ["width", "height", "targetWidth", "targetHeight"].includes(changed)) {
                const ratio = outputRatio();
                if (changed === "height") crop.width = Math.round(crop.height * ratio);
                else crop.height = Math.round(crop.width / ratio);
            }
            syncInputs(["x", "y", "width", "height"].includes(changed)
                ? "size" : "position");
            draw();
        }
        for (const [name, input] of Object.entries(cropInputs)) {
            input.addEventListener("change", () => applyNumericInputs(name));
        }
        function canvasPoint(event) {
            const bounds = canvas.getBoundingClientRect();
            return {
                x: (event.clientX - bounds.left) * canvas.width / bounds.width,
                y: (event.clientY - bounds.top) * canvas.height / bounds.height,
            };
        }
        function sourcePoint(point) {
            return {x: (point.x - drawX) / drawScale, y: (point.y - drawY) / drawScale};
        }
        function boundedSourcePoint(point) {
            return {
                x: Math.max(0, Math.min(sourceWidth, point.x)),
                y: Math.max(0, Math.min(sourceHeight, point.y)),
            };
        }
        function cornerPoints() {
            return {
                nw: {x: crop.x, y: crop.y},
                ne: {x: crop.x + crop.width, y: crop.y},
                se: {x: crop.x + crop.width, y: crop.y + crop.height},
                sw: {x: crop.x, y: crop.y + crop.height},
            };
        }
        function hitCorner(point) {
            const threshold = Math.max(14 / drawScale, 7);
            for (const [name, corner] of Object.entries(cornerPoints())) {
                if (Math.hypot(point.x - corner.x, point.y - corner.y) <= threshold) return name;
            }
            return "";
        }
        function oppositeCorner(name) {
            return ({nw: "se", ne: "sw", se: "nw", sw: "ne"})[name];
        }
        function rectangleFromPoints(anchor, moving) {
            let width = Math.max(1, Math.abs(moving.x - anchor.x));
            let height = Math.max(1, Math.abs(moving.y - anchor.y));
            const horizontal = moving.x >= anchor.x ? 1 : -1;
            const vertical = moving.y >= anchor.y ? 1 : -1;
            if (ratioLock.checked) {
                const ratio = outputRatio();
                if (width / height > ratio) height = width / ratio;
                else width = height * ratio;
                const maximumWidth = horizontal > 0 ? sourceWidth - anchor.x : anchor.x;
                const maximumHeight = vertical > 0 ? sourceHeight - anchor.y : anchor.y;
                const fit = Math.min(1, maximumWidth / width, maximumHeight / height);
                width *= fit; height *= fit;
            }
            return {
                x: horizontal > 0 ? anchor.x : anchor.x - width,
                y: vertical > 0 ? anchor.y : anchor.y - height,
                width, height,
            };
        }
        function insideCrop(point) {
            return point.x >= crop.x && point.x <= crop.x + crop.width
                && point.y >= crop.y && point.y <= crop.y + crop.height;
        }
        function updateCanvasCursor(point) {
            const corner = hitCorner(point);
            if (corner === "nw" || corner === "se") canvas.style.cursor = "nwse-resize";
            else if (corner === "ne" || corner === "sw") canvas.style.cursor = "nesw-resize";
            else if (!isFullCrop() && insideCrop(point)) canvas.style.cursor = "move";
            else canvas.style.cursor = "crosshair";
        }
        function draw() {
            const bounds = canvasWrap.getBoundingClientRect();
            const density = Math.min(globalThis.devicePixelRatio || 1, 2);
            const width = Math.max(320, Math.round(bounds.width * density));
            const height = Math.max(260, Math.round(bounds.height * density));
            if (canvas.width !== width || canvas.height !== height) { canvas.width = width; canvas.height = height; }
            const context = canvas.getContext("2d"); context.clearRect(0, 0, width, height);
            context.fillStyle = "#080a0f"; context.fillRect(0, 0, width, height);
            if (!image.complete || !image.naturalWidth) return;
            drawScale = Math.min((width - 24) / sourceWidth, (height - 24) / sourceHeight);
            drawX = (width - sourceWidth * drawScale) / 2;
            drawY = (height - sourceHeight * drawScale) / 2;
            context.drawImage(image, drawX, drawY, sourceWidth * drawScale, sourceHeight * drawScale);
            const x = drawX + crop.x * drawScale; const y = drawY + crop.y * drawScale;
            const w = crop.width * drawScale; const h = crop.height * drawScale;
            context.save(); context.fillStyle = "#0009"; context.beginPath();
            context.rect(drawX, drawY, sourceWidth * drawScale, sourceHeight * drawScale);
            context.rect(x, y, w, h); context.fill("evenodd");
            context.strokeStyle = "#72a9ff"; context.lineWidth = Math.max(2, density * 1.5);
            context.strokeRect(x, y, w, h);
            context.strokeStyle = "#dbe9ff99"; context.lineWidth = Math.max(1, density);
            for (const fraction of [1 / 3, 2 / 3]) {
                context.beginPath(); context.moveTo(x + w * fraction, y); context.lineTo(x + w * fraction, y + h); context.stroke();
                context.beginPath(); context.moveTo(x, y + h * fraction); context.lineTo(x + w, y + h * fraction); context.stroke();
            }
            context.fillStyle = "#72a9ff";
            const handle = 12 * density;
            for (const corner of [
                [x, y], [x + w, y], [x + w, y + h], [x, y + h],
            ]) {
                context.fillRect(corner[0] - handle / 2, corner[1] - handle / 2, handle, handle);
            }
            context.restore();
        }
        canvas.addEventListener("pointerdown", (event) => {
            if (!image.naturalWidth) return;
            const point = boundedSourcePoint(sourcePoint(canvasPoint(event)));
            const corner = hitCorner(point);
            const previous = {...crop};
            if (corner) {
                const corners = cornerPoints();
                drag = {
                    mode: "resize", anchor: corners[oppositeCorner(corner)],
                    previous,
                };
            } else if (!isFullCrop() && insideCrop(point)) {
                drag = {mode: "move", point, start: {...crop}, previous};
            } else {
                crop.x = point.x; crop.y = point.y; crop.width = 1; crop.height = 1;
                drag = {mode: "create", anchor: point, previous};
                syncInputs("position"); draw();
            }
            canvas.setPointerCapture(event.pointerId); canvas.focus(); event.preventDefault();
        });
        canvas.addEventListener("pointermove", (event) => {
            const point = boundedSourcePoint(sourcePoint(canvasPoint(event)));
            if (!drag) { updateCanvasCursor(point); return; }
            if (drag.mode === "move") {
                const dx = point.x - drag.point.x;
                const dy = point.y - drag.point.y;
                crop.x = drag.start.x + dx; crop.y = drag.start.y + dy;
            } else {
                Object.assign(crop, rectangleFromPoints(drag.anchor, point));
            }
            clampCrop("position"); syncInputs("position"); draw(); event.preventDefault();
        });
        const endDrag = () => {
            if (drag && drag.mode === "create" && crop.width <= 2 && crop.height <= 2) {
                Object.assign(crop, drag.previous);
                syncInputs("position"); draw();
            }
            drag = null;
        };
        canvas.addEventListener("pointerup", endDrag); canvas.addEventListener("pointercancel", endDrag);
        canvas.addEventListener("keydown", (event) => {
            const step = event.shiftKey ? 10 : 1;
            if (event.key === "ArrowLeft") crop.x -= step;
            else if (event.key === "ArrowRight") crop.x += step;
            else if (event.key === "ArrowUp") crop.y -= step;
            else if (event.key === "ArrowDown") crop.y += step;
            else return;
            clampCrop("position"); syncInputs("position"); draw(); event.preventDefault();
        });
        image.addEventListener("load", () => {
            sourceWidth = image.naturalWidth; sourceHeight = image.naturalHeight;
            crop.x = 0; crop.y = 0; crop.width = sourceWidth; crop.height = sourceHeight;
            cropInputs.targetWidth.value = String(sourceWidth);
            cropInputs.targetHeight.value = String(sourceHeight);
            syncInputs(); draw();
        });
        image.addEventListener("error", () => { cropStatus.textContent = "Could not load the full stored source image."; });
        image.src = mediaUrl(project(), asset, "original");
        const observer = new ResizeObserver(draw); observer.observe(canvasWrap);
        const removeModal = modal.remove.bind(modal);
        modal.remove = () => { observer.disconnect(); removeModal(); };
    }
    function renderEditor(asset) {
        editor.replaceChildren();
        if (!asset) return;
        if (asset._unresolved) {
            editor.append(el("strong", "h3pa-unassigned", `${promptTag(asset)} · Unassigned`));
            editor.append(el(
                "div", "h3pa-status",
                `${asset.kind} · ${displayRole(asset.role)}`,
            ));
            const pairedTag = String(asset.options?.audio_tag ?? "");
            if (pairedTag) editor.append(el("div", "h3pa-status", `Paired alias @${pairedTag}`));
            if (asset.content_hash) editor.append(el(
                "small", "h3pa-status", `Source fingerprint ${asset.content_hash.slice(0, 16)}`,
            ));
            if (asset.available === false) editor.append(el(
                "div", "h3pa-status",
                "This tag disappeared from the connected carrier. The placeholder is retained and inactive.",
            ));
            editor.append(
                button("Choose from ComfyUI Input", () => browseSource(asset, "input"),
                    "Bind an existing ComfyUI input file without importing data from the Tagged Reference carrier"),
                button("Upload media", () => {
                    state.bindingSlot = asset;
                    fileInput.click();
                }),
                button("Choose another source", () => browseSource(asset)),
            );
            return;
        }
        editor.append(el("strong", "", asset.original_name || asset.tag));
        editor.append(el("div", "h3pa-status", assetDetail(asset)));
        const isAudio = asset.kind === "audio";
        const isSourceTrack = asset.role === "source_track";
        const audioMode = String(asset.options?.timeline_mode ?? "standalone");
        if (isAudio) {
            const audioUseLabel = el("label", "", "Audio use");
            audioUseLabel.title = "Tagged clip sends the complete audio only when @tag is present. Tagged timeline slice follows the current scene position only when @tag is present and requires Chain Policy Source reference=on. Project timeline source selects the project's full audio track. No @tag is required: Chain Policy decides whether scenes use it as generation reference audio and whether it becomes the final soundtrack.";
            const audioUse = el("select");
            const currentUse = isSourceTrack
                ? "source_track"
                : (audioMode === "source_timeline" ? "tagged_timeline" : "tagged_clip");
            for (const [value, label] of [
                ["tagged_clip", "Tagged clip (@tag)"],
                ["tagged_timeline", "Tagged timeline slice (@tag)"],
                ["source_track", "Project timeline source"],
            ]) {
                const option = el("option", "", label);
                option.value = value; option.selected = value === currentUse;
                audioUse.append(option);
            }
            audioUse.addEventListener("change", () => {
                const use = audioUse.value;
                updateAsset(asset, use === "source_track" ? {
                    role: "source_track",
                } : {
                    role: "audio_reference",
                    options: {
                        timeline_mode: use === "tagged_timeline"
                            ? "source_timeline" : "standalone",
                        ...(use === "tagged_clip"
                            ? {align_audio_reference: false} : {}),
                    },
                });
            });
            audioUseLabel.append(audioUse); editor.append(audioUseLabel);
        } else {
            const roleLabel = el("label", "", "Asset use");
            const role = el("select");
            for (const value of ROLES[asset.kind] ?? []) {
                const option = el("option", "", displayRole(value));
                option.value = value; option.selected = value === asset.role; role.append(option);
            }
            role.addEventListener("change", () => updateAsset(asset, {role: role.value}));
            roleLabel.append(role); editor.append(roleLabel);
        }
        const tagLabel = el("label", "", isSourceTrack ? "Catalog tag" : "Prompt tag");
        tagLabel.title = isSourceTrack
            ? "Internal catalog identifier. A Project source track is not activated from scene prompts."
            : `Scene prompts activate this asset by including ${promptTag(asset)}.`;
        const tag = el("input"); tag.value = asset.tag ?? "";
        tag.addEventListener("change", () => updateAsset(asset, {tag: tag.value}));
        tagLabel.append(tag); editor.append(tagLabel);
        const folderLabel = el("label", "", "Folder");
        folderLabel.title = "Presentation only. Folder membership never changes prompts, references, fingerprints, or generation.";
        const folderSelect = el("select");
        const noFolder = el("option", "", "No folder"); noFolder.value = "";
        folderSelect.append(noFolder);
        for (const folder of state.catalog.folders ?? []) {
            const option = el("option", "", folder.name); option.value = folder.id;
            option.selected = folder.id === String(asset.folder_id ?? "");
            folderSelect.append(option);
        }
        folderSelect.addEventListener("change", () => updateAsset(
            asset, {folder_id: folderSelect.value},
        ));
        folderLabel.append(folderSelect); editor.append(folderLabel);
        const enabledTitle = isSourceTrack ? "Selected timeline source" : "Available to prompts";
        const enabledSummary = isSourceTrack
            ? "Makes this file available to the Plan; Chain Policy decides how it is used."
            : `${promptTag(asset)} is used only when a scene prompt includes its tag. Turn off to archive it from suggestions without deleting it.`;
        const enabledHelp = isSourceTrack
            ? "Select this file as the Plan's project timeline source. This does not activate it in sampling or final audio: Chain Policy Source reference and Final audio remain authoritative. Turn it off to retain the stored file without exporting its Source Timeline."
            : `Keep ${promptTag(asset)} registered in prompt suggestions and reference fingerprinting. Scene prompts still control where it is used. Turn it off to archive it without deleting the stored file.`;
        const enabledLabel = el("label", "h3pa-toggle");
        enabledLabel.title = enabledHelp;
        const enabled = el("input"); enabled.type = "checkbox"; enabled.checked = asset.enabled !== false;
        enabled.setAttribute("aria-label", enabledTitle);
        enabled.title = enabledHelp;
        enabled.addEventListener("change", () => updateAsset(asset, {enabled: enabled.checked}));
        const enabledCopy = el("span", "h3pa-toggle-copy");
        enabledCopy.append(
            el("strong", "", enabledTitle),
            el("small", "", enabledSummary),
        );
        enabledLabel.append(enabled, enabledCopy); editor.append(enabledLabel);
        if (asset.role === "audio_reference" && audioMode === "source_timeline") {
                const alignHelp = "Apply the optional H3 audio-grid alignment to the per-scene reference slice. The stored full track and final assembled audio are unchanged.";
                const alignLabel = el("label", "h3pa-toggle");
                alignLabel.title = alignHelp;
                const align = el("input"); align.type = "checkbox";
                align.checked = Boolean(asset.options?.align_audio_reference);
                align.title = alignHelp;
                align.setAttribute("aria-label", "Align tagged audio reference to the H3 grid");
                align.addEventListener("change", () => updateAsset(
                    asset, {options: {align_audio_reference: align.checked}},
                ));
                const alignCopy = el("span", "h3pa-toggle-copy");
                alignCopy.append(
                    el("strong", "", "Align audio reference"),
                    el("small", "", "Align only the derived per-scene reference slice."),
                );
                alignLabel.append(align, alignCopy); editor.append(alignLabel);
        }
        if (["video", "motion"].includes(asset.role)) {
            const timelineLabel = el("label", "", "Timeline mode");
            const timeline = el("select");
            for (const value of ["restart_each_scene", "sequential"]) {
                const option = el("option", "", value.replaceAll("_", " "));
                option.value = value; option.selected = value === (asset.options?.timeline_mode ?? "restart_each_scene");
                timeline.append(option);
            }
            timeline.addEventListener("change", () => updateAsset(asset, {options: {timeline_mode: timeline.value}}));
            timelineLabel.append(timeline); editor.append(timelineLabel);
            if (asset.metadata?.has_audio) {
                const pairedLabel = el("label");
                const paired = el("input"); paired.type = "checkbox";
                paired.checked = Boolean(
                    asset.options?.use_embedded_audio ?? true);
                paired.addEventListener("change", () => updateAsset(
                    asset, {options: {use_embedded_audio: paired.checked}},
                ));
                pairedLabel.append(
                    paired, document.createTextNode(" Use embedded audio as paired reference"),
                );
                editor.append(pairedLabel);
            }
        }
        if (asset.role === "motion") {
            const edgeLabel = el("label", "", "Reference short edge");
            const edge = el("select");
            for (const value of ["source", "384", "512", "768"]) {
                const option = el("option", "", value);
                option.value = value;
                option.selected = value === String(
                    asset.options?.reference_short_edge ?? "384");
                edge.append(option);
            }
            edge.addEventListener("change", () => updateAsset(
                asset, {options: {reference_short_edge: edge.value}},
            ));
            edgeLabel.append(edge); editor.append(edgeLabel);
            for (const [name, label, fallback] of [
                ["target_subject", "Target Subject", "<Subject 1>"],
                ["motion_description", "Motion description", "the supplied pose sequence, action, and motion timing"],
            ]) {
                const wrapper = el("label", "", label);
                const input = name === "motion_description" ? el("textarea") : el("input");
                input.value = asset.options?.[name] ?? fallback;
                input.addEventListener("change", () => updateAsset(asset, {options: {[name]: input.value}}));
                wrapper.append(input); editor.append(wrapper);
            }
        }
        editor.append(el("small", "h3pa-status", `input/${asset.input_path}`));
        const actions = el("div", "h3pa-editor-actions");
        const primaryActions = el("div", "h3pa-action-primary");
        const manageActions = el("div", "h3pa-action-manage");
        const assetIndex = (state.catalog.assets ?? []).findIndex(
            (item) => item.id === asset.id,
        );
        const earlier = button("←", () => moveAsset(asset, -1),
            "Move this asset one position earlier in the project Carousel");
        earlier.setAttribute("aria-label", "Move asset earlier");
        earlier.disabled = assetIndex <= 0;
        const later = button("→", () => moveAsset(asset, 1),
            "Move this asset one position later in the project Carousel");
        later.setAttribute("aria-label", "Move asset later");
        later.disabled = assetIndex < 0 || assetIndex >= state.catalog.assets.length - 1;
        const remove = button("Delete", () => deleteAsset(asset),
            "Permanently remove this project-owned copy and its H3 backup");
        remove.setAttribute("aria-label", "Delete asset");
        remove.classList.add("danger");
        primaryActions.append(
            ...(asset.kind === "image" ? [button(
                "Crop / resize", () => openImageEditor(asset),
                "Create a nondestructive image variant from exact source pixels",
            )] : []),
            button("Duplicate", () => duplicateAsset(asset),
                "Create another catalog card that initially shares the same stored media bytes"),
        );
        manageActions.append(earlier, later, remove);
        actions.append(
            el("span", "h3pa-action-label", "Asset actions"),
            primaryActions, manageActions,
        );
        editor.append(actions);
    }
    function renderCarousel() {
        carousel.replaceChildren();
        const assets = filteredAssets();
        if (!assets.some((asset) => asset.id === state.selected)) {
            state.selected = assets[0]?.id ?? "";
        }
        for (const asset of assets) {
            const card = el("button", "h3pa-card"); card.type = "button";
            card.classList.toggle("selected", asset.id === state.selected);
            card.classList.toggle("unresolved", Boolean(asset._unresolved));
            card.classList.toggle("stale", asset._unresolved && asset.available === false);
            if (!asset._unresolved) {
                card.draggable = true;
                card.title = "Drag to reorder this project asset.";
            }
            if (!asset._unresolved && ["image", "video"].includes(asset.kind)) {
                const image = el("img"); image.loading = "lazy";
                image.src = mediaUrl(project(), asset, "thumbnail"); card.append(image);
            } else card.append(el(
                "div", "fallback", asset._unresolved ? "?" : "♫",
            ));
            card.append(el(
                "span", "h3pa-badge",
                `${displayRole(asset.role)}${asset._unresolved ? " · unassigned" : ""}`,
            ));
            if (!asset._unresolved) card.append(el(
                "span", "h3pa-drag-handle", "↔",
            ));
            card.append(el(
                "span", "",
                `${asset.available === false || asset.enabled === false ? "○ " : ""}${promptTag(asset)}`,
            ));
            card.addEventListener("click", () => { state.selected = asset.id; render(); });
            if (!asset._unresolved) {
                card.addEventListener("dragstart", (event) => {
                    state.dragging = asset.id;
                    card.classList.add("dragging");
                    event.dataTransfer.effectAllowed = "move";
                    event.dataTransfer.setData("text/plain", asset.id);
                });
                card.addEventListener("dragover", (event) => {
                    if (!state.dragging || state.dragging === asset.id) return;
                    event.preventDefault();
                    event.dataTransfer.dropEffect = "move";
                    card.classList.add("drag-over");
                });
                card.addEventListener("dragleave", () => {
                    card.classList.remove("drag-over");
                });
                card.addEventListener("drop", (event) => {
                    event.preventDefault();
                    card.classList.remove("drag-over");
                    const dragged = state.dragging || event.dataTransfer.getData("text/plain");
                    if (!dragged || dragged === asset.id) return;
                    const assetIds = (state.catalog.assets ?? []).map((item) => item.id);
                    const from = assetIds.indexOf(dragged);
                    if (from < 0) return;
                    assetIds.splice(from, 1);
                    let target = assetIds.indexOf(asset.id);
                    if (target < 0) return;
                    const bounds = card.getBoundingClientRect();
                    if (event.clientX >= bounds.left + bounds.width / 2) target += 1;
                    assetIds.splice(target, 0, dragged);
                    state.selected = dragged;
                    void reorderAssets(assetIds);
                });
                card.addEventListener("dragend", () => {
                    state.dragging = "";
                    for (const item of carousel.children) {
                        item.classList.remove("dragging", "drag-over");
                    }
                });
            }
            carousel.append(card);
        }
    }
    function render() {
        if (state.folder !== "all" && state.folder !== "unfiled"
                && !(state.catalog.folders ?? []).some((folder) => folder.id === state.folder)) {
            state.folder = "all";
        }
        renderTabs(); renderFolders(); renderCarousel();
        const selected = allItems().find((asset) => asset.id === state.selected);
        renderPreview(selected); renderEditor(selected);
    }
    async function refresh() {
        const requestedProject = project();
        const sequence = ++refreshSequence;
        if (!requestedProject) {
            setStatus("Enter a Run name, or connect this node to a named Plan.");
            return;
        }
        try {
            setStatus(`Loading ${requestedProject}…`);
            const catalog = await jsonRequest(
                `/minimax_h3_context_loop/project-assets?project=${encodeURIComponent(requestedProject)}`,
            );
            if (sequence !== refreshSequence || project() !== requestedProject) return;
            persistCatalog(catalog); render();
            setStatus(`${catalog.assets.length} project assets · ${(catalog.reference_slots ?? []).length} unassigned · revision ${(catalog.revision || "empty").slice(0, 12)}`);
        } catch (error) { setStatus(error.message, true); }
    }
    function adoptConnectedRunName() {
        const current = project();
        if (current && current !== "h3_project") return false;
        const connected = downstreamPlanRunName(node);
        if (!connected) return false;
        refreshSequence += 1;
        runNameInput.value = connected;
        if (runNameWidget) {
            runNameWidget.value = connected;
            runNameWidget.callback?.(connected);
        }
        void refresh();
        return true;
    }
    function scheduleGraphRunNameSync() {
        for (const timer of graphSyncTimers) clearTimeout(timer);
        graphSyncTimers.clear();
        for (const delay of [0, 50, 200, 750]) {
            const timer = setTimeout(() => {
                graphSyncTimers.delete(timer);
                if (adoptConnectedRunName()) {
                    for (const pending of graphSyncTimers) clearTimeout(pending);
                    graphSyncTimers.clear();
                }
            }, delay);
            graphSyncTimers.add(timer);
        }
    }
    async function importAsset(body) {
        const result = await jsonRequest(
            "/minimax_h3_context_loop/project-assets/import", {
                method: "POST", headers: {"Content-Type": "application/json"},
                body: JSON.stringify({project: project(), ...body}),
            });
        persistCatalog(result.catalog); state.selected = result.asset.id; render();
        setStatus(`${result.bound_slot_id ? "Bound" : "Imported"} ${promptTag(result.asset)} as ${result.asset.role}.`);
    }
    async function browseSource(slot = null, forcedSource = "") {
        let source = forcedSource || sourceSelect.value;
        if (source === "project" && slot) source = "input";
        if (source === "project") { await refresh(); return; }
        if (source === "path") {
            const path = window.prompt("Absolute server media path");
            if (!path) return;
            try { await importAsset({source: "path", path, slot_id: slot?.id ?? ""}); }
            catch (error) { setStatus(error.message, true); }
            return;
        }
        const modal = el("div", "h3pa-modal");
        const row = el("div", "h3pa-row");
        const search = el("input", "h3pa-project"); search.placeholder = "Filter assets";
        row.append(el("strong", "", source === "input" ? "ComfyUI input" : "H3 chain backups"), search,
            button("Close", () => modal.remove()));
        const list = el("div", "h3pa-source-list"); modal.append(row, list); document.body.append(modal);
        async function load() {
            list.textContent = "Loading…";
            try {
                const payload = await jsonRequest(
                    `/minimax_h3_context_loop/project-assets/sources?source=${source}&q=${encodeURIComponent(search.value)}`,
                );
                list.replaceChildren();
                const items = source === "chains"
                    ? payload.items.flatMap((run) => run.assets.map((asset) => ({...asset, run_name: run.run_name})))
                    : payload.items;
                for (const item of items) {
                    const rowItem = el("div", "h3pa-source-item");
                    rowItem.append(el("span", "", source === "chains"
                        ? `${item.run_name} · ${promptTag(item)}` : item.path),
                    el("span", "", item.kind ?? ""), button(slot ? "Bind" : "Import", async () => {
                        try {
                            if (source === "chains") await importAsset({
                                source, run_name: item.run_name, asset_id: item.id,
                                slot_id: slot?.id ?? "",
                            });
                            else await importAsset({
                                source, path: item.path, slot_id: slot?.id ?? "",
                            });
                            modal.remove();
                        } catch (error) { setStatus(error.message, true); }
                    }));
                    list.append(rowItem);
                }
            } catch (error) { list.textContent = error.message; }
        }
        let timer = 0;
        search.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(load, 250); });
        await load();
    }
    fileInput.addEventListener("change", async () => {
        const file = fileInput.files?.[0]; if (!file) return;
        const slot = state.bindingSlot;
        const data = new FormData();
        data.append("project", project());
        if (slot?.id) data.append("slot_id", slot.id);
        data.append("file", file, file.name);
        try {
            setStatus(`${slot ? `Binding ${promptTag(slot)} from` : "Uploading"} ${file.name}…`);
            const result = await jsonRequest(
                "/minimax_h3_context_loop/project-assets/upload", {method: "POST", body: data});
            persistCatalog(result.catalog); state.selected = result.asset.id; render();
            setStatus(`${slot ? "Bound" : "Uploaded"} ${promptTag(result.asset)}.`);
        } catch (error) { setStatus(error.message, true); }
        state.bindingSlot = null;
        fileInput.value = "";
    });
    let projectTimer = 0;
    runNameInput.addEventListener("input", () => {
        refreshSequence += 1;
        if (runNameWidget) {
            runNameWidget.value = project();
            runNameWidget.callback?.(project());
        }
        clearTimeout(projectTimer); projectTimer = setTimeout(refresh, 400);
    });
    previewSelect.addEventListener("change", () => {
        state.previewMode = previewSelect.value === "full" ? "full" : "light";
        node.properties ??= {};
        node.properties.h3_project_asset_preview_mode = state.previewMode;
        render();
    });
    const connectionsChanged = node.onConnectionsChange;
    node.onConnectionsChange = function () {
        const result = connectionsChanged?.apply(this, arguments);
        scheduleGraphRunNameSync();
        return result;
    };
    const removed = node.onRemoved;
    node.onRemoved = function () {
        for (const timer of graphSyncTimers) clearTimeout(timer);
        graphSyncTimers.clear();
        stopMedia();
        return removed?.apply(this, arguments);
    };
    const executed = node.onExecuted;
    node.onExecuted = function () {
        const result = executed?.apply(this, arguments);
        if (operationWidget?.value) {
            operationWidget.value = "";
            operationWidget.callback?.("");
        }
        void refresh();
        return result;
    };
    node._h3ProjectAssetRefresh = () => {
        if (!adoptConnectedRunName()) void refresh();
        scheduleGraphRunNameSync();
    };
    node._h3ProjectAssetRefresh();
}

app.registerExtension({
    name: "minimax_h3_context_loop.project_asset_manager",
    async beforeRegisterNodeDef(nodeClass, nodeData) {
        if (nodeData.name !== NODE_NAME) return;
        const created = nodeClass.prototype.onNodeCreated;
        nodeClass.prototype.onNodeCreated = function () {
            const result = created?.apply(this, arguments);
            setTimeout(() => mount(this), 0); return result;
        };
        const configured = nodeClass.prototype.onConfigure;
        nodeClass.prototype.onConfigure = function () {
            const result = configured?.apply(this, arguments);
            setTimeout(() => this._h3ProjectAssetRefresh?.(), 0); return result;
        };
        const graphConfigured = nodeClass.prototype.onGraphConfigured;
        nodeClass.prototype.onGraphConfigured = function () {
            const result = graphConfigured?.apply(this, arguments);
            setTimeout(() => this._h3ProjectAssetRefresh?.(), 0); return result;
        };
    },
    async nodeCreated(node) { if (nodeType(node) === NODE_NAME) mount(node); },
    async afterConfigureGraph() {
        for (const node of app.graph?._nodes ?? []) {
            if (nodeType(node) === NODE_NAME) {
                setTimeout(() => node._h3ProjectAssetRefresh?.(), 0);
            }
        }
    },
});
