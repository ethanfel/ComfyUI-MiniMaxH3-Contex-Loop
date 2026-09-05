#!/usr/bin/env python3
"""Workflow ownership locks fence stale H3 project writers."""

import json
import pathlib
import shutil
import tempfile
import threading

from project_ownership import (
    ProjectOwnershipError,
    claim_project_ownership,
    heartbeat_project_ownership,
    ownership_path,
    ownership_status,
    project_write_guard,
    release_project_ownership,
    require_project_ownership,
)


OWNER_A = "workflow-owner-a-1234567890"
OWNER_B = "workflow-owner-b-1234567890"


def rejected(callable_, text=""):
    try:
        callable_()
    except ProjectOwnershipError as exc:
        assert text in str(exc)
        return
    raise AssertionError("Expected ProjectOwnershipError")


def main():
    with tempfile.TemporaryDirectory() as temporary:
        root = pathlib.Path(temporary)
        try:
            ownership_status(str(root), "film unsafe", OWNER_A)
        except ValueError as exc:
            assert "Use 'film_unsafe'" in str(exc)
        else:
            raise AssertionError("ownership accepted an aliasing Run name")
        initial = ownership_status(str(root), "film", OWNER_A)
        assert initial["enabled"] is False
        assert initial["available"] is True

        claimed = claim_project_ownership(
            str(root), "film", OWNER_A, "Workflow A")
        assert claimed["owned_by_requester"] is True
        assert claimed["epoch"] == 1
        proof_a = {"owner_id": OWNER_A, "epoch": claimed["epoch"]}
        assert require_project_ownership(
            str(root), "film", proof_a, "save a scene") == {
                **proof_a, "run_name": "film",
            }
        takeover_started = threading.Event()
        takeover_finished = threading.Event()
        takeover_result = {}

        def force_takeover():
            takeover_started.set()
            takeover_result.update(claim_project_ownership(
                str(root), "film", OWNER_B, "Workflow B", force=True))
            takeover_finished.set()

        with project_write_guard(
                str(root), "film", proof_a, "commit a checkpoint"):
            worker = threading.Thread(target=force_takeover)
            worker.start()
            assert takeover_started.wait(1.0)
            assert not takeover_finished.wait(0.1), (
                "Force ownership split an active durable commit")
        worker.join(timeout=2.0)
        assert not worker.is_alive()
        assert takeover_result["owned_by_requester"] is True
        assert takeover_result["epoch"] == 2
        rejected(lambda: require_project_ownership(
            str(root), "film", proof_a, "publish after takeover"),
            "stale workflow")

        # Restore owner A for the remaining release/status assertions.
        reclaimed = claim_project_ownership(
            str(root), "film", OWNER_A, "Workflow A", force=True)
        proof_a = {"owner_id": OWNER_A, "epoch": reclaimed["epoch"]}
        record_path = pathlib.Path(ownership_path(str(root), "film"))
        assert record_path.parent.name == ".project_ownership"
        run_directory = root / "h3_chains" / "film"
        run_directory.mkdir(parents=True)
        (run_directory / "generated.txt").write_text(
            "disposable output", encoding="utf-8")
        shutil.rmtree(run_directory)
        assert require_project_ownership(
            str(root), "film", proof_a, "save after output cleanup")

        refused = claim_project_ownership(
            str(root), "film", OWNER_B, "Workflow B")
        assert refused["owned_by_requester"] is False
        assert refused["owner_label"] == "Workflow A"
        rejected(lambda: require_project_ownership(
            str(root), "film", None, "save a scene"), "read-only")

        taken = claim_project_ownership(
            str(root), "film", OWNER_B, "Workflow B", force=True)
        assert taken["owned_by_requester"] is True
        assert taken["epoch"] == 4
        rejected(lambda: require_project_ownership(
            str(root), "film", proof_a, "publish a checkpoint"),
            "stale workflow")

        proof_b = {"owner_id": OWNER_B, "epoch": taken["epoch"]}
        released = release_project_ownership(
            str(root), "film", OWNER_B, taken["epoch"])
        assert released["available"] is True
        assert released["epoch"] == 5
        rejected(lambda: require_project_ownership(
            str(root), "film", proof_b, "delete a revision"))

        record_text = pathlib.Path(ownership_path(
            str(root), "film")).read_text(encoding="utf-8")
        assert OWNER_A not in record_text
        assert OWNER_B not in record_text
        assert "owner_digest" in record_text

        # A delayed heartbeat from a released or fenced workflow must never
        # acquire an empty lock or revive its old epoch.
        stale_heartbeat = heartbeat_project_ownership(
            str(root), "film", OWNER_B, proof_b["epoch"], "Workflow B")
        assert stale_heartbeat["owned_by_requester"] is False
        assert stale_heartbeat["available"] is True
        assert ownership_status(str(root), "film")["available"] is True

    with tempfile.TemporaryDirectory() as temporary:
        root = pathlib.Path(temporary)
        claimed = claim_project_ownership(
            str(root), "film", OWNER_A, "Workflow A")
        path = pathlib.Path(ownership_path(str(root), "film"))
        record = json.loads(path.read_text(encoding="utf-8"))
        record["lease_expires_at"] = 0
        path.write_text(json.dumps(record), encoding="utf-8")
        expired_refused = claim_project_ownership(
            str(root), "film", OWNER_B, "Workflow B")
        assert expired_refused["owned_by_requester"] is False
        assert expired_refused["available"] is False
        assert expired_refused["expired"] is True
        taken = claim_project_ownership(
            str(root), "film", OWNER_B, "Workflow B", force=True)
        assert taken["owned_by_requester"] is True
        assert taken["epoch"] == claimed["epoch"] + 1

    with tempfile.TemporaryDirectory() as temporary:
        assert require_project_ownership(
            temporary, "legacy", None, "save") is None


if __name__ == "__main__":
    main()
    print("project ownership tests passed")
