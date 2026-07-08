from __future__ import annotations

from uuid import uuid4

from .safety import clean_list, redact_sensitive_text
from .schemas import SprintRecord, SprintSummaryPayload


DEFAULT_SPRINT_RECORDS = [
    SprintRecord(
        id="sprint26",
        sprint_name="AI员工真实执行闭环 MVP",
        sprint_version="Sprint26-v1.0",
        owner=["天王", "天检", "天监", "天盾"],
        commit_id="629b06289e2003ba20932c99a8e47afc5ed59559",
        changed_files=[
            "backend/employee_execution/",
            "backend/workers/tian_shang_worker.py",
            "backend/tools/",
            "tests/test_sprint26_tian_shang_execution.py",
        ],
        test_result="561 passed",
        deployment_status="passed",
        risk_notes=["内部模拟工具，不自动调用外部 API。"],
    )
]


def list_sprint_records() -> list[SprintRecord]:
    return DEFAULT_SPRINT_RECORDS


def build_sprint_record(payload: SprintSummaryPayload) -> SprintRecord:
    return SprintRecord(
        id=str(uuid4()),
        sprint_name=redact_sensitive_text(payload.sprint_name),
        sprint_version=redact_sensitive_text(payload.sprint_version),
        owner=clean_list(payload.owner),
        commit_id=redact_sensitive_text(payload.commit_id),
        changed_files=clean_list(payload.changed_files),
        test_result=redact_sensitive_text(payload.test_result),
        deployment_status=redact_sensitive_text(payload.deployment_status),
        risk_notes=clean_list(payload.risk_notes),
    )
