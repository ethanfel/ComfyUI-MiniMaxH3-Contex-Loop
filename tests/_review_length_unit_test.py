#!/usr/bin/env python3
"""Review retry duration updates the complete prepared Plan timeline."""

import asyncio
import importlib.util
import json
import pathlib
import sys
import tempfile
import types
from contextlib import nullcontext

import torch


ROOT = pathlib.Path(__file__).resolve().parents[1]
PACKAGE = "h3_review_length_unit"

folder_paths = types.ModuleType("folder_paths")
folder_paths.get_output_directory = lambda: str(ROOT)
folder_paths.get_temp_directory = lambda: str(ROOT)
folder_paths.get_input_directory = lambda: str(ROOT)
folder_paths.get_annotated_filepath = lambda value: str(value)
sys.modules["folder_paths"] = folder_paths

server = types.ModuleType("server")
server.PromptServer = type("PromptServer", (), {"instance": None})
sys.modules["server"] = server

package = types.ModuleType(PACKAGE)
package.__path__ = [str(ROOT)]
sys.modules[PACKAGE] = package

shared_nodes = types.ModuleType(PACKAGE + ".nodes")
shared_nodes.MiniMaxH3MotionContext = object
shared_nodes._claim_inline_patch_ownership = lambda _conditioning=None: "test patch owner"
shared_nodes._prepare_native_guide_conditioning = lambda *args: None
shared_nodes._resize = lambda *args: None
shared_nodes._streams_from_latent = lambda *args: None
sys.modules[shared_nodes.__name__] = shared_nodes

spec = importlib.util.spec_from_file_location(
    PACKAGE + ".chain_nodes", ROOT / "chain_nodes.py")
chain = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = chain
spec.loader.exec_module(chain)


def shot(index, raw_frames, delivered_frames, start):
    prompt = "Scene %d." % index
    return {
        "index": index,
        "id": "scene_%d" % index,
        "scene_prompt": prompt,
        "prompt": prompt,
        "prompt_hash": "prompt-%d" % index,
        "seed": index,
        "steps": 20,
        "raw_frames": raw_frames,
        "delivered_frames": delivered_frames,
        "generation_start_frame": start,
        "audio_start_seconds": start / 24,
        "audio_duration_seconds": raw_frames / 24,
    }


plan = {
    "version": 1,
    "run_name": "review_length",
    "prompt_prefix": "",
    "shots": [shot(1, 39, 39, 0), shot(2, 56, 34, 17),
              shot(3, 39, 17, 51)],
    "compatibility": {
        "fps": 24,
        "width": 960,
        "height": 544,
        "context_length": 22,
        "anchor_mode": "head",
        "audio_mode": "generated_audio",
        "source_audio_hash": "none",
    },
    "total_delivered_frames": 90,
    "plan_hash": "prepared-hash",
    "base_plan_hash": "base-hash",
}

revised = chain._plan_with_review_revision(
    plan, 2, "Longer second scene.", 999, 73)

assert revised["shots"][0]["raw_frames"] == 39
assert revised["shots"][1]["raw_frames"] == 73
assert revised["shots"][1]["delivered_frames"] == 51
assert revised["shots"][1]["generation_start_frame"] == 17
assert revised["shots"][2]["generation_start_frame"] == 68
assert revised["shots"][2]["audio_start_seconds"] == 68 / 24
assert revised["total_delivered_frames"] == 107
assert revised["review_overrides"]["2"]["raw_frames"] == 73
assert revised["base_plan_hash"] == plan["base_plan_hash"]
assert chain._history_hash(revised, 1) == chain._history_hash(plan, 1)
assert chain._history_hash(revised, 2) != chain._history_hash(plan, 2)

external = {
    **plan,
    "shots": [shot(1, 56, 34, -22), shot(2, 39, 17, 12)],
    "compatibility": {
        **plan["compatibility"],
        "external_context_frames": 22,
        "external_context_hash": "external-hash",
    },
    "total_delivered_frames": 51,
}
external["shots"][0]["external_context_frames"] = 22
external_revision = chain._plan_with_review_revision(
    external, 1, "Longer imported-video continuation.", 777, 73)
