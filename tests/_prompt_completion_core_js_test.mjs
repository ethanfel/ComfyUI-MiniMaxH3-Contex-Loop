#!/usr/bin/env node

import assert from "node:assert/strict";
import {
    H3_BRACKET_DIRECTIVES,
    H3_LANGUAGE_MARKERS,
    H3_PROMPT_SECTIONS,
    applyPromptCompletion,
    promptCompletionItems,
    promptCompletionQuery,
} from "../web/h3_prompt_completion_core.mjs";

const records = [
    {kind:"picture", token:"@hero", label:"<Picture 1>", active:true},
    {kind:"picture", token:"@costume", label:null, active:false},
    {kind:"picture", tag:"location", token:"#location",
        nativeToken:null, semanticToken:"#location",
        semanticOnly:true, label:null, active:false},
    {kind:"video", token:"@performance", label:"<Subject 1>", active:true},
    {kind:"audio", token:"@voice", label:"<Audio 1>", active:false},
];

assert.deepEqual(promptCompletionQuery("Use @he", 7), {
    trigger:"@", start:4, end:7, typed:"@he", query:"he", manual:false,
});
assert.equal(promptCompletionQuery("mail@he", 7), null);
assert.equal(promptCompletionQuery("ordinary word", 13), null);
assert.equal(promptCompletionQuery("subj", 4).trigger, "section");
assert.equal(promptCompletionQuery("Use [re", 7).trigger, "[");
assert.equal(promptCompletionQuery("Use <Sub", 8).trigger, "<");
assert.equal(promptCompletionQuery("Use #co", 7).trigger, "#");
assert.equal(promptCompletionQuery("Speaker (S", 10).trigger, "(");

const aliases = promptCompletionItems(
    promptCompletionQuery("@", 1), records, {referenceMode:"tagged"},
);
assert.deepEqual(aliases.map((item) => item.label),
    ["@hero", "@performance", "@costume", "@voice"]);
const scheduledAliases = promptCompletionItems(
    promptCompletionQuery("@", 1), records, {referenceMode:"scheduled"},
);
assert.deepEqual(scheduledAliases.map((item) => item.label), ["@hero", "@performance"]);

const semantic = promptCompletionItems(
    promptCompletionQuery("#co", 3), records, {referenceMode:"tagged"},
);
assert.deepEqual(semantic.map((item) => item.label), ["#costume"]);
assert.equal(semantic[0].insertText, "#costume");
const allSemantic = promptCompletionItems(
    promptCompletionQuery("#", 1), records, {referenceMode:"tagged"},
);
assert.deepEqual(allSemantic.map((item) => item.label), [
    "#hero", "#costume", "#location",
]);
assert.equal(allSemantic[2].detail.startsWith("Semantic Picture Anchor"), true);
assert.equal(promptCompletionItems(
    promptCompletionQuery("@loc", 4), records, {referenceMode:"tagged"},
).length, 0);
assert.deepEqual(applyPromptCompletion("Use #co here", promptCompletionQuery(
    "Use #co here", 7), semantic[0]), {
    text:"Use #costume here",
    caret:12,
});
assert.deepEqual(promptCompletionItems(
    promptCompletionQuery("#", 1), records, {referenceMode:"scheduled"},
), []);

const native = promptCompletionItems(
    promptCompletionQuery("<Pic", 4), [
        {kind:"picture", token:"<Picture 1>", label:"<Picture 1>", active:true},
        {kind:"picture", token:"<Picture 2>", label:"<Picture 2>", active:false},
    ], {referenceMode:"native"},
);
assert.deepEqual(native.map((item) => item.label), ["<Picture 1>"]);
assert.ok(promptCompletionItems(
    promptCompletionQuery("<Sub", 4), records, {referenceMode:"tagged"},
).some((item) => item.label === "<Subject 1>"));
const dialogue = promptCompletionItems(
    promptCompletionQuery("<d", 2), records, {referenceMode:"tagged"},
)[0];
assert.equal(dialogue.insertText, "<d></d>");
assert.equal(dialogue.caretOffset, 3);
assert.ok(promptCompletionItems(
    promptCompletionQuery("<sce", 4), records, {referenceMode:"tagged"},
).some((item) => item.label === "<scenetrans>"));
assert.ok(promptCompletionItems(
    promptCompletionQuery("<cut", 4), records, {referenceMode:"tagged"},
).some((item) => item.label === "<cutoff>"));
assert.equal(promptCompletionItems(
    promptCompletionQuery("(S2", 3), records, {referenceMode:"tagged"},
)[0].label, "(S2)");

const directives = promptCompletionItems(
    promptCompletionQuery("[re", 3), records, {referenceMode:"tagged"},
);
assert.ok(directives.some(
    (item) => item.label === "[reference generation]"));
assert.ok(H3_BRACKET_DIRECTIVES.includes(
    "[video editing + reference generation + audio reference]"));
assert.ok(H3_BRACKET_DIRECTIVES.includes(
    "[reference generation + audio reference]"));
assert.ok(H3_BRACKET_DIRECTIVES.includes("[Shot 12]"));
assert.ok(H3_LANGUAGE_MARKERS.includes("[Japanese]"));
assert.ok(H3_LANGUAGE_MARKERS.includes("[unclear]"));
assert.ok(H3_PROMPT_SECTIONS.includes("integrated_multimodal_description:"));

const sectionQuery = promptCompletionQuery("subject_def", 11);
const section = promptCompletionItems(sectionQuery, records, {
    referenceMode:"tagged", text:"subject_definitions:\n", mode:"ref2va",
})[0];
assert.equal(section.label, "subject_definitions:");
assert.deepEqual(applyPromptCompletion("subject_def", sectionQuery, section), {
    text:"subject_definitions:", caret:20,
});
const aliasQuery = promptCompletionQuery("Use @he now", 7);
const alias = promptCompletionItems(aliasQuery, records, {referenceMode:"tagged"})[0];
assert.deepEqual(applyPromptCompletion("Use @he now", aliasQuery, alias), {
    text:"Use @hero now", caret:9,
});

const manual = promptCompletionQuery("Free text ", 10, {manual:true});
assert.equal(manual.trigger, "manual");
assert.ok(promptCompletionItems(manual, records, {referenceMode:"tagged"}).length > 20);
const fullCatalog = promptCompletionItems(manual, records, {
    referenceMode:"tagged", text:"", mode:"t2va", limit:200,
});
assert.ok(fullCatalog.some((item) => item.label === "(S1)"));
assert.ok(fullCatalog.some((item) => item.label === "[French]"));
assert.ok(fullCatalog.some((item) => item.label === "integrated_multimodal_description:"));
assert.ok(!fullCatalog.some((item) => item.label === "subject_definitions:"));

console.log("H3 prompt completion: contextual queries, valid refs, directives, and replacement pass");
