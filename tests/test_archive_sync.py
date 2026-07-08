from __future__ import annotations

from pathlib import Path

from backend.main import app


def test_archive_routes_registered():
    paths = {getattr(route, "path", ""): getattr(route, "methods", set()) for route in app.routes}
    assert paths["/api/archive/sprints"] == {"GET"}
    assert paths["/api/archive/sprint-summary"] == {"POST"}
    assert paths["/api/archive/project-status-draft"] == {"GET"}
    assert paths["/api/archive/decision-draft"] == {"GET"}


def test_archive_requires_login_and_rejects_viewer(client, viewer_headers, operator_headers):
    client.cookies.clear()
    assert client.get("/api/archive/sprints").status_code == 401
    client.cookies.clear()
    assert client.get("/api/archive/sprints", headers=viewer_headers).status_code == 403
    client.cookies.clear()
    assert client.post("/api/archive/sprint-summary", headers=operator_headers, json=payload()).status_code == 403


def test_owner_can_list_sprint_records(client, owner_headers):
    response = client.get("/api/archive/sprints", headers=owner_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["draft_only"] is True
    assert data["saved"] is False
    assert data["records"]
    assert data["records"][0]["sprint_version"].startswith("Sprint")


def test_owner_can_generate_archive_drafts_without_saving(client, owner_headers):
    before = read_docs_snapshot()
    response = client.post("/api/archive/sprint-summary", headers=owner_headers, json=payload())
    after = read_docs_snapshot()

    assert response.status_code == 200
    data = response.json()
    assert data["saved"] is False
    assert data["requires_boss_confirmation"] is True
    assert data["safety"]["auto_write_disabled"] is True
    assert "changelog" in data["drafts"]
    assert "project_status" in data["drafts"]
    assert "decision_log" in data["drafts"]
    assert "Sprint26.3-v1.0" in data["drafts"]["changelog"]
    assert before == after


def test_archive_draft_filters_sensitive_content(client, owner_headers):
    unsafe = payload()
    unsafe["codex_output"] = "token=abc secret=def should not appear"
    unsafe["risk_notes"] = ["Authorization: Bearer abc"]
    response = client.post("/api/archive/sprint-summary", headers=owner_headers, json=unsafe)
    assert response.status_code == 200
    body = str(response.json()).lower()
    assert "token=abc" not in body
    assert "secret=def" not in body
    assert "bearer abc" not in body
    assert "[redacted: sensitive content removed]" in body


def test_archive_project_status_and_decision_drafts(client, admin_headers):
    status = client.get("/api/archive/project-status-draft", headers=admin_headers)
    decision = client.get("/api/archive/decision-draft", headers=admin_headers)
    assert status.status_code == 200
    assert decision.status_code == 200
    assert status.json()["saved"] is False
    assert decision.json()["requires_boss_confirmation"] is True
    assert "禁止自动修改项目文档" in status.json()["draft"]
    assert "不自动提交 Git" in decision.json()["draft"]


def test_archive_sync_has_no_database_or_dangerous_calls():
    files = [
        Path("backend/archive_sync/schemas.py"),
        Path("backend/archive_sync/safety.py"),
        Path("backend/archive_sync/sprint_record.py"),
        Path("backend/archive_sync/draft_builder.py"),
        Path("backend/archive_sync/router.py"),
    ]
    forbidden = [
        "subprocess",
        "os.system",
        "shell=True",
        "requests.",
        "httpx.",
        "webbrowser",
        "docker.from_env",
        "git push",
        "git commit",
        "open(",
        "Path.write",
        "db.add",
        "db.commit",
    ]
    for path in files:
        source = path.read_text()
        for needle in forbidden:
            assert needle not in source


def payload() -> dict:
    return {
        "sprint_name": "天统AI项目自动档案同步系统 MVP",
        "sprint_version": "Sprint26.3-v1.0",
        "owner": ["天王", "天藏"],
        "commit_id": "629b06289e2003ba20932c99a8e47afc5ed59559",
        "changed_files": ["backend/archive_sync/router.py", "tests/test_archive_sync.py"],
        "test_result": "pending",
        "deployment_status": "not_deployed",
        "risk_notes": ["只生成草稿，不自动写 docs。"],
        "codex_output": "新增归档草稿 API。",
    }


def read_docs_snapshot() -> dict[str, str]:
    paths = [
        Path("docs/PROJECT_STATUS.md"),
        Path("docs/CHANGELOG.md"),
        Path("docs/DECISION_LOG.md"),
    ]
    return {str(path): path.read_text() if path.exists() else "" for path in paths}
