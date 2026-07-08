import logging
import json
import os
import time
from datetime import date, datetime, timezone

from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError

from .ai_employees import DEFAULT_COLLECTOR_EMPLOYEE, DEFAULT_STRATEGY_EMPLOYEE, FLOW_EMPLOYEE_CODES, FLOW_TASK_TYPES, employee_name, normalize_employee_code
from .core.orchestrator import handle_event
from .database import SessionLocal, get_redis
from .brain_execution.worker import process_next_execution as process_next_brain_execution
from .execution_engine import process_next_execution_task
from .logging_config import configure_json_logging
from .models import EmployeeLog, JdSyncLog, TaskCenterResult, TaskCenterTask
from .queue_worker import process_next_event
from .queue import dequeue_task, enqueue_task, requeue_task, update_task_status
from .services.ai_store_manager import analyze_store_health
from .services.jd_collectors import (
    JdCollectorError,
    sync_jd_orders,
    sync_jd_products,
    sync_jd_smart,
    sync_jzt,
)
from .workers.tian_shang_worker import process_next_tian_shang_execution


WORKER_HEARTBEAT_KEY = "tiantong:worker:heartbeat"
WORKER_HEARTBEAT_TTL_SECONDS = 120
DAILY_SCHEDULER_PREFIX = "tiantong:scheduler:daily:"
configure_json_logging()
logger = logging.getLogger("tiantong.worker")

SUPPORTED_TASK_TYPES = {
    "sync_jd_smart",
    "sync_jzt",
    "sync_jd_orders",
    "sync_jd_products",
    "ai_store_manager_daily",
    "sprint17_ai_task",
    "sprint18_business_loop",
}
SPRINT17_QUEUE_TYPE = "sprint17_ai_task"
SPRINT18_QUEUE_TYPE = "sprint18_business_loop"


def update_worker_heartbeat():
    try:
        get_redis().setex(WORKER_HEARTBEAT_KEY, WORKER_HEARTBEAT_TTL_SECONDS, datetime.now(timezone.utc).isoformat())
    except (RedisTimeoutError, RedisConnectionError) as exc:
        logger.warning("worker_heartbeat_warning: %s: %s", type(exc).__name__, exc)


def run_daily_scheduler():
    if os.getenv("ENABLE_DAILY_BUSINESS_FLOW", "1") != "1":
        return
    today = date.today().isoformat()
    redis_client = get_redis()
    key = f"{DAILY_SCHEDULER_PREFIX}{today}"
    if redis_client.get(key):
        return
    redis_client.setex(key, 36 * 3600, "created")

    db = SessionLocal()
    try:
        first_employee = DEFAULT_COLLECTOR_EMPLOYEE
        flow_id = f"daily-business-{today}"
        metadata = {
            "sprint17": True,
            "business_loop": True,
            "scheduler": "daily",
            "type": FLOW_TASK_TYPES[first_employee],
            "input": {"source": "daily_scheduler", "date": today, "channels": ["ecommerce", "stock", "content"]},
            "flow_id": flow_id,
            "flow_steps": list(FLOW_EMPLOYEE_CODES),
            "flow_index": 0,
        }
        task = TaskCenterTask(
            title=f"Sprint 17 daily business loop {today}",
            description=json.dumps({"input": metadata["input"]}, ensure_ascii=False),
            status="assigned",
            priority="normal",
            source="sprint17_ai_execution",
            assigned_ai_employee_code=first_employee,
            assigned_ai_employee_name=employee_name(first_employee),
            split_plan=json.dumps(metadata, ensure_ascii=False),
        )
        db.add(task)
        db.commit()
        db.refresh(task)
        enqueue_task(
            SPRINT17_QUEUE_TYPE,
            {"task_center_id": task.id, "assigned_to": first_employee, "metadata": metadata},
            max_retries=1,
            delay_note="Sprint 17 daily business flow queued",
        )
        logger.info("daily_business_flow_created flow_id=%s task_id=%s", flow_id, task.id)
    finally:
        db.close()


def handle_task(task):
    queued = handle_event(
        {
            "source": "worker",
            "target": "worker.task",
            "action": "process_worker_task",
            "payload": task,
        }
    )
    process_next_event(timeout=1, raise_errors=True)
    return queued


