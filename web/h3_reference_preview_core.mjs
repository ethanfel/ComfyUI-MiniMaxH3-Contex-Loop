export const SCHEDULED_REF2VA_TYPE = "MiniMaxH3ScheduledReferenceToVideo";
export const TAGGED_REF2VA_TYPE = "MiniMaxH3TaggedReferenceToVideo";
export const CORE_REF2VA_TYPE = "MiniMaxH3ReferenceToVideo";
export const IMAGE_TO_VIDEO_TYPE = "MiniMaxH3ImageToVideo";
export const FIRST_SCENE_IMAGE_TYPE = "MiniMaxH3ChainFirstSceneImage";
export const FRAME_INDEX_SWITCH_TYPE = "MiniMaxH3ChainFrameIndexSwitch";
export const PICTURE_REF_TYPE = "MiniMaxH3ScheduledPictureReference";
export const VIDEO_REF_TYPE = "MiniMaxH3ScheduledVideoReference";
export const AUDIO_REF_TYPE = "MiniMaxH3ScheduledAudioReference";
export const TAGGED_PICTURE_REF_TYPE = "MiniMaxH3TaggedPictureReference";
export const TAGGED_VIDEO_REF_TYPE = "MiniMaxH3TaggedVideoReference";
export const TAGGED_MOTION_REF_TYPE = "MiniMaxH3TaggedMotionReference";
export const TAGGED_MOTION_PATH_REF_TYPE =
    "MiniMaxH3TaggedMotionReferencePath";
export const TAGGED_MOTION_TIMELINE_REF_TYPE =
    "MiniMaxH3TaggedMotionReferenceTimeline";
export const TAGGED_AUDIO_REF_TYPE = "MiniMaxH3TaggedAudioReference";
export const SEMANTIC_ANCHOR_BUNDLE_TYPE = "MiniMaxH3SemanticAnchorBundle";
export const SEMANTIC_PICTURE_ANCHOR_TYPE = "MiniMaxH3SemanticPictureAnchor";
export const PROJECT_ASSET_MANAGER_TYPE = "MiniMaxH3ProjectAssetManager";

const SCHEDULE_TYPES = new Set([
    PICTURE_REF_TYPE,
    VIDEO_REF_TYPE,
    AUDIO_REF_TYPE,
]);
const TAGGED_TYPES = new Set([
    TAGGED_PICTURE_REF_TYPE,
    TAGGED_VIDEO_REF_TYPE,
    TAGGED_MOTION_REF_TYPE,
    TAGGED_MOTION_PATH_REF_TYPE,
    TAGGED_MOTION_TIMELINE_REF_TYPE,
    TAGGED_AUDIO_REF_TYPE,
]);

export function nodeType(node) {
    return node?.comfyClass ?? node?.type ?? null;
}

function widgetValue(node, name, fallback = "") {
    const connected = connectedInputValue(node, name);
    if (connected !== undefined) return connected;
    return node?.widgets?.find((item) => item.name === name)?.value ?? fallback;
}

export function referenceTag(value) {
    return String(value ?? "").trim().replace(/^@+/, "");
}

