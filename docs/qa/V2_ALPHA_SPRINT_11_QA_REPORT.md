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
## Migration Evidence Gate 预验收（cc8c779）

测试分支已普通合并 `cc8c77914dbc79a6821d8781f626b77a003b4f7f`，未使用 force push。自动门禁结果为 **2 passed, 7 failed**；由于 Gate 未通过，本轮按验收约定未运行完整 863 项回归。

### 已关闭项

- V1 Migration 0001—0027 与 `v1.0.1` 逐文件字节一致。
- `0005_knowledge_center_tables.py` 已重新验证通过，不再是阻塞项。
- 0025、0026、0027 均与 `v1.0.1` 一致。

### 当前仍失败项

- 缺少 `artifacts/alpha-migration-evidence/path_a_current.log`。
- 缺少 `artifacts/alpha-migration-evidence/path_b_current.log`。
- 缺少 `docs/V2_MIGRATION_FREEZE_POLICY.md`。
- `checksums.sha256` 使用 `/private/tmp/tiantong-v2-sprint10-observability/...` 绝对路径，不符合相对路径要求；且所列 Path A/B 文件不存在，无法完整复算和覆盖全部必需证据。
- 0037 虽在现有摘要中提及，但因冻结政策缺失，无法满足“政策与证据文档双重披露”门禁。
- 0041 在现有摘要和证据文档中出现，但 Path A/B 原始日志缺失，无法证明全链路一致。
- 已存在文件未发现明文 Secret 或跳过变量；但必需文件缺失使敏感信息扫描及 SQLite/Skip 全量检查无法最终通过。

### 等待①补充项

等待 `MIGRATION_EVIDENCE_FINAL_COMMIT` 提供两条 PostgreSQL 原始日志、冻结政策，以及使用仓库相对路径且可完整复算的 Checksums。PR #19 保持 Draft/BLOCK，不降低门禁标准。
## Alpha 前端契约防回退门禁

新增 `tests/test_v2_alpha_frontend_contract_regression.py`，以 PR #18 最终前端 Commit `04804fc62f57305b4bc3f45dbe7bc051bab0cfb4` 为审查基线，使用 Git 对象和仓库相对路径，不依赖未推送文件或本机绝对路径。

门禁精确禁止废弃字段及状态机副本，允许 `STAGE_LABELS`、`skill_version_id`、`root_span_id`、`report_content`、`approval_ids`；并验证报告、恢复、取消由服务端字段控制，阶段按服务端 spans/events 顺序渲染，Root Span 显示“根节点（无父级）”。PR #18 相对最终后端基线的变更范围严格为四个 Alpha 前端文件。
## Migration Gate 硬化整改

Gate实现已整改：Checksum只接受仓库相对路径，直接拒绝绝对路径、`..`逃逸和ROOT外解析结果；已移除basename回退，并要求精确覆盖全部Required Files且禁止校验Checksum自身。

Path A/B现要求顶部结构化 `key=value` 元数据及独立RAW OUTPUT区域，验证数据库标识、不同起点、相同 `validated_code_commit`、规定结果值和原始命令输出一致性。`validated_code_commit` 必须为有效Git Commit且为远程主功能分支Head祖先，其后至Head仅允许证据文件变化；Backend或Alembic变化会直接BLOCK并要求重测。Evidence Bundle不再被要求自引用自身Commit。

0037披露现要求Freeze Policy与Evidence Document同时给出完整路径、基线Commit/Hash、修改后Hash、Boolean `server_default`变化、原因、生产部署状态、预发布例外、批准角色和Sprint 11.1后冻结规则，并逐字段一致。

硬化后使用当前旧证据运行结果：**2 passed, 9 failed**，符合预期BLOCK；前端契约Gate复验：**10 passed, 0 failed**。PR #19继续Draft/BLOCK，等待①最终证据。
## 85586868 Migration Gate 预执行

测试分支已普通合并 `85586868bad3dd5d0fecba5f840383feccdc1c78`，未Force Push。硬化Gate结果：**5 passed, 8 failed**；因此未启动Backend全量回归。

精确阻塞：Path A/B均未采用规定的结构化头和RAW OUTPUT分区。Path A声称起点 `483ebf5`，但 `v1.0.1^{commit}` 为 `60335cdb5eec9975b03c6d19b34c8669a96e8cc3`，且日志的 `current_after_v1` 已是0041而非0027。Path B声称起点等于被验证代码 `cc8c779`，而其与 `origin/develop-v2` 的merge-base为 `2ca1a2579569324ce3ca82f68332fb7f96be004d`。

Freeze Policy缺少0037完整路径及八项结构化披露。Checksums虽已使用相对路径，但Freeze Policy Hash不匹配，缺少 `validation-manifest.json`，且包含Required Files集合外的README/Migration条目。Manifest缺少 `evidence_format_version`、`validated_code_commit`、`final_revision`、`checksum_algorithm`、`required_files`、`path_a`、`path_b`。

