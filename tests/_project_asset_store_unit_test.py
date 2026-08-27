#!/usr/bin/env python3
"""Project Asset Carousel storage, backup, and catalog checks."""

import pathlib
import tempfile
import wave

from PIL import Image

from project_assets import PROJECT_ASSET_FORMAT, ProjectAssetStore


def main():
    with tempfile.TemporaryDirectory() as temporary:
        root = pathlib.Path(temporary)
        input_root = root / "input"
        output_root = root / "output"
        loose = input_root / "loose"
        loose.mkdir(parents=True)
        picture = loose / "Hero Face.png"
        Image.new("RGB", (64, 48), (120, 80, 40)).save(picture)
        audio = loose / "voice.wav"
        with wave.open(str(audio), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(24000)
            handle.writeframes(b"\x00\x00" * 2400)

        store = ProjectAssetStore(str(input_root), str(output_root))
        first = store.import_file(
            "episode_1", picture, role="picture", tag="hero")
        second = store.import_file(
            "episode_1", audio, role="source_track", tag="music")
        assert first["catalog"]["format"] == PROJECT_ASSET_FORMAT
        assert len(second["catalog"]["assets"]) == 2
        assert pathlib.Path(store.asset(
            "episode_1", first["asset"]["id"])[1]).is_file()
        assert (output_root / "h3_chains" / "episode_1" /
                "project_assets" / "catalog.json").is_file()
        assert (output_root / "h3_chains" / "episode_1" /
                "project_assets" / first["asset"]["relative_path"]).is_file()
        listed = store.input_media()
        assert {item["path"] for item in listed} == {
            "loose/Hero Face.png", "loose/voice.wav"}
        assert all(not item["path"].startswith("h3_projects/")
                   for item in listed)

        changed = store.update(
            "episode_1", first["asset"]["id"],
            {"role": "semantic_anchor", "tag": "hero_semantic"})
        assert changed["asset"]["role"] == "semantic_anchor"
        assert changed["asset"]["tag"] == "hero_semantic"
        assert changed["catalog"]["revision"] != first["catalog"]["revision"]

        templated = store.sync_reference_slots("episode_migration", [{
            "kind": "image",
            "role": "picture",
            "tag": "legacy_hero",
            "content_hash": "abc123",
            "options": {},
        }])
        assert templated["assets"] == []
        assert len(templated["reference_slots"]) == 1
        slot = templated["reference_slots"][0]
        assert slot["tag"] == "legacy_hero"
        assert slot["available"] is True
        assert list((input_root / "h3_projects" / "episode_migration" /
                     "images").glob("*.png")) == []
        stale = store.sync_reference_slots("episode_migration", [])
        assert stale["reference_slots"][0]["available"] is False
        refreshed = store.sync_reference_slots("episode_migration", [{
            "kind": "image", "role": "picture", "tag": "legacy_hero",
            "content_hash": "abc123", "options": {},
        }])
        bound = store.bind_reference_slot(
            "episode_migration", refreshed["reference_slots"][0]["id"],
            picture, source_kind="input")
        assert bound["asset"]["tag"] == "legacy_hero"
        assert bound["catalog"]["reference_slots"] == []
        assert len(bound["catalog"]["assets"]) == 1

    print("H3 Project Asset Store: import, backup, metadata sync, binding, listing, and edit pass")


if __name__ == "__main__":
    main()
