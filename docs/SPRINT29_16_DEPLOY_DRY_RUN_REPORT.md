# Sprint29.16 生产部署 Dry Run 报告

目标：在不正式上线、不启动生产服务的前提下，对天统AI V1 生产部署配置执行 dry run 验证。

执行边界：

- 未连接阿里云
- 未执行 `docker compose up`
- 未启动生产服务
- 未执行数据库迁移
- 未修改业务代码
- 未执行 `git push`

## A. 模拟部署结果

### A1. .env.production.example 检查

已检查文件：

- `.env.production.example`

包含配置：

- `APP_ENV=production`
- `DATABASE_URL`
- `POSTGRES_DB`
- `POSTGRES_ADMIN_USER`
- `POSTGRES_ADMIN_PASSWORD`
- `REDIS_PASSWORD`
- `REDIS_URL`
- `JWT_SECRET`
- `ADMIN_RESET_PASSWORD`
- `AI_PROVIDER`
- `OPENAI_API_KEY`
- `DEEPSEEK_API_KEY`
- `TLS_CERT_PATH`
- `TLS_KEY_PATH`
- `HTTP_PORT`
- `HTTPS_PORT`

结论：

- 模板字段完整。
- 模板使用占位符，没有写入真实密钥。
- 真实生产部署必须创建 `.env.production`，且不得保留 `<...>` 占位符。

### A2. docker-compose.prod.yml 检查

已检查文件：

- `docker-compose.prod.yml`

服务清单：

```text
postgres
redis
backend
nginx
worker
```

镜像 / 构建目标：

```text
tiantong-ai-cloud-backend
tiantong-ai-cloud-worker
tiantong-ai-cloud-nginx
postgres:16
redis:7
```

关键配置：

- PostgreSQL 使用 `postgres:16`。
- Redis 使用 `redis:7`。
- Redis 启用 `--requirepass`。
- backend 使用 `Dockerfile.backend`。
- worker 使用 `Dockerfile.worker`。
- nginx 使用 `Dockerfile.frontend`。
- backend 仅 `expose` 8000。
- nginx 仅发布 `80` / `443`。
- PostgreSQL 未发布公网端口。
- Redis 未发布公网端口。
- backend / worker / nginx / postgres / redis 均存在健康检查或依赖健康条件。

### A3. docker compose config 验证

执行命令：

```bash
PRODUCTION_ENV_FILE=.env.production.example \
docker compose --env-file .env.production.example -f docker-compose.prod.yml config
```

结果：

```text
PASS
```

说明：

- Compose 配置可渲染。
- 使用 `.env.production.example` 渲染时，输出中出现 `<...>` 是模板占位符，生产部署前必须替换。

### A4. docker compose build dry-run

执行命令：

```bash
PRODUCTION_ENV_FILE=.env.production.example \
docker compose --env-file .env.production.example -f docker-compose.prod.yml --dry-run build backend worker nginx
```

结果：

```text
Image tiantong-ai-cloud-backend Building
Image tiantong-ai-cloud-worker Building
Image tiantong-ai-cloud-nginx Building
Image backend Built
Image worker Built
Image nginx Built
```

结论：

- backend dry-run build 通过。
- worker dry-run build 通过。
- nginx dry-run build 通过。
- 本次未真实启动容器。
- 本次未执行生产 migration。
- 本次未连接生产服务器。

### A5. 服务逐项检查

#### backend

检查结果：

- 构建目标存在。
- 使用 `Dockerfile.backend`。
- 启动入口为 `uvicorn backend.main:app --host 0.0.0.0 --port 8000`。
- 依赖 postgres / redis healthy。
- healthcheck 请求 `/ready`。

结论：

- dry-run 通过。

#### worker

检查结果：

- 构建目标存在。
- 使用 `Dockerfile.worker`。
- 启动入口为 `python -m backend.worker`。
- 依赖 backend / postgres / redis healthy。

结论：

- dry-run 通过。

#### nginx

检查结果：

- 构建目标存在。
- 使用 `Dockerfile.frontend`。
- 加载 `nginx/production.conf`。
- 发布 `80` / `443`。
- TLS 证书通过只读 mount 注入。