assert external_revision["shots"][0]["generation_start_frame"] == -22
assert external_revision["shots"][0]["delivered_frames"] == 51
assert external_revision["shots"][1]["generation_start_frame"] == 29
assert external_revision["total_delivered_frames"] == 68

try:
    chain._plan_with_review_revision(plan, 2, "Too short.", 999, 22)
except ValueError as exc:
    assert "17k+5" in str(exc) or "continuation overlap" in str(exc)
else:
    raise AssertionError("Review retry accepted an invalid H3 length")


class RetryRequest:
    def __init__(self, token, length):
        self.token = token
        self.length = length

    async def json(self):
        return {
            "token": self.token,
            "action": "retry",
            "scene_prompt": "Route retry.",
            "seed": "123",
            "length": self.length,
        }


async def check_route_validation():
    token = "review-length-test"
    loop = asyncio.get_running_loop()
    future = loop.create_future()
    chain._PENDING_REVIEWS[token] = {
        "future": future,
        "loop": loop,
        "plan": plan,
        "public": {"clip_index": 2, "prompt_prefix": ""},
        "current_seed": 2,
        "current_length": 56,
    }
    try:
        rejected = await chain._submit_review_decision(
            RetryRequest(token, 39))
        assert rejected.status == 400
        assert "next clip requires" in json.loads(rejected.text)["error"]
        assert not future.done()

        accepted = await chain._submit_review_decision(
            RetryRequest(token, 73))
        assert accepted.status == 200
        accepted_body = json.loads(accepted.text)
        assert accepted_body["length"] == 73
        assert accepted_body["scene_prompt"] == "Route retry."
        await asyncio.sleep(0)
        assert future.result()["raw_frames"] == 73
        assert future.result()["scene_prompt"] == "Route retry."
    finally:
        chain._PENDING_REVIEWS.pop(token, None)


asyncio.run(check_route_validation())


assert chain._review_candidate_target(1) == 1
assert chain._review_candidate_target("10") == 10
pending_node = chain.MiniMaxH3PendingReview()
pending_policy = pending_node.build(True)[0]
assert chain._deferred_review_enabled(pending_policy)
assert chain.MiniMaxH3ChainReview.INPUT_TYPES()["optional"][
    "pending_review"][0] == chain.REVIEW_DISPOSITION_TYPE
assert chain.CHAIN_NODE_CLASS_MAPPINGS[
    "MiniMaxH3PendingReview"] is chain.MiniMaxH3PendingReview
try:
    chain._review_candidate_target(21)
except ValueError as exc:
    assert "between 1 and 20" in str(exc)
else:
    raise AssertionError("Review Gate accepted too many candidates")


def candidate_segment(revision, seed):
    selected_plan = chain._plan_with_review_revision(
        plan, 2, "Scene 2.", seed, 56)
    return {
        "index": 2,
        "id": "scene_2",
        "revision": revision,
        "segment": "segments/%s.mp4" % revision,
        "checkpoint": "checkpoints/%s.safetensors" % revision,
        "metadata": "checkpoints/clip_0002.json",
        "revision_metadata": "checkpoints/%s.json" % revision,
        "raw_frames": 56,
        "delivered_frames": 34,
        "scene_prompt": "Scene 2.",
        "prompt": "Scene 2.",
        "prompt_hash": selected_plan["shots"][1]["prompt_hash"],
        "history_hash": chain._history_hash(selected_plan, 2),
        "seed": str(seed),
        "steps": 20,
        "checkpoint_sha256": revision,
    }


