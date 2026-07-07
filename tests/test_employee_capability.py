from backend.employee_capability import get_employee_profile, get_skill, list_employee_profiles, list_skills, match_employee_for_task
from backend.knowledge_center import clear_knowledge, learn_from_execution
from backend.task_queue import ORCHESTRATOR_QUEUE_NAME


def seed_learning_knowledge():
    clear_knowledge()
    learn_from_execution(
        {
            "analysis": {
                "goal": "京东60店转化下降复盘",
                "status": "failed",
                "result_summary": "广告数据缺失导致策略判断不足。",
                "learning_loop": ["task", "execution", "evaluation", "learning", "optimization", "next_run"],
                "success_reasons": ["天采补齐订单数据"],
                "failure_reasons": ["缺少广告数据"],
            },
            "employee_scores": [{"employee_code": "tiantou", "overall_score": 80}],
            "prompt_optimization": {"optimization_suggestions": []},
        }
    )


def test_employee_profile_contains_identity_capability_skill_and_permission():
    profile = get_employee_profile("tianshang")

    assert profile["employee_code"] == "tianshang"
    assert profile["employee_name"]
    assert "ecommerce_operation" in profile["skills"]
    assert "product_optimization" in profile["capability_tags"]
    assert profile["permissions"]
    assert profile["can_expand_permission"] is False
    assert profile["requires_tian_shen_for_high_risk_skill"] is True


def test_skill_registry_describes_inputs_outputs_and_use_cases():
    skills = list_skills()
    skill = get_skill("ad_performance_check")

    assert skills
    assert skill["skill_name"]
    assert skill["input_requirements"]
    assert skill["output_format"]
    assert "ad_anomaly" in skill["use_cases"]
    assert skill["risk_level"] == "high"
    assert skill["requires_tian_shen_approval"] is True


def test_employee_matcher_selects_best_employee_for_product_task():
    result = match_employee_for_task({"goal": "优化京东60店商品详情页转化", "task_type": "product_issue"})

    assert result["task_type"] == "product_issue"
    assert "ecommerce_operation" in result["required_skills"]
    assert result["best_employee"]["employee_code"] == "tianshang"
    assert result["best_employee"]["match_score"] > 0
    assert result["safety"]["recommendation_only"] is True
    assert result["safety"]["can_auto_assign"] is False
    assert result["safety"]["can_expand_permission"] is False


def test_employee_matcher_marks_high_risk_skill_for_tian_shen():
    result = match_employee_for_task({"goal": "检查京东60店广告 ROI 异常", "task_type": "ad_anomaly"})

    assert "ad_performance_check" in result["required_skills"]
    assert result["best_employee"]["employee_code"] == "tiantou"
    assert result["safety"]["requires_tian_shen_for_high_risk_skill"] is True
    assert result["approval_gate"]["center"] == "TianShen"
    assert result["approval_gate"]["decision"] == "YELLOW"
    assert result["approval_gate"]["requires_confirmation"] is True


def test_employee_matcher_uses_knowledge_references_without_external_call():
    seed_learning_knowledge()
    result = match_employee_for_task({"goal": "京东60店转化下降需要复盘广告数据", "task_type": "conversion_decline"})

    assert result["knowledge_references"]
    assert result["knowledge_references"][0]["similarity_score"] > 0


def test_capability_match_requires_login(client):
    response = client.post("/command/capability/match", json={"task": {"goal": "优化商品"}})

    assert response.status_code == 401


def test_capability_match_rejects_low_permission(client, viewer_headers):
    response = client.post(
        "/command/capability/match",
        headers=viewer_headers,
        json={"task": {"goal": "优化商品"}},
    )

    assert response.status_code == 403


def test_capability_match_endpoint_recommends_without_queue_or_permission_expansion(client, owner_headers):
    response = client.post(
        "/command/capability/match",
        headers=owner_headers,
        json={"task": {"goal": "优化京东60店商品详情页转化", "task_type": "product_issue"}},
    )

    assert response.status_code == 200
    match = response.json()["match"]
    assert match["best_employee"]["employee_code"] == "tianshang"
    assert match["safety"]["recommendation_only"] is True
    assert match["safety"]["can_auto_assign"] is False
    assert match["best_employee"]["can_expand_permission"] is False

    redis_client = __import__("backend.database", fromlist=["get_redis"]).get_redis()
    assert redis_client.llen(ORCHESTRATOR_QUEUE_NAME) == 0


def test_employee_profiles_are_available_for_core_ai_employees():
    profiles = list_employee_profiles()
    codes = {row["employee_code"] for row in profiles}

    assert {"tiancai_data", "tiance_strategy", "tianshang", "tiantou", "tianjian_test"} <= codes
