# V2 Migration 冻结政策

## 正式冻结边界

1. V1 Migration `0001—0027` 属于正式发布链，永久冻结，必须与 `v1.0.1` 保持字节一致。
2. V2 Migration `0028—0042` 属于 Sprint 11.1 收口前的预发布链。
3. Sprint 11.1 关闭后，`0028—0042` 全部冻结；后续变更只能新增 forward-only Migration，不得回写冻结文件。
4. 生产环境未执行当前 V2 Migration 链；所有正式证据只在隔离 PostgreSQL 数据库生成。
5. Migration 变更必须由①实施、③验收、④审查，不得由单一角色自行宣称通过。

## Knowledge Asset 唯一性裁决

`knowledge_asset_id` 可由多个 Alpha Workflow Run 合法复用，不是全局幂等身份。0042 删除错误的全局唯一性并保留普通非唯一索引。该数据安全修复不可逆：0042 降级不恢复错误的 Knowledge Asset 唯一约束或唯一索引。

## 0037 预发布兼容调整披露

文件：`alembic/versions/0037_v2_execution_observability_security_ops.py`

0037_baseline_commit_or_hash=9e2086a6c82b5559e17b3f2ecec52740d84d6e1a
0037_modified_hash=3a4359197ec3e632adcfb73b1078b1104fdab248b16b537a6ec6f7f034f6eb97
0037_change=Boolean server_default 从整数 1 调整为 PostgreSQL true 表达
0037_reason=PostgreSQL 不接受布尔列 DEFAULT 1，预发布链需使用原生 true 表达保证新库可执行并与模型一致
0037_production_deployed=否
0037_exception_decision=V2预发布例外，仅接受已审查的 PostgreSQL 兼容版本并自 Sprint 11.1 收口后冻结
0037_approved_role=①实施、③验收、④审查
0037_post_sprint_freeze_rule=Sprint 11.1关闭后冻结旧Migration，后续变化只能新增 forward-only Migration

`0037_baseline_commit_or_hash` 是冻结可运行版本在 Git 中现场计算得到的 Blob Hash；`0037_modified_hash` 是同一文件在冻结代码上的现场 SHA256。当前文件与冻结可运行 Commit `85586868bad3dd5d0fecba5f840383feccdc1c78` 字节一致。

## 证据与例外

- SQLite 不作为正式 Migration 证据。
- 禁止使用任何 Drift 跳过开关。
- 历史失败 Commit 只能以 `KNOWN_BROKEN_HISTORICAL_BASELINE` 分类记录，不得包装成通过路径。
- 正式证据不得包含密码、Token、完整连接串或生产数据。
- 冻结后发现的新缺陷必须通过新增 Migration 修复，并重新完成 PostgreSQL 双路径验收。
