def test_architecture_completed_recommends_backend_without_blocker(client, owner_headers):
    response = client.post(
        "/api/orchestrator/analyze-reply",
        headers=owner_headers,
        json={
            "reply_text": (
                "你是【天工：系统架构中心】。\n"
                "现在执行《天统AI公司 V1 Sprint 5》的架构设计任务。\n"
                "架构设计已完成，数据库表、API、权限边界、安全边界均已确认。\n"
                "测试通过，可以进入下一阶段。"
            ),
            "context": {"sprint": "Sprint 5"},
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["detected_employee"]["employee_code"] == "tiangong"
    assert data["detected_stage"] == "architecture"
    assert data["completion_status"] == "completed"
    assert data["has_blocker"] is False
    assert data["needs_fix"] is False
    assert data["blockers"] == []
    assert data["recommended_next"]["codex"] == "tianwang"
    assert data["recommended_next"]["target_codex"] == "tianwang"
    assert data["recommended_next"]["recommended_action"] == "backend_development"


def test_test_failure_still_needs_fix_and_does_not_continue(client, owner_headers):
    response = client.post(
        "/api/orchestrator/analyze-reply",
        headers=owner_headers,
        json={"reply_text": "天工架构设计测试失败，验收不通过，需要修复。", "context": {"sprint": "Sprint 5"}},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["needs_fix"] is True
    assert data["has_blocker"] is True
    assert data["recommended_next"]["target_codex"] != "tianwang"
    assert data["recommended_next"]["recommended_action"] != "backend_development"


def test_deploy_failure_still_blocks(client, owner_headers):
    response = client.post(
        "/api/orchestrator/analyze-reply",
        headers=owner_headers,
        json={"reply_text": "天盾部署失败，backend unhealthy，无法继续。", "context": {"sprint": "Sprint 5"}},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["has_blocker"] is True
    assert any(item["type"] == "deploy_failure" for item in data["blockers"])
    assert all("message" in item for item in data["blockers"])


def test_boss_confirmation_requires_manual_review(client, owner_headers):
    response = client.post(
        "/api/orchestrator/analyze-reply",
        headers=owner_headers,
        json={"reply_text": "天工架构设计需要老板确认后再继续。", "context": {"sprint": "Sprint 5"}},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["has_blocker"] is True
    assert data["manual_review_required"] is True
