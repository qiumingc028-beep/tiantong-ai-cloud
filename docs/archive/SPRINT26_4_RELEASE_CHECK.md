# Sprint26.4 Release Check

## 当前版本

- Release: `Sprint26.4-v1.0`
- Branch: `main`
- Local HEAD: `a8f712ac1402b5579d16604bc3aef3af173688f4`
- GitHub main: `a8f712ac1402b5579d16604bc3aef3af173688f4`
- Archive Sync backend commit: `66ae283785545c6487230938307cd7f89a648170`

## Git 检查

- main 分支：PASS
- 本地 HEAD 与 GitHub main 一致：PASS
- 未提交业务代码：PASS
- 当前存在未跟踪 docs 草稿文件，不影响业务代码上线判断：
  - `docs/AI_EMPLOYEE_MAP.md`
  - `docs/ARCHITECTURE.md`
  - `docs/CODEX_RULES.md`
  - `docs/DECISION_LOG.md`
  - `docs/DEPLOY_SPRINT26_4.md`

## Docker 检查

`docker-compose.yml` 服务：

- `backend`: PASS，healthy
- `worker`: PASS，running
- `nginx`: PASS，running
- `postgres`: PASS，healthy
- `redis`: PASS，healthy

## API 检查

- `GET /api/health`: PASS，HTTP 200
- `GET /api/ready`: PASS，HTTP 200
- `GET /api/archive/sprints`: PASS，未登录 HTTP 401，接口已加载且不返回 404
- `GET /api/archive/project-status-draft`: PASS，未登录 HTTP 401，接口已加载且不返回 404
- `GET /api/employee-execution/tian-shang/status`: PASS，未登录 HTTP 401，接口已加载且不返回 404

## 测试结果

- 测试命令：`docker compose run --rm -e PYTHONPATH=/app backend pytest -q tests`
- 测试数量：568
- PASS 数量：568
- FAIL 数量：0
- Warnings：14，均为既有 FastAPI on_event / Alembic path_separator deprecation warning，不阻塞上线前验收

## 风险列表

- 低风险：Sprint26.4 Archive Sync 只生成档案草稿，不自动写 docs、不自动提交 Git、不自动部署、不调用外部 API。
- 低风险：当前存在未跟踪 docs 草稿文件，需在后续文档任务中单独处理；不属于业务代码或部署配置。
- 注意：阿里云部署前必须确认生产 `.env` 存在，且 `DATABASE_URL` / `POSTGRES_PASSWORD` 与 PostgreSQL 初始化用户一致。
- 注意：上线部署必须人工执行，禁止自动上传服务器、自动安装软件或自动修改数据库结构。

## 是否允许部署

结论：允许进入天监安全审计。

天监安全审计通过后，可进入阿里云人工部署确认流程。
