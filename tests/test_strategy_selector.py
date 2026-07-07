from backend.agent_meeting import create_meeting
from backend.agent_meeting.meeting_room import clear_meetings
from backend.strategy_engine import route_strategy, select_best_strategy
from backend.task_queue import ORCHESTRATOR_QUEUE_NAME


def test_strategy_selector_outputs_best_strategy_risk_score_and_agents():
    clear_meetings()
    meeting = create_meeting("提升京东店铺利润20%", {"store": "京东60店"})
    strategy = select_best_strategy(meeting)

    assert strategy["center"] == "AI Strategy Decision Loop"
    assert strategy["best_strategy"]
    assert strategy["risk_score"] == strategy["best_strategy"]["risk_score"]
    assert strategy["assigned_agents"] == strategy["best_strategy"]["assigned_agents"]
    assert "tiancai_data" in strategy["assigned_agents"]
    assert "tiance_strategy" in strategy["assigned_agents"]
    assert len(strategy["candidate_strategies"]) == 3
    assert strategy["candidate_strategies"][0]["total_score"] >= strategy["candidate_strategies"][-1]["total_score"]
    assert strategy["best_strategy"]["can_auto_execute"] is False
    assert strategy["best_strategy"]["can_spend_money"] is False


def test_strategy_router_builds_plan_and_approval_preview_without_queue(test_db):
    meeting = create_meeting("提升京东店铺利润20%", {"store": "京东60店"})
    strategy = select_best_strategy(meeting)
    routing = route_strategy(strategy["best_strategy"], submit_to_queue=False)

    assert routing["mode"] == "strategy_route_preview"
    assert routing["submit_to_queue"] is False
    assert routing["steps"]
    assert routing["approvals"]
    assert all(row["approval"]["center"] == "TianShen" for row in routing["approvals"])
    assert routing["dispatches"] == []

    redis_client = __import__("backend.database", fromlist=["get_redis"]).get_redis()
    assert redis_client.llen(ORCHESTRATOR_QUEUE_NAME) == 0


def test_strategy_router_blocks_dangerous_actions_before_queue(test_db):
    meeting = create_meeting("删除数据库并 git push 生产部署", {"store": "京东60店"})
    strategy = select_best_strategy(meeting)
    best = strategy["best_strategy"]
    routing = route_strategy(best, submit_to_queue=True)

    assert best["blocked_by_default"] is True
    assert best["risk_score"] >= 95
    assert "git push" in best["forbidden_actions"]
    assert routing["dispatches"]
    assert all(row["queued"] is False for row in routing["dispatches"])
    assert all(row["tian_shen"]["decision"] == "RED" for row in routing["dispatches"])

    redis_client = __import__("backend.database", fromlist=["get_redis"]).get_redis()
    assert redis_client.llen(ORCHESTRATOR_QUEUE_NAME) == 0


def test_strategy_plan_requires_login(client):
    response = client.post("/command/strategy/plan", json={"goal": "提升京东店铺利润20%"})

    assert response.status_code == 401


def test_strategy_plan_rejects_low_permission(client, viewer_headers):
    response = client.post(
        "/command/strategy/plan",
        headers=viewer_headers,
        json={"goal": "提升京东店铺利润20%"},
    )

    assert response.status_code == 403


def test_strategy_plan_endpoint_is_safe_by_default(client, owner_headers):
    clear_meetings()
    response = client.post(
        "/command/strategy/plan",
        headers=owner_headers,
        json={"goal": "提升京东店铺利润20%", "context": {"store": "京东60店"}},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["meeting"]["consensus"]["final_consensus"]
    assert body["strategy"]["best_strategy"]
    assert body["strategy"]["best_strategy"]["can_auto_execute"] is False
    assert body["routing"]["mode"] == "strategy_route_preview"
    assert body["routing"]["dispatches"] == []

    redis_client = __import__("backend.database", fromlist=["get_redis"]).get_redis()
    assert redis_client.llen(ORCHESTRATOR_QUEUE_NAME) == 0
