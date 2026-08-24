import json
import multiprocessing
import sqlite3
import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from watchdock.pending_actions import PendingActionsQueue
from watchdock.paths import default_database_path


def _claim_in_spawned_process(db_path, action_id, worker_id, start, results):
    queue = PendingActionsQueue(db_path, migrate_legacy=False)
    start.wait(timeout=10)
    claimed = queue.claim(action_id, worker_id=worker_id)
    results.put(claimed is not None)


def _queue(tmp_path, name="actions.sqlite3"):
    return PendingActionsQueue(tmp_path / name, migrate_legacy=False)


def _source(tmp_path, name="source.txt", content="reviewed content"):
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    return path


def _add_action(queue, source, *, include_hash=False):
    analysis = {
        "category": "Documents",
        "tags": ["reviewed", "合同"],
        "nested": {"confidence": 0.91},
    }
    proposal = {
        "action_type": "move",
        "from": str(source),
        "to": str(source.parent / "Archive" / "renamed.txt"),
        "new_name": "renamed.txt",
    }
    return queue.add(
        str(source),
        analysis,
        proposal,
        include_source_hash=include_hash,
    )


def test_add_persists_exact_payload_uuid_fingerprint_and_wal(tmp_path):
    db_path = tmp_path / "queue.sqlite3"
    source = _source(tmp_path, content="hello 世界")
    queue = PendingActionsQueue(db_path, migrate_legacy=False)

    added = _add_action(queue, source, include_hash=True)
    uuid.UUID(added.action_id)
    assert added.status == "pending"
    assert added.source_size == source.stat().st_size
    assert added.source_mtime_ns == source.stat().st_mtime_ns
    assert len(added.source_sha256) == 64

    reopened = PendingActionsQueue(db_path, migrate_legacy=False)
    loaded = reopened.get_by_id(added.action_id)
    assert loaded is not None
    assert loaded.analysis == added.analysis
    assert loaded.proposed_action == added.proposed_action
    assert loaded.source_fingerprint == added.source_fingerprint
    assert reopened.actions[0].action_id == added.action_id
    assert reopened.source_matches(loaded)

    with sqlite3.connect(db_path) as connection:
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"


def test_default_paths_honor_watchdock_home_at_construction_time(tmp_path, monkeypatch):
    portable_home = tmp_path / "portable"
    monkeypatch.setenv("WATCHDOCK_HOME", str(portable_home))

    queue = PendingActionsQueue(migrate_legacy=False)

    assert queue.db_path == default_database_path()
    assert queue.db_path.parent == portable_home
    assert queue.db_path.exists()


def test_source_match_detects_replacement_after_review(tmp_path):
    source = _source(tmp_path, content="first")
    queue = _queue(tmp_path)
    action = _add_action(queue, source, include_hash=True)
    assert queue.source_matches(action)

    source.write_text("different-size replacement", encoding="utf-8")
    assert not queue.source_matches(action)


def test_proposal_paths_are_frozen_and_source_must_match(tmp_path, monkeypatch):
    source = _source(tmp_path)
    queue = _queue(tmp_path)
    monkeypatch.chdir(tmp_path)

    action = queue.add(
        "source.txt",
        {},
        {
            "action_type": "move",
            "from": "source.txt",
            "to": "Archive/source.txt",
        },
    )

    assert action.file_path == str(source.resolve())
    assert action.proposed_action["from"] == str(source.resolve())
    assert action.proposed_action["to"] == str(
        (tmp_path / "Archive" / "source.txt").resolve()
    )

    other = _source(tmp_path, "other.txt")
    with pytest.raises(ValueError, match="does not match"):
        queue.add(
            str(source),
            {},
            {
                "action_type": "move",
                "from": str(other),
                "to": str(tmp_path / "Archive" / "source.txt"),
            },
        )


def test_new_action_requires_an_existing_regular_source(tmp_path):
    queue = _queue(tmp_path)
    missing = tmp_path / "missing.txt"

    with pytest.raises(FileNotFoundError):
        queue.add(str(missing), {}, {"action_type": "move"})

    with pytest.raises(ValueError, match="regular source file"):
        queue.add(str(tmp_path), {}, {"action_type": "move"})


