export function formatCheckpointBytes(value) {
    const bytes = Math.max(0, Number(value) || 0);
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(bytes < 10240 ? 1 : 0)} KB`;
    if (bytes < 1024 ** 3) return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
    return `${(bytes / 1024 ** 3).toFixed(2)} GB`;
}

export function checkpointRevisionKey(scene, revision) {
    return `${Number(scene)}:${String(revision ?? "").toLowerCase()}`;
}

export function checkpointRevisionMap(payload) {
    return new Map((payload?.revisions ?? []).map((item) => [
        checkpointRevisionKey(item.scene, item.revision), item,
    ]));
}

export function selectedCheckpointRevision(payload, scene = null, revision = "") {
    const revisions = Array.isArray(payload?.revisions) ? payload.revisions : [];
    const wantedScene = Number(scene);
    const wantedRevision = String(revision ?? "").toLowerCase();
    if (Number.isInteger(wantedScene) && wantedRevision) {
        const exact = revisions.find((item) =>
            Number(item.scene) === wantedScene &&
            String(item.revision).toLowerCase() === wantedRevision);
        if (exact) return exact;
    }
    const sceneRevisions = Number.isInteger(wantedScene)
        ? revisions.filter((item) => Number(item.scene) === wantedScene) : [];
    const deepest = (items) => [...items].sort((left, right) =>
        Number(right.scene) - Number(left.scene) ||
        String(right.created_at).localeCompare(String(left.created_at)))[0];
    return sceneRevisions.find((item) => item.active)
        ?? sceneRevisions.sort((left, right) =>
            String(right.created_at).localeCompare(String(left.created_at)))[0]
        ?? deepest(revisions.filter((item) => item.active))
        ?? deepest(revisions)
        ?? null;
}

export function checkpointBranchRows(payload) {
    const revisions = checkpointRevisionMap(payload);
    return (payload?.branches ?? []).map((branch) => {
        const slot = branch.attribution_slot;
        return {
            ...branch,
            revisions: (branch.path ?? []).map((item) =>
            revisions.get(checkpointRevisionKey(item.scene, item.revision)))
            .filter(Boolean),
            attribution_slot: slot ? {
                ...slot,
                candidates: (slot.candidates ?? []).map((item) =>
                    revisions.get(checkpointRevisionKey(
                        item.scene, item.revision,
                    ))).filter(Boolean),
            } : null,
        };
    });
}

export function checkpointChapterBranchRows(payload, range) {
    const start = Number(range?.start);
    const end = Number(range?.end);
    if (!Number.isFinite(start) || !Number.isFinite(end) || end < start) {
        return checkpointBranchRows(payload);
    }
    const grouped = new Map();
    for (const branch of checkpointBranchRows(payload)) {
        const revisions = branch.revisions.filter((revision) => {
            const scene = Number(revision.scene);
            return scene >= start && scene <= end;
        });
        if (!revisions.length) continue;
        const key = revisions.map((revision) => checkpointRevisionKey(
            revision.scene, revision.revision,
        )).join("|");
        const tip = revisions.at(-1);
        const active = revisions.every((revision) => Boolean(revision.active));
        const slot = branch.attribution_slot;
        const attributionSlot = slot && Number(slot.scene) >= start
            && Number(slot.scene) <= end
            && Number(slot.parent_scene ?? tip.scene) === Number(tip.scene)
            && String(slot.parent_revision ?? "").toLowerCase()
                === String(tip.revision ?? "").toLowerCase()
            ? slot : null;
        const existing = grouped.get(key);
        if (existing) {
            existing.source_branch_ids.push(branch.id);
            if (active) {
                existing.active = true;
                existing.label = "Active branch";
            }
            existing.attribution_slot ??= attributionSlot;
            continue;
        }
        grouped.set(key, {
            ...branch,
            id:`chapter:${String(range?.id ?? `${start}-${end}`)}:${key}`,
            label:active ? "Active branch"
                : `Branch ${String(tip.revision ?? "").slice(0, 8)}`,
            active,
            path:revisions.map((revision) => ({
                scene:Number(revision.scene),
                revision:String(revision.revision ?? "").toLowerCase(),
            })),
            revisions,
            attribution_slot:attributionSlot,
            source_branch_ids:[branch.id],
        });
    }
    return [...grouped.values()].sort((left, right) =>
        Number(Boolean(right.active)) - Number(Boolean(left.active)) ||
        Number(right.revisions.at(-1)?.scene ?? 0)
            - Number(left.revisions.at(-1)?.scene ?? 0));
}

export function checkpointRevisionLineage(payload, selected, range = null) {
    const records = checkpointRevisionMap(payload);
    const start = Math.max(1, Number(range?.start) || 1);
    let cursor = selected ?? null;
    const reversed = [];
    const seen = new Set();
    while (cursor) {
        const scene = Number(cursor.scene);
        if (!Number.isInteger(scene) || scene < start) return [];
        const key = checkpointRevisionKey(cursor.scene, cursor.revision);
        if (seen.has(key)) return [];
        seen.add(key);
        reversed.push({
            scene,
            revision: String(cursor.revision ?? "").toLowerCase(),
        });
        // A chapter start is an editorial branch root. Its immutable parent
        // remains useful provenance, but it does not select the prior
        // chapter's branch.
        if (scene === start) break;
        if (!cursor.parent) break;
        cursor = records.get(checkpointRevisionKey(
            cursor.parent.scene, cursor.parent.revision,
        ));
        if (!cursor) return [];
    }
    const lineage = reversed.reverse();
    if (!lineage.length || lineage[0].scene !== start) return [];
    if (lineage.some((item, index) => item.scene !== start + index)) return [];
    return lineage;
}

export function checkpointProjectLineage(payload, selected, range = null) {
    const start = Math.max(1, Number(range?.start) || 1);
    const chapterLineage = checkpointRevisionLineage(payload, selected, {
        ...range, start,
    });
    if (!chapterLineage.length) return [];
    const revisions = Array.isArray(payload?.revisions) ? payload.revisions : [];
    const prefix = [];
    for (let scene = 1; scene < start; scene += 1) {
        const active = revisions.find((item) =>
            Number(item.scene) === scene && Boolean(item.active));
        if (!active) return [];
        prefix.push({
            scene,
            revision:String(active.revision ?? "").toLowerCase(),
        });
    }
    return [...prefix, ...chapterLineage];
}

export function checkpointSelectionJson(payload, runName, selected, range = null) {
    const normalizedRun = String(runName ?? "").trim();
    const lineage = checkpointProjectLineage(payload, selected, range);
    const start = Math.max(1, Number(range?.start) || 1);
    const end = Math.max(start, Number(range?.end) || Number(selected?.scene) || start);
    return normalizedRun && lineage.length
        ? JSON.stringify({
            run_name:normalizedRun,
            lineage,
            scope_start_scene:start,
            scope_end_scene:end,
        })
        : "";
}

export function checkpointDependencyText(item) {
    const scene = Number(item?.scene) || 0;
    const id = String(item?.scene_id ?? `clip_${String(scene).padStart(4, "0")}`);
    const video = Math.max(0, Number(item?.context_length) || 0);
    const audio = Math.max(0, Number(item?.audio_context_length) || 0);
    const mode = String(item?.continuation_mode ?? "guide");
    const relationship = video || audio
        ? `uses Video ${video}f / Audio ${audio}f via ${mode}`
        : `has a structural continuation edge (Video 0f / Audio 0f)`;
    return `Scene ${scene} · ${id} ${relationship}`;
}

export function checkpointDeletionTitle(preview) {
    if (!preview) return "Select a checkpoint revision to inspect deletion safety.";
    if (preview.allowed) {
        const action = preview.rollback ? "Safe active-tip rollback" : "Safe leaf deletion";
        return `${action} · ${preview.owned_file_count} files · ${formatCheckpointBytes(preview.reclaimed_bytes)}`;
    }
    return (preview.blockers ?? []).join(" ") || "Deletion is blocked.";
}
