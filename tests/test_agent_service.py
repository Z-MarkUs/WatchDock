from pathlib import Path

from watchdock.agent_service import AgentService
from watchdock.config import AIConfig, ArchiveConfig, WatchedFolder, WatchDockConfig


ANALYSIS = {
    "category": "Documents",
    "suggested_name": "organized-notes.txt",
    "tags": ["notes", "review"],
    "confidence": 0.9,
    "reasoning": "test fixture",
    "requires_review": True,
}


class StaticProcessor:
    def analyze_file(self, _file_path):
        return dict(ANALYSIS)


class MutatingProcessor:
    def analyze_file(self, file_path):
        Path(file_path).write_text("changed while provider was running", encoding="utf-8")
        return dict(ANALYSIS)


def make_service(tmp_path, *, processor=None):
    inbox = tmp_path / "inbox"
    inbox.mkdir(exist_ok=True)
    config = WatchDockConfig(
        watched_folders=[WatchedFolder(str(inbox), recursive=True)],
        ai_config=AIConfig(provider="ollama", model="test-model"),
        archive_config=ArchiveConfig(str(tmp_path / "archive")),
        mode="hitl",
    )
    config_path = tmp_path / "config.json"
    config.save(str(config_path))
    return AgentService(
        config,
        config_path=config_path,
        state_dir=tmp_path,
        ai_processor=processor or StaticProcessor(),
    )


def assert_envelope(response, operation, *, ok=True):
    assert set(response) == {"ok", "operation", "data", "error"}
    assert response["ok"] is ok
    assert response["operation"] == operation
    assert isinstance(response["data"], dict)
    assert (response["error"] is None) is ok


def test_status_and_doctor_are_structured_and_report_no_execution_capability(tmp_path):
    service = make_service(tmp_path)

    status = service.status()
    assert_envelope(status, "status")
    assert status["data"]["mode"] == "hitl"
    assert status["data"]["watched_folders"][0]["exists"] is True
    assert status["data"]["queue"]["pending"] == 0
    assert status["data"]["guardrails"] == {
        "human_approval_required": True,
        "filesystem_execution_available": False,
    }

    doctor = service.doctor()
    assert_envelope(doctor, "doctor")
    assert doctor["data"]["ready"] is True
    assert doctor["data"]["errors"] == 0
    assert doctor["data"]["side_effects"] == ["archive_write_probe"]
    assert not list((tmp_path / "archive").glob(".watchdock-agent-doctor-*"))


def test_analyze_is_a_dry_run_and_queue_persists_without_moving(tmp_path):
    service = make_service(tmp_path)
    source = tmp_path / "inbox" / "meeting notes.txt"
    source.write_text("agenda", encoding="utf-8")
    original = source.read_bytes()

    analyzed = service.analyze_file(str(source))
    assert_envelope(analyzed, "analyze_file")
    assert analyzed["data"]["dry_run"] is True
    assert analyzed["data"]["queued"] is False
    assert analyzed["data"]["analysis"]["category"] == "Documents"
    proposed_destination = Path(analyzed["data"]["proposed_action"]["to"])
    assert source.read_bytes() == original
    assert not proposed_destination.exists()
    assert service.pending_queue.list_actions() == []

    queued = service.queue_file(str(source))
    assert_envelope(queued, "queue_file")
    assert queued["data"]["queued"] is True
    assert queued["data"]["created"] is True
    assert queued["data"]["deduplicated"] is False
    assert queued["data"]["already_queued"] is False
    assert queued["data"]["source_file_mutated"] is False
    assert queued["data"]["side_effects"] == [
        "provider_analysis",
        "queue_database_write",
    ]
    assert queued["data"]["human_approval_required"] is True
    assert queued["data"]["action"]["status"] == "pending"
    assert len(queued["data"]["action"]["source_fingerprint"]["sha256"]) == 64
    assert queued["data"]["action"]["safety"]["source_current"] is True
    assert source.read_bytes() == original
    assert not Path(queued["data"]["action"]["proposed_action"]["to"]).exists()
    assert len(service.pending_queue.get_pending()) == 1

    duplicate = service.queue_file(str(source))
    assert duplicate["ok"] is True
    assert duplicate["data"]["created"] is False
    assert duplicate["data"]["deduplicated"] is True
    assert duplicate["data"]["already_queued"] is True
    assert duplicate["data"]["side_effects"] == [
        "provider_analysis",
        "queue_database_read",
    ]
    assert duplicate["data"]["action"]["action_id"] == queued["data"]["action"][
        "action_id"
    ]
    assert len(service.pending_queue.get_pending()) == 1


def test_analyze_and_queue_reject_paths_outside_enabled_watched_roots(tmp_path):
    service = make_service(tmp_path)
    outside = tmp_path / "outside.txt"
    outside.write_text("must stay outside", encoding="utf-8")

    for operation in (service.analyze_file, service.queue_file):
        response = operation(str(outside))
        assert_envelope(response, operation.__name__, ok=False)
        assert response["error"]["code"] == "outside_watched_roots"

    assert outside.read_text(encoding="utf-8") == "must stay outside"
    assert service.pending_queue.list_actions() == []


