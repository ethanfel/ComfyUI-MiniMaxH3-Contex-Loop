# Masked AV Extension - Single Clip - MiniMax H3 0.6

Adapted for **nightly** from the released **0.6 workflow catalog**. H3 settings and sockets are validated against nightly.

Setup controls come first, followed by numbered generation columns. Recovery is disabled by default. Enable it only to assemble saved clips without sampling.

SOURCE ASSET — CC0

Light-blue soldier crabs on Bribie Island, filmed in 2015 by Watermark Resort Caloundra. Wikimedia Commons records the video as CC0 1.0.

https://commons.wikimedia.org/wiki/File:Light-blue_soldier_crabs_on_Bribie_Island.webm

Copy soldier_crabs_bribie_island_cc0.webm from example_workflows/assets/ to ComfyUI/input/. The prompt and generated continuation are original repository example material; they do not reuse Crab Rave music, video, choreography, or branding.

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

SOFT AV EXTENSION — SINGLE LOOP ITERATION

The complete CC0 source is normalized to 24 fps and persisted as the prelude. Its last 39 frames and matching 65 audio latent steps become scene 1's clean protected target prefix. Soft AV keeps the picture prefix hard while releasing the last eight audio ticks with a half-cosine feather. H3 generates 153 new frames (6.375s); Loop Trim removes the repeated prefix, retains all 39 visual overlap frames for the final linear blend, and Assemble prepends the original 13-second source.

This intentionally uses the same recursive loop as long chains, with a one-scene Plan rather than a separate one-off extension stack.

---

0.6 Studio quick start

1. Open the Project Asset Carousel.
2. Keep the bundled source media selected in the existing loader nodes; use the Carousel for additional project assets.
3. Edit scenes in Production Plan or Plan Studio.
4. Queue; inspect, branch, trim, or restore in Checkpoint Manager.

---

NATIVE SOURCE VIDEO

Core Load Video connects directly to Existing Video Context's source_video input. The node reads embedded audio and the actual video frame rate, fits the source to the Plan canvas, and prepares the protected tail. There is no VHS frame cap or manual FPS conversion. Leave source_frames and source_audio disconnected unless intentionally switching to the separate IMAGE/AUDIO route or overriding the soundtrack.
