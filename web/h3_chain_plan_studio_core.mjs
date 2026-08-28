export function studioCheckpointSignature(runName, records) {
    return JSON.stringify({
        run_name: String(runName ?? ""),
        checkpoints: (Array.isArray(records) ? records : []).map((item) => ({
            scene: item?.scene,
            scene_id: item?.scene_id,
            ready: item?.ready,
            delivered_frames: item?.delivered_frames,
            video: item?.video,
            audio: item?.audio,
            preview_video: item?.preview_video,
            partial_video: item?.partial_video,
        })),
    });
}

export function matchingStudioCheckpoint(checkpoints, index, timingRow) {
    const scene = Number(index) + 1;
    const item = checkpoints instanceof Map
        ? checkpoints.get(scene)
        : (Array.isArray(checkpoints)
            ? checkpoints.find((candidate) => Number(candidate?.scene) === scene)
            : null);
    if (!item?.ready || !timingRow) return null;
    if (String(item.scene_id ?? "") !== String(timingRow.id ?? "")) return null;
    const savedFrames = Number(item.delivered_frames);
    const plannedFrames = Number(timingRow.deliveredFrames);
    if (Number.isFinite(savedFrames) && savedFrames > 0
            && Number.isFinite(plannedFrames) && savedFrames !== plannedFrames) {
        return null;
    }
    return item;
}

export function studioContextWindowLayout(
    deliveredFrames, spanFrames, startFrame,
) {
    const delivered = Number(deliveredFrames);
    const span = Number(spanFrames);
    const requestedStart = Number(startFrame);
    if (!Number.isInteger(delivered) || delivered < 1
            || !Number.isInteger(span) || span < 1 || span > delivered) {
        throw new Error("Context window must fit inside delivered source frames.");
    }
    const latest = delivered - span;
    const start = Number.isInteger(requestedStart)
        ? Math.max(0, Math.min(latest, requestedStart)) : latest;
    return {
        delivered,
        span,
        latest,
        start,
        end:start + span,
        leftFraction:start / delivered,
        widthFraction:span / delivered,
    };
}

export function studioContextWindowStartAtRatio(
    deliveredFrames, spanFrames, ratio,
) {
    const layout = studioContextWindowLayout(
        deliveredFrames, spanFrames, 0,
    );
    const position = Math.max(0, Math.min(1, Number(ratio) || 0));
    return Math.max(0, Math.min(
        layout.latest,
        Math.round(position * layout.delivered - layout.span / 2),
    ));
}

export function studioSceneStartSeconds(rows, index) {
    const bounded = Math.max(0, Math.min(
        Array.isArray(rows) ? rows.length : 0,
        Number.isFinite(Number(index)) ? Math.trunc(Number(index)) : 0,
    ));
    let seconds = 0;
    for (let offset = 0; offset < bounded; offset += 1) {
        seconds += Math.max(0, Number(rows[offset]?.deliveredSeconds) || 0);
    }
    return seconds;
}

function normalizedStartFrame(value) {
    const frames = Number(value);
    return Number.isFinite(frames)
        ? Math.max(0, Math.min(864000, Math.round(frames))) : null;
}

