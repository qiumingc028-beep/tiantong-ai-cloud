# V2 Alpha Sprint 11.1 QA 报告

## Migration Evidence Automated Gate

自动门禁已建立于 `tests/test_v2_alpha_migration_evidence.py`，机器可读当前结果位于 `artifacts/qa/alpha-sprint11/migration-evidence-validation.json`。

门禁会自动验证：6个必需文件、0041最终Head一致性、两条独立PostgreSQL路径的完整字段与命令、禁用SQLite正式证据和Drift跳过变量、SHA256复算及覆盖率、V1.0.1的0001—0027逐文件字节一致性、0005专项一致性、0037冻结政策披露，以及密码/Token/Secret/完整连接串/生产数据扫描。

当前①最终文件尚未到达，因此机器结果为 `BLOCK`，相关测试会明确失败而非skip或xfail。收到 `MIGRATION_EVIDENCE_FINAL_COMMIT` 后立即普通Merge并执行门禁；如Backend或Migration有变化，再执行不少于863项的全量回归。本门禁不修改业务实现、Migration、Contract或CI配置，也不降低任何既有测试标准。

## PR #17 fa9067 新证据阻塞矩阵（等待最终证据 Commit）

只读审计时间：2026-07-13。审计对象：PR #17，Head `fa9067fac27ac44264bf4c4df706ccb23366f987`。该 Head 已修改 Migration、Alembic Env 与 Backend Models，因此此前 `eef1ed6` 上的 `863 passed, 0 failed` 不能作为 `fa9067` 的完整回归证明。

| 检查项 | 当前结果 | 远程事实/缺失项 |
|---|---|---|
| Head/文档一致性 | BLOCK | PR描述声明最终Head为0041，但旧 `artifacts/alpha-migration-evidence/alembic-evidence.txt` 仍记录0040 |
| 路径A日志 | BLOCK | PR #17远程变更文件中未找到 `path_a_current.log` |
| 路径B日志 | BLOCK | PR #17远程变更文件中未找到 `path_b_current.log` |
| Checksums | BLOCK | 未找到 `checksums.sha256`，无法复算证据完整性 |
| Migration冻结政策 | BLOCK | 未找到独立的Migration Freeze Policy文件 |
| 0037历史修改 | BLOCK | `0037_v2_execution_observability_security_ops.py` 被直接修改，需冻结政策明确其预发布边界并如实披露 |
| V1 0001—0027 | BLOCK | 需逐文件Hash证明；尤其0005必须与V1.0.1完全一致 |
| PostgreSQL双路径 | BLOCK | PR描述有结论，但缺少两套独立PostgreSQL数据库的完整原始日志 |
| Drift/重复升级/回退 | BLOCK | 缺少可复核的0041原始命令输出和校验和 |
| GitHub CI | BLOCK | `fa9067` combined status返回空列表，无CI Run/Status证据 |

在①提供 `MIGRATION_EVIDENCE_FINAL_COMMIT` 前，PR #19保持 Draft/BLOCK。最终Commit必须使文档、日志、Checksums、PR描述、Git历史和真实PostgreSQL Schema完全一致；若修改Backend或Migration，必须重新执行不少于863项的全量零失败回归。

## 结论

**BLOCK（代码零失败，Migration证据未通过）。** 已同步最终 Commit `eef1ed66638011503c7377d52104258b72ee80d0`。全量 `863 passed, 0 failed`，所有代码质量门禁均关闭；但①提供的Migration证据存在历史文件变更声明矛盾和Drift绕过开关，PR #19必须保持Draft。

## 范围与合规

- 开发分支：`test/v2-alpha-e2e-quality`
- 最终基线：`origin/feature/v2-alpha-workflow-engine` / `eef1ed66638011503c7377d52104258b72ee80d0`
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
- 最终修复全量结果：**863 passed, 0 failed, 82 warnings in 158.92s**。
- 总数：863，满足数量和零失败标准。
- 最终 Alpha/质量专项：31 passed。
- 原有 Alpha/前端专项基线：8 passed。

## E2E 覆盖阶段

真实集成测试成功贯通 Task Center → Orchestrator → Research → Knowledge Asset → Skills Engine → Agent Runtime → Verification → Audit → Knowledge 引用回流 → Dashboard API，并验证各模块持久化记录可由公开 API 查询。

## 分项判定

| 门禁 | 结果 | 证据摘要 |
|---|---|---|
| 唯一入口/绕过拒绝 | PASS | 仅 `/demo` 为 Alpha 启动入口；伪造模块启动路径返回 404/405 |
| WorkflowContext | PASS | 契约字段、核心 ID、终态和敏感键检查通过 |
| 跨模块 E2E | PASS | 真实 DB 和真实模块服务贯通 |
| Trace 完整性 | PASS | Root parent为NULL，audit/feedback原生Span存在且无循环 |
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
| 模块原生 Span | PASS | audit/feedback及各模块Span完成关联 |
| 审计级联删除 | PASS | Event 保留；模型 RESTRICT 且0040禁止删除 |
| 审批职责分离 | PASS | 安装/审核/批准分离，高风险创建者自批被拒绝 |
| 逐类恢复幂等 | PASS | Knowledge、Invocation、Audit 第二次恢复均不增长 |
| 恢复 Root Trace | PASS | 复用 Run、Trace、Root 并创建 recovery child span |
| 错误码精确一致 | PASS | 400/403/404 与最终 Contract 一致 |
| 0039/0040 链 | PASS | 0040 唯一 Head，链和关键约束存在 |

## Migration 验收设计与结果

0040静态结构验收通过：`0039 → 0040` 链成立，0040为唯一Head，唯一约束与append-only触发器存在。正式证据验收失败：历史Migration未修改的声明与Git差异矛盾；Drift检查使用跳过开关；缺少V1.0.1与develop-v2前一Head两条独立、可复核升级证据。

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

详细证据见 `artifacts/qa/alpha-sprint11/failure-evidence.md`。代码阻塞全部关闭。唯一剩余阻塞为Migration正式证据不自洽/不完整。③未修改业务代码或执行Migration。

## Merge 建议

**BLOCK**。代码测试已满足APPROVE条件，但必须先补交无绕过且与Git历史一致的Migration正式证据；证据通过后方可将PR #19转为Ready for Review。
