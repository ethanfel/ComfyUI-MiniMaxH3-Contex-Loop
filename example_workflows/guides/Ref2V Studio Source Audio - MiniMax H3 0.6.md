# Ref2V Studio Source Audio - MiniMax H3 0.6

Adapted for **nightly** from the released **0.6 workflow catalog**. H3 settings and sockets are validated against nightly.

Setup controls come first, followed by numbered generation columns. Recovery is disabled by default. Enable it only to assemble saved clips without sampling.

0.6 ORIGINAL REFERENCE EXAMPLE

The matching courier and greenhouse pictures were generated specifically for this catalog. They replace the old community demonstration assets and prompts.

---

The two amber recovery nodes are MUTED by default.

If all segments finished but final assembly did not, mute the main green Assemble node, enable both recovery nodes, and queue. They validate every SHA-256 checkpoint pair and assemble without rerendering the completed clips.

For an interrupted generation, leave recovery muted and set Loop Start's start_clip to the first unfinished clip.

---

REF2VA PROMPT FORMAT — SIX SECTIONS

Keep subject_definitions, summary, retention_analysis, detailed_description, overall_soundscape, and non_diegetic_music in that order. References define identity; the prompt defines the new action.

---

0.6 Studio quick start

1. Open the Project Asset Carousel and set a unique run name before importing assets.
2. Import h3_v06_courier_greenhouse_arrival.png; tag courier_arrival (Picture).
3. Import h3_v06_courier_greenhouse_delivery.png; tag greenhouse_delivery (Picture).
4. Import/drop one audio file into the Carousel. Select its card and set Audio use → Project timeline source.
5. Keep Generation Profile → Lip-sync to source audio (already selected), then edit scenes in Production Plan or Plan Studio.
6. Queue; inspect, branch, trim, or restore in Checkpoint Manager.

The preset alone does not load an audio file. Carousel.project_assets already carries the source track to the Plan and loop; no separate Load Audio node, AUDIO cable, or @tag is needed.