export function studioTimelineSegments(
    rows, placements = [], workspaceEndFrame = null,
) {
    const scenes = Array.isArray(rows) ? rows : [];
    const bySceneId = new Map();
    for (const placement of Array.isArray(placements) ? placements : []) {
        const sceneId = String(placement?.scene_id ?? "").trim();
        const startFrame = normalizedStartFrame(placement?.start_frame);
        if (!sceneId || startFrame == null) continue;
        bySceneId.set(sceneId, startFrame);
    }
    const segments = [];
    let cursorFrame = 0;
    scenes.forEach((row, sceneIndex) => {
        const sceneId = String(row?.id ?? "");
        const durationFrames = Math.max(
            0, Math.round(Number(row?.deliveredFrames) ||
                (Number(row?.deliveredSeconds) || 0) * 24),
        );
        const requestedStart = bySceneId.get(sceneId);
        const startFrame = Math.max(
            cursorFrame,
            requestedStart == null ? cursorFrame : requestedStart,
        );
        if (startFrame > cursorFrame) {
            segments.push({
                kind:"gap", key:`gap:before:${sceneId}`, sceneIndex,
                sceneId, gapId:`before_${sceneId}`,
                startFrame:cursorFrame, durationFrames:startFrame - cursorFrame,
                endFrame:startFrame,
                startSeconds:cursorFrame / 24,
                durationSeconds:(startFrame - cursorFrame) / 24,
                endSeconds:startFrame / 24,
            });
        }
        segments.push({
            kind:"scene", key:`scene:${sceneIndex}`, sceneIndex,
            sceneId, startFrame, durationFrames,
            endFrame:startFrame + durationFrames,
            startSeconds:startFrame / 24,
            durationSeconds:durationFrames / 24,
            endSeconds:(startFrame + durationFrames) / 24,
            explicitStartFrame:requestedStart == null ? null : requestedStart,
        });
        cursorFrame = startFrame + durationFrames;
    });
    const requestedWorkspaceEnd = normalizedStartFrame(workspaceEndFrame);
    if (requestedWorkspaceEnd != null && requestedWorkspaceEnd > cursorFrame) {
        const sceneIndex = Math.max(0, scenes.length - 1);
        segments.push({
            kind:"gap", key:"gap:tail", sceneIndex,
            sceneId:String(scenes.at(-1)?.id ?? ""), gapId:"tail",
            trailing:true,
            startFrame:cursorFrame,
            durationFrames:requestedWorkspaceEnd - cursorFrame,
            endFrame:requestedWorkspaceEnd,
            startSeconds:cursorFrame / 24,
            durationSeconds:(requestedWorkspaceEnd - cursorFrame) / 24,
            endSeconds:requestedWorkspaceEnd / 24,
        });
    }
    return segments;
}

export function studioTimelineTotalSeconds(segments) {
    const values = Array.isArray(segments) ? segments : [];
    return values.length ? Math.max(0, Number(values.at(-1)?.endSeconds) || 0) : 0;
}

export function studioTimelineScrollAnchorSeconds(
    scrollLeft, viewportWidth, contentWidth, totalSeconds, anchorRatio = .5,
) {
    const width = Math.max(0, Number(contentWidth) || 0);
    const duration = Math.max(0, Number(totalSeconds) || 0);
    if (!(width > 0) || !(duration > 0)) return null;
    const ratio = Math.max(0, Math.min(1, Number(anchorRatio) || 0));
    return Math.max(0, Math.min(
        duration,
        (Math.max(0, Number(scrollLeft) || 0)
            + Math.max(0, Number(viewportWidth) || 0) * ratio)
            / width * duration,
    ));
}

export function studioTimelineScrollLeftForAnchor(
    seconds, viewportWidth, pixelsPerSecond, anchorRatio = .5,
) {
    const ratio = Math.max(0, Math.min(1, Number(anchorRatio) || 0));
    return Math.max(
        0,
        Math.max(0, Number(seconds) || 0)
            * Math.max(0, Number(pixelsPerSecond) || 0)
            - Math.max(0, Number(viewportWidth) || 0) * ratio,
    );
}

export function studioEditorialSceneStartSeconds(segments, sceneIndex) {
    const wanted = Number(sceneIndex);
    const segment = (Array.isArray(segments) ? segments : []).find(
        (item) => item?.kind === "scene" && item.sceneIndex === wanted,
    );
    return Math.max(0, Number(segment?.startSeconds) || 0);
}

export function studioTimelineLayout(
    rows, viewportWidth, zoom = 1, placements = [], workspaceEndFrame = null,
) {
    const packedSceneSeconds = studioTimelineTotalSeconds(
        studioTimelineSegments(rows),
    );
    const sceneSegments = studioTimelineSegments(rows, placements);
    const sceneEndSeconds = studioTimelineTotalSeconds(sceneSegments);
    const segments = studioTimelineSegments(
        rows, placements, workspaceEndFrame,
    );
    const width = Math.max(1, Number(viewportWidth) || 1);
    const scale = Math.max(1, Math.min(6, Number(zoom) || 1));
    const totalSeconds = studioTimelineTotalSeconds(segments);
    // Keep the time scale stable while clips are positioned. At 100%, the
    // naturally packed generated duration fills one viewport; editorial gaps
    // and the open workspace extend horizontally instead of re-fitting the
    // terminal clip back onto the viewport's right edge after every move.
    const fitSeconds = Math.max(
        1 / 24,
        packedSceneSeconds || sceneEndSeconds || totalSeconds,
    );
    const pixelsPerSecond = width * scale / fitSeconds;
    const contentWidth = Math.max(
        width * scale, totalSeconds * pixelsPerSecond,
    );
    const widths = segments.map(
        (segment) => pixelsPerSecond * segment.durationSeconds,
    );
    return {
        zoom:scale, contentWidth, widths, segments, totalSeconds,
        sceneEndSeconds, packedSceneSeconds, pixelsPerSecond,
    };
}

