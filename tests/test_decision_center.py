from backend.autonomy.task_monitor import monitor_business_state
from backend.decision_center import evaluate_business_decisions, list_decisions
from backend.decision_center.decision_memory import clear_decisions
from backend.task_queue import ORCHESTRATOR_QUEUE_NAME


def test_decision_engine_recommends_ranked_strategy_without_execution():
    clear_decisions()
    monitor = monitor_business_state({"store": "京东60店", "conversion_change_pct": -0.2})
    decision = evaluate_business_decisions(monitor["opportunities"])

    assert decision["center"] == "TianBrain AI Decision Center"
    assert decision["mode"] == "recommendation_only"
    assert decision["recommended_strategy"]
    assert decision["safety"]["can_auto_execute"] is False
    first = decision["decisions"][0]
    assert len(first["candidate_strategies"]) == 3
    assert first["recommended_strategy"]["total_score"] >= first["candidate_strategies"][-1]["total_score"]
    assert first["recommended_strategy"]["can_auto_execute"] is False
    assert first["recommended_strategy"]["can_modify_data"] is False
    assert first["recommended_strategy"]["can_spend_money"] is False
    assert first["approval_gate"]["center"] == "TianShen"
    assert first["approval_gate"]["decision"] in {"GREEN", "YELLOW"}
    assert first["approval_gate"]["tian_brain"]["center"] == "TianBrain"
    assert list_decisions(1)[0]["opportunity_id"] == first["opportunity_id"]


def test_decision_evaluate_requires_login(client):
    response = client.post("/command/decision/evaluate", json={"snapshot": {"store": "京东60店"}})

    assert response.status_code == 401


def test_decision_evaluate_rejects_low_permission(client, viewer_headers):
    response = client.post(
        "/command/decision/evaluate",
        headers=viewer_headers,
        json={"snapshot": {"store": "京东60店", "conversion_change_pct": -0.2}},
    )

    assert response.status_code == 403


def test_decision_evaluate_returns_approval_preview_without_queue(client, owner_headers):
    clear_decisions()
    response = client.post(
        "/command/decision/evaluate",
        headers=owner_headers,
        json={
            "snapshot": {
                "store": "京东60店",
                "conversion_change_pct": -0.2,
                "sales_change_pct": 0,
                "ad_roi_change_pct": 0,
                "product_issue_count": 0,
                "customer_issue_count": 0,
            }
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["decision"]["recommended_strategy"]
    assert body["decision"]["safety"]["requires_approval_center"] is True
    assert body["decision"]["decisions"][0]["can_auto_execute"] is False
    assert body["decision"]["decisions"][0]["approval_gate"]["center"] == "TianShen"

    redis_client = __import__("backend.database", fromlist=["get_redis"]).get_redis()
    assert redis_client.llen(ORCHESTRATOR_QUEUE_NAME) == 0


def test_decision_history_lists_memory(client, owner_headers):
    clear_decisions()
    created = client.post(
        "/command/decision/evaluate",
        headers=owner_headers,
        json={"snapshot": {"store": "京东60店", "sales_change_pct": -0.18}},
    )
    assert created.status_code == 200

    response = client.get("/command/decision/history", headers=owner_headers)

    assert response.status_code == 200
    assert response.json()["decisions"]
    assert response.json()["decisions"][0]["memory_scope"] == "in_process_readonly_decision_memory"
