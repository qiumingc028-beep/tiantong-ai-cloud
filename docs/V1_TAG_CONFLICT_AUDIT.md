# Sprint 68.1 — V1.0.0 Tag 冲突审计与发布基线确认

审计时间：2026-07-11（Asia/Shanghai）
审计性质：Git 历史、Tag、分支和工作区只读审计；除本报告外未修改文件。

## 1. 执行摘要

现有 `v1.0.0` 是 2026-07-10 创建的本地 annotated Tag，Tag 对象为 `75824df675fd6939fe3d9494cb9213b61e4269f3`，解引用后指向 commit `9e0a518ce7dfe47909c15b19a61ddf8c80fe6295`。该 Tag 不存在于 `origin`。当前 HEAD 与该 commit 完全相同，旧 Tag 之后没有已提交 commit；Sprint67.1 的 migration、生产秘密校验、CORS 和生产运行修复全部仍在工作区，因而旧 Tag 不包含这些修复，不能代表当前通过 Release Audit 的最终版本。

推荐方案：**方案 B，在下一阶段形成干净、经重新验证的选择性发布 commit 后，经老板明确批准，保留旧对象的审计引用，再仅在本地替换 `v1.0.0`。** 远程没有此 Tag，因此不需要 force push；本 Sprint 不执行任何 Tag 或 commit 变更。

## 2. 当前 Git 状态

- 当前真实分支：`终端`。此前 `CURRENT_BRANCH = 终端` 是 Git 返回的真实中文分支名，不是终端程序或状态描述。
- 当前 HEAD：`9e0a518ce7dfe47909c15b19a61ddf8c80fe6295`。
- 上游：`origin/终端`，本地与上游显示无 ahead/behind。
- 远程：`origin = https://github.com/qiumingc028-beep/tiantong-ai-cloud.git`（fetch/push URL 相同）。
- 工作区：DIRTY；26 个 tracked modified 文件、134 个 untracked 文件、0 个 staged 文件。
- 当前分支图：HEAD、`origin/终端`、`New-Terminal` 和 `v1.0.0^{commit}` 均位于 `9e0a518`。

只读命令包括：

```text
git status --short
git status --branch
git branch --show-current
git branch -vv
git log --oneline --decorate --graph -30
git remote -v
```

## 3. 现有 v1.0.0 Tag 身份

| 项目 | 结果 |
|---|---|
| Tag 名称 | `v1.0.0` |
| 类型 | Annotated Tag |
| Tag 对象 | `75824df675fd6939fe3d9494cb9213b61e4269f3` |
| 指向 commit | `9e0a518ce7dfe47909c15b19a61ddf8c80fe6295` |
| Tagger | 陈秋明 |
| Tag 时间 | 2026-07-10 18:11:54 +08:00 |
| Tag Message | `Tiantong AI Cloud V1.0.0 Stable Release` |
| Commit 作者/提交者 | 陈秋明 |
| Commit 时间 | 2026-07-10 18:11:47 +08:00 |
| Commit Message | `release: Tiantong AI Cloud V1.0.0 baseline` |

该 commit 是一个明确命名的 V1 基线提交，包含 141 个文件的 V1 能力与发布资料变更；它真实代表当时的 V1 baseline，但不包含随后 Sprint67.1 清除的四个发布阻断。因此它不是当前最终可发布基线。

## 4. 远程 Tag 状态

执行 `git ls-remote --tags origin` 的结果只包含 `v0.1.0-mvp` 及其 peeled commit；未发现 `refs/tags/v1.0.0` 或 `refs/tags/v1.0.0^{}`。

- 远程 `v1.0.0`：不存在。
- 本地/远程一致性：不适用（远程无对应 Tag）。
- 外部使用证据：仓库远程引用没有已发布证据；仅凭 Git 无法证明该本地 Tag 从未通过其他渠道导出或使用，后续替换仍需老板明确批准。
- 本轮没有 fetch、push、删除或修改任何远程引用。

## 5. Tag、HEAD 与 Sprint67.1 的关系

```text
HEAD                              = 9e0a518ce7dfe47909c15b19a61ddf8c80fe6295
v1.0.0^{commit}                  = 9e0a518ce7dfe47909c15b19a61ddf8c80fe6295
commits in v1.0.0..HEAD          = 0
committed diff v1.0.0..HEAD      = empty
```

