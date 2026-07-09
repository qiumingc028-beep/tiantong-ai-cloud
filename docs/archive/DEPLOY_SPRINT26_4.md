# Sprint26.4 Production Deployment SOP

## 目标

将 Mac mini 本地稳定版本同步到阿里云生产环境，发布 Sprint26.4 Archive Sync 长期记忆档案系统封版版本。

本 SOP 只用于部署准备和人工执行指引，不自动部署、不自动修改业务代码、不修改数据库结构。

## 当前发布版本

- Release Version: `Sprint26.4-v1.0`
- Git Commit: `a8f712ac1402b5579d16604bc3aef3af173688f4`
- GitHub main: `a8f712ac1402b5579d16604bc3aef3af173688f4`
- Archive Sync backend commit: `66ae283785545c6487230938307cd7f89a648170`
- Migration: Sprint26.4 无新增 migration，当前 Alembic head 为 `0026_sprint26_ai_employee_execution_mvp`

## 部署链路

```text
Mac mini
  ↓
GitHub main
  ↓
阿里云 /data/apps/tiantong-ai-cloud
  ↓
docker build
  ↓
migration
  ↓
docker compose up
  ↓
health check
```

## 服务器环境要求

- OS: Linux x86_64，建议 Ubuntu 22.04 LTS 或同等级稳定发行版
- Docker: 建议 Docker Engine 24+
- Docker Compose: 建议 Docker Compose v2+
- Git: 可访问 `https://github.com/qiumingc028-beep/tiantong-ai-cloud.git`
- 端口:
  - `80/tcp` 对外开放给 Nginx
  - PostgreSQL / Redis 只在 Docker 网络内访问
- 磁盘:
  - 预留 Docker image、PostgreSQL volume、Redis volume、Nginx log 空间
  - 建议部署前确认剩余空间充足

## Docker 服务结构

`docker-compose.yml` 包含以下服务：

- `postgres`: PostgreSQL 16，持久化 volume `postgres_data`
- `redis`: Redis 7，开启 appendonly，持久化 volume `redis_data`
- `backend`: FastAPI backend，从项目根目录构建
- `worker`: Python worker，从项目根目录构建，命令 `python -m backend.worker`
- `nginx`: Nginx 1.27，代理 `/api/*` 到 backend，静态托管 `frontend/`

## 生产环境变量

生产服务器项目目录必须存在 `.env`，不要提交到 Git。

必需变量：

```env
DATABASE_URL=postgresql+psycopg2://<user>:<password>@postgres:5432/<db>
REDIS_URL=redis://redis:6379/0
JWT_SECRET=<long-random-secret>
OPENAI_API_KEY=
POSTGRES_DB=<db>
POSTGRES_USER=<user>
POSTGRES_PASSWORD=<password>
APP_ENV=production
```

可选变量按线上实际启用模块补充：

```env
AUTOMATION_API_KEY=<internal-api-key>
WEBHOOK_SECRET=<webhook-secret>
ADMIN_RESET_PASSWORD=<one-time-admin-recovery-password>
```

安全要求：

- 不在 docs 中记录真实密码、token、secret、API key
- `.env` 文件权限建议限制为部署用户可读写
- PostgreSQL 密码、`DATABASE_URL`、`POSTGRES_PASSWORD` 必须一致

## 部署前检查

在 Mac mini 本地确认：

```bash
git branch --show-current
git rev-parse HEAD
git ls-remote origin refs/heads/main
git status --short
docker compose config --services
```

期望：

- 当前分支为 `main`
- 本地 HEAD 与 GitHub main 一致
- GitHub main 指向 `a8f712ac1402b5579d16604bc3aef3af173688f4`
- `docker compose config --services` 包含：
  - `postgres`
  - `redis`
  - `backend`
  - `worker`
  - `nginx`

## 阿里云人工部署步骤

进入项目目录：

```bash
cd /data/apps/tiantong-ai-cloud
```

同步 GitHub main：

```bash
git remote -v
git fetch --prune origin main
git reset --hard origin/main
git rev-parse HEAD
git log -1 --oneline
```

确认 HEAD：

```text
a8f712ac1402b5579d16604bc3aef3af173688f4
```

确认核心文件：

```bash
ls -l backend/archive_sync
ls -l docs/PROJECT_STATUS.md
ls -l docs/CHANGELOG.md
ls -l docs/SPRINT_ROADMAP.md
```

检查 `.env`：

```bash
test -f .env && echo ".env exists"
docker compose config
```

启动基础服务：

```bash
docker compose up -d postgres redis
```

执行数据库迁移：

```bash
docker compose run --rm backend alembic upgrade head
docker compose run --rm backend alembic current
```

期望 migration：

```text
0026_sprint26_ai_employee_execution_mvp (head)
```

构建服务：

```bash
docker compose build backend worker
```

启动服务：

```bash
docker compose up -d backend worker nginx
```

检查容器：

```bash
docker compose ps
```

期望：

- `backend`: healthy
- `worker`: running
- `postgres`: healthy
- `redis`: healthy
- `nginx`: running

## 健康检查接口

基础健康检查：

```bash
curl -i http://127.0.0.1/api/health
curl -i http://127.0.0.1/api/ready
```

期望：

- `/api/health`: HTTP 200
- `/api/ready`: HTTP 200

Sprint26.4 Archive Sync 权限检查：

```bash
curl -i http://127.0.0.1/api/archive/sprints
curl -i http://127.0.0.1/api/archive/project-status-draft
curl -i http://127.0.0.1/api/archive/decision-draft
```

未登录期望：

- HTTP 401
- 不应返回 404

如具备 owner/admin 登录 token，可进一步验证：

```bash
curl -i http://127.0.0.1/api/archive/sprints \
  -H "Authorization: Bearer <token>"
```

期望：

- Owner/Admin: HTTP 200
- Viewer: HTTP 403

## 日志检查

```bash
docker compose logs --tail=120 backend
docker compose logs --tail=120 worker
docker compose logs --tail=120 nginx
```

重点确认：

- 无 `ImportError`
- 无 `ModuleNotFoundError`
- 无 `TypeError`
- 无持续 500
- Archive Sync API 不应出现 404
- Redis timeout 如出现，应为 warning，不应导致 worker 持续重启

## 回滚建议

如部署后出现不可接受问题：

1. 停止新版本服务：

```bash
docker compose stop backend worker nginx
```

2. 回退到上一个已知稳定 commit：

```bash
git log --oneline -5
git reset --hard <previous-stable-commit>
```

3. 重建并启动：

```bash
docker compose build backend worker
docker compose up -d backend worker nginx
```

4. 重新验证：

```bash
curl -i http://127.0.0.1/api/health
curl -i http://127.0.0.1/api/ready
docker compose ps
```

## 禁止事项

- 禁止在部署 SOP 中记录真实密码、token、secret、API key
- 禁止自动上传服务器
- 禁止自动执行生产部署
- 禁止自动安装软件
- 禁止修改业务代码
- 禁止修改数据库结构
- 禁止绕过老板确认或安全审计

## 部署完成判定

满足以下条件后，Sprint26.4 可视为生产部署验证通过：

- GitHub main 与服务器 HEAD 一致
- backend / worker / postgres / redis / nginx 状态正常
- Alembic current 为 `0026_sprint26_ai_employee_execution_mvp (head)`
- `/api/health` 返回 200
- `/api/ready` 返回 200
- `/api/archive/*` 未登录返回 401，且不返回 404
- backend 日志无导入错误和持续 500
- 未修改业务逻辑
- 未修改数据库结构