def _handle_task_direct(task):
    task_id = task["task_id"]
    task_type = task["task_type"]
    payload = task.get("payload", {})
    attempt = int(task.get("attempt", 0))
    max_retries = int(task.get("max_retries", 3))
    db = SessionLocal()
    log = JdSyncLog(
        store_id=payload.get("store_id"),
        task_id=task_id,
        task_type=task_type,
        status="running",
        attempt=attempt,
        started_at=datetime.now(timezone.utc),
    )
    db.add(log)
    db.commit()
    update_task_status(task_id, "running", task_type, payload, message="任务执行中", attempt=attempt, max_retries=max_retries)
    try:
        if task_type == "sync_jd_smart":
            result = sync_jd_smart(db, int(payload["store_id"]))
        elif task_type == "sync_jzt":
            result = sync_jzt(db, int(payload["store_id"]))
        elif task_type == "sync_jd_orders":
            result = sync_jd_orders(db, int(payload["store_id"]))
        elif task_type == "sync_jd_products":
            result = sync_jd_products(db, int(payload["store_id"]))
        elif task_type == "ai_store_manager_daily":
            result = {"suggestions": analyze_store_health(db)}
            write_employee_log(db, task_type, "success", result, attempt, max_retries)
        elif task_type == SPRINT17_QUEUE_TYPE:
            result = execute_sprint17_task(db, task)
        elif task_type == SPRINT18_QUEUE_TYPE:
            result = execute_sprint18_business_loop(db, task)
        else:
            raise RuntimeError(f"未知任务类型: {task_type}")
        log.status = "success"
        log.message = str(result)
        log.finished_at = datetime.now(timezone.utc)
        db.commit()
        update_task_status(task_id, "success", task_type, payload, message="任务执行成功", attempt=attempt, max_retries=max_retries)
    except Exception as exc:
        db.rollback()
        log.status = "failed"
        log.message = str(exc)
        log.finished_at = datetime.now(timezone.utc)
        db.add(log)
        if task_type == "ai_store_manager_daily":
            write_employee_log(db, task_type, "failed", {"error": str(exc)}, attempt, max_retries)
        db.commit()
        if attempt < max_retries:
            requeue_task(task, f"执行失败，准备重试: {exc}")
        else:
            update_task_status(task_id, "failed", task_type, payload, message=str(exc), attempt=attempt, max_retries=max_retries)
        raise
    finally:
        db.close()


def execute_sprint17_task(db, queued_task: dict) -> dict:
    payload = queued_task.get("payload", {})
    task_id = int(payload["task_center_id"])
    task = db.get(TaskCenterTask, task_id)
    if not task:
        raise RuntimeError(f"Sprint 17 task not found: {task_id}")

    metadata = parse_json(task.split_plan)
    task_input = metadata.get("input")
    assigned_to = normalize_employee_code(task.assigned_ai_employee_code or payload.get("assigned_to")) or "unassigned"
    task.status = "running"
    db.commit()

    result = handle_event(
        {
            "source": "worker",
            "target": assigned_to,
            "action": "execute_employee_skill",
            "force_sync": True,
            "payload": {
                "task_id": task.id,
                "task_type": metadata.get("type") or "mock_task",
                "task_input": task_input,
            },
        }
    )["result"]
    db.add(
        TaskCenterResult(
            task_id=task.id,
            ai_employee_code=assigned_to,
            ai_employee_name=task.assigned_ai_employee_name or employee_name(assigned_to) or assigned_to,
            result_content=json.dumps(result, ensure_ascii=False),
            attachments_json=json.dumps([], ensure_ascii=False),
        )
    )
    task.status = "completed"
    db.commit()
    create_next_flow_task_if_needed(db, task, metadata, result)
    return result


def execute_sprint18_business_loop(db, queued_task: dict) -> dict:
    payload = queued_task.get("payload", {})
    task_id = int(payload["task_center_id"])
    task = db.get(TaskCenterTask, task_id)
    if not task:
        raise RuntimeError(f"Sprint 18 task not found: {task_id}")

    metadata = parse_json(task.split_plan)
    task_input = metadata.get("input") if isinstance(metadata.get("input"), dict) else {}
    event_type = metadata.get("event_type") or "unknown"
    loop_iteration = int(metadata.get("loop_iteration") or 0)

    task.status = "running"
    db.commit()

    result = build_sprint18_business_result(task.id, event_type, task_input, loop_iteration)
    db.add(
        TaskCenterResult(
            task_id=task.id,
            ai_employee_code=normalize_employee_code(task.assigned_ai_employee_code) or DEFAULT_STRATEGY_EMPLOYEE,
            ai_employee_name=task.assigned_ai_employee_name or employee_name(DEFAULT_STRATEGY_EMPLOYEE),
            result_content=json.dumps(result, ensure_ascii=False),
            attachments_json=json.dumps([], ensure_ascii=False),
        )
    )
    task.status = "completed"
    db.commit()

    create_sprint18_feedback_task_if_needed(db, task, metadata, result)
    return result