结论：Draft/BLOCK，等待①的 `MIGRATION_EVIDENCE_FINAL_COMMIT`；Gate全绿前不运行863+全量测试。
## PR #18 网络错误防回退同步

前端固定审查Head已更新为 `2306c5ef7e0444fa41b7b58ce86595065547f3c4`。门禁新增验证：fetch异常被捕获并转换为“网络连接失败，请检查网络后重试。”；前端源码不直接暴露 `Failed to fetch`；HTTP非2xx继续优先使用后端 `detail`；401登录跳转、`available_actions`及`report_content`所有权保持不变。PR #18范围以其与主功能分支的Git merge-base计算，仍必须严格等于四个Alpha前端文件。
## PostgreSQL历史升级与唯一约束回归准备

新增真实PostgreSQL专项 `tests/test_v2_alpha_postgresql_migration_regression.py`。测试要求隔离数据库管理员连接及 `MIGRATION_CODE_FIX_COMMIT`，从真实Git merge-base归档执行到0037以复现Boolean默认值数据库错误，再使用已合并修复代码升级至Head；全程禁止SQLite与Drift跳过。

最终Head验收从 `pg_constraint` 读取约束名称和有序列集合，逐约束执行真实重复INSERT并要求 `UniqueViolation`，再用 `ON CONFLICT ON CONSTRAINT ... DO NOTHING` 验证业务幂等重试，最后执行0039 downgrade/head re-upgrade并重新读取约束。当前等待①提供修复Commit，PR #19保持Draft/BLOCK。
## 3406 / 0042 PostgreSQL实库预验收

在隔离 PostgreSQL 16.14 临时数据库执行。专项结果：`1 passed, 4 failed`。真实merge-base的0037 Boolean缺陷成功复现，3406 fresh upgrade可到0042；但0037 Blob相对85586868冻结基线再次变化。

0042中五项Required约束名称和列均从 `pg_constraint` 验证通过；逐项重复INSERT真实触发 `UniqueViolation`，`ON CONFLICT ON CONSTRAINT`返回幂等no-op；0039 downgrade后重新upgrade至0042仍通过。阻塞为0042及ORM Model错误保留 `knowledge_asset_id`唯一约束，导致跨Run复用不成立；重复启动仍返回200而非Contract要求的409。

0005专项结论：`0005_tiancang_knowledge_tables` 与 `0005_knowledge_center_tables` 是同一线性链上的两个执行节点，均含相同表的条件创建逻辑，但两者都先检查表是否存在；后者还补充缺失索引。真实PostgreSQL fresh upgrade已成功到0042，没有重复建表失败，故旧静态扫描属于文件级误报，不是执行缺陷。

当前不运行Backend全量，等待①的 `MIGRATION_CODE_FIX_COMMIT` 修复上述四项阻塞。
## 0042架构决策防回退门禁

专项扩展至14项并在隔离PostgreSQL 16.14执行：`3 passed, 11 failed`。0037使用 `git show 85586868:<path>` 与工作树逐字节比较；0042 `_UNIQUE_COLUMNS` 必须精确等于五项Required列并排除Knowledge Asset；Model UniqueConstraint集合必须等于五项加既有trace_id。

实库新增0041遗留迁移场景，要求0042安全移除Knowledge同名唯一索引/约束、保留普通索引和数据并允许跨Run复用。downgrade场景要求不恢复Knowledge唯一性、不产生同名索引/约束冲突、五项Required保持文档语义且可再次upgrade。当前3406均未满足。

API门禁确认相同幂等键返回同一Run通过；对五项Required分别注入另一Run冲突，要求统一映射中文409且不泄漏IntegrityError。当前五项均未捕获数据库IntegrityError，门禁失败。

## Research 持久化与恢复完整性门禁

新增4个定向用例（1个真实PostgreSQL持久化用例、3个API故障注入参数用例）。真实PostgreSQL 16.14执行结果为 `0 passed, 1 failed`：首次 `persist_research_result` 在插入Claim时因 `claim_id=<execution UUID>-c1` 超过 `varchar(36)` 失败，证明当前实现未满足Query/Source/Claim/Evidence稳定标准UUID门禁；后续ID、外键和重复持久化断言因首次事务失败而被阻断。

Claim插入、Evidence插入、Research commit三类故障注入结果为 `0 passed, 3 failed`。三类Run均进入失败/待恢复状态，同trace重放返回同一 `run_id`，Run/Event数量未增加；但失败事务分别残留Query/Source/Claim/Evidence正式行和ResearchExecution虚假报告记录，且 `failure_reason` 直接暴露英文 `database ... failure`。因此半成品Run、正式数据原子性和中文错误脱敏门禁均为BLOCK。

