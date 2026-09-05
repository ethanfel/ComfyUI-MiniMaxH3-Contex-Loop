# Masked AV Bridge - Two Clips - MiniMax H3 0.6

Built for the **0.6 branch**, not nightly.

Setup controls come first, followed by numbered generation columns.

CC0 TWO-CLIP BRIDGE DEMO

Core Load Video feeds Reference Video Prepare, which converts the original 29.97-fps video to a 311-frame H3-safe 24-fps span with its matching source soundtrack. Resize the prepared source to the same canvas as Image / Keyframe Conditioning, then Create Video keeps these prepared frames and audio together without encoding.

The two Trim Video nodes select Source A at 0 seconds for 4.125 seconds (frames 0–98), and Source B at 8.875 seconds through the end (frames 213–310). Get Video Components supplies ordinary core AUDIO dictionaries. The bridge target remains 192 frames: 39 protected frames from Source A + 114 generated middle frames + 39 protected frames from Source B. Assembly removes both repeated protected windows, reconstructing a 311-frame timeline. This drops only the final two frames from the former 313-frame demo; the 114-frame gap is unchanged.

If changing the source intervals, also update the bridge target length and generated-middle audio trim to match the new gap. Keep the source resize and generation canvas identical, and leave Create Video at 24 fps.

SOURCE: Light-blue soldier crabs on Bribie Island (2015), Watermark Resort Caloundra, CC0 1.0.
https://commons.wikimedia.org/wiki/File:Light-blue_soldier_crabs_on_Bribie_Island.webm

Copy soldier_crabs_bribie_island_cc0.webm from example_workflows/assets/ to ComfyUI/input/. This prompt does not reuse Crab Rave music, footage, choreography, or branding.
