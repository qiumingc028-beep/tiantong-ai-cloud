# Sprint29.8 正式上线前最终检查报告

目标：正式连接阿里云和执行部署前，确认 Git、Docker、数据安全、安全配置、回滚方案和上线标准。

执行边界：

- 未连接阿里云
- 未执行生产部署
- 未修改业务代码
- 未修改数据库结构

## 1. Git 版本确认

### 当前状态

- 当前本地 commit：
  - `61f0244ef327d04c9f8d94f2bb035cabd2e729ff`
- 当前分支：
  - `main`
- 当前远程 `origin/main`：
  - `99d7cc9cd6937df7c9f1198cf28dfe460fc8c8fc`

### 判断

当前本地 `main` 包含 Sprint29 生产部署文档和生产配置提交，但尚未同步到 `origin/main`。

### 上线前要求

- 必须先完成 Sprint29 文档/配置提交同步到 GitHub main。
- 阿里云部署时必须拉取已审批的 GitHub main commit。
- 服务器部署前必须再次确认：
  - `git rev-parse HEAD`
  - `git log -1 --oneline`

### 风险

- 如果不先推送 `61f0244` 或后续审批提交到 GitHub main，阿里云服务器无法拉取 Sprint29 生产配置。

## 2. Docker 生产环境确认

### docker-compose.prod.yml

已确认：

- 可使用模板环境渲染。
- backend / worker 使用 `Dockerfile.backend` / `Dockerfile.worker`。
- nginx 使用 `Dockerfile.frontend`，并通过 `NGINX_CONF=nginx/production.conf` 使用生产配置。
- PostgreSQL 不映射公网端口。
- Redis 不映射公网端口。
- backend 只 expose 8000，不映射公网端口。
- nginx 暴露 80 / 443。

### backend

已确认：

- 使用生产环境变量。
- healthcheck 指向 `/ready`。
- 依赖 PostgreSQL 和 Redis healthy。

### worker

已确认：

- 使用生产环境变量。
- 依赖 backend / PostgreSQL / Redis。
- 启动命令为 `python -m backend.worker`。

### nginx

已确认：

- 暴露 80 / 443。
- 挂载 TLS 证书和私钥。
- healthcheck 使用 HTTPS 本机访问。

### postgres

已确认：

- 使用 PostgreSQL 16。
- 不暴露公网端口。
- 使用 volume 保存数据。
- healthcheck 使用 `pg_isready`。

### redis

已确认：

- 使用 Redis 7。
- 不暴露公网端口。
- 使用 `--requirepass "$${REDIS_PASSWORD}"`。
- healthcheck 使用 `redis-cli -a "$${REDIS_PASSWORD}" ping`。

## 3. 数据安全确认

### 数据库备份方案

已确认 Runbook 中包含部署前备份：

```bash
mkdir -p /data/backups/tiantong-ai-cloud
docker compose --env-file .env.production -f docker-compose.prod.yml exec -T postgres \
  pg_dump -U "$POSTGRES_ADMIN_USER" "$POSTGRES_DB" \
  > /data/backups/tiantong-ai-cloud/backup_$(date +%Y%m%d_%H%M%S).sql
```

上线前必须确认：

- 备份文件实际生成。
- 备份文件大小合理。
- 不删除 PostgreSQL volume。
- 不重建数据库。

### Redis 数据保护

已确认：

- Redis 不对公网暴露。
- Redis 生产配置启用密码。
- Redis 使用 volume 保存数据。

上线前必须确认：

- `REDIS_PASSWORD` 与 `REDIS_URL` 一致。
- 不删除 Redis volume。

### migration 状态

