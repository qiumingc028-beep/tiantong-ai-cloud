# V2 Mac 安全单步操作架构

## 目标

本 Sprint 只允许在授权的 Mac 测试设备和白名单测试窗口内执行低风险单步操作。

## 调用链

AI 员工 → Skills Engine → Agent Runtime → 设备与会话校验 → 白名单与控件校验 → 风险判断 → 动作预览 → 逐步审批 → 单步执行 → 执行后验证 → 自动暂停 → 审计记录

## 核心边界

- 不允许连续自主控制。
- 不允许真实账号操作。
- 不允许 Terminal、Shell、剪贴板、上传、下载。
- 不允许绕过审批直接执行。
- 不允许窗口变化后继续使用旧审批。

## 相关能力

- computer.macos.observe
- computer.macos.safe_move
- computer.macos.safe_click
- computer.macos.safe_text_input