这些测试没有使用skip、xfail、字符串截断容错或弱化断言；③未修改业务实现。等待 `ALPHA_RESEARCH_FIX_COMMIT` 后再普通合并主功能分支并执行19项PostgreSQL专项，专项全绿前不运行完整863+回归。

## 95465582 PostgreSQL 定向验收

测试分支普通合并主功能Commit `95465582df8fa52ccb9703b98c71ecefa9a3d4ce`，Merge Commit为 `3c9acfc32743c316309e2b8aac3173f5bcd408da`。本轮将API幂等、五项409和故障补偿迁移到每用例独立的真实PostgreSQL数据库，不再使用SQLite证明事务原子性。

定向专项聚合结果：**15 passed, 5 failed**。通过项包括0037字节冻结、最终Head 0042、五项Required真实Constraint、每项两条NULL、Knowledge Asset普通非unique索引及跨Run复用、0042→0041→0042、0005 Revision DAG与`_has_table`及fresh upgrade、同trace顺序和4路并发重放、五项真实跨Run冲突与中文409。

剩余代码阻塞：

1. 完整 `0042 → 0039` downgrade失败；`0042 → 0041 → 0042`已通过，必须区分。
2. Research生成的ID均为完整标准UUID，但Evidence仍使用输入 `source_id`，没有关联实际生成的ResearchSource ID，真实PostgreSQL触发外键失败。
3. Claim/Evidence插入失败均残留ResearchExecution、Query/Source及部分Claim，AgentExecution仍为`completed`，并泄漏英文database异常。
4. Research commit失败后Run仍为`运行中`、Task仍为`running`、AgentExecution仍为`completed`，未进入失败/待恢复补偿状态。

Migration Evidence Gate单独执行结果为 **5 passed, 8 failed**：旧Path A/B缺结构化RAW区、Manifest字段缺失、Checksum不匹配、0037双文档披露不足。该证据Bundle失败不计作代码专项失败。因代码专项未全绿，本轮未执行Backend 863+、Alpha E2E、Frontend、Static Security及V1完整回归，PR #19保持Draft/BLOCK。

## f50a031 Research 正式门禁

测试分支普通合并 `f50a03148654605d103d6118d8ff57ea1bfba701`，Merge Commit为 `236a92cdc08f7fe76315b542c86e58ced962131a`。定向门禁扩展为21项，全部使用隔离PostgreSQL 16.14；聚合结果为 **16 passed, 5 failed**。

已通过：0037字节冻结、最终Head 0042、五项Required Constraint、多NULL、Knowledge Asset非唯一、0042→0041→0042、0005真实DAG/fresh upgrade、恶意超长上游Source/Evidence ID内部UUID化、Evidence→Source/Claim外键、跨Execution不改绑、正式行数量与ID重放幂等、顺序/四路并发同trace、五项真实Service/DB冲突中文409。

按架构裁决，`0042 → 0039 → 0042`已从阻塞断言删除并记录为 `UNSUPPORTED_SEMANTIC_DOWNGRADE`；原因是0040包含旧Knowledge Asset全局唯一语义，已有合法复用数据无法无损穿越。正式支持边界 `0042 → 0041 → 0042`实库通过。

剩余五项代码失败：

1. commit并关闭Session后，ResearchSource的`query_id`仍为NULL，未引用同Execution真实ResearchQuery。
2. 重复`persist_research_result`不增加正式行且内部ID稳定，但Task summary重复追加两次。
3. 真实PostgreSQL DataError后补偿读取过期Run属性，触发PendingRollbackError穿透API。
4. 真实23503 FK故障虽完成Run/Task/AgentExecution补偿与正式数据回滚，但Task失败审计写入2次，AgentExecution失败审计为0。
5. 真实23505 IntegrityError同样产生2条Task失败审计且缺少AgentExecution失败审计。

Migration Evidence Bundle Gate复跑仍为 **5 passed, 8 failed**，继续独立归类。代码专项未全绿，因此未运行Backend 863+及其后的Alpha E2E、Frontend、Static Security、V1与敏感数据完整回归。

## d31565a6 PostgreSQL 正式代码门禁

测试分支通过普通Merge同步 `d31565a6c18f20384e6140305ee2561a469aef11`，Merge Commit为 `0a3f222408c8efdbeee561596070c0007fdc03d7`。23项门禁全部使用隔离PostgreSQL 16.14，结果为 **18 passed, 5 failed**。

已关闭：Source→Query非NULL外键、Evidence→Source/Claim外键、稳定内部UUID、重复persist的记录数/ID/FK/Task Summary不变、跨Execution归属冲突拒绝、同trace顺序与四路并发仅保留一套Research/Knowledge/Skill正式数据。0037字节冻结、最终Head 0042、五项Required真实Constraint与多NULL、Knowledge Asset非唯一、0042→0041→0042、0005真实DAG/fresh upgrade及五项真实Service/DB中文409均通过。

