// Shared authoring vocabulary for compact 0.5 policy controls. Runtime Python
// remains authoritative; this module prevents the editor, Studio, socket
// presentation, and restore UI from inventing different preset mappings.

export const PRIMARY_TRANSITION_PRESETS = Object.freeze([
    "cut", "guide", "hard_av", "soft_av",
]);

export const GENERATION_SCENE_PROFILES = Object.freeze({
    "Visual continuity": "guide",
    "Independent scenes": "cut",
    "Strong picture + audio continuity": "hard_av",
    "Smooth picture + audio continuity": "soft_av",
});

export const GENERATION_AUDIO_PROFILES = Object.freeze({
    "Generate audio": Object.freeze({
        finalAudio:"generated", sourceReference:"off",
        generatedContinuity:"on", sourceAudioTarget:"off",
    }),
    "Generate fresh audio per scene": Object.freeze({
        finalAudio:"generated", sourceReference:"off",
        generatedContinuity:"off", sourceAudioTarget:"off",
    }),
    "Lip-sync to source audio": Object.freeze({
        finalAudio:"source", sourceReference:"off",
        generatedContinuity:"off", sourceAudioTarget:"locked",
    }),
    "Generate audio from source guide": Object.freeze({
        finalAudio:"generated", sourceReference:"on",
        generatedContinuity:"off", sourceAudioTarget:"off",
    }),
    "Use source soundtrack only": Object.freeze({
        finalAudio:"source", sourceReference:"off",
        generatedContinuity:"off", sourceAudioTarget:"off",
    }),
    "No final audio": Object.freeze({
        finalAudio:"none", sourceReference:"off",
        generatedContinuity:"off", sourceAudioTarget:"off",
    }),
});

export const TRANSITION_PRESETS = Object.freeze({
    cut: Object.freeze({
        continuationMode: "guide", contextLength: 0,
        label: "Visual Cut", description: "No carried picture",
    }),
    guide: Object.freeze({
        continuationMode: "guide", contextLength: 22,
        label: "Guide", description: "22-frame RGB continuation",
    }),
    tone_guide: Object.freeze({
        continuationMode: "tone_carry_guide", contextLength: 22,
        label: "Tone Guide", description: "Experimental corrected RGB guide",
    }),
    latent_guide: Object.freeze({
        continuationMode: "latent_guide", contextLength: 22,
        label: "Latent Guide", description: "Direct generated-latent guide",
    }),
    detail_guide: Object.freeze({
        continuationMode: "tapered_guide", contextLength: 22,
        label: "Detail Guide", description: "Experimental tapered chroma guide",
    }),
    detail_av: Object.freeze({
        continuationMode: "tapered_av", contextLength: 39,
        label: "Detail AV", description: "Experimental latent taper",
    }),
    drift_av: Object.freeze({
        continuationMode: "drift_control_av", contextLength: 39,
        label: "Drift-Control AV", description: "Experimental schedule-matched mask",
    }),
    color_drift_av: Object.freeze({
        continuationMode: "color_stable_drift_av", contextLength: 39,
        label: "Color-Stable Drift AV",
        description: "Drift-Control plus tapered scene-one latent color delta",
    }),
    hard_av: Object.freeze({
        continuationMode: "masked_av", contextLength: 39,
        label: "Hard AV", description: "Protected 39-frame AV prefix",
    }),
    soft_av: Object.freeze({
        continuationMode: "audio_feathered_av", contextLength: 39,
        label: "Soft AV", description: "Hard picture with a short audio release",
    }),
    // Read-only migration alias. Never expose this as a normal selector item.
    audio_feather_av: Object.freeze({
        continuationMode: "audio_feathered_av", contextLength: 39,
        label: "Soft AV", description: "Legacy preset alias",
    }),
});

// Semantic recipes accepted by the composable Advanced Policy node. The
// audio_feather_av spelling is a read-only migration alias for soft_av.
export const ADVANCED_TRANSITION_PRESETS = Object.freeze([
    "cut", "guide", "tone_guide", "latent_guide", "detail_guide",
    "detail_av", "drift_av", "color_drift_av", "hard_av", "soft_av",
]);

export const LEGACY_AUDIO_POLICIES = Object.freeze({
    source_track: Object.freeze(["source", "on", "off"]),
    generated_audio: Object.freeze(["generated", "off", "on"]),
    source_plus_timeline: Object.freeze(["source", "on", "on"]),
});

export function transitionPreset(name) {
    return TRANSITION_PRESETS[String(name)] ?? null;
}

export function transitionPresetName(
    continuationMode, contextLength, {includeAlias = false} = {},
) {
    const mode = String(continuationMode ?? "");
    const context = Number(contextLength);
    for (const [name, preset] of Object.entries(TRANSITION_PRESETS)) {
        if (!includeAlias && name === "audio_feather_av") continue;
        if (preset.continuationMode === mode && preset.contextLength === context) {
            return name;
        }
    }
    return "custom";
}

export function transitionPresetLabel(name) {
    if (name === "inherit") return "Inherit Chain Policy";
    if (name === "custom") return "Custom · Advanced controls";
    return transitionPreset(name)?.label ?? String(name ?? "Unknown");
}

