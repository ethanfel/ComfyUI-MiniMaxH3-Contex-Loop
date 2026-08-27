import assert from "node:assert/strict";
import {
    availableReferenceRecords,
    collectScheduleNodes,
    collectSemanticAnchorNodes,
    collectTaggedNodes,
    convertTaggedPictureReference,
    coreReferenceRecords,
    findScheduledRef2VA,
    findTaggedRef2VA,
    imageToVideoReferenceRecords,
    referencePreviewRecords,
    referenceIsActive,
    referenceReplacementToken,
    replacePromptReferenceOccurrence,
    scheduledReferenceRecords,
    taggedReferenceRecords,
    taggedPictureReferenceMode,
    taggedPictureReferenceToken,
} from "../web/h3_reference_preview_core.mjs";

assert.equal(taggedPictureReferenceToken("@hero", "native"), "@hero");
assert.equal(
    taggedPictureReferenceToken("hero", "semantic", 2.5),
    "#hero[2.50s]",
);
assert.equal(taggedPictureReferenceMode("Use @hero.", "hero"), "native");
assert.equal(
    taggedPictureReferenceMode("Use #hero[2.50s].", "hero"),
    "semantic",
);
assert.equal(
    taggedPictureReferenceMode("Use @hero then #hero[2.50s].", "hero"),
    "mixed",
);
assert.equal(
    convertTaggedPictureReference(
        "Use @hero, but keep @heroine and mail x@hero.",
        "hero", "semantic", 1.25,
    ),
    "Use #hero[1.25s], but keep @heroine and mail x@hero.",
);
assert.equal(
    convertTaggedPictureReference(
        "Use #hero[0.00s], then #hero[2.5].", "hero", "native",
    ),
    "Use @hero, then @hero.",
);
const heroRecord = {
    kind: "picture", tag: "hero", token: "@hero", nativeToken: "@hero",
};
const alternateRecord = {
    kind: "picture", tag: "alternate", token: "@alternate",
    nativeToken: "@alternate",
};
assert.equal(
    referenceReplacementToken(alternateRecord, "semantic", 3.125),
    "#alternate[3.13s]",
);
assert.equal(
    replacePromptReferenceOccurrence(
        "Use @hero, then @hero.", 16, 21, alternateRecord, "native",
    ),
    "Use @hero, then @alternate.",
);
assert.equal(
    replacePromptReferenceOccurrence(
        "Use #hero[1.00s] now.", 4, 16, heroRecord, "semantic", 2.5,
    ),
    "Use #hero[2.50s] now.",
);
assert.equal(
    replacePromptReferenceOccurrence(
        "Use @hero.", -1, 9, alternateRecord, "native",
    ),
    "Use @hero.",
);
assert.equal(
    referenceReplacementToken(
        {kind: "audio", tag: "voice", token: "@voice"}, "semantic", 1,
    ),
    "",
);
assert.equal(
    referenceReplacementToken({
        kind: "picture", tag: "only", token: "#only[0.00s]",
        nativeToken: null, semanticOnly: true,
    }, "native"),
    "",
);

function makeNode(id, type, widgets = {}) {
    return {
        id,
        type,
        title: type,
        widgets: Object.entries(widgets).map(([name, value]) => ({name, value})),
        inputs: [],
        outputs: [{name: "output", links: []}],
    };
}

const graph = {
    _nodes: [],
    links: {},
    getNodeById(id) { return this._nodes.find((node) => node.id === id); },
};
let nextLink = 1;
function add(node) {
    node.graph = graph;
    graph._nodes.push(node);
    return node;
}
function connect(source, target, targetName, sourceSlot = 0) {
    const id = nextLink++;
    while (source.outputs.length <= sourceSlot) {
        source.outputs.push({name: `output_${source.outputs.length}`, links: []});
    }
    source.outputs[sourceSlot].links.push(id);
    target.inputs.push({name: targetName, link: id});
    graph.links[id] = {
        origin_id: source.id,
        origin_slot: sourceSlot,
        target_id: target.id,
        target_slot: target.inputs.length - 1,
    };
}

