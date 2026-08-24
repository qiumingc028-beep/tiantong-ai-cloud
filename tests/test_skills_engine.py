from __future__ import annotations

import pytest

from backend.models import AiEmployee
from backend.skills_engine.schemas import SkillCreatePayload, SkillManifest, SkillReviewPayload, SkillVersionCreatePayload


SKILL_LIST_API = "/api/v2/skills"


@pytest.fixture()
def enable_skill_flags(monkeypatch):
    def flag(name: str) -> bool:
        return name in {
            "SKILLS_ENGINE_ENABLED",
            "SKILL_INSTALLATION_ENABLED",
            "SKILL_INVOCATION_ENABLED",
            "PUBLIC_RESEARCH_ENABLED",
            "BROWSER_READONLY_ENABLED",
            "KNOWLEDGE_LOCAL_SEARCH_ENABLED",
        }

    monkeypatch.setattr("backend.skills_engine.permissions.get_flag", flag)
    monkeypatch.setattr("backend.skills_engine.service.get_flag", flag)
    return flag


def test_skill_manifest_rejects_high_risk_executors():
    with pytest.raises(ValueError):
        SkillManifest(
            skill_code="demo.shell",
            version="1.0.0",
            chinese_name="危险技能",
            chinese_description="演示",
            entrypoint="mock",
            skill_type="其他",
            risk_level="低风险",
            required_capabilities=["knowledge.local.search"],
            required_permissions=["skills.read"],
            shell_access=True,
        )


def test_skill_center_requires_feature_flag(client, owner_headers):
    response = client.get(SKILL_LIST_API, headers=owner_headers)
    assert response.status_code == 403


