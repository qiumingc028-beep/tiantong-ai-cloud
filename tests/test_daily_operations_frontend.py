from pathlib import Path


INDEX_HTML = Path("frontend/index.html")


def test_index_html_contains_daily_operations_panel():
    html = INDEX_HTML.read_text(encoding="utf-8")
    assert "今日运营摘要" in html
    assert "dailyMetrics" in html
    assert "dailyPendingList" in html
    assert "dailyRiskList" in html


def test_index_html_calls_daily_summary_api():
    html = INDEX_HTML.read_text(encoding="utf-8")
    assert "/api/ceo-dashboard/daily-summary" in html
    assert "/api/ceo-dashboard/summary" in html


def test_daily_operations_frontend_does_not_add_business_write_calls():
    html = INDEX_HTML.read_text(encoding="utf-8")
    html += Path("frontend/rbac-navigation.js").read_text(encoding="utf-8")
    normalized = html.replace("method:'POST'", "method: 'POST'")
    assert "method: 'PATCH'" not in normalized
    assert 'method:"PATCH"' not in normalized
    assert "method: 'PUT'" not in normalized
    assert 'method:"PUT"' not in normalized
    assert "method: 'DELETE'" not in normalized
    assert 'method:"DELETE"' not in normalized
    assert "method: 'POST'" in normalized
    assert "/api/logout" in normalized


def test_daily_operations_frontend_has_no_dangerous_operation_buttons():
    html = INDEX_HTML.read_text(encoding="utf-8")
    button_lines = [line for line in html.splitlines() if "<button" in line or "class=\"btn" in line or "class='btn" in line]
    dangerous_labels = ["自动执行", "自动部署", "修改权限", "安装插件", "删除数据", "提交Git"]
    for line in button_lines:
        assert not any(label in line for label in dangerous_labels)
