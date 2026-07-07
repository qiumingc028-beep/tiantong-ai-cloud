from __future__ import annotations

from datetime import datetime, timezone

from .registry import TIANBO, TIANCAI_DATA, TIANCE_STRATEGY, TIANSHU, normalize_employee_code


def execute_employee_skill(task_id: int, task_type: str, assigned_to: str, task_input) -> dict:
    employee_code = normalize_employee_code(assigned_to) or "unassigned"
    if employee_code == TIANCAI_DATA:
        payload = tiancai_collect_data(task_input)
    elif employee_code == TIANSHU:
        payload = tianshu_analyze_data(task_input)
    elif employee_code == TIANCE_STRATEGY:
        payload = tiance_generate_strategy(task_input)
    elif employee_code == TIANBO:
        payload = tianbo_generate_content(task_input)
    else:
        payload = {"output": f"{employee_code} mock executed {task_type}", "input": task_input}
    return {
        "task_id": task_id,
        "type": task_type,
        "assigned_to": employee_code,
        "input": task_input,
        "payload": payload,
        "output": payload.get("summary") or payload.get("output") or f"{employee_code} completed {task_type}",
        "executed_at": datetime.now(timezone.utc).isoformat(),
        "mode": "business_mock",
        "reusable_as_input": True,
    }


def tiancai_collect_data(task_input) -> dict:
    source = task_input if isinstance(task_input, dict) else {}
    return {
        "summary": "天采完成电商/股票/内容模拟数据抓取",
        "records": [
            {"channel": "ecommerce", "name": "爆款A", "sales": 1280, "growth": 0.18, "sentiment": 0.76},
            {"channel": "stock", "name": "AI供应链指数", "price": 42.6, "growth": 0.035, "sentiment": 0.61},
            {"channel": "content", "name": "短视频选题", "views": 56000, "growth": 0.24, "sentiment": 0.82},
        ],
        "source_request": source,
    }


def tianshu_analyze_data(task_input) -> dict:
    records = extract_records(task_input)
    growth_values = [float(row.get("growth", 0)) for row in records if isinstance(row, dict)]
    avg_growth = round(sum(growth_values) / len(growth_values), 4) if growth_values else 0
    top_item = max(records, key=lambda row: float(row.get("growth", 0))) if records else {}
    return {
        "summary": "天数完成基础数据分析",
        "record_count": len(records),
        "average_growth": avg_growth,
        "top_growth_item": top_item,
        "insight": "内容与电商增长较强，适合进入策略和内容生成链路。",
    }


def tiance_generate_strategy(task_input) -> dict:
    analysis = task_input if isinstance(task_input, dict) else {}
    return {
        "summary": "天策生成策略建议",
        "strategy": [
            "优先围绕高增长内容选题生成短视频脚本",
            "将电商爆款A作为转化承接商品",
            "保留股票/行业指标作为市场趋势背景，不自动交易",
        ],
        "risk_control": ["不自动投放广告", "不自动下单", "不修改预算"],
        "based_on": analysis,
    }


def tianbo_generate_content(task_input) -> dict:
    strategy = task_input if isinstance(task_input, dict) else {}
    return {
        "summary": "天播生成结构化内容",
        "content": {
            "title": "AI供应链趋势下的爆款增长机会",
            "hook": "一个内容选题同时带动电商与品牌增长。",
            "script": ["开场提出趋势", "展示爆款A与内容热度", "给出行动建议", "提醒风险边界"],
            "cta": "进入人工复核后再发布。",
        },
        "based_on": strategy,
    }


def extract_records(task_input) -> list[dict]:
    if isinstance(task_input, dict):
        if isinstance(task_input.get("records"), list):
            return [row for row in task_input["records"] if isinstance(row, dict)]
        payload = task_input.get("payload")
        if isinstance(payload, dict) and isinstance(payload.get("records"), list):
            return [row for row in payload["records"] if isinstance(row, dict)]
        source = task_input.get("source_result")
        if isinstance(source, dict):
            return extract_records(source)
    return []
