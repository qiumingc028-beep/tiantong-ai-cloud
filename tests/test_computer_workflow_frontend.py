from pathlib import Path


CENTER_PAGE = Path("frontend/computer-workflow-center.html")
DETAIL_PAGE = Path("frontend/computer-workflow-detail.html")


def test_computer_workflow_frontend_pages_exist():
    assert CENTER_PAGE.exists()
    assert DETAIL_PAGE.exists()


def test_computer_workflow_frontend_contains_required_chinese_copy():
    center_html = CENTER_PAGE.read_text(encoding="utf-8")
    detail_html = DETAIL_PAGE.read_text(encoding="utf-8")
    combined = center_html + detail_html

    for text in [
        "测试工作流中心",
        "测试工作流详情",
        "最大 5 步",
        "关键节点审批",
        "执行后验证",
        "计划变化后原批准失效",
        "已暂停",
        "生产开关",
    ]:
        assert text in combined


def test_computer_workflow_frontend_pages_are_served(client):
    center = client.get("/computer-workflow-center.html")
    detail = client.get("/computer-workflow-detail.html")

    assert center.status_code == 200
    assert detail.status_code == 200
    assert "测试工作流中心" in center.text
    assert "测试工作流详情" in detail.text


def test_computer_workflow_center_uses_real_owner_scoped_contract():
    html = CENTER_PAGE.read_text(encoding="utf-8")

    for contract in [
        "/api/task-center/tasks",
        "/api/v2/computer/workflows",
        "/approve",
        "/start",
        "/resume",
        "data-rbac-action=\"computer-workflow-001\"",
        "data-rbac-action=\"computer-workflow-002\"",
        "data-rbac-action=\"computer-workflow-003\"",
        "data-rbac-action=\"computer-workflow-004\"",
        "data-rbac-action=\"computer-workflow-005\"",
        "暂无工作流",
        "网络连接失败，请检查网络后重试。",
        "action_type:'截图'",
        "target_url:targetUrl",
        "new URL('/computer-workflow-center.html',window.location.origin)",
        "action_type:'等待'",
    ]:
        assert contract in html

    assert "127.0.0.1:59200" not in html
    assert "演示数据" not in html
    assert "mock" not in html.lower()


def test_computer_workflow_actions_follow_server_statuses():
    html = CENTER_PAGE.read_text(encoding="utf-8")

    assert "workflow.status==='等待批准'" in html
    assert "workflow.status==='已批准'" in html
    assert "workflow.status==='已暂停'" in html
    assert "workflow.status==='已完成'" in html
