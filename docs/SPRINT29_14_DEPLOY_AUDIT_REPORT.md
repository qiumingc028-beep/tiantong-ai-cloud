# Sprint29.14 部署验收报告

目标：确认 `tiantong-ai-cloud` 是否可以安全进入阿里云正式部署。

执行边界：

- 未连接阿里云
- 未执行部署
- 未执行 `docker compose up`
- 未修改业务代码
- 未修改数据库

## A. 当前完成度

### A1. deploy.sh 检查

检查文件：

- `deploy.sh`

当前能力：

- 支持 `DEPLOY_MODE=docker`。
- 支持 `DEPLOY_MODE=systemd`。
- Docker 模式包含：
  - Git fetch / checkout / pull
  - compose config
  - pull postgres / redis
  - build backend / worker / nginx
  - 启动 postgres / redis
  - alembic upgrade head
  - 重建 backend / worker / nginx
  - healthcheck
- systemd 模式包含：
  - 创建 venv
  - 安装 requirements
  - alembic upgrade head
  - 复制 systemd service
  - 复制 nginx-systemd.conf
  - systemctl reload / restart
  - healthcheck

发现问题：

- `deploy.sh` 默认读取 `.env`，但 Sprint29 生产方案要求使用 `.env.production`。
- `deploy.sh` 默认 `COMPOSE_FILE=docker-compose.prod.yml`，但没有默认设置 `--env-file .env.production`。
- `ensure_env()` 会在缺少 `.env` 时从 `.env.example` 生成 `.env`，这不适合生产部署。
- Docker 模式会自动 `git pull` 和执行 migration，适合作为人工确认后的脚本，但不适合直接作为首次生产部署入口。
- systemd 模式使用 `.env`、HTTP nginx 配置和 sudo systemctl，不满足 Sprint29 HTTPS 生产标准。

危险命令检查：

- 未发现 `rm -rf`。
- 未发现 `docker volume rm`。
- 未发现 `docker compose down -v`。
- 未发现 `DROP DATABASE`。
- 未发现 `git push`。
- systemd 模式存在 `sudo cp`、`sudo systemctl restart`、`sudo nginx -t`、`sudo systemctl reload nginx`，必须人工确认后执行。

结论：

- Docker 模式逻辑完整，但生产环境变量接入方式需要人工规避或修复。
- systemd 模式可作为备用部署方式，但不建议作为 V1 首次正式生产部署方式。

### A2. Docker 检查

检查文件：

- `docker-compose.yml`
- `docker-compose.prod.yml`
- `Dockerfile.backend`
- `Dockerfile.worker`
- `Dockerfile.frontend`
- `nginx/production.conf`

开发 compose：

- `docker-compose.yml` 使用默认 `POSTGRES_PASSWORD=tiantong`。
- Redis 无密码。
- nginx 只暴露 `80`。
- 适合本地或内部测试，不适合作为正式公网生产配置。

生产 compose：

- `docker-compose.prod.yml` 可以使用 `.env.production.example` 渲染。
- PostgreSQL 未暴露公网端口。
- Redis 未暴露公网端口。
- backend 只 `expose` 8000。
- nginx 只发布 `80` / `443`。
- Redis 启用 `--requirepass`。
- Redis healthcheck 使用密码。
- backend / worker 使用生产环境变量文件。
- nginx TLS 证书通过只读 bind mount 注入。

Dockerfile：

- `Dockerfile.backend` 使用 `python:3.12-slim`。
- backend 启动入口为 `uvicorn backend.main:app --host 0.0.0.0 --port 8000`。
- `Dockerfile.worker` 使用 `python:3.12-slim`。
- worker 启动入口为 `python -m backend.worker`。
- `Dockerfile.frontend` 使用 `nginx:1.27-alpine`。
- frontend 镜像复制指定 Nginx 配置和 `frontend` 静态目录。

Nginx 生产配置：

- HTTP 跳 HTTPS。
- TLSv1.2 / TLSv1.3。
- HSTS。
- `X-Content-Type-Options`。
- `X-Frame-Options`。
- `Referrer-Policy`。
- `Permissions-Policy`。
- gzip。
- 登录和 API 基础限流。
- 隐藏文件拒绝访问。
- `/api` 代理 backend。
- `/health` / `/ready` 代理 backend。
- 静态页面 fallback 到 `index.html`。

结论：

