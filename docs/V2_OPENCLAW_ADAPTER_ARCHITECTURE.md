# V2 OpenClaw 安全适配层架构说明

## 目标

本 Sprint 只实现 OpenClaw 或等效桌面自动化工具的安全适配层，不接入真实用户电脑，不打开真实 Shell，不绕过 Agent Runtime。

## 分层

老板 / Orchestrator
→ AI 员工
→ Skills Engine
→ Agent Runtime
→ 电脑控制权限检查
→ Computer Executor
→ OpenClaw Adapter
→ 隔离桌面环境
→ 截图、动作记录、结果回传
→ Task Center / 审计中心

## 职责边界

- Skills Engine 只负责技能版本、授权与调用入口。
- Agent Runtime 负责执行请求、权限校验、审计与状态回写。
- Computer Executor 负责电脑会话、动作执行、截图和证据。
- OpenClaw Adapter 只负责协议转换，不负责权限判断。
- 隔离桌面环境只允许测试会话，不允许控制真实电脑。

## 默认安全状态

- COMPUTER_CONTROL_ENABLED = false
- OPENCLAW_ADAPTER_ENABLED = false
- COMPUTER_EXECUTOR_ENABLED = false
- ISOLATED_DESKTOP_ENABLED = false
- SCREEN_CAPTURE_ENABLED = false
- HUMAN_TAKEOVER_ENABLED = false

## 设计原则

1. 所有动作必须逐步校验。
2. 高风险动作默认禁止。
3. Terminal / Shell 永久独立阻断。
4. 真实桌面、生产桌面默认不可达。
5. 截图只保存安全引用，不保存大体积 Base64。
6. 审计记录必须完整，但不得泄露 Secret。
