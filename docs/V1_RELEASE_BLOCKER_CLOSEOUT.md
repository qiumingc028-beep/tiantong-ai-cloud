# Sprint 67.1 — V1 Release Blocker Closeout

更新时间：2026-07-11（Asia/Shanghai）

## 1. 执行结论

本 Sprint 以最小生产级变更清除了四项 V1 发布阻断。全量 V1 后端回归为 `769 passed, 14 warnings`，前端验证为 `68 passed, 2 warnings`；全新隔离 PostgreSQL 的 `alembic upgrade head`、`alembic check`、回退/再升级均通过。使用 `docker-compose.prod.yml` 创建的全新本地生产配置栈完成了 PostgreSQL、Redis、Migration、Backend、Worker、Nginx、HTTPS、CORS 与健康检查验证，未连接远程生产环境。

结论：`READY_FOR_FINAL_RELEASE`。该结论表示代码与本地生产配置基线已具备最终发布条件，不代表远程生产已部署。

## 2. 阻断根因与修复

### 2.1 MIGRATION_MODEL_DRIFT

根因分为两层：

1. `alembic/env.py` 只导入了少量模型模块，导致 Alembic 未注册全部 `Base.metadata`，将历史表错误识别为待删除对象。
2. 补齐模型导入后，历史 migration 与当前 ORM 仍存在真实差异，集中在 nullable、索引命名/唯一性和唯一约束。

修复：补齐 metadata 导入，并新增唯一确定性 revision `0027_v1_schema_alignment.py`。该 revision 不创建或删除表、不包含 DML，仅对已确认的 nullable、index 和 unique constraint 差异进行对齐。统计：286 个 `alter_column`、20 个 `create_index`、20 个 `drop_index`、5 个 `create_unique_constraint`、5 个 `drop_constraint`。

验证：在全新临时 PostgreSQL 上执行 `upgrade head -> check -> downgrade 0026 -> upgrade head -> check`，全部通过。生产配置隔离栈也完成 `upgrade head` 与 `check`。实际部署前仍应备份并预检存量数据；若存量数据不满足 NOT NULL/唯一约束，migration 会事务性失败，不会静默删除或猜测修复数据。

### 2.2 DEFAULT_CREDENTIAL_FALLBACKS

根因：配置和 seed 路径存在运行时开发默认值，生产模式未统一 fail-fast。

修复：新增显式 `APP_ENV/ENV=production` 边界；生产模式不读取 `.env`，强制要求数据库、Redis、JWT、老板初始密码与 CORS 配置；拒绝占位符、短/默认 JWT、默认老板密码、开发数据库凭据、无认证 Redis 与 debug 模式。开发/测试默认值仅保留在明确的非生产分支。`.env.production.example` 仅包含安全占位符，不含真实秘密。

验证：缺失生产配置的容器启动以 `ConfigurationError` 失败；生产配置专项测试与认证测试 `24 passed, 2 warnings`。

### 2.3 PRODUCTION_CORS_POLICY

根因：应用曾使用通配 origin 且允许 credentials。

修复：CORS origin 与 credentials 由统一 Settings 提供；生产要求显式、非空的 HTTP(S) origin 列表，拒绝 `*` 和非法 origin。开发/测试 origin 与生产隔离。

验证：专项测试覆盖合法 origin、缺失 origin、通配拒绝和 credentials 安全；生产栈合法 origin 预检返回精确 `Access-Control-Allow-Origin`，恶意 origin 返回 400 且不返回 allow-origin。

### 2.4 PRODUCTION_RUNTIME_STATE_UNKNOWN

根因：此前只有冻结测试记录，没有从空状态启动现有生产 Compose 的可重复证据。

修复与验证：使用唯一 Compose project、全新临时 volume/network、临时测试秘密及临时 TLS 证书启动所需生产栈；未复用旧容器或数据。验证结果：PostgreSQL healthy、Redis healthy、Backend healthy、Nginx healthy、Worker heartbeat healthy；HTTP 301、HTTPS 首页 200、`/health` 200、`/ready` 200；所有服务 restart policy 为 `unless-stopped`；生产模式启用且 debug=false。

## 3. 文件变更

Sprint 67.1 新增/修改：

