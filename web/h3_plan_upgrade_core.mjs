export const LEGACY_PLAN_NODE = "MiniMaxH3ChainPlan";
export const MODERN_PLAN_NODE = "MiniMaxH3ChainPlanModern";
export const MODERN_PLAN_WIDGET_NAMES = Object.freeze([
    "plan_json", "run_name", "generation_fingerprint", "width", "height",
    "encode_mode", "crop", "default_duration_seconds", "default_steps",
    "base_seed", "segment_crf", "video_blend_frames",
]);

function graphLink(graph, id) {
    if (id == null) return null;
    return graph?.links?.[id] ?? graph?.links?.get?.(id) ?? null;
}

function inputConnected(node, name) {
    const input = node?.inputs?.find((item) => item.name === name);
    return input?.link !== null && input?.link !== undefined;
}

function widgetValue(node, name) {
    return node?.widgets?.find((item) => item.name === name)?.value;
}

function cloneSerializable(value, fallback) {
    try {
        return typeof structuredClone === "function"
            ? structuredClone(value) : JSON.parse(JSON.stringify(value));
    } catch (_error) {
        return fallback;
    }
}

/** Replace one legacy Plan without interpreting its positional widget array.
 *
 * Connections and supported values are resolved by name. The caller owns all
 * confirmation/error UI so this helper remains testable without ComfyUI's DOM.
 */
export function upgradeLegacyPlanNode(node, {
    createNode,
    confirmUpgrade = () => true,
} = {}) {
    const graph = node?.graph;
    if (!graph || typeof createNode !== "function") {
        return {ok:false, reason:"create_unavailable"};
    }
    if (!inputConnected(node, "chain_policy")) {
        return {ok:false, reason:"policy_required"};
    }
    if (!confirmUpgrade()) return {ok:false, reason:"cancelled"};

    const incoming = (node.inputs ?? []).map((input) => {
        const link = graphLink(graph, input.link);
        return link ? {
            name: input.name,
            originId: link.origin_id,
            originSlot: link.origin_slot,
        } : null;
    }).filter(Boolean);
    const outgoing = [];
    for (const output of node.outputs ?? []) {
        for (const linkId of output.links ?? []) {
            const link = graphLink(graph, linkId);
            if (link) outgoing.push({
                name: output.name,
                targetId: link.target_id,
                targetSlot: link.target_slot,
            });
        }
    }

    const replacement = createNode(MODERN_PLAN_NODE);
    if (!replacement) return {ok:false, reason:"modern_unregistered"};
    for (const name of MODERN_PLAN_WIDGET_NAMES) {
        const value = widgetValue(node, name);
        if (value === undefined) continue;
        const widget = replacement.widgets?.find((item) => item.name === name);
        if (widget) widget.value = value;
    }
    replacement.pos = Array.isArray(node.pos) ? [...node.pos] : node.pos;
    replacement.properties = cloneSerializable(node.properties, {});
    replacement.color = node.color;
    replacement.bgcolor = node.bgcolor;
    replacement.mode = node.mode;

    graph.add(replacement);
    if (node.size != null) {
        replacement.setSize?.(
            Array.isArray(node.size) ? [...node.size] : node.size);
    }
    graph.remove(node);

    for (const item of incoming) {
        const origin = graph.getNodeById?.(item.originId);
        const targetSlot = replacement.inputs?.findIndex(
            (input) => input.name === item.name);
        if (origin && targetSlot >= 0) {
            origin.connect?.(item.originSlot, replacement, targetSlot);
        }
    }
    for (const item of outgoing) {
        const target = graph.getNodeById?.(item.targetId);
        const originSlot = replacement.outputs?.findIndex(
            (output) => output.name === item.name);
        if (target && originSlot >= 0) {
            replacement.connect?.(originSlot, target, item.targetSlot);
        }
    }
    graph.setDirtyCanvas?.(true, true);
    return {ok:true, node:replacement};
}
