from __future__ import annotations

from typing import Final


ACTION_PLAN_STATUSES: Final[tuple[str, ...]] = (
    "草稿",
    "待校验",
    "等待批准",
    "已批准",
    "执行中",
    "已暂停",
    "已完成",
    "已拒绝",
    "已取消",
    "已超时",
    "已失败",
)

ACTION_APPROVAL_STATUSES: Final[tuple[str, ...]] = (
    "等待审批",
    "已批准",
    "已拒绝",
    "已过期",
)

ACTION_VERIFICATION_STATUSES: Final[tuple[str, ...]] = (
    "结果符合预期",
    "结果部分符合",
    "结果不符合",
    "出现异常窗口",
    "出现敏感内容",
    "无法判断",
)

ACTION_CONTROL_TYPES: Final[tuple[str, ...]] = (
    "普通按钮",
    "单选按钮",
    "复选框",
    "普通文本框",
    "测试页面链接",
    "分页按钮",
    "安全导航控件",
)

SAFE_ACTION_TYPES: Final[tuple[str, ...]] = (
    "移动鼠标",
    "单击",
    "滚动",
    "输入普通文本",
    "按允许的快捷键",
    "等待",
    "截图",
)

SAFE_SHORTCUTS: Final[tuple[str, ...]] = (
    "Tab",
    "Shift+Tab",
    "Escape",
    "Enter",
    "方向上",
    "方向下",
    "方向左",
    "方向右",
)

DEFAULT_FORBIDDEN_TARGETS: Final[tuple[str, ...]] = (
    "提交订单",
    "付款",
    "发布",
    "删除",
    "确认删除",
    "保存密码",
    "登录",
    "退出账号",
    "修改账号",
    "上传文件",
    "下载文件",
    "安装",
    "允许系统权限",
    "管理员授权",
    "生产部署",
    "数据库操作",
)
