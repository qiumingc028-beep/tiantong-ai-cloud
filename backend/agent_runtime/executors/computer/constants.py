from __future__ import annotations

from typing import Final


SESSION_STATUSES: Final[tuple[str, ...]] = (
    "待创建",
    "等待审批",
    "已创建",
    "执行中",
    "已暂停",
    "等待人工接管",
    "已完成",
    "已取消",
    "已超时",
    "已失败",
    "已关闭",
)

ACTION_TYPES: Final[tuple[str, ...]] = (
    "查看屏幕",
    "获取窗口列表",
    "激活允许的窗口",
    "移动鼠标",
    "单击",
    "双击",
    "滚动",
    "输入普通文本",
    "按允许的快捷键",
    "截图",
    "等待",
    "返回上一步",
    "取消任务",
)

TAKEOVER_STATUSES: Final[tuple[str, ...]] = ("未接管", "等待接管", "已接管", "已释放")

DEFAULT_ALLOWED_APPLICATIONS: Final[tuple[str, ...]] = (
    "隔离测试浏览器",
    "隔离文本编辑器",
    "隔离演示窗口",
)

DEFAULT_BLOCKED_APPLICATIONS: Final[tuple[str, ...]] = (
    "Terminal",
    "iTerm",
    "系统设置",
    "钥匙串",
    "密码管理器",
    "银行应用",
    "支付应用",
    "邮件客户端",
    "通讯软件",
    "远程桌面",
    "SSH 客户端",
    "Docker Desktop",
    "生产运维工具",
)

HIGH_RISK_ACTION_KEYWORDS: Final[tuple[str, ...]] = (
    "删除",
    "覆盖",
    "批量",
    "安装",
    "卸载",
    "支付",
    "下单",
    "发布",
    "提交",
    "密码",
    "验证码",
    "Secret",
    "Token",
    "私钥",
    "Terminal",
    "Shell",
)
