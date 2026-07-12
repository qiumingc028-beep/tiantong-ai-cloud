from __future__ import annotations


def test_observability_frontend_pages_render(client):
    pages = {
        "/security-ops-center.html": ["安全运营中心", "在线测试设备", "运行中工作流"],
        "/device-monitoring.html": ["设备监控", "设备名称", "健康评分"],
        "/execution-quality.html": ["执行质量", "质量评分", "风险评分"],
        "/security-incidents.html": ["安全事件", "告警", "处理"],
    }
    for path, snippets in pages.items():
        response = client.get(path)
        assert response.status_code == 200
        for snippet in snippets:
            assert snippet in response.text

