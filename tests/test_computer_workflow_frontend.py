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
