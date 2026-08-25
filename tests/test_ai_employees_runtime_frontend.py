from pathlib import Path


AI_EMPLOYEES_HTML = Path("frontend/ai-employees.html")


def test_ai_employees_page_contains_runtime_status_panel():
    html = AI_EMPLOYEES_HTML.read_text(encoding="utf-8")

    assert "AI员工运行状态" in html
    assert "runtimeTotal" in html
    assert "runtimeOnline" in html
    assert "runtimeWorking" in html
    assert "runtimeError" in html


def test_ai_employees_page_calls_runtime_status_api():
    html = AI_EMPLOYEES_HTML.read_text(encoding="utf-8")

    assert "/api/ai-employees/runtime-status" in html
    assert "loadRuntimeStatus" in html


def test_ai_employees_runtime_panel_adds_no_execution_controls():
    html = AI_EMPLOYEES_HTML.read_text(encoding="utf-8")
    runtime_section = html.split('<section class="card runtime-card">', 1)[1].split('<div class="layout">', 1)[0]

    forbidden_labels = ["自动执行", "自动部署", "修改权限", "安装插件", "执行任务", "调用工具"]
    button_lines = [line for line in runtime_section.splitlines() if "<button" in line]
    assert len(button_lines) == 1
    assert 'class="secondary"' in button_lines[0]
    assert 'data-rbac-action="ai-employees-003"' in button_lines[0]
    assert "onclick" not in button_lines[0]
    assert "刷新运行状态" in button_lines[0]
    for line in button_lines:
        assert not any(label in line for label in forbidden_labels)
