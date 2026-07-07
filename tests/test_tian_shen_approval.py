import pytest

from backend.core.orchestrator import handle_event
from backend.queue_worker import process_next_event
from backend.security.tian_shen import (
    APPROVAL_GREEN,
    APPROVAL_RED,
    APPROVAL_YELLOW,
    evaluate_command,
    load_policy,
    read_audit_records,
)
from backend.task_queue import ORCHESTRATOR_QUEUE_NAME


def test_tian_shen_green_event_enters_queue(test_db):
    response = handle_event(
        {
            "source": "test",
            "target": "tianshu",
            "action": "execute_employee_skill",
            "payload": {"task_id": 1, "task_type": "data_analysis", "task_input": {"rows": [1, 2]}},
        }
    )

    assert response["ok"] is True
    assert response["queued"] is True
    assert response["tian_shen"]["decision"] == APPROVAL_GREEN
    assert response["tian_shen"]["tian_brain"]["predicted_level"] == APPROVAL_GREEN

    redis_client = __import__("backend.database", fromlist=["get_redis"]).get_redis()
    assert redis_client.llen(ORCHESTRATOR_QUEUE_NAME) == 1


def test_tian_shen_yellow_requires_confirmation_before_queue(test_db):
    response = handle_event(
        {
            "source": "codex",
            "target": "tianwang",
            "action": "review_code",
            "payload": {"summary": "review only"},
        }
    )

    assert response["ok"] is False
    assert response["queued"] is False
    assert response["approval_required"] is True
    assert response["tian_shen"]["decision"] == APPROVAL_YELLOW

    redis_client = __import__("backend.database", fromlist=["get_redis"]).get_redis()
    assert redis_client.llen(ORCHESTRATOR_QUEUE_NAME) == 0


def test_tian_shen_yellow_confirmed_can_queue_and_execute(test_db):
    response = handle_event(
        {
            "source": "codex",
            "target": "tianshu",
            "action": "execute_employee_skill",
            "approval_confirmed": True,
            "payload": {"task_id": 1, "task_type": "data_analysis", "task_input": {"rows": [1, 2]}},
        }
    )

    assert response["ok"] is True
    assert response["queued"] is True
    assert response["tian_shen"]["decision"] == APPROVAL_YELLOW
    assert process_next_event(timeout=1) is True


def test_tian_shen_red_blocks_dangerous_cli_event(test_db):
    response = handle_event(
        {
            "source": "cli",
            "target": "tiandun_ops",
            "action": "execute_command",
            "command": "git push origin main",
            "payload": {"command": "git push origin main"},
        }
    )

    assert response["ok"] is False
    assert response["blocked"] is True
    assert response["queued"] is False
    assert response["tian_shen"]["decision"] == APPROVAL_RED
    assert response["tian_shen"]["danger_explanation"]
    assert response["tian_shen"]["safe_alternative"]
    assert response["tian_shen"]["tian_brain"]["predicted_level"] == APPROVAL_RED

    redis_client = __import__("backend.database", fromlist=["get_redis"]).get_redis()
    assert redis_client.llen(ORCHESTRATOR_QUEUE_NAME) == 0


def test_tian_shen_direct_engine_classifies_openclaw():
    decision = evaluate_command({"source": "openclaw", "target": "worker", "action": "plan"})

    assert decision["decision"] == APPROVAL_YELLOW
    assert decision["requires_confirmation"] is True


def test_policy_loading():
    policy = load_policy()

    assert policy["version"] == "phase-2.3.2"
    assert "git push" in policy["red"]["keywords"]
    assert "codex" in policy["yellow"]["sources"]
    assert policy["green"]["default_reasons"]


def test_audit_log(monkeypatch, tmp_path):
    audit_path = tmp_path / "tian_shen_audit.jsonl"
    monkeypatch.setenv("TIAN_SHEN_AUDIT_LOG", str(audit_path))

    decision = evaluate_command(
        {
            "source": "cli",
            "target": "tiandun_ops",
            "action": "execute_command",
            "command": "git push origin main",
        }
    )
    records = read_audit_records()

    assert decision["decision"] == APPROVAL_RED
    assert len(records) == 1
    assert records[0]["command"] == "git push origin main"
    assert records[0]["level"] == APPROVAL_RED
    assert records[0]["decision"] == APPROVAL_RED
    assert records[0]["source"] == "cli"
    assert records[0]["timestamp"]


def test_cross_entry_blocking(test_db):
    for source in ["api", "cli", "openclaw"]:
        response = handle_event(
            {
                "source": source,
                "target": "tiandun_ops",
                "action": "execute_command",
                "payload": {"command": "docker compose down"},
            }
        )
        assert response["ok"] is False
        assert response["blocked"] is True
        assert response["queued"] is False
        assert response["tian_shen"]["decision"] == APPROVAL_RED
        assert response["tian_shen"]["danger_explanation"]
        assert response["tian_shen"]["safe_alternative"]

    redis_client = __import__("backend.database", fromlist=["get_redis"]).get_redis()
    assert redis_client.llen(ORCHESTRATOR_QUEUE_NAME) == 0