async def check_candidate_batch():
    sent = []

    class BatchServerInstance:
        client_id = "candidate-client"

        def send_sync(self, event, payload, client_id=None):
            sent.append((event, payload, client_id))

    original_server = chain.PromptServer
    original_review_video = chain._review_video
    original_load_revision = chain._load_checkpoint_revision
    original_prune_candidates = chain._prune_review_candidates
    original_select_candidate = chain._select_review_candidate
    original_resume_revisions = chain._review_candidate_resume_revisions
    original_write_archives = chain._write_run_archives
    original_persist_deferred = chain._persist_deferred_review
    original_execution_blocker = chain.ExecutionBlocker
    cleanup_calls = []
    archive_calls = []
    review_video_calls = []
    chain.PromptServer = type(
        "BatchServer", (), {"instance": BatchServerInstance()})

    def review_video(_plan, segment, _audio, retain_previous=False):
        review_video_calls.append((
            segment["revision"], _audio is not None,
            bool(retain_previous)))
        return (
            {"filename": "%s.mp4" % segment["revision"],
             "subfolder": "candidates", "type": "output"}, True, "")

    chain._review_video = review_video
    chain._prune_review_candidates = (
        lambda candidate_plan, scene, candidates, kept: (
            cleanup_calls.append((candidate_plan, scene, candidates, kept)) or {
                "kept": list(kept),
                "deleted": [],
                "reclaimed_bytes": 0,
                "warnings": [],
            }))
    chain._review_candidate_resume_revisions = (
        lambda _run_name, scene, revision: [
            {"scene": number,
             "revision": revision if number == scene else "%032x" % number}
            for number in range(1, scene + 1)])
    chain._write_run_archives = lambda selected_plan: archive_calls.append(
        selected_plan)
    automatic = candidate_segment("d" * 32, 2)
    automatic_result = await asyncio.wait_for(
        chain.MiniMaxH3ChainReview().review(
            {"plan": plan, "index": 2,
             "segments": [{"revision": "parent"}]},
            automatic, True, False, 0.0, False, False, "none",
            candidate_count=2, unique_id="review-node"),
        timeout=2.0)
    assert not chain._PENDING_REVIEWS
    automatic_decision = automatic_result["result"][0][
        "_h3_review_decision"]
    assert automatic_decision["action"] == "retry"
    assert automatic_decision["candidate_batch"]["target"] == 2
    assert len(automatic_decision["candidate_batch"]["candidates"]) == 1
    assert automatic_decision["candidate_batch"]["kept_revisions"] == []
    automatic_token = automatic_decision["candidate_batch"]["batch_token"]
    assert automatic_token in chain._ACTIVE_CANDIDATE_BATCHES
    progress = chain._ACTIVE_CANDIDATE_BATCHES[automatic_token]["public"]
    assert progress["candidate_batch_active"] is True
    assert progress["pending_decision"] is False
    assert progress["candidate_index"] == 1
    assert progress["end_clip"] == len(plan["shots"])
    assert [item["revision"] for item in progress["candidates"]] == [
        automatic["revision"]]
    assert "automatically generating candidate 2" in automatic_result[
        "result"][1]

    class KeepAutomaticCandidate:
        async def json(self):
            return {
                "token": automatic_token,
                "action": "update",
                "candidate_revisions": [automatic["revision"]],
            }

    keep_response = await chain._submit_candidate_batch_command(
        KeepAutomaticCandidate())
    assert keep_response.status == 200
    assert chain._ACTIVE_CANDIDATE_BATCHES[automatic_token][
        "kept_revisions"] == [automatic["revision"]]

    class PauseAutomaticBatch:
        async def json(self):
            return {
                "token": automatic_token,
                "action": "pause",
                "candidate_revisions": [automatic["revision"]],
            }

    pause_response = await chain._submit_candidate_batch_command(
        PauseAutomaticBatch())
    assert pause_response.status == 200
    assert chain._ACTIVE_CANDIDATE_BATCHES[automatic_token]["command"] == {
        "action": "pause",
        "candidate_revision": "",
        "kept_revisions": [automatic["revision"]],
    }
    chain._ACTIVE_CANDIDATE_BATCHES.clear()

    early_automatic = candidate_segment("e" * 32, 2)
    early_automatic_result = await chain.MiniMaxH3ChainReview().review(
        {"plan": plan, "index": 2,
         "segments": [{"revision": "parent"}]},
        early_automatic, True, False, 0.0, False, False, "none",
        candidate_count=2, unique_id="review-node")
    early_decision = early_automatic_result["result"][0][
        "_h3_review_decision"]
    early_token = early_decision["candidate_batch"]["batch_token"]

    class AcceptAutomaticBatch:
        async def json(self):
            return {
                "token": early_token,
                "action": "accept",
                "candidate_revision": early_automatic["revision"],
                "candidate_revisions": [],
            }

    accept_response = await chain._submit_candidate_batch_command(
        AcceptAutomaticBatch())
    assert accept_response.status == 200
    accept_body = json.loads(accept_response.text)
    assert accept_body["resume_scene"] == 3
    assert accept_body["resume_revisions"][-1] == {
        "scene": 2, "revision": early_automatic["revision"]}
    next_plan = chain._plan_with_review_revision(
        plan, 2, "Scene 2.", early_decision["seed"], 56)
    next_candidate = candidate_segment("f" * 32, early_decision["seed"])

    def select_automatic(selected_state, current_segment, decision):
        assert current_segment == next_candidate
        assert decision["candidate_revision"] == early_automatic["revision"]
        accepted_state = dict(selected_state)
        accepted_state["plan"] = chain._plan_with_review_revision(
            plan, 2, "Scene 2.", 2, 56)
        accepted_state.pop("candidate_batch", None)
        return early_automatic, accepted_state

    chain._select_review_candidate = select_automatic
    accepted_early_result = await asyncio.wait_for(
        chain.MiniMaxH3ChainReview().review(
            {"plan": next_plan, "index": 2,
             "segments": [{"revision": "parent"}],
             "candidate_batch": early_decision["candidate_batch"]},
            next_candidate, True, False, 0.0, False, False, "none",
            candidate_count=2, unique_id="review-node"),
        timeout=2.0)
    assert accepted_early_result["result"][0]["revision"] == (
        early_automatic["revision"])
    assert not chain._PENDING_REVIEWS
    assert early_token not in chain._ACTIVE_CANDIDATE_BATCHES
    assert any(
        event == "minimax_h3_context_loop_review_resolved"
        and payload.get("action") == "candidate_batch_approve"
        for event, payload, _client in sent)
    chain._select_review_candidate = original_select_candidate

    first = candidate_segment("a" * 32, 2)
    try:
        first_task = asyncio.create_task(chain.MiniMaxH3ChainReview().review(
            {"plan": plan, "index": 2, "segments": [{"revision": "parent"}]},
            first, True, False, 0.0, False, False, "none",
            candidate_count=2, review_each_candidate=True,
            unique_id="review-node"))
        for _ in range(100):
            if chain._PENDING_REVIEWS:
                break
            await asyncio.sleep(0.01)
        assert chain._PENDING_REVIEWS
        first_public = next(iter(chain._PENDING_REVIEWS.values()))["public"]
        assert first_public["candidate_index"] == 1
        assert first_public["candidate_generation_complete"] is False
        assert first_public["candidate_remaining"] == 1
        assert [item["revision"] for item in first_public["candidates"]] == [
            first["revision"]]

        class GenerateNext:
            async def json(self):
                return {
                    "token": first_public["token"],
                    "action": "next_candidate",
                    "candidate_revisions": [first["revision"]],
                }

        next_response = await chain._submit_review_decision(GenerateNext())
        next_body = json.loads(next_response.text)
        assert next_response.status == 200
        assert next_body["action"] == "next_candidate"
        assert next_body["kept_candidate_count"] == 1
        first_result = await asyncio.wait_for(first_task, timeout=2.0)
        decision = first_result["result"][0]["_h3_review_decision"]
        assert decision["action"] == "retry"
        assert decision["candidate_batch"]["target"] == 2
        assert len(decision["candidate_batch"]["candidates"]) == 1
        assert decision["candidate_batch"]["kept_revisions"] == [
            first["revision"]]
        assert decision["seed"] != 2

        second_plan = chain._plan_with_review_revision(
            plan, 2, "Scene 2.", decision["seed"], 56)
        second = candidate_segment("b" * 32, decision["seed"])
        state = {
            "plan": second_plan,
            "index": 2,
            "segments": [{"revision": "parent"}],
            "candidate_batch": decision["candidate_batch"],
        }
        chain._load_checkpoint_revision = lambda _run, _scene, revision: (
            {"segment": first if revision == first["revision"] else second},
            "candidate.json")
        task = asyncio.create_task(chain.MiniMaxH3ChainReview().review(
            state, second, True, False, 0.0, False, False, "none",
            candidate_count=2, unique_id="review-node"))
        for _ in range(100):
            if chain._PENDING_REVIEWS:
                break
            await asyncio.sleep(0.01)
        assert chain._PENDING_REVIEWS
        public = next(iter(chain._PENDING_REVIEWS.values()))["public"]
        assert public["candidate_count"] == 2
        assert public["candidate_generation_complete"] is True
        assert public["kept_candidate_revisions"] == [first["revision"]]
        assert [item["revision"] for item in public["candidates"]] == [
            first["revision"], second["revision"]]
        token = public["token"]

        class ChooseCurrent:
            async def json(self):
                return {"token": token, "action": "approve",
                        "candidate_revision": second["revision"],
                        "candidate_revisions": [first["revision"]]}

        response = await chain._submit_review_decision(ChooseCurrent())
        body = json.loads(response.text)
        assert response.status == 200
        assert body["candidate_number"] == 2
        assert body["kept_candidate_count"] == 2
        result = await asyncio.wait_for(task, timeout=2.0)
        assert result["result"][0]["revision"] == second["revision"]
        assert "selected candidate 2/2" in result["result"][1]
        assert cleanup_calls
        assert cleanup_calls[-1][3] == [first["revision"], second["revision"]]

        early = candidate_segment("c" * 32, 2)
        early_task = asyncio.create_task(chain.MiniMaxH3ChainReview().review(
            {"plan": plan, "index": 2, "segments": [{"revision": "parent"}]},
            early, True, False, 0.0, False, False, "none",
            candidate_count=3, review_each_candidate=True,
            unique_id="review-node"))
        for _ in range(100):
            if chain._PENDING_REVIEWS:
                break
            await asyncio.sleep(0.01)
        early_public = next(iter(chain._PENDING_REVIEWS.values()))["public"]
        assert early_public["candidate_generation_complete"] is False

        class AcceptEarly:
            async def json(self):
                return {
                    "token": early_public["token"],
                    "action": "approve",
                    "candidate_revision": early["revision"],
                    "candidate_revisions": [],
                }

        early_response = await chain._submit_review_decision(AcceptEarly())
        assert early_response.status == 200
        early_body = json.loads(early_response.text)
        assert early_body["candidate_number"] == 1
        assert early_body["candidate_count"] == 3
        assert early_body["candidate_generated_count"] == 1
        assert early_body["kept_candidate_count"] == 1
        early_result = await asyncio.wait_for(early_task, timeout=2.0)
        assert early_result["result"][0]["revision"] == early["revision"]
        assert cleanup_calls[-1][3] == [early["revision"]]

        finalize_token = "1" * 32
        finalize_candidate = candidate_segment("9" * 32, 29)
        chain._ACTIVE_CANDIDATE_BATCHES[finalize_token] = {
            "run_name": plan["run_name"],
            "scene": 2,
            "target": 3,
            "plan": plan,
            "candidates": [{"segment": finalize_candidate}],
            "kept_revisions": [finalize_candidate["revision"]],
            "command": {
                "action": "accept",
                "candidate_revision": finalize_candidate["revision"],
                "kept_revisions": [finalize_candidate["revision"]],
            },
        }

        class FinalizeAutomaticBatch:
            async def json(self):
                return {
                    "token": finalize_token,
                    "action": "finalize",
                    "candidate_revision": finalize_candidate["revision"],
                }

        finalize_response = await chain._submit_candidate_batch_command(
            FinalizeAutomaticBatch())
        assert finalize_response.status == 200
        assert finalize_token not in chain._ACTIVE_CANDIDATE_BATCHES
        assert archive_calls[-1]["shots"][1]["seed"] == 29
        assert cleanup_calls[-1][3] == [finalize_candidate["revision"]]

        deferred_documents = []
        chain._persist_deferred_review = (
            lambda deferred_plan, deferred_payload, deferred_candidates: (
                deferred_documents.append((
                    deferred_plan, deferred_payload, deferred_candidates))
                or "pending.json"))

        class TestExecutionBlocker:
            def __init__(self, value):
                self.value = value

        chain.ExecutionBlocker = TestExecutionBlocker
        deferred_first = candidate_segment("7" * 32, 71)
        deferred_first_result = await chain.MiniMaxH3ChainReview().review(
            {"plan": plan, "index": 2,
             "segments": [{"revision": "parent"}]},
            deferred_first, False, False, 0.0, False, False, "none",
            candidate_count=2, review_each_candidate=True,
            pending_review=pending_policy, unique_id="review-node")
        deferred_decision = deferred_first_result["result"][0][
            "_h3_review_decision"]
        assert deferred_decision["candidate_batch"]["target"] == 2
        assert "automatically generating candidate 2" in (
            deferred_first_result["result"][1])

        deferred_plan = chain._plan_with_review_revision(
            plan, 2, "Scene 2.", deferred_decision["seed"], 56)
        deferred_second = candidate_segment(
            "8" * 32, deferred_decision["seed"])
        deferred_result = await chain.MiniMaxH3ChainReview().review(
            {"plan": deferred_plan, "index": 2,
             "segments": [{"revision": "parent"}],
             "candidate_batch": deferred_decision["candidate_batch"]},
            deferred_second, False, False, 0.0, False, False, "none",
            candidate_count=2, review_each_candidate=True,
            pending_review=pending_policy, unique_id="review-node")
        assert isinstance(
            deferred_result["result"][0], TestExecutionBlocker)
        assert "pending review" in deferred_result["result"][1]
        assert not chain._PENDING_REVIEWS
        assert deferred_documents
        deferred_public = deferred_documents[-1][1]
        assert deferred_public["deferred_review"] is True
        assert deferred_public["candidate_generation_complete"] is True
        assert len(deferred_documents[-1][2]) == 2

        deferred_single = candidate_segment("0" * 32, 70)
        deferred_single_result = await chain.MiniMaxH3ChainReview().review(
            {"plan": plan, "index": 2,
             "segments": [{"revision": "parent"}]},
            deferred_single, False, False, 0.0, False, False, "none",
            audio=object(), candidate_count=1,
            pending_review=pending_policy, unique_id="review-node")
        assert isinstance(
            deferred_single_result["result"][0], TestExecutionBlocker)
        assert (deferred_single["revision"], True, True) in (
            review_video_calls)
    finally:
        chain._PENDING_REVIEWS.clear()
        chain._ACTIVE_CANDIDATE_BATCHES.clear()
        chain.PromptServer = original_server
        chain._review_video = original_review_video
        chain._load_checkpoint_revision = original_load_revision
        chain._prune_review_candidates = original_prune_candidates
        chain._select_review_candidate = original_select_candidate
        chain._review_candidate_resume_revisions = original_resume_revisions
        chain._write_run_archives = original_write_archives
        chain._persist_deferred_review = original_persist_deferred
        chain.ExecutionBlocker = original_execution_blocker


