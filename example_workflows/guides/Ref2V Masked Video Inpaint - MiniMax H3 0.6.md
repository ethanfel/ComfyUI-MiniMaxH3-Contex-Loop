# Ref2V Masked Video Inpaint - MiniMax H3 0.6

Built for the **0.6 branch**, not nightly.

Setup controls come first, followed by numbered generation columns. Recovery is disabled by default. Enable it only to assemble saved clips without sampling.

CORE SOURCE VIDEO

Load Video feeds Get Video Components. Keep all three images, audio, and fps outputs connected to Loop Source AV Target: that node converts the native source rate to H3's 24 fps and fits each scene to the Plan canvas. Do not replace the fps connection with a fixed 24 for non-24-fps input. The included single-frame mask is broadcast across the scene; if using a tracked mask video, supply that mask's actual source frame rate to Mask Slice.

---

SOURCE ASSETS — CC0

Light-blue soldier crabs on Bribie Island, filmed in 2015 by Watermark Resort Caloundra. Wikimedia Commons records the video as CC0 1.0.

https://commons.wikimedia.org/wiki/File:Light-blue_soldier_crabs_on_Bribie_Island.webm

Copy soldier_crabs_bribie_island_cc0.webm, soldier_crabs_inpaint_mask.png, and soldier_crabs_reference_cc0.png from example_workflows/assets/ to ComfyUI/input/.

ABLEJONES / DROZ V3.1 MAPPING

Apply Target Mask in H3 exact mode implements the same H3 auto + max / max causal-token mask contract as MVEx Mask To Latent Space. The pack-native Loop Source AV Target replaces separate VAEEncode, SetLatentNoiseMask, and LTXVConcatAVLatent wiring. Subject Crop / Uncrop remains an optional external efficiency and compositing stage, not a requirement for correct masked H3 sampling.

---

REF2VA MASKED-EDIT PROMPT FORMAT

Use these six fields in order: subject_definitions, summary, retention_analysis, detailed_description, overall_soundscape, and non_diegetic_music.

Picture 1 defines only the replacement appearance. The movie remains the real masked target latent and is intentionally not connected a second time as a Ref2VA video. The source target supplies motion, camera, protected pixels, and synchronized audio; the picture supplies subject appearance.

---

The two amber recovery nodes are MUTED by default.

If all segments finished but final assembly did not, mute the main green Assemble node, enable both recovery nodes, and queue. They validate every SHA-256 checkpoint pair and assemble without rerendering the completed clips.

For an interrupted generation, leave recovery muted and set Loop Start's start_clip to the first unfinished clip.

---

REF2V MASKED VIDEO INPAINT — CHAIN LOOP

This is the picture-conditioned counterpart to the T2VA masked-inpaint demo. Picture 1 supplies the species appearance; the source video is encoded as the actual joint AV target. Do not connect the source video again as ref_video_0.

Two 175-frame generations share a 39-frame protected overlap and deliver 311 frames. Scene 1 selects source frames 0..174; scene 2 selects 136..310. Loop Source AV Target aligns picture and sound to the stock Ref2VA target grid. Chain Context preserves the accepted edited overlap. Apply Target Mask then intersects that temporal protection with the spatial edit mask, so preservation wins.

The bundled one-frame mask is broadcast. Replace it with a tracked MASK batch for moving subjects; Loop Mask Slice selects the corresponding source interval automatically. Grid Preview shows the exact H3 causal and 32px token coverage before sampling. Source audio remains protected.

---

0.6 Studio quick start

1. Open the Project Asset Carousel.
2. Keep the bundled source media selected in the existing loader nodes; use the Carousel for additional project assets.
3. Edit scenes in Production Plan or Plan Studio.
4. Queue; inspect, branch, trim, or restore in Checkpoint Manager.
