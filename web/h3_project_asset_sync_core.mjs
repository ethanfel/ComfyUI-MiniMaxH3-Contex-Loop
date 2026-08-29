export const PROJECT_ASSET_CATALOG_CHANGED_EVENT =
    "minimax-h3-project-assets-changed";

export function publishProjectAssetCatalogChanged(manager, catalog) {
    const project = String(catalog?.project ?? "").trim();
    const revision = String(catalog?.revision ?? "").trim();
    const signature = `${project}\u0000${revision}`;
    if (manager?._h3ProjectAssetPublishedSignature === signature) return false;
    if (manager) manager._h3ProjectAssetPublishedSignature = signature;
    if (typeof globalThis.dispatchEvent !== "function"
            || typeof globalThis.CustomEvent !== "function") return false;
    globalThis.dispatchEvent(new CustomEvent(
        PROJECT_ASSET_CATALOG_CHANGED_EVENT,
        {detail: {manager, project, revision}},
    ));
    return true;
}