- `docker-compose.prod.yml` + `nginx/production.conf` 具备生产部署基础。
- 正式上线必须使用 production compose，不应使用默认 `docker-compose.yml`。

### A3. 数据库检查

连接配置：

- `backend/config.py` 默认 `DATABASE_URL` 为开发值：`tiantong:tiantong@postgres`。
- `.env.production.example` 要求 production 使用低权限 `tiantong_app`。
- Alembic 通过 `DATABASE_URL` 或 `get_settings().DATABASE_URL` 获取连接。

Migration 流程：

- `deploy.sh` Docker 模式会执行 `alembic upgrade head`。
- systemd service `ExecStartPre` 也会执行 `alembic upgrade head`。
- Sprint29 正式部署应采用人工先备份，再执行 migration 的流程。

备份方案：

- `scripts/backup_db.sh` 存在。
- 当前脚本默认读取 `.env`，默认用户为 `tiantong`。
- Sprint29 生产方案要求使用 `.env.production` 和生产 compose 执行备份。

结论：

- 数据库迁移机制存在。
- 生产备份必须按 Sprint29.10 / Sprint29.12 文档中的 `.env.production` 命令执行，不建议直接使用旧 `scripts/backup_db.sh` 默认模式。

### A4. Redis 检查

开发配置：

- `docker-compose.yml` Redis 无密码。
- `backend/config.py` 默认 `REDIS_URL=redis://redis:6379/0`。

生产配置：

- `.env.production.example` 使用 `REDIS_PASSWORD`。
- `docker-compose.prod.yml` 使用 `redis-server --appendonly yes --requirepass`。
- backend / worker 通过 `REDIS_URL=redis://:<REDIS_PASSWORD>@redis:6379/0` 接入。

发现问题：

- `scripts/healthcheck.sh` 的 `CHECK_DOCKER_INFRA=1` 深度检查中，Redis 检查仍使用 `redis-cli ping`，未带生产密码。

结论：

- 生产 Redis 认证配置存在。
- 生产深度健康检查脚本需要人工改用带密码命令，或暂不使用该脚本的 Redis 深度检查模式作为生产验收依据。

### A5. 服务检查

backend：

- Docker 入口：`uvicorn backend.main:app --host 0.0.0.0 --port 8000`。
- health endpoint：
  - `/api/health`
  - `/health`
  - `/api/ready`
  - `/ready`

worker：

- Docker 入口：`python -m backend.worker`。
- compose 中 worker 依赖 backend / postgres / redis healthy。

nginx：

- 生产配置反代到 `backend:8000`。
- 对外发布 `80` 和 `443`。
- 静态页面由 nginx 镜像内 `/usr/share/nginx/html` 提供。

healthcheck：

- backend 容器 healthcheck 请求 `http://127.0.0.1:8000/ready`。
- nginx 容器 healthcheck 请求 `https://127.0.0.1/`。
- postgres 和 redis 均配置 healthcheck。

结论：

- 服务启动入口完整。
- 健康检查链路存在。
- nginx 生产模式依赖 TLS 证书路径正确，否则 nginx 无法启动。

### A6. 安全检查

环境文件：

- `.env` 本地存在，权限为 `600`，已被 `.gitignore` 忽略。
- `.env.production` 当前本地不存在，已被 `.gitignore` 忽略。
- `.env.production.example` 使用占位符，没有真实密钥。

默认密码风险：

- `docker-compose.yml`、`.env.example`、`backend/config.py` 包含开发默认值。
- 正式生产不得使用默认 `.env.example` 或 `docker-compose.yml`。

API Key 风险：

- `.env.production.example` 中 `OPENAI_API_KEY`、`DEEPSEEK_API_KEY` 为空。
- 当前生产方案保持 mock provider，不要求真实模型 Key。

SSH 风险：

- Sprint29.13 已确认当前 Codex 环境无法 SSH 登录服务器。
- Sprint29.14 已生成专用部署用户和 SSH Key 方案。
- 在 SSH 认证链路建立前，不应执行自动化部署。

敏感信息：

- 本次未读取 `.env` 内容。
- 未发现生产文档新增真实密码、token、API Key 或私钥。

## B. 阻塞问题