export function studioNearestH3FrameLength(
    frames, minimumFrames = 5, maximumFrames = 3592,
) {
    const minimum = Math.max(5, Math.ceil(Number(minimumFrames) || 5));
    const maximum = Math.max(minimum, Math.floor(
        Number(maximumFrames) || 3592,
    ));
    const firstIndex = Math.max(0, Math.ceil((minimum - 5) / 17));
    const lastIndex = Math.max(firstIndex, Math.floor((maximum - 5) / 17));
    const requested = Number.isFinite(Number(frames)) ? Number(frames) : minimum;
    const index = Math.max(firstIndex, Math.min(
        lastIndex, Math.round((requested - 5) / 17),
    ));
    return 5 + index * 17;
}

export function locateStudioTimelineSegment(segments, seconds) {
    const values = Array.isArray(segments) ? segments : [];
    const totalSeconds = studioTimelineTotalSeconds(values);
    const targetSeconds = Math.max(0, Math.min(
        totalSeconds, Number.isFinite(Number(seconds)) ? Number(seconds) : 0,
    ));
    if (!values.length) return {
        index:-1, segmentIndex:-1, kind:"empty", startSeconds:0,
        localSeconds:0, targetSeconds, totalSeconds,
    };
    for (let segmentIndex = 0; segmentIndex < values.length; segmentIndex += 1) {
        const segment = values[segmentIndex];
        if (targetSeconds < segment.endSeconds || segmentIndex === values.length - 1) {
            return {
                ...segment,
                index:Number(segment.sceneIndex), segmentIndex,
                localSeconds:Math.max(0, targetSeconds - segment.startSeconds),
                targetSeconds, totalSeconds,
            };
        }
    }
    return {
        ...values.at(-1), index:Number(values.at(-1)?.sceneIndex),
        segmentIndex:values.length - 1, localSeconds:0,
        targetSeconds, totalSeconds,
    };
}

export function studioRulerTicks(totalSeconds, pixelWidth) {
    const duration = Math.max(0, Number(totalSeconds) || 0);
    const width = Math.max(1, Number(pixelWidth) || 1);
    if (!duration) return [{seconds:0, major:true}];
    const minimumMajorSeconds = duration * 72 / width;
    const candidates = [
        .25, .5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 900, 1800,
    ];
    const majorStep = candidates.find((value) => value >= minimumMajorSeconds)
        ?? candidates.at(-1);
    const minorStep = majorStep >= 5 ? majorStep / 5 : majorStep / 2;
    const ticks = [];
    const count = Math.ceil(duration / minorStep);
    for (let index = 0; index <= count; index += 1) {
        const seconds = Math.min(duration, index * minorStep);
        if (index > 0 && seconds === ticks.at(-1)?.seconds) continue;
        const ratio = seconds / majorStep;
        ticks.push({seconds, major:Math.abs(ratio - Math.round(ratio)) < 1e-7});
    }
    if (ticks.at(-1)?.seconds !== duration) ticks.push({seconds:duration, major:true});
    return ticks;
}

export function parseStudioTimecode(value) {
    const entered = String(value ?? "").trim();
    const text = /s$/i.test(entered) ? entered.slice(0, -1).trim() : entered;
    if (!text) return null;
    const parts = text.split(":");
    if (parts.length > 3 || parts.some((part) => !/^\d+(?:\.\d+)?$/.test(part))) {
        throw new Error("Use seconds, M:SS, or H:MM:SS for editorial time.");
    }
    let seconds = 0;
    for (const part of parts) seconds = seconds * 60 + Number(part);
    if (!Number.isFinite(seconds) || seconds < 0 || seconds > 36000) {
        throw new Error("Editorial time must be between 0 and 10 hours.");
    }
    return seconds;
}

