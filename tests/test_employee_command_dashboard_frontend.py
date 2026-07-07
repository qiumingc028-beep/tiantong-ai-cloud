from __future__ import annotations

from pathlib import Path


DASHBOARD_FILES = [
    Path("frontend/dashboard/overview.html"),
    Path("frontend/dashboard/organization.html"),
    Path("frontend/dashboard/employees.html"),
]


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_employee_command_dashboard_frontend_files_exist():
    for path in DASHBOARD_FILES:
        assert path.exists(), f"{path} should exist"


def test_employee_command_dashboard_pages_are_served(client):
    for path in ["/dashboard/overview.html", "/dashboard/organization.html", "/dashboard/employees.html", "/dashboard/workflow.html"]:
        response = client.get(path)
        assert response.status_code == 200


def test_employee_command_dashboard_overview_shows_required_metrics():
    html = read(Path("frontend/dashboard/overview.html"))

    for text in ["AI员工数量", "在线员工", "执行任务数量", "成功率", "风险数量", "待审批任务"]:
        assert text in html
    assert "/api/ceo-dashboard/employee-command-dashboard" in html
    assert "不修改权限、不创建员工、不执行任务" in html


def test_employee_command_dashboard_organization_shows_core_tree_nodes():
    html = read(Path("frontend/dashboard/organization.html"))

    for text in ["天统", "天工", "天王", "天颜", "天检", "天监", "天盾", "天藏", "天采"]:
        assert text in html
    assert "查看上下级" in html
    assert "查看负责人" in html
    assert "查看能力标签" in html


def test_employee_command_dashboard_detail_shows_required_employee_fields():
    html = read(Path("frontend/dashboard/employees.html"))

    for text in ["技能", "完成任务", "成功率", "失败记录", "学习建议", "当前能力等级"]:
        assert text in html
    assert "/api/ceo-dashboard/employee-command-dashboard/employees/" in html


def test_employee_command_dashboard_frontend_is_readonly():
    combined = "\n".join(read(path) for path in DASHBOARD_FILES)
    forbidden_patterns = [
        "method:'POST'",
        'method:"POST"',
        "method: 'POST'",
        'method: "POST"',
        "method:'PATCH'",
        "method:'PUT'",
        "method:'DELETE'",
        "自动修改权限</button>",
        "创建员工</button>",
        "执行任务</button>",
        "window.open",
        "<iframe",
        "WebSocket",
        "EventSource",
        "sendBeacon",
    ]

    for pattern in forbidden_patterns:
        assert pattern not in combined
    assert combined.count("fetch(") >= 3
    assert "/api/ceo-dashboard/employee-command-dashboard" in combined
