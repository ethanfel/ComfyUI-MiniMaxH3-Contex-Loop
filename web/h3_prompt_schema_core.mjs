export const H3_BASE_SECTIONS = Object.freeze([
    "integrated_multimodal_description",
    "overall_soundscape",
    "non_diegetic_music",
]);

export const H3_REFERENCE_SECTIONS = Object.freeze([
    "subject_definitions",
    "summary",
    "retention_analysis",
    "detailed_description",
    "overall_soundscape",
    "non_diegetic_music",
]);

export const H3_ALL_SECTIONS = Object.freeze([
    ...new Set([...H3_BASE_SECTIONS, ...H3_REFERENCE_SECTIONS]),
]);

// Exact case-sensitive tokens registered by MiniMax-H3's tokenizer_config and
// by ComfyUI PR #15808. Keep this order aligned with tokenizer ids 151669–151675.
export const H3_MINIMAX_SPECIAL_TOKENS = Object.freeze([
    "<d>",
    "</d>",
    "<|cutoff|>",
    "<|lyrics_start|>",
    "<|lyrics_end|>",
    "<|caption_start|>",
    "<|caption_end|>",
]);

export const H3_MODES = Object.freeze([
    {id:"auto", label:"Auto schema"},
    {id:"t2va", label:"T2VA"},
    {id:"i2va", label:"I2VA"},
    {id:"fl2va", label:"FL2VA"},
    {id:"l2va", label:"L2VA"},
    {id:"ref2va", label:"Ref2VA"},
]);

// Common valid summary prefixes from the H3 full-reference format. The
// validator also accepts other non-conflicting combinations of the six
// canonical task types, so this list is an authoring catalog rather than an
// artificial restriction on mixed tasks.
export const H3_TASK_DIRECTIVES = Object.freeze([
    "[keyframe completion]",
    "[reference generation]",
    "[video editing]",
    "[video continuation]",
    "[audio reference]",
    "[audio reuse]",
    "[keyframe completion + reference generation]",
    "[keyframe completion + reference generation + audio reference]",
    "[keyframe completion + reference generation + audio reuse]",
    "[video editing + keyframe completion]",
    "[video editing + keyframe completion + audio reference]",
    "[video editing + keyframe completion + audio reuse]",
    "[video editing + reference generation]",
    "[video editing + reference generation + audio reference]",
    "[video editing + reference generation + audio reuse]",
    "[video continuation + keyframe completion]",
    "[video continuation + keyframe completion + audio reference]",
    "[video continuation + keyframe completion + audio reuse]",
    "[video continuation + reference generation]",
    "[video continuation + reference generation + audio reference]",
    "[video continuation + reference generation + audio reuse]",
]);

export const H3_VISUAL_RETENTION_MARKERS = Object.freeze([
    "fully_preserved",
    "partially_preserved",
    "attribute_transfer",
    "weak_reference",
]);

export const H3_AUDIO_RETENTION_MARKERS = Object.freeze([
    "fully_copy",
    "partially_copy",
    "reference",
    "weak_reference",
]);

const MODE_IDS = new Set(H3_MODES.map((item) => item.id));
const ALIGNMENT_PREFIX = /^(?:For the target video, at 0\.00 seconds into the target video,|How the reference pictures align with the target video —).*$/m;
const SECTION_PATTERN = new RegExp(
    `^(${H3_ALL_SECTIONS.join("|")}):`,
    "gm",
);
const TASK_TYPES = new Set([
    "keyframe completion",
    "reference generation",
    "video editing",
    "video continuation",
    "audio reference",
    "audio reuse",
]);
const TASK_ORDER = new Map([
    ["video editing", 0],
    ["video continuation", 0],
    ["keyframe completion", 1],
    ["reference generation", 2],
    ["audio reference", 3],
    ["audio reuse", 3],
]);
const REFERENCE_LABEL_PATTERN = /<(?:Subject|Picture|Video|Audio)\s+\d+>/g;