这里的“0 个 commit”不表示 Sprint67.1 已包含在 Tag 中。相反，Sprint67.1 全部成果仍是未提交工作区差异：

- `alembic/env.py` 与新增 `0027_v1_schema_alignment.py`：metadata 导入和 schema alignment。
- `backend/config.py`、`backend/seed.py`、`.env.production.example`：生产秘密 fail-fast。
- `backend/main.py` 的 Settings/CORS hunk：显式生产 origin，移除通配配置。
- `Dockerfile.backend`、`Dockerfile.worker`：固定 digest 与离线 hash-lock 依赖。
- deploy/release center 及 16 个测试：Alembic head 从 0026 更新为 0027。
- `tests/test_production_config.py` 与 `docs/V1_RELEASE_BLOCKER_CLOSEOUT.md`：专项验证和报告。

结论：`v1.0.0` 不含 Sprint67.1，也不含通过发布所依赖的最终 Migration、Security、CORS 和 Production Runtime 修复。

## 6. 工作区文件分类

### A. 必须进入最终 V1 发布候选

- Sprint67.1 tracked 变更：`.env.production.example`、两个生产 Dockerfile、`alembic/env.py`、`backend/config.py`、`backend/seed.py`、deploy/release center、16 个 Alembic head 测试。
- Sprint67.1 untracked：`alembic/versions/0027_v1_schema_alignment.py`、`tests/test_production_config.py`、`docs/V1_RELEASE_BLOCKER_CLOSEOUT.md`。
- `backend/main.py` 中仅 Settings import 与 CORS middleware hunk；同一文件还混有 Sprint63/64 内容，不能整文件直接暂存。
- Sprint66.7B.1 的 `requirements.txt` greenlet 固定项及 `artifacts/wheelhouse/linux-arm64-cp312/` 42 个离线依赖工件/清单：当前 Dockerfile 构建依赖它们，纳入发布前必须再次确认制品仓储策略和体积。

### B. V1 发布文档

- `docs/V1_FAST_TRACK_CLOSEOUT.md`
- `docs/V1_RELEASE_BLOCKER_CLOSEOUT.md`
- `docs/SPRINT62_73_V1_RELEASE_COMMIT_REPORT.md`
- Sprint61/62 安全、Freeze、验收相关报告以及部分较早 V1 验收报告。

哪些历史未跟踪报告应进入最终发布 commit，需要在下一阶段按发布证据最小集合逐项选择，不能全量添加 `docs/`。

### C. Sprint63 / Sprint64 成果

- Sprint63：11 个设计/验收文档；AI Workforce View 的 router/service/adapters；`ai-workspace.html` 及对应测试。
- Sprint64：17 个设计/验收文档；Platform Account Center router/schema/service；`ecommerce-dashboard.html` 及对应测试。
- `backend/main.py` 同时包含这两组 router import、route registration 和页面入口，是与 Sprint67.1 CORS 修复重叠的关键文件。

这些内容属于已审计的未提交 V2 候选成果，不应混入当前 V1 发布 commit，也不得丢失。

### D. V2 或未来能力

- Sprint65.0–65.10 Enterprise OS V2 规划体系（11 个文档）。
- Sprint66.1 App Shell 设计，以及 Sprint63/64 候选实现和页面。
- 后续应在 V2 分支单独形成可追踪提交。

### E. 临时文件、日志、缓存、测试产物

- 当前 `git ls-files --others --exclude-standard` 未列出 `.env.production`、数据库文件、日志或缓存目录。
- `artifacts/` 是已验证的离线供应链工件，不应简单视为临时缓存；是否提交 Git 需依据制品管理策略明确决定。
- `docs/graphify-report.md` 属于生成型报告，是否进入发布范围无法仅凭文件名确认。

### F. 无法确认归属

- 未跟踪的较早 Sprint31/32 报告、`BOSS_FIXED_PASSWORD_REPORT.md`、`PROJECT_HANDOFF.md`、`graphify-report.md` 是否应进入本次发布 commit，需老板或发布负责人确认。
- Sprint66.2–66.7B 审计/恢复文档是发布证据，但不一定都属于最终产品发行包；建议只选择最终审计链所需文件。

