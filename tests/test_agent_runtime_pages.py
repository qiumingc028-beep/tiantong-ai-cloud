from pathlib import Path


AGENT_RUNTIME_PAGE = Path("frontend/agent-runtime.html")
CAPABILITY_PAGE = Path("frontend/capability-center.html")
EXECUTION_PAGE = Path("frontend/execution-records.html")
BROWSER_READONLY_PAGE = Path("frontend/browser-readonly-test.html")
RESEARCH_PAGE = Path("frontend/research-records.html")
KNOWLEDGE_CENTER_PAGE = Path("frontend/knowledge-asset-center.html")
KNOWLEDGE_DETAIL_PAGE = Path("frontend/knowledge-asset-detail.html")


def test_agent_runtime_page_files_exist():
    assert AGENT_RUNTIME_PAGE.exists()
    assert CAPABILITY_PAGE.exists()
    assert EXECUTION_PAGE.exists()
    assert RESEARCH_PAGE.exists()
    assert KNOWLEDGE_CENTER_PAGE.exists()
    assert KNOWLEDGE_DETAIL_PAGE.exists()


def test_agent_runtime_pages_are_served(client):
    for path, text in [
        ("/agent-runtime.html", "Agent Runtime"),
        ("/capability-center.html", "能力中心"),
        ("/execution-records.html", "执行记录"),
        ("/browser-readonly-test.html", "公开网页采集"),
        ("/research-records.html", "研究记录"),
        ("/knowledge-asset-center.html", "天藏知识资产中心"),
        ("/knowledge-asset-detail.html", "知识资产详情"),
    ]:
        response = client.get(path)
        assert response.status_code == 200
        assert text in response.text


def test_agent_runtime_pages_contain_core_chinese_copy():
    for page, phrases in [
        (AGENT_RUNTIME_PAGE, ["统一接收执行请求", "真实执行器默认关闭", "浏览器只读", "Agent Runtime"]),
        (CAPABILITY_PAGE, ["统一能力注册表", "查看能力详情", "创建执行", "模拟执行器", "公开网页采集"]),
        (EXECUTION_PAGE, ["执行记录与审计链路", "批准并执行", "审计记录", "敏感字段必须脱敏", "最终网址"]),
        (BROWSER_READONLY_PAGE, ["公开网页只读采集", "开始只读采集", "公开网页采集"]),
        (RESEARCH_PAGE, ["多来源公开信息研究", "研究记录", "证据链", "交叉验证"]),
        (KNOWLEDGE_CENTER_PAGE, ["天藏知识资产中心", "新建知识", "提交为知识候选", "知识总数"]),
        (KNOWLEDGE_DETAIL_PAGE, ["知识资产详情", "提交审核", "批准", "版本历史", "引用记录"]),
    ]:
        html = page.read_text(encoding="utf-8")
        for phrase in phrases:
            assert phrase in html


def test_agent_runtime_pages_do_not_expose_forbidden_controls():
    forbidden = ["OpenClaw", "真实电脑控制", "真实手机控制", "任意 Shell", "自动发布", "自动部署生产"]
    for page in [AGENT_RUNTIME_PAGE, CAPABILITY_PAGE, EXECUTION_PAGE, BROWSER_READONLY_PAGE, RESEARCH_PAGE, KNOWLEDGE_CENTER_PAGE, KNOWLEDGE_DETAIL_PAGE]:
        html = page.read_text(encoding="utf-8")
        for phrase in forbidden:
            assert phrase not in html
