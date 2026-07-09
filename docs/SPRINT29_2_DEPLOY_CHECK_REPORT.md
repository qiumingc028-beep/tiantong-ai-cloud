# Sprint29.2 天盾生产部署验收报告

验收目标：确认 Sprint29.1 生产配置可以进入部署阶段。

验收边界：

- 未执行正式服务器部署
- 未连接阿里云
- 未修改业务代码
- 未修改数据库结构

## A 已通过

### 1. docker-compose.prod.yml

检查结果：PASS

- `docker compose config` 可使用模板环境渲染成功：
  - `PRODUCTION_ENV_FILE=.env.production.example docker compose --env-file .env.production.example -f docker-compose.prod.yml config`
- PostgreSQL 未暴露宿主端口：
  - 仅在 compose 内部网络供 backend / worker 使用
  - 未配置 `5432:5432`
- Redis 未暴露宿主端口：
  - 仅在 compose 内部网络供 backend / worker 使用
  - 未配置 `6379:6379`
- Redis 密码机制存在：
  - `redis-server --appendonly yes --requirepass "$${REDIS_PASSWORD}"`
  - healthcheck 使用 `redis-cli -a "$${REDIS_PASSWORD}" ping`
- Redis 容器仅注入 `REDIS_PASSWORD`，不再注入 DATABASE_URL / JWT_SECRET 等无关 secret。
- backend / worker 使用 `.env.production`：
  - 生产部署必须通过真实 `.env.production` 注入 `DATABASE_URL`、`REDIS_URL`、`JWT_SECRET` 等变量。
- healthcheck 存在：
  - PostgreSQL：`pg_isready`
  - Redis：`redis-cli -a "$${REDIS_PASSWORD}" ping`
  - backend：`/ready`
  - nginx：HTTPS 本地检查
- 生产配置删除默认弱口令 fallback：
  - 缺少关键变量时 compose 配置会失败，避免弱口令误启动。

### 2. nginx/production.conf

检查结果：PASS

- HTTP 跳 HTTPS：
  - `return 301 https://$host$request_uri`
- HTTPS 配置存在：
  - `ssl_certificate`
  - `ssl_certificate_key`
  - TLS 1.2 / TLS 1.3
- 安全 Header 存在：
  - `Strict-Transport-Security`
  - `X-Content-Type-Options`
  - `X-Frame-Options`
  - `Referrer-Policy`
  - `Permissions-Policy`
- 限流存在：
  - `/api/login` 使用 `login_limit`
  - `/api/` 使用 `api_general`
- API 转发存在：
  - `/api/login`
  - `/api`
  - `/api/`
  - `/health`
  - `/ready`
- 静态资源入口存在：
  - `try_files $uri $uri/ /index.html`
- 隐藏文件保护存在：
  - `location ~ /\.` deny all

### 3. .env.production.example

检查结果：PASS

- 未发现真实私钥。
- 未发现真实 token。
- 未发现真实 API key。
- 未发现真实密码。
- 所有敏感值均为占位符：
  - `<APP_DB_PASSWORD>`
  - `<POSTGRES_ADMIN_PASSWORD>`
  - `<REDIS_PASSWORD>`
  - `<JWT_SECRET_64_PLUS_CHARS>`
  - `<ONE_TIME_ADMIN_RECOVERY_PASSWORD>`
- 明确生产运行账户：
  - `DATABASE_URL` 使用低权限应用用户 `tiantong_app`
- 明确 Redis 认证：
  - `REDIS_URL=redis://:<REDIS_PASSWORD>@redis:6379/0`

### 4. 静态检查

检查结果：PASS

- `git diff --check` 通过。
- 新增/修改配置未发现典型真实密钥形态：
  - `PRIVATE KEY`
  - `OPENSSH PRIVATE`
  - GitHub token
  - OpenAI `sk-` key
  - AWS `AKIA` key

## B 风险

1. PostgreSQL 权限降级仍需人工执行
   - 当前配置已要求 backend 使用 `tiantong_app`。
   - 但生产数据库中必须先创建该低权限用户并授予现有表、sequence 权限。

2. TLS 证书必须先准备
   - `docker-compose.prod.yml` 要求：
     - `TLS_CERT_PATH`
     - `TLS_KEY_PATH`
   - 证书不存在时 nginx 会启动失败。

3. Cookie Secure 仍需要后端配合
   - 当前生产 Nginx 已提供 HTTPS。
   - 后端 cookie 仍需在后续小改中根据 `APP_ENV=production` 设置 `secure=True`。
   - 本 Sprint29.2 不修改业务代码，因此只记录为待执行项。

4. backend / worker 仍以容器默认用户运行
   - 未开启非 root 用户。
   - 未开启 read-only rootfs。
   - 不阻塞本阶段，但进入公网长期运行前建议继续硬化。

5. `.env.production` 不存在于仓库
   - 这是正确策略。
   - 部署前必须由人工在服务器创建真实 `.env.production` 并设置 `chmod 600`。

6. `docs/SSH_FIX_REPORT.md` 仍是本地未跟踪文件
   - 不影响部署配置。
   - 提交前必须继续排除。

## C 部署前必须人工确认事项

1. 确认生产服务器 `.env.production`
   - 不使用 `.env.production.example` 直接部署。
   - 所有 `<...>` 占位符必须替换为强随机值。
   - 文件权限必须为 `600`。

2. 确认 PostgreSQL 用户策略
   - `postgres` 仅作为管理用户。
   - `tiantong_app` 作为 backend / worker 运行用户。
   - `tiantong_app` 不得具备 Superuser、Create DB、Create Role、Replication、Bypass RLS。

3. 确认 Redis 密码
   - `REDIS_PASSWORD` 为强随机值。
   - `REDIS_URL` 与 `REDIS_PASSWORD` 一致。

4. 确认 TLS 证书路径
   - `TLS_CERT_PATH` 指向 fullchain。
   - `TLS_KEY_PATH` 指向 private key。
   - 证书文件只存在服务器，不提交 Git。

5. 确认阿里云安全组
   - 仅开放 80 / 443 / 必要 SSH。
   - 不开放 5432。
   - 不开放 6379。
   - 不开放 backend 8000。

6. 确认部署命令
   - `PRODUCTION_ENV_FILE=.env.production docker compose --env-file .env.production -f docker-compose.prod.yml config`
   - `docker compose --env-file .env.production -f docker-compose.prod.yml build backend worker nginx`
   - `docker compose --env-file .env.production -f docker-compose.prod.yml run --rm backend alembic upgrade head`
   - `docker compose --env-file .env.production -f docker-compose.prod.yml up -d`

7. 确认上线后验证
   - `https://<domain>/api/health`
   - `https://<domain>/api/ready`
   - 登录
   - 老板驾驶舱
   - Task Center
   - AI员工中心
   - backend / worker / nginx 日志无 secret 泄露

## 结论

Sprint29.1 生产配置通过 Sprint29.2 静态部署验收。

允许进入下一步：人工确认 `.env.production`、PostgreSQL 降权、TLS 证书和阿里云安全组后，再进入天盾部署执行阶段。
