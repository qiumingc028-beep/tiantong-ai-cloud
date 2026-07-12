from __future__ import annotations

DEVICE_HEALTH_GRADES = ("健康", "注意", "风险", "不可用")
QUALITY_GRADES = ("优秀", "良好", "合格", "需改进", "不合格")
RISK_GRADES = ("低", "中", "高", "极高")

INCIDENT_STATUSES = ("新发现", "待确认", "处理中", "已隔离", "已解决", "已忽略", "已关闭")
INCIDENT_SEVERITIES = ("提醒", "低", "中", "高", "紧急")

BREAKER_STATUSES = ("正常", "警告", "已熔断", "等待恢复", "人工恢复")

ALERT_DEFAULT_RULES = [
    {"rule_code": "device_offline", "中文名称": "设备离线", "metric_name": "device_online_status", "condition": "equals", "threshold": "离线", "duration_seconds": 0, "severity": "中", "action": "暂停设备", "enabled": True, "environment": "test"},
    {"rule_code": "heartbeat_timeout", "中文名称": "心跳超时", "metric_name": "device_last_heartbeat_age", "condition": "gte", "threshold": "120", "duration_seconds": 120, "severity": "高", "action": "暂停设备", "enabled": True, "environment": "test"},
    {"rule_code": "auth_failure_burst", "中文名称": "高频认证失败", "metric_name": "device_auth_failure_count", "condition": "gte", "threshold": "3", "duration_seconds": 300, "severity": "高", "action": "撤销凭据", "enabled": True, "environment": "test"},
    {"rule_code": "replay_attack", "中文名称": "重放攻击", "metric_name": "device_replay_block_count", "condition": "gte", "threshold": "1", "duration_seconds": 60, "severity": "高", "action": "撤销凭据", "enabled": True, "environment": "test"},
    {"rule_code": "workflow_fail_burst", "中文名称": "工作流连续失败", "metric_name": "workflow_failure_count", "condition": "gte", "threshold": "3", "duration_seconds": 600, "severity": "高", "action": "暂停工作流", "enabled": True, "environment": "test"},
    {"rule_code": "verification_fail_burst", "中文名称": "验证连续失败", "metric_name": "verification_failure_count", "condition": "gte", "threshold": "2", "duration_seconds": 600, "severity": "高", "action": "暂停工作流", "enabled": True, "environment": "test"},
    {"rule_code": "sensitive_window", "中文名称": "敏感窗口出现", "metric_name": "sensitive_window_count", "condition": "gte", "threshold": "1", "duration_seconds": 60, "severity": "高", "action": "请求人工接管", "enabled": True, "environment": "test"},
    {"rule_code": "terminal_attempt", "中文名称": "Terminal 目标尝试", "metric_name": "terminal_attempt_count", "condition": "gte", "threshold": "1", "duration_seconds": 0, "severity": "紧急", "action": "熔断会话", "enabled": True, "environment": "test"},
    {"rule_code": "shell_attempt", "中文名称": "Shell 目标尝试", "metric_name": "shell_attempt_count", "condition": "gte", "threshold": "1", "duration_seconds": 0, "severity": "紧急", "action": "熔断会话", "enabled": True, "environment": "test"},
    {"rule_code": "password_input_attempt", "中文名称": "密码输入尝试", "metric_name": "password_input_attempt_count", "condition": "gte", "threshold": "1", "duration_seconds": 0, "severity": "紧急", "action": "熔断会话", "enabled": True, "environment": "test"},
    {"rule_code": "otp_input_attempt", "中文名称": "验证码输入尝试", "metric_name": "otp_input_attempt_count", "condition": "gte", "threshold": "1", "duration_seconds": 0, "severity": "紧急", "action": "熔断会话", "enabled": True, "environment": "test"},
    {"rule_code": "file_transfer_attempt", "中文名称": "文件上传下载尝试", "metric_name": "file_transfer_attempt_count", "condition": "gte", "threshold": "1", "duration_seconds": 0, "severity": "高", "action": "暂停工作流", "enabled": True, "environment": "test"},
    {"rule_code": "workflow_timeout", "中文名称": "工作流超时", "metric_name": "workflow_timeout_count", "condition": "gte", "threshold": "1", "duration_seconds": 300, "severity": "高", "action": "暂停工作流", "enabled": True, "environment": "test"},
    {"rule_code": "budget_exceeded", "中文名称": "预算超限", "metric_name": "budget_exceeded_count", "condition": "gte", "threshold": "1", "duration_seconds": 300, "severity": "高", "action": "暂停工作流", "enabled": True, "environment": "test"},
    {"rule_code": "local_stop", "中文名称": "本地紧急停止", "metric_name": "local_emergency_stop_count", "condition": "gte", "threshold": "1", "duration_seconds": 0, "severity": "高", "action": "暂停工作流", "enabled": True, "environment": "test"},
    {"rule_code": "risk_high", "中文名称": "风险分数达到高", "metric_name": "risk_score", "condition": "gte", "threshold": "70", "duration_seconds": 0, "severity": "高", "action": "暂停工作流", "enabled": True, "environment": "test"},
    {"rule_code": "risk_extreme", "中文名称": "风险分数达到极高", "metric_name": "risk_score", "condition": "gte", "threshold": "90", "duration_seconds": 0, "severity": "紧急", "action": "熔断会话", "enabled": True, "environment": "test"},
]

