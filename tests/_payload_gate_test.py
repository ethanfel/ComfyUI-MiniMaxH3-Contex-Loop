"""The payload patch must only touch graphs that came from this pack.

`MiniMaxH3.extra_conds` is wrapped process-wide, so every H3 graph in the
process runs through it. A Ref2VA workflow with a last_frame anchor is a
legitimate combination of keyframes and refs that has nothing to do with
chaining, and it must come out of the wrapper bit-identical to stock.

Fakes comfy.model_base with a MiniMaxH3 whose extra_conds reproduces the
stock overwrite, then checks four cases:

  1. stock keyframes + stock refs      -> untouched (refs overwrite, as stock)
  2. marked keyframes + marked ref     -> merged (the pack's own graph)
  3. marked keyframes, unmarked refs   -> merged (chaining under Ref2VA)
  4. one mechanism only                -> untouched either way
"""

import importlib
import importlib.util
import os
import sys
import types

_PKG = __file__.rsplit("/", 2)[0]
sys.path.insert(0, _PKG)

MC_KEY = "motion_context_index"
MC_AUDIO_KEY = "motion_context_audio_end_frame"


class Cond:
    def __init__(self, cond):
        self.cond = cond


def make_model_base():
    mb = types.ModuleType("comfy.model_base")

    class MiniMaxH3:
        def extra_conds(self, **kwargs):
            payload = {}
            kfs = kwargs.get("minimax_keyframes")
            refs = kwargs.get("minimax_refs")
            if kfs is not None:
                payload["cond_video_latents"] = [kf["latent"] for kf in kfs]
            if refs is not None:
                # the stock overwrite this patch exists to work around
                payload["cond_video_latents"] = [r["latent"] for r in refs
                                                 if "latent" in r]
                payload["cond_audio_latents"] = [
                    r["audio_latent"] for r in refs
                    if r.get("audio_latent") is not None]
            fc = kwargs.get("minimax_frame_count")
            if fc is not None:
                payload["frame_count"] = fc
            return {"minimax_payload": Cond(payload)}

    mb.MiniMaxH3 = MiniMaxH3
    sys.modules.setdefault("comfy", types.ModuleType("comfy"))
    sys.modules["comfy.model_base"] = mb
    sys.modules["comfy"].model_base = mb
    return mb