当前五项代码阻塞：

1. 恶意超长上游 `duplicate_of_source_id` 被原样写入 `research_sources.duplicate_of_source_id varchar(36)`，触发PostgreSQL `StringDataRightTruncation`；应映射为本次持久化生成的内部Source UUID，不得截断。
2. Claim DataError后未先rollback即读取事务对象，`PendingRollbackError`穿透API；Run仍为运行中、Task仍为running、AgentExecution仍为completed，且没有失败Event或失败审计。
3. Evidence真实23503 FK故障完成状态补偿和正式数据回滚，但Task `alpha_workflow_failed`审计为2条，AgentExecution `execution_failed`审计为0条。
4. flush阶段真实23505唯一冲突存在相同的Task重复审计和Agent审计缺失。
5. Evidence已flush后的deferred FK在最终commit触发23503，仍存在相同的Task重复审计和Agent审计缺失。

门禁未达到0 failed，按执行顺序未运行Backend 863+、Alpha E2E、Frontend Gate、Static Security、V1 Regression、Sensitive Data Scan，也未执行Migration Evidence Gate。PR #19继续Draft/BLOCK；历史f50结果仅作历史记录，不代表当前Head。

## 273e6587 PostgreSQL 最终验收

测试分支普通Merge同步 `273e658700439e34911dcb6c1e4a7fb2e80101b9`，Merge Commit为 `6c334405ad3fc60ebe5ecc9dc3fd83fea0b128a4`。23项隔离PostgreSQL 16.14门禁结果：**19 passed, 4 failed**。

相对d315已关闭：恶意超长 `duplicate_of_source_id` 已映射为内部Source UUID；Evidence/flush/final-commit三路的AgentExecution `execution_failed`审计均恰好1条，`workflow_failed` Event恰好1条；正式Research、Knowledge Asset/Version、Skill Invocation、Task Result均无残留，同trace重放不增加这些正式数据或Event。

剩余四项：Claim DataError仍以 `PendingRollbackError` 穿透API，Run/Task/AgentExecution未补偿且失败Event/Audit为0；Evidence FK、flush唯一冲突和deferred final-commit FK三路的Task `alpha_workflow_failed`审计仍各写入2条（其余补偿断言通过）。五项真实Service/DB冲突中文409和 `0042 → 0041 → 0042`继续通过；`0042 → 0039`仅标记 `UNSUPPORTED_SEMANTIC_DOWNGRADE`，不计失败。

因第一阶段非零失败，Backend 863+、Alpha E2E、Frontend Gate、Static Security、V1 Regression、Sensitive Data Scan未执行。Migration Evidence Gate独立结果为 **5 passed, 8 failed**，仍缺Path A/B RAW结构、Manifest字段、可复算Checksum及0037双文档披露。PR #19保持Draft/BLOCK。

## 8d9b5f28 最终代码闸

测试分支普通Merge同步冻结代码 `8d9b5f2890545f1f08d05b9b1618f71ff82d6621`。四个历史PostgreSQL故障节点首先独立执行并得到 **4 passed, 0 failed**；随后完整PostgreSQL定向门禁得到 **23 passed, 0 failed**，因此 `CODE_GATE=PASS`。

四路真实数据库故障均满足：PendingRollback不穿透；Run=`已失败`、Task=`rejected`、AgentExecution=`failed`、recovery_status=`待恢复`；Task失败Audit、AgentExecution `execution_failed` Audit及`workflow_failed` Event均恰好1条；Research/Knowledge/Skill/TaskResult无残留；同trace重放不增加Audit、Event或正式数据。

代码完整回归（独立排除Migration Evidence Bundle）为 **892 passed, 0 failed, 82 warnings in 330.38s**。独立专项：Alpha完整质量/E2E **28 passed**；Frontend Contract Gate **6 passed**；V1 Regression **2 passed**；Static Security **1 passed**且`git diff --check`通过；Sensitive Data Scan **2 passed**。

完整回归首次运行出现6个过时测试断言：五个断言要求将内部异常原文写入用户可见`failure_reason`，与最终Contract“用户可见错误为中文”和统一脱敏策略冲突；一个按文件名/create_table文本数量误报0005。测试已在允许目录中校正为统一中文脱敏断言，以及单Head、线性Revision DAG和逐表`_has_table`保护断言；6个节点复验通过，随后892项完整重跑零失败。未修改业务代码。

Migration Evidence Gate继续独立为 **5 passed, 8 failed**，因此代码冻结成立，但PR #19状态为Draft/BLOCK_EVIDENCE_ONLY，等待最终证据Bundle。
