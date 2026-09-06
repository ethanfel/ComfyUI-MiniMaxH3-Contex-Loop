import assert from "node:assert/strict";
import {
    applyPromptCompletion, promptCompletionItems, promptCompletionQuery,
    promptTokenReplacementQuery, promptBracketReplacementQuery,
    promptRetentionReplacementQuery,
} from "../web/h3_prompt_completion_core.mjs";
import {
    H3_MINIMAX_SPECIAL_TOKENS, H3_VISUAL_RETENTION_MARKERS,
    H3_AUDIO_RETENTION_MARKERS, H3_MODES, analyzeH3Prompt,
} from "../web/h3_prompt_schema_core.mjs";
import {tokenizeRichPrompt, PromptUndoHistory} from "../web/h3_rich_prompt_editor_core.mjs";
import {
    H3_PROMPT_EDITOR_SETTING_IDS as IDS,
    H3_PROMPT_EDITOR_SETTING_DEFINITIONS as DEFINITIONS,
    h3PromptEditorPreferences, isWorkflowSaveShortcut, promptEditorRichText,
} from "../web/h3_prompt_editor_settings_core.mjs";

const records = [
    {kind:"picture", tag:"Hero", token:"@Hero", label:"<Picture 2>", active:true},
    {kind:"picture", token:"@costume", label:null, active:false},
    {kind:"picture", token:"#place", tag:"place", nativeToken:null, semanticToken:"#place", active:false},
    {kind:"audio", token:"@voice", label:"<Audio 1>", active:true},
];
const options = {referenceMode:"tagged"};
const queryAtEnd = (text, extra = {}) => promptCompletionQuery(text, text.length, {records, ...extra});
const labels = (query) => promptCompletionItems(query, records, options).map(item => item.label);
function insert(text, label, extra = {}) {
    const query = queryAtEnd(text, extra);
    const item = promptCompletionItems(query, records, options).find(item => item.label === label);
    assert.ok(item, label);
    return applyPromptCompletion(text, query, item, extra);
}

// Preserve dynamic labels, alias case, semantic-only assets and inactive rules.
assert.deepEqual(labels(queryAtEnd("<Pic")), ["<Picture 2>"]);
assert.deepEqual(labels(queryAtEnd("@")), ["@Hero", "@voice", "@costume"]);
assert.deepEqual(labels(queryAtEnd("#")), ["#Hero", "#costume", "#place"]);
assert.equal(insert("Use @He", "@Hero").text, "Use @Hero");
assert.equal(insert("Use <Pic", "<Picture 2>").text, "Use <Picture 2>");
assert.equal(insert("Use <Pic", "<Picture 2>", {appendSpace:true}).text, "Use <Picture 2> ");
// Never introduce a space between a semantic reference and its timestamp.
assert.equal(insert("Use #He", "#Hero", {appendSpace:true}).text, "Use #Hero");

const pasted = "Keep <Picture 2> and <Subject 1>.";
const pastedQuery = promptCompletionQuery(pasted, 8);
assert.equal(pastedQuery.end, pasted.indexOf(">") + 1);
assert.equal(pastedQuery.replacement, true);
assert.equal(promptCompletionQuery(pasted, 8, {tokenReplacement:false}), null);
const deleteItem = promptCompletionItems(pastedQuery, records, options).at(-1);
assert.equal(deleteItem.deleteToken, true);
assert.equal(applyPromptCompletion(pasted, pastedQuery, deleteItem).text, "Keep and <Subject 1>.");

for (const [token, kind, replacement] of [
    ["(S1)", "(", "(S2)"],
    ["[Shot 1]", "shot", "[Shot 3]"],
    ["[English]", "language", "[French]"],
    ["[reference generation + audio reuse]", "directive", "[audio reference]"],
]) {
    const text = "Keep " + token + " after";
    const query = promptTokenReplacementQuery(text, 5, 5 + token.length);
    assert.equal(query.trigger, kind);
    const item = promptCompletionItems(query, records, options).find(item => item.label === replacement);
    assert.equal(applyPromptCompletion(text, query, item).text, "Keep " + replacement + " after");
}
assert.equal(promptBracketReplacementQuery("a [Shot 3] b", 5).trigger, "shot");
assert.equal(promptBracketReplacementQuery("a [ordinary prose] b", 5), null);
assert.equal(promptTokenReplacementQuery("summary:", 0, 8), null);
// Replacing a single opening boundary must not add a second closing boundary.
for (const token of ["<d>", "<|lyrics_start|>", "<|caption_start|>"]) {
    const query = promptTokenReplacementQuery(token, 0, token.length);
    assert.ok(promptCompletionItems(query).every(item => item.caretOffset == null));
    assert.ok(promptCompletionItems(query).some(item => item.insertText === token));
}
const all = promptCompletionItems(queryAtEnd("", {manual:true}), records, {limit:200});
for (const token of H3_MINIMAX_SPECIAL_TOKENS) {
    assert.ok(all.some(item => item.insertText.includes(token)), token);
}
assert.equal(insert("<|lyr", "<|lyrics_start|>…<|lyrics_end|>").caret, "<|lyrics_start|>".length);

