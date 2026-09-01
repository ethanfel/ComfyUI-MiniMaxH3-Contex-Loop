"""Let keyframes and refs coexist.

Older `MiniMaxH3.extra_conds` implementations in comfy/model_base.py fill the
payload from two independent `if` blocks. The keyframe block sets the Guide
video/audio lists, then the refs block **overwrites** them:

    if keyframes is not None:
        payload["cond_video_latents"] = [kf["latent"] for kf in keyframes]
    if refs is not None:
        payload["cond_video_latents"] = [r["latent"] for r in refs if "latent" in r]
        payload["cond_audio_latents"] = [r["audio_latent"] for r in refs ...]

So attaching an audio-only ref alongside keyframes wipes the keyframe video
content: an audio-only block has no "latent" key, the list comes back empty,
and the cond rows the layout built have nothing to fill them.

The layout itself handles the combination fine. Keyframe cond rows are
emitted first, ref rows second, target rows last, which is exactly the order
the forward pass expects when it writes rows into the never-denoised slots.
Only this payload assignment is in the way.

This wrapper re-runs the same logic and concatenates instead, keeping
keyframe latents first to match the row order. Both video and audio must be
merged: native H3 Guides may carry continuation audio while Ref2VA carries a
separate tagged/source audio reference in the same conditioning.

It only does that for graphs that asked for it. The wrapper is installed
process-wide, but it returns stock output unless a keyframe or a ref
carries one of this pack's markers. Graphs that combine stock keyframes
and refs without going anywhere near Motion Context therefore behave
exactly as they did before the pack was installed. That matters because
such graphs exist: a Ref2VA workflow with a last_frame anchor is a
legitimate combination of both mechanisms and has nothing to do with
chaining. Whether stock's overwrite is a bug there is not this pack's
call to make.

Graphs using only one mechanism are unaffected either way: with no refs
the ref list is empty, with no keyframes the keyframe list is.

The order is what makes this safe under Ref2VA, where the ref list holds
the graph's own image, video and audio blocks as well as ours. Stock
builds the layout as text, then cond rows, then reference blocks in list
order, so keyframe latents first and reference latents in list order is
exactly the order the rows are waiting in. Audio is filled from the same
list in the same order, and an audio-only block contributes nothing to
the video list, so the two stay in step however the graph is wired.
"""

import logging
import sys

import torch

import comfy.model_base as model_base

_LOG = logging.getLogger("h3_motion_context")

# Duplicated from patch_layout rather than imported, so this module stays
# independently testable against a fake model_base. The marker strings are
# a shared ABI across the two patches, the node, and any pack vendoring
# them: rename in lockstep or not at all.
MC_KEY = "motion_context_index"
MC_AUDIO_KEY = "motion_context_audio_end_frame"
CHAIN_VISUAL_KEY = "h3_chain_context_visual"
CHAIN_AUDIO_KEY = "h3_chain_context_audio"
CHAIN_FUTURE_KEY = "h3_chain_future_end_anchor"

# Marker set on our wrapper so a second copy of this file, vendored into
# another pack, can recognise it and stand down instead of wrapping it.
# Shared ABI across every pack that vendors this patch.
PATCH_MARKER = "_h3_motion_context_payload_patch"
MULTISHOT_PATCH_MARKER = "_h3_avbank_merge"

_orig_extra_conds = None
_applied = False


def _callable_source(fn):
    """Best-effort source path for a dynamically imported wrapper."""
    code = getattr(fn, "__code__", None)
    source = str(getattr(code, "co_filename", "") or "")
    owner_globals = getattr(fn, "__globals__", None)
    if not source and isinstance(owner_globals, dict):
        source = str(owner_globals.get("__file__") or "")
    if not source:
        owner_module = sys.modules.get(str(getattr(fn, "__module__", "")))
        source = str(getattr(owner_module, "__file__", "") or "")
    return source


def _custom_node_folder(source):
    """Extract ``custom_nodes/<pack>`` from POSIX or Windows paths."""
    normalized = str(source or "").replace("\\", "/")
    marker = "/custom_nodes/"
    if marker not in normalized:
        return "unknown"
    tail = normalized.split(marker, 1)[1]
    return tail.split("/", 1)[0] or "unknown"


def _loaded_payload_patch_modules(current=None):
    """List loaded modules that look capable of owning this wrapper family."""
    found = []
    for name, module in list(sys.modules.items()):
        if module is None:
            continue
        try:
            candidate = getattr(module, "_patched_extra_conds", None)
            source = str(getattr(module, "__file__", "") or "")
            basename = source.replace("\\", "/").rsplit("/", 1)[-1]
            relevant = bool(
                candidate is current
                or getattr(candidate, PATCH_MARKER, False)
                or basename == "patch_payload.py"
            )
        except Exception:
            continue
        if not relevant:
            continue
        relationship = "live_owner" if candidate is current else "same_family"
        found.append("%s [relationship=%s; custom_node=%s; source=%s]" % (
            name,
            relationship,
            _custom_node_folder(source),
            source or "unknown",
        ))
    return sorted(set(found))