export function parseTimedLyrics(value) {
    const text = String(value ?? "").replaceAll("\r\n", "\n").replaceAll("\r", "\n");
    const srt = [];
    const srtPattern = /(?:^|\n)(?:\d+\s*\n)?\s*(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})\s*-->\s*(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})[^\n]*\n([\s\S]*?)(?=\n{2,}|$)/g;
    for (const match of text.matchAll(srtPattern)) {
        const milliseconds = (hour, minute, second, fraction) => (
            Number(hour) * 3600000 + Number(minute) * 60000 +
            Number(second) * 1000 + Number(String(fraction).padEnd(3, "0").slice(0, 3))
        );
        const start = milliseconds(match[1], match[2], match[3], match[4]) / 1000;
        const end = milliseconds(match[5], match[6], match[7], match[8]) / 1000;
        const cueText = match[9].trim();
        if (cueText && end > start) srt.push({startSeconds:start, endSeconds:end, text:cueText});
    }
    if (srt.length) return srt.sort((a, b) => a.startSeconds - b.startSeconds);

    let offsetSeconds = 0;
    const starts = [];
    for (const line of text.split("\n")) {
        const offset = line.match(/^\s*\[offset:([+-]?\d+)\]\s*$/i);
        if (offset) { offsetSeconds = Number(offset[1]) / 1000; continue; }
        const timestamps = [...line.matchAll(/\[(\d{1,3}):(\d{2})(?:[.:](\d{1,3}))?\]/g)];
        if (!timestamps.length) continue;
        const cueText = line.replace(/\[[^\]]+\]/g, "").trim();
        if (!cueText) continue;
        for (const match of timestamps) {
            const fraction = String(match[3] ?? "0");
            const fractionScale = fraction.length === 3
                ? 1000 : fraction.length === 2 ? 100 : 10;
            const fractionSeconds = Number(fraction) / fractionScale;
            starts.push({
                startSeconds:Math.max(0, Number(match[1]) * 60 + Number(match[2]) + fractionSeconds + offsetSeconds),
                text:cueText,
            });
        }
    }
    starts.sort((a, b) => a.startSeconds - b.startSeconds);
    return starts.map((cue, index) => ({
        ...cue,
        endSeconds:Math.max(
            cue.startSeconds + .1,
            starts[index + 1]?.startSeconds ?? cue.startSeconds + 4,
        ),
    }));
}

export function timedLyricAtSecond(cues, seconds, offsetSeconds = 0) {
    const target = (Number(seconds) || 0) - (Number(offsetSeconds) || 0);
    return (Array.isArray(cues) ? cues : []).find(
        (cue) => target >= Number(cue.startSeconds)
            && target < Number(cue.endSeconds),
    ) ?? null;
}

export function locateStudioTimelineSecond(rows, seconds) {
    const scenes = Array.isArray(rows) ? rows : [];
    const totalSeconds = studioSceneStartSeconds(scenes, scenes.length);
    const targetSeconds = Math.max(0, Math.min(
        totalSeconds, Number.isFinite(Number(seconds)) ? Number(seconds) : 0,
    ));
    if (!scenes.length) {
        return {index: -1, startSeconds: 0, localSeconds: 0, targetSeconds, totalSeconds};
    }
    let startSeconds = 0;
    for (let index = 0; index < scenes.length; index += 1) {
        const duration = Math.max(0, Number(scenes[index]?.deliveredSeconds) || 0);
        if (targetSeconds < startSeconds + duration || index === scenes.length - 1) {
            return {
                index,
                startSeconds,
                localSeconds: Math.max(0, targetSeconds - startSeconds),
                targetSeconds,
                totalSeconds,
            };
        }
        startSeconds += duration;
    }
    return {index: scenes.length - 1, startSeconds, localSeconds: 0, targetSeconds, totalSeconds};
}

export function matchingStudioSourceScene(payload, index, timingRow) {
    if (!payload?.token || !timingRow) return null;
    const scene = Number(index) + 1;
    const item = (Array.isArray(payload.scenes) ? payload.scenes : []).find(
        (candidate) => Number(candidate?.scene) === scene,
    );
    if (!item || String(item.scene_id ?? "") !== String(timingRow.id ?? "")) {
        return null;
    }
    if (Number(item.delivered_frames) !== Number(timingRow.deliveredFrames)) {
        return null;
    }
    const references = Array.isArray(item.references) ? item.references : [];
    return references.length ? item : null;
}

export function matchingStudioSourceAudio(payload, timingRows) {
    const audio = payload?.source_audio;
    if (!payload?.token || !audio?.available) return null;
    const rows = Array.isArray(timingRows) ? timingRows : [];
    const plannedFrames = rows.reduce(
        (total, row) => total + Math.max(0, Number(row?.deliveredFrames) || 0),
        0,
    );
    if (Number(audio.frame_count) !== plannedFrames) return null;
    return audio;
}

