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


def test_skill_create_review_approve_install_invoke_flow(client, owner_headers, test_db, enable_skill_flags):
    db = test_db()
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

    invoke = client.post(
        f"/api/v2/skills/{skill_id}/invoke",
        headers=owner_headers,
        json={
            "employee_code": "tiancai_data",
            "installation_id": installation_id,
            "task_id": 1,
            "execution_id": 99,
            "trace_id": "trace-skill-test",
            "input_payload": {"query": "天统AI云中台", "limit": 3},
        },
    )
    assert invoke.status_code == 200
    invocation = invoke.json()["invocation"]
    assert invocation["status"] == "执行成功"
    assert invocation["trace_id"] == "trace-skill-test"

    invocation_list = client.get("/api/v2/skills/invocations", headers=owner_headers)
    assert invocation_list.status_code == 200
    assert any(row["invocation_id"] == invocation["invocation_id"] for row in invocation_list.json()["invocations"])

    audit = client.get(f"/api/v2/skills/invocations/{invocation['invocation_id']}/audit", headers=owner_headers)
    assert audit.status_code == 200
    assert audit.json()["audit"]

    cancel = client.post(f"/api/v2/skills/invocations/{invocation['invocation_id']}/cancel", headers=owner_headers)
    assert cancel.status_code == 200
    assert cancel.json()["invocation"]["status"] == "已取消"

    retry = client.post(f"/api/v2/skills/invocations/{invocation['invocation_id']}/retry", headers=owner_headers)
    assert retry.status_code == 200
    assert retry.json()["invocation"]["retry_count"] == 1

    detail = client.get(f"/api/v2/skills/{skill_id}", headers=owner_headers)
    assert detail.status_code == 200
    assert detail.json()["skill"]["skill_code"] == "demo.knowledge.echo"


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
