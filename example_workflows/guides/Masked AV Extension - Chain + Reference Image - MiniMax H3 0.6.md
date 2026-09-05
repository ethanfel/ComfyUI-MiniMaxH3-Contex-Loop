# Masked AV Extension - Chain + Reference Image - MiniMax H3 0.6

Built for the **0.6 branch**, not nightly.

Setup controls come first, followed by numbered generation columns. Recovery is disabled by default. Enable it only to assemble saved clips without sampling.

REF2VA PROMPT FORMAT — SIX SECTIONS

1. subject_definitions:
2. summary:
3. retention_analysis:
4. detailed_description:
5. overall_soundscape:
6. non_diegetic_music:

Write stable @tags in the Plan. Tagged Ref2VA activates only registered @tags present in the resolved scene prompt and compiles them to native <Picture N> labels; it does not insert definitions for you.

---

The two amber recovery nodes are MUTED by default.

If all segments finished but final assembly did not, mute the main green Assemble node, enable both recovery nodes, and queue. They validate every SHA-256 checkpoint pair and assemble without rerendering the completed clips.

For an interrupted generation, leave recovery muted and set Loop Start's start_clip to the first unfinished clip.

---

SOFT AV EXTENSION — THREE-SCENE LOOP + REFERENCE IMAGE

The source video's last 39 frames/65 audio steps protect scene 1. Soft AV keeps each picture prefix hard while releasing only the final eight audio ticks with a half-cosine feather. Each accepted generated scene then supplies the protected prefix for the next loop iteration. @crabs is active in all three prompts only as identity/appearance guidance; the incoming latent prefix remains authoritative for pose, motion, camera, light, and audio timing. Loop Trim retains all 39 repeated visual frames for linear seam blending, and the original source is prepended once during final assembly.

---

SOURCE ASSETS — CC0

The bundled 2015 soldier-crab WebM is CC0 1.0, as recorded by Wikimedia Commons. The PNG is one frame extracted from that same CC0 video.

https://commons.wikimedia.org/wiki/File:Light-blue_soldier_crabs_on_Bribie_Island.webm

Copy both soldier_crabs_bribie_island_cc0.webm and soldier_crabs_reference_cc0.png from example_workflows/assets/ to ComfyUI/input/. Prompts are original and do not reuse Crab Rave.

---

0.6 Studio quick start

1. Open the Project Asset Carousel.
2. Import soldier_crabs_reference_cc0.png; tag crabs (Picture).
3. Edit scenes in Production Plan or Plan Studio.
4. Queue; inspect, branch, trim, or restore in Checkpoint Manager.

---

NATIVE SOURCE VIDEO

Core Load Video connects directly to Existing Video Context's source_video input. The node reads embedded audio and the actual video frame rate, fits the source to the Plan canvas, and prepares the protected tail. There is no VHS frame cap or manual FPS conversion. Leave source_frames and source_audio disconnected unless intentionally switching to the separate IMAGE/AUDIO route or overriding the soundtrack.
