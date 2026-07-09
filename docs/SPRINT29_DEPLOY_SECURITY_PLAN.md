# Sprint29 天盾生产部署安全计划

目标：把 V1 冻结版本从内部运行环境升级为生产部署标准。

边界：

- 不新增业务功能
- 不修改 Task Center / AI员工 / Orchestrator 业务逻辑
- 不改变数据库结构
- 不直接部署公网

## 当前风险清单

1. `docker-compose.yml` 是内部运行配置，PostgreSQL / Redis 存在默认弱口令回退。
2. 现有 `docker-compose.prod.yml` 仍使用默认弱口令 fallback，Redis 未强制认证。
3. 现有 PostgreSQL 运行环境中应用用户存在超级用户风险，需要在生产切换为低权限应用用户。
4. Redis 当前未配置密码，虽然未暴露公网端口，但生产必须启用认证。
5. Nginx 默认配置仅提供 HTTP，没有 TLS、安全 Header、登录限流和 API 基础限流。
6. Cookie 安全需要后端配合 `APP_ENV=production` 启用 `Secure` 属性，当前本阶段只输出配置计划，不改认证业务逻辑。
7. Docker 容器仍以默认 root 用户运行，未启用只读 rootfs，属于后续硬化项。
8. `.env.example` 和 README 中仍有开发示例密码，不是真实密钥，但生产文档应统一引导使用 `.env.production.example`。

## A 已完成

1. 新增 `.env.production.example`
   - 只包含占位符，不包含真实密钥。
   - 敏感信息全部变量化。
   - 明确 `DATABASE_URL` 使用低权限应用用户 `tiantong_app`。
   - 明确 `REDIS_URL` 必须携带 Redis 密码。

2. 更新 `.gitignore`
   - 增加 `.env.production`，防止生产密钥文件被提交。

3. 更新 `docker-compose.prod.yml`
   - Redis 启用 `--requirepass`。
   - Redis healthcheck 使用认证。
   - backend / worker 读取 `.env.production`。
   - PostgreSQL / Redis 不暴露宿主公网端口。
   - Nginx 仅暴露 80 / 443。
   - 删除生产配置中的默认弱口令 fallback，缺失关键变量时 compose 会直接失败。

4. 更新 `Dockerfile.frontend`
   - 支持通过 `NGINX_CONF` build arg 选择 Nginx 配置。
   - 开发默认仍使用 `nginx/default.conf`。
   - 生产 compose 使用 `nginx/production.conf`。

5. 新增 `nginx/production.conf`
   - HTTP 自动跳转 HTTPS。
   - TLS 1.2 / 1.3。
   - HSTS、`X-Content-Type-Options`、`X-Frame-Options`、`Referrer-Policy`、`Permissions-Policy`。
   - `/api/login` 登录限流。
   - `/api/` 基础限流。
   - 禁止访问隐藏文件。
   - 保留 gzip 和 API 反代。

## B 待执行

1. 生产服务器创建 `.env.production`
   - 从 `.env.production.example` 复制。
   - 写入真实强密钥。
   - 设置权限：`chmod 600 .env.production`。

2. PostgreSQL 权限降级
   - 保留 `postgres` 作为管理用户。
   - 创建低权限运行用户：
     - `tiantong_app`
   - 授权当前业务库和 schema：
     - `CONNECT`
     - `USAGE ON SCHEMA public`
     - 对现有表授予 `SELECT, INSERT, UPDATE, DELETE`
     - 对现有 sequence 授予 `USAGE, SELECT, UPDATE`
     - 配置 default privileges，覆盖后续表和 sequence。
   - 将 `.env.production` 的 `DATABASE_URL` 切换到 `tiantong_app`。

3. Redis 认证切换
   - 生成强 `REDIS_PASSWORD`。
   - 更新 `.env.production`。
   - 使用 `docker compose --env-file .env.production -f docker-compose.prod.yml config` 验证配置。

4. TLS 证书准备
   - 使用阿里云证书、Let's Encrypt 或上游 SLB 证书。
   - 将证书路径写入：
     - `TLS_CERT_PATH`
     - `TLS_KEY_PATH`

5. Cookie Secure 配置
   - 需要后端在 `APP_ENV=production` 时设置 `secure=True`。
   - 该项涉及认证代码变更，应单独进入天王开发和天监审计，不在本配置准备阶段直接修改。

6. 生产部署前检查
   - `git rev-parse HEAD`
   - `docker compose --env-file .env.production -f docker-compose.prod.yml config`
   - 本地模板检查可用：`PRODUCTION_ENV_FILE=.env.production.example docker compose --env-file .env.production.example -f docker-compose.prod.yml config`
   - `docker compose --env-file .env.production -f docker-compose.prod.yml build backend worker nginx`
   - `docker compose --env-file .env.production -f docker-compose.prod.yml run --rm backend alembic upgrade head`
   - `docker compose --env-file .env.production -f docker-compose.prod.yml up -d`
   - 验证 `/api/health`、`/api/ready`、登录、老板驾驶舱、Task Center。

## C 后续优化

1. backend / worker 改为非 root 用户运行。
2. Docker `read_only: true` 和 `cap_drop: ["ALL"]` 分阶段验证。
3. JWT 不再返回 response body，仅使用 HttpOnly Secure Cookie。
4. 登录失败次数限制和账号临时锁定。
5. 接入阿里云 KMS / Secrets Manager。
6. 接入 WAF / CDN / SLB 统一 TLS。
7. 完整 CSP 策略，需要先改造现有前端 inline script。
8. 蓝绿部署和数据库备份自动化。
9. 镜像 SBOM 和漏洞扫描。
10. 生产审计日志集中化。

## 生产执行注意事项

- 不提交 `.env.production`。
- 不在文档、日志、聊天窗口粘贴真实密码、token、secret、API key。
- 不删除 PostgreSQL / Redis volume。
- 不执行数据库 downgrade。
- 不跳过天检、天监、天盾流程。