asyncio.run(check_candidate_batch())


async def check_deferred_review_storage():
    original_output_root = chain._output_root
    original_load_revision = chain._load_checkpoint_revision
    original_resume_revisions = chain._review_candidate_resume_revisions
    original_write_archives = chain._write_run_archives
    original_prune = chain._prune_review_candidates
    with tempfile.TemporaryDirectory() as temporary:
        chain._output_root = lambda: temporary
        pending_plan = json.loads(json.dumps(plan))
        pending_plan["run_name"] = "pending-review-test"
        selected = candidate_segment("4" * 32, 44)
        other = candidate_segment("5" * 32, 55)
        candidates = [
            chain._review_candidate_record(
                selected, {"filename": "selected.mp4", "subfolder": "reviews",
                           "type": "output"}, True, ""),
            chain._review_candidate_record(
                other, {"filename": "other.mp4", "subfolder": "reviews",
                        "type": "output"}, True, ""),
        ]
        token = "6" * 32
        public = {
            "token": token,
            "run_name": pending_plan["run_name"],
            "clip_index": 2,
            "clip_count": 3,
            "end_clip": 3,
            "shot_id": "scene_2",
            "candidate_count": 2,
            "candidate_generation_complete": True,
            "candidates": chain._review_public_candidates(candidates),
        }
        try:
            path = chain._persist_deferred_review(
                pending_plan, public, candidates)
            assert pathlib.Path(path).is_file()
            listed = chain._list_deferred_review_records(
                pending_plan["run_name"])
            assert len(listed) == 1
            assert listed[0]["deferred_review"] is True
            assert listed[0]["candidates"][0]["raw_frames"] == 56

            class ListRequest:
                query = {"run_name": pending_plan["run_name"]}

            response = await chain._list_deferred_reviews(ListRequest())
            assert response.status == 200
            assert len(json.loads(response.text)["reviews"]) == 1

            chain._load_checkpoint_revision = (
                lambda _run, _scene, revision: (
                    {"segment": selected if revision == selected["revision"]
                     else other}, "revision.json"))
            chain._review_candidate_resume_revisions = (
                lambda _run, scene, revision: [
                    {"scene": 1, "revision": "1" * 32},
                    {"scene": scene, "revision": revision},
                ])
            archive_calls = []
            prune_calls = []
            chain._write_run_archives = lambda value: archive_calls.append(value)
            chain._prune_review_candidates = (
                lambda value, scene, values, kept: (
                    prune_calls.append((value, scene, values, kept)) or {
                        "kept": kept,
                        "deleted": [other["revision"]],
                        "reclaimed_bytes": 123,
                        "warnings": [],
                    }))

            class DeferredRequest:
                def __init__(self, action):
                    self.action = action

                async def json(self):
                    return {
                        "action": self.action,
                        "token": token,
                        "run_name": pending_plan["run_name"],
                        "candidate_revision": selected["revision"],
                        "candidate_revisions": [],
                    }

            prepared = await chain._submit_deferred_review(
                DeferredRequest("prepare"))
            assert prepared.status == 200
            prepared_body = json.loads(prepared.text)
            assert prepared_body["resume_scene"] == 3
            assert prepared_body["resume_revisions"][-1]["revision"] == (
                selected["revision"])
            assert pathlib.Path(path).is_file()

            checkpoint_dir = pathlib.Path(temporary) / "h3_chains" / (
                pending_plan["run_name"]) / "checkpoints"
            chain._atomic_json(
                str(checkpoint_dir / "clip_0002.json"),
                {"segment": selected})
            finalized = await chain._submit_deferred_review(
                DeferredRequest("finalize"))
            assert finalized.status == 200
            finalized_body = json.loads(finalized.text)
            assert finalized_body["kept_candidate_count"] == 1
            assert finalized_body["deleted_candidate_count"] == 1
            assert archive_calls and prune_calls
            assert prune_calls[-1][3] == [selected["revision"]]
            assert not pathlib.Path(path).exists()
        finally:
            chain._output_root = original_output_root
            chain._load_checkpoint_revision = original_load_revision
            chain._review_candidate_resume_revisions = original_resume_revisions
            chain._write_run_archives = original_write_archives
            chain._prune_review_candidates = original_prune


