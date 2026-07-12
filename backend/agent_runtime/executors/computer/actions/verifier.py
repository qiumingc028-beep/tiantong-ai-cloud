from __future__ import annotations

import hashlib
from uuid import uuid4

from sqlalchemy.orm import Session

from .constants import ACTION_VERIFICATION_STATUSES
from .models import ComputerActionApproval, ComputerActionPlan, ComputerActionVerification


def make_hash(value: str | None) -> str | None:
    if value is None:
        return None
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def verify_action_result(db: Session, *, plan: ComputerActionPlan, approval: ComputerActionApproval, action_result: dict, before_screenshot_reference: str | None, after_screenshot_reference: str | None, current_application: str | None, current_window: str | None, trace_id: str | None):
    verification_status = "结果符合预期"
    if not action_result.get("success", True):
        verification_status = "结果不符合"
    verification = ComputerActionVerification(
        verification_id=uuid4().hex,
        plan_id=plan.plan_id,
        action_id=approval.action_id,
        verification_status=verification_status,
        expected_window=plan.target_window,
        expected_application=plan.target_application,
        before_screenshot_reference=before_screenshot_reference,
        after_screenshot_reference=after_screenshot_reference,
        before_screenshot_hash=approval.before_screenshot_hash,
        after_screenshot_hash=make_hash(after_screenshot_reference),
        result_summary=action_result.get("message") or action_result.get("result") or "执行完成",
        trace_id=trace_id,
    )
    db.add(verification)
    db.flush()
    return verification