def build_sprint18_business_result(task_id: int, event_type: str, task_input: dict, loop_iteration: int) -> dict:
    analysis = analyze_sprint18_business_event(event_type, task_input)
    decision = decide_sprint18_business_actions(event_type, analysis)
    execution = mock_execute_sprint18_decision(decision)
    return {
        "task_id": task_id,
        "event_type": event_type,
        "input": task_input,
        "analysis": analysis,
        "decision": decision,
        "execution": execution,
        "feedback_loop": {
            "reusable_as_input": True,
            "loop_iteration": loop_iteration,
            "next_input": {
                "source_task_id": task_id,
                "source_event_type": event_type,
                "decision": decision,
                "execution": execution,
            },
            "next_research_focus": decision.get("optimization_focus"),
        },
        "mode": "sprint18_business_mock",
        "executed_at": datetime.now(timezone.utc).isoformat(),
    }


def analyze_sprint18_business_event(event_type: str, task_input: dict) -> dict:
    if event_type == "ecommerce_order":
        quantity = safe_number(task_input.get("quantity"), default=1)
        amount = safe_number(task_input.get("amount"), default=0)
        unit_price = round(amount / quantity, 2) if quantity else amount
        return {
            "summary": "电商订单触发：识别成交商品、客单价和复购线索。",
            "signal_type": "order_conversion",
            "product": {
                "sku": task_input.get("sku") or "unknown",
                "name": task_input.get("product_name") or task_input.get("sku") or "unknown",
                "quantity": quantity,
                "amount": amount,
                "unit_price": unit_price,
            },
            "customer_tags": task_input.get("customer_tags") or [],
            "confidence": "medium",
        }
    if event_type == "content_metrics":
        views = safe_number(task_input.get("views"))
        likes = safe_number(task_input.get("likes"))
        comments = safe_number(task_input.get("comments"))
        shares = safe_number(task_input.get("shares"))
        engagement = likes + comments + shares
        engagement_rate = round(engagement / views, 4) if views else 0
        return {
            "summary": "内容数据触发：识别互动率、传播潜力和内容复用价值。",
            "signal_type": "content_performance",
            "content": {
                "content_id": task_input.get("content_id") or "unknown",
                "title": task_input.get("title") or "未命名内容",
                "views": views,
                "engagement": engagement,
                "engagement_rate": engagement_rate,
            },
            "confidence": "medium",
        }
    if event_type == "file_upload":
        rows = task_input.get("rows") if isinstance(task_input.get("rows"), list) else []
        return {
            "summary": "文件上传触发：提取结构化行数、文件类型和人工摘要。",
            "signal_type": "uploaded_dataset",
            "file": {
                "filename": task_input.get("filename") or "unknown",
                "file_type": task_input.get("file_type") or "unknown",
                "row_count": len(rows),
                "content_summary": task_input.get("content_summary") or "暂无摘要",
            },
            "confidence": "low" if not rows else "medium",
        }
    if event_type == "feedback_replay":
        return {
            "summary": "反馈循环触发：基于历史结果和新增反馈重新生成优化建议。",
            "signal_type": "feedback_loop",
            "previous_result": task_input.get("previous_result"),
            "feedback": task_input.get("feedback"),
            "confidence": "medium",
        }
    return {
        "summary": "通用业务事件触发：进入保守策略分析。",
        "signal_type": "generic_business_event",
        "payload": task_input,
        "confidence": "low",
    }


