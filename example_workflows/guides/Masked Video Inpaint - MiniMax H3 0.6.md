# Masked Video Inpaint - MiniMax H3 0.6

Adapted for **nightly** from the released **0.6 workflow catalog**. H3 settings and sockets are validated against nightly.

Setup controls come first, followed by numbered generation columns. Recovery is disabled by default. Enable it only to assemble saved clips without sampling.

CORE SOURCE VIDEO

Load Video feeds Get Video Components. Keep all three images, audio, and fps outputs connected to Loop Source AV Target: that node converts the native source rate to H3's 24 fps and fits each scene to the Plan canvas. Do not replace the fps connection with a fixed 24 for non-24-fps input. The included single-frame mask is broadcast across the scene; if using a tracked mask video, supply that mask's actual source frame rate to Mask Slice.

---

SOURCE ASSET — CC0

Light-blue soldier crabs on Bribie Island, filmed in 2015 by Watermark Resort Caloundra. Wikimedia Commons records the video as CC0 1.0.

https://commons.wikimedia.org/wiki/File:Light-blue_soldier_crabs_on_Bribie_Island.webm

Copy soldier_crabs_bribie_island_cc0.webm and soldier_crabs_inpaint_mask.png from example_workflows/assets/ to ComfyUI/input/.

---

T2VA PROMPT FORMAT

T2VA begins directly with these three fields in this exact order—there is no Picture alignment instruction:

integrated_multimodal_description: [Shot 1] Describe visible style, composition, subjects, actions, camera movement, dialogue, and synchronized diegetic events.

overall_soundscape: Summarize ambience, physical sounds, and non-verbal human sounds.

non_diegetic_music: Describe audience-only music, or use N/A.

For a chained continuation, explicitly continue the incoming pose, action phase, camera position and motion, lighting, environment, object states, ambience, and speaker identity. Do not re-establish or reset the shot unless a cut is intentional.

---

The two amber recovery nodes are MUTED by default.

If all segments finished but final assembly did not, mute the main green Assemble node, enable both recovery nodes, and queue. They validate every SHA-256 checkpoint pair and assemble without rerendering the completed clips.

For an interrupted generation, leave recovery muted and set Loop Start's start_clip to the first unfinished clip.

---

MASKED VIDEO INPAINT — CHAIN LOOP

This is a real Chain Loop workflow, including Current Shot, checkpoint/review, Loop End, resume, and disk assembly. Two 175-frame generations share a 39-frame protected overlap, delivering the largest valid span contained by the bundled 313-frame source: 311 frames. Scene 1 selects source frames 0..174; scene 2 selects 136..310 and retains the preceding edited result in its protected prefix.

The pack-native Loop Source AV Target selects the current source interval from Chain state, then fits picture and sound to the exact stock H3 joint target. It does not use LTXVConcatAVLatent or LTXVSeparateAVLatent. The source picture and audio therefore share the same frame-derived 24-fps start and duration. Apply Target Mask preserves source audio and every black video cell; only white cells are regenerated. Loop Mask Slice broadcasts the bundled one-frame mask explicitly. Replace its mask input with a tracked MASK batch covering the complete source timeline to follow a moving object; scene 2 automatically receives mask frames 136..310, including the same 39-frame overlap as source AV.

---

0.6 Studio quick start

1. Open the Project Asset Carousel.
2. Keep the bundled source media selected in the existing loader nodes; use the Carousel for additional project assets.
3. Edit scenes in Production Plan or Plan Studio.
4. Queue; inspect, branch, trim, or restore in Checkpoint Manager.