function connectExistingInput(source, target, targetName, sourceSlot = 0) {
    const targetSlot = target.inputs.findIndex(
        (input) => input.name === targetName,
    );
    assert.notEqual(targetSlot, -1);
    const id = nextLink++;
    source.outputs[sourceSlot].links.push(id);
    target.inputs[targetSlot].link = id;
    graph.links[id] = {
        origin_id: source.id,
        origin_slot: sourceSlot,
        target_id: target.id,
        target_slot: targetSlot,
    };
}

function makeSubgraph(host, inputs = [], outputs = []) {
    const subgraph = {
        _nodes: [],
        links: {},
        inputs: inputs.map((name) => ({name, linkIds: []})),
        outputs: outputs.map((name) => ({name, linkIds: []})),
        rootGraph: graph,
        getNodeById(id) {
            return this._nodes.find((node) => node.id === id);
        },
    };
    host.subgraph = subgraph;
    host.inputs = inputs.map((name) => ({name, link: null}));
    host.outputs = outputs.map((name) => ({name, links: []}));
    return subgraph;
}

function addInside(subgraph, node) {
    node.graph = subgraph;
    subgraph._nodes.push(node);
    return node;
}

function connectInside(source, target, targetName, sourceSlot = 0) {
    const owner = source.graph;
    const id = nextLink++;
    while (source.outputs.length <= sourceSlot) {
        source.outputs.push({name: `output_${source.outputs.length}`, links: []});
    }
    source.outputs[sourceSlot].links.push(id);
    target.inputs.push({name: targetName, link: id});
    owner.links[id] = {
        origin_id: source.id,
        origin_slot: sourceSlot,
        target_id: target.id,
        target_slot: target.inputs.length - 1,
    };
}

function connectSubgraphInput(subgraph, inputSlot, target, targetName) {
    const id = nextLink++;
    target.inputs.push({name: targetName, link: id});
    subgraph.inputs[inputSlot].linkIds.push(id);
    subgraph.links[id] = {
        origin_id: -10,
        origin_slot: inputSlot,
        target_id: target.id,
        target_slot: target.inputs.length - 1,
    };
}

function connectSubgraphOutput(subgraph, source, sourceSlot, outputSlot) {
    const id = nextLink++;
    source.outputs[sourceSlot].links.push(id);
    subgraph.outputs[outputSlot].linkIds.push(id);
    subgraph.links[id] = {
        origin_id: source.id,
        origin_slot: sourceSlot,
        target_id: -20,
        target_slot: outputSlot,
    };
}

const editor = add(makeNode(1, "MiniMaxH3ChainScenePromptEditor"));
const relay = add(makeNode(2, "MiniMaxH3ChainCurrent"));
const wrapper = add(makeNode(3, "MiniMaxH3ScheduledReferenceToVideo"));
const firstImage = add(makeNode(4, "LoadImage", {image: "first.png"}));
const secondImage = add(makeNode(5, "LoadImage", {image: "second.png"}));
const audioFile = add(makeNode(6, "LoadAudio", {audio: "score.wav"}));
const first = add(makeNode(7, "MiniMaxH3ScheduledPictureReference", {
    tag: "picture_1", scenes: "1",
}));
const second = add(makeNode(8, "MiniMaxH3ScheduledPictureReference", {
    tag: "picture_2", scenes: "",
}));
const audio = add(makeNode(9, "MiniMaxH3ScheduledAudioReference", {
    tag: "score", scenes: "all",
}));

connect(editor, relay, "state");
connect(relay, wrapper, "prompt");
connect(firstImage, first, "image");
connect(first, second, "previous");
connect(secondImage, second, "image");
connect(second, audio, "previous");
connect(audioFile, audio, "audio");
connect(audio, wrapper, "reference_schedule");

assert.equal(findScheduledRef2VA(editor), wrapper);
assert.deepEqual(collectScheduleNodes(wrapper), [first, second, audio]);
assert.equal(referenceIsActive("1,3:5", 4), true);
assert.equal(referenceIsActive("1,3:5", 2), false);