export function normalizeH3Mode(value) {
    const mode = String(value ?? "auto").toLowerCase();
    return MODE_IDS.has(mode) ? mode : "auto";
}

export function h3ModeLabel(value) {
    const mode = normalizeH3Mode(value);
    return H3_MODES.find((item) => item.id === mode)?.label ?? "Auto schema";
}

export function detectH3Mode(value) {
    const text = String(value ?? "").trimStart();
    if (/^(?:subject_definitions|summary|retention_analysis|detailed_description):/m.test(text)) {
        return "ref2va";
    }
    const firstLine = text.split("\n", 1)[0];
    if (firstLine.startsWith("For the target video, at 0.00 seconds")) return "i2va";
    if (firstLine.startsWith("How the reference pictures align") && /Picture 2/.test(firstLine)) return "fl2va";
    if (firstLine.startsWith("How the reference pictures align")) return "l2va";
    return "t2va";
}

export function effectiveH3Mode(value, selectedMode = "auto") {
    const selected = normalizeH3Mode(selectedMode);
    return selected === "auto" ? detectH3Mode(value) : selected;
}

export function h3SectionsForMode(mode) {
    return normalizeH3Mode(mode) === "ref2va"
        ? H3_REFERENCE_SECTIONS : H3_BASE_SECTIONS;
}

function normalizedDuration(value) {
    const number = Number(value);
    return Number.isFinite(number) ? Math.max(0.01, number).toFixed(2) : "6.00";
}

function normalizedShot(value) {
    const number = Math.trunc(Number(value));
    return Number.isFinite(number) ? Math.max(1, Math.min(99, number)) : 1;
}

export function h3AlignmentInstruction(mode, {duration = 6, finalShot = 1} = {}) {
    const selected = normalizeH3Mode(mode);
    const seconds = normalizedDuration(duration);
    const shot = normalizedShot(finalShot);
    if (selected === "i2va") {
        return "For the target video, at 0.00 seconds into the target video, <Picture 1> (from [Shot 1]) is fully referenced.";
    }
    if (selected === "fl2va") {
        return `How the reference pictures align with the target video — Picture 1 (from Shot 1) aligns with the 0.00-second mark of the target video; Picture 2 (from Shot ${shot}) aligns with the ${seconds}-second mark of the target video.`;
    }
    if (selected === "l2va") {
        return `How the reference pictures align with the target video — <Picture 1> (from [Shot ${shot}]) aligns with the ${seconds}-second mark of the target video.`;
    }
    return "";
}

export function parseH3Sections(value) {
    const text = String(value ?? "");
    const records = [];
    SECTION_PATTERN.lastIndex = 0;
    for (const match of text.matchAll(SECTION_PATTERN)) {
        records.push({
            name:match[1],
            start:match.index ?? 0,
            headerEnd:(match.index ?? 0) + match[0].length,
        });
    }
    records.forEach((record, index) => {
        record.end = records[index + 1]?.start ?? text.length;
        record.contentStart = record.headerEnd;
        while (record.contentStart < record.end && /[ \t]/.test(text[record.contentStart])) record.contentStart += 1;
        if (text.slice(record.contentStart, record.contentStart + 2) === "\r\n") record.contentStart += 2;
        else if (text[record.contentStart] === "\n") record.contentStart += 1;
        while (record.contentStart < record.end && /[ \t]/.test(text[record.contentStart])) record.contentStart += 1;
    });
    return records;
}

function malformedSectionLines(text) {
    const known = new Set(H3_ALL_SECTIONS);
    const result = [];
    String(text ?? "").split("\n").forEach((line, index) => {
        const candidate = line.match(/^([A-Za-z][A-Za-z _-]+)\s*:/);
        if (!candidate) return;
        const normalized = candidate[1].trim().toLowerCase().replace(/[ -]+/g, "_");
        if (known.has(normalized) && !line.startsWith(`${normalized}:`)) {
            result.push({line:index + 1, expected:`${normalized}:`});
        }
    });
    return result;
}

