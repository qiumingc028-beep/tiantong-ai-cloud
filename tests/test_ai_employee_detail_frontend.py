from pathlib import Path


DETAIL_PAGE = Path("frontend/ai-employee-detail.html")
LIST_PAGE = Path("frontend/ai-employees.html")


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_ai_employee_detail_page_is_served(client):
    response = client.get("/ai-employee-detail.html")

    assert response.status_code == 200
    assert "AI员工详情" in response.text


def test_ai_employee_detail_page_contains_required_sections():
    html = read(DETAIL_PAGE)

    for text in ["员工档案", "能力中心", "权限中心", "当前任务", "最近错误", "安全边界", "任务历史", "最近运行日志"]:
        assert text in html
    for text in ["员工名称", "部门", "状态", "职责", "技能列表", "可执行任务类型", "使用工具", "权限范围", "风险等级", "是否需要老板确认", "成功率", "boss_confirm=true", "security_audited=true"]:
        assert text in html


def test_ai_employee_detail_page_has_loading_error_and_empty_states():
    html = read(DETAIL_PAGE)

    for text in [
        "正在加载AI员工详情",
        "详情已加载",
        "AI员工详情加载失败",
        "页面加载失败",
        "暂无当前任务",
        "暂无最近错误",
        "暂无任务历史",
        "暂无运行日志",
        "暂无工具绑定",
    ]:
        assert text in html


def test_ai_employee_detail_page_has_frontend_renderers_for_required_data():
    html = read(DETAIL_PAGE)

    for snippet in [
        "function renderDetail()",
        "function renderCurrentTask(task)",
        "function renderRecentError(task)",
        "function renderSafety(safety, sources)",
        "function renderTasks(tasks)",
        "function renderLogs(logs)",
        "detail.current_task",
        "detail.recent_error",
        "detail.historical_tasks",
        "detail.success_rate",
        "detail.permission_scope",
        "detail.skills",
    ]:
        assert snippet in html


def test_ai_employee_detail_page_calls_readonly_detail_api():
    html = read(DETAIL_PAGE)

    assert "/api/ai-employees/" in html
    assert "/detail" in html
    assert "GET /api/ai-employees/{employee_id}/detail" not in html


def test_ai_employee_list_links_to_detail_page():
    html = read(LIST_PAGE)

    assert "/ai-employee-detail.html?code=" in html
    assert "详情" in html


def test_ai_employee_detail_frontend_has_no_execution_calls():
    html = read(DETAIL_PAGE)
    forbidden = [
        "/api/execution/",
        "/api/brain/start",
        "/api/task-center/tasks/",
        "/api/orchestrator/analyze",
        "/api/orchestrator/plan",
        "/task-center.html",
        "/ai-execution.html",
        "/orchestrator.html",
        "立即执行",
        "开始任务",
        "提交结果",
        "分配AI员工",
        "更新任务状态",
        "提交验收",
        "提交审计",
    ]

    for snippet in forbidden:
        assert snippet not in html


def test_ai_employee_detail_frontend_retains_risk_controls():
    html = read(DETAIL_PAGE)

    for snippet in [
        "boss_confirm=true",
        "security_audited=true",
        "high_risk_requires",
        "dangerous_action_entrypoints_hidden",
        "external_api_called",
        "can_auto_execute",
    ]:
        assert snippet in html


def test_ai_employee_detail_frontend_uses_only_readonly_local_api_calls():
    html = read(DETAIL_PAGE)

    assert "fetch('http://" not in html
    assert 'fetch("http://' not in html
    assert "fetch('https://" not in html
    assert 'fetch("https://' not in html
    assert "/api/logout" in html
    for snippet in [
        "/api/execution/",
        "/api/task-center/tasks/",
        "/api/orchestrator/analyze",
        "/api/orchestrator/plan",
        "/api/ai/tasks/",
    ]:
        assert snippet not in html


def test_ai_employee_detail_frontend_filters_sensitive_words():
    html = read(DETAIL_PAGE).lower()
    forbidden = ["password_hash", "authorization", "bearer", "private_key"]

    for snippet in forbidden:
        assert snippet not in html
