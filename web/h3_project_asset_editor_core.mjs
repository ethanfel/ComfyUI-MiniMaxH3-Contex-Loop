function positiveNumber(value, fallback = 0) {
    const number = Number(value);
    return Number.isFinite(number) && number > 0 ? number : fallback;
}

export function imageMegapixels(width, height) {
    return positiveNumber(width) * positiveNumber(height) / 1_000_000;
}

export function dimensionsForMegapixels(megapixels, aspectRatio) {
    const pixels = positiveNumber(megapixels, 0.01) * 1_000_000;
    const ratio = positiveNumber(aspectRatio, 1);
    const width = Math.max(1, Math.round(Math.sqrt(pixels * ratio)));
    const height = Math.max(1, Math.round(width / ratio));
    return {width, height};
}

export function coupledOutputDimensions(
        width, height, changed, aspectRatio, locked = true) {
    let outputWidth = Math.max(1, Math.round(positiveNumber(width, 1)));
    let outputHeight = Math.max(1, Math.round(positiveNumber(height, 1)));
    if (!locked) return {width: outputWidth, height: outputHeight};
    const ratio = positiveNumber(aspectRatio, outputWidth / outputHeight);
    if (changed === "height") {
        outputWidth = Math.max(1, Math.round(outputHeight * ratio));
    } else {
        outputHeight = Math.max(1, Math.round(outputWidth / ratio));
    }
    return {width: outputWidth, height: outputHeight};
}

export function formatMegapixels(value) {
    const megapixels = positiveNumber(value);
    if (megapixels >= 10) return megapixels.toFixed(1);
    if (megapixels >= 1) return megapixels.toFixed(2);
    return megapixels.toFixed(3);
}
