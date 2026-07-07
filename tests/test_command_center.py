from backend.command_center.task_parser import parse_command
from backend.task_queue import ORCHESTRATOR_QUEUE_NAME


def test_command_parser_builds_six_employee_flow():
    parsed = parse_command("帮我做一个电商利润增长方案", {"channel": "jd"})

    assert parsed["task_type"] == "ecommerce_business_command"
    assert parsed["flow"] == "input_parse_allocate_approve_execute_feedback"
    assert [step["employee_code"] for step in parsed["steps"]] == [
        "tiancai_data",
        "tiance_strategy",
        "tianchuang",
        "tianshang",
        "tianjian_test",
        "tiandun_ops",
    ]
    assert parsed["safety"]["requires_tian_shen"] is True


def test_command_parser_handles_jd_sales_decline():
    parsed = parse_command("分析今天京东60店销量下降原因")

    assert parsed["task_type"] == "jd_sales_decline_diagnosis"
    assert [step["employee_code"] for step in parsed["steps"]] == [
        "tiancai_data",
        "tiance_strategy",
        "tianshang",
        "tiantou",
        "tianjian_test",
    ]
    assert parsed["steps"][0]["role"] == "fetch_sales_data"
    assert parsed["steps"][3]["role"] == "check_ads"


def test_command_submit_requires_login(client):
    response = client.post("/command/submit", json={"command": "帮我做电商增长"})

    assert response.status_code == 401


def test_command_submit_rejects_low_permission(client, viewer_headers):
    response = client.post("/command/submit", headers=viewer_headers, json={"command": "帮我做电商增长"})

    assert response.status_code == 403


def test_command_submit_queues_all_steps(client, owner_headers):
    response = client.post(
        "/command/submit",
        headers=owner_headers,
        json={"command": "帮我做一个电商利润增长方案", "metadata": {"priority": "normal"}},
    )

    assert response.status_code == 200
    data = response.json()["command"]
    assert data["command_id"]
    assert data["status"] == "submitted"
    assert len(data["parsed"]["steps"]) == 6
    assert len(data["event_ids"]) == 6
    assert all(row["queued"] is True for row in data["dispatches"])
    assert all(row["tian_shen"]["allowed"] is True for row in data["dispatches"])

    redis_client = __import__("backend.database", fromlist=["get_redis"]).get_redis()
    assert redis_client.llen(ORCHESTRATOR_QUEUE_NAME) == 6


def test_command_status_and_history(client, owner_headers):
    created = client.post("/command/submit", headers=owner_headers, json={"command": "帮我生成内容增长方案"})
    command_id = created.json()["command"]["command_id"]

    status = client.get("/command/status", headers=owner_headers, params={"command_id": command_id})
    history = client.get("/command/history", headers=owner_headers)

    assert status.status_code == 200
    assert status.json()["command"]["command_id"] == command_id
    assert len(status.json()["command"]["events"]) == 6
    assert history.status_code == 200
    assert any(row["command_id"] == command_id for row in history.json()["commands"])


def test_command_operations_and_logs(client, owner_headers):
    created = client.post("/command/submit", headers=owner_headers, json={"command": "分析今天京东60店销量下降原因"})
    assert created.status_code == 200

    operations = client.get("/command/operations", headers=owner_headers)
    logs = client.get("/command/logs", headers=owner_headers)

    assert operations.status_code == 200
    data = operations.json()["operations"]
    assert set(data["summary"]) >= {"current_tasks", "today_completed", "success_rate", "risk_count"}
    assert {row["employee_code"] for row in data["employee_statuses"]} >= {
        "tiancai_data",
        "tiance_strategy",
        "tianshang",
        "tiantou",
        "tianjian_test",
        "tian_shen",
    }
    assert logs.status_code == 200
    first_log = logs.json()["logs"][0]
    assert set(first_log) >= {"employee_code", "executed_at", "tool", "result", "status", "failure_reason"}


def test_command_status_404(client, owner_headers):
    response = client.get("/command/status", headers=owner_headers, params={"command_id": "missing"})

    assert response.status_code == 404


def test_command_center_does_not_bypass_tian_shen_red(client, owner_headers):
    response = client.post(
        "/command/submit",
        headers=owner_headers,
        json={"command": "请执行 git push origin main 并上线"},
    )

    assert response.status_code == 200
    command = response.json()["command"]
    assert len(command["event_ids"]) == 0
    assert command["dispatches"]
    assert all(row["queued"] is False for row in command["dispatches"])
    assert all(row["tian_shen"]["decision"] == "RED" for row in command["dispatches"])
