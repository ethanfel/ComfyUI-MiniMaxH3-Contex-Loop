"""Small execution-scoped receipts; never retain conditioning or GPU tensors."""

from collections import OrderedDict
import json
import threading

from .reference_cache_migration import ReferenceCacheMigrator


_LOCK = threading.RLock()
_USES = OrderedDict()


def _context():
    try:
        from comfy_execution.utils import get_executing_context
        return get_executing_context()
    except ImportError:
        return None


def note_converted_use(metadata, output_root):
    context = _context()
    conversion = metadata.get("legacy_conversion") or {}
    if context is None or conversion.get("delete_after_success") is not True:
        return
    key = (str(context.prompt_id), str(context.node_id), context.list_index,
           str(metadata["metadata"]))
    with _LOCK:
        _USES[key] = (str(output_root), json.loads(json.dumps(metadata)))
        _USES.move_to_end(key)
        # Failed/cancelled runs can leave receipts, but they cannot authorize a
        # different prompt and must not grow memory indefinitely.
        while len(_USES) > 1024:
            _USES.popitem(last=False)


def _sampling_ancestors(dynprompt, saver_id):
    """Conservative graph proof: saved pixels descend through a known sampler.

    Unknown wrappers are allowed to render but cannot trigger automatic bundle
    deletion. Merely connecting conditioning's passthrough pixels is not proof.
    """
    if dynprompt is None or not saver_id:
        return set()
    sampler_types = {"SamplerCustom", "SamplerCustomAdvanced", "KSampler",
                     "KSamplerAdvanced", "CATUltimateSDUpscaleGuiderVideo"}

    def link(value):
        return (isinstance(value, (list, tuple)) and len(value) == 2
                and isinstance(value[0], str) and isinstance(value[1], int))

    saver = dynprompt.get_node(str(saver_id))
    pending = [(value[0], value[1], False) for key, value in saver.get("inputs", {}).items()
               if key in ("images", "video") and link(value)]
    visited, proven = set(), set()
    while pending:
        node_id, slot, conditioning = pending.pop()
        if (node_id, slot, conditioning) in visited:
            continue
        visited.add((node_id, slot, conditioning))
        node = dynprompt.get_node(node_id)
        kind = str(node.get("class_type", ""))
        sampled = kind in sampler_types or kind.startswith("UltimateSDUpscale")
        if conditioning:
            proven.add((node_id, slot))
        for name, value in node.get("inputs", {}).items():
            if link(value):
                uses_conditioning = conditioning or (sampled and name in (
                    "positive", "negative", "guider", "conditioning"))
                pending.append((value[0], value[1], uses_conditioning))
    return proven


def confirm_saved_use(dynprompt, saver_id, saved_metadata, output_root, logger):
    context = _context()
    if context is None:
        return []
    try:
        with _LOCK:
            uses = [(key, value) for key, value in _USES.items()
                    if key[0] == str(context.prompt_id)
                    and key[2] == context.list_index
                    and value[0] == str(output_root)]
        if not uses:
            return []
        ancestors = _sampling_ancestors(dynprompt, saver_id or context.node_id)
        uses = [(key, value) for key, value in uses if (key[1], 0) in ancestors]
        retired = []
        for key, (_, metadata) in uses:
            try:
                receipt = ReferenceCacheMigrator(output_root).retire_after_success(metadata, saved_metadata)
                if receipt is not None:
                    retired.append(receipt)
                    logger.info("H3 retired legacy reference bundle %s after verified render save; "
                                "converted tensor objects and legacy JSON retained (%d bytes unlinked).",
                                receipt["legacy"]["tensors"], receipt["retired_bytes"])
                    if receipt.get("directory_sync_error"):
                        logger.warning("H3 legacy bundle was deleted, but directory sync failed: %s",
                                       receipt["directory_sync_error"])
                with _LOCK:
                    _USES.pop(key, None)
            except Exception as exc:
                # Cleanup cannot turn a committed render into a failed render.
                logger.warning("H3 kept legacy reference bundle after save: %s", exc)
        return retired
    except Exception as exc:
        logger.warning("H3 reference-cache cleanup skipped: %s", exc)
        return []