def test_source_replacement_during_analysis_fails_closed_without_queueing(tmp_path):
    service = make_service(tmp_path, processor=MutatingProcessor())
    source = tmp_path / "inbox" / "changing.txt"
    source.write_text("before", encoding="utf-8")

    response = service.queue_file(str(source))

    assert_envelope(response, "queue_file", ok=False)
    assert response["error"]["code"] == "source_changed"
    assert service.pending_queue.list_actions() == []
    assert source.read_text(encoding="utf-8") == "changed while provider was running"


def test_action_listing_lookup_and_rejection_keep_source_untouched(tmp_path):
    service = make_service(tmp_path)
    source = tmp_path / "inbox" / "review.txt"
    source.write_text("review me", encoding="utf-8")
    queued = service.queue_file(str(source))
    action_id = queued["data"]["action"]["action_id"]

    listed = service.list_actions(statuses=["pending"])
    assert_envelope(listed, "list_actions")
    assert listed["data"]["count"] == 1
    assert listed["data"]["actions"][0]["action_id"] == action_id

    fetched = service.get_action(action_id)
    assert_envelope(fetched, "get_action")
    assert fetched["data"]["action"]["safety"]["within_watched_roots"] is True

    rejected = service.reject_action(action_id)
    assert_envelope(rejected, "reject_action")
    assert rejected["data"]["action"]["status"] == "rejected"
    assert rejected["data"]["source_file_mutated"] is False
    assert rejected["data"]["side_effects"] == ["queue_database_write"]
    assert source.read_text(encoding="utf-8") == "review me"

    # The default list is review-focused; terminal history is explicitly requested.
    assert service.list_actions()["data"]["count"] == 0
    assert service.list_actions(statuses=["rejected"])["data"]["count"] == 1

    # Rejecting an already-rejected action is deliberately idempotent and read-only.
    rejected_again = service.reject_action(action_id)
    assert rejected_again["ok"] is True
    assert rejected_again["data"]["side_effects"] == ["queue_database_read"]
    retry = service.retry_action(action_id)
    assert_envelope(retry, "retry_action", ok=False)
    assert retry["error"]["code"] == "transition_not_allowed"


def test_retry_only_accepts_failed_actions_with_current_safe_sources(tmp_path):
    service = make_service(tmp_path)
    source = tmp_path / "inbox" / "retry.txt"
    source.write_text("reviewed version", encoding="utf-8")
    action_id = service.queue_file(str(source))["data"]["action"]["action_id"]
    claimed = service.pending_queue.claim(action_id, worker_id="test")
    service.pending_queue.fail(claimed.action_id, "simulated failure")

    retried = service.retry_action(action_id)
    assert_envelope(retried, "retry_action")
    assert retried["data"]["action"]["status"] == "pending"
    assert retried["data"]["human_approval_required"] is True

    claimed_again = service.pending_queue.claim(action_id, worker_id="test")
    service.pending_queue.fail(claimed_again.action_id, "simulated failure again")
    source.write_text("replacement with different contents", encoding="utf-8")

    stale = service.retry_action(action_id)
    assert_envelope(stale, "retry_action", ok=False)
    assert stale["error"]["code"] == "source_changed"
    assert service.pending_queue.get_by_id(action_id).status == "failed"


def test_invalid_ids_states_filters_and_limits_return_typed_errors(tmp_path):
    service = make_service(tmp_path)

    for operation in (
        service.get_action,
        service.reject_action,
        service.retry_action,
    ):
        response = operation("missing-action")
        assert response["ok"] is False
        assert response["error"]["code"] == "action_not_found"

    invalid_status = service.list_actions(statuses=["not-a-state"])
    assert_envelope(invalid_status, "list_actions", ok=False)
    assert invalid_status["error"]["code"] == "invalid_request"

    invalid_limit = service.list_actions(limit=0)
    assert_envelope(invalid_limit, "list_actions", ok=False)
    assert invalid_limit["error"]["code"] == "invalid_request"

    source = tmp_path / "inbox" / "processing.txt"
    source.write_text("claimed", encoding="utf-8")
    action_id = service.queue_file(str(source))["data"]["action"]["action_id"]
    service.pending_queue.claim(action_id, worker_id="test")
    rejected = service.reject_action(action_id)
    assert rejected["ok"] is False
    assert rejected["error"]["code"] == "transition_not_allowed"
    assert source.exists()


def test_from_config_path_requires_existing_configuration(tmp_path):
    response_path = tmp_path / "missing.json"

    try:
        AgentService.from_config_path(response_path)
    except FileNotFoundError as exc:
        assert "configuration not found" in str(exc)
    else:  # pragma: no cover - makes the failure message explicit
        raise AssertionError("missing agent configuration was silently accepted")