const sceneOne = scheduledReferenceRecords(editor, 1).records;
assert.deepEqual(sceneOne.map(({tag, label, active}) => ({tag, label, active})), [
    {tag: "picture_1", label: "<Picture 1>", active: true},
    {tag: "picture_2", label: "<Picture 2>", active: true},
    {tag: "score", label: "<Audio 1>", active: true},
]);
const sceneTwo = scheduledReferenceRecords(editor, 2).records;
assert.deepEqual(sceneTwo.map(({tag, label, active}) => ({tag, label, active})), [
    {tag: "picture_1", label: null, active: false},
    {tag: "picture_2", label: "<Picture 1>", active: true},
    {tag: "score", label: "<Audio 1>", active: true},
]);
assert.deepEqual(
    availableReferenceRecords(editor, 2).records.map(({tag}) => tag),
    ["picture_2", "score"],
);
assert.deepEqual(
    availableReferenceRecords(editor, 2, {includeInactive: true})
        .records.map(({tag}) => tag),
    ["picture_1", "picture_2", "score"],
);

const taggedEditor = add(makeNode(30, "MiniMaxH3ChainScenePromptEditor"));
const taggedRelay = add(makeNode(31, "MiniMaxH3ChainCurrent"));
const taggedWrapper = add(makeNode(32, "MiniMaxH3TaggedReferenceToVideo"));
const taggedPromptSet = add(makeNode(64, "SetNode", {
    Constant: "tagged_prompt",
}));
const taggedPromptGet = add(makeNode(65, "GetNode", {
    Constant: "tagged_prompt",
}));
const taggedReferenceReroute = add(makeNode(66, "Reroute"));
const taggedReferenceSet = add(makeNode(67, "SetNode", {
    Constant: "tagged_references",
}));
const taggedReferenceGet = add(makeNode(68, "GetNode", {
    Constant: "tagged_references",
}));
const taggedImageA = add(makeNode(33, "LoadImage", {image: "face.png"}));
const taggedImageB = add(makeNode(34, "LoadImage", {image: "look.png"}));
const taggedVideoFile = add(makeNode(35, "LoadVideo", {video: "motion.mp4"}));
const taggedVideoAudio = add(makeNode(36, "LoadAudio", {audio: "motion.wav"}));
const taggedPictureA = add(makeNode(37, "MiniMaxH3TaggedPictureReference", {
    tag: "hero_face",
}));
const taggedPictureTagText = add(makeNode(169, "PrimitiveNode", {
    value: "connected_face",
}));
taggedPictureTagText.outputs[0].name = "STRING";
const taggedPictureTagSet = add(makeNode(170, "SetNode", {
    Constant: "picture_tag_text",
}));
const taggedPictureTagGet = add(makeNode(171, "GetNode", {
    Constant: "picture_tag_text",
}));
const taggedPictureB = add(makeNode(38, "MiniMaxH3TaggedPictureReference", {
    tag: "hero_look",
}));
const taggedVideo = add(makeNode(39, "MiniMaxH3TaggedVideoReference", {
    tag: "performance", audio_tag: "performance_audio",
}));
const taggedMotionVideo = add(makeNode(60, "LoadVideo", {
    video: "motion-role.mp4",
}));
const taggedMotion = add(makeNode(61, "MiniMaxH3TaggedMotionReference", {
    tag: "motion", target_subject: "<Subject 1> and <Subject 2>",
}));
const taggedLazyLoader = add(makeNode(63, "MiniMaxH3LazyMotionAVLoader", {
    video_path: "/media/lazy-motion.mkv",
}));
const taggedLazyMotion = add(makeNode(
    62, "MiniMaxH3TaggedMotionReferencePath", {
        video_path: "", tag: "lazy_motion",
        target_subject: "<Subject 1>", use_embedded_audio: true,
        audio_tag: "lazy_motion_audio",
    },
));
connect(taggedEditor, taggedPromptSet, "*");
connect(taggedPromptGet, taggedRelay, "state");
connect(taggedRelay, taggedWrapper, "prompt");
connect(taggedImageA, taggedPictureA, "image");
connect(taggedPictureTagText, taggedPictureTagSet, "*");
connect(taggedPictureTagGet, taggedPictureA, "tag");
connect(taggedPictureA, taggedPictureB, "previous");
connect(taggedImageB, taggedPictureB, "image");
connect(taggedPictureB, taggedVideo, "previous");
connect(taggedVideoFile, taggedVideo, "video");
connect(taggedVideoAudio, taggedVideo, "audio");
connect(taggedVideo, taggedMotion, "previous");
connect(taggedMotionVideo, taggedMotion, "video");
connect(taggedMotion, taggedLazyMotion, "previous");
connect(taggedLazyLoader, taggedLazyMotion, "source_video");
connect(taggedLazyMotion, taggedReferenceReroute, "*");
connect(taggedReferenceReroute, taggedReferenceSet, "*");
connect(taggedReferenceGet, taggedWrapper, "references");