def payload_owner_diagnostics(fn=None):
    """Describe the live payload owner without relying on import aliases.

    ComfyUI loads custom-node packages under dynamic module names, and an old
    wrapper can survive after its alias is replaced. Function globals and code
    paths are therefore more authoritative than the current ``sys.modules``
    entry. This text is intentionally suitable for pasting into an issue.
    """
    if fn is None:
        cls = getattr(model_base, "MiniMaxH3", None)
        fn = getattr(cls, "extra_conds", None) if cls is not None else None
    if fn is None:
        return "live payload owner is unavailable"

    module_name = str(getattr(fn, "__module__", "") or "unknown")
    function_name = str(
        getattr(fn, "__qualname__", "")
        or getattr(fn, "__name__", "")
        or type(fn).__name__)
    source = _callable_source(fn)
    markers = []
    if getattr(fn, PATCH_MARKER, False):
        markers.append(PATCH_MARKER)
    if getattr(fn, MULTISHOT_PATCH_MARKER, False):
        markers.append(MULTISHOT_PATCH_MARKER)
    if hasattr(fn, "__wrapped__"):
        markers.append("__wrapped__")

    owner_globals = getattr(fn, "__globals__", None)
    captures = []
    if isinstance(owner_globals, dict):
        for name, value in owner_globals.items():
            lowered = str(name).lower()
            if (callable(value) and "cond" in lowered
                    and ("orig" in lowered or "stock" in lowered)):
                captures.append(str(name))

    loaded = _loaded_payload_patch_modules(fn)
    return (
        "live_owner=%s.%s; custom_node=%s; source=%s; markers=%s; "
        "captured_conditioning_methods=%s; loaded_payload_patch_modules=%s"
        % (
            module_name,
            function_name,
            _custom_node_folder(source),
            source or "unknown",
            ",".join(markers) or "none",
            ",".join(sorted(captures)) or "none",
            " | ".join(loaded) or "none",
        )
    )


def _patched_extra_conds(self, **kwargs):
    out = _orig_extra_conds(self, **kwargs)

    keyframes = kwargs.get("minimax_keyframes", None)
    refs = kwargs.get("minimax_refs", None)
    if not keyframes or not refs:
        return out  # only one mechanism in play, stock behaviour is correct
    if not (any(MC_KEY in kf or CHAIN_VISUAL_KEY in kf
                or CHAIN_AUDIO_KEY in kf or CHAIN_FUTURE_KEY in kf
                for kf in keyframes)
            or any(MC_AUDIO_KEY in r for r in refs)):
        # nothing here came from this pack. The layout patch is gated the
        # same way, so leaving the payload alone keeps the two consistent
        # and leaves unrelated graphs bit-identical to stock.
        return out

    cond = out.get("minimax_payload", None)
    payload = getattr(cond, "cond", None) if cond is not None else None
    if not isinstance(payload, dict):
        _LOG.warning("h3_motion_context: could not reach the H3 payload, "
                     "keyframe latents may have been overwritten by refs")
        return out

    kf_video = [kf["latent"] for kf in keyframes if "latent" in kf]
    ref_video = [r["latent"] for r in refs if "latent" in r]
    kf_audio = [kf["audio_latent"] for kf in keyframes
                if kf.get("audio_latent") is not None]
    ref_audio = [r["audio_latent"] for r in refs
                 if r.get("audio_latent") is not None]
    payload["cond_video_latents"] = kf_video + ref_video
    payload["cond_audio_latents"] = kf_audio + ref_audio
    # only write frame_count when we actually have one. This wrapper fires
    # for ANY graph combining keyframes and refs, not just ours; a graph
    # that reaches here without minimax_frame_count may have a valid value
    # already set by the original, and overwriting it with None would break
    # the last-frame anchor branch downstream.
    fc = kwargs.get("minimax_frame_count", None)
    if fc is not None:
        payload["frame_count"] = fc
    return out


setattr(_patched_extra_conds, PATCH_MARKER, True)


