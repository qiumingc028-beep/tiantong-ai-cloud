from backend.core.orchestrator import handle_event
from backend.queue_worker import process_next_event
from backend.task_queue import ORCHESTRATOR_QUEUE_NAME
from backend.workflow.router import route_event


def test_workflow_router_maps_worker_task_to_worker_handler():
    route = route_event({"source": "worker", "target": "worker.task", "action": "process_worker_task"})
    assert route.handler == "worker.process_task"
    assert route.queue_required is True


def test_workflow_router_maps_tian_cai_and_tian_ce_aliases():
    cai_route = route_event({"source": "worker", "target": "tian_cai", "action": "execute_employee_skill"})
    ce_route = route_event({"source": "worker", "target": "tian_ce", "action": "execute_employee_skill"})
    assert cai_route.target == "tiancai_data"
    assert cai_route.handler == "ai_employee.execute"
    assert ce_route.target == "tiance_strategy"
    assert ce_route.handler == "ai_employee.execute"


def test_handle_event_enqueues_ai_employee_event(test_db):
    response = handle_event(
        {
            "source": "test",
            "target": "tian_ce",
            "action": "execute_employee_skill",
            "payload": {"task_id": 1, "task_type": "strategy_planning", "task_input": {"topic": "growth"}},
        }
    )
    assert response["orchestrated"] is True
    assert response["queued"] is True
    assert response["route"]["target"] == "tiance_strategy"

    redis_client = __import__("backend.database", fromlist=["get_redis"]).get_redis()
    assert redis_client.llen(ORCHESTRATOR_QUEUE_NAME) == 1


def test_queue_worker_executes_queued_ai_employee_event(test_db):
    handle_event(
        {
            "source": "test",
            "target": "tian_ce",
            "action": "execute_employee_skill",
            "payload": {"task_id": 1, "task_type": "strategy_planning", "task_input": {"topic": "growth"}},
        }
    )
    assert process_next_event(timeout=1) is True


def test_handle_event_dispatches_business_logic_through_queue(test_db):
    response = handle_event(
        {
            "source": "api",
            "target": "dual_engine",
            "action": "content_video",
            "payload": {"topic": "AI增长", "views": 1000, "likes": 80},
        }
    )
    assert response["orchestrated"] is True
    assert response["queued"] is True
    assert response["route"]["handler"] == "business.content_video"
    assert process_next_event(timeout=1) is True