1. `deploy.sh` 生产 Docker 模式默认仍依赖 `.env`，没有默认注入 `.env.production` 和 `--env-file .env.production`。
2. `deploy.sh ensure_env()` 会从 `.env.example` 创建 `.env`，这在生产首次部署中有误用风险。
3. systemd 模式使用 `.env` 和 HTTP Nginx 配置，不满足 Sprint29 生产 HTTPS 标准。
4. `scripts/backup_db.sh` 默认读取 `.env` 和开发用户，不适合作为生产备份默认命令。
5. `scripts/healthcheck.sh` 的 Redis 深度检查不支持生产 Redis 密码。
6. 当前 SSH 认证链路仍未建立，无法由 Codex 执行服务器环境检查。
7. Sprint29.7 到 Sprint29.14 文档仍未提交和推送，生产服务器无法从 GitHub main 拉取这些最新部署文档。
8. 真实 `.env.production`、TLS 证书、数据库备份、低权限 PostgreSQL 用户、Redis 密码尚未在服务器侧确认。

## C. 必须修复项

正式部署前必须处理：

1. 明确部署入口：首次生产部署建议不要直接执行 `./deploy.sh`，应按 Sprint29.10 / Sprint29.12 文档逐步人工执行。
2. 如果必须使用 `deploy.sh`，需先修复其生产环境变量读取逻辑，使其显式支持 `.env.production` 和 `docker compose --env-file .env.production -f docker-compose.prod.yml`。
3. 生产备份必须使用 `.env.production` 和 `docker-compose.prod.yml` 的命令，不使用旧 `scripts/backup_db.sh` 默认模式。
4. 建立 SSH 或 Workbench 受控部署通道。
5. 生产服务器执行只读环境检查并反馈结果。
6. 确认 `.env.production` 无占位符，权限为 `600`。
7. 确认 TLS 证书路径有效。
8. 确认 PostgreSQL / Redis / backend 未暴露公网。
9. 确认数据库备份成功后再迁移。
10. 确认 owner/admin 登录和 viewer 权限阻断。

## D. 可以上线项

在修复或规避阻塞问题后，以下部分具备上线基础：

- `docker-compose.prod.yml`
- `Dockerfile.backend`
- `Dockerfile.worker`
- `Dockerfile.frontend`
- `nginx/production.conf`
- backend 启动入口
- worker 启动入口
- Nginx API 代理和静态页面
- `/api/health`
- `/api/ready`
- `/health`
- `/ready`
- Alembic migration 机制
- Redis 生产认证配置
- PostgreSQL / Redis 不公网暴露的生产 compose 结构

## E. 下一步执行计划

### E1. 不部署前置动作

1. 老板确认是否接受“首次部署不直接运行 `deploy.sh`，改为按文档逐步执行”的策略。
2. 确认是否需要修复 `deploy.sh` 的生产环境变量读取逻辑。
3. 确认 Sprint29.7 到 Sprint29.14 文档是否提交。
4. 排除 `docs/SSH_FIX_REPORT.md`。
5. 建立 SSH 或 Workbench 部署通道。

### E2. 服务器只读检查

按 `docs/SPRINT29_13_SERVER_ENV_CHECK.md` 执行：

- Docker 版本
- Docker Compose 版本
- Git 版本
- Python / Node
- 磁盘空间
- 内存
- 端口占用
- 防火墙
- Docker 服务状态

### E3. 部署前人工确认

按 `docs/SPRINT29_12_FIRST_DEPLOY_PLAN.md` 确认：

- 目标 commit
- `.env.production`
- TLS 证书
- PostgreSQL 备份
- Redis 密码
- PostgreSQL 低权限用户
- 回滚负责人

### E4. 正式部署

仅在老板确认后执行：

1. GitHub main 同步。
2. `.env.production` 检查。
3. Docker build。
4. 数据库备份。
5. Alembic migration。
6. 服务启动。
7. health / ready 验证。
8. 登录和权限验证。
9. 日志检查。

## F. 是否允许进入阿里云正式部署

当前结论：暂不允许直接进入正式部署。

原因：

- 部署入口存在生产 `.env` 读取风险。
- 服务器环境尚未实际检查。
- SSH 认证仍未解决。
- 生产 `.env.production`、TLS、数据库备份和权限用户仍未确认。

允许进入下一步：

- 进入 Sprint29.15：修复或规避部署入口风险，并完成服务器只读环境检查。

不允许：

- 直接执行 `./deploy.sh` 进行生产部署。
- 未备份数据库直接 migration。
- 未确认 `.env.production` 直接启动服务。
- 未确认权限边界直接对外上线。