def native_payload_merge_status():
    """Behaviorally probe the live keyframe + Ref2VA payload merge.

    Native arbitrary Guide layout and payload merging landed in different
    ComfyUI revisions.  A partially updated runtime can therefore reserve
    both Guide and reference rows in ``PackedLayout`` while ``extra_conds``
    supplies only the reference tensors.  Probe the callable that is actually
    installed instead of relying on a ComfyUI version or source inspection.
    """
    status = {
        "native_keyframe_ref_merge": False,
        "native_keyframe_ref_audio_merge": False,
    }
    cls = getattr(model_base, "MiniMaxH3", None)
    fn = getattr(cls, "extra_conds", None) if cls is not None else None
    if fn is None:
        status["error"] = "MiniMaxH3.extra_conds is unavailable"
        return status
    try:
        probe = cls.__new__(cls)
        # BaseModel.extra_conds only consults these fields when called without
        # cross-attention, masks, or latent-shape inputs.
        probe.concat_keys = ()
        probe.latent_shapes = None
        # Real tensors keep the probe compatible with otherwise harmless
        # wrappers that validate latent shape/dtype before forwarding to core.
        keyframe_video = torch.zeros((1, 24, 1, 2, 2))
        reference_video = torch.ones((1, 24, 1, 2, 2))
        keyframe_audio = torch.zeros((1, 32, 2, 2))
        reference_audio = torch.ones((1, 32, 2, 2))
        keyframes = [{
            "resolved_frame_index": 0,
            "latent": keyframe_video,
            "audio_latent": keyframe_audio,
            CHAIN_VISUAL_KEY: True,
            CHAIN_AUDIO_KEY: True,
        }]
        refs = [
            {"kind": "image", "latent": reference_video,
             "latent_h": 2, "latent_w": 2},
            {"kind": "audio", "ref_audio_t": 1,
             "audio_latent": reference_audio},
        ]
        result = fn(
            probe, minimax_keyframes=keyframes, minimax_refs=refs)
        wrapped = (result.get("minimax_payload")
                   if isinstance(result, dict) else None)
        payload = getattr(wrapped, "cond", wrapped)
        if not isinstance(payload, dict):
            status["error"] = "MiniMaxH3 payload is not a dictionary"
            return status
        videos = payload.get("cond_video_latents", [])
        audios = payload.get("cond_audio_latents", [])
        status["native_keyframe_ref_merge"] = bool(
            len(videos) == 2
            and videos[0] is keyframe_video
            and videos[1] is reference_video)
        status["native_keyframe_ref_audio_merge"] = bool(
            len(audios) == 2
            and audios[0] is keyframe_audio
            and audios[1] is reference_audio)
    except Exception as exc:
        status["error"] = repr(exc)
    return status


def _already_patched(cls):
    """Has another copy of this file already wrapped extra_conds?

    Returns None, "same", "other", "h3_multishot" or "foreign". The
    marker only recognises copies new enough to set it, so a wrapper
    merely NAMED like ours counts as another copy: an older version, or
    a fork, and the second one in stands down. Anything else wrapping
    extra_conds is a different pack solving the same problem its own way,
    and this one refuses rather than stacking on it. See patch_layout's
    version for how the detection works and what it cannot see.
    """
    fn = getattr(cls, "extra_conds", None)
    if fn is None:
        return None
    if getattr(fn, PATCH_MARKER, False):
        return "same"
    if getattr(fn, "__name__", "") == "_patched_extra_conds":
        return "other"
    # H3-Multishot installs its AV-bank merge at package import time. Its
    # wrapper calls stock first, then rebuilds cond_video_latents as keyframes
    # followed by reference video latents -- the same row order required here.
    # Stock already supplies reference audio latents and frame_count, so that
    # wrapper is sufficient for our marked Ref2VA + motion-context payloads.
    # Require both its public marker and source-module suffix: a coincidental
    # attribute on an unrelated wrapper must remain a hard collision.
    where = str(getattr(fn, "__module__", "") or "")
    if (getattr(fn, MULTISHOT_PATCH_MARKER, False)
            and (where == "h3_avbank_probe"
                 or where.endswith(".h3_avbank_probe"))):
        return "h3_multishot"
    if hasattr(fn, "__wrapped__"):
        return "foreign"
    home = getattr(cls, "__module__", None)
    where = getattr(fn, "__module__", None)
    if home and where and where != home:
        return "foreign"
    return None