- `.env.production.example`
- `Dockerfile.backend`, `Dockerfile.worker`
- `alembic/env.py`
- `alembic/versions/0027_v1_schema_alignment.py`
- `backend/config.py`, `backend/seed.py`
- `backend/main.py`（仅本 Sprint 的配置导入与 CORS 段；该文件执行前已有 Sprint63/64 未提交修改）
- `backend/routers/deploy_center.py`, `backend/routers/release_center.py`
- `tests/test_production_config.py`
- 16 个引用 Alembic head 的既有测试文件，统一从 `0026` 更新为 `0027`
- `docs/V1_RELEASE_BLOCKER_CLOSEOUT.md`

执行前已存在且未归入本 Sprint 的修改包括 `requirements.txt`、Sprint63/64 代码、测试、页面、文档和 Sprint66 工件；未删除、覆盖或提交这些成果。

## 4. 主要执行命令与结果

- `pytest`（Git 跟踪的 V1 测试 + `tests/test_production_config.py`）：`769 passed, 14 warnings`
- 前端既有验证：`68 passed, 2 warnings`
- `python -m py_compile ...`（临时可写副本）：PASS
- `python -c 'import backend.main ...'`：PASS，346 routes
- `alembic upgrade head`（全新 PostgreSQL）：PASS
- `alembic check`：`No new upgrade operations detected.`
- `alembic downgrade 0026` 后再 `upgrade head` 与 `check`：PASS
- `docker compose ... config --quiet`：PASS
- 生产镜像构建：Backend/Worker 使用固定 Python digest 和 35 项 hash-lock wheelhouse 离线安装；PASS
- 生产 Compose 启动与健康检查：PASS
- 生产 fail-fast、CORS 与静态秘密检查：PASS
- `tests/api_acceptance_check.py`：后端 API、登录、仪表盘、店铺、指标及四个前端页面均通过；脚本在生产 Nginx 分层入口对 `/openapi.json` 的两项探测失败，因为生产 Nginx 不公开该后端 schema 路径。对应两个业务路由已由后端回归覆盖；不为测试脚本公开生产 OpenAPI，记录为非阻断测试入口兼容性观察项。

## 5. Warning 与观察项

- 后端 14 条 warning：2 条 FastAPI `on_event` deprecation，12 条 Alembic `path_separator` 配置 deprecation；均不影响本次结果。
- 前端 2 条 Node experimental warning；不影响结果。
- 生产 acceptance 脚本仍假设单体页面/API/OpenAPI 共用同一入口，与生产 Nginx 分层结构不完全兼容。真实 API、页面及业务路由分别验证通过；未降低安全策略或额外暴露 OpenAPI。
- 镜像供应链限制延续：digest 已固定；Cosign/OCI referrer 签名未找到，SBOM/Provenance 仅存在但未验证。

## 6. 回滚说明

- 应用配置/CORS：回滚 `backend/config.py`、`backend/main.py`、`backend/seed.py` 及环境模板变更。
- Migration：仅在确认无后续 schema/data 依赖后执行 `alembic downgrade 0026_sprint26_ai_employee_execution_mvp`；生产操作前必须备份并审批。
- 容器：使用本 Sprint 唯一 Compose project 执行 `down -v --remove-orphans`；不触碰旧项目 volume。
- 本 Sprint 未 commit、push、创建 tag 或部署远程生产。
- 验证结束后已删除临时 Compose 容器、network、volume、镜像和临时认证/配置树；旧项目五个容器保持 `exited`，原 `unless-stopped` restart policy 已恢复且未自动启动；Docker Desktop 已关闭。

## 7. 最终状态

```text
MIGRATION_UPGRADE_RESULT = PASS
MIGRATION_CHECK_RESULT = PASS
MIGRATION_MODEL_DRIFT = CLEARED
DEFAULT_CREDENTIAL_FALLBACKS = CLEARED
PRODUCTION_SECRET_VALIDATION = PASS
PRODUCTION_CORS_POLICY = PASS
PRODUCTION_RUNTIME_STATE = VERIFIED
PRODUCTION_STARTUP_RESULT = PASS
PRODUCTION_HEALTHCHECK_RESULT = PASS
REMAINING_BLOCKERS = NONE
V1_RELEASE_DECISION = READY_FOR_FINAL_RELEASE
```
