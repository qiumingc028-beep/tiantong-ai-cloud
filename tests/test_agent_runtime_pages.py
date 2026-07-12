from pathlib import Path


AGENT_RUNTIME_PAGE = Path("frontend/agent-runtime.html")
CAPABILITY_PAGE = Path("frontend/capability-center.html")
EXECUTION_PAGE = Path("frontend/execution-records.html")


def test_agent_runtime_page_files_exist():
    assert AGENT_RUNTIME_PAGE.exists()
    assert CAPABILITY_PAGE.exists()
    assert EXECUTION_PAGE.exists()


def test_agent_runtime_pages_are_served(client):
    for path, text in [
        ("/agent-runtime.html", "Agent Runtime"),
        ("/capability-center.html", "能力中心"),
        ("/execution-records.html", "执行记录"),
    ]:
        response = client.get(path)
        assert response.status_code == 200
        assert text in response.text


def test_agent_runtime_pages_contain_core_chinese_copy():
    for page, phrases in [
        (AGENT_RUNTIME_PAGE, ["统一接收执行请求", "真实执行器默认关闭", "Agent Runtime"]),
        (CAPABILITY_PAGE, ["统一能力注册表", "查看能力详情", "创建执行", "模拟执行器"]),
        (EXECUTION_PAGE, ["执行记录与审计链路", "批准并执行", "审计记录", "敏感字段必须脱敏"]),
    ]:
        html = page.read_text(encoding="utf-8")
        for phrase in phrases:
            assert phrase in html


def test_agent_runtime_pages_do_not_expose_forbidden_controls():
    forbidden = ["OpenClaw", "真实电脑控制", "真实手机控制", "任意 Shell", "自动发布", "自动部署生产"]
    for page in [AGENT_RUNTIME_PAGE, CAPABILITY_PAGE, EXECUTION_PAGE]:
        html = page.read_text(encoding="utf-8")
        for phrase in forbidden:
            assert phrase not in html

