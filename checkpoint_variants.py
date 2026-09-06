"""Read-only catalogue of saved processing takes, separate from generation lineage.

Listing reads JSON and file sizes, never model tensors or multi-GB checksums.
Execution remains responsible for artifact integrity and latent validation.
"""

import json
from pathlib import Path
import re


STAGES = ("derope", "latent_upscale", "pixel_upscale", "other")


def processing_stage(config):
    config = config if isinstance(config, dict) else {}
    recipe = config.get("recipe") or {}
    recipe = recipe if isinstance(recipe, dict) else {}
    explicit = recipe.get("stage")
    if explicit in STAGES:
        return explicit
    # The released combined LBH/DeRoPE example records this recipe field.
    # Never infer a processing stage from a user-chosen folder/profile name.
    derope = recipe.get("derope")
    if derope is True or (isinstance(derope, str) and derope.strip().lower()
                          not in ("", "false", "off", "none", "disabled")):
        return "derope"
    return {"h3_latent": "latent_upscale", "pixel": "pixel_upscale"}.get(
        config.get("backend"), "other")


def saved_checkpoint_variants(output_root, run_name, originals):
    root = Path(output_root).resolve()
    run = (root / "h3_chains" / run_name).resolve()
    if run.parent != root / "h3_chains":
        raise ValueError("Invalid checkpoint variant run directory.")
    records, warnings, seen = [], [], set()

    def inside(path, parent):
        resolved = path.resolve()
        if not resolved.is_relative_to(parent):
            raise ValueError("Saved processing artifact escapes its profile directory.")
        return resolved

    def read(path):
        with path.open(encoding="utf-8") as handle:
            value = json.load(handle)
        if not isinstance(value, dict):
            raise ValueError("Saved processing metadata is not an object.")
        return value

    def media(path):
        rel = path.relative_to(root)
        return {"filename": rel.name, "subfolder": str(rel.parent), "type": "output"}

    parents = [run / "upscaled"]
    chapters = run / "chapters"
    if chapters.is_dir():
        parents.extend(path / "upscaled" for path in chapters.iterdir() if path.is_dir())
    for parent in parents:
        try:
            inside(parent, run)
            if not parent.is_dir():
                continue
            profiles = sorted(parent.iterdir())
        except (OSError, ValueError) as exc:
            warnings.append(str(exc))
            continue
        for profile in profiles:
            try:
                profile = inside(profile, run)
                folder = inside(profile / "checkpoints", profile)
                if not folder.is_dir():
                    continue
                files = sorted(folder.iterdir())
            except (OSError, ValueError) as exc:
                warnings.append(str(exc))
                continue
            for path in files:
                match = re.fullmatch(r"clip_(\d{4})(?:\.([0-9a-f]{32}))?\.json", path.name)
                if not match:
                    continue
                try:
                    path = inside(path, profile)
                    metadata = read(path)
                    if metadata.get("format") != "h3_chain_upscale_segment_v1":
                        continue
                    if metadata.get("run_name") != run_name or metadata.get("profile") != profile.name:
                        raise ValueError("Saved processing metadata belongs to another run/profile.")
                    segment = metadata["segment"]
                    scene = int(segment["index"])
                    revision = str(segment["revision"])
                    if (scene != int(match[1]) or not re.fullmatch(r"[0-9a-f]{32}", revision)
                            or (match[2] and match[2] != revision)):
                        raise ValueError("Saved processing scene/revision does not match its file.")
                    canonical = inside(root / segment["revision_metadata"], profile)
                    if canonical != folder / ("clip_%04d.%s.json" % (scene, revision)):
                        raise ValueError("Saved processing revision address is inconsistent.")
                    # Ignore mutable pointer copies; their immutable revision
                    # file is the authority and is scanned separately.
                    if path != canonical:
                        continue
                    identity = str(path.relative_to(root))
                    if identity in seen:
                        continue
                    seen.add(identity)
                    missing, size, outputs = [], 0, {}
                    for field in ("segment", "checkpoint", "generated_audio"):
                        address = segment.get(field)
                        if not address and field == "generated_audio":
                            continue
                        if not isinstance(address, str) or not address:
                            missing.append(field)
                            continue
                        artifact = inside(root / address, profile)
                        if not artifact.is_file():
                            missing.append(field)
                            continue
                        size += artifact.stat().st_size
                        if field != "checkpoint":
                            outputs["video" if field == "segment" else "audio"] = media(artifact)
                    config = metadata.get("profile_config") or {}
                    stage = metadata.get("processing_stage")
                    if stage not in STAGES:
                        stage = processing_stage(config)
                    record = {
                        "key": identity, "metadata_path": identity,
                        "scene": scene, "scene_id": str(segment.get("id") or ""),
                        "revision": revision, "stage": stage, "profile": profile.name,
                        "profile_path": str(profile.relative_to(root)),
                        "source_manifest_hash": str(metadata.get("source_manifest_hash") or ""),
                        "source_revision": str(segment.get("source_revision") or ""),
                        "source_checkpoint_sha256": str(segment.get("source_checkpoint_sha256") or ""),
                        "checkpoint_sha256": str(segment.get("checkpoint_sha256") or ""),
                        "created_at": str(segment.get("created_at") or ""),
                        "width": segment.get("width"), "height": segment.get("height"),
                        "raw_frames": segment.get("raw_frames"),
                        "delivered_frames": segment.get("delivered_frames"),
                        "latent_saved": segment.get("latent_saved") is True,
                        "latent_layout": str(segment.get("latent_layout") or "omitted"),
                        "context_steps": segment.get("context_steps", 0),
                        "audio_route": str(segment.get("audio_route") or "unknown"),
                        "prompt": str(segment.get("prompt") or ""),
                        "ready": not missing, "missing_files": missing, "size_bytes": size,
                        **outputs,
                    }
                    records.append(record)
                except (OSError, ValueError, TypeError, KeyError) as exc:
                    warnings.append("%s: %s" % (path.name, exc))

    # Match the exact source revision AND saved checkpoint identity. A rerun
    # with the same scene number is not the same take. Follow derived sources
    # transitively so a future DeRoPE -> upscale take stays beside its original.
    sources = {}
    for original in originals:
        if original.get("take_kind") == "editorial_alternate":
            continue
        key = (int(original["scene"]), str(original["revision"]),
               str(original.get("checkpoint_sha256") or ""))
        if key[2]:
            sources.setdefault(key, []).append(original)
        alias = str(original.get("adopted_from_revision") or "")
        if alias and key[2]:
            sources.setdefault((key[0], alias, key[2]), []).append(original)
    derived = {}
    for record in records:
        key = (record["scene"], record["revision"], record["checkpoint_sha256"])
        if key[2]:
            derived.setdefault(key, []).append(record)

    def origins(record, visited):
        key = (record["scene"], record["source_revision"], record["source_checkpoint_sha256"])
        if not key[1] or not key[2] or key in visited:
            return []
        if key in sources:
            return sources[key]
        return [origin for parent in derived.get(key, [])
                for origin in origins(parent, visited | {key})]

    for record in records:
        matches = {(int(item["scene"]), str(item["revision"]))
                   for item in origins(record, set())}
        record["originals"] = [{"scene": scene, "revision": revision}
                               for scene, revision in sorted(matches)]
        record["source_status"] = "linked" if matches else "original unavailable or source mismatch"
    records.sort(key=lambda item: (item["scene"], item["created_at"], item["key"]), reverse=True)
    return {"variants": records, "warnings": warnings}
