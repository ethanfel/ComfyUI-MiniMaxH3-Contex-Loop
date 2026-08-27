"""Project-owned media catalog for the H3 Asset Carousel node.

The catalog lives below ComfyUI's input directory so ordinary loader nodes can
open every imported file without this pack.  A second, content-identical copy
is retained below the matching H3 chain output directory for recovery.
"""

from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import re
import shutil
import subprocess
import uuid
from datetime import datetime, timezone
from fractions import Fraction
from typing import Any

try:
    import av
except ImportError:  # ComfyUI normally includes PyAV.
    av = None

try:
    from PIL import Image
except ImportError:  # ComfyUI normally includes Pillow.
    Image = None


PROJECT_ASSET_FORMAT = "h3_project_assets_v1"
PROJECT_ASSET_VERSION = 1
PROJECT_ASSET_ROLES = (
    "picture", "semantic_anchor", "video", "motion",
    "audio_reference", "source_track",
)
IMAGE_EXTENSIONS = frozenset((
    ".avif", ".bmp", ".gif", ".jpeg", ".jpg", ".png", ".tif",
    ".tiff", ".webp",
))
VIDEO_EXTENSIONS = frozenset((
    ".avi", ".m4v", ".mkv", ".mov", ".mp4", ".mpeg", ".mpg",
    ".webm",
))
AUDIO_EXTENSIONS = frozenset((
    ".aac", ".flac", ".m4a", ".mp3", ".oga", ".ogg", ".opus",
    ".wav",
))
ALL_MEDIA_EXTENSIONS = IMAGE_EXTENSIONS | VIDEO_EXTENSIONS | AUDIO_EXTENSIONS
MAX_CATALOG_ASSETS = 512
MAX_REFERENCE_SLOTS = 512
MAX_INPUT_RESULTS = 2000
_TAG_RE = re.compile(r"[A-Za-z][A-Za-z0-9_-]{0,63}")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(
        timespec="seconds").replace("+00:00", "Z")


def _safe_name(value: Any, fallback: str = "asset", limit: int = 128) -> str:
    text = re.sub(r"[^A-Za-z0-9._-]+", "_", str(value or "").strip())
    text = text.strip("._-")
    return (text or fallback)[:limit]


def _safe_project(value: Any) -> str:
    project = _safe_name(value, "", 96)
    if not project:
        raise ValueError("Project name cannot be blank.")
    return project


def _safe_tag(value: Any, fallback: str = "asset") -> str:
    tag = str(value or "").strip().lstrip("@#")
    if not tag:
        tag = _safe_name(fallback, "asset", 64)
        if not tag[:1].isalpha():
            tag = "asset_" + tag
    if _TAG_RE.fullmatch(tag) is None:
        tag = re.sub(r"[^A-Za-z0-9_-]+", "_", tag).strip("_-")[:64]
        if not tag or not tag[0].isalpha():
            tag = "asset_" + (tag or uuid.uuid4().hex[:8])
        tag = tag[:64]
    if _TAG_RE.fullmatch(tag) is None:
        raise ValueError("Asset tag must begin with a letter and contain only letters, numbers, _ or -.")
    return tag


def _inside(root: str, path: str) -> bool:
    try:
        return os.path.commonpath(
            (os.path.realpath(root), os.path.realpath(path))) == os.path.realpath(root)
    except ValueError:
        return False


