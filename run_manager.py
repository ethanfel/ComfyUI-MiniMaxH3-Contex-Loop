"""Discover and restore H3 Chain Plan archives without loading prompt history."""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from typing import Any

try:
    from .asset_store import RunAssetStore
except ImportError:  # Standalone unit tests import this module without a package.
    from asset_store import RunAssetStore

try:
    from .contracts_v05 import (
        AUDIO_POLICY_VERSION,
        CONTINUATION_POLICIES,
        TRANSITION_POLICY_VERSION,
        TRANSITION_PRESETS,
        audio_policy,
        migrate_continuation_mode,
        migrate_legacy_audio_mode,
        transition_policy,
    )
except ImportError:  # Standalone unit tests import this module without a package.
    from contracts_v05 import (
        AUDIO_POLICY_VERSION,
        CONTINUATION_POLICIES,
        TRANSITION_POLICY_VERSION,
        TRANSITION_PRESETS,
        audio_policy,
        migrate_continuation_mode,
        migrate_legacy_audio_mode,
        transition_policy,
    )


PLAN_NODE_TYPE = "MiniMaxH3ChainPlan"
MODERN_PLAN_NODE_TYPE = "MiniMaxH3ChainPlanModern"
PLAN_NODE_TYPES = (PLAN_NODE_TYPE, MODERN_PLAN_NODE_TYPE)
PLAN_WIDGET_NAMES = (
    "plan_json",
    "run_name",
    "generation_fingerprint",
    "width",
    "height",
    "context_length",
    "encode_mode",
    "anchor_mode",
    "crop",
    "audio_mode",
    "audio_context_length",
    "default_duration_seconds",
    "default_steps",
    "base_seed",
    "segment_crf",
    "video_blend_frames",
    "continuation_mode",
)
MODERN_PLAN_WIDGET_NAMES = (
    "plan_json",
    "run_name",
    "generation_fingerprint",
    "width",
    "height",
    "encode_mode",
    "crop",
    "default_duration_seconds",
    "default_steps",
    "base_seed",
    "segment_crf",
    "video_blend_frames",
)

H3_CONTEXT_LENGTHS = (
    1, 5, 22, 39, 56, 73, 90, 107, 124,
    141, 158, 175, 192, 209, 226, 243,
)
CONTINUATION_MODES = tuple(CONTINUATION_POLICIES)
SCENE_LORA_ROUTES = (
    "base", *(chr(ord("a") + offset) for offset in range(26)))


def _safe_name(value: Any, fallback: str = "") -> str:
    text = re.sub(r"[^A-Za-z0-9._-]+", "_", str(value or "").strip())
    text = text.strip("._-")
    return (text or fallback)[:96]


def _read_json(path: str) -> Any:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _json_string(value: Any) -> str | None:
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return None
        if not isinstance(parsed, (dict, list)):
            return None
        return json.dumps(parsed, ensure_ascii=False, indent=2)
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, indent=2)
    return None