结论：

- dry-run 通过。

#### postgres

检查结果：

- 使用 `postgres:16`。
- 有 named volume `postgres_data`。
- 有 healthcheck。
- 无公网端口发布。

结论：

- config 通过。

#### redis

检查结果：

- 使用 `redis:7`。
- 启用 appendonly。
- 启用 `--requirepass`。
- 有 named volume `redis_data`。
- 有带密码 healthcheck。
- 无公网端口发布。

结论：

- config 通过。

## B. 阻塞问题

当前 dry run 本身通过，但仍存在正式上线前阻塞项：

1. 生产服务器 SSH / Workbench 环境检查尚未完成。
2. 真实 `.env.production` 尚未在生产服务器确认。
3. `.env.production` 必须替换所有 `<...>` 占位符。
4. TLS 证书路径尚未在生产服务器确认。
5. PostgreSQL 生产备份尚未执行。
6. PostgreSQL 低权限应用用户 `tiantong_app` 尚未在服务器侧确认。
7. Redis 强密码尚未在服务器侧确认。
8. 阿里云安全组尚未在本轮确认是否只开放 `80` / `443` 和受控 SSH。
9. Sprint29.7 到 Sprint29.16 文档及 Sprint29.15 配置修复尚未提交和推送。
10. `docs/SSH_FIX_REPORT.md` 仍需继续排除，不得提交。

## C. 上线前最后清单

### C1. Git 与文档

```text
[ ] 提交 Sprint29.7 到 Sprint29.16 文档
[ ] 提交 Sprint29.15 部署配置修复
[ ] 确认 docs/SSH_FIX_REPORT.md 不进入 Git
[ ] 推送 GitHub main
[ ] 确认生产服务器拉取的 commit
```

### C2. 服务器环境

```text
[ ] 完成 Sprint29.13 服务器环境检查
[ ] Docker 可用
[ ] Docker Compose 可用
[ ] Git 可用
[ ] 磁盘空间不少于 10GB
[ ] 内存和负载正常
[ ] 80 / 443 可用
[ ] 5432 / 6379 / 8000 不对公网开放
```

### C3. 生产环境变量

```text
[ ] .env.production 已创建
[ ] .env.production 权限为 600
[ ] .env.production 无 <...> 占位符
[ ] JWT_SECRET 为长随机值
[ ] REDIS_PASSWORD 为强密码
[ ] DATABASE_URL 使用低权限 tiantong_app
[ ] OPENAI_API_KEY / DEEPSEEK_API_KEY 按审批结果为空或配置
```

### C4. 数据库和 Redis

```text
[ ] PostgreSQL 已备份
[ ] 备份文件非空
[ ] tiantong_app 低权限用户存在
[ ] Alembic current 已记录
[ ] Redis requirepass 生效
```

### C5. TLS 和 Nginx

```text
[ ] TLS_CERT_PATH 文件存在
[ ] TLS_KEY_PATH 文件存在
[ ] 证书未过期
[ ] 私钥权限受限
[ ] nginx production.conf 使用 HTTPS 和安全 Header
```

### C6. 上线验收

```text
[ ] /api/health 返回 200
[ ] /api/ready 返回 200
[ ] 登录成功
[ ] owner/admin 权限正常
[ ] viewer 无越权
[ ] 老板驾驶舱可访问
[ ] AI员工中心可访问
[ ] Task Center 可访问
[ ] backend / worker / nginx 日志无阻断错误
```

## D. 是否允许进入 Sprint29.17 正式部署

结论：暂不允许直接进入正式部署。

允许进入 Sprint29.17 的前提：

1. 老板确认提交并推送 Sprint29.7 到 Sprint29.16 文档和 Sprint29.15 配置修复。
2. 完成服务器 SSH / Workbench 接入检查。
3. 生产服务器确认 `.env.production`、TLS、数据库备份、Redis 密码、PostgreSQL 低权限用户。
4. 阿里云安全组确认无危险端口暴露。
5. 老板确认部署窗口和回滚负责人。

当前建议：

- 可以进入 Sprint29.16 结果审核。
- 不建议直接进入 Sprint29.17 正式部署执行。