export function sceneTransitionPreset(
    shot, defaultContinuationMode = "guide", defaultContextLength = 22,
    defaultAudioContextLength = defaultContextLength,
) {
    const hasAudioContext = Object.hasOwn(shot ?? {}, "audio_context_length")
        && shot.audio_context_length !== null
        && !(typeof shot.audio_context_length === "string"
            && !String(shot.audio_context_length).trim());
    const hasMode = Object.hasOwn(shot ?? {}, "continuation_mode")
        && shot.continuation_mode !== null
        && !(typeof shot.continuation_mode === "string"
            && !shot.continuation_mode.trim());
    const hasContext = Object.hasOwn(shot ?? {}, "context_length")
        && shot.context_length !== null
        && !(typeof shot.context_length === "string"
            && !String(shot.context_length).trim());
    if (!hasMode && !hasContext && !hasAudioContext) {
        return "inherit";
    }
    const selected = transitionPresetName(
        hasMode ? shot.continuation_mode : defaultContinuationMode,
        hasContext ? shot.context_length : defaultContextLength,
    );
    const effectiveAudioContext = hasAudioContext
        ? Number(shot.audio_context_length) : Number(defaultAudioContextLength);
    if ((hasMode || hasContext || hasAudioContext) && (
        selected === "custom"
        || effectiveAudioContext !== transitionPreset(selected)?.contextLength
    )) return "custom";
    return selected;
}

export function applySceneTransitionPreset(shot, name) {
    if (!shot || typeof shot !== "object" || Array.isArray(shot)) {
        throw new Error("A scene transition requires a scene object.");
    }
    const selected = String(name);
    if (selected === "custom") return shot;
    if (selected === "inherit") {
        delete shot.continuation_mode;
        delete shot.context_length;
        delete shot.audio_context_length;
        return shot;
    }
    if (!PRIMARY_TRANSITION_PRESETS.includes(selected)) {
        throw new Error(`Unknown compact scene transition “${selected}”.`);
    }
    const preset = transitionPreset(selected);
    shot.continuation_mode = preset.continuationMode;
    shot.context_length = preset.contextLength;
    // Keep generated-audio carry on the same tested boundary without
    // exposing a second normal-user duration choice.
    shot.audio_context_length = preset.contextLength;
    return shot;
}

export function primaryTransitionOptions() {
    return PRIMARY_TRANSITION_PRESETS.map((name) => {
        const preset = transitionPreset(name);
        return {
            name,
            label: preset.label,
            description: preset.description,
            continuationMode: preset.continuationMode,
            contextLength: preset.contextLength,
        };
    });
}

const SCENE_AUDIO_AXES = Object.freeze({
    source_reference: Object.freeze(["off", "on"]),
    generated_continuity: Object.freeze(["off", "on"]),
    source_audio_target: Object.freeze(["off", "locked"]),
});

function sceneAudioAxis(shot, key, fallback) {
    const raw = shot?.[key];
    if (raw === undefined || raw === null || String(raw).trim() === ""
            || String(raw).trim().toLowerCase() === "inherit") {
        return fallback;
    }
    const value = String(raw).trim().toLowerCase();
    if (!SCENE_AUDIO_AXES[key]?.includes(value)) {
        throw new Error(`Unknown scene ${key.replaceAll("_", " ")} override “${raw}”.`);
    }
    return value;
}

export function sceneAudioPolicy(shot, planPolicy = {}) {
    const finalAudio = String(planPolicy.finalAudio ?? "generated");
    const sourceReference = sceneAudioAxis(
        shot, "source_reference", String(planPolicy.sourceReference ?? "off"),
    );
    const generatedContinuity = sceneAudioAxis(
        shot, "generated_continuity",
        String(planPolicy.generatedContinuity ?? "on"),
    );
    const sourceAudioTarget = sceneAudioAxis(
        shot, "source_audio_target",
        String(planPolicy.sourceAudioTarget ?? "off"),
    );
    if (sourceAudioTarget === "locked") {
        return {
            finalAudio, sourceReference:"off", generatedContinuity:"off",
            sourceAudioTarget,
        };
    }
    return {
        finalAudio, sourceReference, generatedContinuity, sourceAudioTarget,
    };
}

export function sceneAudioOverride(shot, key) {
    if (!Object.hasOwn(SCENE_AUDIO_AXES, key)) {
        throw new Error(`Unknown scene audio override axis “${key}”.`);
    }
    if (!Object.hasOwn(shot ?? {}, key) || shot[key] === null
            || String(shot[key]).trim() === ""
            || String(shot[key]).trim().toLowerCase() === "inherit") {
        return "inherit";
    }
    return sceneAudioAxis(shot, key, null);
}

export function applySceneAudioOverride(shot, key, value) {
    if (!shot || typeof shot !== "object" || Array.isArray(shot)) {
        throw new Error("A scene audio override requires a scene object.");
    }
    if (!Object.hasOwn(SCENE_AUDIO_AXES, key)) {
        throw new Error(`Unknown scene audio override axis “${key}”.`);
    }
    const selected = String(value ?? "inherit").trim().toLowerCase();
    if (!selected || selected === "inherit") {
        delete shot[key];
        return shot;
    }
    if (!SCENE_AUDIO_AXES[key].includes(selected)) {
        throw new Error(`Unknown scene ${key.replaceAll("_", " ")} override “${value}”.`);
    }
    shot[key] = selected;
    return shot;
}
