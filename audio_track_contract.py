"""JSON-only contracts for grouped project audio; no media or runtime imports."""

AUDIO_TRACK_ROLES = ("full_mix", "vocals", "instrumental")


def audio_track_bindings(value, assets):
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) - set(AUDIO_TRACK_ROLES):
        raise ValueError("Audio tracks must map full_mix, vocals, and instrumental to asset IDs.")
    known = {str(asset.get("id") or ""): asset for asset in assets}
    result = {}
    for role in AUDIO_TRACK_ROLES:
        raw = value.get(role, "")
        if raw is not None and not isinstance(raw, str):
            raise ValueError("Audio track IDs must be strings.")
        asset_id = str(raw or "").strip()
        if asset_id and (asset_id not in known or known[asset_id].get("kind") != "audio"):
            raise ValueError("Audio track %s must reference an existing audio asset in this project." % role)
        result[role] = asset_id
    selected = [asset_id for asset_id in result.values() if asset_id]
    if not selected:
        raise ValueError("Select at least one audio track, or reset to the original single track.")
    if len(selected) != len(set(selected)):
        raise ValueError("The same audio asset cannot be both a mix and a stem, or both stems.")
    return result
