from __future__ import annotations

from .approval import create_checkpoint_approval
from .constants import WORKFLOW_CHECKPOINT_TYPES


def checkpoint_type_for_step(step) -> str:
    if step.action_type in {"输入普通文本", "按允许的快捷键", "单击"}:
        return "输入前确认" if step.action_type == "输入普通文本" else "执行前确认"
    return "执行前确认"


def requires_checkpoint(step) -> bool:
    return bool(step.checkpoint_required or step.action_type in {"单击", "输入普通文本", "按允许的快捷键"})