assert.equal(findTaggedRef2VA(taggedEditor), taggedWrapper);
assert.deepEqual(
    collectTaggedNodes(taggedWrapper),
    [taggedPictureA, taggedPictureB, taggedVideo, taggedMotion,
        taggedLazyMotion],
);
const promptRefs = taggedReferenceRecords(
    taggedEditor,
    "<Subject 1> and <Subject 2> use @hero_look, " +
    "@performance_audio, @motion, and @lazy_motion.",
).records;
assert.deepEqual(
    promptRefs.map(({tag, label, active, sourceLabel}) => ({
        tag, label, active, sourceLabel,
    })),
    [
        {tag: "connected_face", label: null, active: false,
            sourceLabel: undefined},
        {tag: "hero_look", label: "<Picture 1>", active: true,
            sourceLabel: undefined},
        {tag: "performance", label: "<Video 1>", active: true,
            sourceLabel: "<Video 1>"},
        {tag: "motion", label: "<Subject 3>", active: true,
            sourceLabel: "<Video 2>"},
        {tag: "lazy_motion", label: "<Subject 4>", active: true,
            sourceLabel: "<Video 3>"},
        {tag: "performance_audio", label: "<Audio 1>", active: true,
            sourceLabel: undefined},
        {tag: "lazy_motion_audio", label: "<Audio 2>", active: true,
            sourceLabel: undefined},
    ],
);
assert.equal(
    promptRefs.find(({tag}) => tag === "lazy_motion").source,
    taggedLazyLoader,
);
assert.equal(
    promptRefs.find(({tag}) => tag === "lazy_motion_audio").source,
    taggedLazyLoader,
);
const semanticPromptRefs = taggedReferenceRecords(
    taggedEditor, "Use #connected_face[1.50s].",
).records;
const semanticHero = semanticPromptRefs.find(
    ({tag}) => tag === "connected_face",
);
assert.equal(semanticHero.active, true);
assert.equal(semanticHero.nativeActive, false);
assert.equal(semanticHero.semanticActive, true);
assert.equal(semanticHero.label, null);
assert.equal(semanticHero.nativeToken, "@connected_face");
assert.equal(semanticHero.semanticToken, "#connected_face[0.00s]");
assert.equal(semanticHero.supportsSemantic, true);
assert.equal(referencePreviewRecords(
    taggedEditor, 2, {prompt: "Use @hero_look."}).mode, "tagged");
assert.deepEqual(
    availableReferenceRecords(taggedEditor, 2, {
        prompt: "Use @hero_look.",
    }).records.map(({tag}) => tag),
    ["hero_look"],
);
assert.deepEqual(
    availableReferenceRecords(taggedEditor, 2, {
        prompt: "Use @hero_look.", includeInactive: true,
    }).records.map(({tag}) => tag),
    ["connected_face", "hero_look", "performance", "motion", "lazy_motion",
        "performance_audio", "lazy_motion_audio"],
);

