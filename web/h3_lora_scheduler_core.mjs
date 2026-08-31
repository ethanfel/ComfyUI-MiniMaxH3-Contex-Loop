export const LORA_SCHEDULER_NODE = "MiniMaxH3ChainLoRAScheduler";
export const LORA_ROUTE_LETTERS = Object.freeze([
    ..."abcdefghijklmnopqrstuvwxyz",
]);

export function loraInputRoute(name) {
    const match = /^lora_([a-z])$/.exec(String(name ?? ""));
    return match?.[1] ?? null;
}

export function connectedLoRARoutes(node) {
    const connected = new Set();
    for (const input of node?.inputs ?? []) {
        const route = loraInputRoute(input.name);
        if (route && input.link != null) connected.add(route);
    }
    return LORA_ROUTE_LETTERS.filter((route) => connected.has(route));
}

export function nextLoRARoute(node) {
    const connected = new Set(connectedLoRARoutes(node));
    return LORA_ROUTE_LETTERS.find((route) => !connected.has(route)) ?? null;
}

export function loraRouteLabel(route) {
    return route === "base" ? "Base model" : `LoRA ${String(route).toUpperCase()}`;
}

function nodeType(node) {
    return node?.comfyClass ?? node?.type ?? null;
}

function allNodes(graph, result = []) {
    for (const node of graph?._nodes ?? []) {
        result.push(node);
        if (node.subgraph) allNodes(node.subgraph, result);
    }
    return result;
}

function hasUpstreamNode(start, target) {
    if (!start || !target) return false;
    const queue = [start];
    const seen = new Set();
    while (queue.length) {
        const node = queue.shift();
        if (!node || seen.has(node)) continue;
        if (node === target) return true;
        seen.add(node);
        for (const input of node.inputs ?? []) {
            if (input.link == null) continue;
            const link = node.graph?.links?.[input.link];
            const parent = link
                ? node.graph?.getNodeById?.(link.origin_id) ?? null
                : null;
            if (parent) queue.push(parent);
        }
    }
    return false;
}

export function availableLoRARoutes(
    graph, owners = [], currentRoute = "base",
) {
    const ownerList = owners.filter(Boolean);
    const available = new Set(["base"]);
    for (const scheduler of allNodes(graph)) {
        if (nodeType(scheduler) !== LORA_SCHEDULER_NODE) continue;
        if (ownerList.length && !ownerList.some(
            (owner) => hasUpstreamNode(scheduler, owner),
        )) continue;
        for (const route of connectedLoRARoutes(scheduler)) available.add(route);
    }
    const current = String(currentRoute ?? "base").trim().toLowerCase();
    if (current === "base" || LORA_ROUTE_LETTERS.includes(current)) {
        available.add(current);
    }
    return ["base", ...LORA_ROUTE_LETTERS.filter(
        (route) => available.has(route),
    )];
}
