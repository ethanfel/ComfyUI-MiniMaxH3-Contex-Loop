# I2V Normal - MiniMax H3 0.6

Built for the **0.6 branch**, not nightly.

Setup controls come first, followed by numbered generation columns. Recovery is disabled by default. Enable it only to assemble saved clips without sampling.

0.6 REFERENCE ASSET

h3_v06_courier_greenhouse_arrival.png was generated specifically for this release catalog. Copy it from example_workflows/assets to ComfyUI/input before loading the workflow.

---

I2VA PROMPT FORMAT

Scene 1 declares <Picture 1> as the opening frame inside the three-section H3 prompt. Scene 2 relies on the incoming H3 Motion Context and begins new action only after the carried overlap.

---

I2V 0.6 QUICK START

Select the courier arrival image and keep Frame Gate connected: it applies Picture 1 only to scene 1. Select installed H3 model/VAE files, edit the Plan, then queue.

---

The two amber recovery nodes are MUTED by default.

If all segments finished but final assembly did not, mute the main green Assemble node, enable both recovery nodes, and queue. They validate every SHA-256 checkpoint pair and assemble without rerendering the completed clips.

For an interrupted generation, leave recovery muted and set Loop Start's start_clip to the first unfinished clip.
