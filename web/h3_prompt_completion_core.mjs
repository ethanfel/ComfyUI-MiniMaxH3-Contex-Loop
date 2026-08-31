import {
    effectiveH3Mode,
    H3_ALL_SECTIONS,
    H3_TASK_DIRECTIVES,
    h3SectionsForMode,
} from "./h3_prompt_schema_core.mjs?v=0.5.62";

export const H3_PROMPT_SECTIONS = Object.freeze(
    H3_ALL_SECTIONS.map((section) => `${section}:`),
);

// These are the generation-intent declarations used by the H3 prompt
// formats represented in the shipped workflows. Keep audio reference and
// audio reuse separate: they describe different final-audio behavior.
export const H3_LANGUAGE_MARKERS = Object.freeze([
    "[English]", "[French]", "[Spanish]", "[German]", "[Italian]",
    "[Portuguese]", "[Chinese]", "[Japanese]", "[Korean]", "[Arabic]",
    "[unclear]",
]);

// Keep the chain editor's previously useful, validator-approved combinations
// in addition to the standalone IDE's canonical authoring catalog.
const H3_CHAIN_TASK_DIRECTIVES = Object.freeze([
    "[reference generation + audio reference]",
    "[reference generation + audio reuse]",
    "[video editing + audio reference]",
    "[video editing + audio reuse]",
    "[video continuation + audio reference]",
    "[video continuation + audio reuse]",
]);

export const H3_BRACKET_DIRECTIVES = Object.freeze([
    ...new Set([...H3_TASK_DIRECTIVES, ...H3_CHAIN_TASK_DIRECTIVES]),
    ...Array.from({length:12}, (_, index) => `[Shot ${index + 1}]`),
    ...H3_LANGUAGE_MARKERS,
]);

function clampedCaret(text, caret) {
    const numeric = Number(caret);
    if (!Number.isFinite(numeric)) return text.length;
    return Math.max(0, Math.min(text.length, Math.trunc(numeric)));
}

function specialQuery(before, trigger, pattern) {
    const match = before.match(pattern);
    if (!match) return null;
    const typed = match[1];
    return {
        trigger,
        start: before.length - typed.length,
        end: before.length,
        typed,
        query: typed.slice(1),
        manual: false,
    };
}

/**
 * Return the incomplete H3 construct immediately before the caret.
 *
 * A normal word only opens completion when it starts a line and matches an
 * H3 section prefix. Ctrl/Cmd+Space can request the complete catalog anywhere
 * without consuming surrounding text.
 */
