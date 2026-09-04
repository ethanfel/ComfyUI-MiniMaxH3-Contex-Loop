import assert from "node:assert/strict";
import fs from "node:fs";
import {
    parsePlanJson,
    planToJson,
    promptTextToLines,
    promptValueToText,
} from "../web/h3_chain_plan_core.mjs";

const plan = parsePlanJson(JSON.stringify({
    prompt_prefix: "Shared identity.",
    shots: [
        {id: "one", prompt: "Old one."},
        {id: "two", prompt: ["Old two.", "", "CAMERA: Wide."]},
    ],
}));
plan.shots[1].prompt = promptTextToLines(
    "Continue the action.\n\n<Picture 1> remains the identity reference.",
);
const saved = parsePlanJson(planToJson(plan));
assert.equal(promptValueToText(saved.shots[0].prompt), "Old one.");
assert.equal(
    promptValueToText(saved.shots[1].prompt),
    "Continue the action.\n\n<Picture 1> remains the identity reference.",
);

const source = fs.readFileSync(
    new URL("../web/h3_chain_scene_prompt_editor.js", import.meta.url),
    "utf8",
);
assert.match(source, /MiniMaxH3ChainScenePromptEditor/);
assert.match(source, /item\.name === "plan_json"/);
assert.match(source, /shot\.prompt = promptTextToLines\(textarea\.value\)/);
assert.match(source, /state\.planWidget\.value = value/);
assert.match(source, /_h3ChainEditorRefresh/);
assert.match(source, /Alt\+Left/);
assert.match(source, /Alt\+Right/);
assert.match(source, /@ Reference/);
assert.match(source, /availableReferenceRecords/);
assert.match(source, /does not invent unavailable labels/);
assert.doesNotMatch(source, /Generic native labels are shown instead/);
assert.match(source, /Hover to preview/);
assert.match(source, /Audio never autoplays/);
assert.match(source, /h3sp-ref-preview-media/);
assert.match(source, /function referenceMediaPreview\(record, kind\)/);
assert.match(source, /url: api\.apiURL\(record\.previewUrl\)/);
assert.doesNotMatch(source, /record\.previewUrl\s*\?\s*api\.apiURL/);
assert.match(source, /record\.kind === "picture" \? "image"/);
assert.match(source, /showReferencePreview\(records\[0\], preview\)/);
assert.match(source, /Core Ref2VA references/);
assert.doesNotMatch(source, /event\.key === "#"/);
assert.match(source, /createPromptCompletionController/);
assert.match(source, /createH3PromptSchemaController/);
assert.match(source, /h3_scene_prompt_editor/);
assert.match(source, /getMode:\(\) => state\.schema/);
assert.match(source, /h3sp-token-section/);
assert.match(source, /h3sp-token-flow/);
assert.match(source, /h3sp-token-speaker/);
assert.match(source, /state\.completion\?\.handleKeydown/);
assert.match(source, /restoreTextSelection/);
assert.match(source, /editingSemanticTime/);
assert.match(source, /type @ # < \[/);
assert.doesNotMatch(source, /event\.key === "@"/);
assert.match(source, /FONT_SIZE_PROPERTY/);
assert.match(source, /const PROMPT_ASSISTANT_ENABLED = false;/);
assert.match(source, /if \(PROMPT_ASSISTANT_ENABLED\) \{\s*assistant\.client = new PromptAssistantClient/);
assert.match(source, /getMinHeight: \(\) => PROMPT_ASSISTANT_ENABLED \? 760 : 420/);
assert.match(source, /const minimumHeight = PROMPT_ASSISTANT_ENABLED \? 900 : 620/);
assert.match(source, /currentWidth === 760/);
assert.match(source, /currentHeight === 900/);
assert.match(source, /PromptAssistantClient/);
assert.match(source, /buildPromptAssistantContext/);
assert.match(source, /prompt_assist_result/);
assert.match(source, /Staged .* proposal/);
assert.match(source, /Apply to scene/);
assert.match(source, /Apply anyway/);
assert.match(source, /messagesByProvider/);
assert.match(source, /promptAssistantIdentityKey/);
assert.match(source, /activeWorkflow/);
assert.match(source, /persistPendingRequest/);
assert.match(source, /restorePendingRequest/);
assert.match(source, /Accept only a request this editor incarnation/);
assert.match(source, /assistant\.preparingRequest !== preparation/);
assert.match(source, /Snapshot the selected scene before the asynchronous bridge handshake/);
assert.match(source, /rebaseActivePromptOntoLivePlan/);
assert.match(source, /publishCompanionScene/);
assert.match(source, /prompt_assist_cancel_ack/);
assert.match(source, /empty assistant draft cannot replace/i);
assert.match(source, /Undo last apply/);
assert.match(source, /assistant\.client\?\.close\(\)/);
assert.match(source, /appendScene/);
assert.match(source, /state\.plan\.shots\.push\(makeShot\(state\.plan\.shots\)\)/);
assert.match(source, /Append a new scene and select it/);
assert.match(source, /PRESENTATION_PROPERTY/);
assert.match(source, /state\.decorated \? "Rich text" : "Plain text"/);
assert.match(source, /tokenizeRichPrompt/);
assert.match(source, /h3sp-token-picture/);
assert.match(source, /h3sp-token-audio/);
assert.match(source, /h3sp-token-thumb/);
assert.match(source, /--h3sp-accent: color-mix\(in srgb, var\(--h3sp-text\)/);
assert.match(source, /--h3sp-token-subject: color-mix/);
assert.match(source, /color:var\(--h3sp-token-subject\)/);
assert.doesNotMatch(source, /h3sp-token-subject \{ color:#8ed7a4/);
assert.match(source, /h3sp-popover audio/);
assert.match(source, /mediaElement\.controls = true/);
assert.match(source, /contentEditable = "true"/);
assert.match(source, /convertTaggedPictureReference/);
assert.match(source, /replacePromptReferenceOccurrence/);
assert.match(source, /click to replace or edit/);
assert.match(source, /Time \(sec\)/);
assert.match(source, /makeRichToken\(part, partStart, partEnd\)/);
assert.match(source, /popoverPinned/);
assert.match(source, /taggedPictureReferenceMode/);
assert.match(source, /h3sp-ref-mode/);
assert.match(source, /Use untimed Qwen-only #tag/);
assert.match(source, /referenceButton\.addEventListener\("pointerdown", rememberPromptSelection\)/);
assert.match(source, /document\.activeElement === state\.richEditor/);
assert.match(source, /current\.slice\(0, insertionStart\)/);
assert.match(source, /if \(record\.semanticOnly\) return "semantic"/);
assert.match(source, /editorPlainText\(range\.cloneContents\(\)\)\.length/);
assert.match(source, /maxItems:40/);
assert.match(source, /"keydown", "keyup", "keypress", "copy", "cut", "paste"/);
assert.match(source, /stopPropagation deliberately preserves the browser's default/);
assert.match(source, /selectedEditorPlainText/);
assert.match(source, /data-token value/);
assert.match(source, /setData\("text\/plain", text\)/);
assert.match(source, /richEditor\.addEventListener\("copy"/);
assert.match(source, /richEditor\.addEventListener\("cut"/);
assert.match(source, /PromptUndoHistory/);
assert.match(source, /promptUndoDirection/);
assert.match(source, /applyPromptUndo/);
assert.match(source, /activeSceneIndexAfterRefresh/);
assert.match(source, /ownsPromptHistoryTarget/);
assert.match(source, /stopImmediatePropagation\(\)/);
assert.match(source, /event\.inputType \|\| state\.richInputType/);
assert.match(source, /promptUndoForScene\(shotId, text, \{external:true\}\)/);
assert.match(source, /window\.setInterval\(\(\) => loadPlan\(false\), 500\)/);
assert.match(source, /h3_prompt_history_core\.mjs/);
assert.match(source, /promptRevisionNavigation/);
assert.match(source, /promptRevisionLabel/);
assert.match(source, /promptRevisionTree/);
assert.match(source, /\/minimax_h3_context_loop\/prompt-history/);
assert.match(source, /action: "save"/);
assert.match(source, /action: "activate"/);
assert.match(source, /mutateHistoryRevision\(\s*"label"/);
assert.match(source, /mutateHistoryRevision\(\s*"archive"/);
assert.match(source, /mutateHistoryRevision\(\s*"delete"/);
assert.match(source, /parent → child progression/);
assert.match(source, /Delete unexecuted leaf/);
assert.match(source, /scheduleHistoryDraft\(shotId, textarea\.value\)/);
assert.match(source, /navigation\.position.*navigation\.total/);
assert.match(source, /Loading prompt versions/);
assert.match(source, /runName === state\.lastRunName/);
assert.match(source, /grid-template-columns:minmax\(0,1fr\) auto minmax\(0,1fr\)/);
assert.match(source, /footer\.append\(identity, historyHost, status\)/);
assert.match(source, /PROJECT_ASSET_CATALOG_CHANGED_EVENT/);
assert.match(source, /function refreshReferenceState/);
assert.match(source, /refreshReferenceState\(next\)/);
assert.match(source, /const referenceData = refreshReferenceState\(activePromptText\(\)\)/);
assert.match(source, /onProjectAssetCatalogChanged/);
assert.match(source, /removeEventListener\?\.\(\s*PROJECT_ASSET_CATALOG_CHANGED_EVENT/);
assert.match(source, /const scrollTop = state\.richEditor\.scrollTop/);
assert.match(source, /state\.richEditor\.scrollTop = scrollTop/);
assert.match(source, /target\.focus\(\{preventScroll:true\}\)/);
assert.match(source, /const PROMPT_SYNC_DELAY_MS = 140/);
assert.match(source, /const PROMPT_ANALYSIS_DELAY_MS = 90/);
assert.match(source, /writePlan\(status, \{deferEffects:true\}\)/);
assert.match(source, /function flushPlanEffects\(\)/);
assert.match(source, /state\.planWidget\.value = value/);
assert.match(source, /window\.setTimeout\(\s*flushPlanEffects, PROMPT_SYNC_DELAY_MS/);
assert.match(source, /liveValue !== state\.lastValue && !rebaseActivePromptOntoLivePlan\(\)/);
assert.match(source, /textarea\.addEventListener\("blur", \(\) => \{\s*flushPlanEffects\(\)/);
assert.match(source, /schedulePromptAnalysis\(\)/);
const teardown = source.slice(
    source.indexOf("node.onRemoved = function ()"),
    source.indexOf("node._h3PromptCompanionSetActiveScene"),
);
assert.match(teardown, /state\.disposed = true/);
assert.match(teardown, /state\.planSyncPending = null/);
assert.match(teardown, /state\.history\.pendingDraft = null/);
assert.doesNotMatch(teardown, /flushPlanEffects\(\)/);
assert.doesNotMatch(teardown, /flushPromptAnalysis\(\)/);
assert.doesNotMatch(teardown, /flushHistoryDraft\(\)/);

console.log("H3 Scene Prompt companion: Plan synchronization and controls pass");
