# FL2V Normal - MiniMax H3 0.6

Built for the **0.6 branch**, not nightly.

Setup controls come first, followed by numbered generation columns. Recovery is disabled by default. Enable it only to assemble saved clips without sampling.

0.6 A→B REFERENCES

Copy h3_v06_courier_greenhouse_arrival.png and h3_v06_courier_greenhouse_delivery.png from example_workflows/assets to ComfyUI/input. They were created as a coherent opening/destination pair for this release catalog.

---

FL2VA PROMPT FORMAT

Each three-section prompt identifies the opening and final target inside integrated_multimodal_description. The action converges on the target only at the final frame.

---

The two amber recovery nodes are MUTED by default.

If all segments finished but final assembly did not, mute the main green Assemble node, enable both recovery nodes, and queue. They validate every SHA-256 checkpoint pair and assemble without rerendering the completed clips.

For an interrupted generation, leave recovery muted and set Loop Start's start_clip to the first unfinished clip.

---

FL2V 0.6 QUICK START

Keep delivery on Frame Index Switch frame_1 and arrival on frame_2. Frame Gate supplies arrival as scene 1's opening and alternates B→A end targets for the loop.