已确认 Runbook 中包含：

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml run --rm backend alembic upgrade head
docker compose --env-file .env.production -f docker-compose.prod.yml run --rm backend alembic current
```

上线前必须确认：

- migration 成功。
- current 为 head。
- 不执行 downgrade。

## 4. 安全确认

### 密码

已确认：

- `.env.production.example` 只保留占位符。
- `.env.production` 已加入 `.gitignore`。

上线前必须确认：

- `.env.production` 不含 `<...>` 占位符。
- `POSTGRES_ADMIN_PASSWORD` 为强随机值。
- `REDIS_PASSWORD` 为强随机值。
- `ADMIN_RESET_PASSWORD` 如启用，必须一次性使用并轮换。

### Token / API Key

已确认：

- 模板中 `OPENAI_API_KEY` 和 `DEEPSEEK_API_KEY` 为空。
- 当前计划保持 `AI_PROVIDER=mock`。

上线前必须确认：

- 不在 Git、文档、日志、聊天窗口中记录真实 API Key。

### JWT_SECRET

上线前必须确认：

- `JWT_SECRET` 为强随机值。
- 不使用示例值。
- 不输出到日志。

### Cookie Secure

当前状态：

- Nginx 生产配置已准备 HTTPS。
- 后端仍需小改以在 `APP_ENV=production` 下设置 cookie `secure=True`。

风险判断：

- 若是受控试运行，可以由老板确认接受短期风险。
- 若是公网长期运行，建议先修复 Cookie Secure 后再正式发布。

### HTTPS 准备

已确认：

- `nginx/production.conf` 包含 HTTP 跳 HTTPS。
- TLS 证书路径由 `.env.production` 提供。
- 安全 Header 已配置。
- `/api/login` 和 `/api/` 已配置基础限流。

上线前必须确认：

- `TLS_CERT_PATH` 指向有效 fullchain。
- `TLS_KEY_PATH` 指向有效 private key。
- 证书未过期。

## 5. 回滚方案确认

### Git 回滚

已确认 Runbook 中包含：

```bash
git log --oneline -5
git reset --hard <previous_stable_commit>
docker compose --env-file .env.production -f docker-compose.prod.yml build backend worker nginx
docker compose --env-file .env.production -f docker-compose.prod.yml up -d --force-recreate backend worker nginx
```

### Docker 回滚

已确认 Runbook 中包含旧镜像标记方案：

```bash
docker tag tiantong-ai-cloud-backend:latest tiantong-ai-cloud-backend:backup-$(date +%Y%m%d_%H%M%S)
docker tag tiantong-ai-cloud-worker:latest tiantong-ai-cloud-worker:backup-$(date +%Y%m%d_%H%M%S)
```

### 数据库恢复

已确认原则：

- 不自动 downgrade。
- 不删除 volume。
- 不重建数据库。
- 不执行 `docker volume rm`。
- 如需数据库恢复，必须使用部署前备份，并经过老板二次确认。

## 6. 上线成功标准

上线成功必须同时满足：

1. Git HEAD 等于老板确认的 GitHub main commit。
2. `.env.production` 存在，权限为 600，无占位符。
3. PostgreSQL 已备份。
4. `tiantong_app` 低权限用户存在且权限正确。
5. Redis 密码配置正确。
6. TLS 证书存在且未过期。
7. Docker build 成功。
8. Alembic upgrade 成功，current 为 head。
9. backend healthy。
10. postgres healthy。
11. redis healthy。
12. worker running。
13. nginx healthy / running。
14. `/api/health` 返回 200。
15. `/api/ready` 返回 200。
16. 首页和核心页面返回 200，浏览器不白屏。
17. 未登录管理 API 返回 401。
18. owner / boss / admin 登录成功。
19. viewer 无越权。
20. backend / worker / nginx 日志无持续 500、Traceback、ImportError、secret 泄露。

## 7. 上线失败停止条件

满足任一条件必须停止上线：

1. 目标 ECS 无法确认。
2. Git HEAD 与审批 commit 不一致。
3. `.env.production` 缺失或仍有占位符。
4. `.env.production` 权限不是 600。
5. PostgreSQL 备份失败。
6. `tiantong_app` 不存在或权限过高。
7. Redis 密码与 `REDIS_URL` 不一致。
8. TLS 证书不存在或过期。
9. Docker build 失败。
10. Alembic migration 失败。
11. backend / postgres / redis / nginx 非 healthy。
12. worker 持续重启。
13. `/api/health` 或 `/api/ready` 非 200。
14. 核心页面 404 / 500 / 白屏。
15. 未登录管理 API 返回 200。
16. viewer 可访问管理接口。
17. 日志出现 password / token / secret / private key 泄露。
18. 发现 5432 / 6379 / 8000 对公网开放。

## 8. 最终结论

当前 Sprint29.8 检查结论：

- 生产配置和部署文档已基本就绪。
- 当前本地 Sprint29 提交尚未同步到 `origin/main`。
- 在正式阿里云部署前，必须先完成 GitHub main 同步。
- Cookie Secure 仍是需要老板确认的短期风险，或进入小修复后再部署。

建议：

1. 先提交并推送 Sprint29.7 / Sprint29.8 文档。
2. 确认 GitHub main 最新 commit。
3. 老板确认 Cookie Secure 风险处理方式。
4. 再进入阿里云正式部署执行。