export function promptCompletionQuery(value, caret, {manual = false} = {}) {
    const text = String(value ?? "");
    const position = clampedCaret(text, caret);
    const before = text.slice(0, position);
    const queries = [
        ["@", /(?:^|[^A-Za-z0-9_])(@[A-Za-z0-9_-]*)$/],
        ["#", /(?:^|[^A-Za-z0-9_])(#[A-Za-z0-9_-]*)$/],
        ["<", /(<[^>\n]{0,64})$/],
        ["[", /(\[[^\]\n]{0,96})$/],
        ["(", /(\(S[0-9,]*)$/i],
    ];
    for (const [trigger, pattern] of queries) {
        const result = specialQuery(before, trigger, pattern);
        if (result) return result;
    }

    const section = before.match(/(?:^|\n)([A-Za-z_][A-Za-z_]*)$/);
    if (section) {
        const typed = section[1];
        const lowered = typed.toLowerCase();
        if (H3_PROMPT_SECTIONS.some((item) => item.toLowerCase().startsWith(lowered))) {
            return {
                trigger: "section",
                start: position - typed.length,
                end: position,
                typed,
                query: typed,
                manual: false,
            };
        }
    }

    if (!manual) return null;
    return {
        trigger: "manual",
        start: position,
        end: position,
        typed: "",
        query: "",
        manual: true,
    };
}

function normalizedSearch(value) {
    return String(value ?? "").toLowerCase().replace(/^[#@<\[(]/, "")
        .replace(/[>\])]$/, "").replace(/[_+:-]+/g, " ")
        .replace(/\s+/g, " ").trim();
}

function matchScore(item, query) {
    const wanted = normalizedSearch(query);
    if (!wanted) return 0;
    const candidate = normalizedSearch(item.filterText ?? item.label);
    if (candidate === wanted) return 0;
    if (candidate.startsWith(wanted)) return 1;
    const word = candidate.split(" ").findIndex((part) => part.startsWith(wanted));
    if (word >= 0) return 3 + word;
    const contained = candidate.indexOf(wanted);
    return contained >= 0 ? 20 + contained : null;
}

function uniqueItems(items) {
    const seen = new Set();
    return items.filter((item) => {
        const key = `${item.kind}:${item.insertText}`;
        if (seen.has(key)) return false;
        seen.add(key);
        return true;
    });
}

function referenceItems(records, referenceMode, trigger) {
    const items = [];
    for (const record of records ?? []) {
        const token = String(record?.token ?? "");
        if (trigger === "@") {
            const nativeToken = record?.nativeToken === null
                ? "" : String(record?.nativeToken ?? token);
            if (!nativeToken.startsWith("@")) continue;
            if (!record.active && referenceMode !== "tagged") continue;
            const mapping = record.label && record.label !== nativeToken
                ? ` → ${record.label}` : "";
            items.push({
                id: `alias:${nativeToken}`,
                kind: record.kind || "reference",
                label: nativeToken,
                insertText: nativeToken,
                filterText: nativeToken,
                detail: `${record.active ? "Active" : "Insert to activate"} ${record.kind || "reference"}${mapping}`,
                priority: record.active ? 0 : 1,
            });
        } else if (trigger === "#") {
            if (referenceMode !== "tagged" || record.kind !== "picture") continue;
            const tag = String(record?.tag ?? (
                token.startsWith("@") ? token.slice(1)
                    : token.startsWith("#") ? token.slice(1).split("[")[0] : ""
            )).trim();
            const semanticCapable = Boolean(
                record?.supportsSemantic || record?.semanticOnly
                || record?.semanticToken || token.startsWith("@"),
            );
            if (!tag || !semanticCapable) continue;
            const anchor = `#${tag}[0.00s]`;
            items.push({
                id: `semantic:${tag}`,
                kind: "semantic",
                label: `#${tag}[timestamp]`,
                insertText: anchor,
                filterText: tag,
                detail: record?.semanticOnly
                    ? "Semantic Picture Anchor · Qwen storyboard anchor; type the scene time"
                    : "Tagged Picture · Qwen semantic/storyboard anchor; type the scene time",
                selectionStart: anchor.indexOf("[") + 1,
                selectionEnd: anchor.indexOf("s]"),
                priority: record.active ? 0 : 1,
            });
        }
    }
    return items;
}

function nativeLabelItems(records, referenceMode) {
    const items = [];
    for (const record of records ?? []) {
        if (!record?.active) continue;
        const label = String(record.label ?? record.token ?? "");
        if (!/^<(?:Picture|Video|Audio)\s+\d+>$/i.test(label)) continue;
        const alias = String(record.token ?? "");
        const compiledAlias = alias.startsWith("@")
            ? ` · current compiled label for ${alias}; keep the alias in the prompt`
            : "";
        items.push({
            id: `native:${label}`,
            kind: record.kind || "reference",
            label,
            insertText: label,
            filterText: label,
            detail: `Available ${record.kind || "reference"}${compiledAlias}`,
            priority: referenceMode === "native" || referenceMode === "native_keyframes" ? 0 : 2,
        });
    }
    for (let index = 1; index <= 8; index += 1) {
        const label = `<Subject ${index}>`;
        items.push({
            id: `subject:${index}`,
            kind: "subject",
            label,
            insertText: label,
            filterText: label,
            detail: "H3 reusable subject label",
            priority: 10 + index,
        });
    }
    items.push(
        {
            id: "dialogue:pair",
            kind: "dialogue",
            label: "<d>…</d>",
            insertText: "<d></d>",
            filterText: "d dialogue",
            detail: "H3 spoken dialogue",
            caretOffset: 3,
            priority: 20,
        },
        {
            id: "dialogue:close",
            kind: "dialogue",
            label: "</d>",
            insertText: "</d>",
            filterText: "/d close dialogue",
            detail: "Close an H3 dialogue span",
            priority: 21,
        },
        {
            id: "flow:scene-transition",
            kind: "flow",
            label: "<scenetrans>",
            insertText: "<scenetrans>",
            filterText: "scenetrans scene transition dialogue flow",
            detail: "H3 dialogue-flow marker; keep it inside <d>…</d>",
            priority: 22,
        },
        {
            id: "flow:cutoff",
            kind: "flow",
            label: "<cutoff>",
            insertText: "<cutoff>",
            filterText: "cutoff interrupted dialogue flow",
            detail: "H3 dialogue cutoff marker; keep it inside <d>…</d>",
            priority: 23,
        },
    );
    return items;
}

function speakerItems() {
    const items = Array.from({length:8}, (_, index) => {
        const label = `(S${index + 1})`;
        return {
            id:`speaker:${index + 1}`,
            kind:"speaker",
            label,
            insertText:label,
            filterText:label,
            detail:"H3 dialogue speaker marker",
            priority:index,
        };
    });
    items.push({
        id:"speaker:pair",
        kind:"speaker",
        label:"(S1,S2)",
        insertText:"(S1,S2)",
        filterText:"S1 S2 multiple speakers",
        detail:"H3 simultaneous-speaker marker",
        priority:9,
    });
    return items;
}

function bracketItems() {
    return H3_BRACKET_DIRECTIVES.map((directive, index) => ({
        id: `directive:${directive}`,
        kind: directive.startsWith("[Shot ") ? "shot"
            : H3_LANGUAGE_MARKERS.includes(directive)
              ? "language" : "directive",
        label: directive,
        insertText: directive,
        filterText: directive,
        detail: directive.startsWith("[Shot ")
            ? "H3 shot marker" : H3_LANGUAGE_MARKERS.includes(directive)
              ? "Dialogue language marker" : "H3 summary intent",
        priority: index,
    }));
}

function sectionItems(text = "", mode = "auto") {
    const sections = h3SectionsForMode(effectiveH3Mode(text, mode));
    return sections.map((name, index) => {
        const section = `${name}:`;
        return {
            id: `section:${section}`,
            kind: "section",
            label: section,
            insertText: section,
            filterText: section,
            detail: `Required ${effectiveH3Mode(text, mode).toUpperCase()} section`,
            priority: index,
        };
    });
}

/** Return filtered, ranked completion items for a detected query. */
export function promptCompletionItems(query, records = [], {
    referenceMode = null,
    text = "",
    mode = "auto",
    limit = 40,
} = {}) {
    if (!query) return [];
    let items;
    if (query.trigger === "@" || query.trigger === "#") {
        items = referenceItems(records, referenceMode, query.trigger);
    } else if (query.trigger === "<") {
        items = nativeLabelItems(records, referenceMode);
    } else if (query.trigger === "[") {
        items = bracketItems();
    } else if (query.trigger === "(") {
        items = speakerItems();
    } else if (query.trigger === "section") {
        items = sectionItems(text, mode);
    } else {
        items = [
            ...referenceItems(records, referenceMode, "@"),
            ...nativeLabelItems(records, referenceMode),
            ...bracketItems(),
            ...speakerItems(),
            ...sectionItems(text, mode),
        ];
        if (referenceMode === "tagged") {
            items.push(...referenceItems(records, referenceMode, "#"));
        }
    }

    return uniqueItems(items).map((item) => ({
        item,
        score: matchScore(item, query.query),
    })).filter(({score}) => score != null)
        .sort((left, right) => left.score - right.score
            || (left.item.priority ?? 0) - (right.item.priority ?? 0)
            || left.item.label.localeCompare(right.item.label))
        .slice(0, Math.max(1, Number(limit) || 40))
        .map(({item}) => item);
}

/** Replace the typed completion prefix with the selected item. */
export function applyPromptCompletion(value, query, item) {
    const text = String(value ?? "");
    if (!query || !item) return {text, caret: text.length};
    const start = Math.max(0, Math.min(text.length, Number(query.start) || 0));
    const end = Math.max(start, Math.min(text.length, Number(query.end) || start));
    const insertText = String(item.insertText ?? item.label ?? "");
    const result = text.slice(0, start) + insertText + text.slice(end);
    const relativeCaret = item.caretOffset == null
        ? insertText.length : Math.max(0, Math.min(insertText.length, Number(item.caretOffset) || 0));
    const replacement = {text: result, caret: start + relativeCaret};
    if (item.selectionStart != null && item.selectionEnd != null) {
        replacement.selectionStart = start + Math.max(
            0, Math.min(insertText.length, Number(item.selectionStart) || 0));
        replacement.selectionEnd = start + Math.max(
            0, Math.min(insertText.length, Number(item.selectionEnd) || 0));
        replacement.caret = replacement.selectionEnd;
    }
    return replacement;
}

function completionStyles() {
    if (document.getElementById("h3-prompt-completion-style")) return;
    const style = document.createElement("style");
    style.id = "h3-prompt-completion-style";
    style.textContent = `
      .h3pc-menu { position:fixed; z-index:100200; width:min(440px,calc(100vw - 24px));
        max-height:min(300px,45vh); overflow:auto; padding:5px; border:1px solid #60718c;
        border-radius:8px; background:var(--comfy-menu-bg,#171a20); color:var(--input-text,#eef2f8);
        box-shadow:0 16px 42px rgba(0,0,0,.52); font:12px/1.35 system-ui,sans-serif; }
      .h3pc-menu[hidden] { display:none; }
      .h3pc-option { display:grid; grid-template-columns:auto minmax(0,1fr); gap:2px 8px;
        align-items:center; padding:6px 7px; border-radius:5px; cursor:pointer; }
      .h3pc-option[aria-selected="true"] { background:color-mix(in srgb,#5e8fff 24%,transparent); }
      .h3pc-kind { grid-row:1/3; min-width:26px; padding:2px 4px; border:1px solid #65738a;
        border-radius:4px; color:color-mix(in srgb,var(--input-text,#eef2f8) 72%,transparent);
        text-align:center; font-size:9px; font-weight:750; text-transform:uppercase; }
      .h3pc-label { min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;
        font:600 12px/1.3 ui-monospace,SFMono-Regular,Consolas,monospace; }
      .h3pc-detail { min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;
        color:color-mix(in srgb,var(--input-text,#eef2f8) 58%,transparent); font-size:10px; }
      .h3pc-empty { padding:8px; color:color-mix(in srgb,var(--input-text,#eef2f8) 58%,transparent); }
    `;
    document.head.append(style);
}

function caretAnchor(input) {
    if (input?.isContentEditable) {
        const selection = globalThis.getSelection?.();
        if (selection?.rangeCount && input.contains(selection.anchorNode)) {
            const range = selection.getRangeAt(0).cloneRange();
            range.collapse(true);
            const rect = range.getBoundingClientRect();
            if (rect && (rect.width || rect.height || rect.left || rect.top)) return rect;
        }
    }
    return input?.getBoundingClientRect?.() ?? {left:12, bottom:40, top:12};
}

/**
 * Attach the browser completion popup to either a textarea or contenteditable.
 * The editor owns text persistence; replaceText receives the pure replacement
 * result so both prompt editors can keep their existing Plan/undo behavior.
 */
export function createPromptCompletionController({
    input,
    getText,
    getCaret,
    getRecords = () => [],
    getReferenceMode = () => null,
    getMode = () => "auto",
    replaceText,
    maxItems = 12,
} = {}) {
    if (!input || typeof replaceText !== "function") return null;
    completionStyles();
    const menu = document.createElement("div");
    const menuId = `h3pc-${Math.random().toString(36).slice(2)}`;
    menu.id = menuId;
    menu.className = "h3pc-menu";
    menu.setAttribute("role", "listbox");
    menu.hidden = true;
    menu.addEventListener("pointerdown", (event) => event.stopPropagation());
    menu.addEventListener("click", (event) => event.stopPropagation());
    menu.addEventListener("wheel", (event) => event.stopPropagation());
    document.body.append(menu);
    input.setAttribute("aria-autocomplete", "list");
    input.setAttribute("aria-controls", menuId);
    input.setAttribute("aria-expanded", "false");

    let currentQuery = null;
    let currentItems = [];
    let selected = 0;

    function hide() {
        currentQuery = null;
        currentItems = [];
        selected = 0;
        menu.hidden = true;
        input.setAttribute("aria-expanded", "false");
        input.removeAttribute("aria-activedescendant");
    }

    function position() {
        const anchor = caretAnchor(input);
        const width = Math.min(440, Math.max(240, globalThis.innerWidth - 24));
        const left = Math.max(12, Math.min(globalThis.innerWidth - width - 12, anchor.left ?? 12));
        menu.style.left = `${left}px`;
        const below = (anchor.bottom ?? anchor.top ?? 12) + 6;
        const roomBelow = globalThis.innerHeight - below - 12;
        if (roomBelow >= Math.min(180, menu.offsetHeight || 180)) {
            menu.style.top = `${below}px`;
        } else {
            menu.style.top = `${Math.max(12, (anchor.top ?? below) - menu.offsetHeight - 6)}px`;
        }
    }

    function updateActiveOption() {
        const options = [...menu.querySelectorAll(".h3pc-option")];
        options.forEach((option, index) => option.setAttribute(
            "aria-selected", String(index === selected)));
        const active = options[selected];
        if (active) {
            input.setAttribute("aria-activedescendant", active.id);
            active.scrollIntoView?.({block:"nearest"});
        } else {
            input.removeAttribute("aria-activedescendant");
        }
    }

    function render() {
        menu.replaceChildren();
        currentItems.forEach((item, index) => {
            const option = document.createElement("div");
            option.id = `${menuId}-option-${index}`;
            option.className = "h3pc-option";
            option.setAttribute("role", "option");
            option.setAttribute("aria-selected", String(index === selected));
            const kind = document.createElement("span");
            kind.className = "h3pc-kind";
            kind.textContent = String(item.kind || "H3").slice(0, 3);
            const label = document.createElement("span");
            label.className = "h3pc-label";
            label.textContent = item.label;
            const detail = document.createElement("span");
            detail.className = "h3pc-detail";
            detail.textContent = item.detail || "H3 prompt completion";
            option.append(kind, label, detail);
            option.addEventListener("pointerdown", (event) => event.preventDefault());
            option.addEventListener("mouseenter", () => {
                selected = index;
                updateActiveOption();
            });
            option.addEventListener("click", () => accept(index));
            menu.append(option);
        });
        updateActiveOption();
        menu.hidden = false;
        input.setAttribute("aria-expanded", "true");
        position();
    }

    function refresh({manual = false} = {}) {
        const text = String(getText?.() ?? "");
        const caret = Number(getCaret?.());
        const nextQuery = promptCompletionQuery(text, caret, {manual});
        const previousIdentity = currentQuery
            ? `${currentQuery.trigger}:${currentQuery.start}:${currentQuery.typed}` : "";
        const nextIdentity = nextQuery
            ? `${nextQuery.trigger}:${nextQuery.start}:${nextQuery.typed}` : "";
        if (previousIdentity !== nextIdentity) selected = 0;
        currentQuery = nextQuery;
        currentItems = promptCompletionItems(currentQuery, getRecords(), {
            referenceMode: getReferenceMode(),
            text,
            mode:getMode(),
            limit: maxItems,
        });
        selected = Math.min(selected, Math.max(0, currentItems.length - 1));
        if (!currentQuery || !currentItems.length) hide();
        else render();
        return !menu.hidden;
    }

    function accept(index = selected) {
        const item = currentItems[index];
        if (!item || !currentQuery) return false;
        const result = applyPromptCompletion(getText?.(), currentQuery, item);
        replaceText(result, item);
        hide();
        input.focus();
        return true;
    }

    function move(delta) {
        if (!currentItems.length) return;
        selected = (selected + delta + currentItems.length) % currentItems.length;
        updateActiveOption();
    }

    function handleKeydown(event) {
        if ((event.ctrlKey || event.metaKey) && !event.altKey
                && (event.code === "Space" || event.key === " ")) {
            event.preventDefault();
            refresh({manual:true});
            return true;
        }
        if (menu.hidden) return false;
        if (event.key === "ArrowDown") {
            event.preventDefault(); move(1); return true;
        }
        if (event.key === "ArrowUp") {
            event.preventDefault(); move(-1); return true;
        }
        if (event.key === "Enter" || event.key === "Tab") {
            event.preventDefault(); return accept();
        }
        if (event.key === "Escape") {
            event.preventDefault(); hide(); return true;
        }
        return false;
    }

    const onBlur = () => globalThis.setTimeout?.(() => {
        if (!menu.matches(":hover")) hide();
    }, 100);
    const onClick = () => refresh();
    const onKeyup = (event) => {
        if (["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) refresh();
    };
    const onResize = () => { if (!menu.hidden) position(); };
    input.addEventListener("blur", onBlur);
    input.addEventListener("click", onClick);
    input.addEventListener("keyup", onKeyup);
    globalThis.addEventListener?.("resize", onResize);
    globalThis.addEventListener?.("scroll", onResize, true);

    return {
        refresh,
        hide,
        accept,
        handleKeydown,
        get visible() { return !menu.hidden; },
        destroy() {
            input.removeEventListener("blur", onBlur);
            input.removeEventListener("click", onClick);
            input.removeEventListener("keyup", onKeyup);
            globalThis.removeEventListener?.("resize", onResize);
            globalThis.removeEventListener?.("scroll", onResize, true);
            input.removeAttribute("aria-autocomplete");
            input.removeAttribute("aria-controls");
            input.removeAttribute("aria-expanded");
            input.removeAttribute("aria-activedescendant");
            menu.remove();
        },
    };
}