def decide_sprint18_business_actions(event_type: str, analysis: dict) -> dict:
    if event_type == "ecommerce_order":
        product = analysis.get("product") or {}
        unit_price = safe_number(product.get("unit_price"))
        return {
            "selected_product": product.get("sku"),
            "pricing_strategy": {
                "suggested_price": round(unit_price * 1.08, 2) if unit_price else 0,
                "reason": "基于当前成交价做 8% 价格弹性测试，需人工确认后执行。",
            },
            "content_strategy": "围绕已成交商品生成复购和使用场景内容。",
            "ad_strategy": "建议建立人工审核的低预算复购测试计划，不自动投放。",
            "optimization_focus": "复购转化",
            "requires_human_approval": True,
        }
    if event_type == "content_metrics":
        content = analysis.get("content") or {}
        rate = safe_number(content.get("engagement_rate"))
        return {
            "selected_product": "由人工从相关商品池选择",
            "pricing_strategy": {"suggested_price": None, "reason": "内容数据不直接改价。"},
            "content_strategy": "复用高互动主题，生成短视频脚本和商品详情页角度。",
            "ad_strategy": "互动率达到阈值后建议人工创建投放实验。",
            "optimization_focus": "内容转化" if rate >= 0.03 else "内容钩子优化",
            "requires_human_approval": True,
        }
    if event_type == "file_upload":
        file_info = analysis.get("file") or {}
        return {
            "selected_product": "从上传文件中人工确认候选商品",
            "pricing_strategy": {"suggested_price": None, "reason": "上传文件仅用于研究，不自动改价。"},
            "content_strategy": f"基于 {file_info.get('filename')} 生成数据洞察摘要。",
            "ad_strategy": "仅输出投放研究建议，不修改预算。",
            "optimization_focus": "数据清洗与候选机会识别",
            "requires_human_approval": True,
        }
    if event_type == "feedback_replay":
        return {
            "selected_product": "沿用上一轮业务对象",
            "pricing_strategy": {"suggested_price": None, "reason": "反馈循环只生成二次优化建议。"},
            "content_strategy": "根据反馈收敛内容卖点和执行顺序。",
            "ad_strategy": "根据反馈调整人工审核的实验方案。",
            "optimization_focus": "反馈闭环优化",
            "requires_human_approval": True,
        }
    return {
        "selected_product": None,
        "pricing_strategy": {"suggested_price": None, "reason": "未知事件不自动定价。"},
        "content_strategy": "先进入人工研究。",
        "ad_strategy": "不自动投放。",
        "optimization_focus": "风险识别",
        "requires_human_approval": True,
    }


def mock_execute_sprint18_decision(decision: dict) -> dict:
    return {
        "status": "mock_executed",
        "writes_database": True,
        "external_actions": [],
        "task_status_updated": True,
        "records": [
            {
                "action": "write_strategy_result",
                "status": "completed",
                "detail": "策略结果已写入 TaskCenterResult。",
            },
            {
                "action": "manual_review_required",
                "status": "pending_human",
                "detail": "定价、投放、发布、付款均需人工确认。",
            },
        ],
        "safety_boundary": [
            "不调用外部 API",
            "不自动付款",
            "不自动投放广告",
            "不自动发布内容",
            "不修改权限",
        ],
        "decision_snapshot": decision,
    }


