from __future__ import annotations

from typing import Final


WORKFLOW_STATUSES: Final[tuple[str, ...]] = (
    "草稿",
    "待校验",
    "等待批准",
    "已批准",
    "执行中",
    "等待关键节点确认",
    "已暂停",
    "已完成",
    "已取消",
    "已超时",
    "已失败",
    "已终止",
)

WORKFLOW_STEP_STATUSES: Final[tuple[str, ...]] = (
    "待执行",
    "等待审批",
    "已批准",
    "执行中",
    "验证中",
    "已完成",
    "已失败",
    "已跳过",
    "已取消",
)

WORKFLOW_APPROVAL_STATUSES: Final[tuple[str, ...]] = (
    "等待审批",
    "已批准",
    "已拒绝",
    "已过期",
)

WORKFLOW_CHECKPOINT_STATUSES: Final[tuple[str, ...]] = (
    "等待审批",
    "已批准",
    "已拒绝",
    "已过期",
)

WORKFLOW_CHECKPOINT_TYPES: Final[tuple[str, ...]] = (
    "执行前确认",
    "页面变化确认",
    "输入前确认",
    "状态异常确认",
    "最终完成确认",
    "人工接管确认",
)

SAFE_CONTINUOUS_ACTIONS: Final[tuple[str, ...]] = (
    "查看屏幕",
    "获取窗口列表",
    "移动鼠标",
    "滚动",
    "截图",
    "等待",
)

WORKFLOW_ACTION_TYPES: Final[tuple[str, ...]] = (
    "查看屏幕",
    "获取窗口列表",
    "激活允许的窗口",
    "移动鼠标",
    "单击",
    "滚动",
    "输入普通文本",
    "按允许的快捷键",
    "截图",
    "等待",
)

DEFAULT_MIN_STEPS = 2
DEFAULT_MAX_STEPS = 5
DEFAULT_MAX_DURATION_SECONDS = 300
DEFAULT_MAX_ACTIONS_PER_MINUTE = 6
DEFAULT_MAX_RETRIES = 1
