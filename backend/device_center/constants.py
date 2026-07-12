from __future__ import annotations

DEVICE_TYPES = [
    "Mac 测试设备",
    "Windows 测试设备",
    "Linux 测试设备",
    "隔离虚拟桌面",
    "手机测试设备",
]

DEVICE_STATUSES = [
    "待注册",
    "等待批准",
    "已批准",
    "在线",
    "离线",
    "已暂停",
    "已禁用",
    "已撤销",
    "认证失败",
    "版本不兼容",
]

DEVICE_TRUST_LEVELS = ["低", "中", "高", "受控", "测试"]

DEVICE_ENVIRONMENTS = ["test", "staging", "development", "isolated"]

OBSERVATION_STATUSES = [
    "等待设备",
    "等待授权",
    "执行中",
    "已暂停",
    "敏感内容阻断",
    "已完成",
    "已取消",
    "已超时",
    "设备离线",
    "已失败",
]

OBSERVATION_EVENT_TYPES = [
    "window_snapshot",
    "screen_state",
    "suggestion",
    "screenshot",
    "security_event",
]

DEVICE_SECURITY_EVENT_CODES = [
    "SENSITIVE_WINDOW_BLOCKED",
    "SENSITIVE_SCREEN_REGION_DETECTED",
    "INVALID_SIGNATURE",
    "REPLAY_DETECTED",
    "DEVICE_REVOKED",
    "DEVICE_DISABLED",
    "DEVICE_OFFLINE",
    "WINDOW_NOT_ALLOWED",
    "APP_NOT_ALLOWED",
]

DEFAULT_DEVICE_CENTER_FEATURES = {
    "DEVICE_CENTER_ENABLED": False,
    "MAC_DEVICE_AGENT_ENABLED": False,
    "MAC_READONLY_OBSERVER_ENABLED": False,
    "MAC_WINDOW_ENUMERATION_ENABLED": False,
    "MAC_SCREEN_CAPTURE_ENABLED": False,
    "LOCAL_VISION_PROVIDER_ENABLED": False,
    "EXTERNAL_VISION_PROVIDER_ENABLED": False,
}

DEFAULT_MAC_ALLOWED_APPLICATIONS = [
    "VS Code",
    "Chrome",
    "Safari",
    "纯文本测试编辑器",
    "天统 AI 测试页面",
    "隔离演示应用",
]

DEFAULT_MAC_BLOCKED_APPLICATIONS = [
    "Terminal",
    "iTerm",
    "系统设置",
    "钥匙串",
    "密码管理器",
    "邮件",
    "微信",
    "企业微信",
    "钉钉",
    "飞书",
    "银行",
    "支付",
    "App Store",
    "Docker Desktop",
    "SSH",
    "远程桌面",
]

DEFAULT_MAC_ALLOWED_WINDOW_PATTERNS = [
    ".*测试.*",
    ".*隔离.*",
    ".*天统.*",
    ".*VS Code.*",
    ".*Chrome.*",
    ".*Safari.*",
]

DEFAULT_MAC_BLOCKED_WINDOW_PATTERNS = [
    ".*密码.*",
    ".*Password.*",
    ".*验证码.*",
    ".*OTP.*",
    ".*Token.*",
    ".*Secret.*",
    ".*私钥.*",
    ".*Keychain.*",
    ".*钥匙串.*",
    ".*付款.*",
    ".*银行卡.*",
    ".*身份证.*",
    ".*登录凭据.*",
    ".*恢复密钥.*",
    ".*Terminal.*",
    ".*iTerm.*",
]

DEFAULT_MAC_OBSERVER_CAPABILITIES = [
    "window_enumeration",
    "screen_capture",
    "state_summary",
]

DEFAULT_MAC_OBSERVER_WINDOWS = [
    {"application_name": "Chrome", "bundle_id": "com.google.Chrome", "window_title": "天统 AI 测试页面 - 只读观察", "width": 1440, "height": 900, "frontmost": True, "screenshot_allowed": True},
    {"application_name": "VS Code", "bundle_id": "com.microsoft.VSCode", "window_title": "项目代码 - 只读观察", "width": 1680, "height": 1050, "frontmost": False, "screenshot_allowed": True},
]