const semanticEditor = add(makeNode(80, "MiniMaxH3ChainScenePromptEditor"));
const semanticRelay = add(makeNode(81, "MiniMaxH3ChainCurrent"));
const semanticWrapper = add(makeNode(82, "MiniMaxH3TaggedReferenceToVideo"));
const nativeImage = add(makeNode(83, "LoadImage", {image: "native.png"}));
const nativePicture = add(makeNode(84, "MiniMaxH3TaggedPictureReference", {
    tag: "native",
}));
const semanticImageA = add(makeNode(85, "LoadImage", {image: "beat-a.png"}));
const semanticImageB = add(makeNode(86, "LoadImage", {image: "beat-b.png"}));
const semanticAnchorA = add(makeNode(
    87, "MiniMaxH3SemanticPictureAnchor", {tag: "beat_a"},
));
const semanticAnchorB = add(makeNode(
    88, "MiniMaxH3SemanticPictureAnchor", {tag: "beat_b"},
));
const semanticBundle = add(makeNode(
    89, "MiniMaxH3SemanticAnchorBundle", {
        semantic_anchor_size: "768",
        semantic_anchor_mode: "picture_storyboard",
    },
));
connect(semanticEditor, semanticRelay, "state");
connect(semanticRelay, semanticWrapper, "prompt");
connect(nativeImage, nativePicture, "image");
connect(semanticImageA, semanticAnchorA, "image");
connect(semanticAnchorA, semanticAnchorB, "previous");
connect(semanticImageB, semanticAnchorB, "image");
connect(semanticAnchorB, semanticBundle, "anchors");
connect(nativePicture, semanticBundle, "references");
connect(semanticBundle, semanticWrapper, "references", 0);

assert.deepEqual(collectTaggedNodes(semanticWrapper), [nativePicture]);
assert.deepEqual(
    collectSemanticAnchorNodes(semanticWrapper).nodes,
    [semanticAnchorA, semanticAnchorB],
);
const separateRecords = taggedReferenceRecords(
    semanticEditor, "Use @native and #beat_b[2.50s].",
).records;
assert.deepEqual(
    separateRecords.map((item) => ({
        tag: item.tag,
        token: item.token,
        label: item.label,
        active: item.active,
        semanticOnly: Boolean(item.semanticOnly),
        supportsSemantic: item.supportsSemantic,
    })),
    [
        {tag: "native", token: "@native", label: "<Picture 1>",
            active: true, semanticOnly: false, supportsSemantic: true},
        {tag: "beat_a", token: "#beat_a[0.00s]", label: null,
            active: false, semanticOnly: true, supportsSemantic: false},
        {tag: "beat_b", token: "#beat_b[0.00s]", label: "<Picture 2>",
            active: true, semanticOnly: true, supportsSemantic: false},
    ],
);

// Packing the semantic registry into a ComfyUI subgraph is presentation-only.
// Discovery must cross the output rail to find the bundle and the input rail
// to resolve an externally connected image used by an internal anchor.
const nestedEditor = add(makeNode(180, "MiniMaxH3ChainScenePromptEditor"));
const nestedRelay = add(makeNode(181, "MiniMaxH3ChainCurrent"));
const nestedWrapper = add(makeNode(182, "MiniMaxH3TaggedReferenceToVideo"));
const nestedHost = add(makeNode(183, "semantic-registry-subgraph"));
const nestedImage = add(makeNode(184, "LoadImage", {image: "nested.png"}));
const nestedGraph = makeSubgraph(
    nestedHost, ["semantic_image"], ["references"],
);
const nestedAnchor = addInside(nestedGraph, makeNode(
    185, "MiniMaxH3SemanticPictureAnchor", {tag: "nested_beat"},
));
const nestedBundle = addInside(nestedGraph, makeNode(
    186, "MiniMaxH3SemanticAnchorBundle", {
        semantic_anchor_size: "768",
        semantic_anchor_mode: "timestamped_video",
    },
));
connect(nestedEditor, nestedRelay, "state");
connect(nestedRelay, nestedWrapper, "prompt");
connectExistingInput(nestedImage, nestedHost, "semantic_image");
connectSubgraphInput(nestedGraph, 0, nestedAnchor, "image");
connectInside(nestedAnchor, nestedBundle, "anchors");
connectSubgraphOutput(nestedGraph, nestedBundle, 0, 0);
connect(nestedHost, nestedWrapper, "references");