def test_claim_fail_retry_complete_lifecycle_and_events(tmp_path):
    source = _source(tmp_path)
    queue = _queue(tmp_path)
    action = _add_action(queue, source)

    claimed = queue.claim(action.action_id, worker_id="worker-a")
    assert claimed.status == "processing"
    assert claimed.claimed_by == "worker-a"
    assert claimed.attempt_count == 1
    assert queue.claim(action.action_id, worker_id="worker-b") is None
    assert queue.get_pending() == []

    failed = queue.fail(action.action_id, "destination is locked")
    assert failed.status == "failed"
    assert failed.error == "destination is locked"
    assert failed.failed_at is not None
    assert queue.complete(action.action_id) is None

    retried = queue.retry(action.action_id)
    assert retried.status == "pending"
    assert retried.error is None
    claimed_again = queue.claim(action.action_id, worker_id="worker-b")
    assert claimed_again.attempt_count == 2
    completed = queue.complete(action.action_id)
    assert completed.status == "completed"
    assert completed.completed_at is not None
    assert queue.get_by_id(action.action_id).status == "completed"

    events = queue.get_events(action.action_id)
    assert [event["to_status"] for event in events] == [
        "pending",
        "processing",
        "failed",
        "pending",
        "processing",
        "completed",
    ]
    assert events[2]["error"] == "destination is locked"


def test_compatibility_approve_and_remove_are_claim_then_complete(tmp_path):
    source = _source(tmp_path)
    queue = _queue(tmp_path)
    action = _add_action(queue, source)

    approved = queue.approve(action.action_id)
    assert approved.status == "processing"
    assert queue.get_by_id(action.action_id).status == "processing"

    # The compatibility remove call is deliberately a state transition, not a
    # physical deletion. Callers must invoke it only after execution succeeds.
    completed = queue.remove(action.action_id)
    assert completed.status == "completed"
    assert queue.get_by_id(action.action_id).status == "completed"


def test_reject_is_durable_and_remove_does_not_reclassify_it(tmp_path):
    source = _source(tmp_path)
    queue = _queue(tmp_path)
    action = _add_action(queue, source)

    rejected = queue.reject(action.action_id)
    assert rejected.status == "rejected"
    assert rejected.rejected_at is not None
    assert queue.remove(action.action_id) is None
    assert queue.get_by_id(action.action_id).status == "rejected"


def test_concurrent_claim_allows_exactly_one_winner(tmp_path):
    db_path = tmp_path / "concurrent.sqlite3"
    source = _source(tmp_path)
    seed_queue = PendingActionsQueue(db_path, migrate_legacy=False)
    action = _add_action(seed_queue, source)
    queues = [PendingActionsQueue(db_path, migrate_legacy=False) for _ in range(8)]
    barrier = Barrier(len(queues))

    def attempt_claim(index):
        barrier.wait()
        return queues[index].claim(action.action_id, worker_id=f"worker-{index}")

    with ThreadPoolExecutor(max_workers=len(queues)) as executor:
        results = list(executor.map(attempt_claim, range(len(queues))))

    winners = [result for result in results if result is not None]
    assert len(winners) == 1
    persisted = seed_queue.get_by_id(action.action_id)
    assert persisted.status == "processing"
    assert persisted.claimed_by == winners[0].claimed_by


def test_concurrent_claim_next_does_not_duplicate_work(tmp_path):
    db_path = tmp_path / "claim-next.sqlite3"
    source = _source(tmp_path)
    seed_queue = PendingActionsQueue(db_path, migrate_legacy=False)
    action = _add_action(seed_queue, source)
    queues = [PendingActionsQueue(db_path, migrate_legacy=False) for _ in range(6)]
    barrier = Barrier(len(queues))

    def claim_next(index):
        barrier.wait()
        return queues[index].claim_next(worker_id=f"next-{index}")

    with ThreadPoolExecutor(max_workers=len(queues)) as executor:
        results = list(executor.map(claim_next, range(len(queues))))

    winners = [result for result in results if result is not None]
    assert [winner.action_id for winner in winners] == [action.action_id]


def test_spawned_processes_allow_exactly_one_claim_winner(tmp_path):
    db_path = tmp_path / "process-concurrent.sqlite3"
    source = _source(tmp_path)
    queue = PendingActionsQueue(db_path, migrate_legacy=False)
    action = _add_action(queue, source)
    context = multiprocessing.get_context("spawn")
    start = context.Event()
    results = context.Queue()
    processes = [
        context.Process(
            target=_claim_in_spawned_process,
            args=(db_path, action.action_id, f"process-{index}", start, results),
        )
        for index in range(4)
    ]

    for process in processes:
        process.start()
    start.set()
    for process in processes:
        process.join(timeout=15)

    assert all(not process.is_alive() for process in processes)
    assert all(process.exitcode == 0 for process in processes)
    assert sum(results.get(timeout=5) for _ in processes) == 1


