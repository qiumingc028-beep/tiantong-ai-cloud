from pathlib import Path


PAGE = Path("frontend/ai-employee-memory.html")


def read_page() -> str:
    return PAGE.read_text(encoding="utf-8")


def test_ai_employee_memory_page_file_exists():
    assert PAGE.exists()


def test_ai_employee_memory_page_contains_required_sections():
    html = read_page()

    for text in [
        "AI Employee Memory Center",
        "AI员工记忆中心",
        "记忆总览",
        "记忆数量",
        "最近更新",
        "记忆类型",
        "Memory分类",
        "Experience",
        "经验",
        "DecisionHistory",
        "决策记录",
        "LearningRecord",
        "学习记录",
        "SuccessCase",
        "成功案例",
        "FailureCase",
        "失败案例",
        "最近记忆",
        "安全边界",
        "readonly安全模式",
        "暂无数据",
    ]:
        assert text in html


def test_ai_employee_memory_page_uses_existing_readonly_apis():
    html = read_page()

    for text in [
        "/api/task-center/tasks",
        "/api/tiancang/articles/search",
        "/api/tiancang/sops",
        "/api/tiancang/prompts",
        "/api/tiancang/bugs",
    ]:
        assert text in html


def test_ai_employee_memory_page_has_safe_empty_state():
    html = read_page()

    for text in [
        "当前记忆数据暂不可用",
        "renderSafeEmpty",
        "安全空状态",
    ]:
        assert text in html


def test_ai_employee_memory_page_has_no_dangerous_entries():
    html = read_page()

    forbidden = [
        "Execution Engine",
        "OpenClaw",
        "n8n",
        "自动学习",
        "自动修改记忆",
        "自动训练模型",
        "写入记忆按钮",
        "训练模型按钮",
        "修改记忆按钮",
        "开始训练",
        "立即训练",
        "执行任务",
        "立即执行",
        "开始任务",
        "修改权限",
        "/api/execution",
        "/api/brain/start",
        "/ai-execution.html",
    ]
    for text in forbidden:
        assert text not in html