assert.equal(findTaggedRef2VA(nestedEditor), nestedWrapper);
assert.equal(collectSemanticAnchorNodes(nestedWrapper).bundle, nestedBundle);
assert.deepEqual(
    collectSemanticAnchorNodes(nestedWrapper).nodes,
    [nestedAnchor],
);
const nestedRecords = taggedReferenceRecords(
    nestedEditor, "Use #nested_beat[1.00s].",
).records;
assert.deepEqual(
    nestedRecords.map(({tag, active, source}) => ({
        tag, active, source: source.id,
    })),
    [{tag: "nested_beat", active: true, source: nestedImage.id}],
);

// The 0.5 Source Timeline motion node can be the final link in a tagged chain.
// Discovery must traverse through it or every earlier picture reference also
// disappears from both prompt editors.
const timelineEditor = add(makeNode(70, "MiniMaxH3ChainScenePromptEditor"));
const timelineRelay = add(makeNode(71, "MiniMaxH3ChainCurrent"));
const timelineWrapper = add(makeNode(72, "MiniMaxH3TaggedReferenceToVideo"));
const timelineCharacterImage = add(makeNode(73, "LoadImage", {
    image: "timeline-character.png",
}));
const timelineKeyframeImage = add(makeNode(74, "LoadImage", {
    image: "timeline-keyframe.png",
}));
const timelineCharacter = add(makeNode(
    75, "MiniMaxH3TaggedPictureReference", {tag: "character"},
));
const timelineKeyframe = add(makeNode(
    76, "MiniMaxH3TaggedPictureReference", {tag: "keyframe"},
));
const sourceTimeline = add(makeNode(77, "MiniMaxH3SourceTimeline", {
    video_path: "/media/source-motion.mp4",
}));
const timelineMotion = add(makeNode(
    78, "MiniMaxH3TaggedMotionReferenceTimeline", {
        tag: "motion", paired_audio: "embedded", audio_tag: "audio_1",
    },
));
connect(timelineEditor, timelineRelay, "state");
connect(timelineRelay, timelineWrapper, "prompt");
connect(timelineCharacterImage, timelineCharacter, "image");
connect(timelineCharacter, timelineKeyframe, "previous");
connect(timelineKeyframeImage, timelineKeyframe, "image");
connect(timelineKeyframe, timelineMotion, "previous");
connect(sourceTimeline, timelineMotion, "source_timeline");
connect(timelineMotion, timelineWrapper, "references");

assert.deepEqual(
    collectTaggedNodes(timelineWrapper),
    [timelineCharacter, timelineKeyframe, timelineMotion],
);
const timelineRecords = taggedReferenceRecords(
    timelineEditor, "Use @character, @keyframe, @motion, and @audio_1.",
).records;
assert.deepEqual(
    timelineRecords.map(({tag, label, active, source}) => ({
        tag, label, active, source: source.id,
    })),
    [
        {tag: "character", label: "<Picture 1>", active: true,
            source: timelineCharacterImage.id},
        {tag: "keyframe", label: "<Picture 2>", active: true,
            source: timelineKeyframeImage.id},
        {tag: "motion", label: "<Subject 1>", active: true,
            source: sourceTimeline.id},
        {tag: "audio_1", label: "<Audio 1>", active: true,
            source: sourceTimeline.id},
    ],
);

