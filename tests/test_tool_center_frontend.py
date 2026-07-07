from pathlib import Path


PAGE = Path("frontend/tool-center.html")


def test_tool_center_page_exists_and_loads(client):
    assert PAGE.is_file()
    response = client.get("/tool-center.html")
    assert response.status_code == 200
    assert "Tool Center 工具中心" in response.text


def test_tool_center_page_uses_readonly_tool_center_apis():
    source = PAGE.read_text()
    assert "/api/tools/list" in source
    assert "/api/tools/logs" in source
    assert "/api/tools/employees/" in source
    assert "/api/tools/call" not in source
    assert "/api/tools/check" not in source
    assert "PATCH" not in source
    assert "PUT" not in source
    assert "DELETE" not in source


def test_tool_center_page_hides_sensitive_terms():
    source = PAGE.read_text()
    for word in ["password_hash", "token", "secret", "API Key", "Bearer", "Authorization"]:
        assert word not in source