export function validateH3TaskDirective(value) {
    const text = String(value ?? "").trim();
    const match = text.match(/^\[([^\]]+)\]/);
    if (!match) return {valid:false, message:"summary must begin with a square-bracketed H3 task type"};
    const parts = match[1].split("+").map((item) => item.trim()).filter(Boolean);
    if (!parts.length || parts.some((item) => !TASK_TYPES.has(item))) {
        return {valid:false, message:"summary contains an unknown H3 task type"};
    }
    if (new Set(parts).size !== parts.length) {
        return {valid:false, message:"summary repeats an H3 task type"};
    }
    if (parts.includes("video editing") && parts.includes("video continuation")) {
        return {valid:false, message:"summary cannot combine video editing and video continuation"};
    }
    if (parts.includes("audio reference") && parts.includes("audio reuse")) {
        return {valid:false, message:"summary cannot combine audio reference and audio reuse"};
    }
    const order = parts.map((item) => TASK_ORDER.get(item));
    if (order.some((value, index) => index && value < order[index - 1])) {
        return {valid:false, message:"summary task types are not in canonical H3 order"};
    }
    return {valid:true, directive:`[${parts.join(" + ")}]`};
}

function uniqueMatches(value, pattern) {
    pattern.lastIndex = 0;
    return [...String(value ?? "").matchAll(pattern)]
        .map((match) => match[0])
        .filter((item, index, all) => all.indexOf(item) === index);
}

function analyzeShotBody(body, problems) {
    const shots = [...String(body ?? "").matchAll(/\[Shot\s+(\d+)\]/g)];
    if (!shots.length || Number(shots[0][1]) !== 1) {
        problems.push({severity:"error", code:"shots", message:"The main description must begin its shot sequence with [Shot 1]"});
        return;
    }
    const numbers = shots.map((match) => Number(match[1]));
    if (numbers.some((number, index) => number !== index + 1)) {
        problems.push({severity:"error", code:"shots", message:"Shot markers must be sequential: [Shot 1], [Shot 2], and so on"});
    }
    let previousTime = -1;
    for (let index = 1; index < shots.length; index += 1) {
        const match = shots[index];
        const after = body.slice((match.index ?? 0) + match[0].length);
        const timestamp = after.match(/^ At (\d{2}):(\d{2})\.(\d{3}),/);
        if (!timestamp) {
            problems.push({severity:"error", code:"timestamp", message:`${match[0]} must immediately use At MM:SS.mmm,`});
            continue;
        }
        const seconds = Number(timestamp[1]) * 60 + Number(timestamp[2]) + Number(timestamp[3]) / 1000;
        if (seconds <= previousTime) {
            problems.push({severity:"error", code:"timestamp", message:`${match[0]} cut time must be strictly later than the previous cut`});
        }
        previousTime = seconds;
    }
}

function analyzeDialogue(text, problems) {
    const ranges = [];
    for (const match of String(text ?? "").matchAll(/<d>([\s\S]*?)<\/d>/gi)) {
        const start = match.index ?? 0;
        ranges.push([start, start + match[0].length]);
        const language = match[1].match(/^\s*\[([A-Za-z][^\]]*)\]\s+/);
        if (!language || language[1].toLowerCase() === "unclear") {
            problems.push({severity:"warning", code:"language", message:"Each <d> span should begin with a [Language] marker"});
        }
    }
    for (const match of String(text ?? "").matchAll(/<(?:scenetrans|cutoff)>|<\|cutoff\|>/gi)) {
        const position = match.index ?? 0;
        if (!ranges.some(([start, end]) => start < position && position < end)) {
            problems.push({severity:"error", code:"dialogue_flow", message:`${match[0]} must be inside a <d> dialogue span`});
        }
    }
    if (/<cutoff>/i.test(String(text ?? ""))) {
        problems.push({severity:"warning", code:"legacy_token",
            message:"Use tokenizer-native <|cutoff|> instead of legacy <cutoff>"});
    }
}

