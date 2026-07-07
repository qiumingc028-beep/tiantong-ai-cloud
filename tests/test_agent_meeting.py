from backend.agent_meeting import create_meeting
from backend.agent_meeting.meeting_room import clear_meetings
from backend.task_queue import ORCHESTRATOR_QUEUE_NAME


def test_agent_meeting_builds_messages_consensus_and_approval_gate():
    clear_meetings()
    meeting = create_meeting("提升京东店铺利润20%", {"store": "京东60店"})

    assert meeting["mode"] == "multi_agent_ai_meeting"
    assert meeting["status"] == "discussion_completed"
    assert meeting["goal"] == "提升京东店铺利润20%"
    assert meeting["invitees"] == ["tiancai_data", "tiance_strategy", "tianshang", "tiantou", "tianjian_test", "tian_shen"]
    assert {message["employee_code"] for message in meeting["messages"]} == set(meeting["invitees"])
    assert all({"analysis", "suggestion", "risk", "expected_result"} <= set(message) for message in meeting["messages"])
    assert meeting["consensus"]["approval_required"] is True
    assert meeting["consensus"]["can_auto_execute"] is False
    assert meeting["consensus"]["can_modify_data"] is False
    assert meeting["consensus"]["can_call_external_tool"] is False
    assert meeting["approval_gate"]["center"] == "TianShen"
    assert meeting["approval_gate"]["decision"] == "YELLOW"
    assert meeting["safety"]["discussion_only"] is True
    assert meeting["safety"]["can_auto_execute"] is False


def test_meeting_create_requires_login(client):
    response = client.post("/command/meeting/create", json={"goal": "提升京东店铺利润20%"})

    assert response.status_code == 401


def test_meeting_create_rejects_low_permission(client, viewer_headers):
    response = client.post(
        "/command/meeting/create",
        headers=viewer_headers,
        json={"goal": "提升京东店铺利润20%"},
    )

    assert response.status_code == 403


def test_meeting_create_is_discussion_only_and_does_not_queue(client, owner_headers):
    clear_meetings()
    response = client.post(
        "/command/meeting/create",
        headers=owner_headers,
        json={"goal": "提升京东店铺利润20%", "context": {"store": "京东60店"}},
    )

    assert response.status_code == 200
    meeting = response.json()["meeting"]
    assert meeting["consensus"]["final_consensus"]
    assert meeting["approval_gate"]["requires_confirmation"] is True
    assert meeting["safety"]["requires_approval_center"] is True

    redis_client = __import__("backend.database", fromlist=["get_redis"]).get_redis()
    assert redis_client.llen(ORCHESTRATOR_QUEUE_NAME) == 0


def test_meeting_history_lists_recent_discussions(client, owner_headers):
    clear_meetings()
    created = client.post(
        "/command/meeting/create",
        headers=owner_headers,
        json={"goal": "提升京东店铺利润20%"},
    )
    assert created.status_code == 200

    response = client.get("/command/meeting/history", headers=owner_headers)

    assert response.status_code == 200
    meetings = response.json()["meetings"]
    assert meetings
    assert meetings[0]["goal"] == "提升京东店铺利润20%"
