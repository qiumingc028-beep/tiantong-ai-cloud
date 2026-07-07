from backend.ai_employees import FLOW_EMPLOYEE_CODES, FLOW_TASK_TYPES, employee_name, normalize_employee_code
from backend.ai_employees.executors import execute_employee_skill
from backend.worker import SUPPORTED_TASK_TYPES


def test_ai_employee_registry_normalizes_legacy_names():
    assert normalize_employee_code("tian_cai") == "tiancai_data"
    assert normalize_employee_code("tian_ce") == "tiance_strategy"
    assert normalize_employee_code("tiancai") == "tiancai_data"
    assert normalize_employee_code("tiance") == "tiance_strategy"
    assert employee_name("tian_ce") == "天策：策略分析中心"


def test_flow_employee_codes_are_canonical_and_ordered():
    assert FLOW_EMPLOYEE_CODES == ("tiancai_data", "tianshu", "tiance_strategy", "tianbo")
    assert FLOW_TASK_TYPES == {
        "tiancai_data": "data_collection",
        "tianshu": "data_analysis",
        "tiance_strategy": "strategy_planning",
        "tianbo": "video_script",
    }


def test_employee_executor_accepts_legacy_aliases():
    result = execute_employee_skill(1, "strategy_planning", "tian_ce", {"topic": "growth"})
    assert result["assigned_to"] == "tiance_strategy"
    assert result["payload"]["summary"] == "天策生成策略建议"


def test_worker_imports_and_supports_ai_task_queues():
    assert "sprint17_ai_task" in SUPPORTED_TASK_TYPES
    assert "sprint18_business_loop" in SUPPORTED_TASK_TYPES