def _restorable_widget_value(name: str, value: Any) -> Any:
    if name == "plan_json":
        return _json_string(value)
    if name == "base_seed" and isinstance(value, int):
        # aiohttp JSON would otherwise turn uint64 values above 2^53 into an
        # inexact JavaScript Number before the Plan widget sees them.
        return str(value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    # API-prompt links are lists such as [node_id, output_slot]. Restoring a
    # widget must never replace or invent graph connections.
    return None


def _api_prompt_inputs(document: Any, run_name: str) -> dict[str, Any]:
    if not isinstance(document, dict):
        return {}
    candidates = []
    exact = []
    for node in document.values():
        if (not isinstance(node, dict) or
                node.get("class_type") not in PLAN_NODE_TYPES):
            continue
        inputs = node.get("inputs")
        if not isinstance(inputs, dict):
            continue
        candidates.append(inputs)
        if _safe_name(inputs.get("run_name")) == run_name:
            exact.append(inputs)
    selected = exact[0] if exact else (candidates[0] if len(candidates) == 1 else None)
    if selected is None:
        return {}
    restored = {}
    for name in dict.fromkeys(PLAN_WIDGET_NAMES + MODERN_PLAN_WIDGET_NAMES):
        if name not in selected:
            continue
        value = _restorable_widget_value(name, selected[name])
        if value is not None:
            restored[name] = value
    return restored


def _workflow_inputs(document: Any, run_name: str) -> dict[str, Any]:
    if not isinstance(document, dict) or not isinstance(document.get("nodes"), list):
        return {}
    candidates = []
    exact = []
    for node in document["nodes"]:
        if (not isinstance(node, dict) or
                node.get("type") not in PLAN_NODE_TYPES):
            continue
        widgets = node.get("widgets_values")
        if not isinstance(widgets, list):
            continue
        candidate = (node.get("type"), widgets)
        candidates.append(candidate)
        if len(widgets) > 1 and _safe_name(widgets[1]) == run_name:
            exact.append(candidate)
    selected = exact[0] if exact else (candidates[0] if len(candidates) == 1 else None)
    if selected is None:
        return {}
    plan_type, selected = selected
    if plan_type == MODERN_PLAN_NODE_TYPE:
        if (len(selected) < len(MODERN_PLAN_WIDGET_NAMES)
                or selected[5] not in ("video", "frames")
                or selected[6] not in ("disabled", "center")):
            return {}
        restored = {}
        for name, value in zip(MODERN_PLAN_WIDGET_NAMES, selected):
            value = _restorable_widget_value(name, value)
            if value is not None:
                restored[name] = value
        return restored
    if len(selected) < 15:
        return {}
    # widgets_values is positional and old workflows can predate fields added
    # near the front of the Plan. Refuse a shifted layout rather than applying
    # plausible-looking values to the wrong widgets; plan.json still restores
    # the effective scene configuration.
    if (selected[5] not in H3_CONTEXT_LENGTHS
            or selected[6] not in ("video", "frames")
            or selected[7] not in ("head", "before")
            or selected[8] not in ("disabled", "center")
            or selected[9] not in (
                "source_track", "generated_audio", "source_plus_timeline")):
        return {}
    if len(selected) > 16 and selected[16] not in CONTINUATION_MODES:
        return {}
    restored = {}
    for name, value in zip(PLAN_WIDGET_NAMES, selected):
        value = _restorable_widget_value(name, value)
        if value is not None:
            restored[name] = value
    # 0.3 workflows end at segment_crf. New widgets are appended, so old
    # positional values remain exact and receive their compatibility defaults.
    restored.setdefault("video_blend_frames", 0)
    restored.setdefault("continuation_mode", "guide")
    return restored


def _editor_plan(archive: dict[str, Any]) -> dict[str, Any]:
    existing = archive.get("editor_plan")
    if isinstance(existing, dict) and isinstance(existing.get("shots"), list):
        return existing
    shots = []
    for offset, shot in enumerate(archive.get("shots") or []):
        if not isinstance(shot, dict):
            continue
        value = {
            "id": shot.get("id", "clip_%04d" % (offset + 1)),
            "prompt": shot.get("scene_prompt", shot.get("prompt", "")),
        }
        if shot.get("raw_frames") is not None:
            value["length"] = int(shot["raw_frames"])
        if shot.get("steps") is not None:
            value["steps"] = int(shot["steps"])
        if shot.get("seed") is not None:
            value["seed"] = str(shot["seed"])
        if shot.get("continuation_mode") in CONTINUATION_MODES:
            value["continuation_mode"] = shot["continuation_mode"]
        if (shot.get("context_length") == 0
                or shot.get("context_length") in H3_CONTEXT_LENGTHS):
            value["context_length"] = int(shot["context_length"])
        audio_context = shot.get("audio_context_length")
        if (isinstance(audio_context, int) and not isinstance(audio_context, bool)
                and 0 <= audio_context <= 240):
            value["audio_context_length"] = audio_context
        lora_route = str(shot.get("lora_route") or "").strip().lower()
        if lora_route in SCENE_LORA_ROUTES and lora_route != "base":
            value["lora_route"] = lora_route
        shots.append(value)
    return {
        "prompt_prefix": archive.get("prompt_prefix", ""),
        "shots": shots,
    }


def _archive_inputs(archive: Any, run_name: str) -> dict[str, Any]:
    if not isinstance(archive, dict):
        return {}
    editor = _editor_plan(archive)
    if not editor.get("shots"):
        return {}
    restored: dict[str, Any] = {
        "plan_json": json.dumps(editor, ensure_ascii=False, indent=2),
        "run_name": run_name,
    }
    compatibility = archive.get("compatibility")
    if isinstance(compatibility, dict):
        for name in (
            "generation_fingerprint", "width", "height", "context_length",
            "encode_mode", "anchor_mode", "crop", "audio_mode",
            "audio_context_length", "segment_crf", "video_blend_frames",
            "continuation_mode",
        ):
            if name in compatibility:
                restored[name] = compatibility[name]
    if "segment_crf" in archive:
        restored["segment_crf"] = archive["segment_crf"]
    restored.setdefault("video_blend_frames", 0)
    restored.setdefault("continuation_mode", "guide")
    return restored


def archive_policy_inputs(archive: Any) -> dict[str, dict[str, Any]]:
    """Return exact widget values for connected 0.5 policy nodes.

    Plan archives store resolved typed policies in compatibility metadata.  A
    restore must project those records back onto the upstream policy widgets;
    writing only the Plan's hidden 0.4 fallbacks has no effect while a typed
    policy input is connected.
    """
    if not isinstance(archive, dict):
        return {}
    compatibility = archive.get("compatibility")
    if not isinstance(compatibility, dict):
        return {}

    restored: dict[str, dict[str, Any]] = {}
    saved_audio = compatibility.get("audio_policy")
    try:
        if (isinstance(saved_audio, dict) and
                saved_audio.get("version") == AUDIO_POLICY_VERSION):
            resolved_audio = audio_policy(
                saved_audio.get("final_audio"),
                saved_audio.get("source_reference"),
                saved_audio.get("generated_continuity"),
                saved_audio.get("source_audio_target", "off"))
        else:
            resolved_audio = migrate_legacy_audio_mode(
                compatibility.get("audio_mode", "generated_audio"))
        restored["audio_policy"] = {
            "final_audio": resolved_audio["final_audio"],
            "source_reference": resolved_audio["source_reference"],
            "generated_continuity": resolved_audio["generated_continuity"],
        }
        if resolved_audio.get("source_audio_target") == "locked":
            restored["audio_policy"]["source_audio_target"] = "locked"
    except (TypeError, ValueError):
        # A malformed optional policy must not prevent prompt/Plan recovery.
        pass

    saved_transition = compatibility.get("transition_policy")
    try:
        if (isinstance(saved_transition, dict) and
                saved_transition.get("version") == TRANSITION_POLICY_VERSION and
                saved_transition.get("preset") in TRANSITION_PRESETS):
            resolved_transition = transition_policy(
                saved_transition.get("preset"),
                expert_override=bool(saved_transition.get(
                    "expert_override", False)),
                continuation_mode=saved_transition.get("continuation_mode"),
                context_length=saved_transition.get("context_length"))
        else:
            mode = migrate_continuation_mode(
                compatibility.get("continuation_mode", "guide"))
            context = int(compatibility.get("context_length", 22))
            matching = next((
                name for name, preset in TRANSITION_PRESETS.items()
                if preset["continuation_mode"] == mode and
                int(preset["context_length"]) == context
            ), None)
            resolved_transition = transition_policy(
                matching or "guide", expert_override=matching is None,
                continuation_mode=mode, context_length=context)
        restored["transition_policy"] = {
            "preset": resolved_transition["preset"],
            "expert_override": bool(
                resolved_transition.get("expert_override", False)),
            "expert_continuation_mode": resolved_transition[
                "continuation_mode"],
            "expert_context_length": int(
                resolved_transition["context_length"]),
        }
    except (TypeError, ValueError):
        pass
    return restored


def _scene_count_from_plan(path: str) -> int | None:
    if not os.path.isfile(path):
        return None
    try:
        archive = _read_json(path)
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(archive, dict):
        return None
    editor = archive.get("editor_plan")
    shots = editor.get("shots") if isinstance(editor, dict) else archive.get("shots")
    return len(shots) if isinstance(shots, list) else None


def _iso_mtime(path: str) -> str:
    timestamp = os.path.getmtime(path)
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat(
        timespec="seconds").replace("+00:00", "Z")


class RunArchiveManager:
    def __init__(self, output_root: str, input_root: str | None = None):
        self.output_root = os.path.abspath(output_root)
        self.chains_root = os.path.join(self.output_root, "h3_chains")
        self.assets = RunAssetStore(self.output_root, input_root)

    def _run_dir(self, run_name: Any) -> tuple[str, str]:
        run = _safe_name(run_name)
        if not run:
            raise ValueError("A non-empty H3 chain run_name is required.")
        path = os.path.realpath(os.path.join(self.chains_root, run))
        root = os.path.realpath(self.output_root)
        if os.path.commonpath([root, path]) != root:
            raise ValueError("H3 run path escapes the output directory.")
        return path, run

    def list_runs(self) -> list[dict[str, Any]]:
        if not os.path.isdir(self.chains_root):
            return []
        runs = []
        for entry in os.scandir(self.chains_root):
            if not entry.is_dir(follow_symlinks=False):
                continue
            run_name = _safe_name(entry.name)
            if not run_name or run_name != entry.name:
                continue
            directory = entry.path
            plan_path = os.path.join(directory, "plan.json")
            api_path = os.path.join(directory, "api_prompt.json")
            workflow_path = os.path.join(directory, "workflow.json")
            archive_paths = [path for path in (plan_path, api_path, workflow_path)
                             if os.path.isfile(path)]
            checkpoint_dir = os.path.join(directory, "checkpoints")
            asset_manifest = os.path.join(directory, "references", "manifest.json")
            checkpoints = 0
            if os.path.isdir(checkpoint_dir):
                checkpoints = sum(
                    1 for name in os.listdir(checkpoint_dir)
                    if re.fullmatch(r"clip_\d{4}\.json", name))
            modified_paths = [directory]
            if os.path.isdir(checkpoint_dir):
                modified_paths.append(checkpoint_dir)
            if os.path.isfile(asset_manifest):
                modified_paths.append(asset_manifest)
            modified_paths.extend(archive_paths)
            newest = max(modified_paths, key=os.path.getmtime)
            try:
                asset_summary = self.assets.summary(run_name)
            except (OSError, ValueError, json.JSONDecodeError):
                asset_summary = {"asset_count": 0, "asset_bytes": 0}
            runs.append({
                "run_name": run_name,
                "modified_at": _iso_mtime(newest),
                "scene_count": _scene_count_from_plan(plan_path),
                "checkpoint_count": checkpoints,
                "restorable": bool(archive_paths),
                "archive_bytes": (
                    sum(os.path.getsize(path) for path in archive_paths)
                    + int(asset_summary.get("asset_bytes") or 0)),
                **asset_summary,
                "sources": {
                    "api_prompt": os.path.isfile(api_path),
                    "workflow": os.path.isfile(workflow_path),
                    "plan": os.path.isfile(plan_path),
                },
            })
        runs.sort(key=lambda item: item["modified_at"], reverse=True)
        return runs

    def load_plan(self, run_name: Any) -> dict[str, Any]:
        """Load the complete saved Plan without restoring archived assets."""
        directory, run = self._run_dir(run_name)
        if not os.path.isdir(directory):
            raise ValueError("H3 run %r does not exist." % run)

        restored: dict[str, Any] = {}
        policy_inputs: dict[str, dict[str, Any]] = {}
        sources = []
        warnings = []
        plan_path = os.path.join(directory, "plan.json")
        if os.path.isfile(plan_path):
            try:
                archive = _read_json(plan_path)
                restored.update(_archive_inputs(archive, run))
                policy_inputs.update(archive_policy_inputs(archive))
                if restored:
                    sources.append("plan.json")
            except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
                warnings.append("plan.json: %s" % exc)

        workflow_path = os.path.join(directory, "workflow.json")
        if os.path.isfile(workflow_path):
            try:
                values = _workflow_inputs(_read_json(workflow_path), run)
                if values:
                    restored.update(values)
                    sources.append("workflow.json")
            except (OSError, json.JSONDecodeError) as exc:
                warnings.append("workflow.json: %s" % exc)

        api_path = os.path.join(directory, "api_prompt.json")
        if os.path.isfile(api_path):
            try:
                values = _api_prompt_inputs(_read_json(api_path), run)
                if values:
                    restored.update(values)
                    sources.append("api_prompt.json")
            except (OSError, json.JSONDecodeError) as exc:
                warnings.append("api_prompt.json: %s" % exc)

        restored["run_name"] = run
        if "plan_json" not in restored:
            detail = "; ".join(warnings) if warnings else "no usable Plan archive was found"
            raise ValueError("Could not restore H3 run %r: %s." % (run, detail))
        parsed = json.loads(restored["plan_json"])
        shots = parsed.get("shots") if isinstance(parsed, dict) else parsed
        return {
            "run_name": run,
            "scene_count": len(shots) if isinstance(shots, list) else None,
            "plan_inputs": restored,
            "policy_inputs": policy_inputs,
            "sources": sources,
            "warnings": warnings,
        }

    def load_run(self, run_name: Any) -> dict[str, Any]:
        payload = self.load_plan(run_name)
        run = payload["run_name"]
        warnings = list(payload["warnings"])
        try:
            assets = self.assets.prepare_restore(run)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            assets = {"run_name": run, "bindings": [], "warnings": [str(exc)]}
        warnings.extend(assets.get("warnings") or [])
        return {
            **payload,
            "warnings": warnings,
            "assets": assets,
        }