统计：26 个 modified、134 个 untracked、0 个 staged。134 个 untracked 文件按顶层为：`alembic` 1、`artifacts` 42、`backend` 18、`docs` 66、`frontend` 2、`tests` 5。

## 7. 风险分析

1. **Tag 不完整风险：高。** 旧 Tag 缺少 Sprint67.1 的发布阻断修复。
2. **混合提交风险：高。** `backend/main.py` 同时包含 V1 CORS 与 Sprint63/64 路由/page 变更；禁止整文件全量暂存。
3. **历史可信度风险：中。** 虽然远程没有 `v1.0.0`，本地 Tag 的 message 明确写着 Stable Release；替换前应保留旧对象引用和审计记录。
4. **制品体积/策略风险：中。** Dockerfile 当前依赖 42 个 wheelhouse 文件及清单，需要明确这些工件随 Git 发布还是迁移到受控制品库。
5. **成果丢失风险：高。** 不能使用 reset/clean/checkout 覆盖 Sprint63/64 未提交成果。
6. **外部引用不确定性：低至中。** origin 没有 Tag，但 Git 审计无法排除本地 Tag 曾被离线导出。

## 8. 推荐版本策略

### 推荐：方案 B（仅建议，本 Sprint 不执行）

理由：

- 远程 `origin` 没有 `v1.0.0`，无需改写远程历史或 force push。
- 旧 Tag 指向明确的 baseline，而非通过 Sprint67.1 Release Audit 的最终代码。
- 产品目标仍是第一次正式发布 `1.0.0`；直接跳到 `1.0.1` 会把一个没有远程发布证据且不完整的本地 baseline 当作公开版本。

安全条件：

1. 老板明确批准替换本地 Tag。
2. 先为旧 commit `9e0a518` 建立不可混淆的审计引用（名称需老板批准），并在最终报告保留 Tag 对象、commit、时间与 message。
3. 通过选择性暂存形成只包含 V1 修复与发布文档的 commit；`backend/main.py` 必须按 hunk 拆分。
4. 从该 commit 创建干净隔离副本，重新执行完整发布验证。
5. 验证通过后才替换本地 annotated `v1.0.0`；不 push，且不使用 force push。

`TAG_MOVE_SAFE = YES_WITH_EXPLICIT_BOSS_APPROVAL_AND_ARCHIVE_REFERENCE`。

### 不推荐

- 方案 A：旧 Tag 不含 Sprint67.1，不能代表已通过最终审计的版本。
- 方案 C：仅在发现旧 Tag 已经外部使用或老板决定保持其不可变时采用；当前 origin 没有该 Tag。
- 方案 D：Sprint67.1 已验证通过，当前主要问题是工作区选择性整理和 Tag 冲突，不需要用 RC 掩盖发布基线整理工作。

## 9. 下一步命令草案（不在本 Sprint 执行）

以下仅为下一阶段经审批后的草案，执行前必须再次核对路径和 diff：

```bash
# 1. 保存状态证据并创建临时补丁/归档，禁止 clean/reset。
git status --short
git diff --binary > /tmp/tiantong-pre-release-worktree.patch

# 2. 仅选择 V1 文件；backend/main.py 必须交互式按 hunk 选择 CORS，排除 Sprint63/64。
git add <明确的 V1 文件列表>
git add -p backend/main.py
git diff --cached --check
git diff --cached --name-status

# 3. 从暂存内容形成候选 release commit 后，在独立副本重新验证。
git commit -m "release: TIANTONG AI Cloud V1.0.0"

# 4. 只有老板明确批准后，先保留旧对象的审计引用，再替换本地 annotated Tag。
# 具体引用名称及 Tag 替换命令必须在执行 Sprint 中再次审批，本文不提供可误执行的删除命令。

# 5. 验证，不推送。
git show v1.0.0 --stat --summary
git ls-remote --tags origin
```

下一 Sprint 应专门执行“V1 选择性发布提交整理与 Tag 替换审批”，先解决 `backend/main.py` 重叠和 wheelhouse 制品策略，再进行任何 commit/Tag 操作。