const coreEditor = add(makeNode(10, "MiniMaxH3ChainScenePromptEditor"));
const coreRelay = add(makeNode(11, "MiniMaxH3ChainCurrent"));
const core = add(makeNode(12, "MiniMaxH3ReferenceToVideo"));
const coreImage = add(makeNode(13, "LoadImage", {image: "core.png"}));
const coreAudio = add(makeNode(14, "LoadAudio", {audio: "core.wav"}));
connect(coreEditor, coreRelay, "state");
connect(coreRelay, core, "prompt");
connect(coreImage, core, "ref_images.ref_image_0");
connect(coreAudio, core, "ref_audios.ref_audio_0");
const native = coreReferenceRecords(coreEditor);
assert.equal(native.mode, "native");
assert.deepEqual(native.records.map(({kind, token, label}) => ({kind, token, label})), [
    {kind: "picture", token: "<Picture 1>", label: "<Picture 1>"},
    {kind: "audio", token: "<Audio 1>", label: "<Audio 1>"},
]);
assert.equal(referencePreviewRecords(coreEditor, 1).mode, "native");
assert.deepEqual(
    availableReferenceRecords(coreEditor, 1).records.map(({token}) => token),
    ["<Picture 1>", "<Audio 1>"],
);

const flEditor = add(makeNode(15, "MiniMaxH3ChainScenePromptEditor"));
const flRelay = add(makeNode(16, "MiniMaxH3ChainCurrent"));
const fl2v = add(makeNode(17, "MiniMaxH3ImageToVideo"));
const firstFrame = add(makeNode(18, "LoadImage", {image: "first.png"}));
const lastFrame = add(makeNode(19, "LoadImage", {image: "last.png"}));
connect(flEditor, flRelay, "state");
connect(flRelay, fl2v, "prompt");
connect(firstFrame, fl2v, "first_frame");
connect(lastFrame, fl2v, "last_frame");
const keyframes = imageToVideoReferenceRecords(flEditor);
assert.equal(keyframes.mode, "native_keyframes");
assert.deepEqual(
    keyframes.records.map(({token, role}) => ({token, role})),
    [
        {token: "<Picture 1>", role: "first frame"},
        {token: "<Picture 2>", role: "last frame"},
    ],
);
assert.equal(referencePreviewRecords(flEditor, 1).mode, "native_keyframes");

const indexedEditor = add(makeNode(40, "MiniMaxH3ChainRichScenePromptEditor"));
const indexedRelay = add(makeNode(41, "MiniMaxH3ChainCurrent"));
const indexedFl2v = add(makeNode(42, "MiniMaxH3ImageToVideo"));
const indexedGate = add(makeNode(43, "MiniMaxH3ChainFirstSceneImage"));
const indexedSwitch = add(makeNode(44, "MiniMaxH3ChainFrameIndexSwitch"));
const frameA = add(makeNode(45, "LoadImage", {image: "frame-a.png"}));
const frameB = add(makeNode(46, "LoadImage", {image: "frame-b.png"}));
connect(indexedEditor, indexedRelay, "state");
connect(indexedRelay, indexedFl2v, "prompt");
connect(frameA, indexedGate, "image");
connect(frameB, indexedSwitch, "frame_1");
connect(frameA, indexedSwitch, "frame_2");
connect(indexedSwitch, indexedGate, "last_frame");
connect(indexedGate, indexedFl2v, "first_frame", 0);
connect(indexedGate, indexedFl2v, "last_frame", 3);

const indexedSceneOne = imageToVideoReferenceRecords(indexedEditor, 1).records;
assert.deepEqual(
    indexedSceneOne.map(({token, role, source}) => ({token, role, source: source.id})),
    [
        {token: "<Picture 1>", role: "first frame", source: frameA.id},
        {token: "<Picture 2>", role: "last frame", source: frameB.id},
    ],
);
const indexedSceneTwo = imageToVideoReferenceRecords(indexedEditor, 2).records;
assert.deepEqual(
    indexedSceneTwo.map(({token, role, active, source}) => ({
        token, role, active, source: source.id,
    })),
    [
        {token: "<Picture 1>", role: "first frame", active: false, source: frameA.id},
        {token: "<Picture 1>", role: "last frame", active: true, source: frameA.id},
    ],
);
assert.deepEqual(
    availableReferenceRecords(indexedEditor, 1).records.map(({source}) => source.id),
    [frameA.id, frameB.id],
);

