export const H3_PROMPT_EDITOR_SETTING_IDS = Object.freeze({
    defaultPresentation:"MiniMaxH3ContextLoop.PromptEditor.Editor.DefaultPresentation",
    automaticSuggestions:"MiniMaxH3ContextLoop.PromptEditor.Completion.AutomaticSuggestions",
    appendCompletionSpace:"MiniMaxH3ContextLoop.PromptEditor.Completion.AppendSpace",
    markerReplacement:"MiniMaxH3ContextLoop.PromptEditor.Interaction.MarkerReplacement",
});

export const H3_PROMPT_EDITOR_SETTING_DEFINITIONS = Object.freeze([
    Object.freeze({
        id:H3_PROMPT_EDITOR_SETTING_IDS.defaultPresentation,
        category:["MiniMax H3 Context Loop", "Prompt editor", "Default presentation"],
        name:"Default presentation for new nodes",
        type:"combo",
        defaultValue:"rich",
        options:[
            {text:"Rich text", value:"rich"},
            {text:"Plain text", value:"plain"},
        ],
        tooltip:"Choose how MiniMax H3 Context Loop nodes without a saved per-node Rich/Plain choice are displayed.",
    }),
    Object.freeze({
        id:H3_PROMPT_EDITOR_SETTING_IDS.automaticSuggestions,
        category:["MiniMax H3 Context Loop", "Prompt editor", "Automatic suggestions"],
        name:"Show suggestions while typing",
        type:"boolean",
        defaultValue:true,
        tooltip:"Show contextual completions automatically. Ctrl/Cmd+Space continues to open completions when this is disabled.",
    }),
    Object.freeze({
        id:H3_PROMPT_EDITOR_SETTING_IDS.appendCompletionSpace,
        category:["MiniMax H3 Context Loop", "Prompt editor", "Trailing space"],
        name:"Append a space after completed symbols",
        type:"boolean",
        defaultValue:false,
        tooltip:"Insert a trailing space after completing reference labels and other sentence-level H3 symbols.",
    }),
    Object.freeze({
        id:H3_PROMPT_EDITOR_SETTING_IDS.markerReplacement,
        category:["MiniMax H3 Context Loop", "Prompt editor", "Marker replacement"],
        name:"Enable marker replacement interactions",
        type:"boolean",
        defaultValue:true,
        tooltip:"Allow new token and Ctrl/Cmd-click marker replacement menus. Existing tagged-reference controls remain available.",
    }),
]);

function readValue(readSetting, id, fallback) {
    const value = typeof readSetting === "function" ? readSetting(id, fallback) : undefined;
    return value == null ? fallback : value;
}

export function h3PromptEditorPreferences(readSetting) {
    const presentation = String(readValue(
        readSetting, H3_PROMPT_EDITOR_SETTING_IDS.defaultPresentation, "rich",
    )).toLowerCase();
    return {
        defaultRichText:presentation !== "plain",
        automaticSuggestions:readValue(
            readSetting, H3_PROMPT_EDITOR_SETTING_IDS.automaticSuggestions, true,
        ) !== false,
        appendCompletionSpace:readValue(
            readSetting, H3_PROMPT_EDITOR_SETTING_IDS.appendCompletionSpace, false,
        ) !== false,
        markerReplacement:readValue(
            readSetting, H3_PROMPT_EDITOR_SETTING_IDS.markerReplacement, true,
        ) !== false,
    };
}

/** Saved per-node choices win; the global setting only supplies a default. */
export function promptEditorRichText(properties, key, preferences) {
    return Object.hasOwn(properties ?? {}, key)
        ? properties[key] !== false : preferences.defaultRichText;
}

export function isWorkflowSaveShortcut(event) {
    return Boolean((event?.ctrlKey || event?.metaKey) && !event.altKey
        && !event.shiftKey && String(event.key ?? "").toLowerCase() === "s");
}
