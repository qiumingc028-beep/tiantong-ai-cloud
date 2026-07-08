# CHANGELOG

## Sprint26.4-v1.0

Commit:

`66ae283785545c6487230938307cd7f89a648170`

变更：

- 完成 Sprint26.3 Archive Sync 自动档案同步系统 MVP 封版。
- 新增后端模块：
  - `backend/archive_sync/`
- 新增 API：
  - `GET /api/archive/sprints`
  - `POST /api/archive/sprint-summary`
  - `GET /api/archive/project-status-draft`
  - `GET /api/archive/decision-draft`
- 新增测试：
  - `tests/test_archive_sync.py`
- `backend/main.py` 注册 Archive Sync router。

测试：

- 全量测试：`568 passed`
- Archive Sync 全量验收与关键回归：`57 passed`
- `git diff --check`：通过

安全审计：

- Sprint26.4 安全审计：PASS
- 风险等级：低
- Owner/Admin 可生成档案草稿。
- Viewer / 未登录禁止访问。
- 不返回 password / token / secret / API Key / private_key / DATABASE_URL / REDIS_URL。
- 不自动写 docs。
- 不自动提交 Git。
- 不自动部署。
- 不调用外部 API。

部署状态：

- backend 镜像已重建并加载 `backend.archive_sync`。
- backend healthy。
- worker running。
- postgres / redis healthy。
- nginx running。
- `/api/health` 返回 200。
- `/api/ready` 返回 200。
- `/api/archive/*` 未登录返回 401，权限保护正常。

## Sprint26-v1.0

Commit:

`629b06289e2003ba20932c99a8e47afc5ed59559`

变更：

- 新增 Employee Execution Contract。
- 新增天商 Worker。
- 新增 AI Planner / AI Executor。
- 新增内部工具：
  - `market_search`
  - `data_analysis`
  - `report_generator`
- 新增 Sprint26 API：
  - `POST /api/employee-execution/tian-shang/tasks`
  - `POST /api/employee-execution/tian-shang/process-next`
  - `GET /api/employee-execution/tian-shang/status`
  - `GET /api/employee-execution/contracts/{contract_id}`
- 新增 migration：
  - `0026_sprint26_ai_employee_execution_mvp`

测试：

- `561 passed`

部署：

- GitHub main 已同步。
- Docker backend / worker / nginx / postgres / redis 正常。
- Migration 0026 已执行。
- Sprint26 API owner 验证通过。

## Sprint25.3

Commit:

`16c0d87c484b133b19d8a0f772586898b0c882d5`

变更：

- Brain Execution Engine 增强。
- 增加 priority queue、worker heartbeat、retry、timeout、execution context。
- CEO Dashboard 增加执行引擎 summary。

测试：

- `555 passed`

## Sprint24-Sprint23

- Sprint24：Brain Execution dry-run Center。
- Sprint23：Brain Center + Orchestrator dry-run 联动。

## 维护规则

每个 Sprint 完成后必须新增一条 changelog，包含：

- Sprint编号
- Commit ID
- 主要变更
- 测试结果
- 部署状态
- 安全边界