asyncio.run(check_deferred_review_storage())


def check_candidate_resume_lineage():
    original_load = chain._load_checkpoint_revision
    revisions = {
        (1, "1" * 32): {
            "segment": {
                "index": 1,
                "revision": "1" * 32,
                "checkpoint_sha256": "hash-one",
            },
        },
        (2, "2" * 32): {
            "segment": {
                "index": 2,
                "revision": "2" * 32,
                "checkpoint_sha256": "hash-two",
                "predecessor_revision": "1" * 32,
                "predecessor_checkpoint_sha256": "hash-one",
            },
        },
    }
    chain._load_checkpoint_revision = (
        lambda _run_name, scene, revision: (
            revisions[(scene, revision)], "metadata.json"))
    try:
        assert chain._review_candidate_resume_revisions(
            "run", 2, "2" * 32) == [
                {"scene": 1, "revision": "1" * 32},
                {"scene": 2, "revision": "2" * 32},
            ]
        revisions[(2, "2" * 32)]["segment"][
            "predecessor_checkpoint_sha256"] = "wrong"
        try:
            chain._review_candidate_resume_revisions("run", 2, "2" * 32)
            raise AssertionError("candidate lineage hash mismatch was accepted")
        except ValueError as exc:
            assert "different scene 1 checkpoint" in str(exc)
    finally:
        chain._load_checkpoint_revision = original_load