def _atomic_json(path: str, value: Any) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temporary = "%s.%s.tmp" % (path, uuid.uuid4().hex)
    try:
        with open(temporary, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def _file_sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_fingerprint(value: Any) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _media_kind(path: str) -> str:
    suffix = os.path.splitext(path)[1].lower()
    if suffix in IMAGE_EXTENSIONS:
        return "image"
    if suffix in VIDEO_EXTENSIONS:
        return "video"
    if suffix in AUDIO_EXTENSIONS:
        return "audio"
    raise ValueError("Unsupported media extension %r." % suffix)


def _role_for_kind(kind: str, role: Any) -> str:
    role = str(role or "").strip().lower()
    defaults = {"image": "picture", "video": "video", "audio": "audio_reference"}
    role = role or defaults[kind]
    allowed = {
        "image": {"picture", "semantic_anchor"},
        "video": {"video", "motion", "source_track"},
        "audio": {"audio_reference", "source_track"},
    }
    if role not in allowed[kind]:
        raise ValueError("Role %r is not valid for a %s asset." % (role, kind))
    return role


def _stream_duration(stream: Any, container: Any) -> float:
    if stream.duration is not None and stream.time_base is not None:
        return max(0.0, float(stream.duration * stream.time_base))
    if container.duration is not None:
        return max(0.0, float(container.duration) / 1_000_000.0)
    return 0.0


def _fraction_parts(value: Any, fallback: int = 24) -> tuple[int, int]:
    try:
        rate = Fraction(value)
    except (TypeError, ValueError, ZeroDivisionError):
        rate = Fraction(fallback, 1)
    if rate <= 0:
        rate = Fraction(fallback, 1)
    return int(rate.numerator), int(rate.denominator)


def _probe_media(path: str, kind: str) -> dict[str, Any]:
    if kind == "image":
        if Image is None:
            return {}
        with Image.open(path) as image:
            return {
                "width": int(image.width),
                "height": int(image.height),
                "format": str(image.format or "").lower(),
                "frames": int(getattr(image, "n_frames", 1)),
            }
    if av is None:
        return {}
    with av.open(path, mode="r") as container:
        if kind == "video":
            videos = list(container.streams.video)
            if not videos:
                raise ValueError("Video asset contains no video stream.")
            video = videos[0]
            rate = video.average_rate or video.guessed_rate or video.base_rate
            numerator, denominator = _fraction_parts(rate)
            duration = _stream_duration(video, container)
            frames = int(video.frames or 0)
            if frames <= 0 and duration > 0:
                frames = int(round(duration * numerator / denominator))
            audio_metadata = {}
            audios = list(container.streams.audio)
            if audios:
                audio = audios[0]
                audio_metadata = {
                    "audio_sample_rate": int(
                        audio.codec_context.sample_rate or audio.rate or 0),
                    "audio_channels": len(audio.codec_context.layout.channels),
                    "audio_start_seconds": float(
                        audio.start_time * audio.time_base)
                        if audio.start_time is not None
                        and audio.time_base is not None else 0.0,
                }
            return {
                "width": int(video.codec_context.width or video.width or 0),
                "height": int(video.codec_context.height or video.height or 0),
                "duration_seconds": duration,
                "frame_count": frames,
                "source_rate_numerator": numerator,
                "source_rate_denominator": denominator,
                "fps": numerator / float(denominator),
                "codec": str(video.codec_context.name or ""),
                "video_start_seconds": float(
                    video.start_time * video.time_base)
                    if video.start_time is not None and video.time_base is not None
                    else 0.0,
                "has_audio": bool(audios),
                **audio_metadata,
            }
        audios = list(container.streams.audio)
        if not audios:
            raise ValueError("Audio asset contains no audio stream.")
        audio = audios[0]
        sample_rate = int(audio.codec_context.sample_rate or audio.rate or 0)
        channels = len(audio.codec_context.layout.channels)
        return {
            "duration_seconds": _stream_duration(audio, container),
            "sample_rate": sample_rate,
            "channels": channels,
            "codec": str(audio.codec_context.name or ""),
        }


def _entry_contract(entry: dict[str, Any]) -> dict[str, Any]:
    options = entry.get("options") if isinstance(entry.get("options"), dict) else {}
    return {
        "id": str(entry.get("id") or ""),
        "kind": str(entry.get("kind") or ""),
        "role": str(entry.get("role") or ""),
        "tag": str(entry.get("tag") or ""),
        "sha256": str(entry.get("sha256") or ""),
        "enabled": bool(entry.get("enabled", True)),
        "options": options,
    }


def _slot_contract(slot: dict[str, Any]) -> dict[str, Any]:
    options = slot.get("options") if isinstance(slot.get("options"), dict) else {}
    return {
        "id": str(slot.get("id") or ""),
        "kind": str(slot.get("kind") or ""),
        "role": str(slot.get("role") or ""),
        "tag": str(slot.get("tag") or ""),
        "content_hash": str(slot.get("content_hash") or ""),
        "available": bool(slot.get("available", True)),
        "options": options,
    }


class ProjectAssetStore:
    """Own project media below input/h3_projects and mirror it to a run."""

    def __init__(self, input_root: str, output_root: str):
        self.input_root = os.path.abspath(input_root)
        self.output_root = os.path.abspath(output_root)
        self.projects_root = os.path.join(self.input_root, "h3_projects")
        self.chains_root = os.path.join(self.output_root, "h3_chains")

    def _project_dir(self, project: Any) -> tuple[str, str]:
        name = _safe_project(project)
        path = os.path.realpath(os.path.join(self.projects_root, name))
        if not _inside(self.input_root, path):
            raise ValueError("Project asset path escapes the ComfyUI input directory.")
        return path, name

    def _backup_dir(self, project: Any) -> tuple[str, str]:
        name = _safe_project(project)
        path = os.path.realpath(os.path.join(
            self.chains_root, name, "project_assets"))
        if not _inside(self.output_root, path):
            raise ValueError("Project backup path escapes the ComfyUI output directory.")
        return path, name

    @staticmethod
    def _empty_catalog(project: str) -> dict[str, Any]:
        return {
            "format": PROJECT_ASSET_FORMAT,
            "version": PROJECT_ASSET_VERSION,
            "project": project,
            "updated_at": _utc_now(),
            "revision": "",
            "assets": [],
            "reference_slots": [],
        }

    def load(self, project: Any, *, create: bool = False) -> dict[str, Any]:
        directory, name = self._project_dir(project)
        path = os.path.join(directory, "catalog.json")
        if not os.path.isfile(path):
            catalog = self._empty_catalog(name)
            if create:
                return self._save_catalog(catalog)
            return catalog
        with open(path, "r", encoding="utf-8") as handle:
            catalog = json.load(handle)
        if (not isinstance(catalog, dict)
                or catalog.get("format") != PROJECT_ASSET_FORMAT
                or int(catalog.get("version", -1)) != PROJECT_ASSET_VERSION
                or not isinstance(catalog.get("assets"), list)):
            raise ValueError("Project asset catalog has an unsupported format.")
        catalog["project"] = name
        slots = catalog.get("reference_slots")
        catalog["reference_slots"] = (
            slots if isinstance(slots, list) else [])
        return catalog

    def _save_catalog(self, catalog: dict[str, Any]) -> dict[str, Any]:
        directory, name = self._project_dir(catalog.get("project"))
        assets = [dict(item) for item in catalog.get("assets", [])
                  if isinstance(item, dict)]
        slots = [dict(item) for item in catalog.get("reference_slots", [])
                 if isinstance(item, dict)]
        if len(assets) > MAX_CATALOG_ASSETS:
            raise ValueError("Project asset catalog supports at most %d assets." % MAX_CATALOG_ASSETS)
        if len(slots) > MAX_REFERENCE_SLOTS:
            raise ValueError(
                "Project asset catalog supports at most %d unresolved "
                "reference slots." % MAX_REFERENCE_SLOTS)
        document = {
            "format": PROJECT_ASSET_FORMAT,
            "version": PROJECT_ASSET_VERSION,
            "project": name,
            "updated_at": _utc_now(),
            "assets": assets,
            "reference_slots": slots,
        }
        document["revision"] = _canonical_fingerprint({
            "assets": [_entry_contract(item) for item in assets],
            "reference_slots": [_slot_contract(item) for item in slots],
        })
        for group in ("images", "videos", "audio", "previews", ".uploads"):
            os.makedirs(os.path.join(directory, group), exist_ok=True)
        _atomic_json(os.path.join(directory, "catalog.json"), document)
        backup, _name = self._backup_dir(name)
        os.makedirs(backup, exist_ok=True)
        _atomic_json(os.path.join(backup, "catalog.json"), document)
        return document

    def public_catalog(self, project: Any) -> dict[str, Any]:
        catalog = self.load(project, create=True)
        return {
            **catalog,
            "assets": [dict(item) for item in catalog["assets"]],
            "reference_slots": [
                dict(item) for item in catalog.get("reference_slots", [])],
        }

    def _asset_path(self, project: Any, entry: dict[str, Any]) -> str:
        directory, _name = self._project_dir(project)
        relative = str(entry.get("relative_path") or "")
        path = os.path.realpath(os.path.join(directory, relative))
        if not relative or not _inside(directory, path) or not os.path.isfile(path):
            raise FileNotFoundError("Project asset file is missing: %s" % relative)
        return path

    def asset(self, project: Any, asset_id: Any) -> tuple[dict[str, Any], str]:
        catalog = self.load(project)
        wanted = str(asset_id or "")
        entry = next((item for item in catalog["assets"]
                      if str(item.get("id") or "") == wanted), None)
        if entry is None:
            raise FileNotFoundError("Project asset %s was not found." % wanted)
        return dict(entry), self._asset_path(project, entry)

    def upload_path(self, project: Any, filename: Any) -> str:
        directory, _name = self._project_dir(project)
        os.makedirs(os.path.join(directory, ".uploads"), exist_ok=True)
        basename = _safe_name(os.path.basename(str(filename or "asset")), "asset")
        suffix = os.path.splitext(basename)[1].lower()
        if suffix not in ALL_MEDIA_EXTENSIONS:
            raise ValueError("Unsupported upload extension %r." % suffix)
        return os.path.join(directory, ".uploads", "%s_%s" % (
            uuid.uuid4().hex, basename))

    def sync_reference_slots(
            self, project: Any, templates: Any) -> dict[str, Any]:
        """Mirror reference metadata without copying or serializing media."""
        if not isinstance(templates, list):
            raise ValueError("Reference templates must be a list.")
        catalog = self.load(project, create=True)
        resolved_tags = {
            str(item.get("tag") or "") for item in catalog["assets"]}
        current = {
            str(item.get("tag") or ""): dict(item)
            for item in catalog.get("reference_slots", [])
            if isinstance(item, dict) and str(item.get("tag") or "")
        }
        incoming_tags = set()
        slots = []
        now = _utc_now()
        for raw in templates:
            if not isinstance(raw, dict):
                raise ValueError("Every reference template must be an object.")
            kind = str(raw.get("kind") or "").strip().lower()
            if kind not in ("image", "video", "audio"):
                raise ValueError(
                    "Reference template kind must be image, video, or audio.")
            tag = _safe_tag(raw.get("tag"), "%s_reference" % kind)
            if tag in incoming_tags:
                raise ValueError("Reference template @%s is duplicated." % tag)
            incoming_tags.add(tag)
            if tag in resolved_tags:
                # A project asset with this tag is already the authoritative
                # binding. Synchronization never overwrites it.
                continue
            role = _role_for_kind(kind, raw.get("role"))
            options = raw.get("options")
            options = dict(options) if isinstance(options, dict) else {}
            previous = current.get(tag)
            created_at = str(
                (previous or {}).get("created_at") or now)
            slot = {
                "id": str((previous or {}).get("id") or
                          ("slot_" + uuid.uuid4().hex)),
                "kind": kind,
                "role": role,
                "tag": tag,
                "content_hash": str(raw.get("content_hash") or ""),
                "available": True,
                "source": "tagged_references",
                "created_at": created_at,
                "updated_at": now,
                "options": options,
            }
            slots.append(slot)
        for tag, previous in current.items():
            if tag in incoming_tags or tag in resolved_tags:
                continue
            stale = dict(previous)
            stale["available"] = False
            stale["updated_at"] = now
            slots.append(stale)
        old_contract = [
            _slot_contract(item)
            for item in catalog.get("reference_slots", [])]
        new_contract = [_slot_contract(item) for item in slots]
        if old_contract == new_contract:
            return self.public_catalog(project)
        catalog["reference_slots"] = slots
        return self._save_catalog(catalog)

    def bind_reference_slot(
            self, project: Any, slot_id: Any, source_path: Any, *,
            role: Any = "", tag: Any = "", original_name: Any = "",
            source_kind: str = "path",
            options: dict[str, Any] | None = None) -> dict[str, Any]:
        """Bind explicitly selected media to one unresolved reference slot."""
        catalog = self.load(project)
        wanted = str(slot_id or "")
        slot = next((item for item in catalog.get("reference_slots", [])
                     if str(item.get("id") or "") == wanted), None)
        if slot is None:
            raise FileNotFoundError(
                "Unresolved reference slot %s was not found." % wanted)
        merged_options = dict(slot.get("options") or {})
        if isinstance(options, dict):
            merged_options.update(options)
        result = self.import_file(
            project, source_path,
            role=role or slot.get("role"), tag=tag or slot.get("tag"),
            original_name=original_name, source_kind=source_kind,
            options=merged_options)
        bound_catalog = result["catalog"]
        bound_catalog["reference_slots"] = [
            item for item in bound_catalog.get("reference_slots", [])
            if str(item.get("id") or "") != wanted]
        result["catalog"] = self._save_catalog(bound_catalog)
        result["bound_slot_id"] = wanted
        return result

    def import_file(self, project: Any, source_path: Any, *, role: Any = "",
                    tag: Any = "", original_name: Any = "",
                    source_kind: str = "path",
                    options: dict[str, Any] | None = None) -> dict[str, Any]:
        source = os.path.realpath(os.path.abspath(os.path.expanduser(
            str(source_path or "").strip())))
        if not source or not os.path.isfile(source):
            raise FileNotFoundError("Asset source does not exist: %s" % source)
        kind = _media_kind(source)
        role = _role_for_kind(kind, role)
        basename = os.path.basename(str(original_name or source))
        stem = os.path.splitext(basename)[0]
        tag = _safe_tag(tag, stem)
        digest = _file_sha256(source)
        size = int(os.path.getsize(source))
        directory, name = self._project_dir(project)
        catalog = self.load(name, create=True)
        if role == "source_track" and any(
                item.get("role") == "source_track"
                and bool(item.get("enabled", True))
                for item in catalog["assets"]):
            raise ValueError(
                "This project already has an enabled Source track. Disable "
                "or reassign it before importing another one.")
        group = {"image": "images", "video": "videos", "audio": "audio"}[kind]
        suffix = os.path.splitext(source)[1].lower()
        filename = "%s_%s%s" % (
            digest[:16], _safe_name(stem, kind, 80), suffix)
        destination = os.path.join(directory, group, filename)
        os.makedirs(os.path.dirname(destination), exist_ok=True)
        if not os.path.isfile(destination) or _file_sha256(destination) != digest:
            temporary = "%s.%s.tmp" % (destination, uuid.uuid4().hex)
            try:
                shutil.copy2(source, temporary)
                if _file_sha256(temporary) != digest:
                    raise ValueError("Imported asset failed its SHA-256 check.")
                os.replace(temporary, destination)
            finally:
                try:
                    os.unlink(temporary)
                except FileNotFoundError:
                    pass
        metadata = _probe_media(destination, kind)
        used_tags = {
            str(item.get("tag") or "") for item in catalog["assets"]
            if bool(item.get("enabled", True))
        }
        if tag in used_tags:
            base = tag
            ordinal = 2
            while tag in used_tags:
                suffix_text = "_%d" % ordinal
                tag = base[:64 - len(suffix_text)] + suffix_text
                ordinal += 1
        now = _utc_now()
        entry = {
            "id": uuid.uuid4().hex,
            "kind": kind,
            "role": role,
            "tag": tag,
            "enabled": True,
            "relative_path": os.path.relpath(destination, directory).replace(os.sep, "/"),
            "input_path": os.path.relpath(destination, self.input_root).replace(os.sep, "/"),
            "sha256": digest,
            "size": size,
            "mime_type": mimetypes.guess_type(destination)[0] or "application/octet-stream",
            "original_name": basename,
            "source_kind": str(source_kind or "path")[:40],
            "created_at": now,
            "updated_at": now,
            "metadata": metadata,
            "options": dict(options or {}),
        }
        catalog["assets"].append(entry)
        catalog = self._save_catalog(catalog)
        backup, _name = self._backup_dir(name)
        backup_path = os.path.join(backup, group, filename)
        os.makedirs(os.path.dirname(backup_path), exist_ok=True)
        if not os.path.isfile(backup_path) or _file_sha256(backup_path) != digest:
            temporary = "%s.%s.tmp" % (backup_path, uuid.uuid4().hex)
            try:
                shutil.copy2(destination, temporary)
                os.replace(temporary, backup_path)
            finally:
                try:
                    os.unlink(temporary)
                except FileNotFoundError:
                    pass
        return {"catalog": catalog, "asset": entry}

    def update(self, project: Any, asset_id: Any, changes: Any) -> dict[str, Any]:
        if not isinstance(changes, dict):
            raise ValueError("Asset changes must be a JSON object.")
        catalog = self.load(project)
        wanted = str(asset_id or "")
        entry = next((item for item in catalog["assets"]
                      if str(item.get("id") or "") == wanted), None)
        if entry is None:
            raise FileNotFoundError("Project asset %s was not found." % wanted)
        kind = str(entry["kind"])
        if "role" in changes:
            entry["role"] = _role_for_kind(kind, changes["role"])
        if "tag" in changes:
            tag = _safe_tag(changes["tag"], entry.get("tag") or "asset")
            if any(str(item.get("tag") or "") == tag
                   and str(item.get("id") or "") != wanted
                   and bool(item.get("enabled", True))
                   for item in catalog["assets"]):
                raise ValueError("Another enabled project asset already uses @%s." % tag)
            entry["tag"] = tag
        if "enabled" in changes:
            entry["enabled"] = bool(changes["enabled"])
        if "options" in changes:
            if not isinstance(changes["options"], dict):
                raise ValueError("Asset options must be a JSON object.")
            options = dict(entry.get("options") or {})
            options.update(changes["options"])
            entry["options"] = options
        if bool(entry.get("enabled", True)):
            if any(str(item.get("tag") or "") == str(entry.get("tag") or "")
                   and str(item.get("id") or "") != wanted
                   and bool(item.get("enabled", True))
                   for item in catalog["assets"]):
                raise ValueError(
                    "Another enabled project asset already uses @%s." %
                    entry.get("tag"))
            if (entry.get("role") == "source_track" and any(
                    item.get("role") == "source_track"
                    and str(item.get("id") or "") != wanted
                    and bool(item.get("enabled", True))
                    for item in catalog["assets"])):
                raise ValueError(
                    "This project already has an enabled Source track.")
        entry["updated_at"] = _utc_now()
        catalog = self._save_catalog(catalog)
        return {"catalog": catalog, "asset": dict(entry)}

    def input_media(self, query: Any = "") -> list[dict[str, Any]]:
        needle = str(query or "").strip().lower()
        result = []
        if not os.path.isdir(self.input_root):
            return result
        for root, directories, files in os.walk(self.input_root):
            directories[:] = [name for name in directories
                               if not (root == self.input_root and name == "h3_projects")]
            for filename in files:
                suffix = os.path.splitext(filename)[1].lower()
                if suffix not in ALL_MEDIA_EXTENSIONS:
                    continue
                path = os.path.join(root, filename)
                relative = os.path.relpath(path, self.input_root).replace(os.sep, "/")
                if needle and needle not in relative.lower():
                    continue
                try:
                    stat = os.stat(path)
                except OSError:
                    continue
                result.append({
                    "path": relative,
                    "kind": _media_kind(path),
                    "size": int(stat.st_size),
                    "modified": float(stat.st_mtime),
                })
                if len(result) >= MAX_INPUT_RESULTS:
                    break
            if len(result) >= MAX_INPUT_RESULTS:
                break
        return sorted(result, key=lambda item: item["path"].lower())

    def input_path(self, relative: Any) -> str:
        value = str(relative or "").strip()
        path = os.path.realpath(os.path.join(self.input_root, value))
        if not value or not _inside(self.input_root, path) or not os.path.isfile(path):
            raise FileNotFoundError("ComfyUI input asset was not found: %s" % value)
        return path

    def backups(self) -> list[dict[str, Any]]:
        result = []
        if not os.path.isdir(self.chains_root):
            return result
        with os.scandir(self.chains_root) as runs:
            for run in runs:
                if not run.is_dir(follow_symlinks=False):
                    continue
                path = os.path.join(run.path, "project_assets", "catalog.json")
                if not os.path.isfile(path):
                    continue
                try:
                    with open(path, "r", encoding="utf-8") as handle:
                        catalog = json.load(handle)
                    assets = catalog.get("assets") if isinstance(catalog, dict) else None
                    if not isinstance(assets, list):
                        continue
                    result.append({
                        "run_name": run.name,
                        "revision": str(catalog.get("revision") or ""),
                        "assets": [dict(item) for item in assets if isinstance(item, dict)],
                    })
                except (OSError, ValueError, json.JSONDecodeError):
                    continue
        return sorted(result, key=lambda item: item["run_name"].lower())

    def backup_asset_path(self, run_name: Any, asset_id: Any) -> tuple[dict[str, Any], str]:
        backup, name = self._backup_dir(run_name)
        path = os.path.join(backup, "catalog.json")
        if not os.path.isfile(path):
            raise FileNotFoundError("H3 chain %s has no project asset backup." % name)
        with open(path, "r", encoding="utf-8") as handle:
            catalog = json.load(handle)
        entry = next((item for item in catalog.get("assets", [])
                      if str(item.get("id") or "") == str(asset_id or "")), None)
        if entry is None:
            raise FileNotFoundError("Backup asset %s was not found." % asset_id)
        relative = str(entry.get("relative_path") or "")
        source = os.path.realpath(os.path.join(backup, relative))
        if not _inside(backup, source) or not os.path.isfile(source):
            raise FileNotFoundError("Backup media is missing: %s" % relative)
        return dict(entry), source

    def _preview_path(self, project: Any, entry: dict[str, Any], suffix: str) -> str:
        directory, _name = self._project_dir(project)
        return os.path.join(directory, "previews", "%s_%s%s" % (
            entry["id"], str(entry.get("sha256") or "")[:12], suffix))

    def ensure_poster(self, project: Any, asset_id: Any) -> str:
        entry, source = self.asset(project, asset_id)
        if entry["kind"] == "audio":
            raise ValueError("Audio assets do not have poster frames.")
        target = self._preview_path(project, entry, ".jpg")
        os.makedirs(os.path.dirname(target), exist_ok=True)
        if os.path.isfile(target) and os.path.getsize(target) > 0:
            return target
        temporary = "%s.%s.tmp.jpg" % (target, uuid.uuid4().hex)
        try:
            if entry["kind"] == "image" and Image is not None:
                with Image.open(source) as image:
                    frame = image.convert("RGB")
                    frame.thumbnail((960, 540))
                    frame.save(temporary, format="JPEG", quality=86, optimize=True)
            else:
                ffmpeg = shutil.which("ffmpeg")
                if ffmpeg:
                    command = [
                        ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
                        "-ss", "0", "-i", source, "-frames:v", "1",
                        "-vf", "scale='min(960,iw)':-2", "-q:v", "3", temporary,
                    ]
                    completed = subprocess.run(
                        command, stdout=subprocess.DEVNULL,
                        stderr=subprocess.PIPE, timeout=60, check=False)
                    if completed.returncode:
                        raise RuntimeError(completed.stderr.decode(
                            "utf-8", errors="replace")[-1200:])
                elif av is not None and Image is not None:
                    with av.open(source, mode="r") as container:
                        video = next(iter(container.streams.video), None)
                        frame = next(container.decode(video), None) if video else None
                        if frame is None:
                            raise ValueError("Video contains no decodable frame.")
                        image = frame.to_image().convert("RGB")
                        image.thumbnail((960, 540))
                        image.save(temporary, format="JPEG", quality=86)
                else:
                    raise RuntimeError("Video poster generation requires ffmpeg or PyAV/Pillow.")
            if not os.path.isfile(temporary) or os.path.getsize(temporary) <= 0:
                raise RuntimeError("Preview generator produced an empty poster.")
            os.replace(temporary, target)
        finally:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
        return target

    @staticmethod
    def _browser_video(entry: dict[str, Any], path: str) -> bool:
        suffix = os.path.splitext(path)[1].lower()
        codec = str((entry.get("metadata") or {}).get("codec") or "").lower()
        return ((suffix in (".mp4", ".m4v", ".mov") and codec in (
            "h264", "av1", "hevc")) or
            (suffix == ".webm" and codec in ("vp8", "vp9", "av1")))

    def ensure_browser_media(self, project: Any, asset_id: Any) -> str:
        entry, source = self.asset(project, asset_id)
        if entry["kind"] != "video" or self._browser_video(entry, source):
            return source
        target = self._preview_path(project, entry, ".mp4")
        os.makedirs(os.path.dirname(target), exist_ok=True)
        if os.path.isfile(target) and os.path.getsize(target) > 0:
            return target
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            return source
        temporary = "%s.%s.tmp.mp4" % (target, uuid.uuid4().hex)
        try:
            command = [
                ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
                "-i", source, "-vf", "scale='min(1280,iw)':-2",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "25",
                "-pix_fmt", "yuv420p", "-movflags", "+faststart",
                "-c:a", "aac", "-b:a", "128k", temporary,
            ]
            completed = subprocess.run(
                command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                timeout=max(120, int(float((entry.get("metadata") or {}).get(
                    "duration_seconds") or 0) * 8)), check=False)
            if completed.returncode:
                raise RuntimeError(completed.stderr.decode(
                    "utf-8", errors="replace")[-1600:])
            if not os.path.isfile(temporary) or os.path.getsize(temporary) <= 0:
                raise RuntimeError("Preview proxy generator produced an empty video.")
            os.replace(temporary, target)
        finally:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
        return target
