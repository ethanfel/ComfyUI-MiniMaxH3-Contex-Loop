#!/usr/bin/env python3
"""Guard the experimental pixel workflow's IMAGE/conditioning/audio contract."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
path, = (ROOT / "example_workflows").glob("Deferred Upscale - Pixel DLSS5 + USDU - EXPERIMENTAL - MiniMax H3*.json")
wf = json.loads(path.read_text())
nodes = {n["type"]: n for n in wf["nodes"]}
by_id = {n["id"]: n for n in wf["nodes"]}
links = {link[0]: link for link in wf["links"]}


def origin(target_type, input_name):
    target = nodes[target_type]
    socket = next(s for s in target["inputs"] if s["name"] == input_name)
    if socket["link"] is None:
        return None
    _, source, slot, target_id, target_slot, _ = links[socket["link"]]
    assert target_id == target["id"] and target["inputs"][target_slot] == socket
    return by_id[source]["type"], by_id[source]["outputs"][slot]["name"]


conditioning = "MiniMaxH3ChainUpscalePixelConditioning"
current = "MiniMaxH3ChainUpscalePixelCurrent"
refiner = "UltimateSDUpscaleNoUpscaleGuider"
assert nodes["MiniMaxH3ChainCheckpointManager"]["widgets_values"] == [""]
assert nodes["MiniMaxH3ChainUpscaleAdapter"]["widgets_values"][1] == "pixel"
assert nodes["MiniMaxH3ChainUpscaleAdapter"]["widgets_values"][5] is False
assert not {"H3ConditioningSyncFromLatents", "MiniMaxH3ChainPass2Prepare",
            "VAEDecodeAudio", "VAEDecode"}.intersection(nodes)
assert origin(conditioning, "images") == ("DLSS5EnhanceImages", "images")
assert origin("DLSS5EnhanceImages", "images") == (current, "images")
# The exact same image tensor that determined conditioning MUST reach USDU.
assert origin(refiner, "upscaled_image") == (conditioning, "images")
assert origin("BasicGuider", "conditioning") == (conditioning, "positive")
assert origin(refiner, "guider") == ("BasicGuider", "GUIDER")
assert origin(refiner, "seed") == (current, "seed")
seed = next(s for s in nodes[refiner]["inputs"] if s["name"] == "seed")
assert seed["widget"] == {"name": "seed"}
assert nodes[refiner]["widgets_values"][-1] is False, "anchor_context is BOOLEAN, not a stale mode string"
for typ in ("MiniMaxH3ChainUpscaleSegmentSave", "MiniMaxH3ChainUpscaleLoopEnd"):
    assert origin(typ, "images") == (refiner, "IMAGE")
    assert origin(typ, "state") == (current, "state")
    assert origin(typ, "upscaled_latent") is None
assert origin("MiniMaxH3ChainUpscaleSegmentSave", "recovered_audio") is None
assert origin("MiniMaxH3ChainAssemble", "source_audio") is None
assert origin("MiniMaxH3ChainAssemble", "manifest") == ("MiniMaxH3ChainUpscaleLoopEnd", "manifest")
assert origin("MiniMaxH3ChainUpscaleLoopEnd", "flow") == ("MiniMaxH3ChainUpscaleAdapter", "flow")
assert all(n["mode"] == 0 for n in wf["nodes"])
for i, a in enumerate(wf["nodes"]):
    ax, ay = a["pos"]; aw, ah = a["size"]
    for b in wf["nodes"][i + 1:]:
        bx, by = b["pos"]; bw, bh = b["size"]
        assert not (ax < bx + bw and bx < ax + aw and ay - 30 < by + bh and by - 30 < ay + ah)
guide = (path.parent / "guides" / path.with_suffix(".md").name).read_text()
assert "Illynir" in guide and "1537598841199792148" in guide
assert "Validated against" in guide and "GPU" in guide
print("Pixel workflow: actual-size image/conditioning path, positive Guider, original audio, clean values, preview spacing and attribution pass")
