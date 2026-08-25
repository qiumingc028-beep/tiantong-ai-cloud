from __future__ import annotations

from datetime import datetime, timezone
from json import dumps
from uuid import uuid4

from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.orm import Session

from .constants import (
    DEFAULT_ALPHA_SCENARIO_CODE,
    DEFAULT_ALPHA_SCENARIO_DESCRIPTION,
    DEFAULT_ALPHA_SCENARIO_INPUT,
    DEFAULT_ALPHA_SCENARIO_INPUT_HINT,
    DEFAULT_ALPHA_SCENARIO_TITLE,
)
from .models import AlphaWorkflowScenario


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def default_workflow_template() -> dict[str, object]:
    return {
        "target": "Task → Research → Knowledge → Skills → Workflow → Dashboard",
        "max_steps": 7,
        "auto_continue": False,
        "failure_recovery": "手动恢复",
        "quality_gate": "全链路完成后评分",
    }


def ensure_default_scenarios(
    db: Session,
    *,
    created_by_id: int | None = None,
    commit: bool = True,
) -> list[AlphaWorkflowScenario]:
    scenario = db.query(AlphaWorkflowScenario).filter(AlphaWorkflowScenario.scenario_code == DEFAULT_ALPHA_SCENARIO_CODE).one_or_none()
    if not scenario:
        values = {
            "scenario_id": str(uuid4()),
            "scenario_code": DEFAULT_ALPHA_SCENARIO_CODE,
            "title": DEFAULT_ALPHA_SCENARIO_TITLE,
            "description": DEFAULT_ALPHA_SCENARIO_DESCRIPTION,
            "input_hint": DEFAULT_ALPHA_SCENARIO_INPUT_HINT,
            "default_input_text": DEFAULT_ALPHA_SCENARIO_INPUT,
            "workflow_template_json": dumps(default_workflow_template(), ensure_ascii=False),
            "enabled": True,
            "created_by_id": created_by_id,
        }
        if db.get_bind().dialect.name == "postgresql":
            db.execute(
                postgresql_insert(AlphaWorkflowScenario)
                .values(**values)
                .on_conflict_do_nothing(constraint="uq_alpha_workflow_scenarios_code")
            )
            scenario = db.query(AlphaWorkflowScenario).filter(AlphaWorkflowScenario.scenario_code == DEFAULT_ALPHA_SCENARIO_CODE).one()
        else:
            scenario = AlphaWorkflowScenario(**values)
            db.add(scenario)
            db.flush()
        if commit:
            db.commit()
            db.refresh(scenario)
    return [scenario]


def scenario_to_dict(scenario: AlphaWorkflowScenario) -> dict[str, object]:
    from json import loads

    return {
        "scenario_id": scenario.scenario_id,
        "scenario_code": scenario.scenario_code,
        "title": scenario.title,
        "description": scenario.description,
        "input_hint": scenario.input_hint,
        "default_input_text": scenario.default_input_text,
        "workflow_template": loads(scenario.workflow_template_json) if scenario.workflow_template_json else default_workflow_template(),
        "enabled": bool(scenario.enabled),
        "created_by_id": scenario.created_by_id,
        "created_at": scenario.created_at.isoformat() if scenario.created_at else None,
        "updated_at": scenario.updated_at.isoformat() if scenario.updated_at else None,
    }
