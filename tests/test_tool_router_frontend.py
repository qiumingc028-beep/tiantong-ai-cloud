from pathlib import Path


PAGE = Path("frontend/tool-router.html")


def test_tool_router_page_exists_and_loads(client):
    assert PAGE.is_file()
    response = client.get("/tool-router.html")
    assert response.status_code == 200
    assert "Tool Router 工具路由中心" in response.text


def test_tool_router_page_uses_only_router_simulation_apis():
    source = PAGE.read_text()
    assert "/api/tool-router/routes" in source
    assert "/api/tool-router/check" in source
    assert "/api/tool-router/route" in source
    assert "/api/tool-router/logs" in source
    assert "/api/tools/call" not in source
    assert "PATCH" not in source
    assert "PUT" not in source
    assert "DELETE" not in source


def test_tool_router_page_has_required_sections_and_no_sensitive_terms():
    source = PAGE.read_text()
    for text in ["路由总览", "AI员工路由关系", "路由规则管理", "路由日志", "审批状态"]:
        assert text in source
    for word in ["password_hash", "token", "secret", "API Key", "Bearer", "Authorization"]:
        assert word not in source

