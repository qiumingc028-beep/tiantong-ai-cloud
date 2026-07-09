# Sprint29.15 生产部署前配置修复报告

目标：修复 Sprint29.14 部署验收中发现的生产配置问题，使首次正式部署入口统一使用 `.env.production`，避免误读开发 `.env`。

执行边界：

- 未连接阿里云
- 未执行正式部署
- 未执行 `docker compose up`
- 未修改业务代码
- 未修改数据库结构

## A. 修改文件列表

### 已修改

- `deploy.sh`
- `deploy/tiantong-api.service`
- `deploy/tiantong-worker.service`

### 已检查

- `.env.production.example`
- `docker-compose.prod.yml`
- `nginx/production.conf`

## B. 修改内容

### B1. deploy.sh

修复前：

- 默认使用 `.env`。
- 缺少 `.env` 时会从 `.env.example` 自动生成。
- Docker 模式默认命令为 `docker compose -f docker-compose.prod.yml`，未显式传入 `--env-file .env.production`。

修复后：

- 新增 `ENV_FILE="${ENV_FILE:-.env.production}"`。
- `COMPOSE_CMD` 统一为：

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml
```

- 缺少 `.env.production` 时直接失败。
- `.env.production` 仍包含 `<...>` 占位符时直接失败。
- 自动设置 `.env.production` 权限为 `600`。
- 不再从 `.env.example` 生成 `.env`。
- systemd 模式也通过同一个 `ENV_FILE` 读取生产变量。

### B2. systemd service

修复文件：

- `deploy/tiantong-api.service`
- `deploy/tiantong-worker.service`

修复前：

```text
EnvironmentFile=-/data/apps/tiantong-ai-cloud/.env
```

修复后：

```text
EnvironmentFile=/data/apps/tiantong-ai-cloud/.env.production
```

影响：

- systemd 生产运行不再读取开发 `.env`。
- `.env.production` 缺失时 systemd 服务不会静默使用空环境。

### B3. .env.production.example

当前已包含：

- PostgreSQL 配置
- Redis 配置
- JWT 配置
- API 配置
- 环境标识 `APP_ENV=production`
- TLS 证书路径
- HTTP / HTTPS 端口

结论：

- 当前模板满足 Sprint29.15 要求。
- 模板只包含占位符，不包含真实密钥。

### B4. nginx production 配置

已确认：

- HTTP 跳 HTTPS。
- TLSv1.2 / TLSv1.3。
- HSTS。
- `X-Content-Type-Options`。
- `X-Frame-Options`。
- `Referrer-Policy`。
- `Permissions-Policy`。
- 登录限流。
- API 限流。
- 隐藏文件拒绝访问。
- `/api`、`/health`、`/ready` 正确反代到 backend。

未修改：

- `nginx/production.conf`

## C. 风险说明

### C1. 已降低风险

- 避免生产部署误读 `.env`。
- 避免生产部署从 `.env.example` 自动生成开发默认配置。
- 避免生产 Docker Compose 在缺失 `.env.production` 时继续执行。
- 避免 systemd 服务静默忽略环境文件缺失。

### C2. 仍需人工确认的风险

- `.env.production` 必须在服务器人工创建。
- `.env.production` 中所有占位符必须替换。
- `JWT_SECRET` 必须使用长随机值。
- Redis 密码必须设置强密码。
- PostgreSQL 应使用低权限应用用户。
- TLS 证书路径必须在服务器存在。
- 数据库迁移前必须完成备份。

### C3. 仍不建议直接执行的入口

虽然 `deploy.sh` 已修复生产环境文件读取，但首次生产部署仍建议按照文档逐步执行：

- `docs/SPRINT29_10_PRODUCTION_DEPLOY_EXECUTION.md`
- `docs/SPRINT29_12_FIRST_DEPLOY_PLAN.md`

原因：

- 首次生产部署需要逐步确认 Git、环境变量、备份、migration、服务启动和权限验收。

## D. 验证结果

已执行静态验证：

```bash
bash -n deploy.sh
```

结果：

- 通过。

已执行生产 Compose 渲染检查：

```bash
PRODUCTION_ENV_FILE=.env.production.example \
docker compose --env-file .env.production.example -f docker-compose.prod.yml config
```

结果：

- 通过。

已检查 `.env` 引用：

- `deploy.sh` 默认指向 `.env.production`。
- `deploy/tiantong-api.service` 指向 `.env.production`。
- `deploy/tiantong-worker.service` 指向 `.env.production`。
- `docker-compose.prod.yml` 指向 `.env.production`。
- 未发现生产部署入口继续强制读取 `.env`。

已检查 Nginx 生产配置：

- HTTPS、安全 Header、限流、反代、静态 fallback 均存在。

未执行：

- 未执行 `docker compose up`。
- 未连接阿里云。
- 未执行 migration。
- 未启动生产服务。

## E. 下一步部署条件

进入正式部署前必须满足：

1. Sprint29.15 修改提交并推送 GitHub main。
2. `docs/SSH_FIX_REPORT.md` 继续排除。
3. 生产服务器完成 SSH / Workbench 接入确认。
4. 生产服务器执行 Sprint29.13 只读环境检查。
5. 服务器创建 `.env.production`，权限为 `600`。
6. `.env.production` 不存在任何 `<...>` 占位符。
7. PostgreSQL 已备份。
8. Redis 强密码已配置。
9. TLS 证书路径有效。
10. 阿里云安全组未开放 `5432` / `6379` / `8000`。
11. owner/admin 登录和 viewer 权限阻断可验证。

当前结论：

- Sprint29.15 生产配置修复已完成。
- 当前仍不执行正式部署。
- 等待老板确认后进入提交、推送和服务器只读检查阶段。