function analyzeMiniMaxSpecialTokens(text, problems) {
    const source = String(text ?? "");
    const pattern = /<\/?d>|<\|(?:cutoff|lyrics_start|lyrics_end|caption_start|caption_end)\|>/gi;
    for (const match of source.matchAll(pattern)) {
        const canonical = H3_MINIMAX_SPECIAL_TOKENS.find(
            (token) => token.toLowerCase() === match[0].toLowerCase(),
        );
        if (canonical && match[0] !== canonical) {
            problems.push({severity:"error", code:"special_token",
                message:`Use exact case-sensitive MiniMax token ${canonical}`});
        }
    }

    for (const pair of [
        ["lyrics", "<|lyrics_start|>", "<|lyrics_end|>"],
        ["caption", "<|caption_start|>", "<|caption_end|>"],
    ]) {
        const [kind, start, end] = pair;
        const boundaryPattern = kind === "lyrics"
            ? /<\|lyrics_(?:start|end)\|>/g
            : /<\|caption_(?:start|end)\|>/g;
        let open = false;
        let invalid = false;
        for (const match of source.matchAll(boundaryPattern)) {
            if (match[0] === start) {
                if (open) invalid = true;
                open = true;
            } else if (!open) invalid = true;
            else open = false;
        }
        if (open || invalid) {
            problems.push({severity:"error", code:"special_pair",
                message:`Balance ${start} with ${end} in presentation order`});
        }
    }
}

