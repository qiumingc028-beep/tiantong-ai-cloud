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

    for text in [
        "AI员工详情",
        "员工第一眼信息",
        "AI员工",
        "部门",
        "当前状态",
        "成长分",
        "完成",
        "老板关心的员工信息",
        "返回AI员工中心",
        "我的身份：",
        "我负责：",
        "今天完成：",
        "我正在学习：",
        "我的成长：",
        "我的成长记录",
        "最近变化：",
        "成长分：",
        "现在几分",
        "上升趋势",
        "成长原因",
        "经验记录",
        "做过什么",
        "解决什么问题",
        "积累什么经验",
        "我正在学习的能力",
        "熟练程度",
        "什么时候会的",
        "用过几次",
        "做成比例",
    ]:
        assert text in html
    for text in [
        "我的身份：",
        "我负责：",
        "今天完成：",
        "我正在学习：",
        "我的成长：",
        "只看不操作",
        "老板确认",
        "安全记录",
        "readonly=true",
        "boss_confirm=true",
        "security_audited=true",
    ]:
        assert text in html


def test_ai_employee_detail_page_has_loading_error_and_empty_states():
    html = read(DETAIL_PAGE)

    for text in [
        "正在加载AI员工详情",
        "详情已加载",
        "现在看不到这个员工，请稍后再看。",
        "暂无数据",
        "暂无成长记录",
    ]:
        assert text in html


def test_ai_employee_detail_page_has_frontend_renderers_for_required_data():
    html = read(DETAIL_PAGE)

    for snippet in [
        "function renderHeader(detail,growth)",
        "function renderProfile(detail,growth)",
        "function renderRecentChanges(data)",
        "function renderGrowthScore(detail,growth)",
        "function renderExperience(detail,growth)",
        "function renderAbilities(detail,growth)",
        "function skillLevel(growth)",
        "function successRateText(tasks)",
        "function growthReason(tasks,memory)",
        "function renderSecurity(detail,growth)",
        "detail.success_rate",
        "detail.skills",
        "growth.task_summary",
        "growth.memory_summary",
        "growth.growth_summary",
        "learningBox",
    ]:
        assert snippet in html


def test_ai_employee_detail_page_calls_readonly_detail_api():
    html = read(DETAIL_PAGE)

    assert "/api/ai-employees/" in html
    assert "/detail" in html
    assert "/api/ai-employee-growth/employees/" in html
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
        "<button",
        "method:'POST'",
        'method:"POST"',
    ]

    for snippet in forbidden:
        assert snippet not in html


def test_ai_employee_detail_frontend_retains_risk_controls():
    html = read(DETAIL_PAGE)

    for snippet in [
        "boss_confirm=true",
        "security_audited=true",
        "readonly=true",
        "auto_task_execution:false",
        "auto_skill_upgrade:false",
        "auto_permission_change:false",
    ]:
        assert snippet in html


def test_ai_employee_detail_frontend_uses_only_readonly_local_api_calls():
    html = read(DETAIL_PAGE)

    assert "fetch('http://" not in html
    assert 'fetch("http://' not in html
    assert "fetch('https://" not in html
    assert 'fetch("https://' not in html
    for snippet in [
        "/api/execution/",
        "/api/task-center/tasks/",
        "/api/orchestrator/analyze",
        "/api/orchestrator/plan",
        "/api/ai/tasks/",
        "<table",
    ]:
        assert snippet not in html


def test_ai_employee_detail_frontend_filters_sensitive_words():
    html = read(DETAIL_PAGE).lower()
    forbidden = ["password_hash", "authorization", "bearer", "private_key", "employee_id", "database field", "api field"]

    for snippet in forbidden:
        assert snippet not in html


def test_ai_employee_detail_supports_simple_workforce_flow():
    html = read(DETAIL_PAGE)

    for text in [
        'href="/ai-workforce.html"',
        "返回AI员工中心",
        "我的身份：",
        "我负责：",
        "今天完成：",
        "我正在学习：",
        "我的成长：",
        "只看不操作",
    ]:
        assert text in html
