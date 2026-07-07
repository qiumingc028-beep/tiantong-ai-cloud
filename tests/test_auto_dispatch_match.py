from __future__ import annotations


def test_auto_dispatch_match_recommends_employee_for_normal_task(client, owner_headers):
    response = client.post(
        "/api/auto-dispatch/match",
        headers=owner_headers,
        json={"task_title": "分析新品推广方案", "task_description": "需要输出增长策略和推广建议"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["risk_level"] == "low"
    assert data["recommended_employees"]
    first = data["recommended_employees"][0]
    assert first["employee_code"] == "tiance"
    assert first["employee_name"]
    assert first["match_reason"]
    assert first["risk_level"]


def test_auto_dispatch_match_returns_high_risk_level(client, owner_headers):
    response = client.post(
        "/api/auto-dispatch/match",
        headers=owner_headers,
        json={"task_title": "部署生产环境", "task_description": "docker compose up 并执行 deploy"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["risk_level"] == "critical"
    assert data["recommended_employees"]
    assert data["recommended_employees"][0]["employee_code"] == "tiandun"


def test_auto_dispatch_match_returns_empty_list_without_match(client, owner_headers):
    response = client.post(
        "/api/auto-dispatch/match",
        headers=owner_headers,
        json={"task_title": "蓝色月光随机事项", "task_description": "没有任何任务类型和能力标签"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["task_type"] == "general"
    assert data["recommended_employees"] == []
    assert data["best_employee"] is None


def test_auto_dispatch_match_requires_login_and_permission(client, viewer_headers):
    client.cookies.clear()
    unauthorized = client.post(
        "/api/auto-dispatch/match",
        json={"task_title": "分析新品推广方案", "task_description": "需要策略建议"},
    )
    assert unauthorized.status_code == 401

    forbidden = client.post(
        "/api/auto-dispatch/match",
        headers=viewer_headers,
        json={"task_title": "分析新品推广方案", "task_description": "需要策略建议"},
    )
    assert forbidden.status_code == 403
