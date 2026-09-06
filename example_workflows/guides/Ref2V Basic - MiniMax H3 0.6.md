# Ref2V Basic - MiniMax H3 0.6

Adapted for **nightly** from the released **0.6 workflow catalog**. H3 settings and sockets are validated against nightly.

Setup controls come first, followed by numbered generation columns. Recovery is disabled by default. Enable it only to assemble saved clips without sampling.

0.6 ORIGINAL REFERENCE EXAMPLE

The matching courier and greenhouse pictures were generated specifically for this catalog. They replace the old community demonstration assets and prompts.

---

REF2VA PROMPT FORMAT — SIX SECTIONS

Keep subject_definitions, summary, retention_analysis, detailed_description, overall_soundscape, and non_diegetic_music in that order. References define identity; the prompt defines the new action.

---

REF2V 0.6 QUICK START

Copy both courier PNGs to ComfyUI/input. The two picture references are activated as courier_arrival and greenhouse_delivery. Edit the Plan, then queue and approve each checkpointed scene.

---

The two amber recovery nodes are MUTED by default.

If all segments finished but final assembly did not, mute the main green Assemble node, enable both recovery nodes, and queue. They validate every SHA-256 checkpoint pair and assemble without rerendering the completed clips.

For an interrupted generation, leave recovery muted and set Loop Start's start_clip to the first unfinished clip.
