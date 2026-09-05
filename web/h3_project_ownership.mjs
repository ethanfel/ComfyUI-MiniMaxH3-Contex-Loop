import {app} from "/scripts/app.js";
import {api} from "/scripts/api.js";

const ROUTE = "/minimax_h3_context_loop/project-ownership";
const HEARTBEAT_MS = 25000;
const controllers = new Set();
const subscribers = new Set();
const graphIds = new WeakMap();
let graphSerial = 0;

function rootGraph(node) {
    return node?.graph?.rootGraph ?? node?.graph ?? app.graph ?? null;
}

function activeWorkflowDescriptor() {
    const workflow = app.extensionManager?.workflow?.activeWorkflow;
    const key = workflow?.activeState?.id
        ?? workflow?.path
        ?? workflow?.filename
        ?? "legacy-workflow";
    const rawLabel = workflow?.filename
        ?? workflow?.path
        ?? workflow?.activeState?.id
        ?? "ComfyUI workflow";
    const label = String(rawLabel).split(/[\\/]/).at(-1) || "ComfyUI workflow";
    return {key:String(key), label};
}

function ephemeralGraphKey(node) {
    const graph = rootGraph(node);
    if (!graph) return "detached";
    if (!graphIds.has(graph)) graphIds.set(graph, `graph-${++graphSerial}`);
    return graphIds.get(graph);
}

function sessionOwnerId(node) {
    const workflow = activeWorkflowDescriptor();
    const key = `h3-project-owner-v1:${workflow.key}`;
    let value = "";
    try { value = globalThis.sessionStorage?.getItem(key) ?? ""; } catch (_error) { /* unavailable */ }
    if (!/^[A-Za-z0-9._:-]{16,192}$/.test(value)) {
        const random = globalThis.crypto?.randomUUID?.()
            ?? `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
        value = `h3:${random}:${ephemeralGraphKey(node)}`.replace(/[^A-Za-z0-9._:-]/g, "-");
        try { globalThis.sessionStorage?.setItem(key, value); } catch (_error) { /* unavailable */ }
    }
    return {ownerId:value, ownerLabel:workflow.label.slice(0, 120)};
}

async function command(body) {
    const response = await api.fetchApi(ROUTE, {
        method:"POST",
        headers:{"Content-Type":"application/json"},
        body:JSON.stringify(body),
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
        const error = new Error(payload.error || `HTTP ${response.status}`);
        error.payload = payload;
        throw error;
    }
    return payload;
}

function ownershipHeaders(controller) {
    if (!controller?.owned || !Number.isInteger(Number(controller.epoch))) return {};
    return {
        "X-H3-Workflow-Owner": controller.ownerId,
        "X-H3-Ownership-Epoch": String(controller.epoch),
    };
}

function controllerFor(node, runName) {
    const graph = rootGraph(node);
    const wanted = String(runName || "").trim();
    for (const controller of controllers) {
        if (!controller.disposed && controller.graph === graph
                && controller.runName === wanted) return controller;
    }
    return null;
}

export function subscribeProjectOwnership(node, onChange) {
    const subscriber = {node, onChange};
    subscribers.add(subscriber);
    return () => subscribers.delete(subscriber);
}

export function isProjectReadOnlyError(error, runName) {
    const message = String(error?.message ?? error ?? "");
    return message.startsWith(`Project ${runName} is read-only here;`)
        || message.startsWith(`Project ${runName} is protected by workflow ownership.`);
}

function notifyOwnershipSubscribers(controller, payload) {
    for (const subscriber of subscribers) {
        if (rootGraph(subscriber.node) !== controller.graph) continue;
        try { subscriber.onChange(payload); }
        catch (error) { console.warn("H3 ownership UI refresh failed:", error); }
    }
}

export function registerProjectOwnership(node, onChange = null) {
    const identity = sessionOwnerId(node);
    const controller = {
        node,
        graph:rootGraph(node),
        ownerId:identity.ownerId,
        ownerLabel:identity.ownerLabel,
        runName:"",
        status:null,
        owned:false,
        epoch:null,
        timer:null,
        disposed:false,
        async request(action = "status") {
            if (this.disposed || !this.runName) return null;
            const requestedRun = this.runName;
            const payload = await command({
                action, run_name:requestedRun, owner_id:this.ownerId,
                owner_label:this.ownerLabel, epoch:this.epoch,
            });
            if (this.disposed || this.runName !== requestedRun) return payload;
            this.status = payload;
            this.owned = payload.owned_by_requester === true;
            this.epoch = Number.isInteger(Number(payload.epoch))
                ? Number(payload.epoch) : null;
            this.schedule();
            onChange?.(payload);
            notifyOwnershipSubscribers(this, payload);
            return payload;
        },
        async select(runName) {
            const next = String(runName || "").trim();
            if (next === this.runName && this.status) return this.status;
            this.runName = next;
            this.status = null;
            this.owned = false;
            this.epoch = null;
            this.schedule();
            if (!next) {
                onChange?.(null);
                return null;
            }
            return await this.request("claim");
        },
        async force() { return await this.request("force"); },
        async release() {
            const payload = await this.request("release");
            this.owned = false;
            this.schedule();
            return payload;
        },
        schedule() {
            if (this.timer) clearTimeout(this.timer);
            this.timer = null;
            if (!this.disposed && this.owned && this.runName) {
                this.timer = setTimeout(() => {
                    this.request("heartbeat").catch(() => {
                        // A transient connection failure does not surrender
                        // the persistent server lock. Keep the proof and retry;
                        // an actual takeover is learned from the next response
                        // or ownership websocket event.
                        this.schedule();
                    });
                }, HEARTBEAT_MS);
            }
        },
        proof() {
            return this.owned ? {
                owner_id:this.ownerId, epoch:this.epoch,
            } : null;
        },
        dispose() {
            this.disposed = true;
            if (this.timer) clearTimeout(this.timer);
            this.timer = null;
            controllers.delete(this);
        },
    };
    controllers.add(controller);
    return controller;
}

export async function projectMutationOptions(node, runName, options = {}) {
    const controller = controllerFor(node, runName);
    if (!controller) return options;
    if (!controller.owned) await controller.request("claim");
    if (!controller.owned) {
        const owner = controller.status?.owner_label || "another workflow";
        throw new Error(
            `Project ${runName} is read-only here; it is owned by ${owner}. ` +
            "Use Force ownership in this workflow's Project Asset Carousel.",
        );
    }
    return {
        ...options,
        headers:{...(options.headers ?? {}), ...ownershipHeaders(controller)},
    };
}

export async function queuedProjectOwnership(node, runName) {
    const controller = controllerFor(node, runName);
    if (!controller) return "";
    if (!controller.owned) await controller.request("claim");
    if (!controller.owned) {
        const owner = controller.status?.owner_label || "another workflow";
        throw new Error(
            `Project ${runName} is read-only here; it is owned by ${owner}. ` +
            "Use Force ownership in the Project Asset Carousel.",
        );
    }
    return JSON.stringify(controller.proof());
}

api.addEventListener?.("minimax_h3_project_ownership", (event) => {
    const runName = String(event?.detail?.run_name ?? "");
    for (const controller of controllers) {
        if (!controller.disposed && controller.runName === runName) {
            controller.request("status").catch(() => {});
        }
    }
});