check_candidate_resume_lineage()


def check_candidate_cleanup():
    original_manager = chain.CheckpointGraphManager
    deleted = []

    class FakeManager:
        def __init__(self, _root):
            pass

        def deletion_preview(self, run_name, scene, revision):
            assert run_name == plan["run_name"]
            assert scene == 2
            return {"allowed": True, "snapshot": "snapshot-" + revision}

        def delete(self, run_name, scene, revision, snapshot):
            deleted.append((run_name, scene, revision, snapshot))
            return {"reclaimed_bytes": 123}

    chain.CheckpointGraphManager = FakeManager
    try:
        candidates = [
            {"segment": candidate_segment("a" * 32, 1)},
            {"segment": candidate_segment("b" * 32, 2)},
            {"segment": candidate_segment("c" * 32, 3)},
        ]
        cleanup = chain._prune_review_candidates(
            plan, 2, candidates, ["a" * 32, "c" * 32])
        assert cleanup["kept"] == ["a" * 32, "c" * 32]
        assert cleanup["deleted"] == ["b" * 32]
        assert cleanup["reclaimed_bytes"] == 123
        assert deleted == [(
            plan["run_name"], 2, "b" * 32, "snapshot-" + "b" * 32)]
    finally:
        chain.CheckpointGraphManager = original_manager