for (const [reference, family] of [
    ["<Subject 1>", "visual"], ["<Picture 2>", "visual"], ["<Video 1>", "visual"],
    ["<Audio 1>", "audio"], ["@Hero", "visual"], ["#place[1.5s]", "visual"],
    ["@voice", "audio"],
]) {
    const prefix = "retention_analysis:\n" + reference + " (appears in [Shot 1]): ";
    const query = queryAtEnd(prefix, {manual:true});
    assert.equal(query.trigger, "retention_" + family);
    const expected = family === "audio" ? H3_AUDIO_RETENTION_MARKERS : H3_VISUAL_RETENTION_MARKERS;
    assert.deepEqual(labels(query), [...expected]);
    const text = prefix + "weak_reference - existing explanation";
    const start = text.indexOf("weak_reference");
    const replacementQuery = promptRetentionReplacementQuery(text, start + 4, records);
    assert.equal(replacementQuery.trigger, query.trigger);
    const item = promptCompletionItems(replacementQuery, records, options)[0];
    assert.equal(applyPromptCompletion(text, replacementQuery, item).text,
        text.replace("weak_reference", expected[0]));
    for (let index = 1; index < "weak_reference".length; index++) {
        assert.equal(promptCompletionQuery(text, start + index, {records}), null);
    }
}
assert.equal(insert("retention_analysis:\n<Picture 2> :wea", "weak_reference").text,
    "retention_analysis:\n<Picture 2>: weak_reference - ");
const beforeProse = "retention_analysis:\n<Picture 2>: wea existing explanation";
const beforeQuery = promptCompletionQuery(beforeProse, beforeProse.indexOf("wea") + 3);
assert.equal(applyPromptCompletion(beforeProse, beforeQuery, promptCompletionItems(beforeQuery)[0]).text,
    "retention_analysis:\n<Picture 2>: weak_reference - existing explanation");
for (const text of [
    "summary:\n<Picture 2>: wea", "retention_analysis:\nordinary prose wea",
    "retention_analysis:\n@unknown: wea", "retention_analysis:\n#voice: wea",
    "retention_analysis:\n@place: wea",
]) assert.equal(queryAtEnd(text), null);
assert.equal(promptRetentionReplacementQuery("detailed_description:\nweak_reference", 30), null);

for (const suffix of ["[Shot 1] At", "[Shot 2] At ", "[Shot 12] at"]) {
    const text = "detailed_description:\n" + suffix;
    const result = insert(text, "At MM:SS.mmm,");
    assert.equal(result.text.slice(result.selectionStart, result.selectionEnd), "00.000");
    assert.equal(result.caret, result.selectionEnd);
    assert.match(result.text, /At 00:00\.000, $/);
}
assert.equal(queryAtEnd("detailed_description:\nAt"), null);
assert.equal(queryAtEnd("detailed_description:\nAt", {manual:true}).trigger, "timestamp");
assert.equal(queryAtEnd("summary:\nAt", {manual:true}).trigger, "manual");

const legacy = "<d>[English] Continue.<cutoff></d>";
assert.ok(analyzeH3Prompt(legacy).problems.some(problem => problem.code === "legacy_token"));
assert.equal(tokenizeRichPrompt(legacy).map(part => part.text).join(""), legacy);
for (const [text, code] of [
    ["<|LYRICS_START|>word<|lyrics_end|>", "special_token"],
    ["<|lyrics_start|>word", "special_pair"],
    ["<|caption_end|>word<|caption_start|>", "special_pair"],
]) assert.ok(analyzeH3Prompt(text).problems.some(problem => problem.code === code));
const validTokens = "<d>[English] (S1) Hi<|cutoff|></d><|lyrics_start|>la<|lyrics_end|><|caption_start|>sky<|caption_end|>";
assert.ok(!analyzeH3Prompt(validTokens).problems.some(problem => ["special_token", "special_pair", "dialogue_flow"].includes(problem.code)));
assert.equal(tokenizeRichPrompt(validTokens).map(part => part.text).join(""), validTokens);
assert.ok(!H3_MODES.some(mode => mode.id === "edit"), "No task-aware mode port");
const compiledLabels = analyzeH3Prompt(
    "subject_definitions:\n<Picture 2> a courier\nretention_analysis:\n<Picture 2>: fully_preserved",
    "ref2va", {connectedReferences:records},
);
assert.ok(!compiledLabels.problems.some(problem => problem.code === "reference"));

const preferences = h3PromptEditorPreferences();
assert.deepEqual(preferences, {
    defaultRichText:true, automaticSuggestions:true, appendCompletionSpace:false, markerReplacement:true,
});
assert.equal(new Set(DEFINITIONS.map(item => item.id)).size, 4);
assert.ok(DEFINITIONS.every(item => !item.id.startsWith("H3PromptIDE.")));
const custom = h3PromptEditorPreferences((id, fallback) =>
    id === IDS.defaultPresentation ? "plain" : fallback);
assert.equal(promptEditorRichText({}, "rich", custom), false);
assert.equal(promptEditorRichText({rich:true}, "rich", custom), true);
assert.equal(promptEditorRichText({rich:false}, "rich", preferences), false);
for (const modifier of ["ctrlKey", "metaKey"]) {
    assert.equal(isWorkflowSaveShortcut({[modifier]:true, key:"s"}), true);
    assert.equal(isWorkflowSaveShortcut({[modifier]:true, key:"s", altKey:true}), false);
    assert.equal(isWorkflowSaveShortcut({[modifier]:true, key:"z"}), false);
}

const sceneOne = new PromptUndoHistory("original");
const sceneTwo = new PromptUndoHistory("");
sceneOne.record(insert("Use <Pic", "<Picture 2>").text, {inputType:"insertReplacementText"});
sceneTwo.record("Second scene", {inputType:"insertReplacementText"});
assert.equal(sceneOne.undo(), "original");
assert.equal(sceneTwo.current, "Second scene");
console.log("Prompt editor improvements: native/tagged completions, markers, settings and compatibility pass");
