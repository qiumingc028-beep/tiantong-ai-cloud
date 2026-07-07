from __future__ import annotations

from backend.employee_growth import (
    analyze_growth_with_tianbrain,
    build_employee_growth_profile,
    build_employee_growth_report,
    distill_growth_knowledge,
)
from backend.knowledge_center import clear_knowledge, list_knowledge
from backend.models import TaskCenterAuditLog, TaskCenterTask
from backend.task_queue import ORCHESTRATOR_QUEUE_NAME


def seed_growth_tasks(test_db, employee_code: str = "tianshang"):
    db = test_db()
    try:
        completed = TaskCenterTask(
            title="优化商品详情页转化",
            description="整理页面卖点并形成复盘",
            status="completed",
            assigned_ai_employee_code=employee_code,
            assigned_ai_employee_name="天商",
        )
        failed = TaskCenterTask(
            title="检查广告预算异常",
            description="广告预算和投放策略需要复盘",
            status="failed",
            assigned_ai_employee_code=employee_code,
            assigned_ai_employee_name="天商",
        )
        pending_risk = TaskCenterTask(
            title="部署商品策略变更",
            description="涉及部署和权限，必须审批",
            status="assigned",
            assigned_ai_employee_code=employee_code,
            assigned_ai_employee_name="天商",
        )
        db.add_all([completed, failed, pending_risk])
        db.flush()
        db.add(
            TaskCenterAuditLog(
                task_id=failed.id,
                action="task_failed",
                from_status="running",
                to_status="failed",
                detail="缺少广告 ROI 数据",
                actor_role="tianjian",
            )
        )
        db.commit()
    finally:
        db.close()


def test_growth_profile_records_task_count_success_failure_risk_and_skill_growth(test_db):
    seed_growth_tasks(test_db)
    db = test_db()
    try:
        profile = build_employee_growth_profile(db, "tianshang")
    finally:
        db.close()

    assert profile["employee_code"] == "tianshang"
    assert profile["completed_task_count"] == 1
    assert profile["failed_task_count"] == 1
    assert profile["success_rate"] == 0.5
    assert profile["failure_reasons"] == ["task#2: 缺少广告 ROI 数据"]
    assert len(profile["risk_records"]) == 2
    assert all(row["requires_tian_shen"] is True for row in profile["risk_records"])
    assert profile["skill_growth"]["can_auto_add_skill"] is False
    assert profile["skill_growth"]["can_auto_expand_permission"] is False
    assert "quality_acceptance" in profile["skill_growth"]["suggested_new_skills"]
    assert profile["safety"]["can_auto_modify_production_rule"] is False


def test_tianbrain_growth_analysis_is_suggestion_only(test_db):
    seed_growth_tasks(test_db)
    db = test_db()
    try:
        profile = build_employee_growth_profile(db, "tianshang")
    finally:
        db.close()
    analysis = analyze_growth_with_tianbrain(profile)

    assert analysis["center"] == "TianBrain"
    assert analysis["success_analysis"]
    assert any("缺少广告 ROI 数据" in row for row in analysis["failure_analysis"])
    assert analysis["prompt_optimization"]["can_auto_update_prompt"] is False
    assert analysis["safety"]["can_auto_modify_production_rule"] is False
    assert analysis["safety"]["can_auto_expand_permission"] is False
    assert all(row["can_auto_apply"] is False for row in analysis["next_optimization"])


def test_tiancang_distillation_previews_knowledge_without_production_rule_change(test_db):
    seed_growth_tasks(test_db)
    db = test_db()
    try:
        profile = build_employee_growth_profile(db, "tianshang")
    finally:
        db.close()
    analysis = analyze_growth_with_tianbrain(profile)
    knowledge = distill_growth_knowledge(profile, analysis)

    assert knowledge["mode"] == "preview_only"
    assert knowledge["knowledge"]["can_auto_store"] is False
    assert knowledge["sop_suggestions"]
    assert knowledge["experience_rules"]
    assert knowledge["safety"]["append_only"] is True
    assert knowledge["safety"]["can_auto_modify_production_rule"] is False
    assert knowledge["safety"]["can_auto_modify_prompt"] is False
    assert knowledge["safety"]["can_auto_expand_permission"] is False


def test_growth_report_can_append_only_to_tiancang_without_queue_or_permission_expansion(test_db):
    clear_knowledge()
    seed_growth_tasks(test_db)
    db = test_db()
    try:
        report = build_employee_growth_report(db, "tianshang", persist_knowledge=True)
    finally:
        db.close()

    assert report["center"] == "AI Employee Growth Center"
    assert report["growth_profile"]["completed_task_count"] == 1
    assert report["tianbrain_analysis"]["center"] == "TianBrain"
    assert report["tiancang_distillation"]["mode"] == "append_only"
    assert report["safety"]["suggestion_only"] is True
    assert report["safety"]["can_auto_modify_production_rule"] is False
    assert report["safety"]["can_auto_expand_permission"] is False
    assert report["safety"]["can_auto_execute"] is False
    assert list_knowledge(limit=10)

    redis_client = __import__("backend.database", fromlist=["get_redis"]).get_redis()
    assert redis_client.llen(ORCHESTRATOR_QUEUE_NAME) == 0


def test_growth_profile_empty_employee_is_safe(test_db):
    db = test_db()
    try:
        report = build_employee_growth_report(db, "new_employee")
    finally:
        db.close()

    assert report["growth_profile"]["completed_task_count"] == 0
    assert report["growth_profile"]["success_rate"] == 0
    assert report["growth_profile"]["failure_reasons"] == ["暂无失败记录"]
    assert report["growth_profile"]["skill_growth"]["suggested_new_skills"]
    assert report["safety"]["can_auto_modify_prompt"] is False
