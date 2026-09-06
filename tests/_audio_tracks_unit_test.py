#!/usr/bin/env python3
"""Grouped source audio: routing, mixing, recovery, previews and catalog links."""

import json
import pathlib
import tempfile
import types

import torch

from _project_asset_manager_unit_test import ACTIVE, chain, folder_paths


def audio(value, seconds=8, rate=24000, channels=1):
    return {"waveform": torch.full((1, channels, int(seconds * rate)), value),
            "sample_rate": rate}


def timeline(value):
    return chain._make_source_timeline(source_audio=value)


def rejects(message, operation):
    try:
        operation()
    except ValueError as exc:
        assert message in str(exc), str(exc)
    else:
        raise AssertionError("Expected rejection: " + message)


def plan(name="tracks", off=False):
    policy = chain._contract_compose_chain_policy(
        chain._contract_audio_policy("source", "off", "off", "locked",
                                     chain._contract_masked_song_options()),
        chain._contract_transition_policy("cut"), audio_context_length=0)
    second = {"id": "second", "prompt": "Action.", "length": 73}
    if off:
        second.update(source_audio_target="off", source_reference="off",
                      generated_continuity="off")
    return chain._normalize_plan(json.dumps({"shots": [
        {"id": "first", "prompt": "Singing.", "length": 73}, second]}),
        name, 64, 64, 1, "video", "head", "disabled", "generated_audio", 0,
        1.0, 8, 7, 18, "model-stack", 0, "guide", policy)