def test_skill_center_lists_seeded_mock_skills(client, owner_headers, enable_skill_flags):
    response = client.get(SKILL_LIST_API, headers=owner_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["readonly"] is True
    assert data["summary"]["total"] >= 2
    codes = {row["skill_code"] for row in data["skills"]}
    assert "research.public.report_organize" in codes
    assert "knowledge.local.search" in codes


def test_skill_create_review_approve_install_invoke_flow(
    client,
    owner_headers,
    admin_headers,
    test_db,
    enable_skill_flags,
):
    import json

    from backend.models import EmployeeLog, TaskCenterResult, TaskCenterTask, User
    from backend.skills_engine.models import (
        Skill,
        SkillEmployeePermission,
        SkillInstallation,
        SkillInvocation,
        SkillReview,
        SkillVersion,
    )
    from backend.skills_engine.registry import audit_employee_log
    from backend.task_center_ownership import (
        SESSION_USER_KEY,
        TASK_OWNERSHIP_FIELDS,
        bind_task_ownership,
        owned_task_or_none,
    )
    from tests.task_center_ownership_helpers import bind_pending_tasks, owner_db

    client.cookies.clear()
    db = owner_db(test_db)
    owner = db.info[SESSION_USER_KEY]

    tracked_models = (
        Skill,
        SkillVersion,
        SkillEmployeePermission,
        SkillInstallation,
        SkillInvocation,
        SkillReview,
        EmployeeLog,
        TaskCenterTask,
        TaskCenterResult,
    )

    def business_state():
        db.expire_all()
        return {
            model.__tablename__: tuple(
                tuple(getattr(row, column.name) for column in model.__table__.columns)
                for row in db.query(model).order_by(model.id.asc()).all()
            )
            for model in tracked_models
        }

    credentials = tuple(
        credential
        for headers in (owner_headers, admin_headers)
        if (credential := headers.get("Authorization", "").removeprefix("Bearer ").strip())
    )

    def assert_credential_absent(*values):
        serialized = json.dumps(values, ensure_ascii=False, default=str)
        if any(credential in serialized for credential in credentials):
            pytest.fail("credential exposure")

    employee = db.query(AiEmployee).filter(AiEmployee.employee_code == "tiancai_data").one_or_none()
    if employee is None:
        employee = AiEmployee(
            employee_code="tiancai_data",
            employee_name="天采：公开数据研究",
            legion="数据资产军团",
            duty="公开信息研究",
            status="active",
            task_types='["data_collection"]',
            default_permissions='["skills.read"]',
            is_legacy=False,
            sort_order=140,
        )
        db.add(employee)
        db.commit()
        db.refresh(employee)

    owner_task = TaskCenterTask(
        title="owner skill invocation task",
        status="accepted",
        assigned_ai_employee_code="tiancai_data",
        assigned_ai_employee_name=employee.employee_name,
        created_by_id=owner.id,
    )
    db.add(owner_task)
    bind_pending_tasks(db)

    foreign_user = db.query(User).filter(User.username == "admin").one()
    foreign_task = TaskCenterTask(
        title="foreign skill invocation sentinel",
        status="accepted",
        assigned_ai_employee_code="tiancai_data",
        assigned_ai_employee_name=employee.employee_name,
        created_by_id=foreign_user.id,
    )
    bind_task_ownership(db, foreign_task, user=foreign_user)
    db.add(foreign_task)
    db.commit()
    db.refresh(owner_task)
    db.refresh(foreign_task)

    assert owner_task.id != foreign_task.id
    assert owner_task.assigned_ai_employee_code == "tiancai_data"
    assert all(getattr(owner_task, field) not in (None, "") for field in TASK_OWNERSHIP_FIELDS)
    assert owner_task.requester_id == owner.id
    assert foreign_task.requester_id == foreign_user.id
    assert owned_task_or_none(db, user=owner, task_id=owner_task.id).id == owner_task.id
    assert owned_task_or_none(db, user=owner, task_id=foreign_task.id) is None

    manifest = {
        "skill_code": "demo.knowledge.echo",
        "version": "1.0.0",
        "chinese_name": "知识回显技能",
        "chinese_description": "将输入的知识查询整理为结构化结果。",
        "entrypoint": "mock_executor",
        "skill_type": "知识检索",
        "risk_level": "低风险",
        "required_capabilities": ["knowledge.local.search"],
        "required_permissions": ["skills.read"],
        "allowed_employee_codes": ["tiancai_data"],
        "input_schema": {"type": "object"},
        "output_schema": {"type": "object"},
        "timeout_seconds": 20,
        "max_retries": 1,
        "network_access": False,
        "filesystem_access": False,
        "browser_access": False,
        "computer_access": False,
        "mobile_access": False,
        "shell_access": False,
        "secrets_required": False,
        "audit_required": True,
        "required_feature_flags": ["KNOWLEDGE_LOCAL_SEARCH_ENABLED"],
        "checksum": "demo-checksum",
        "signature_status": "已验证",
    }

    create_response = client.post(
        SKILL_LIST_API,
        headers=owner_headers,
        json={
            "skill_code": "demo.knowledge.echo",
            "chinese_name": "知识回显技能",
            "chinese_description": "将输入的知识查询整理为结构化结果。",
            "skill_type": "知识检索",
            "category": "测试技能",
            "risk_level": "低风险",
            "publisher_type": "内部",
            "publisher_name": "天统AI云中台",
            "source_type": "内部定义",
            "source_url": "about:blank",
            "license": "Tiantong Internal",
            "checksum": "demo-checksum",
            "signature_status": "已验证",
            "enabled": False,
            "deprecated": False,
            "status": "草稿",
            "manifest": manifest,
        },
    )
    assert create_response.status_code == 200
    skill_id = create_response.json()["skill"]["skill_id"]

    review = client.post(f"/api/v2/skills/{skill_id}/submit-review", headers=owner_headers, json={
        "decision": "需要审核",
        "review_comment": "先审核再发布",
        "source_check_result": "通过",
        "sensitivity_check_result": "通过",
    })
    assert review.status_code == 200
    assert review.json()["review"]["decision"] == "需要审核"
    review_id = review.json()["review"]["review_id"]

    approve = client.post(f"/api/v2/skills/{skill_id}/approve", headers=owner_headers)
    assert approve.status_code == 200

    permission = client.post(
        f"/api/v2/skills/{skill_id}/permissions",
        headers=owner_headers,
        json={"employee_code": "tiancai_data", "permission_scope": "employee", "allow": True, "risk_limit": "低风险", "environment_limit": "development,test"},
    )
    assert permission.status_code == 200

    install = client.post(
        f"/api/v2/skills/{skill_id}/install",
        headers=owner_headers,
        json={"employee_code": "tiancai_data", "department_id": "数据资产军团", "configuration": {"mode": "safe"}},
    )
    assert install.status_code == 200
    installation_id = install.json()["installation"]["installation_id"]

    enable = client.post(
        f"/api/v2/skills/{skill_id}/enable",
        headers=owner_headers,
        json={"employee_code": "tiancai_data", "department_id": "数据资产军团", "configuration": {}},
    )
    assert enable.status_code == 200
    assert enable.json()["installation"]["status"] == "已启用"

    skill = db.get(Skill, skill_id)
    assert skill is not None
    assert skill.current_version_id is not None
    foreign_before = business_state()
    blocked_foreign_invoke = client.post(
        f"/api/v2/skills/{skill_id}/invoke",
        headers=owner_headers,
        json={
            "employee_code": "tiancai_data",
            "installation_id": installation_id,
            "task_id": foreign_task.id,
            "execution_id": 98,
            "trace_id": "trace-skill-foreign",
            "input_payload": {"query": "foreign sentinel", "limit": 1},
        },
    )
    assert blocked_foreign_invoke.status_code == 404
    assert blocked_foreign_invoke.json() == {"detail": "task not found"}
    assert "foreign skill invocation sentinel" not in blocked_foreign_invoke.text
    assert business_state() == foreign_before

    invocation_count_before = db.query(SkillInvocation).count()
    result_count_before = db.query(TaskCenterResult).count()
    audit_count_before = db.query(EmployeeLog).count()
    invoke_state_before = business_state()

    foreign_invoke = client.post(
        f"/api/v2/skills/{skill_id}/invoke",
        headers=admin_headers,
        json={
            "employee_code": "tiancai_data",
            "installation_id": installation_id,
            "task_id": foreign_task.id,
            "execution_id": 98,
            "trace_id": "trace-skill-foreign-sentinel",
            "input_payload": {"query": "foreign sentinel", "limit": 1},
        },
    )
    assert foreign_invoke.status_code == 200
    foreign_invocation_data = foreign_invoke.json()["invocation"]

    owner_invoke_a = client.post(
        f"/api/v2/skills/{skill_id}/invoke",
        headers=owner_headers,
        json={
            "employee_code": "tiancai_data",
            "installation_id": installation_id,
            "task_id": owner_task.id,
            "execution_id": 99,
            "trace_id": "trace-skill-test",
            "input_payload": {"query": "天统AI云中台", "limit": 3},
        },
    )
    assert owner_invoke_a.status_code == 200
    invocation_a = owner_invoke_a.json()["invocation"]
    assert invocation_a["status"] == "执行成功"
    assert invocation_a["trace_id"] == "trace-skill-test"
    assert invocation_a["task_id"] == owner_task.id

    owner_invoke_b = client.post(
        f"/api/v2/skills/{skill_id}/invoke",
        headers=owner_headers,
        json={
            "employee_code": "tiancai_data",
            "installation_id": installation_id,
            "task_id": owner_task.id,
            "execution_id": 100,
            "trace_id": "trace-skill-test-b",
            "input_payload": {"query": "天统AI云中台 B", "limit": 2},
        },
    )
    assert owner_invoke_b.status_code == 200
    invocation_b = owner_invoke_b.json()["invocation"]
    assert invocation_b["status"] == "执行成功"
    assert invocation_b["trace_id"] == "trace-skill-test-b"
    assert invocation_b["task_id"] == owner_task.id

    db.expire_all()
    persisted_a = db.get(SkillInvocation, invocation_a["invocation_id"])
    persisted_b = db.get(SkillInvocation, invocation_b["invocation_id"])
    foreign_invocation = db.get(SkillInvocation, foreign_invocation_data["invocation_id"])
    assert persisted_a is not None and persisted_b is not None and foreign_invocation is not None
    assert persisted_a.task_id == persisted_b.task_id == owner_task.id
    assert persisted_a.employee_id == persisted_b.employee_id == employee.id
    assert foreign_invocation.task_id == foreign_task.id
    assert db.query(SkillInvocation).count() == invocation_count_before + 3
    assert db.query(TaskCenterResult).count() == result_count_before + 3
    assert db.query(EmployeeLog).count() == audit_count_before + 3
    assert db.query(SkillInvocation).filter(SkillInvocation.trace_id == "trace-skill-foreign").count() == 0
    assert db.query(TaskCenterResult).filter(TaskCenterResult.task_id == foreign_task.id).count() == 1
    owner_results = db.query(TaskCenterResult).filter(TaskCenterResult.task_id == owner_task.id).all()
    assert len(owner_results) == 2
    assert {row.ai_employee_code for row in owner_results} == {"tiancai_data"}

    incomplete_task = TaskCenterTask(
        title="incomplete ownership skill invocation sentinel",
        status="accepted",
        assigned_ai_employee_code="tiancai_data",
        assigned_ai_employee_name=employee.employee_name,
        created_by_id=owner.id,
    )
    taskless_invocation = SkillInvocation(
        skill_id=skill_id,
        skill_version_id=skill.current_version_id,
        installation_id=installation_id,
        employee_id=employee.id,
        task_id=None,
        status="执行成功",
        trace_id="trace-skill-taskless-sentinel",
    )
    db.add_all([incomplete_task, taskless_invocation])
    db.flush()
    incomplete_invocation = SkillInvocation(
        skill_id=skill_id,
        skill_version_id=skill.current_version_id,
        installation_id=installation_id,
        employee_id=employee.id,
        task_id=incomplete_task.id,
        status="执行成功",
        trace_id="trace-skill-incomplete-sentinel",
    )
    db.add(incomplete_invocation)
    db.flush()
    historical_null_audit = audit_employee_log(
        db,
        user_id=owner.id,
        action="skill_invocation",
        detail="historical null invocation audit",
        skill_id=skill_id,
    )
    db.commit()
    db.refresh(taskless_invocation)
    db.refresh(incomplete_invocation)
    db.refresh(historical_null_audit)
    assert historical_null_audit.skill_invocation_id is None

    invoke_state_after = business_state()
    assert invoke_state_after != invoke_state_before

    all_invocation_ids = {
        invocation_a["invocation_id"],
        invocation_b["invocation_id"],
        foreign_invocation.id,
        taskless_invocation.id,
        incomplete_invocation.id,
    }
    missing_invocation_id = max(all_invocation_ids) + 100_000
    get_state_before = business_state()
    invocation_list = client.get("/api/v2/skills/invocations", headers=owner_headers)
    assert invocation_list.status_code == 200
    owner_list_ids = {row["invocation_id"] for row in invocation_list.json()["invocations"]}
    assert owner_list_ids & all_invocation_ids == {
        invocation_a["invocation_id"],
        invocation_b["invocation_id"],
    }

    invocation_a_detail = client.get(
        f"/api/v2/skills/invocations/{invocation_a['invocation_id']}",
        headers=owner_headers,
    )
    invocation_b_detail = client.get(
        f"/api/v2/skills/invocations/{invocation_b['invocation_id']}",
        headers=owner_headers,
    )
    assert invocation_a_detail.status_code == invocation_b_detail.status_code == 200
    assert invocation_a_detail.json()["invocation"]["invocation_id"] == invocation_a["invocation_id"]
    assert invocation_b_detail.json()["invocation"]["invocation_id"] == invocation_b["invocation_id"]

    audit_a = client.get(
        f"/api/v2/skills/invocations/{invocation_a['invocation_id']}/audit",
        headers=owner_headers,
    )
    audit_b = client.get(
        f"/api/v2/skills/invocations/{invocation_b['invocation_id']}/audit",
        headers=owner_headers,
    )
    foreign_audit_as_admin = client.get(
        f"/api/v2/skills/invocations/{foreign_invocation.id}/audit",
        headers=admin_headers,
    )
    assert audit_a.status_code == audit_b.status_code == foreign_audit_as_admin.status_code == 200
    audit_a_rows = db.query(EmployeeLog).filter(
        EmployeeLog.skill_invocation_id == invocation_a["invocation_id"],
    ).all()
    audit_b_rows = db.query(EmployeeLog).filter(
        EmployeeLog.skill_invocation_id == invocation_b["invocation_id"],
    ).all()
    foreign_audit_rows = db.query(EmployeeLog).filter(
        EmployeeLog.skill_invocation_id == foreign_invocation.id,
    ).all()
    assert len(audit_a_rows) == len(audit_b_rows) == len(foreign_audit_rows) == 1
    assert {row["log_id"] for row in audit_a.json()["audit"]} == {audit_a_rows[0].id}
    assert {row["log_id"] for row in audit_b.json()["audit"]} == {audit_b_rows[0].id}
    assert {row["log_id"] for row in foreign_audit_as_admin.json()["audit"]} == {
        foreign_audit_rows[0].id,
    }
    assert not (
        {audit_b_rows[0].id, foreign_audit_rows[0].id, historical_null_audit.id}
        & {row["log_id"] for row in audit_a.json()["audit"]}
    )

    missing_detail = client.get(
        f"/api/v2/skills/invocations/{missing_invocation_id}",
        headers=owner_headers,
    )
    missing_audit = client.get(
        f"/api/v2/skills/invocations/{missing_invocation_id}/audit",
        headers=owner_headers,
    )
    assert missing_detail.status_code == missing_audit.status_code == 404
    assert missing_detail.json() == missing_audit.json() == {"detail": "调用记录不存在"}
    hidden_invocations = (foreign_invocation, taskless_invocation, incomplete_invocation)
    hidden_get_responses = []
    for hidden in hidden_invocations:
        hidden_detail = client.get(
            f"/api/v2/skills/invocations/{hidden.id}",
            headers=owner_headers,
        )
        hidden_audit = client.get(
            f"/api/v2/skills/invocations/{hidden.id}/audit",
            headers=owner_headers,
        )
        assert hidden_detail.status_code == hidden_audit.status_code == 404
        assert hidden_detail.json() == hidden_audit.json() == missing_detail.json()
        hidden_get_responses.extend((hidden_detail, hidden_audit))

    foreign_invocation_list = client.get("/api/v2/skills/invocations", headers=admin_headers)
    assert foreign_invocation_list.status_code == 200
    foreign_list_ids = {row["invocation_id"] for row in foreign_invocation_list.json()["invocations"]}
    assert foreign_list_ids & all_invocation_ids == {foreign_invocation.id}

    detail = client.get(f"/api/v2/skills/{skill_id}", headers=owner_headers)
    assert detail.status_code == 200
    assert detail.json()["skill"]["skill_code"] == "demo.knowledge.echo"
    assert business_state() == get_state_before

    foreign_write_before = business_state()
    missing_cancel = client.post(
        f"/api/v2/skills/invocations/{missing_invocation_id}/cancel",
        headers=owner_headers,
    )
    missing_retry = client.post(
        f"/api/v2/skills/invocations/{missing_invocation_id}/retry",
        headers=owner_headers,
    )
    assert missing_cancel.status_code == missing_retry.status_code == 404
    assert missing_cancel.json() == missing_retry.json() == {"detail": "调用记录不存在"}
    hidden_write_responses = []
    for hidden in hidden_invocations:
        hidden_cancel = client.post(
            f"/api/v2/skills/invocations/{hidden.id}/cancel",
            headers=owner_headers,
        )
        hidden_retry = client.post(
            f"/api/v2/skills/invocations/{hidden.id}/retry",
            headers=owner_headers,
        )
        assert hidden_cancel.status_code == hidden_retry.status_code == 404
        assert hidden_cancel.json() == hidden_retry.json() == missing_cancel.json()
        hidden_write_responses.extend((hidden_cancel, hidden_retry))
    assert business_state() == foreign_write_before

    cancel = client.post(
        f"/api/v2/skills/invocations/{invocation_a['invocation_id']}/cancel",
        headers=owner_headers,
    )
    assert cancel.status_code == 200
    assert cancel.json()["invocation"]["status"] == "已取消"

    retry = client.post(
        f"/api/v2/skills/invocations/{invocation_a['invocation_id']}/retry",
        headers=owner_headers,
    )
    assert retry.status_code == 200
    assert retry.json()["invocation"]["retry_count"] == 1

    owner_mutation_state = business_state()
    audit_a_after_mutations = client.get(
        f"/api/v2/skills/invocations/{invocation_a['invocation_id']}/audit",
        headers=owner_headers,
    )
    assert audit_a_after_mutations.status_code == 200
    assert business_state() == owner_mutation_state
    assert {row["action"] for row in audit_a_after_mutations.json()["audit"]} == {
        "skill_invocation",
        "skill_invocation_cancelled",
        "skill_invocation_retried",
    }
    assert len(audit_a_after_mutations.json()["audit"]) == 3

    db.expire_all()
    assert db.query(Skill).filter(Skill.skill_code == "demo.knowledge.echo").count() == 1
    assert db.query(SkillVersion).filter(SkillVersion.skill_id == skill_id).count() == 1
    skill_reviews = db.query(SkillReview).filter(SkillReview.skill_id == skill_id).all()
    assert len(skill_reviews) == 1
    assert skill_reviews[0].id == review_id
    assert skill_reviews[0].reviewer_id == owner.id
    assert skill_reviews[0].decision == "需要审核"
    assert db.query(SkillEmployeePermission).filter(
        SkillEmployeePermission.skill_id == skill_id,
        SkillEmployeePermission.employee_id == employee.id,
        SkillEmployeePermission.permission_scope == "employee",
    ).count() == 1
    assert db.query(SkillInstallation).filter(
        SkillInstallation.skill_id == skill_id,
        SkillInstallation.employee_id == employee.id,
    ).count() == 1
    for trace_id in (
        "trace-skill-test",
        "trace-skill-test-b",
        "trace-skill-foreign-sentinel",
        "trace-skill-taskless-sentinel",
        "trace-skill-incomplete-sentinel",
    ):
        assert db.query(SkillInvocation).filter(
            SkillInvocation.skill_id == skill_id,
            SkillInvocation.trace_id == trace_id,
        ).count() == 1
    assert db.query(TaskCenterTask).filter(TaskCenterTask.id == owner_task.id).count() == 1
    assert db.query(TaskCenterTask).filter(TaskCenterTask.id == foreign_task.id).count() == 1
    assert db.query(TaskCenterTask).filter(TaskCenterTask.id == incomplete_task.id).count() == 1
    assert db.query(TaskCenterResult).filter(TaskCenterResult.task_id == owner_task.id).count() == 2
    assert db.query(TaskCenterResult).filter(TaskCenterResult.task_id == foreign_task.id).count() == 1
    exact_invocation_audits = db.query(EmployeeLog).filter(
        EmployeeLog.skill_invocation_id.in_(
            (
                invocation_a["invocation_id"],
                invocation_b["invocation_id"],
                foreign_invocation.id,
            )
        ),
    ).all()
    assert len(exact_invocation_audits) == 5
    assert len({row.id for row in exact_invocation_audits}) == 5
    assert len([row for row in exact_invocation_audits if row.skill_invocation_id == persisted_a.id]) == 3
    assert len([row for row in exact_invocation_audits if row.skill_invocation_id == persisted_b.id]) == 1
    assert len([row for row in exact_invocation_audits if row.skill_invocation_id == foreign_invocation.id]) == 1
    assert db.query(EmployeeLog).filter(
        EmployeeLog.id == historical_null_audit.id,
        EmployeeLog.skill_invocation_id.is_(None),
    ).count() == 1
    assert db.query(EmployeeLog).filter(
        EmployeeLog.skill_invocation_id.in_((taskless_invocation.id, incomplete_invocation.id)),
    ).count() == 0
    assert foreign_task.title not in json.dumps(
        [owner_invoke_a.json(), owner_invoke_b.json(), invocation_list.json(), audit_a.json(), detail.json()],
        ensure_ascii=False,
    )
    assert_credential_absent(
        create_response.text,
        review.text,
        approve.text,
        permission.text,
        install.text,
        enable.text,
        blocked_foreign_invoke.text,
        foreign_invoke.text,
        owner_invoke_a.text,
        owner_invoke_b.text,
        invocation_list.text,
        invocation_a_detail.text,
        invocation_b_detail.text,
        audit_a.text,
        audit_b.text,
        foreign_audit_as_admin.text,
        missing_detail.text,
        missing_audit.text,
        *(response.text for response in hidden_get_responses),
        foreign_invocation_list.text,
        detail.text,
        missing_cancel.text,
        missing_retry.text,
        *(response.text for response in hidden_write_responses),
        cancel.text,
        retry.text,
        audit_a_after_mutations.text,
        business_state(),
    )


def test_skill_center_health_and_employee_link(client, owner_headers, enable_skill_flags):
    health = client.get("/api/v2/skills-engine/health", headers=owner_headers)
    assert health.status_code == 200
    assert health.json()["ok"] is True
    assert "feature_flags" in health.json()
    assert "SKILLS_ENGINE_ENABLED" in health.json()["feature_flags"]

    employee = client.get("/api/v2/skills/employees/tiancai_data", headers=owner_headers)
    assert employee.status_code == 200
    assert employee.json()["employee_code"] == "tiancai_data"
    assert isinstance(employee.json()["skills"], list)


def test_skill_center_disabled_feature_flag_blocks_api(client, owner_headers, monkeypatch):
    monkeypatch.setattr("backend.skills_engine.permissions.get_flag", lambda name: False)
    monkeypatch.setattr("backend.skills_engine.service.get_flag", lambda name: False)
    response = client.get(SKILL_LIST_API, headers=owner_headers)
    assert response.status_code == 403
