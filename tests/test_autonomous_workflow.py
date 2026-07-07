from backend.autonomy.business_detector import detect_business_signals
from backend.autonomy.opportunity_engine import build_opportunities
from backend.autonomy.task_monitor import monitor_business_state
from backend.task_queue import ORCHESTRATOR_QUEUE_NAME


def test_business_detector_finds_conversion_decline():
    signals = detect_business_signals(
        {
            "store": "京东60店",
            "conversion_change_pct": -0.2,
            "sales_change_pct": 0,
            "ad_roi_change_pct": 0,
            "product_issue_count": 0,
            "customer_issue_count": 0,
        }
    )

    assert len(signals) == 1
    assert signals[0]["signal_type"] == "conversion_decline"
    assert signals[0]["severity"] == "high"
    assert signals[0]["lifecycle_stage"] == "discovered"


def test_opportunity_engine_builds_multi_agent_lifecycle():
    signals = detect_business_signals({"store": "京东60店", "conversion_change_pct": -0.2})
    opportunities = build_opportunities(signals)

    first = opportunities[0]
    assert first["approval_required"] is True
    assert "tiancai_data" in first["recommended_team"]
    assert "tiantou" in first["recommended_team"]
    assert [row["stage"] for row in first["lifecycle"]] == [
        "discovered",
        "analysis",
        "decision",
        "approval",
        "execution",
        "review",
        "learning",
    ]


def test_task_monitor_connects_command_center_orchestrator_and_safety():
    monitor = monitor_business_state({"store": "京东60店", "sales_change_pct": -0.18})

    assert monitor["mode"] == "autonomous_business_monitor"
    assert monitor["signals"]
    assert monitor["opportunities"]
    assert monitor["requires_command_center"] is True
    assert monitor["requires_orchestrator"] is True
    assert monitor["requires_tian_shen"] is True
    assert monitor["requires_tian_brain"] is True


def test_autonomy_opportunities_requires_login(client):
    response = client.get("/command/autonomy/opportunities")

    assert response.status_code == 401


def test_autonomy_scan_rejects_low_permission(client, viewer_headers):
    response = client.post(
        "/command/autonomy/scan",
        headers=viewer_headers,
        json={"snapshot": {"store": "京东60店", "conversion_change_pct": -0.2}},
    )

    assert response.status_code == 403


def test_autonomy_scan_creates_collaborative_commands(client, owner_headers):
    response = client.post(
        "/command/autonomy/scan",
        headers=owner_headers,
        json={
            "snapshot": {
                "store": "京东60店",
                "conversion_change_pct": -0.2,
                "sales_change_pct": 0,
                "ad_roi_change_pct": 0,
                "product_issue_count": 0,
                "customer_issue_count": 0,
            },
            "auto_create": True,
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["monitor"]["signals"][0]["signal_type"] == "conversion_decline"
    assert data["commands"]
    command = data["commands"][0]
    assert command["parsed"]["task_type"] == "jd_sales_decline_diagnosis"
    assert [step["employee_code"] for step in command["parsed"]["steps"]] == [
        "tiancai_data",
        "tiance_strategy",
        "tianshang",
        "tiantou",
        "tianjian_test",
    ]
    assert all(row["tian_shen"]["allowed"] is True for row in command["dispatches"])

    redis_client = __import__("backend.database", fromlist=["get_redis"]).get_redis()
    assert redis_client.llen(ORCHESTRATOR_QUEUE_NAME) == 5


def test_autonomy_scan_can_preview_without_creating_commands(client, owner_headers):
    response = client.post(
        "/command/autonomy/scan",
        headers=owner_headers,
        json={"snapshot": {"store": "京东60店", "sales_change_pct": -0.18}, "auto_create": False},
    )

    assert response.status_code == 200
    assert response.json()["monitor"]["opportunities"]
    assert response.json()["commands"] == []

    redis_client = __import__("backend.database", fromlist=["get_redis"]).get_redis()
    assert redis_client.llen(ORCHESTRATOR_QUEUE_NAME) == 0
