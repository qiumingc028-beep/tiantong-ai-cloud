# V2 Alpha Sprint 11.1 QA 报告

## 结论

**BLOCK。** 已同步最终集成 Commit `b04e872135d6c4fe47824a2b88be78943a9e0531`。17 项失败已关闭 13 项；最终全量仍有 4 项失败，因此未达到零失败门槛，PR #19 必须保持 Draft，不得合并。

## 范围与合规

- 开发分支：`test/v2-alpha-e2e-quality`
- 最终基线：`origin/feature/v2-alpha-workflow-engine` / `b04e872135d6c4fe47824a2b88be78943a9e0531`
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
14. Alpha Service 直接绕过 Orchestrator 拒绝。
15. 模块原生 Span 与工作流 Span ID 关联，禁止终态统一伪造。
16. 审计事件禁止随 Run 级联删除。
17. 安装人、审核人、批准人职责分离及高风险 Skill 禁止自批。
18. Knowledge、Skill Invocation、审计事件逐类恢复幂等。
19. 恢复复用 Root Trace 并新增 recovery child span。
20. Contract 错误码精确匹配。
21. `0039 → 0040` 单 Head 与关键约束检查。

## 测试结果

- 全量命令：`PYTHONDONTWRITEBYTECODE=1 /private/tmp/tiantong-alpha-qa-venv/bin/python -m pytest -q`
- 初始全量结果：**846 passed, 6 failed, 82 warnings in 150.74s**。
- 补强后全量结果：**846 passed, 17 failed, 82 warnings in 156.24s**。
- 最终集成全量结果：**859 passed, 4 failed, 82 warnings in 154.13s**。
- 总数：863，高于 852 与 835 基准；因 4 项失败，不满足“全部通过”。
- 最终 Alpha 专项：28 项中 24 通过、4 失败。
- 原有 Alpha/前端专项基线：8 passed。

## E2E 覆盖阶段

真实集成测试成功贯通 Task Center → Orchestrator → Research → Knowledge Asset → Skills Engine → Agent Runtime → Verification → Audit → Knowledge 引用回流 → Dashboard API，并验证各模块持久化记录可由公开 API 查询。

## 分项判定

| 门禁 | 结果 | 证据摘要 |
|---|---|---|
| 唯一入口/绕过拒绝 | PASS | 仅 `/demo` 为 Alpha 启动入口；伪造模块启动路径返回 404/405 |
| WorkflowContext | PASS | 契约字段、核心 ID、终态和敏感键检查通过 |
| 跨模块 E2E | PASS | 真实 DB 和真实模块服务贯通 |
| Trace 完整性 | FAIL | Event 字段已齐；Root Event 的 parent 错误自指 |
| 审计顺序 | PASS | 时间线有序 |
| 审计不可覆盖 | PASS | ORM 层拒绝 UPDATE；0040 提供数据库触发器 |
| Knowledge 唯一来源 | PASS（正常路径） | 正常闭环只产生一个 Knowledge Asset |
| Skill 版本追踪 | PASS | invocation/version/trace 可关联 |
| 五类失败 | PASS | Research/Knowledge/Skill/Verification/Audit 失败均安全记录 |
| 恢复与幂等 | PASS | 同 Run/Root 恢复；重复请求不重复正式结果 |
| 重复启动 | PASS | 相同幂等键返回同一结果 |
| Feature Flag | PASS | 默认关闭，关闭时 403 |
| V1 隔离 | PASS | 登录、Task Center、Owner Dashboard、Health 均正常 |
| API Contract | PASS（除 Root 关系） | 路径、字段、状态和错误码对齐 |
| 权限不扩张 | PASS | Alpha 源码未引入 Shell/Computer/写 Browser 权限 |
| Migration 静态图 | PASS | 单 Head 为 0040；重复核心表检查通过 |
| Service 绕过 | PASS | 缺少 Orchestrator 证明的直接调用被拒绝 |
| 模块原生 Span | FAIL | 模块事件与 Context Span ID 不关联，audit/feedback 缺失 |
| 审计级联删除 | PASS | Event 保留；模型 RESTRICT 且0040禁止删除 |
| 审批职责分离 | FAIL | 安装、审核、批准身份未分离；高风险 Skill 可自批 |
| 逐类恢复幂等 | PASS | Knowledge、Invocation、Audit 第二次恢复均不增长 |
| 恢复 Root Trace | PASS | 复用 Run、Trace、Root 并创建 recovery child span |
| 错误码精确一致 | PASS | 400/403/404 与最终 Contract 一致 |
| 0039/0040 链 | PASS | 0040 唯一 Head，链和关键约束存在 |

## Migration 验收设计与结果

静态验收通过：`0039 → 0040` 链成立，0040 为唯一 Head，核心 Knowledge/Skill/Trace 表无重复创建，Root/Workflow/Orchestrator/Knowledge/Skill 唯一约束与审计 append-only 触发器存在。

以下官方执行证据尚缺，按职责只能由①提供：

- V1.0.1 基线升级至最新 Head。
- develop-v2 最新 Head 升级。
- `alembic check` 无 Drift。
- 同一数据库重复 `upgrade head` 安全。
- 回退边界与数据保留说明。

## 未覆盖风险

- 未在 PostgreSQL 生产同构环境执行 Migration。
- 未执行真实外部 Research Provider；E2E 使用项目自带确定性公开来源 Reader，但其余模块与数据库均为真实实现。
- 未执行①负责的正式 PostgreSQL Migration；仍需其 Upgrade、Drift、重复执行和结构证据。

## 阻塞项与最小修复建议

详细证据见 `artifacts/qa/alpha-sprint11/failure-evidence.md`。剩余阻塞：Root Event parent 自指；audit/feedback 原生 Span 缺失；安装/审核/批准/启用职责未完整分离；高风险 Skill 允许创建者自批；①正式 Migration 证据尚未提供。③未修改业务代码。

## Merge 建议

**BLOCK**。修复剩余 4 项并补交 Migration 官方证据后，重新执行全部 863+ 项测试；只有零失败才可将 Draft PR #19 改为 Ready for Review。
