from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from backend.security.tian_brain.risk_predictor import predict_risk

from .audit import record_audit


APPROVAL_GREEN = "GREEN"
APPROVAL_YELLOW = "YELLOW"
APPROVAL_RED = "RED"

POLICY_PATH = Path(__file__).with_name("policy.json")


class TianShenApprovalError(RuntimeError):
    def __init__(self, decision: dict[str, Any]):
        self.decision = decision
        super().__init__(decision.get("message") or "TianShen approval blocked this command")


def evaluate_command(event: dict[str, Any], route: dict[str, Any] | None = None) -> dict[str, Any]:
    normalized = event if isinstance(event, dict) else {}
    route_payload = route if isinstance(route, dict) else {}
    policy = load_policy()
    text = _event_text(normalized, route_payload)
    brain_prediction = predict_risk(normalized, route_payload, policy)
    reasons: list[str] = []
    command = _command_text(normalized)
    green_allowlist = [str(row).lower() for row in (policy.get("green") or {}).get("allowlist_commands", [])]
    is_allowlisted = bool(command and command.lower() in green_allowlist)

    red_policy = policy.get("red") or {}
    red_keywords = [str(keyword).lower() for keyword in red_policy.get("keywords", [])]
    matched_red = sorted(keyword for keyword in red_keywords if _matches_policy_keyword(keyword, text))
    if matched_red:
        reasons.extend(f"命中高危动作: {keyword}" for keyword in matched_red)
        decision = _decision(
            APPROVAL_RED,
            False,
            True,
            reasons,
            "blocked",
            normalized,
            route_payload,
            matched_keywords=matched_red,
            policy=policy,
            brain_prediction=brain_prediction,
        )
        record_audit(normalized, decision)
        return decision

    if is_allowlisted:
        decision = _decision(
            APPROVAL_GREEN,
            True,
            False,
            [f"TianBrain allowlist 命中: {command}"],
            "auto_execute",
            normalized,
            route_payload,
            matched_keywords=[],
            policy=policy,
            brain_prediction=brain_prediction,
        )
        record_audit(normalized, decision)
        return decision

    yellow_policy = policy.get("yellow") or {}
    yellow_keywords = [str(keyword).lower() for keyword in yellow_policy.get("keywords", [])]
    yellow_sources = [str(source).lower() for source in yellow_policy.get("sources", [])]
    matched_yellow = sorted(keyword for keyword in yellow_keywords if _matches_policy_keyword(keyword, text))
    surface_hits = sorted(source for source in yellow_sources if _matches_policy_keyword(source, text))
    if normalized.get("requires_boss_confirmation"):
        reasons.append("事件声明需要老板确认")
    if surface_hits:
        reasons.append("命中 AI 命令入口: " + ", ".join(surface_hits))
    for keyword in matched_yellow:
        if keyword not in surface_hits:
            reasons.append(f"命中需确认动作: {keyword}")

    if reasons:
        approved = bool(normalized.get("approval_confirmed") or normalized.get("boss_confirmed"))
        decision = _decision(
            APPROVAL_YELLOW,
            approved,
            not approved,
            reasons,
            "confirm_before_execute",
            normalized,
            route_payload,
            matched_keywords=matched_yellow + surface_hits,
            policy=policy,
            brain_prediction=brain_prediction,
        )
        record_audit(normalized, decision)
        return decision

    decision = _decision(
        APPROVAL_GREEN,
        True,
        False,
        list((policy.get("green") or {}).get("default_reasons") or ["未命中高危或需确认动作，允许自动进入队列"]),
        "auto_execute",
        normalized,
        route_payload,
        matched_keywords=[],
        policy=policy,
        brain_prediction=brain_prediction,
    )
    record_audit(normalized, decision)
    return decision


def load_policy(path: str | Path | None = None) -> dict[str, Any]:
    policy_path = Path(path) if path else POLICY_PATH
    with policy_path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    return data if isinstance(data, dict) else {}


def _decision(
    decision: str,
    allowed: bool,
    requires_confirmation: bool,
    reasons: list[str],
    recommended_action: str,
    event: dict[str, Any],
    route: dict[str, Any],
    matched_keywords: list[str],
    policy: dict[str, Any],
    brain_prediction: dict[str, Any],
) -> dict[str, Any]:
    safe_alternatives = _safe_alternatives(decision, matched_keywords, policy)
    return {
        "center": "TianShen",
        "decision": decision,
        "allowed": allowed,
        "requires_confirmation": requires_confirmation,
        "reasons": reasons,
        "danger_explanation": _danger_explanation(decision, matched_keywords),
        "safe_alternative": safe_alternatives[0] if safe_alternatives else "",
        "alternatives": safe_alternatives,
        "matched_keywords": matched_keywords,
        "tian_brain": brain_prediction,
        "recommended_action": recommended_action,
        "message": _message(decision, allowed, requires_confirmation),
        "source": str(event.get("source") or "unknown"),
        "target": str(event.get("target") or "unknown"),
        "action": str(event.get("action") or "dispatch"),
        "handler": str(route.get("handler") or ""),
    }


def _danger_explanation(decision: str, matched_keywords: list[str]) -> str:
    if decision != APPROVAL_RED:
        return ""
    return "该命令包含可修改系统、提交代码、控制部署、操作浏览器、扣费或改权限的高危动作：" + ", ".join(matched_keywords)


def _safe_alternatives(decision: str, matched_keywords: list[str], policy: dict[str, Any]) -> list[str]:
    if decision == APPROVAL_RED:
        configured = (policy.get("red") or {}).get("safe_alternatives") or {}
        rows = [configured.get(keyword) for keyword in matched_keywords if configured.get(keyword)]
        return rows or ["改为生成只读分析报告和人工审批单，不直接执行高危命令。"]
    if decision == APPROVAL_YELLOW:
        fallback = (policy.get("yellow") or {}).get("safe_alternative")
        return [fallback] if fallback else ["先生成只读计划并等待老板确认。"]
    return []


def _message(decision: str, allowed: bool, requires_confirmation: bool) -> str:
    if decision == APPROVAL_RED:
        return "天审判定 RED：高危命令已阻断"
    if requires_confirmation and not allowed:
        return "天审判定 YELLOW：需要确认后才能执行"
    if decision == APPROVAL_YELLOW:
        return "天审判定 YELLOW：已确认，允许执行"
    return "天审判定 GREEN：允许自动执行"


def _event_text(event: dict[str, Any], route: dict[str, Any]) -> str:
    payload = {
        "source": event.get("source"),
        "target": event.get("target"),
        "action": event.get("action"),
        "tool": event.get("tool"),
        "command": event.get("command"),
        "route": route,
        "payload": event.get("payload"),
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).lower()


def _command_text(event: dict[str, Any]) -> str:
    payload = event.get("payload")
    if event.get("command"):
        return str(event.get("command"))
    if isinstance(payload, dict) and payload.get("command"):
        return str(payload.get("command"))
    return str(event.get("action") or "")


def _matches_policy_keyword(keyword: str, text: str) -> bool:
    if not keyword:
        return False
    if keyword.isalnum() and len(keyword) <= 3:
        return keyword in set(re.findall(r"[a-z0-9]+", text))
    return keyword in text
