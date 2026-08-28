export const SCENE_DATA_FIELDS = Object.freeze({
    "RefMod sources": Object.freeze({name: "refmod_sources", type: "H3_REF_LIST"}),
    "Compiled prompt": Object.freeze({name: "compiled_prompt", type: "STRING"}),
    "Active references": Object.freeze({name: "active_references", type: "STRING"}),
    "Reference fingerprint": Object.freeze({name: "reference_fingerprint", type: "STRING"}),
    "Scene prompt": Object.freeze({name: "prompt", type: "STRING"}),
    "Scene number": Object.freeze({name: "clip_index", type: "INT"}),
    "Scene count": Object.freeze({name: "clip_count", type: "INT"}),
    "Shot ID": Object.freeze({name: "shot_id", type: "STRING"}),
    "Noise seed": Object.freeze({name: "noise_seed", type: "INT"}),
    "Raw length": Object.freeze({name: "length", type: "INT"}),
    "Steps": Object.freeze({name: "steps", type: "INT"}),
    "Width": Object.freeze({name: "width", type: "INT"}),
    "Height": Object.freeze({name: "height", type: "INT"}),
    "Audio start": Object.freeze({name: "audio_start", type: "FLOAT"}),
    "Audio duration": Object.freeze({name: "audio_duration", type: "FLOAT"}),
    "Source audio slice": Object.freeze({name: "source_audio_slice", type: "AUDIO"}),
    "Status": Object.freeze({name: "status", type: "STRING"}),
    "Reference image size": Object.freeze({name: "ref_image_size", type: "STRING"}),
    "Reference policy": Object.freeze({name: "reference_policy", type: "STRING"}),
    "Semantic anchor size": Object.freeze({name: "semantic_anchor_size", type: "STRING"}),
    "Semantic anchor mode": Object.freeze({name: "semantic_anchor_mode", type: "STRING"}),
    "Cache for upscale": Object.freeze({name: "cache_for_upscale", type: "BOOLEAN"}),
    "Conditioning backend": Object.freeze({name: "conditioning_backend", type: "STRING"}),
    "Align audio reference": Object.freeze({name: "align_audio_reference", type: "BOOLEAN"}),
});

const FALLBACK_FIELD = "RefMod sources";

export function sceneDataFieldPresentation(field) {
    const label = String(field ?? "");
    return SCENE_DATA_FIELDS[label] ?? SCENE_DATA_FIELDS[FALLBACK_FIELD];
}
