export const AUDIO_TRACK_ROLES = Object.freeze([
    ["full_mix", "Full mix · final soundtrack"],
    ["vocals", "Vocals · lip-sync driver"],
    ["instrumental", "Instrumental · optional backing"],
]);

export function projectAudioTrackBindings(asset) {
    const saved = asset?.options?.audio_tracks;
    return Object.fromEntries(AUDIO_TRACK_ROLES.map(([role]) => [role,
        String(saved ? saved[role] ?? "" : role === "full_mix" ? asset?.id ?? "" : ""),
    ]));
}

export function setProjectAudioTrack(asset, role, assetId) {
    if (!AUDIO_TRACK_ROLES.some(([key]) => key === role)) throw new Error("Unknown audio track role.");
    const bindings = projectAudioTrackBindings(asset);
    const id = String(assetId ?? "");
    for (const key of Object.keys(bindings)) {
        if (key !== role && id && bindings[key] === id) bindings[key] = "";
    }
    bindings[role] = id;
    if (!Object.values(bindings).some(Boolean)) throw new Error("Keep at least one audio track, or reset to single track.");
    return bindings;
}

function positiveNumber(value, fallback = 0) {
    const number = Number(value);
    return Number.isFinite(number) && number > 0 ? number : fallback;
}

export function imageMegapixels(width, height) {
    return positiveNumber(width) * positiveNumber(height) / 1_000_000;
}

function normalizedMultiple(value) {
    const multiple = Math.round(positiveNumber(value, 1));
    return multiple > 1 ? multiple : 1;
}

function snappedDimension(value, multiple) {
    const step = normalizedMultiple(multiple);
    return Math.max(step, Math.round(positiveNumber(value, step) / step) * step);
}

function greatestCommonDivisor(left, right) {
    let a = Math.abs(Math.round(left));
    let b = Math.abs(Math.round(right));
    while (b) [a, b] = [b, a % b];
    return a || 1;
}

function leastCommonMultiple(left, right) {
    return Math.abs(left * right) / greatestCommonDivisor(left, right);
}

function approximateFraction(value, maximumDenominator = 256) {
    let best = {numerator: Math.max(1, Math.round(value)), denominator: 1};
    let bestError = Math.abs(best.numerator / best.denominator - value);
    for (let denominator = 1; denominator <= maximumDenominator; denominator += 1) {
        const numerator = Math.max(1, Math.round(value * denominator));
        const error = Math.abs(numerator / denominator - value);
        if (error < bestError - Number.EPSILON) {
            best = {numerator, denominator}; bestError = error;
        }
    }
    const divisor = greatestCommonDivisor(best.numerator, best.denominator);
    return {
        numerator: best.numerator / divisor,
        denominator: best.denominator / divisor,
    };
}

export function dimensionsForMegapixels(
        megapixels, aspectRatio, multiple = 1) {
    const pixels = positiveNumber(megapixels, 0.01) * 1_000_000;
    const ratio = positiveNumber(aspectRatio, 1);
    const idealWidth = Math.sqrt(pixels * ratio);
    const idealHeight = idealWidth / ratio;
    const step = normalizedMultiple(multiple);
    if (step === 1) {
        const width = Math.max(1, Math.round(idealWidth));
        const height = Math.max(1, Math.round(width / ratio));
        return {width, height};
    }
    // Preserve the locked ratio exactly. Reducing it to a small rational pair
    // lets us find the nearest scale where both dimensions share the requested
    // model-friendly multiple.
    const fraction = approximateFraction(ratio);
    const scaleStep = leastCommonMultiple(
        step / greatestCommonDivisor(fraction.numerator, step),
        step / greatestCommonDivisor(fraction.denominator, step),
    );
    const idealScale = Math.sqrt(
        pixels / (fraction.numerator * fraction.denominator));
    const lowerScale = Math.max(
        scaleStep, Math.floor(idealScale / scaleStep) * scaleStep);
    const upperScale = Math.max(
        scaleStep, Math.ceil(idealScale / scaleStep) * scaleStep);
    const candidates = [lowerScale, upperScale].map((scale) => ({
        width: fraction.numerator * scale,
        height: fraction.denominator * scale,
    }));
    candidates.sort((left, right) => (
        Math.abs(Math.log((left.width * left.height) / pixels))
        - Math.abs(Math.log((right.width * right.height) / pixels))
    ));
    return candidates[0];
}

export function coupledOutputDimensions(
        width, height, changed, aspectRatio, locked = true, multiple = 1) {
    const step = normalizedMultiple(multiple);
    let outputWidth = snappedDimension(width, step);
    let outputHeight = snappedDimension(height, step);
    if (!locked) return {width: outputWidth, height: outputHeight};
    const ratio = positiveNumber(aspectRatio, outputWidth / outputHeight);
    if (step > 1) {
        const pixels = changed === "height"
            ? outputHeight * (outputHeight * ratio)
            : outputWidth * (outputWidth / ratio);
        return dimensionsForMegapixels(pixels / 1_000_000, ratio, step);
    }
    if (changed === "height") {
        outputWidth = snappedDimension(outputHeight * ratio, step);
    } else {
        outputHeight = snappedDimension(outputWidth / ratio, step);
    }
    return {width: outputWidth, height: outputHeight};
}

export function formatMegapixels(value) {
    const megapixels = positiveNumber(value);
    if (megapixels >= 10) return megapixels.toFixed(1);
    if (megapixels >= 1) return megapixels.toFixed(2);
    return megapixels.toFixed(3);
}
