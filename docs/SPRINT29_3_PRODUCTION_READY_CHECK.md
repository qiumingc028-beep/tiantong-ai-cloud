# Sprint29.3 生产部署冻结检查

目标：在正式部署前，确认 V1 可以进入生产部署。

执行边界：

- 未连接阿里云
- 未执行生产部署
- 未修改业务代码
- 未新增功能

## A. 当前可以部署项

### 1. Git 与文件范围

当前 Sprint29 生产化文件完整：

- `.gitignore`
- `.env.production.example`
- `Dockerfile.frontend`
- `docker-compose.prod.yml`
- `nginx/production.conf`
- `docs/SPRINT29_DEPLOY_SECURITY_PLAN.md`
- `docs/SPRINT29_2_DEPLOY_CHECK_REPORT.md`
- `docs/SPRINT29_3_PRODUCTION_READY_CHECK.md`

确认：

- `.env` 已被 `.gitignore` 忽略。
- `.env.production` 已被 `.gitignore` 忽略。
- `docs/SSH_FIX_REPORT.md` 未跟踪，保持排除。
- `git diff --check` 通过。
- 未发现真实私钥、真实 token、真实 API key。

### 2. Docker 生产配置

`docker-compose.prod.yml` 静态检查通过：

- 可使用模板环境渲染：
  - `PRODUCTION_ENV_FILE=.env.production.example docker compose --env-file .env.production.example -f docker-compose.prod.yml config`
- PostgreSQL 不暴露公网端口。
- Redis 不暴露公网端口。
- Redis 启用密码：
  - `redis-server --appendonly yes --requirepass "$${REDIS_PASSWORD}"`
- Redis healthcheck 使用密码：
  - `redis-cli -a "$${REDIS_PASSWORD}" ping`
- backend / worker 通过 `.env.production` 注入运行环境。
- nginx 暴露 80 / 443。
- backend 只 expose 8000 给内部网络。
- 关键服务均配置 healthcheck：
  - PostgreSQL
  - Redis
  - backend
  - nginx

### 3. Dockerfile

生产相关 Dockerfile 检查通过：

- `Dockerfile.backend`
  - Python 3.12
  - 安装 requirements
  - 启动 `uvicorn backend.main:app`
- `Dockerfile.worker`
  - Python 3.12
  - 安装 requirements
  - 启动 `python -m backend.worker`
- `Dockerfile.frontend`
  - 支持 `NGINX_CONF` build arg
  - 生产 compose 使用 `nginx/production.conf`

### 4. Nginx 生产配置

`nginx/production.conf` 检查通过：

- HTTP 自动跳转 HTTPS。
- TLS 证书路径配置存在。
- 安全 Header 存在：
  - HSTS
  - `X-Content-Type-Options`
  - `X-Frame-Options`
  - `Referrer-Policy`
  - `Permissions-Policy`
- 登录限流存在：
  - `/api/login`
- API 基础限流存在：
  - `/api`
  - `/api/`
- API 反向代理存在：
  - `/api/login`
  - `/api`
  - `/api/`
  - `/health`
  - `/ready`
- 静态资源 fallback 存在：
  - `try_files $uri $uri/ /index.html`
- 隐藏文件访问禁止：
  - `location ~ /\.`

### 5. 生产环境模板

`.env.production.example` 检查通过：

- 不包含真实密码。
- 不包含真实 token。
- 不包含真实 API key。
- 不包含私钥。
- 所有敏感项均为占位符。
- 明确低权限应用用户：
  - `tiantong_app`
- 明确 Redis 认证：
  - `REDIS_PASSWORD`
  - `REDIS_URL`

## B. 部署前人工确认项

1. 创建生产 `.env.production`
   - 不使用 `.env.production.example` 直接部署。
   - 替换全部 `<...>` 占位符。
   - 使用强随机值。
   - 执行 `chmod 600 .env.production`。

2. PostgreSQL 权限降级
   - 确认生产数据库存在低权限用户 `tiantong_app`。
   - `tiantong_app` 仅具备业务表和 sequence 的必要权限。
   - `tiantong_app` 不得拥有：
     - Superuser
     - Create DB
     - Create Role
     - Replication
     - Bypass RLS