def test_stale_processing_is_failed_for_manual_reconciliation(tmp_path):
    source = _source(tmp_path)
    queue = _queue(tmp_path)
    action = _add_action(queue, source)
    queue.claim(action.action_id, worker_id="crashed-worker")

    stale = queue.fail_stale_processing(0)
    assert [item.action_id for item in stale] == [action.action_id]
    assert stale[0].status == "failed"
    assert "outcome requires review" in stale[0].error


def test_clear_processed_only_purges_terminal_history(tmp_path):
    queue = _queue(tmp_path)
    completed_source = _source(tmp_path, "completed.txt")
    rejected_source = _source(tmp_path, "rejected.txt")
    failed_source = _source(tmp_path, "failed.txt")

    completed = _add_action(queue, completed_source)
    queue.claim(completed.action_id)
    queue.complete(completed.action_id)
    rejected = _add_action(queue, rejected_source)
    queue.reject(rejected.action_id)
    failed = _add_action(queue, failed_source)
    queue.claim(failed.action_id)
    queue.fail(failed.action_id, "keep me")

    assert queue.clear_processed() == 2
    assert queue.get_by_id(completed.action_id) is None
    assert queue.get_by_id(rejected.action_id) is None
    assert queue.get_by_id(failed.action_id).status == "failed"


def test_legacy_json_import_is_idempotent_and_approved_is_not_assumed_done(
    tmp_path,
):
    source = _source(tmp_path)
    legacy_path = tmp_path / "pending_actions.json"
    db_path = tmp_path / "migrated.sqlite3"
    legacy_path.write_text(
        json.dumps(
            {
                "actions": [
                    {
                        "action_id": "legacy-pending",
                        "file_path": str(source),
                        "analysis": {"category": "Documents"},
                        "proposed_action": {"to": "Archive/source.txt"},
                        "created_at": "2025-01-01T00:00:00",
                        "status": "pending",
                    },
                    {
                        "action_id": "legacy-approved",
                        "file_path": str(source),
                        "analysis": {},
                        "proposed_action": {"to": "Archive/source.txt"},
                        "created_at": "2025-01-02T00:00:00",
                        "status": "approved",
                    },
                    {
                        "action_id": "legacy-rejected",
                        "file_path": str(source),
                        "analysis": {},
                        "proposed_action": {"to": "Archive/source.txt"},
                        "created_at": "2025-01-03T00:00:00",
                        "status": "rejected",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    queue = PendingActionsQueue(db_path, legacy_json_path=legacy_path)
    assert queue.get_by_id("legacy-pending").status == "pending"
    approved = queue.get_by_id("legacy-approved")
    assert approved.status == "failed"
    assert "could not be verified" in approved.error
    assert queue.get_by_id("legacy-rejected").status == "rejected"
    assert queue.get_by_id("legacy-pending").source_size == source.stat().st_size

    reopened = PendingActionsQueue(db_path, legacy_json_path=legacy_path)
    assert len(reopened.list_actions()) == 3


def test_custom_database_imports_colocated_legacy_queue(tmp_path):
    source = _source(tmp_path)
    (tmp_path / "pending_actions.json").write_text(
        json.dumps(
            {
                "actions": [
                    {
                        "action_id": "colocated-legacy",
                        "file_path": str(source),
                        "analysis": {},
                        "proposed_action": {"to": "Archive/source.txt"},
                        "status": "pending",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    queue = PendingActionsQueue(tmp_path / "pending_actions.sqlite3")

    assert queue.get_by_id("colocated-legacy").status == "pending"


def test_corrupt_legacy_json_does_not_prevent_new_sqlite_actions(tmp_path):
    source = _source(tmp_path)
    legacy_path = tmp_path / "broken.json"
    legacy_path.write_text("{not valid json", encoding="utf-8")
    queue = PendingActionsQueue(
        tmp_path / "queue.sqlite3", legacy_json_path=legacy_path
    )

    action = _add_action(queue, source)
    assert queue.get_by_id(action.action_id).status == "pending"