check_candidate_cleanup()


def check_exact_candidate_selection():
    current_plan = chain._plan_with_review_revision(
        plan, 2, "Scene 2.", 999, 56)
    selected = candidate_segment("c" * 32, 2)
    metadata = {
        "compatibility": plan["compatibility"],
        "segment": selected,
    }
    original_load_revision = chain._load_checkpoint_revision
    original_st_load = chain._st_load
    original_atomic_json = chain._atomic_json
    original_lock = chain.checkpoint_run_lock
    writes = []
    chain._load_checkpoint_revision = lambda *_args: (metadata, "selected.json")
    chain._st_load = lambda _path: {
        "context_frames": torch.zeros((22, 2, 2, 3)),
        "video": torch.zeros((1, 2, 2)),
        "audio": torch.zeros((1, 2, 2)),
    }
    chain._atomic_json = lambda path, value: writes.append((path, value))
    chain.checkpoint_run_lock = lambda *_args: nullcontext()
    try:
        accepted, selected_state = chain._select_review_candidate({
            "plan": current_plan,
            "index": 2,
            "segments": [{"revision": "parent"}],
            "candidate_batch": {"scene": 2},
        }, candidate_segment("d" * 32, 999), {
            "candidate_revision": selected["revision"],
        })
        choice = accepted["_h3_review_decision"]
        assert choice["action"] == "candidate_selected"
        assert choice["plan"]["shots"][1]["seed"] == 2
        assert choice["context_frames"].shape[0] == 22
        assert selected_state["plan"]["shots"][1]["seed"] == 2
        assert "candidate_batch" not in selected_state
        assert writes and writes[0][1] is metadata
    finally:
        chain._load_checkpoint_revision = original_load_revision
        chain._st_load = original_st_load
        chain._atomic_json = original_atomic_json
        chain.checkpoint_run_lock = original_lock


