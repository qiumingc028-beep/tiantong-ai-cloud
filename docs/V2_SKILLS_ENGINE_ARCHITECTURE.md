# V2 Skills Engine Architecture

日期：2026-07-12

## 1. 目标

Skills Engine 是 AI 员工技能管理基础层。它负责技能定义、版本、安装、授权、调用、审计，并强制所有技能调用先经过 Agent Runtime。

## 2. 架构边界

调用链：

老板 / Orchestrator → AI 员工 → Skills Engine → 权限与风险校验 → Capability 解析 → Agent Runtime → 执行器 → 结果回传 → 调用记录 → 审计日志

禁止：

- Skill 绕过 Agent Runtime 直接执行
- 未安装 Skill 调用
- 未授权员工调用
- 真实 Shell / 电脑 / 手机 / OpenClaw 默认开启

## 3. 模块组成

- `backend/skills_engine/models.py`
- `backend/skills_engine/schemas.py`
- `backend/skills_engine/registry.py`
- `backend/skills_engine/service.py`
- `backend/skills_engine/installer.py`
- `backend/skills_engine/versioning.py`
- `backend/skills_engine/permissions.py`
- `backend/skills_engine/validator.py`
- `backend/skills_engine/runtime.py`
- `backend/skills_engine/audit.py`

## 4. 核心数据

已定义：

- Skill
- Skill Version
- Skill Installation
- Skill Employee Permission
- Skill Invocation
- Skill Review
- Skill Capability Relation

## 5. 运行策略

- 生产环境默认关闭
- 第三方 Skill 默认禁止
- 未签名 Skill 默认禁止
- 自动更新默认禁止
- 高风险 Skill 必须审批
- 极高风险 Skill 默认拒绝

## 6. 与 Agent Runtime 的关系

Skill 只负责能力编排，不直接触发底层工具。真正执行仍由 Agent Runtime 处理，Skills Engine 只能调用统一入口。

## 7. 后续扩展

后续可以在保持同一安全边界的前提下接入：

- OpenClaw
- 浏览器控制
- 电脑控制
- 手机控制

但这些能力默认仍需关闭，并单独受审批与环境限制控制。
