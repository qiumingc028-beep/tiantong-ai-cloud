from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from backend.security.tian_shen.audit import read_audit_records


def analyze_audit_records(records: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    rows = records if records is not None else read_audit_records()
    level_counts = Counter(str(row.get("level") or "unknown") for row in rows)
    source_counts = Counter(str(row.get("source") or "unknown") for row in rows)
    command_counts = Counter(str(row.get("command") or "unknown") for row in rows)
    command_levels: dict[str, Counter] = defaultdict(Counter)
    command_allowed: dict[str, Counter] = defaultdict(Counter)

    for row in rows:
        command = str(row.get("command") or "unknown")
        command_levels[command][str(row.get("level") or "unknown")] += 1
        command_allowed[command]["allowed" if row.get("allowed") else "blocked"] += 1

    return {
        "total": len(rows),
        "by_level": dict(level_counts),
        "by_source": dict(source_counts),
        "repeated_commands": [
            {"command": command, "count": count}
            for command, count in command_counts.most_common()
            if count >= 2
        ],
        "yellow_to_green_candidates": yellow_to_green_candidates(command_levels, command_allowed),
        "red_reinforcement_candidates": red_reinforcement_candidates(command_levels),
    }


def yellow_to_green_candidates(command_levels: dict[str, Counter], command_allowed: dict[str, Counter]) -> list[dict[str, Any]]:
    candidates = []
    for command, levels in command_levels.items():
        yellow_count = levels.get("YELLOW", 0)
        blocked_count = command_allowed[command].get("blocked", 0)
        if yellow_count >= 3 and blocked_count == 0:
            candidates.append(
                {
                    "command": command,
                    "reason": "该命令多次被判定 YELLOW 且均被确认允许，可考虑加入 GREEN allowlist。",
                    "observations": yellow_count,
                }
            )
    return candidates


def red_reinforcement_candidates(command_levels: dict[str, Counter]) -> list[dict[str, Any]]:
    candidates = []
    for command, levels in command_levels.items():
        red_count = levels.get("RED", 0)
        if red_count >= 2:
            candidates.append(
                {
                    "command": command,
                    "reason": "该命令多次触发 RED，应保持或加强阻断规则。",
                    "observations": red_count,
                }
            )
    return candidates