with tempfile.TemporaryDirectory() as temporary:
    ACTIVE["root"] = temporary
    root = pathlib.Path(temporary)
    chain.PromptHistoryStore = lambda _root: types.SimpleNamespace(
        mark_executed=lambda *_args, **_kwargs: None)
    full = timeline(audio(0.3, channels=2))
    vocal_audio = audio(0.1)
    vocal_audio["waveform"][..., 24000:48000] = 0  # Preserve instrumental gap.
    vocals = timeline(vocal_audio)
    backing = timeline(audio(0.2, rate=48000, channels=2))
    grouped = chain._make_audio_tracks(full, vocals, backing)
    assert chain._make_audio_tracks(full) is full
    assert grouped["fingerprints"]["audio"] == full["fingerprints"]["audio"]
    assert grouped["fingerprints"]["timeline"] != full["fingerprints"]["timeline"]
    assert torch.equal(chain._source_timeline_source_audio(grouped)["waveform"],
                       full["audio"]["value"]["waveform"])
    assert chain._source_timeline_generation_track(grouped, lip_sync=True) is vocals
    assert chain._source_timeline_generation_track(grouped) is grouped
    assert chain._source_timeline_generation_track(full, lip_sync=True) is full

    mixed = chain._make_audio_tracks(vocals=vocals, instrumental=backing)
    waveform = chain._source_timeline_source_audio(mixed)["waveform"]
    assert waveform.shape == (1, 2, 8 * 48000)
    assert torch.allclose(waveform[..., :48000 - 1], torch.full_like(
        waveform[..., :48000 - 1], 0.3))
    assert torch.allclose(waveform[..., 48001:96000 - 1], torch.full_like(
        waveform[..., 48001:96000 - 1], 0.2))
    assert mixed["audio_tracks"]["mix_gain"] == 1
    loud = chain._make_audio_tracks(vocals=timeline(audio(0.8)),
                                   instrumental=timeline(audio(0.7)))
    assert abs(loud["audio_tracks"]["mix_gain"] - 2 / 3) < 1e-6
    assert float(chain._source_timeline_source_audio(loud)["waveform"].max()) <= 1
    rejects("same duration", lambda: chain._make_audio_tracks(
        full, timeline(audio(0.1, seconds=1))))
    rejects("needs a full mix", lambda: chain._make_audio_tracks())
    rejects("non-finite", lambda: chain._make_audio_tracks(vocals=timeline(audio(float("nan")))))
    no_voice = chain._make_audio_tracks(full_mix=full, instrumental=backing)
    rejects("no vocal track", lambda: chain._plan_with_source_timeline(plan(), no_voice))
    assert not (root / "output" / "h3_chains").exists(), "Validation must precede run writes"
    report = {"errors": [], "warnings": []}
    chain._preflight_bind_source(plan(), report, no_voice)
    assert any(item["code"] == "source_vocals_missing" for item in report["errors"])
    all_off = plan("instrumental", off=True)
    all_off["shots"][0].update(source_audio_target="off", source_reference="off",
                               generated_continuity="off")
    _, no_voice_source = chain._plan_with_source_timeline(all_off, no_voice)
    assert chain._source_timeline_source_audio(no_voice_source) is not None
    rejects("too short", lambda: chain._plan_with_source_timeline(plan(),
        chain._make_audio_tracks(timeline(audio(0., seconds=1)),
                                 timeline(audio(0., seconds=1)))))

    # Auto-mix and tensor-input groups have a seekable final-soundtrack preview.
    for source in (mixed, grouped):
        media = chain._plan_studio_source_audio_media(plan(), source)
        assert pathlib.Path(media["audio_path"]).is_file()
        preview = chain._make_source_timeline(audio_path=media["audio_path"])
        assert torch.equal(chain._source_timeline_source_audio(preview)["waveform"],
                           chain._source_timeline_source_audio(source)["waveform"])

    prepared, runtime = chain._plan_with_source_timeline(plan(), grouped)
    json.dumps(prepared)  # No full-song tensors in saved Plan/recovery records.
    assert runtime["audio"]["kind"] == "external_path"
    assert runtime["audio_tracks"]["vocals"]["audio"]["kind"] == "external_path"
    recovered = chain._source_timeline_from_recovery(prepared["source_timeline"])
    assert recovered["fingerprints"] == grouped["fingerprints"]
    # Includes pre-roll/lookahead around resized scenes; the driver is vocals.
    result = chain.MiniMaxH3ChainCurrent().current({
        "plan": prepared, "index": 2, "source_timeline": runtime})["result"][0]
    dep = result["current_source_reference_dependency"]
    assert (dep["start_frame"], dep["end_frame"]) == (49, 151)
    assert dep["audio_track"] == "vocals"
    target = result["current_source_audio_target"]
    expected = chain._source_timeline_scene_audio(vocals, 49, 151)
    assert torch.equal(target["waveform"], expected["waveform"])
    assert result["current_source_audio_target_clip_start_seconds"] == 1.0
    changed = chain._make_audio_tracks(full, timeline(audio(0.4)), backing)
    changed_plan, changed_runtime = chain._plan_with_source_timeline(plan(), changed)
    changed_state = chain.MiniMaxH3ChainCurrent().current({
        "plan": changed_plan, "index": 2, "source_timeline": changed_runtime})["result"][0]
    assert changed_state["current_source_reference_dependency"] != dep
    off_plan, off_source = chain._plan_with_source_timeline(plan(off=True), grouped)
    off_state = chain.MiniMaxH3ChainCurrent().current({
        "plan": off_plan, "index": 2, "source_timeline": off_source,
        "current_source_audio_target": target})["result"][0]
    assert "current_source_audio_target" not in off_state
    assert not chain._audio_policy_uses_source_reference(off_plan, off_plan["shots"][1])
    assert not chain._audio_policy_uses_generated_continuity(off_plan, off_plan["shots"][1])
    assert chain._audio_policy_final(off_plan) == "source"
    assert torch.equal(chain._source_timeline_source_audio(off_source)["waveform"],
                       full["audio"]["value"]["waveform"])

    # Recovery/relink verifies every stem, not just the final soundtrack.
    archived = chain._archive_source_timeline_media(runtime, plan("archive"),
                                                   archive_audio=True, archive_video=False)
    record = chain._source_timeline_recovery_record(archived)
    for track in (runtime, runtime["audio_tracks"]["vocals"],
                  runtime["audio_tracks"]["instrumental"]):
        pathlib.Path(track["audio"]["path"]).unlink()
    restored = chain._source_timeline_from_recovery(record)
    assert torch.equal(chain._source_timeline_source_audio(restored)["waveform"],
                       full["audio"]["value"]["waveform"])
    wrong = root / "wrong.wav"
    chain._atomic_float_wav(audio(0.5), str(wrong))
    rejects("match", lambda: chain._source_timeline_from_recovery(
        record, track_paths={"vocals": str(wrong)}))

    # Carousel selectors work with disabled prompt references, duplicates and
    # cross-project copies; references never point back into the original Run.
    store = chain.ProjectAssetStore(folder_paths.get_input_directory(),
                                   folder_paths.get_output_directory())
    ids = {}
    for role, value in (("full_mix", audio(0.3)), ("vocals", vocal_audio),
                        ("instrumental", audio(0.2))):
        path = root / (role + ".wav")
        chain._atomic_float_wav(value, str(path))
        item = store.import_file("catalog", path,
            role="source_track" if role == "full_mix" else "audio_reference")
        ids[role] = item["asset"]["id"]
        if role != "full_mix":
            store.update("catalog", ids[role], {"enabled": False})
    store.update("catalog", ids["full_mix"], {"options": {"audio_tracks": ids}})
    built = chain.MiniMaxH3ProjectAssetManager().build("catalog")[3]
    assert built["audio_tracks"]["mix_mode"] == "full_mix"
    store.update("catalog", ids["full_mix"], {"options": {"audio_tracks": {
        **ids, "full_mix": ""}}})
    auto = chain.MiniMaxH3ProjectAssetManager().build("catalog")[3]
    assert auto["audio_tracks"]["mix_mode"] == "stems"
    # Carousel -> Plan serializes the source; no extra direct wire is needed.
    auto_recovered = chain._source_timeline_from_recovery(
        chain._source_timeline_recovery_record(auto))
    chain._validate_source_timeline(auto_recovered, require_runtime=True)
    assert chain._plan_studio_source_audio_media(plan(), auto_recovered)
    store.update("catalog", ids["full_mix"], {"options": {"audio_tracks": ids}})
    rejects("existing audio asset", lambda: store.update("catalog", ids["full_mix"],
        {"options": {"audio_tracks": {"vocals": "missing"}}}))
    rejects("Detach", lambda: store.delete("catalog", ids["vocals"]))
    clone = store.duplicate("catalog", ids["full_mix"])["asset"]
    assert clone["options"]["audio_tracks"]["full_mix"] == clone["id"]
    copied = store.import_project_asset("copied", "catalog", ids["full_mix"])
    copied_ids = copied["asset"]["options"]["audio_tracks"]
    assert not set(copied_ids.values()) & set(ids.values())
    assert len(copied["catalog"]["assets"]) == 3
    assert chain.MiniMaxH3ProjectAssetManager().build("copied")[3]["audio_tracks"]
    duplicated = store.duplicate_project("catalog", "duplicated")
    assert chain.MiniMaxH3ProjectAssetManager().build("duplicated")[3]["audio_tracks"]
    store.update("catalog", ids["full_mix"], {"options": {"audio_tracks": None}})
    store.update("catalog", clone["id"], {"options": {"audio_tracks": None}})
    assert "audio_tracks" not in chain.MiniMaxH3ProjectAssetManager().build("catalog")[3]
    store.delete("catalog", ids["vocals"])

    assert chain.CHAIN_NODE_CLASS_MAPPINGS["MiniMaxH3AudioTracks"] is chain.MiniMaxH3AudioTracks
    node_source, status = chain.MiniMaxH3AudioTracks().build(
        full_mix=audio(0.3), vocals=vocal_audio)
    assert "lip-sync=vocals" in status
    assert node_source["audio_tracks"]["mix_mode"] == "full_mix"

print("Audio tracks: exact final mix, stem mixing, vocal-only driver, per-scene Off, "
      "preflight, preview, recovery and cross-project lifecycle pass")