function escapedPattern(value) {
    return String(value ?? "").replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

export function taggedPictureReferenceToken(tag, mode = "native", timestamp = 0) {
    const cleanTag = referenceTag(tag);
    if (!cleanTag) return "";
    if (mode !== "semantic") return `@${cleanTag}`;
    const seconds = Number(timestamp);
    const safeSeconds = Number.isFinite(seconds) ? Math.max(0, seconds) : 0;
    return `#${cleanTag}[${safeSeconds.toFixed(2)}s]`;
}

export function taggedPictureReferenceMode(prompt, tag) {
    const cleanTag = referenceTag(tag);
    if (!cleanTag) return "unused";
    const escaped = escapedPattern(cleanTag);
    const native = new RegExp(
        `(^|[^A-Za-z0-9_])@${escaped}(?![A-Za-z0-9_-])`, "i",
    ).test(String(prompt ?? ""));
    const semantic = new RegExp(
        `(^|[^A-Za-z0-9_])#${escaped}\\[[0-9]+(?:\\.[0-9]+)?s?\\]`, "i",
    ).test(String(prompt ?? ""));
    if (native && semantic) return "mixed";
    if (semantic) return "semantic";
    if (native) return "native";
    return "unused";
}

export function convertTaggedPictureReference(
        prompt, tag, mode = "native", timestamp = 0) {
    const source = String(prompt ?? "");
    const cleanTag = referenceTag(tag);
    if (!cleanTag || !["native", "semantic"].includes(mode)) return source;
    const escaped = escapedPattern(cleanTag);
    if (mode === "semantic") {
        const replacement = taggedPictureReferenceToken(
            cleanTag, "semantic", timestamp,
        );
        return source.replace(
            new RegExp(
                `(^|[^A-Za-z0-9_])@${escaped}(?![A-Za-z0-9_-])`, "gi",
            ),
            (_match, prefix) => `${prefix}${replacement}`,
        );
    }
    const replacement = taggedPictureReferenceToken(cleanTag, "native");
    return source.replace(
        new RegExp(
            `(^|[^A-Za-z0-9_])#${escaped}\\[[0-9]+(?:\\.[0-9]+)?s?\\]`,
            "gi",
        ),
        (_match, prefix) => `${prefix}${replacement}`,
    );
}

export function referenceReplacementToken(
        record, mode = "native", timestamp = 0) {
    if (!record || !["native", "semantic"].includes(mode)) return "";
    if (mode === "semantic") {
        if (record.kind !== "picture" || !record.tag) return "";
        return taggedPictureReferenceToken(record.tag, "semantic", timestamp);
    }
    if (record.nativeToken === null) return "";
    return String(record.nativeToken ?? record.token ?? "");
}

export function replacePromptReferenceOccurrence(
        prompt, start, end, record, mode = "native", timestamp = 0) {
    const source = String(prompt ?? "");
    const first = Number(start);
    const last = Number(end);
    if (!Number.isInteger(first) || !Number.isInteger(last)
            || first < 0 || last < first || last > source.length) {
        return source;
    }
    const replacement = referenceReplacementToken(record, mode, timestamp);
    if (!replacement) return source;
    return `${source.slice(0, first)}${replacement}${source.slice(last)}`;
}

const TRANSPARENT_REROUTE_TYPES = new Set([
    "Reroute",
    "Reroute (rgthree)",
]);
const SUBGRAPH_INPUT_ID = "-10";
const SUBGRAPH_OUTPUT_ID = "-20";

function graphLink(graph, linkId) {
    if (linkId == null) return null;
    return graph?.links?.get?.(linkId) ?? graph?.links?.[linkId] ?? null;
}

function graphLinks(graph) {
    if (graph?.links?.values) return [...graph.links.values()];
    return Object.values(graph?.links ?? {});
}

function isGraphIoNode(id, expected) {
    return String(id) === expected;
}

function subgraphHostNode(graph) {
    if (!graph) return null;
    const root = rootGraph(graph);
    if (!root || graph === root) return null;
    const graphs = [root, ...graphDescendants(root)];
    for (const candidate of graphs) {
        const host = candidate?._nodes?.find((node) => node?.subgraph === graph);
        if (host) return host;
    }
    return null;
}

function connectionFromLink(graph, link) {
    if (!graph || !link) return null;
    if (isGraphIoNode(link.origin_id, SUBGRAPH_INPUT_ID)) {
        const host = subgraphHostNode(graph);
        const input = host?.inputs?.[Number(link.origin_slot ?? 0)];
        const parentLink = graphLink(host?.graph, input?.link);
        return connectionFromLink(host?.graph, parentLink);
    }
    const source = graph.getNodeById?.(link.origin_id) ?? null;
    return source
        ? {source, originSlot: Number(link.origin_slot ?? 0)}
        : null;
}

function subgraphOutputConnection(node, originSlot) {
    const graph = node?.subgraph;
    if (!graph) return null;
    const slotIndex = Number(originSlot ?? 0);
    const slot = graph.outputs?.[slotIndex]
        ?? graph.outputNode?.slots?.[slotIndex];
    const linked = (slot?.linkIds ?? [])
        .map((linkId) => graphLink(graph, linkId))
        .filter(Boolean);
    const candidates = linked.length ? linked : graphLinks(graph).filter(
        (link) => isGraphIoNode(link?.target_id, SUBGRAPH_OUTPUT_ID)
            && Number(link?.target_slot ?? -1) === slotIndex,
    );
    const link = candidates.find(
        (item) => isGraphIoNode(item?.target_id, SUBGRAPH_OUTPUT_ID)
            && Number(item?.target_slot ?? -1) === slotIndex,
    ) ?? candidates[0];
    return connectionFromLink(graph, link);
}

function directInputConnection(node, name = null) {
    const input = name === null
        ? node?.inputs?.find((item) => item.link != null)
        : node?.inputs?.find((item) => item.name === name);
    const link = graphLink(node?.graph, input?.link);
    return connectionFromLink(node?.graph, link);
}

function rootGraph(graph) {
    return graph?.rootGraph ?? graph ?? null;
}

function graphAncestors(graph) {
    if (!graph) return [];
    const root = rootGraph(graph);
    if (!root || graph === root) return root ? [root] : [];

    const result = [graph];
    const seen = new Set(result);
    let current = graph;
    while (current !== root) {
        let parent = null;
        const candidates = [root];
        const subgraphs = root?._subgraphs ?? root?.subgraphs;
        if (subgraphs?.values) candidates.push(...subgraphs.values());
        for (const candidate of candidates) {
            if (!candidate?._nodes || candidate === current) continue;
            if (candidate._nodes.some((node) => node.subgraph === current)) {
                parent = candidate;
                break;
            }
        }
        if (!parent || seen.has(parent)) {
            if (!seen.has(root)) result.push(root);
            break;
        }
        result.push(parent);
        seen.add(parent);
        current = parent;
    }
    return result;
}

function graphDescendants(graph, seen = new Set()) {
    if (!graph?._nodes || seen.has(graph)) return [];
    seen.add(graph);
    const result = [];
    for (const node of graph._nodes) {
        if (!node?.subgraph || seen.has(node.subgraph)) continue;
        result.push(node.subgraph);
        result.push(...graphDescendants(node.subgraph, seen));
    }
    return result;
}

function setGetName(node) {
    return String(node?.widgets?.[0]?.value ?? "");
}

function setNodeFor(getNode) {
    const name = setGetName(getNode);
    if (!name) return null;
    for (const graph of graphAncestors(getNode?.graph)) {
        const setter = graph?._nodes?.find(
            (node) => nodeType(node) === "SetNode" && setGetName(node) === name,
        );
        if (setter) return setter;
    }
    return null;
}

function getNodesFor(setNode) {
    const name = setGetName(setNode);
    if (!name || !setNode?.graph) return [];
    const graphs = [setNode.graph, ...graphDescendants(setNode.graph)];
    return graphs.flatMap((graph) => (graph?._nodes ?? []).filter(
        (node) => nodeType(node) === "GetNode" && setGetName(node) === name,
    ));
}

function transparentInputConnection(node, originSlot = 0) {
    if (node?.subgraph) {
        return subgraphOutputConnection(node, originSlot);
    }
    const type = nodeType(node);
    if (type === "GetNode") {
        const setter = setNodeFor(node);
        return setter ? directInputConnection(setter) : null;
    }
    if (type === "SetNode" || TRANSPARENT_REROUTE_TYPES.has(type)) {
        return directInputConnection(node);
    }
    return null;
}

function resolveInputConnection(connection) {
    let current = connection;
    const seen = new Set();
    while (current?.source && !seen.has(current.source)) {
        seen.add(current.source);
        const next = transparentInputConnection(
            current.source, current.originSlot,
        );
        if (!next) break;
        current = next;
    }
    return current;
}

function inputConnection(node, name) {
    return resolveInputConnection(directInputConnection(node, name));
}

function connectedInputValue(node, name) {
    const connection = inputConnection(node, name);
    if (!connection?.source) return undefined;
    const {source, originSlot} = connection;
    const output = source.outputs?.[originSlot];
    if (output?.value !== undefined) return output.value;
    if (source.output_values?.[originSlot] !== undefined) {
        return source.output_values[originSlot];
    }

    const widgets = source.widgets ?? [];
    const outputName = String(output?.name ?? "").trim().toLowerCase();
    const matching = outputName
        ? widgets.find((widget) => String(
            widget?.name ?? "",
        ).trim().toLowerCase() === outputName)
        : null;
    if (matching?.value !== undefined) return matching.value;

    for (const candidate of ["value", "string", "text", "tag"]) {
        const widget = widgets.find((item) => String(
            item?.name ?? "",
        ).trim().toLowerCase() === candidate);
        if (widget?.value !== undefined) return widget.value;
    }
    if (widgets.length === 1 && widgets[0]?.value !== undefined) {
        return widgets[0].value;
    }
    return undefined;
}

function inputSource(node, name) {
    return inputConnection(node, name)?.source ?? null;
}

function outputTargets(node) {
    const targets = [];
    for (const output of node?.outputs ?? []) {
        for (const linkId of output.links ?? []) {
            const link = graphLink(node?.graph, linkId);
            const target = link ? node.graph?.getNodeById?.(link.target_id) : null;
            if (target) targets.push(target);
        }
    }
    if (nodeType(node) === "SetNode") targets.push(...getNodesFor(node));
    return targets;
}

function findDownstreamType(start, wantedType) {
    const queue = [start];
    const seen = new Set();
    while (queue.length) {
        const node = queue.shift();
        if (!node || seen.has(node)) continue;
        seen.add(node);
        if (node !== start && nodeType(node) === wantedType) return node;
        queue.push(...outputTargets(node));
    }
    return null;
}

export function findScheduledRef2VA(start) {
    return findDownstreamType(start, SCHEDULED_REF2VA_TYPE);
}

export function findTaggedRef2VA(start) {
    return findDownstreamType(start, TAGGED_REF2VA_TYPE);
}

export function findCoreRef2VA(start) {
    return findDownstreamType(start, CORE_REF2VA_TYPE);
}

export function findImageToVideo(start) {
    return findDownstreamType(start, IMAGE_TO_VIDEO_TYPE);
}

export function collectScheduleNodes(wrapper) {
    const result = [];
    const seen = new Set();
    let current = inputSource(wrapper, "reference_schedule");
    while (current && SCHEDULE_TYPES.has(nodeType(current)) && !seen.has(current)) {
        seen.add(current);
        result.unshift(current);
        current = inputSource(current, "previous");
    }
    return result;
}

export function collectTaggedNodes(wrapper) {
    const result = [];
    const seen = new Set();
    let current = inputSource(wrapper, "references");
    if (nodeType(current) === SEMANTIC_ANCHOR_BUNDLE_TYPE) {
        current = inputSource(current, "references");
    }
    while (current && TAGGED_TYPES.has(nodeType(current)) && !seen.has(current)) {
        seen.add(current);
        result.unshift(current);
        current = inputSource(current, "previous");
    }
    return result;
}

export function collectSemanticAnchorNodes(wrapper) {
    const candidates = [
        inputSource(wrapper, "references"),
        inputSource(wrapper, "tagged_references"),
    ];
    const bundle = candidates.find(
        (node) => nodeType(node) === SEMANTIC_ANCHOR_BUNDLE_TYPE,
    );
    if (nodeType(bundle) !== SEMANTIC_ANCHOR_BUNDLE_TYPE) {
        return {bundle: null, nodes: []};
    }
    const nodes = [];
    const seen = new Set();
    let current = inputSource(bundle, "anchors");
    while (current && nodeType(current) === SEMANTIC_PICTURE_ANCHOR_TYPE
            && !seen.has(current)) {
        seen.add(current);
        nodes.unshift(current);
        current = inputSource(current, "previous");
    }
    return {bundle, nodes};
}

export function referenceIsActive(selector, scene) {
    const text = String(selector ?? "").trim().toLowerCase();
    if (!text || text === "all" || text === "*") return true;
    const target = Number(scene);
    if (!Number.isInteger(target) || target < 1) return false;
    return text.split(",").some((piece) => {
        const match = piece.trim().match(/^(\d+)(?::(\d+))?$/);
        if (!match) return false;
        const first = Number(match[1]);
        const last = Number(match[2] ?? match[1]);
        return first <= target && target <= last;
    });
}

function baseRecord(node, kind, scene, inputName, tagName = "tag") {
    const selector = String(widgetValue(node, "scenes", ""));
    return {
        node,
        kind,
        tag: referenceTag(widgetValue(node, tagName, "")),
        selector: selector.trim() || "all",
        active: referenceIsActive(selector, scene),
        source: inputSource(node, inputName),
        label: null,
    };
}

export function scheduledReferenceRecords(editorNode, scene) {
    const wrapper = findScheduledRef2VA(editorNode);
    if (!wrapper) return {wrapper: null, records: []};
    const nodes = collectScheduleNodes(wrapper);
    const pictures = [];
    const videos = [];
    const pairedAudios = [];
    const audios = [];

    for (const node of nodes) {
        const type = nodeType(node);
        if (type === PICTURE_REF_TYPE) {
            pictures.push(baseRecord(node, "picture", scene, "image"));
        } else if (type === VIDEO_REF_TYPE) {
            const video = baseRecord(node, "video", scene, "video");
            videos.push(video);
            const audioSource = inputSource(node, "audio");
            if (audioSource) {
                const explicit = referenceTag(widgetValue(node, "audio_tag", ""));
                pairedAudios.push({
                    node,
                    kind: "audio",
                    tag: explicit || `${video.tag}_audio`,
                    selector: video.selector,
                    active: video.active,
                    source: audioSource,
                    label: null,
                    pairedWith: video,
                });
            }
        } else if (type === AUDIO_REF_TYPE) {
            audios.push(baseRecord(node, "audio", scene, "audio"));
        }
    }

    let ordinal = 0;
    for (const item of pictures) {
        if (item.active) item.label = `<Picture ${++ordinal}>`;
    }
    ordinal = 0;
    for (const item of videos) {
        if (item.active) item.label = `<Video ${++ordinal}>`;
    }
    ordinal = 0;
    // Core Ref2VA numbers paired video soundtracks before standalone audio.
    for (const item of pairedAudios) {
        if (item.active) item.label = `<Audio ${++ordinal}>`;
    }
    for (const item of audios) {
        if (item.active) item.label = `<Audio ${++ordinal}>`;
    }

    return {
        wrapper,
        mode: "scheduled",
        records: [...pictures, ...videos, ...pairedAudios, ...audios]
            .filter((item) => item.tag)
            .map((item) => ({...item, token: `@${item.tag}`})),
    };
}

function promptTagSet(prompt) {
    return new Set([...String(prompt ?? "").matchAll(
        /(?<![A-Za-z0-9_])@([A-Za-z][A-Za-z0-9_-]{0,63})/g,
    )].map((match) => match[1]));
}

function semanticPromptTagSet(prompt) {
    return new Set([...String(prompt ?? "").matchAll(
        /(?<![A-Za-z0-9_])#([A-Za-z][A-Za-z0-9_-]{0,63})\[[0-9]+(?:\.[0-9]+)?s?\]/gi,
    )].map((match) => match[1]));
}

function projectCatalog(node) {
    if (nodeType(node) !== PROJECT_ASSET_MANAGER_TYPE) return null;
    try {
        const value = JSON.parse(String(widgetValue(node, "catalog_json", "")));
        return value && Array.isArray(value.assets) ? value : null;
    } catch (_error) {
        return null;
    }
}

function projectPreviewUrl(catalog, asset, variant = "poster") {
    const query = new URLSearchParams({
        project: String(catalog?.project ?? ""),
        asset: String(asset?.id ?? ""),
        variant,
    });
    return `/minimax_h3_context_loop/project-assets/media?${query}`;
}

export function projectAssetReferenceRecords(manager, prompt = "") {
    const catalog = projectCatalog(manager);
    if (!catalog) return [];
    const used = promptTagSet(prompt);
    const semanticUsed = semanticPromptTagSet(prompt);
    const pictures = [];
    const semanticPictures = [];
    const videos = [];
    const pairedAudios = [];
    const audios = [];
    for (const asset of catalog.assets) {
        if (!asset?.enabled || asset.role === "source_track") continue;
        const tag = referenceTag(asset.tag);
        if (!tag) continue;
        const common = {
            node: manager,
            tag,
            selector: asset.role === "semantic_anchor"
                ? "semantic prompt tag" : "prompt tag",
            source: manager,
            assetId: String(asset.id ?? ""),
            asset,
        };
        if (asset.role === "picture") {
            pictures.push({
                ...common, kind: "picture",
                nativeActive: used.has(tag),
                semanticActive: semanticUsed.has(tag),
                active: used.has(tag) || semanticUsed.has(tag),
                previewUrl: projectPreviewUrl(catalog, asset, "poster"),
            });
        } else if (asset.role === "semantic_anchor") {
            semanticPictures.push({
                ...common, kind: "picture", semanticOnly: true,
                nativeActive: false, semanticActive: semanticUsed.has(tag),
                active: semanticUsed.has(tag),
                previewUrl: projectPreviewUrl(catalog, asset, "poster"),
            });
        } else if (["video", "motion"].includes(asset.role)) {
            const options = asset.options ?? {};
            const hasAudio = Boolean(
                options.use_embedded_audio ?? asset.metadata?.has_audio);
            const audioTag = referenceTag(options.audio_tag) || `${tag}_audio`;
            const video = {
                ...common, kind: "video",
                semanticRole: asset.role === "motion" ? "motion" : "video",
                tagActive: used.has(tag),
                active: used.has(tag) || (hasAudio && used.has(audioTag)),
                previewUrl: projectPreviewUrl(catalog, asset, "preview"),
            };
            videos.push(video);
            if (hasAudio) pairedAudios.push({
                ...common, kind: "audio", tag: audioTag,
                active: video.active, pairedWith: video,
                previewUrl: projectPreviewUrl(catalog, asset, "original"),
            });
        } else if (asset.role === "audio_reference") {
            audios.push({
                ...common, kind: "audio", active: used.has(tag),
                previewUrl: projectPreviewUrl(catalog, asset, "original"),
            });
        }
    }
    let ordinal = 0;
    for (const item of pictures) {
        if (item.nativeActive) item.label = `<Picture ${++ordinal}>`;
    }
    ordinal = 0;
    for (const item of videos) {
        if (item.active) {
            item.sourceLabel = `<Video ${++ordinal}>`;
            item.label = item.sourceLabel;
        }
    }
    const usedSubjects = [...String(prompt ?? "").matchAll(
        /<Subject\s+(\d+)>/gi,
    )].map((match) => Number(match[1]));
    let subjectOrdinal = Math.max(0, ...usedSubjects) + 1;
    for (const item of videos) {
        if (item.active && item.semanticRole === "motion" && item.tagActive) {
            item.label = `<Subject ${subjectOrdinal++}>`;
        }
    }
    ordinal = 0;
    for (const item of pairedAudios) {
        if (item.active) item.label = `<Audio ${++ordinal}>`;
    }
    for (const item of audios) {
        if (item.active) item.label = `<Audio ${++ordinal}>`;
    }
    const anchorMode = String(widgetValue(
        manager, "semantic_anchor_mode", "timestamped_video"));
    ordinal = anchorMode === "picture_storyboard"
        ? pictures.filter((item) => item.nativeActive).length
        : videos.filter((item) => item.active).length;
    for (const item of semanticPictures) {
        if (!item.active) continue;
        item.label = anchorMode === "picture_storyboard"
            ? `<Picture ${++ordinal}>` : `<Video ${++ordinal}>`;
    }
    return [...pictures, ...semanticPictures, ...videos, ...pairedAudios, ...audios]
        .map((item) => ({
            ...item,
            token: item.semanticOnly
                ? taggedPictureReferenceToken(item.tag, "semantic")
                : `@${item.tag}`,
            nativeToken: item.semanticOnly ? null : `@${item.tag}`,
            semanticToken: item.kind === "picture"
                ? taggedPictureReferenceToken(item.tag, "semantic") : null,
            supportsSemantic: item.kind === "picture" && !item.semanticOnly,
        }));
}

export function taggedReferenceRecords(editorNode, prompt = "") {
    const wrapper = findTaggedRef2VA(editorNode);
    if (!wrapper) return {wrapper: null, mode: null, records: []};
    const referenceSource = inputSource(wrapper, "references");
    if (nodeType(referenceSource) === PROJECT_ASSET_MANAGER_TYPE) {
        return {
            wrapper,
            mode: "tagged",
            records: projectAssetReferenceRecords(referenceSource, prompt),
        };
    }
    const nodes = collectTaggedNodes(wrapper);
    const dedicated = collectSemanticAnchorNodes(wrapper);
    const used = promptTagSet(prompt);
    const semanticUsed = semanticPromptTagSet(prompt);
    const pictures = [];
    const videos = [];
    const pairedAudios = [];
    const audios = [];
    const semanticPictures = [];

    for (const node of nodes) {
        const type = nodeType(node);
        if (type === TAGGED_PICTURE_REF_TYPE) {
            const record = baseRecord(node, "picture", 1, "image");
            record.selector = "prompt tag";
            record.nativeActive = used.has(record.tag);
            record.semanticActive = semanticUsed.has(record.tag);
            record.active = record.nativeActive || record.semanticActive;
            pictures.push(record);
        } else if (type === TAGGED_VIDEO_REF_TYPE ||
                type === TAGGED_MOTION_REF_TYPE ||
                type === TAGGED_MOTION_PATH_REF_TYPE ||
                type === TAGGED_MOTION_TIMELINE_REF_TYPE) {
            const pathBacked = type === TAGGED_MOTION_PATH_REF_TYPE;
            const timelineBacked =
                type === TAGGED_MOTION_TIMELINE_REF_TYPE;
            const video = baseRecord(
                node, "video", 1,
                timelineBacked ? "source_timeline"
                    : pathBacked ? "video_path" : "video");
            const nativeVideoSource = pathBacked
                ? inputSource(node, "source_video") : null;
            const timelineSource = timelineBacked
                ? inputSource(node, "source_timeline") : null;
            if (pathBacked) video.source = nativeVideoSource || node;
            if (timelineBacked) video.source = timelineSource || node;
            video.selector = "prompt tag";
            video.semanticRole = (
                type === TAGGED_MOTION_REF_TYPE || pathBacked || timelineBacked)
                ? "motion" : "video";
            video.tagActive = used.has(video.tag);
            const audioSource = inputSource(node, "audio");
            const embeddedAudio = (
                pathBacked && Boolean(
                    widgetValue(node, "use_embedded_audio", true))) || (
                timelineBacked && String(
                    widgetValue(node, "paired_audio", "off")) === "embedded");
            const explicit = referenceTag(widgetValue(node, "audio_tag", ""));
            const audioTag = explicit || `${video.tag}_audio`;
            video.active = video.tagActive || Boolean(
                (audioSource || embeddedAudio) && used.has(audioTag));
            videos.push(video);
            if (audioSource || embeddedAudio) {
                pairedAudios.push({
                    node,
                    kind: "audio",
                    tag: audioTag,
                    selector: "prompt tag",
                    active: video.active,
                    source: audioSource || nativeVideoSource
                        || timelineSource || node,
                    label: null,
                    pairedWith: video,
                });
            }
        } else if (type === TAGGED_AUDIO_REF_TYPE) {
            const record = baseRecord(node, "audio", 1, "audio");
            record.selector = "prompt tag";
            record.active = used.has(record.tag);
            audios.push(record);
        }
    }

    for (const node of dedicated.nodes) {
        const record = baseRecord(node, "picture", 1, "image");
        record.selector = "semantic prompt tag";
        record.nativeActive = false;
        record.semanticActive = semanticUsed.has(record.tag);
        record.active = record.semanticActive;
        record.semanticOnly = true;
        semanticPictures.push(record);
    }

    let ordinal = 0;
    for (const item of pictures) {
        if (item.nativeActive) item.label = `<Picture ${++ordinal}>`;
    }
    ordinal = 0;
    const activeMotionRecords = [];
    for (const item of videos) {
        if (!item.active) continue;
        item.sourceLabel = `<Video ${++ordinal}>`;
        item.label = item.sourceLabel;
        if (item.semanticRole === "motion" && item.tagActive) {
            activeMotionRecords.push(item);
        }
    }
    const usedSubjectNumbers = [...String(prompt ?? "").matchAll(
        /<Subject\s+(\d+)>/gi,
    )].map((match) => Number(match[1]));
    let subjectOrdinal = Math.max(0, ...usedSubjectNumbers) + 1;
    for (const item of activeMotionRecords) {
        item.label = `<Subject ${subjectOrdinal++}>`;
    }
    ordinal = 0;
    for (const item of pairedAudios) {
        if (item.active) item.label = `<Audio ${++ordinal}>`;
    }
    for (const item of audios) {
        if (item.active) item.label = `<Audio ${++ordinal}>`;
    }
    const anchorMode = String(widgetValue(
        dedicated.bundle, "semantic_anchor_mode", "timestamped_video"));
    ordinal = anchorMode === "picture_storyboard"
        ? pictures.filter((item) => item.nativeActive).length
        : videos.filter((item) => item.active).length;
    for (const item of semanticPictures) {
        if (!item.active) continue;
        item.label = anchorMode === "picture_storyboard"
            ? `<Picture ${++ordinal}>` : `<Video ${++ordinal}>`;
    }
    return {
        wrapper,
        mode: "tagged",
        records: [
            ...pictures, ...semanticPictures, ...videos, ...pairedAudios, ...audios,
        ]
            .filter((item) => item.tag)
            .map((item) => ({
                ...item,
                token: item.semanticOnly
                    ? taggedPictureReferenceToken(item.tag, "semantic")
                    : `@${item.tag}`,
                nativeToken: item.semanticOnly ? null : `@${item.tag}`,
                semanticToken: item.kind === "picture"
                    ? taggedPictureReferenceToken(item.tag, "semantic") : null,
                supportsSemantic: item.kind === "picture" && !item.semanticOnly,
            })),
    };
}

function numberedInputRecords(wrapper, pattern, kind, labelKind) {
    const records = [];
    for (const input of wrapper?.inputs ?? []) {
        const match = String(input.name ?? "").match(pattern);
        if (!match || input.link == null) continue;
        const index = Number(match[1]);
        const label = `<${labelKind} ${index + 1}>`;
        records.push({
            node: wrapper,
            kind,
            tag: "",
            token: label,
            selector: "all",
            active: true,
            source: inputSource(wrapper, input.name),
            label,
            index,
            mode: "native",
        });
    }
    records.sort((left, right) => left.index - right.index);
    return records;
}

export function coreReferenceRecords(editorNode) {
    const wrapper = findCoreRef2VA(editorNode);
    if (!wrapper) return {wrapper: null, mode: null, records: []};
    const pictures = numberedInputRecords(
        wrapper, /^ref_images\.ref_image_(\d+)$/, "picture", "Picture");
    const videos = numberedInputRecords(
        wrapper, /^ref_videos\.ref_video_(\d+)$/, "video", "Video");
    const pairedAudios = numberedInputRecords(
        wrapper, /^ref_video_audios\.ref_video_audio_(\d+)$/, "audio", "Audio");
    const audios = numberedInputRecords(
        wrapper, /^ref_audios\.ref_audio_(\d+)$/, "audio", "Audio");
    // Audio labels are shared across video-paired and standalone references.
    [...pairedAudios, ...audios].forEach((item, index) => {
        item.label = `<Audio ${index + 1}>`;
        item.token = item.label;
    });
    return {
        wrapper,
        mode: "native",
        records: [...pictures, ...videos, ...pairedAudios, ...audios],
    };
}

function selectedFrameSource(source, scene) {
    if (nodeType(source) !== FRAME_INDEX_SWITCH_TYPE) return source;
    const frames = [];
    for (let index = 1; index <= 8; index += 1) {
        const frame = inputSource(source, `frame_${index}`);
        if (frame) frames.push(frame);
    }
    if (!frames.length) return source;
    const requested = Math.max(1, Number.isFinite(Number(scene))
        ? Math.trunc(Number(scene)) : 1);
    return frames[(requested - 1) % frames.length];
}

function keyframePreviewSource(connection, role, scene) {
    let source = connection?.source ?? null;
    if (!source) return null;

    // The frame gate exposes both first_frame and last_frame from the same
    // node. Starting a generic upstream search at that node always encounters
    // its opening `image` first, which made Picture 2 preview Picture 1. Follow
    // the input that corresponds to the I2V socket instead.
    if (nodeType(source) === FIRST_SCENE_IMAGE_TYPE) {
        source = inputSource(source, role === "first" ? "image" : "last_frame")
            ?? source;
    }
    return selectedFrameSource(source, scene);
}

export function imageToVideoReferenceRecords(editorNode, scene = 1) {
    const wrapper = findImageToVideo(editorNode);
    if (!wrapper) return {wrapper: null, mode: null, records: []};
    const firstConnection = inputConnection(wrapper, "first_frame");
    const lastConnection = inputConnection(wrapper, "last_frame");
    const firstFrame = firstConnection?.source ?? null;
    const lastFrame = lastConnection?.source ?? null;
    const records = [];
    let firstActive = false;
    if (firstFrame) {
        const firstSceneOnly = nodeType(firstFrame) === FIRST_SCENE_IMAGE_TYPE;
        const active = !firstSceneOnly || Number(scene) === 1;
        firstActive = active;
        records.push({
            node: wrapper,
            kind: "picture",
            tag: "",
            token: "<Picture 1>",
            selector: firstSceneOnly ? "1" : "all",
            active,
            source: keyframePreviewSource(firstConnection, "first", scene),
            label: "<Picture 1>",
            mode: "native",
            role: "first frame",
        });
    }
    if (lastFrame) {
        const ordinal = firstActive ? 2 : 1;
        records.push({
            node: wrapper,
            kind: "picture",
            tag: "",
            token: `<Picture ${ordinal}>`,
            selector: "all",
            active: true,
            source: keyframePreviewSource(lastConnection, "last", scene),
            label: `<Picture ${ordinal}>`,
            mode: "native",
            role: "last frame",
        });
    }
    return {wrapper, mode: "native_keyframes", records};
}

export function referencePreviewRecords(editorNode, scene, {prompt = ""} = {}) {
    const tagged = taggedReferenceRecords(editorNode, prompt);
    if (tagged.wrapper) return tagged;
    const scheduled = scheduledReferenceRecords(editorNode, scene);
    if (scheduled.wrapper) return scheduled;
    const core = coreReferenceRecords(editorNode);
    if (core.wrapper) return core;
    return imageToVideoReferenceRecords(editorNode, scene);
}

export function availableReferenceRecords(
    editorNode, scene, {includeInactive = false, prompt = ""} = {},
) {
    const result = referencePreviewRecords(editorNode, scene, {prompt});
    return {
        ...result,
        records: result.records.filter(
            (record) => record.source && (includeInactive || record.active),
        ),
    };
}
