# CHANGELOG

## V2 Usable V1 S1 release candidate（R229）

状态：PR #34 OPEN；尚未合并，尚未生产部署。

变更：

- CI 使用 job-local PostgreSQL 16、Redis 7 与完整 Git 历史，并从当前候选源码构建临时 backend/worker 测试镜像，补齐原三个环境 SKIP 的真实执行条件。
- Research Runtime 的 list/detail/sources/claims/evidence 读取入口统一使用 Owner-scoped SQL 查询；foreign、missing、taskless 与 ownership 不完整记录均失败关闭并保持非枚举。
- Skills Invocation 的 list/detail/audit/cancel/retry 五个入口统一使用 Owner-scoped SQL 查询，foreign 读取与写入均失败关闭。
- EmployeeLog 新增 nullable、非唯一索引的 `skill_invocation_id` 精确外键；`0047_skill_invocation_audit_scope` 迁移不回填历史日志，Invocation 审计不再使用 skill 或文本模糊关联。
- 逐步修复 Agent Runtime、Browser、Device Center、Employee Trace、Money Loop、Research 与 Skills 测试的真实运行前置和 Owner fixture 合同，未放宽产品权限或非枚举边界。

验证：

- 业务 UAT：`12/12 PASS`。
- Trusted CI replacement：`1691/1691 PASS`。
- FC-CI-01：`593/593 PASS`；FC-CI-02：`11/11 PASS`；FC-CI-03：`12/12 PASS`。
- Alembic 唯一 head：`0047_skill_invocation_audit_scope`。

发布边界：

- 生产仍运行 `483ebf560e1a4cfadecee4912a3ff6bca99516f6`。
- 本候选未合并、未生产部署；生产备份、rollback readiness 与回滚演练须在后续受控生产门禁重新核验。

## 天统AI可用 V1.0 S1 - 京东经营数据垂直切片

### 授权安全修复 R3

- 新增 `0044_tenant_company_store_authorization_scope`，单链承接 `0043_ai_product_asset_upload`。
- 新增租户、公司、用户/店铺作用域与显式店铺成员授权；店铺编号改为租户内唯一。
- 导入、经营中心、老板驾驶舱、今日指标、手工指标、店铺列表和账号中心统一按认证用户作用域失败关闭。
- 一次性本地 PostgreSQL 测试库完成回填、升级、受保护降级和重新升级；未连接或修改生产数据库。
- 安全与回归测试通过；尚未创建 PR、合并或部署，等待独立复审。

基线与分支：

- `develop-v2@99f1c78f72f7d60300be741a108a01059453114b`
- `feat/v2-usable-v1-s1-jd-import`

变更：

- 服务端 `/api/me` 只开放老板驾驶舱、店铺与数据、经营中心三个菜单。
- 打通内部测试店铺的 XLSX/CSV 导入、行级错误明细、持久化导入记录和并发重复提交保护。
- 经营中心与老板驾驶舱共享已入库的经营数据，并支持日期与店铺筛选。
- 拒绝缺失必要表头或必填单元格的文件，避免错误数据覆盖既有日指标。

验收：

- 真实浏览器完成登录、两类文件上传、错误明细、重复拦截、经营查询、驾驶舱一致性、刷新/重新登录/服务重启持久化和退出登录。
- 相关 Python 测试与前端 RBAC 测试通过。
- 新增数据库迁移 `0044_tenant_company_store_authorization_scope`；未进行镜像构建或部署，生产数据影响为零。

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