def load_payload_patch(name):
    spec = importlib.util.spec_from_file_location(
        name, os.path.join(_PKG, "patch_payload.py"))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def main():
    mb = make_model_base()
    sys.modules.pop("patch_payload", None)
    pp = importlib.import_module("patch_payload")
    assert pp.apply_patch(), "payload patch did not apply"

    model = mb.MiniMaxH3()

    def run(kfs, refs):
        return model.extra_conds(minimax_keyframes=kfs, minimax_refs=refs,
                                 minimax_frame_count=124)["minimax_payload"].cond

    # 1. an unrelated graph: stock keyframes plus stock refs. Stock drops
    # the keyframe latent here. Right or wrong, that is not this pack's
    # call, and the wrapper must leave it alone.
    plain_kf = [{"resolved_frame_index": 0, "latent": "KF"}]
    plain_ref = [{"kind": "image", "latent": "REF"}]
    got = run(plain_kf, plain_ref)
    assert got["cond_video_latents"] == ["REF"], got
    print("1. stock keyframes + stock refs: untouched, stock overwrite intact")

    # 2. this pack's own legacy graph: marked keyframes and a marked audio ref
    mc_kf = [{"resolved_frame_index": 0, MC_KEY: 0, "latent": "KF"}]
    mc_ref = [{"kind": "audio", MC_AUDIO_KEY: 22.2, "audio_latent": "A"}]
    got = run(mc_kf, mc_ref)
    assert got["cond_video_latents"] == ["KF"], got
    assert got["cond_audio_latents"] == ["A"], got
    print("2. marked keyframes + marked ref: keyframe latent preserved")

    # Native Guide continuation uses a different private marker and may carry
    # audio in a keyframe while Ref2VA contributes its own tagged audio ref.
    # Both audio rows must survive, in the same keyframe-then-ref order as the
    # packed layout. This is the issue #38 scene-2 regression.
    native_kfs = [{
        "resolved_frame_index": 0,
        "h3_chain_context_visual": True,
        "latent": "NATIVE_KF",
        "audio_latent": "GUIDE_AUDIO",
    }]
    native_refs = [{
        "kind": "video_audio",
        "latent": "NATIVE_REF",
        "audio_latent": "TAGGED_AUDIO",
    }]
    got = run(native_kfs, native_refs)
    assert got["cond_video_latents"] == ["NATIVE_KF", "NATIVE_REF"], got
    assert got["cond_audio_latents"] == ["GUIDE_AUDIO", "TAGGED_AUDIO"], got
    print("2b. native Chain Guide + Ref2VA audio: both audio rows preserved")
    status = pp.native_payload_merge_status()
    assert status["native_keyframe_ref_merge"] is True, status
    assert status["native_keyframe_ref_audio_merge"] is True, status

    # A future/boundary Guide intentionally does not carry the normal visual
    # scheduling marker. Its payload-only marker must still activate the merge
    # when Ref2VA references coexist on a partially compatible core.
    future_kfs = [{
        "resolved_frame_index": 124,
        "h3_chain_future_end_anchor": True,
        "latent": "FUTURE_KF",
    }]
    got = run(future_kfs, native_refs)
    assert got["cond_video_latents"] == ["FUTURE_KF", "NATIVE_REF"], got
    assert got["cond_audio_latents"] == ["TAGGED_AUDIO"], got
    print("2c. future/boundary Guide + Ref2VA: payload merge activated")

    # 3. chaining under Ref2VA: the graph's own references are unmarked,
    # ours is marked, and every video latent must survive in list order
    mixed_refs = [{"kind": "image", "latent": "R1"},
                  {"kind": "video_audio", "latent": "R2", "audio_latent": "A2"},
                  {"kind": "audio", MC_AUDIO_KEY: 22.2, "audio_latent": "A3"}]
    got = run(mc_kf, mixed_refs)
    assert got["cond_video_latents"] == ["KF", "R1", "R2"], got
    assert got["cond_audio_latents"] == ["A2", "A3"], got
    print("3. marked keyframes + Ref2VA refs: merged in layout row order")

    # 4. one mechanism only, marked or not, is stock either way
    assert run(mc_kf, None)["cond_video_latents"] == ["KF"]
    assert run(None, mixed_refs)["cond_video_latents"] == ["R1", "R2"]
    print("4. one mechanism only: unchanged")

    # 5. H3-Multishot installs this merge globally from h3_avbank_probe at
    # package import. It produces the same video-latent ordering our graph
    # needs, while stock preserves reference audio and frame_count. Recognise
    # it and stand down instead of rejecting a safe, already-active owner.
    mb2 = make_model_base()
    original = mb2.MiniMaxH3.extra_conds

    def extra_conds(self, **kwargs):
        out = original(self, **kwargs)
        kfs = kwargs.get("minimax_keyframes")
        refs = kwargs.get("minimax_refs")
        if kfs and refs:
            out["minimax_payload"].cond["cond_video_latents"] = (
                [item["latent"] for item in kfs]
                + [item["latent"] for item in refs if "latent" in item])
        return out

    extra_conds._h3_avbank_merge = True
    # Real Multishot installations can inherit our generic marker from a
    # previously loaded payload wrapper. Its specific identity must win when
    # both markers are present (issue #38).
    extra_conds._h3_motion_context_payload_patch = True
    extra_conds.__module__ = "custom_nodes.h3_multishot.h3_avbank_probe"
    mb2.MiniMaxH3.extra_conds = extra_conds
    sys.modules.pop("patch_payload", None)
    pp2 = importlib.import_module("patch_payload")
    assert pp2._already_patched(mb2.MiniMaxH3) == "h3_multishot"
    assert pp2.apply_patch(), "compatible H3-Multishot patch was refused"
    assert mb2.MiniMaxH3.extra_conds is extra_conds, "compatible patch was wrapped"
    got = mb2.MiniMaxH3().extra_conds(
        minimax_keyframes=mc_kf, minimax_refs=mixed_refs,
        minimax_frame_count=124)["minimax_payload"].cond
    assert got["cond_video_latents"] == ["KF", "R1", "R2"], got
    assert got["cond_audio_latents"] == ["A2", "A3"], got
    assert got["frame_count"] == 124, got
    print("5. H3-Multishot AV-bank payload owner: compatible and reused")

    # If a live capability probe has specifically found missing keyframe
    # audio, priority may safely layer the marker-gated AV merge over this
    # one known video-only wrapper.
    claimed, detail = pp2.claim_patch_ownership(require_keyframe_audio=True)
    assert claimed, detail
    assert mb2.MiniMaxH3.extra_conds is pp2._patched_extra_conds
    got = mb2.MiniMaxH3().extra_conds(
        minimax_keyframes=native_kfs, minimax_refs=native_refs,
        minimax_frame_count=124)["minimax_payload"].cond
    assert got["cond_video_latents"] == ["NATIVE_KF", "NATIVE_REF"], got
    assert got["cond_audio_latents"] == ["GUIDE_AUDIO", "TAGGED_AUDIO"], got
    print("5b. H3-Multishot video merge: missing keyframe audio layered safely")

    # The marker alone is not a compatibility contract. Only Multishot's
    # known module is accepted; an unrelated wrapper remains refused.
    mb3 = make_model_base()
    foreign = mb3.MiniMaxH3.extra_conds
    foreign._h3_avbank_merge = True
    foreign.__module__ = "some_other_h3_pack.payload"
    sys.modules.pop("patch_payload", None)
    pp3 = importlib.import_module("patch_payload")
    assert pp3._already_patched(mb3.MiniMaxH3) == "foreign"
    assert not pp3.apply_patch(), "unrelated marker collision was accepted"
    competing = types.ModuleType("competing_h3_payload")
    competing.__file__ = (
        "J:\\ai\\ComfyUI\\custom_nodes\\Competing-H3-Pack\\patch_payload.py")
    competing._patched_extra_conds = foreign
    sys.modules[competing.__name__] = competing
    diagnostic = pp3.payload_owner_diagnostics(foreign)
    assert "some_other_h3_pack.payload" in diagnostic, diagnostic
    assert "custom_node=Competing-H3-Pack" in diagnostic, diagnostic
    assert "competing_h3_payload" in diagnostic, diagnostic
    assert "relationship=live_owner" in diagnostic, diagnostic
    print("6. lookalike marker from an unrelated pack: still refused")

    mb4 = make_model_base()
    older = load_payload_patch("h3_payload_vendor_older")
    assert older.apply_patch()
    newer = load_payload_patch("h3_payload_vendor_newer")
    assert newer.apply_patch()
    assert mb4.MiniMaxH3.extra_conds is older._patched_extra_conds
    claimed, detail = newer.claim_patch_ownership()
    assert claimed, detail
    assert mb4.MiniMaxH3.extra_conds is newer._patched_extra_conds
    got = mb4.MiniMaxH3().extra_conds(
        minimax_keyframes=mc_kf, minimax_refs=mixed_refs,
        minimax_frame_count=124)["minimax_payload"].cond
    assert got["cond_video_latents"] == ["KF", "R1", "R2"], got
    assert got["cond_audio_latents"] == ["A2", "A3"], got

    # ComfyUI may retain a wrapper on the live model class after reusing or
    # removing its dynamic import alias. The wrapper still executes with its
    # original globals, so priority must recover the captured stock method
    # there instead of asking users to remove a correctly installed pack.
    mb5 = make_model_base()
    older_orphaned = load_payload_patch("h3_payload_vendor_orphaned")
    assert older_orphaned.apply_patch()
    orphaned_wrapper = mb5.MiniMaxH3.extra_conds
    sys.modules.pop("h3_payload_vendor_orphaned")
    newer_after_refresh = load_payload_patch(
        "h3_payload_vendor_after_refresh")
    assert newer_after_refresh.apply_patch()
    assert mb5.MiniMaxH3.extra_conds is orphaned_wrapper
    claimed, detail = newer_after_refresh.claim_patch_ownership(
        require_keyframe_audio=True)
    assert claimed, detail
    assert mb5.MiniMaxH3.extra_conds is newer_after_refresh._patched_extra_conds
    got = mb5.MiniMaxH3().extra_conds(
        minimax_keyframes=native_kfs, minimax_refs=native_refs,
        minimax_frame_count=124)["minimax_payload"].cond
    assert got["cond_video_latents"] == ["NATIVE_KF", "NATIVE_REF"], got
    assert got["cond_audio_latents"] == ["GUIDE_AUDIO", "TAGGED_AUDIO"], got

    refused, detail = pp3.claim_patch_ownership()
    assert not refused, "priority replaced an unrelated payload wrapper"
    assert "some_other_h3_pack.payload" in detail, detail
    assert "custom_node=Competing-H3-Pack" in detail, detail
    sys.modules.pop(competing.__name__, None)
    print("7. explicit priority claims addressable and orphaned compatible "
          "payload owners and still refuses an unrelated wrapper")

    print("payload gate test passed")


if __name__ == "__main__":
    main()
