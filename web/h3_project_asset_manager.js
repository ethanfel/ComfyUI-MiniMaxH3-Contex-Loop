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

function nodeType(node) {
    return node?.comfyClass ?? node?.type ?? "";
}

function widget(node, name) {
    return node?.widgets?.find((item) => item.name === name) ?? null;
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
        .h3pa-tabs{display:flex;gap:5px;overflow-x:auto}.h3pa-tab.active{background:#284d7e;border-color:#70a9ff}
        .h3pa-stage{flex:1 1 auto;min-height:230px;display:grid;grid-template-columns:minmax(0,1fr) 260px;gap:10px;overflow:hidden}
        .h3pa-preview{position:relative;display:grid;place-items:center;min-width:0;min-height:220px;
          overflow:hidden;border:1px solid var(--border-color,#566174);border-radius:9px;background:#090b10}
        .h3pa-preview img,.h3pa-preview video{display:block;max-width:100%;max-height:100%;object-fit:contain}
        .h3pa-preview audio{width:min(94%,650px)}.h3pa-empty{color:#738097;text-align:center;padding:24px}
        .h3pa-editor{display:flex;flex-direction:column;gap:8px;padding:10px;overflow:auto;border:1px solid
          var(--border-color,#566174);border-radius:9px;background:var(--comfy-input-bg,#151820)}
        .h3pa-editor label{display:flex;flex-direction:column;gap:3px;color:#aeb7c8}.h3pa-editor textarea{min-height:62px;resize:vertical}
        .h3pa-carousel{display:flex;gap:8px;overflow-x:auto;overflow-y:hidden;padding:4px 1px 7px;min-height:126px}
        .h3pa-card{position:relative;flex:0 0 150px;height:112px;padding:0;border:1px solid #495466;border-radius:8px;
          overflow:hidden;background:#11141a;color:inherit;text-align:left;cursor:pointer}.h3pa-card.selected{border:2px solid #76aaff}
        .h3pa-card.unresolved{border-style:dashed;background:#171922}.h3pa-card.unresolved.stale{opacity:.58}
        .h3pa-card.unresolved .fallback{color:#d7a95c}.h3pa-unassigned{color:#e6b76a;font-weight:650}
        .h3pa-card img{width:100%;height:78px;object-fit:cover;background:#090b10}.h3pa-card .fallback{height:78px;display:grid;
          place-items:center;font-size:24px;color:#81a8dc}.h3pa-card span{display:block;padding:4px 6px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
        .h3pa-badge{position:absolute;top:5px;left:5px;padding:2px 5px!important;border-radius:4px;background:#111c;color:#fff;font-size:10px}
        .h3pa-modal{position:fixed;z-index:100000;inset:8vh 10vw;display:flex;flex-direction:column;gap:8px;padding:14px;
          border:1px solid #65738a;border-radius:10px;background:#141820;color:#eee;box-shadow:0 20px 70px #000b}
        .h3pa-source-list{overflow:auto;display:flex;flex-direction:column;gap:5px}.h3pa-source-item{display:grid;
          grid-template-columns:1fr auto auto;gap:8px;align-items:center;padding:7px;border:1px solid #3d4655;border-radius:6px}
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

function syncDownstreamPlan(node, project) {
    for (const output of node.outputs ?? []) {
        for (const linkId of output.links ?? []) {
            const link = node.graph?.links?.[linkId];
            const target = link ? node.graph?.getNodeById?.(link.target_id) : null;
            if (!target || !PLAN_TYPES.has(nodeType(target))) continue;
            const run = widget(target, "run_name");
            if (run && run.value !== project) {
                run.value = project;
                run.callback?.(project);
            }
        }
    }
}

function mount(node) {
    if (node._h3ProjectAssetMounted) return;
    node._h3ProjectAssetMounted = true;
    injectStyles();
    const projectWidget = widget(node, "project_name");
    const catalogWidget = widget(node, "catalog_json");
    const semanticSize = widget(node, "semantic_anchor_size");
    const semanticMode = widget(node, "semantic_anchor_mode");
    [projectWidget, catalogWidget, semanticSize, semanticMode].forEach(collapseWidget);

    const root = el("div", "h3pa-root");
    const top = el("div", "h3pa-row");
    const projectInput = el("input", "h3pa-project");
    projectInput.placeholder = "Project name";
    projectInput.value = String(projectWidget?.value ?? "h3_project");
    const sourceSelect = el("select");
    for (const [value, label] of [
        ["project", "Project assets"], ["input", "ComfyUI input"],
        ["path", "Server path"], ["chains", "H3 backups"],
    ]) {
        const option = el("option", "", label); option.value = value;
        sourceSelect.append(option);
    }
    top.append(projectInput, sourceSelect);
    const fileInput = el("input");
    fileInput.type = "file"; fileInput.accept = "image/*,video/*,audio/*";
    fileInput.hidden = true;
    top.append(
        button("Upload", () => {
            state.bindingSlot = null;
            fileInput.click();
        }, "Copy media into this project"),
        button("Browse source", () => browseSource(), "Import from selected source"),
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
        catalog: {assets: [], reference_slots: []}, selected: "",
        filter: "all", media: null, bindingSlot: null,
    };
    const project = () => String(projectInput.value || "h3_project").trim();
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
        state.catalog = catalog ?? {assets: [], reference_slots: []};
        const canonicalProject = String(state.catalog.project || project());
        projectInput.value = canonicalProject;
        if (catalogWidget) {
            catalogWidget.value = JSON.stringify(state.catalog);
            catalogWidget.callback?.(catalogWidget.value);
        }
        projectWidget.value = canonicalProject;
        projectWidget.callback?.(canonicalProject);
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
    function filteredAssets() {
        return allItems().filter((asset) => {
            if (state.filter === "all") return true;
            if (state.filter === "unassigned") return asset._unresolved;
            if (state.filter === "semantic") return asset.role === "semantic_anchor";
            if (state.filter === "image") return asset.kind === "image";
            if (state.filter === "video") return asset.kind === "video";
            if (state.filter === "audio") return asset.kind === "audio";
            return asset.role === state.filter;
        });
    }
    function renderTabs() {
        tabs.replaceChildren();
        for (const [key, label] of [["all", "All"], ["image", "Images"],
            ["semantic", "Semantic"], ["video", "Video"],
            ["audio", "Audio"], ["unassigned", "Unassigned"],
            ["source_track", "Source track"]]) {
            const count = allItems().filter((asset) => key === "all"
                || (key === "unassigned" ? asset._unresolved
                    : key === "semantic" ? asset.role === "semantic_anchor"
                        : key === "source_track" ? asset.role === key
                            : asset.kind === key)).length;
            const item = button(`${label} ${count}`, () => {
                state.filter = key; render();
            });
            item.classList.add("h3pa-tab");
            item.classList.toggle("active", state.filter === key);
            tabs.append(item);
        }
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
                    ? `@${asset.tag} is no longer present on the connected reference line.`
                    : `@${asset.tag} is unassigned. Choose its ${asset.kind} from ComfyUI input or upload it.`,
            ));
            return;
        }
        if (asset.kind === "image") {
            const image = el("img");
            image.alt = asset.tag; image.src = mediaUrl(project(), asset, "original");
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
            setStatus(`Updating @${asset.tag}…`);
            const result = await jsonRequest(
                "/minimax_h3_context_loop/project-assets/update", {
                    method: "POST", headers: {"Content-Type": "application/json"},
                    body: JSON.stringify({project: project(), asset_id: asset.id, changes}),
                });
            persistCatalog(result.catalog); render();
            setStatus(`Updated @${result.asset.tag}.`);
        } catch (error) { setStatus(error.message, true); }
    }
    function renderEditor(asset) {
        editor.replaceChildren();
        if (!asset) return;
        if (asset._unresolved) {
            editor.append(el("strong", "h3pa-unassigned", `@${asset.tag} · Unassigned`));
            editor.append(el(
                "div", "h3pa-status",
                `${asset.kind} · ${String(asset.role || "").replaceAll("_", " ")}`,
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
        const tagLabel = el("label", "", "Prompt tag");
        const tag = el("input"); tag.value = asset.tag ?? "";
        tag.addEventListener("change", () => updateAsset(asset, {tag: tag.value}));
        tagLabel.append(tag); editor.append(tagLabel);
        const roleLabel = el("label", "", "Role");
        const role = el("select");
        for (const value of ROLES[asset.kind] ?? []) {
            const option = el("option", "", value.replaceAll("_", " "));
            option.value = value; option.selected = value === asset.role; role.append(option);
        }
        role.addEventListener("change", () => updateAsset(asset, {role: role.value}));
        roleLabel.append(role); editor.append(roleLabel);
        const enabledLabel = el("label");
        const enabled = el("input"); enabled.type = "checkbox"; enabled.checked = asset.enabled !== false;
        enabled.addEventListener("change", () => updateAsset(asset, {enabled: enabled.checked}));
        enabledLabel.append(enabled, document.createTextNode(" Enabled")); editor.append(enabledLabel);
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
            if (!asset._unresolved && ["image", "video"].includes(asset.kind)) {
                const image = el("img"); image.loading = "lazy";
                image.src = mediaUrl(project(), asset, "poster"); card.append(image);
            } else card.append(el(
                "div", "fallback", asset._unresolved ? "?" : "♫",
            ));
            card.append(el(
                "span", "h3pa-badge",
                `${asset.role.replaceAll("_", " ")}${asset._unresolved ? " · unassigned" : ""}`,
            ));
            card.append(el(
                "span", "",
                `${asset.available === false || asset.enabled === false ? "○ " : ""}@${asset.tag}`,
            ));
            card.addEventListener("click", () => { state.selected = asset.id; render(); });
            carousel.append(card);
        }
    }
    function render() {
        renderTabs(); renderCarousel();
        const selected = allItems().find((asset) => asset.id === state.selected);
        renderPreview(selected); renderEditor(selected);
    }
    async function refresh() {
        try {
            setStatus(`Loading ${project()}…`);
            const catalog = await jsonRequest(
                `/minimax_h3_context_loop/project-assets?project=${encodeURIComponent(project())}`,
            );
            persistCatalog(catalog); render();
            setStatus(`${catalog.assets.length} project assets · ${(catalog.reference_slots ?? []).length} unassigned · revision ${(catalog.revision || "empty").slice(0, 12)}`);
        } catch (error) { setStatus(error.message, true); }
    }
    async function importAsset(body) {
        const result = await jsonRequest(
            "/minimax_h3_context_loop/project-assets/import", {
                method: "POST", headers: {"Content-Type": "application/json"},
                body: JSON.stringify({project: project(), ...body}),
            });
        persistCatalog(result.catalog); state.selected = result.asset.id; render();
        setStatus(`${result.bound_slot_id ? "Bound" : "Imported"} @${result.asset.tag} as ${result.asset.role}.`);
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
                        ? `${item.run_name} · @${item.tag}` : item.path),
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
            setStatus(`${slot ? `Binding @${slot.tag} from` : "Uploading"} ${file.name}…`);
            const result = await jsonRequest(
                "/minimax_h3_context_loop/project-assets/upload", {method: "POST", body: data});
            persistCatalog(result.catalog); state.selected = result.asset.id; render();
            setStatus(`${slot ? "Bound" : "Uploaded"} @${result.asset.tag}.`);
        } catch (error) { setStatus(error.message, true); }
        state.bindingSlot = null;
        fileInput.value = "";
    });
    let projectTimer = 0;
    projectInput.addEventListener("input", () => {
        clearTimeout(projectTimer); projectTimer = setTimeout(refresh, 400);
    });
    const removed = node.onRemoved;
    node.onRemoved = function () { stopMedia(); return removed?.apply(this, arguments); };
    const executed = node.onExecuted;
    node.onExecuted = function () {
        const result = executed?.apply(this, arguments);
        void refresh();
        return result;
    };
    node._h3ProjectAssetRefresh = refresh;
    void refresh();
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
    },
    async nodeCreated(node) { if (nodeType(node) === NODE_NAME) mount(node); },
});
