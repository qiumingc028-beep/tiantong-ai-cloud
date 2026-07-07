from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.security.tian_brain.audit_analyzer import analyze_audit_records
from backend.security.tian_shen.approval_engine import POLICY_PATH, load_policy


def build_policy_update(
    policy: dict[str, Any] | None = None,
    audit_records: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    current = deepcopy(policy if policy is not None else load_policy())
    analysis = analyze_audit_records(audit_records)
    green = current.setdefault("green", {})
    allowlist = set(str(row) for row in green.get("allowlist_commands", []))
    proposed_allowlist = []

    for candidate in analysis["yellow_to_green_candidates"]:
        command = candidate["command"]
        if command not in allowlist:
            proposed_allowlist.append(command)

    return {
        "analysis": analysis,
        "proposed_changes": {
            "green_allowlist_additions": proposed_allowlist,
            "red_reinforcement_candidates": analysis["red_reinforcement_candidates"],
        },
        "updated_policy": merge_policy(current, proposed_allowlist),
    }


def self_learning_loop(policy_path: str | Path | None = None, dry_run: bool = True) -> dict[str, Any]:
    path = Path(policy_path) if policy_path else POLICY_PATH
    update = build_policy_update(load_policy(path))
    if dry_run:
        return {"applied": False, **update}

    path.write_text(json.dumps(update["updated_policy"], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"applied": True, **update}


def merge_policy(policy: dict[str, Any], green_allowlist_additions: list[str]) -> dict[str, Any]:
    updated = deepcopy(policy)
    green = updated.setdefault("green", {})
    existing = [str(row) for row in green.get("allowlist_commands", [])]
    merged = sorted(set(existing + green_allowlist_additions))
    if merged:
        green["allowlist_commands"] = merged
    updated.setdefault("tian_brain", {})
    updated["tian_brain"]["last_optimized_at"] = datetime.now(timezone.utc).isoformat()
    updated["tian_brain"]["mode"] = "self_learning_policy_optimizer"
    return updated
