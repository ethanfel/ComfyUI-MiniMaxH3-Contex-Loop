"""Chapter-local geometry; no media mutation or implicit latent resizing."""


def normalize_resolution(value, label="Chapter resolution"):
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) != {"width", "height"}:
        raise ValueError(f"{label} must contain width and height, or be null to inherit.")
    result = {}
    for key in ("width", "height"):
        number = value[key]
        if (isinstance(number, bool) or not isinstance(number, int)
                or number < 32 or number > 16384 or number % 32):
            raise ValueError(f"{label} {key} must be a multiple of 32 between 32 and 16384.")
        result[key] = number
    return result


def scene_resolution(plan, index):
    shot = plan["shots"][int(index) - 1]
    return dict(shot.get("resolution") or {
        key: int(plan["compatibility"][key]) for key in ("width", "height")
    })


def saved_resolution(segment, metadata=None):
    """Prefer the immutable scene's recorded geometry, including legacy saves."""
    metadata = metadata or {}
    dependency = segment.get("scene_dependency") or metadata.get("scene_dependency") or {}
    candidates = (
        segment.get("resolution"),
        dependency.get("scopes", {}).get("global_generation"),
        metadata.get("compatibility"),
    )
    for candidate in candidates:
        if isinstance(candidate, dict) and all(key in candidate for key in ("width", "height")):
            return normalize_resolution(
                {key: candidate[key] for key in ("width", "height")},
                "Saved scene resolution")
    return None


def apply_chapter_resolutions(plan, chapters, locked_resolutions):
    """Resolve one size per chapter, pinning inherited chapters to saved locks.

    Only chapter-sized geometry is authored. Locking a saved scene prevents a
    Plan-default edit from changing the interpretation of its whole chapter.
    Explicit conflicting chapter edits fail; locks never waive integrity checks.
    """
    starts = sorted(chapters, key=lambda row: int(row["start_scene"]))
    if not starts or int(starts[0]["start_scene"]) > 1:
        implicit = {"start_scene": 1, "title": "Unassigned",
                    "start_scene_id": plan["shots"][0]["id"], "text": ""}
        identifier = "unassigned"
        while any(row["id"] == identifier for row in chapters):
            identifier += "_"
        implicit["id"] = identifier
        starts.insert(0, implicit)
    for offset, chapter in enumerate(starts):
        start = int(chapter["start_scene"])
        end = int(starts[offset + 1]["start_scene"]) - 1 if offset + 1 < len(starts) else len(plan["shots"])
        shots = plan["shots"][start - 1:end]
        explicit = normalize_resolution(chapter.get("resolution"))
        locked = [locked_resolutions[shot["id"]] for shot in shots
                  if shot["id"] in locked_resolutions]
        sizes = {(row["width"], row["height"]) for row in locked}
        if len(sizes) > 1:
            raise ValueError(f"{chapter['title']} has locked saved scenes at different resolutions. "
                             "Place the resolution boundary between chapters before continuing.")
        pinned = locked[0] if locked else None
        if pinned and explicit and explicit != pinned:
            raise ValueError(f"{chapter['title']} is pinned by locked saved scenes to "
                             f"{pinned['width']}x{pinned['height']}. Unlock those scenes "
                             "before changing this chapter's resolution; saved files are unchanged.")
        resolution = pinned or explicit
        if resolution:
            if pinned:
                chapter["resolution"] = dict(pinned)
                if chapter not in chapters:
                    # Recovery must retain a pin before the first authored marker.
                    chapters.insert(0, chapter)
            for shot in shots:
                shot["resolution"] = dict(resolution)


def common_saved_resolution(segments, label="Video assembly"):
    sizes = {tuple(value[key] for key in ("width", "height"))
             for segment in segments
             if (value := saved_resolution(segment)) is not None}
    if len(sizes) > 1:
        raise ValueError(f"{label} contains different chapter resolutions. Export each chapter "
                         "separately, then resize to a common output size before joining. "
                         "Saved scenes and exports are unchanged.")
    if sizes:
        width, height = next(iter(sizes))
        return {"width": width, "height": height}
    return None
