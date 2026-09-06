# Example assets

## `h3_v06_courier_greenhouse_arrival.png`

Fresh landscape opening reference for the 0.6 I2V, FL2V, and Ref2V examples.
It shows one adult bicycle courier arriving at a glass greenhouse with a parcel.
The image was generated specifically for this repository's release examples;
it contains no logo, watermark, or embedded text.

SHA-256:
`1e7b02dbf5d4f3d51f6e65e1c8cbf6f35b542995a7b27f278889efa32ef9462c`

Copy it to `ComfyUI/input/` for Normal workflows. For Studio, import it through
Project Asset Carousel, use tag `courier_arrival`, and assign **Picture**.

## `h3_v06_courier_greenhouse_delivery.png`

Matching destination reference: the same courier and bicycle inside the same
greenhouse, placing the parcel on a potting table. It was generated from the
arrival image specifically for coherent A→B and tagged-reference examples.

SHA-256:
`d225b876063e9fe7c611f8b0217dc961f2ed34eaee4445a0c895d9b6e30b5b76`

Copy it beside the arrival image for FL2V and Basic Ref2V. For Studio, import
it through the Carousel as `greenhouse_delivery` with the **Picture** role.

## Legacy 0.5 reference assets

The following Jigen images remain available because workflows preserved in
`example_workflows/Archive/pre-0.6-nightly/` still reference them. They are no longer used
by the maintained 0.6 catalog.

## `jigen_market_garden_doom_opening.png`

Opening image for the paired MiniMax H3 I2V example workflows. It was shared
by **ᴊɪɢᴇɴ** in Banodoco's `#minimax_h3_gens` on August 12, 2026 alongside the
I2V prompt used by scene 1:

- [Prompt and source image](https://discord.com/channels/1076117621407223829/1533677158067736777/1537180042210054226)
- [Generated result](https://discord.com/channels/1076117621407223829/1533677158067736777/1537178443358142555)

SHA-256:
`7a9993055d71b1e174096f2a2533ae2a0b14a686fdacae0c7bab1faa738ef5f3`

Copy the PNG to `ComfyUI/input/` before loading either I2V workflow or any of
the Ref2V examples. ComfyUI's Load Image node resolves assets from its
configured input directories, not from this repository folder.

## `jigen_market_garden_doom_last.png`

Final frame extracted from ᴊɪɢᴇɴ's credited generated result above. The FL2V
Normal example uses it as Frame B, then alternates B and the original Frame A
as per-scene last-frame targets.

SHA-256:
`e07862c0d5160f06f015b8849dc4b7d2db0524de5ba490fd26c3dff33e196b34`

Copy this PNG and `jigen_market_garden_doom_opening.png` to `ComfyUI/input/`
before loading the FL2V workflow or any of the Ref2V examples.

## `soldier_crabs_bribie_island_cc0.webm`

Modern source video for the masked inpaint, AV extension, and bridge examples. It
shows light-blue soldier crabs (*Mictyris longicarpus*) on Bribie Island,
Queensland, Australia. The video was filmed in 2015 by **Watermark Resort
Caloundra** and is distributed under the
[CC0 1.0 Universal Public Domain Dedication](https://creativecommons.org/publicdomain/zero/1.0/).

- [Wikimedia Commons source and license record](https://commons.wikimedia.org/wiki/File:Light-blue_soldier_crabs_on_Bribie_Island.webm)
- Original format: VP8/Vorbis WebM, 1280×720, 13.049 seconds, stereo audio

SHA-256:
`aacef1ac138445311eb61734f8ca92f8dc438b8d9ca3210fd8893aa5e925ee47`

Copy the WebM to `ComfyUI/input/` before loading any masked inpaint, AV
extension, or bridge workflow. The examples force decoder output to 24 fps and
resize it to their 960×544 H3 canvas.

## `soldier_crabs_inpaint_mask.png`

Static 960×544 black-and-white demonstration mask for the looped inpaint
workflow. White selects the lower-central beach region for regeneration;
black protects the source video. Grid Preview displays the exact effective H3
32px cells before sampling. Loop Mask Slice explicitly broadcasts this single
frame. Replace its input with a tracked MASK batch to follow a moving object;
the node slices matching frames for every loop scene and overlap.

SHA-256:
`95cf18228cd3559ad980339fe9d8fccdcef25799368719b8e044cd61c6691fe4`

## `soldier_crabs_reference_cc0.png`

Reference frame extracted at 9 seconds from the CC0 soldier-crab video above.
The multi-scene Ref2VA extension workflow uses it to stabilize species
appearance beneath the authoritative protected AV prefix. The Ref2V masked
inpaint demo uses it as `<Picture 1>` to define the appearance regenerated only
inside the spatial mask.

SHA-256:
`432dc2c9b0b9d0c33ed33217247fefcbe551d240959f6eefb7c04dfc99378047`

Copy it to `ComfyUI/input/` together with the WebM before loading either the
chained Ref2VA extension or Ref2V masked-inpaint example.