def create_sprint18_feedback_task_if_needed(db, task: TaskCenterTask, metadata: dict, previous_result: dict) -> None:
    if not metadata.get("auto_optimize"):
        return
    loop_iteration = int(metadata.get("loop_iteration") or 0)
    if loop_iteration >= 1:
        return

    next_metadata = {
        "sprint18": True,
        "event_type": "feedback_replay",
        "input": {
            "previous_result": previous_result,
            "feedback": {"source": "auto_optimize", "note": "一次性闭环优化任务"},
        },
        "loop_id": metadata.get("loop_id"),
        "loop_iteration": loop_iteration + 1,
        "auto_optimize": False,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    next_task = TaskCenterTask(
        title="Sprint 18 business loop: feedback_replay",
        description=json.dumps({"input": next_metadata["input"]}, ensure_ascii=False),
        status="assigned",
        priority="normal",
        source="sprint18_business_loop",
        parent_task_id=task.id,
        assigned_ai_employee_code=DEFAULT_STRATEGY_EMPLOYEE,
        assigned_ai_employee_name=employee_name(DEFAULT_STRATEGY_EMPLOYEE),
        split_plan=json.dumps(next_metadata, ensure_ascii=False),
    )
    db.add(next_task)
    db.commit()
    db.refresh(next_task)
    enqueue_task(
        SPRINT18_QUEUE_TYPE,
        {"task_center_id": next_task.id, "metadata": next_metadata},
        max_retries=1,
        delay_note="Sprint 18 feedback loop queued",
    )


def safe_number(value, default: float = 0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def create_next_flow_task_if_needed(db, task: TaskCenterTask, metadata: dict, previous_result: dict) -> None:
    steps = metadata.get("flow_steps") or []
    index = metadata.get("flow_index")
    if not steps or index is None or int(index) >= len(steps) - 1:
        return

    next_index = int(index) + 1
    next_employee = normalize_employee_code(steps[next_index]) or steps[next_index]
    next_type = FLOW_TASK_TYPES.get(next_employee, "mock_task")
    next_metadata = {
        "sprint17": True,
        "type": next_type,
        "input": previous_result,
        "flow_id": metadata.get("flow_id"),
        "flow_steps": steps,
        "flow_index": next_index,
        "business_loop": metadata.get("business_loop", False),
    }
    next_task = TaskCenterTask(
        title=f"Sprint 17 flow {metadata.get('flow_id')} step {next_index + 1}/{len(steps)}",
        description=json.dumps({"input": previous_result}, ensure_ascii=False),
        status="assigned",
        priority="normal",
        source="sprint17_ai_execution",
        parent_task_id=task.id,
        assigned_ai_employee_code=next_employee,
        assigned_ai_employee_name=employee_name(next_employee) or next_employee,
        split_plan=json.dumps(next_metadata, ensure_ascii=False),
    )
    db.add(next_task)
    db.commit()
    db.refresh(next_task)
    enqueue_task(
        SPRINT17_QUEUE_TYPE,
        {
            "task_center_id": next_task.id,
            "assigned_to": next_employee,
            "metadata": next_metadata,
        },
        max_retries=1,
        delay_note="Sprint 17 flow next step queued",
    )


def parse_json(value: str | None) -> dict:
    try:
        data = json.loads(value or "{}")
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def write_employee_log(db, task_type: str, status: str, detail: dict, attempt: int, max_retries: int):
    db.add(
        EmployeeLog(
            action=task_type,
            detail=str(
                {
                    "status": status,
                    "detail": detail,
                    "retry_count": attempt,
                    "max_retries": max_retries,
                    "last_executed_at": datetime.now(timezone.utc).isoformat(),
                }
            ),
        )
    )


def main():
    while True:
        update_worker_heartbeat()
        run_daily_scheduler()
        if not process_next_tian_shang_worker_execution() and not process_next_employee_execution() and not process_next_brain_runtime_execution():
            process_next_task()
        time.sleep(0.1)


def process_next_tian_shang_worker_execution():
    db = SessionLocal()
    try:
        return process_next_tian_shang_execution(db, timeout=1)
    except (RedisTimeoutError, RedisConnectionError) as exc:
        logger.warning("tian_shang_queue_warning: %s: %s", type(exc).__name__, exc)
        return False
    except Exception as exc:
        logger.exception("tian_shang_execution_failed: %s", exc)
        return False
    finally:
        db.close()


def process_next_employee_execution():
    db = SessionLocal()
    try:
        return process_next_execution_task(db, timeout=1, worker_id="employee_worker")
    except (RedisTimeoutError, RedisConnectionError) as exc:
        logger.warning("execution_queue_warning: %s: %s", type(exc).__name__, exc)
        return False
    except Exception as exc:
        logger.exception("employee_execution_failed: %s", exc)
        return False
    finally:
        db.close()


def process_next_brain_runtime_execution():
    db = SessionLocal()
    try:
        result = process_next_brain_execution(db, timeout=1)
        return bool(result.get("processed"))
    except (RedisTimeoutError, RedisConnectionError) as exc:
        logger.warning("brain_execution_queue_warning: %s: %s", type(exc).__name__, exc)
        return False
    except Exception as exc:
        logger.exception("brain_execution_failed: %s", exc)
        return False
    finally:
        db.close()


def process_next_task():
    try:
        task = dequeue_task(timeout=5)
    except (RedisTimeoutError, RedisConnectionError) as exc:
        logger.warning("redis_queue_warning: %s: %s", type(exc).__name__, exc)
        time.sleep(2)
        return False
    if not task:
        return False
    try:
        handle_task(task)
    except JdCollectorError as exc:
        logger.warning("collector_task_incomplete: %s", exc)
    except Exception as exc:
        logger.exception("worker_task_failed: %s", exc)
    return True


if __name__ == "__main__":
    main()