const i2vEditor = add(makeNode(24, "MiniMaxH3ChainScenePromptEditor"));
const i2vRelay = add(makeNode(25, "MiniMaxH3ChainCurrent"));
const i2v = add(makeNode(26, "MiniMaxH3ImageToVideo"));
const openingFrame = add(makeNode(27, "LoadImage", {image: "opening.png"}));
const firstSceneGate = add(makeNode(28, "MiniMaxH3ChainFirstSceneImage"));
connect(i2vEditor, i2vRelay, "state");
connect(i2vRelay, i2v, "prompt");
connect(openingFrame, firstSceneGate, "image");
connect(firstSceneGate, i2v, "first_frame");
assert.deepEqual(
    imageToVideoReferenceRecords(i2vEditor, 1).records
        .map(({token, selector, active, source}) => ({
            token, selector, active, source: source.type,
        })),
    [{token: "<Picture 1>", selector: "1", active: true,
        source: "LoadImage"}],
);
assert.deepEqual(
    referencePreviewRecords(i2vEditor, 2).records
        .map(({token, selector, active}) => ({token, selector, active})),
    [{token: "<Picture 1>", selector: "1", active: false}],
);
assert.deepEqual(availableReferenceRecords(i2vEditor, 2).records, []);

const lEditor = add(makeNode(20, "MiniMaxH3ChainScenePromptEditor"));
const lRelay = add(makeNode(21, "MiniMaxH3ChainCurrent"));
const l2v = add(makeNode(22, "MiniMaxH3ImageToVideo"));
const onlyLastFrame = add(makeNode(23, "LoadImage", {image: "last-only.png"}));
connect(lEditor, lRelay, "state");
connect(lRelay, l2v, "prompt");
connect(onlyLastFrame, l2v, "last_frame");
assert.deepEqual(
    imageToVideoReferenceRecords(lEditor).records.map(({token, role}) => ({token, role})),
    [{token: "<Picture 1>", role: "last frame"}],
);

const projectEditor = add(makeNode(270, "MiniMaxH3ChainScenePromptEditor"));
const projectManager = add(makeNode(271, "MiniMaxH3ProjectAssetManager", {
    catalog_json: JSON.stringify({
        project: "episode_1",
        assets: [
            {id: "p", kind: "image", role: "picture", tag: "hero",
                enabled: true, metadata: {}},
            {id: "s", kind: "image", role: "semantic_anchor", tag: "door",
                enabled: true, metadata: {}},
            {id: "v", kind: "video", role: "motion", tag: "walk",
                enabled: true, metadata: {has_audio: true}, options: {}},
            {id: "a", kind: "audio", role: "audio_reference", tag: "voice",
                enabled: true, metadata: {}},
        ],
    }),
    semantic_anchor_mode: "timestamped_video",
}));
const projectRef2va = add(makeNode(272, "MiniMaxH3TaggedReferenceToVideo"));
connect(projectEditor, projectRef2va, "prompt");
connect(projectManager, projectRef2va, "references", 1);
const projectRecords = taggedReferenceRecords(
    projectEditor, "Use @hero and @walk with #door[2.00s] and @voice.",
).records;
assert.deepEqual(
    projectRecords.map(({tag, active, semanticOnly}) => ({
        tag, active, semanticOnly: Boolean(semanticOnly),
    })),
    [
        {tag: "hero", active: true, semanticOnly: false},
        {tag: "door", active: true, semanticOnly: true},
        {tag: "walk", active: true, semanticOnly: false},
        {tag: "walk_audio", active: true, semanticOnly: false},
        {tag: "voice", active: true, semanticOnly: false},
    ],
);
assert.ok(projectRecords.every((record) => record.previewUrl?.includes(
    "project=episode_1")));

console.log("H3 reference preview: tagged/scheduled Ref2VA, core Ref2VA, and core I2V/FL2V discovery pass");
