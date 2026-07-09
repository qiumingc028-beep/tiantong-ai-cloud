from pathlib import Path


INDEX_HTML = Path("frontend/index.html")


def test_index_html_contains_boss_approval_center_panel():
    html = INDEX_HTML.read_text(encoding="utf-8")

    assert "待老板确认" in html
    assert "approvalCount" in html
    assert "approvalList" in html


def test_index_html_calls_approval_center_pending_api():
    html = INDEX_HTML.read_text(encoding="utf-8")

    assert "/api/approval-center/pending" in html
    assert "loadApprovalCenter" in html


def test_boss_approval_panel_adds_no_execution_or_confirm_buttons():
    html = INDEX_HTML.read_text(encoding="utf-8")
    section = html.split('<h2>待老板确认</h2>', 1)[1].split('<section class="grid section-grid">', 1)[0]

    assert "批准" not in section
    assert "确认执行" not in section
    assert "自动执行" not in section
    assert "自动部署" not in section
    assert "修改权限" not in section
    assert "method:'POST'" not in section
    assert 'method:"POST"' not in section
