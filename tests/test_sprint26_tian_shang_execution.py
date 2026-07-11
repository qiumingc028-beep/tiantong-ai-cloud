from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

from backend.employee_execution.models import EmployeeExecutionContract
from backend.main import app
from backend.models import TaskCenterResult, TaskCenterTask
from backend.workers.tian_shang_worker import create_tian_shang_task, process_next_tian_shang_execution


def test_sprint26_routes_registered():
    paths = {getattr(route, "path", ""): getattr(route, "methods", set()) for route in app.routes}
    assert paths["/api/employee-execution/tian-shang/tasks"] == {"POST"}
    assert paths["/api/employee-execution/tian-shang/process-next"] == {"POST"}
    assert paths["/api/employee-execution/tian-shang/status"] == {"GET"}
    assert paths["/api/employee-execution/contracts/{contract_id}"] == {"GET"}


def test_tian_shang_execution_contract_lifecycle(test_db):
    db = test_db()
    try:
        created = create_tian_shang_task(db, "帮我找未来30天最值得开发的男士机械表", enqueue=True)
        contract_id = created["contract"]["id"]
        contract = db.get(EmployeeExecutionContract, contract_id)
        assert contract.status == "CREATED"
        assert contract.employee_id == "tianshang"
        assert "market_search" in contract.required_tools

        processed = process_next_tian_shang_execution(db, timeout=1)
        assert processed is True
        db.refresh(contract)
        assert contract.status == "COMPLETED"
        assert contract.progress == 100
        assert contract.review_status == "pending_review"
        assert "未来30天男士机械表新品建议" in contract.result

        task = db.get(TaskCenterTask, int(contract.task_id))
        assert task.status == "completed"
        result = db.query(TaskCenterResult).filter(TaskCenterResult.task_id == task.id).one()
        assert result.ai_employee_code == "tianshang"
        assert "不自动上架商品" in result.result_content
    finally:
        db.close()


def test_tian_shang_api_creates_processes_and_reports(client, owner_headers):
    create = client.post(
        "/api/employee-execution/tian-shang/tasks",
        headers=owner_headers,
        json={"goal": "帮我找未来30天最值得开发的男士机械表"},
    )
    assert create.status_code == 200
    contract_id = create.json()["contract"]["id"]
    assert create.json()["queued"] is True

    status = client.get("/api/employee-execution/tian-shang/status", headers=owner_headers)
    assert status.status_code == 200
    assert status.json()["employee_id"] == "tianshang"

    processed = client.post("/api/employee-execution/tian-shang/process-next", headers=owner_headers)
    assert processed.status_code == 200
    assert processed.json()["processed"] is True
    assert processed.json()["status"]["progress"] == 100

    contract = client.get(f"/api/employee-execution/contracts/{contract_id}", headers=owner_headers)
    assert contract.status_code == 200
    data = contract.json()
    assert data["status"] == "COMPLETED"
    assert data["result"]["report"]["title"] == "未来30天男士机械表新品建议"
    assert data["result"]["external_actions"] == []

    dashboard = client.get("/api/ceo-dashboard/summary", headers=owner_headers)
    assert dashboard.status_code == 200
    assert dashboard.json()["tian_shang_execution"]["report_available"] is True


def test_tian_shang_api_permissions(client, viewer_headers, operator_headers, owner_headers):
    client.cookies.clear()
    assert client.get("/api/employee-execution/tian-shang/status").status_code == 401
    client.cookies.clear()
    assert client.get("/api/employee-execution/tian-shang/status", headers=viewer_headers).status_code == 403
    client.cookies.clear()
    assert client.post(
        "/api/employee-execution/tian-shang/tasks",
        headers=operator_headers,
        json={"goal": "分析男士机械表市场"},
    ).status_code == 403
    client.cookies.clear()
    assert client.get("/api/employee-execution/tian-shang/status", headers=owner_headers).status_code == 200


def test_sprint26_has_no_external_or_dangerous_calls():
    files = [
        Path("backend/workers/tian_shang_worker.py"),
        Path("backend/employee_execution/ai_planner.py"),
        Path("backend/employee_execution/ai_executor.py"),
        Path("backend/tools/market_search.py"),
        Path("backend/tools/data_analysis.py"),
        Path("backend/tools/report_generator.py"),
        Path("backend/routers/employee_execution.py"),
    ]
    forbidden = [
        "subprocess",
        "os.system",
        "shell=True",
        "requests.",
        "httpx.",
        "webbrowser",
        "selenium",
        "playwright",
        "puppeteer",
        "docker.from_env",
        "git push",
    ]
    for path in files:
        source = path.read_text()
        for needle in forbidden:
            assert needle not in source


def test_sprint26_migration_head_and_table():
    assert "employee_execution_contracts" in set(EmployeeExecutionContract.metadata.tables)
    script = ScriptDirectory.from_config(Config(str(Path("alembic.ini"))))
    assert script.get_heads() == ["0027_v1_schema_alignment"]