def apply_patch():
    global _orig_extra_conds, _applied
    if _applied:
        return True
    cls = getattr(model_base, "MiniMaxH3", None)
    if cls is None or not hasattr(cls, "extra_conds"):
        _LOG.warning("h3_motion_context: MiniMaxH3.extra_conds not found, "
                     "keyframes and refs cannot be combined")
        return False
    who = _already_patched(cls)
    if who == "foreign":
        _LOG.warning(
            "h3_motion_context: another pack has already patched "
            "MiniMaxH3.extra_conds (it now comes from %r). Both packs are "
            "solving the same keyframe/ref collision and they cannot both "
            "own it, so this one is refusing. Disable the identified "
            "competing pack or duplicate folder and fully restart ComfyUI. "
            "%s",
            getattr(getattr(cls, "extra_conds", None), "__module__", "?"),
            payload_owner_diagnostics(getattr(cls, "extra_conds", None)))
        return False
    if who:
        # report success: the patch IS active, just not ours, and the
        # calling pack's nodes check is_applied() before they will run
        _applied = True
        if who == "same":
            _LOG.info("h3_motion_context: keyframe/ref coexistence already "
                      "enabled by another pack, standing down")
        elif who == "h3_multishot":
            _LOG.info(
                "h3_motion_context: H3-Multishot's compatible AV-bank "
                "payload merge is active; standing down without stacking")
        else:
            _LOG.warning(
                "h3_motion_context: the H3 payload patch is already "
                "installed by a DIFFERENT copy of this code (another "
                "version, or a fork). Standing down. If you have more than "
                "one H3 Motion Context folder in custom_nodes, keep one and "
                "remove the rest.")
        return True
    _orig_extra_conds = cls.extra_conds
    cls.extra_conds = _patched_extra_conds
    _applied = True
    _LOG.info("h3_motion_context: keyframe/ref coexistence enabled")
    return True


def claim_patch_ownership(*, require_keyframe_audio=False):
    """Prefer this copy over an older compatible copy of the same patch.

    This is intentionally stricter than merely replacing whatever currently
    owns ``extra_conds``. Only a wrapper carrying our shared marker (or the
    exact legacy wrapper name) can be displaced, and its module must expose
    the unwrapped stock callable it captured. H3-Multishot's known-compatible
    merge remains in place; unknown wrappers are refused.

    Returns ``(ok, detail)`` for the visible Patch Priority pass-through node.
    """
    global _orig_extra_conds, _applied
    cls = getattr(model_base, "MiniMaxH3", None)
    current = getattr(cls, "extra_conds", None) if cls is not None else None
    if current is None:
        return False, "MiniMaxH3.extra_conds is unavailable"
    if current is _patched_extra_conds:
        _applied = True
        return True, "payload owned by this pack"

    who = _already_patched(cls)
    if who == "h3_multishot":
        if not require_keyframe_audio:
            _applied = True
            return True, "compatible H3-Multishot payload merge retained"
        # Its known-compatible wrapper merges the video lists but historically
        # leaves audio to the underlying ComfyUI implementation. If the live
        # capability probe has already shown that keyframe audio is missing,
        # layer our marker-gated AV merge over that known wrapper. Unrelated
        # wrappers remain refused below.
        _orig_extra_conds = current
        cls.extra_conds = _patched_extra_conds
        _applied = True
        _LOG.info(
            "h3_motion_context: marker-gated keyframe-audio merge layered "
            "over H3-Multishot's compatible video merge")
        return True, "keyframe-audio merge layered over H3-Multishot"
    if who not in ("same", "other"):
        return False, (
            "payload owner is %s; only another H3 Motion Context copy can "
            "be safely replaced. %s" % (
                who or "stock/uninitialized",
                payload_owner_diagnostics(current)))

    # ComfyUI's custom-node loader can leave an active function reachable from
    # the model class after its import alias has been reused by another copy or
    # disappeared from sys.modules. A function keeps the exact globals
    # dictionary it executes against, so that is the authoritative place to
    # recover the stock method captured by another compatible copy. Keep the
    # module lookup as a fallback for unusual callable wrappers.
    owner_globals = getattr(current, "__globals__", None)
    original = (owner_globals.get("_orig_extra_conds")
                if isinstance(owner_globals, dict) else None)
    if not callable(original):
        owner_module = sys.modules.get(
            str(getattr(current, "__module__", "")))
        original = getattr(owner_module, "_orig_extra_conds", None)
    if not callable(original) or original is current:
        return False, (
            "the existing H3 Motion Context payload wrapper does not expose "
            "its captured stock method. Disable the competing pack or "
            "duplicate folder identified below, then fully restart ComfyUI. "
            "%s" % payload_owner_diagnostics(current))
    home = str(getattr(cls, "__module__", "") or "")
    where = str(getattr(original, "__module__", "") or "")
    if (hasattr(original, "__wrapped__") or (home and where != home)
            or getattr(original, PATCH_MARKER, False)):
        return False, (
            "the existing payload wrapper captured another unknown wrapper; "
            "refusing to discard it. %s" %
            payload_owner_diagnostics(current))

    _orig_extra_conds = original
    cls.extra_conds = _patched_extra_conds
    _applied = True
    _LOG.info(
        "h3_motion_context: this pack claimed keyframe/ref payload ownership "
        "from compatible module %s", getattr(current, "__module__", "?"))
    return True, "payload ownership claimed from a compatible older copy"


def is_applied():
    return _applied
