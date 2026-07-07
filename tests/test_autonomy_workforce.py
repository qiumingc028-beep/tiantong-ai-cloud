from backend.autonomy.ai_team_coordinator import coordinate_task
from backend.autonomy.self_healing_worker import detect_worker_error
from backend.autonomy.task_allocator import allocate_task
from backend.core.orchestrator import handle_event
from backend.queue_worker import process_next_event
from backend.task_queue import ORCHESTRATOR_QUEUE_NAME, ORCHESTRATOR_STATUS_PREFIX, push_queue
from backend.workflow.router import route_event


def test_task_allocator_assigns_autonomous_team():
    allocation = allocate_task({"task_type": "business_growth", "title": "增长闭环"})

    assert allocation["strategy"] == "multi_agent_autonomous_allocation"
    assert [row["employee_code"] for row in allocation["assignments"]] == [
        "tiancai_data",
        "tiance_strategy",
        "tianjian_test",
        "tiandun_ops",
    ]
    assert allocation["requires_orchestrator"] is True
    assert allocation["requires_tian_shen"] is True


def test_ai_team_coordinator_builds_decision_log_and_child_events():
    coordination = coordinate_task({"id": 7, "task_type": "business_growth", "input": {"topic": "AI经营"}})

    assert coordination["consensus"] == "approved_for_queue"
    assert len(coordination["decision_log"]) == 5
    assert len(coordination["child_events"]) == 4
    assert coordination["child_events"][0]["target"] == "tiancai_data"
    assert coordination["child_events"][2]["target"] == "tianjian_test"
    assert coordination["child_events"][3]["target"] == "tiandun_ops"
    assert coordination["child_events"][0]["payload"]["task_input"]["decision_log"]


def test_workflow_router_maps_autonomy_coordination():
    route = route_event({"source": "api", "target": "autonomy", "action": "coordinate_multi_agent"})

    assert route.handler == "autonomy.coordinate"
    assert route.queue_required is True


def test_orchestrator_coordinates_multi_agent_and_queues_children(test_db):
    response = handle_event(
        {
            "source": "api",
            "target": "autonomy",
            "action": "coordinate_multi_agent",
            "payload": {"id": 9, "task_type": "business_growth", "input": {"topic": "增长"}},
        }
    )
    assert response["queued"] is True

    assert process_next_event(timeout=1) is True
    redis_client = __import__("backend.database", fromlist=["get_redis"]).get_redis()
    assert redis_client.llen(ORCHESTRATOR_QUEUE_NAME) == 4


def test_self_healing_worker_detects_transient_error():
    healing = detect_worker_error({"event_id": "evt-1"}, TimeoutError("Redis timeout reading from socket"))

    assert healing["detected"] is True
    assert healing["retry_recommended"] is True
    assert healing["plan"]["category"] == "transient_queue_error"


def test_queue_worker_records_self_healing_on_failure(test_db):
    queued = push_queue(
        {
            "source": "api",
            "target": "worker.task",
            "action": "process_worker_task",
            "payload": {"task_id": "bad-1", "task_type": "unknown_type", "payload": {}, "attempt": 0, "max_retries": 0},
        },
        {"handler": "worker.process_task"},
        max_retries=0,
    )

    assert process_next_event(timeout=1) is False

    redis_client = __import__("backend.database", fromlist=["get_redis"]).get_redis()
    raw = redis_client.get(f"{ORCHESTRATOR_STATUS_PREFIX}{queued['event_id']}")
    assert raw
    assert "self_healing" in raw
    assert "generic_worker_error" in raw
