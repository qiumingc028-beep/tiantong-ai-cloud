from backend.learning_center import analyze_execution, optimize_prompt_suggestions, score_employees
from backend.task_queue import ORCHESTRATOR_QUEUE_NAME


SAMPLE_LOGS = [
    {
        "employee_code": "tiancai_data",
        "role": "fetch_sales_data",
        "status": "completed",
        "result": {"rows": 20},
        "failure_reason": "",
        "risk_decision": "GREEN",
    },
    {
        "employee_code": "tiance_strategy",
        "role": "analyze_decline_strategy",
        "status": "failed",
        "result": {},
        "failure_reason": "缺少广告数据",
        "risk_decision": "YELLOW",
    },
]


def test_execution_analyzer_summarizes_goal_process_result_and_reasons():
    analysis = analyze_execution({"goal": "分析京东60店销量下降", "logs": SAMPLE_LOGS})

    assert analysis["goal"] == "分析京东60店销量下降"
    assert analysis["total_steps"] == 2
    assert analysis["successful_steps"] == 1
    assert analysis["failed_steps"] == 1
    assert analysis["risk_steps"] == 1
    assert analysis["status"] == "failed"
    assert analysis["completion_rate"] == 0.5
    assert analysis["failure_reasons"] == ["tiance_strategy: 缺少广告数据"]
    assert analysis["can_auto_update_prompt"] is False


def test_employee_score_rates_completion_accuracy_risk_and_efficiency():
    scores = score_employees(SAMPLE_LOGS)
    by_employee = {row["employee_code"]: row for row in scores}

    assert by_employee["tiancai_data"]["completion_rate"] == 1
    assert by_employee["tiancai_data"]["risk_rate"] == 0
    assert by_employee["tiance_strategy"]["completion_rate"] == 0
    assert by_employee["tiance_strategy"]["risk_rate"] == 1
    assert by_employee["tiance_strategy"]["overall_score"] < by_employee["tiancai_data"]["overall_score"]


def test_prompt_optimizer_is_suggestion_only():
    analysis = analyze_execution({"goal": "分析京东60店销量下降", "logs": SAMPLE_LOGS})
    scores = score_employees(SAMPLE_LOGS)
    prompt = optimize_prompt_suggestions(analysis, scores, SAMPLE_LOGS)

    assert prompt["failed_case_count"] == 1
    assert prompt["risky_case_count"] == 1
    assert prompt["prompt_update_mode"] == "suggestion_only"
    assert prompt["requires_tian_shen_approval"] is True
    assert prompt["can_auto_update_prompt"] is False
    assert prompt["can_modify_production_prompt"] is False
    assert any(row["suggestion_code"] == "add_safety_gate" for row in prompt["optimization_suggestions"])


def test_learning_analyze_requires_login(client):
    response = client.post("/command/learning/analyze", json={"goal": "复盘", "logs": SAMPLE_LOGS})

    assert response.status_code == 401


def test_learning_analyze_rejects_low_permission(client, viewer_headers):
    response = client.post(
        "/command/learning/analyze",
        headers=viewer_headers,
        json={"goal": "复盘", "logs": SAMPLE_LOGS},
    )

    assert response.status_code == 403


def test_learning_analyze_returns_review_only_report_without_queue(client, owner_headers):
    response = client.post(
        "/command/learning/analyze",
        headers=owner_headers,
        json={"goal": "分析京东60店销量下降", "logs": SAMPLE_LOGS},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["center"] == "TianWu AI Learning Center"
    assert body["analysis"]["status"] == "failed"
    assert body["employee_scores"]
    assert body["prompt_optimization"]["can_auto_update_prompt"] is False
    assert body["prompt_optimization"]["can_modify_production_prompt"] is False
    assert body["approval_gate"]["center"] == "TianShen"
    assert body["approval_gate"]["decision"] == "YELLOW"
    assert body["safety"]["review_only"] is True

    redis_client = __import__("backend.database", fromlist=["get_redis"]).get_redis()
    assert redis_client.llen(ORCHESTRATOR_QUEUE_NAME) == 0


def test_learning_analyze_can_use_command_history(client, owner_headers):
    created = client.post("/command/submit", headers=owner_headers, json={"command": "分析今天京东60店销量下降原因"})
    assert created.status_code == 200
    command_id = created.json()["command"]["command_id"]

    response = client.post("/command/learning/analyze", headers=owner_headers, json={"command_id": command_id})

    assert response.status_code == 200
    body = response.json()
    assert body["execution"]["command_id"] == command_id
    assert body["analysis"]["total_steps"] == 5
    assert body["prompt_optimization"]["prompt_update_mode"] == "suggestion_only"


def test_learning_analyze_missing_command_returns_404(client, owner_headers):
    response = client.post("/command/learning/analyze", headers=owner_headers, json={"command_id": "missing"})

    assert response.status_code == 404
