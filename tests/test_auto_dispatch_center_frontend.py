from __future__ import annotations

from pathlib import Path


PAGE = Path("frontend/auto-dispatch-center.html")


def read_page() -> str:
    return PAGE.read_text(encoding="utf-8")


def test_auto_dispatch_center_file_exists():
    assert PAGE.exists()


def test_auto_dispatch_center_page_is_served(client):
    response = client.get("/auto-dispatch-center.html")
    assert response.status_code == 200
    assert "AI自动派单中心" in response.text


def test_auto_dispatch_center_required_modules_present():
    html = read_page()
    for text in [
        "任务输入区",
        "AI员工推荐区",
        "派单方案区",
        "老板确认区",
        "执行追踪区",
        "任务标题",
        "任务描述",
        "优先级",
        "风险等级",
        "分析任务",
        "确认派单",
        "拒绝",
        "重新分析",
        "等待老板确认",
    ]:
        assert text in html


def test_auto_dispatch_center_uses_existing_dispatch_apis():
    html = read_page()
    for path in [
        "/api/auto-dispatch/overview",
        "/api/auto-dispatch/employee-capabilities",
        "/api/auto-dispatch/analyze",
        "/api/auto-dispatch/match",
        "/api/auto-dispatch/tasks/${id}/plan",
        "/api/auto-dispatch/tasks/${id}/confirm",
        "/api/auto-dispatch/tasks/${id}/tracking",
    ]:
        assert path in html


def test_auto_dispatch_center_keeps_manual_safety_boundary():
    html = read_page()
    assert "不自动执行任务" in html
    assert "不绕过老板确认" in html
    assert "高风险任务必须显示等待老板确认" in html
    assert "不会自动执行任务" in html

    forbidden_button_snippets = [
        ">自动执行<",
        ">自动部署<",
        ">自动提交代码<",
        ">绕过确认<",
        ">修改权限<",
    ]
    for snippet in forbidden_button_snippets:
        assert snippet not in html


def test_auto_dispatch_center_menu_entry_points_to_new_page():
    index_html = Path("frontend/index.html").read_text(encoding="utf-8")
    task_center_html = Path("frontend/task-center.html").read_text(encoding="utf-8")
    assert "['AI自动派单中心','/auto-dispatch-center.html']" in index_html
    assert "['AI自动派单中心','/auto-dispatch-center.html']" in task_center_html
