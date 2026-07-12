# V2 Alpha Sprint 11.1 QA 报告

## 结论

**BLOCK。** 契约 Commit `3fe8df6065e3ee028cbde14803a9a0020e6a0ba6` 的真实 Alpha 主链路可完成，但发布质量门禁存在 6 项失败。不得合并，业务修复后应在同一测试集复验。

## 范围与合规

- 开发分支：`test/v2-alpha-e2e-quality`
- 基线：`origin/feature/v2-alpha-workflow-engine` / `3fe8df6065e3ee028cbde14803a9a0020e6a0ba6`
- Contract：`docs/contracts/V2_ALPHA_WORKFLOW_CONTEXT.md`、`docs/contracts/V2_ALPHA_WORKFLOW_API.md`
- 修改范围仅为 `tests/`、本文和 `artifacts/qa/alpha-sprint11/`。
- 未修改或执行 `backend/`、`frontend/`、`alembic/`、生产配置及生产环境。

## 新增测试清单

新增 `tests/test_v2_alpha_sprint11_quality_gates.py`，覆盖：

1. 真实 SQLite + HTTP + 真实服务跨模块 E2E（不是全部 Mock）。
2. Orchestrator 唯一入口与模块绕过拒绝。
3. 重复启动幂等/明确拒绝。
4. WorkflowContext 必填 ID、一致性、状态和敏感键检查。
5. Root Trace 唯一、Child Span 父子关系、事件 Trace 一致性。
6. 审计顺序与不可覆盖。
7. Knowledge 唯一来源、Skill 版本与 Trace 引用。
8. Research、Knowledge、Skill、Verification、Audit 五类失败。
9. 安全检查点恢复、重复恢复与正式结果幂等。
10. Feature Flag 默认关闭与 V1 登录/Task/Dashboard/Health 隔离。
11. API 路径、字段、状态与错误码 Contract 对齐。
12. Alembic 单 Head、重复核心表静态检查。
13. Browser/Computer/Shell 权限不扩张静态检查。

## 测试结果

- 全量命令：`PYTHONDONTWRITEBYTECODE=1 /private/tmp/tiantong-alpha-qa-venv/bin/python -m pytest -q`
- 全量结果：**846 passed, 6 failed, 82 warnings in 150.74s**。
- 总数：852，高于 835 基准；因 6 项失败，不满足“全部通过”。
- Alpha 专项：17 项中 11 通过、6 失败（修正 Contract 解析误差后的全量结果）。
- 原有 Alpha/前端专项基线：8 passed。

## E2E 覆盖阶段

真实集成测试成功贯通 Task Center → Orchestrator → Research → Knowledge Asset → Skills Engine → Agent Runtime → Verification → Audit → Knowledge 引用回流 → Dashboard API，并验证各模块持久化记录可由公开 API 查询。

## 分项判定

| 门禁 | 结果 | 证据摘要 |
|---|---|---|
| 唯一入口/绕过拒绝 | PASS | 仅 `/demo` 为 Alpha 启动入口；伪造模块启动路径返回 404/405 |
| WorkflowContext | PASS | 契约字段、核心 ID、终态和敏感键检查通过 |
| 跨模块 E2E | PASS | 真实 DB 和真实模块服务贯通 |
| Trace 完整性 | FAIL | Trace 事件响应缺少 `trace_id` |
| 审计顺序 | PASS | 时间线有序 |
| 审计不可覆盖 | FAIL | ORM UPDATE 可覆盖既有事件 |
| Knowledge 唯一来源 | PASS（正常路径） | 正常闭环只产生一个 Knowledge Asset |
| Skill 版本追踪 | PASS | invocation/version/trace 可关联 |
| 五类失败 | PARTIAL | Research/Knowledge/Skill/Verification 通过；入口 Audit 失败穿透 |
| 恢复与幂等 | FAIL | 重复恢复返回 200 并重复正式结果 |
| 重复启动 | FAIL | 唯一约束异常未转为幂等或明确拒绝 |
| Feature Flag | PASS | 默认关闭，关闭时 403 |
| V1 隔离 | PASS | 登录、Task Center、Owner Dashboard、Health 均正常 |
| API Contract | PASS（除 Trace） | 路径、上下文字段、状态、404 对齐；Trace 字段单列失败 |
| 权限不扩张 | PASS | Alpha 源码未引入 Shell/Computer/写 Browser 权限 |
| Migration 静态图 | FAIL | 单 Head 为 0039，但发现两个旧 revision 重复创建两张 Knowledge 表 |

## Migration 验收设计与结果

已建立只读静态门禁：revision/down_revision 图、单一 Head、核心 Knowledge/Skill/Trace 表重复创建检查、最新 Head 文件确认。当前单 Head 为 `0039_v2_alpha_workflow_unified_contract`，重复表检查失败。

以下官方执行证据尚缺，按职责只能由①提供：

- V1.0.1 基线升级至最新 Head。
- develop-v2 最新 Head 升级。
- `alembic check` 无 Drift。
- 同一数据库重复 `upgrade head` 安全。
- 回退边界与数据保留说明。

## 未覆盖风险

- 未在 PostgreSQL 生产同构环境执行 Migration。
- 未执行真实外部 Research Provider；E2E 使用项目自带确定性公开来源 Reader，但其余模块与数据库均为真实实现。
- 未做并发重复启动/恢复竞争测试；串行路径已失败，暂不扩大测试。
- 审计 append-only 需数据库权限/触发器层证据，当前实现失败。

## 阻塞项与最小修复建议

详细堆栈摘要见 `artifacts/qa/alpha-sprint11/failure-evidence.md`。阻塞项为：启动幂等、Trace 事件字段、审计 append-only、入口 Audit 失败边界、恢复幂等、重复 Knowledge 表与官方 Migration 证据缺失。③未修改业务代码。

## Merge 建议

**BLOCK**。①修复或明确处置 6 项失败，并补交两条升级路径、Drift、重复升级与回退证据后，重新执行全部 852+ 项测试；只有全部通过才可改为 APPROVE。