export function analyzeH3Prompt(value, selectedMode = "auto", options = {}) {
    const text = String(value ?? "");
    const mode = effectiveH3Mode(text, selectedMode);
    const required = h3SectionsForMode(mode);
    const records = parseH3Sections(text);
    const byName = new Map();
    for (const record of records) {
        const entries = byName.get(record.name) ?? [];
        entries.push(record);
        byName.set(record.name, entries);
    }
    const missing = required.filter((section) => !byName.has(section));
    const duplicates = [...byName.entries()].filter(([, entries]) => entries.length > 1)
        .map(([section]) => section);
    const unexpected = [...byName.keys()].filter((section) => !required.includes(section));
    const canonicalIndexes = records.filter((record) => required.includes(record.name))
        .map((record) => required.indexOf(record.name));
    const outOfOrder = canonicalIndexes.some((value, index) => index && value < canonicalIndexes[index - 1]);
    const malformed = malformedSectionLines(text);
    const problems = [];
    for (const section of missing) problems.push({severity:"error", code:"missing", section, message:`Missing ${section}:`});
    for (const section of duplicates) problems.push({severity:"error", code:"duplicate", section, message:`Duplicate ${section}:`});
    for (const section of unexpected) problems.push({severity:"error", code:"unexpected", section, message:`${section}: does not belong in ${h3ModeLabel(mode)}`});
    if (outOfOrder) problems.push({severity:"error", code:"order", message:"H3 sections are not in their required order"});
    for (const item of malformed) problems.push({severity:"error", code:"format", message:`Line ${item.line}: use exact ${item.expected}`});

    const alignment = h3AlignmentInstruction(mode, options);
    const firstLine = text.trimStart().split("\n", 1)[0];
    if (alignment) {
        if (firstLine !== alignment) {
            problems.push({severity:"error", code:"alignment", message:`${h3ModeLabel(mode)} requires its exact first-line picture alignment`});
        }
    } else if (ALIGNMENT_PREFIX.test(firstLine)) {
        problems.push({severity:"error", code:"alignment", message:`${h3ModeLabel(mode)} must not begin with a keyframe-alignment instruction`});
    }

    if (mode === "ref2va" && byName.has("summary")) {
        const summary = byName.get("summary")[0];
        const body = text.slice(summary.contentStart, summary.end).trim();
        const directive = validateH3TaskDirective(body);
        if (!directive.valid) problems.push({severity:"error", code:"summary", section:"summary", message:directive.message});
    }

    for (const section of required) {
        const record = byName.get(section)?.[0];
        if (!record) continue;
        const body = text.slice(record.contentStart, record.end).trim();
        const meaningful = body
            .replace(/^\[reference generation\]\s*$/, "")
            .replace(/^\[Shot 1\]\s*$/, "")
            .trim();
        if (!body || (!meaningful && section !== "non_diegetic_music")) {
            problems.push({severity:"warning", code:"empty", section, message:`${section}: still needs content`});
        }
    }

    const mainSection = mode === "ref2va" ? "detailed_description" : "integrated_multimodal_description";
    const mainRecord = byName.get(mainSection)?.[0];
    if (mainRecord) {
        const body = text.slice(mainRecord.contentStart, mainRecord.end).trim();
        analyzeShotBody(body, problems);
        if (mode === "ref2va") {
            const firstShot = body.indexOf("[Shot 1]");
            if (firstShot <= 0 || !body.slice(0, firstShot).trim()) {
                problems.push({severity:"warning", code:"style", section:mainSection,
                    message:"Ref2VA detailed_description needs 1–2 style sentences before [Shot 1]"});
            }
        }
    }

    const openDialogue = (text.match(/<d>/gi) ?? []).length;
    const closeDialogue = (text.match(/<\/d>/gi) ?? []).length;
    if (openDialogue !== closeDialogue) {
        problems.push({severity:"error", code:"dialogue", message:"Unbalanced <d> and </d> dialogue tags"});
    }
    analyzeDialogue(text, problems);
    analyzeMiniMaxSpecialTokens(text, problems);

    if (mode === "ref2va") {
        const definitions = byName.get("subject_definitions")?.[0];
        const retention = byName.get("retention_analysis")?.[0];
        if (definitions && retention) {
            const definitionBody = text.slice(definitions.contentStart, definitions.end);
            const retentionBody = text.slice(retention.contentStart, retention.end);
            const retained = uniqueMatches(retentionBody, REFERENCE_LABEL_PATTERN);
            const used = uniqueMatches(text.slice(definitions.end), REFERENCE_LABEL_PATTERN);
            const definitionLines = [...definitionBody.matchAll(/^\s*(<(?:Subject|Picture|Video|Audio)\s+\d+>)/gm)]
                .map((match) => match[1]);
            const defined = definitionLines.filter((label, index, all) => all.indexOf(label) === index);
            const duplicateDefinitions = definitionLines.filter((label, index, all) => all.indexOf(label) !== index)
                .filter((label, index, all) => all.indexOf(label) === index);
            for (const label of duplicateDefinitions) {
                problems.push({severity:"error", code:"definition", message:`${label} is defined more than once`});
            }
            for (const label of used.filter((item) => !defined.includes(item))) {
                problems.push({severity:"warning", code:"definition", message:`${label} is used but not defined in subject_definitions`});
            }
            for (const label of defined.filter((item) => !retained.includes(item))) {
                problems.push({severity:"warning", code:"retention", message:`${label} has no retention_analysis entry`});
            }
        }
    }

    const connected = new Set();
    for (const reference of options.connectedReferences ?? []) {
        const candidates = typeof reference === "string"
            ? [reference] : [reference?.token, reference?.label];
        for (const rawToken of candidates) {
            const match = String(rawToken ?? "").match(/^<(Picture|Video|Audio)\s+(\d+)>$/i);
            if (match) connected.add(`<${match[1][0].toUpperCase()}${match[1].slice(1).toLowerCase()} ${Number(match[2])}>`);
        }
    }
    for (const ordinal of options.connectedPictures ?? []) {
        const value = Number(ordinal);
        if (Number.isInteger(value)) connected.add(`<Picture ${value}>`);
    }
    const connectedPictures = new Set(
        [...connected].filter((token) => token.startsWith("<Picture ")),
    );
    const requiredPictures = mode === "fl2va" ? 2 : ["i2va", "l2va"].includes(mode) ? 1 : 0;
    if (requiredPictures && connectedPictures.size < requiredPictures) {
        problems.push({severity:"warning", code:"reference",
            message:`${h3ModeLabel(mode)} expects ${requiredPictures} connected picture reference${requiredPictures === 1 ? "" : "s"}`});
    }
    const usedExternalReferences = [...text.matchAll(/<(Picture|Video|Audio)\s+(\d+)>/gi)]
        .map((match) => `<${match[1][0].toUpperCase()}${match[1].slice(1).toLowerCase()} ${Number(match[2])}>`)
        .filter((token, index, all) => all.indexOf(token) === index);
    for (const token of usedExternalReferences.filter((item) => !connected.has(item))) {
        problems.push({severity:"warning", code:"reference", message:`${token} has no connected authoring reference`});
    }

    return {
        mode,
        required,
        records,
        missing,
        duplicates,
        unexpected,
        outOfOrder,
        problems,
        valid:!problems.some((problem) => problem.severity === "error"),
    };
}