export function studioSourceAudioSecond(sourceAudio, timelineSeconds) {
    const start = Math.max(0, Number(sourceAudio?.seek_seconds) || 0);
    const local = Math.max(0, Number(timelineSeconds) || 0);
    // The source file is served directly and may be longer than the generated
    // scene chain. Editorial gaps deliberately keep advancing through it.
    return start + local;
}

export function studioWaveformSceneSamples(waveform, rows, index) {
    const scenes = Array.isArray(rows) ? rows : [];
    const samples = Array.isArray(waveform?.samples) ? waveform.samples : [];
    const rate = Math.max(1, Number(waveform?.points_per_second) || 1);
    if (!samples.length || index < 0 || index >= scenes.length) return [];
    const start = studioSceneStartSeconds(scenes, index);
    const end = start + Math.max(
        0, Number(scenes[index]?.deliveredSeconds) || 0);
    return samples.slice(
        Math.max(0, Math.floor(start * rate)),
        Math.min(samples.length, Math.max(1, Math.ceil(end * rate))),
    );
}

export function studioWaveformIntervalSamples(
    waveform, startSeconds, durationSeconds,
) {
    const samples = Array.isArray(waveform?.samples) ? waveform.samples : [];
    const pointsPerSecond = Math.max(
        0, Number(waveform?.points_per_second) || 0,
    );
    if (!samples.length || !pointsPerSecond) return [];
    const start = Math.max(0, Math.floor(
        (Number(startSeconds) || 0) * pointsPerSecond,
    ));
    const end = Math.max(start + 1, Math.ceil(
        ((Number(startSeconds) || 0) + Math.max(0, Number(durationSeconds) || 0))
            * pointsPerSecond,
    ));
    return samples.slice(start, end);
}

export function studioSourceSecond(reference, deliveredLocalSeconds, fps = 24) {
    const rate = Math.max(1, Number(fps) || 24);
    const offset = Math.max(0, Number(reference?.compare_offset_frames) || 0) / rate;
    const local = Math.max(0, Number(deliveredLocalSeconds) || 0);
    const duration = Math.max(0, Number(reference?.frame_count) || 0) / rate;
    return Math.min(Math.max(0, duration - 0.02), offset + local);
}

export function h3StudioGridMarkers(
    rawFrames, contextFrames = 0, continuationMode = "guide",
    preserveAudioPrefix = true,
) {
    const frames = Math.trunc(Number(rawFrames));
    const context = Math.trunc(Number(contextFrames));
    const rawIndex = Number.isInteger(frames) ? (frames - 5) / 17 : NaN;
    const rawOnGrid = Number.isInteger(rawIndex) && rawIndex >= 0;
    const raw = {
        frames,
        onGrid:rawOnGrid,
        index:rawOnGrid ? rawIndex : null,
        label:rawOnGrid
            ? `${frames}f = 17×${rawIndex}+5`
            : `${frames}f is off the 17n+5 grid`,
    };

    const avMode = [
        "masked_av", "tapered_av", "feathered_av", "audio_feathered_av",
        "drift_control_av",
    ].includes(
        String(continuationMode ?? ""),
    );
    let av = null;
    if (avMode && Number.isInteger(context) && context > 0) {
        const latentIndex = (context - 5) / 17;
        const latentGrid = Number.isInteger(latentIndex) && latentIndex >= 0;
        const audioAligned = context % 3 === 0;
        const audioPreserved = Boolean(preserveAudioPrefix);
        const exact = latentGrid && (!audioPreserved || audioAligned);
        const audioTicks = context * 5 / 3;
        av = {
            frames:context,
            latentGrid,
            exact,
            audioAligned,
            audioPreserved,
            audioTicks,
            label:audioPreserved
                ? (audioAligned
                    ? `${context}f AV = ${audioTicks} audio ticks`
                    : `${context}f AV = ${audioTicks.toFixed(3)} audio ticks`)
                : `${context}f video-only AV`,
        };
    }

    // Community experiments report fewer flashes when a generated-to-real
    // cut lands within the four-frame window beginning at 17n-3.  Surface the
    // nearest completed window as an optional diagnostic, never a validator.
    const packet = Number.isInteger(frames) ? Math.floor(frames / 17) : 0;
    const cut = packet > 0 ? {
        start:17 * packet - 3,
        end:17 * packet,
        experimental:true,
        label:`cut test ${17 * packet - 3}–${17 * packet}f`,
    } : null;
    return {raw, av, cut};
}
