# Ref2V Sequential Motion - EXPERIMENTAL - MiniMax H3 0.6

Built for the **0.6 branch**, not nightly.

Setup controls come first, followed by numbered generation columns. Recovery is disabled by default. Enable it only to assemble saved clips without sampling.

0.6 ORIGINAL REFERENCE EXAMPLE

The matching courier and greenhouse pictures were generated specifically for this catalog. They replace the old community demonstration assets and prompts.

---

REF2VA PROMPT FORMAT — SIX SECTIONS

Keep subject_definitions, summary, retention_analysis, detailed_description, overall_soundscape, and non_diegetic_music in that order. References define identity; the prompt defines the new action.

---

SEQUENTIAL MOTION 0.6 QUICK START

Copy both courier PNGs to ComfyUI/input and select a motion video with embedded audio lasting at least 19.333 seconds. Keep tags @courier_arrival, @greenhouse_delivery, @courier_motion, and @courier_motion_audio in the prompts. The motion window advances with each scene.

---

The two amber recovery nodes are MUTED by default.

If all segments finished but final assembly did not, mute the main green Assemble node, enable both recovery nodes, and queue. They validate every SHA-256 checkpoint pair and assemble without rerendering the completed clips.

For an interrupted generation, leave recovery muted and set Loop Start's start_clip to the first unfinished clip.