function sectionStarter(section, mode) {
    if (normalizeH3Mode(mode) === "ref2va") {
        if (section === "summary") return "summary:\n[reference generation] ";
        if (section === "detailed_description") return "detailed_description:\n";
        if (section === "non_diegetic_music") return "non_diegetic_music:\nN/A";
        return `${section}:\n`;
    }
    if (section === "integrated_multimodal_description") {
        return "integrated_multimodal_description: [Shot 1] ";
    }
    if (section === "non_diegetic_music") return "non_diegetic_music: N/A";
    return `${section}: `;
}

function cleanJoin(before, inserted, after) {
    const left = before.replace(/[ \t]+$/g, "").replace(/\n*$/g, "");
    const right = after.replace(/^\n*/g, "");
    if (!left) return right ? `${inserted}\n\n${right}` : inserted;
    if (!right) return `${left}\n\n${inserted}`;
    return `${left}\n\n${inserted}\n\n${right}`;
}

export function insertH3Section(value, section, mode) {
    const text = String(value ?? "");
    const selected = normalizeH3Mode(mode) === "auto" ? detectH3Mode(text) : normalizeH3Mode(mode);
    const required = h3SectionsForMode(selected);
    if (!required.includes(section)) return {text, caret:text.length, added:false};
    const records = parseH3Sections(text);
    const existing = records.find((record) => record.name === section);
    if (existing) return {text, caret:existing.contentStart, added:false};
    const wanted = required.indexOf(section);
    const next = records.find((record) => required.indexOf(record.name) > wanted);
    const split = next?.start ?? text.length;
    const starter = sectionStarter(section, selected);
    const result = cleanJoin(text.slice(0, split), starter, text.slice(split));
    const inserted = parseH3Sections(result).find((record) => record.name === section);
    return {text:result, caret:inserted?.contentStart ?? result.length, added:true};
}

function removeKnownAlignment(value) {
    const text = String(value ?? "").trimStart();
    const firstLine = text.split("\n", 1)[0];
    if (!ALIGNMENT_PREFIX.test(firstLine)) return text;
    return text.slice(firstLine.length).replace(/^\s*/, "");
}

export function ensureH3Structure(value, mode, options = {}) {
    const original = String(value ?? "");
    const selected = normalizeH3Mode(mode) === "auto"
        ? detectH3Mode(original) : normalizeH3Mode(mode);
    let text = removeKnownAlignment(original);
    const alignment = h3AlignmentInstruction(selected, options);
    if (alignment) text = text ? `${alignment}\n\n${text}` : alignment;
    const added = [];
    for (const section of h3SectionsForMode(selected)) {
        const result = insertH3Section(text, section, selected);
        text = result.text;
        if (result.added) added.push(section);
    }
    return {text, mode:selected, added, caret:text.length};
}