3. Redis 密码
   - 确认 `REDIS_PASSWORD` 为强随机值。
   - 确认 `REDIS_URL` 与 `REDIS_PASSWORD` 一致。

4. TLS 证书
   - 确认 `TLS_CERT_PATH` 指向 fullchain。
   - 确认 `TLS_KEY_PATH` 指向 private key。
   - 确认证书文件存在于生产服务器。
   - 确认证书文件不会进入 Git。

5. 阿里云安全组
   - 只开放 80 / 443 / 必要 SSH。
   - 不开放 5432。
   - 不开放 6379。
   - 不开放 8000。

6. 生产配置渲染
   - 执行：
     - `PRODUCTION_ENV_FILE=.env.production docker compose --env-file .env.production -f docker-compose.prod.yml config`
   - 确认无缺失变量。

7. 部署前备份
   - 备份 PostgreSQL volume。
   - 记录当前 Git commit。
   - 记录当前 Docker 镜像版本。

8. Cookie Secure
   - 当前配置层已具备 HTTPS。
   - 后端仍需后续小改以 `APP_ENV=production` 设置 cookie `secure=True`。
   - 若本次直接公网发布，必须人工评估该风险。

## C. 上线风险

1. Cookie `Secure` 仍需后端配合
   - 风险等级：中
   - 说明：HTTPS 已准备，但后端 cookie 还需要生产环境下设置 `secure=True`。
   - 建议：正式公网前单独修复并审计。

2. 容器非 root / read-only rootfs 尚未完成
   - 风险等级：低到中
   - 说明：当前生产配置未强制非 root 用户运行，也未开启只读 rootfs。
   - 建议：V1 可后置，V2 做容器硬化。

3. PostgreSQL 降权依赖人工执行
   - 风险等级：中
   - 说明：配置已要求低权限用户，但数据库内用户创建和授权必须人工完成。
   - 建议：部署前必须验证 `\du` 和权限。

4. TLS 证书依赖人工准备
   - 风险等级：中
   - 说明：证书路径不正确会导致 nginx 启动失败。
   - 建议：部署前先检查证书路径和权限。

5. `.env.production` 不在仓库
   - 风险等级：低
   - 说明：这是正确安全策略，但部署时必须人工创建。

6. `docs/SSH_FIX_REPORT.md` 本地未跟踪
   - 风险等级：低
   - 说明：包含 SSH 接入诊断上下文，继续保持不提交。

## D. 回滚方案

### 1. 应用回滚

1. 记录当前线上 commit：
   - `git rev-parse HEAD`
2. 如部署失败，回滚到上一稳定 commit：
   - `git reset --hard <previous_stable_commit>`
3. 重新构建：
   - `docker compose --env-file .env.production -f docker-compose.prod.yml build backend worker nginx`
4. 重启：
   - `docker compose --env-file .env.production -f docker-compose.prod.yml up -d --force-recreate backend worker nginx`

### 2. 配置回滚

1. 保留上一份 `.env.production` 备份。
2. 如 Redis 密码或 DB 用户切换失败：
   - 恢复 `.env.production`。
   - 重启 backend / worker / redis。

### 3. 数据库回滚

1. 本阶段不新增数据库结构。
2. 不执行自动 downgrade。
3. 如数据库用户授权失败：
   - 使用 PostgreSQL 管理用户修复授权。
   - 不删除 volume。
   - 不重建数据库。

### 4. Nginx 回滚

1. 若 HTTPS 配置导致 nginx 启动失败：
   - 检查证书路径。
   - 临时回退到上一版 nginx 配置。
   - 保持 backend / worker / postgres / redis 不变。

### 5. 验证回滚成功

必须验证：

- `/api/health`
- `/api/ready`
- 登录
- 老板驾驶舱
- Task Center
- AI员工中心

## 结论

Sprint29.3 生产部署冻结检查通过。

允许在老板确认后进入正式部署准备，但正式公网发布前必须人工确认：

- `.env.production`
- PostgreSQL 低权限用户
- Redis 密码
- TLS 证书
- 阿里云安全组
- Cookie Secure 风险接受或修复计划