check_exact_candidate_selection()


class FakePromptServerInstance:
    def __init__(self):
        self.client_id = "current-client"
        self.sent = []

    def send_sync(self, event, payload, client_id=None):
        self.sent.append((event, payload, client_id))


fake_prompt_server = FakePromptServerInstance()
chain.PromptServer.instance = fake_prompt_server
final_manifest = {
    "format": "h3_chain_manifest_v3",
    "run_name": "review_length",
    "plan_hash": "prepared-hash",
}
final_key = chain._final_review_preview_key(final_manifest)
chain._PENDING_FINAL_REVIEW_PREVIEWS[final_key] = {
    "token": "final-token",
    "node_id": "review-node",
    "client_id": "originating-client",
}
chain._publish_final_review_preview(
    final_manifest, str(ROOT / "final.mp4"), "assembled final")
assert final_key not in chain._PENDING_FINAL_REVIEW_PREVIEWS
assert fake_prompt_server.sent == [(
    "minimax_h3_context_loop_review_resolved",
    {
        "token": "final-token",
        "node_id": "review-node",
        "action": "final",
        "status": "assembled final",
        "final_video": {
            "filename": "final.mp4",
            "subfolder": "",
            "type": "output",
        },
    },
    "originating-client",
)]

print("H3 Review length and final preview handoff: pass")
