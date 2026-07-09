# Sprint29.11 阿里云第一次正式部署预检查

目标：在第一次正式部署天统AI V1 前，确认本地状态、生产配置、环境变量、数据库迁移风险和回滚条件。本文档只做检查和准备，不代表已经执行部署。

执行边界：

- 未连接阿里云
- 未执行 SSH
- 未执行 `docker compose up`
- 未修改业务代码
- 未执行 `git push`

## A. 本地环境确认

### A1. Git 状态

当前检查结果：

- 当前分支：`main`
- 最新本地 commit：`61f0244 Sprint29 production deployment readiness`
- 当前存在未提交 Sprint29 部署文档：
  - `docs/SPRINT29_7_DEPLOY_DRY_RUN_REPORT.md`
  - `docs/SPRINT29_7_PRODUCTION_DEPLOY_PLAN.md`
  - `docs/SPRINT29_8_GO_LIVE_FINAL_CHECK.md`
  - `docs/SPRINT29_8_RELEASE_SUMMARY.md`
  - `docs/SPRINT29_9_FINAL_SECURITY_GATE.md`
  - `docs/SPRINT29_10_PRODUCTION_DEPLOY_EXECUTION.md`
  - `docs/SPRINT29_11_PRE_DEPLOY_CHECK.md`
- 本地未跟踪且不应提交：
  - `docs/SSH_FIX_REPORT.md`

结论：

- 业务代码未在本次检查中修改。
- 正式部署前，应先由老板确认是否提交 Sprint29.7 到 Sprint29.11 文档。
- `docs/SSH_FIX_REPORT.md` 必须继续排除。

### A2. Docker 配置

已确认文件存在：

- `docker-compose.yml`
- `docker-compose.prod.yml`
- `Dockerfile.backend`
- `Dockerfile.worker`
- `Dockerfile.frontend`
- `nginx/production.conf`
- `.env.production.example`

生产配置要点：

- `docker-compose.prod.yml` 使用 `postgres:16`。
- `docker-compose.prod.yml` 使用 `redis:7`。
- backend 只 `expose` 8000，不直接发布公网端口。
- nginx 发布 `80` 和 `443`。
- PostgreSQL 未配置公网端口映射。
- Redis 未配置公网端口映射。
- Redis 使用 `--requirepass`。
- backend / worker 通过 `.env.production` 读取生产环境变量。
- nginx 挂载 TLS 证书和私钥，只读加载。

### A3. Nginx 生产配置

已确认：

- HTTP 跳转 HTTPS。
- TLS 协议限制为 TLSv1.2 / TLSv1.3。
- 存在 HSTS。
- 存在 `X-Content-Type-Options`。
- 存在 `X-Frame-Options`。
- 存在 `Referrer-Policy`。
- 存在基础 `Permissions-Policy`。
- 登录接口有限流。
- API 接口有基础限流。
- 隐藏文件访问被拒绝。
- 静态页面 fallback 到 `index.html`。

### A4. 当前本地预检查结论

当前本地配置满足进入正式部署准备阶段，但还不满足直接部署条件。

未满足项：

- Sprint29.7 到 Sprint29.11 文档尚未提交。
- Sprint29 文档尚未推送 GitHub main。
- 真实 `.env.production` 尚需在生产服务器人工准备。
- 数据库备份、TLS 证书、低权限数据库用户、Redis 密码需要在阿里云部署前人工确认。

## B. 阿里云需要准备事项

### B1. ECS 基础环境

必须确认：

- 目标 ECS 正确。
- 部署路径为 `/data/apps/tiantong-ai-cloud`。
- 登录方式已审批：Workbench / SSH Key / 其他审批方式。
- 部署用户具备 Docker 权限。
- 磁盘可用空间不少于 10GB。
- 系统时间和时区正常。
- 当前部署窗口允许短暂重启。

建议检查命令：

```bash
whoami
hostname
date
timedatectl
df -h
docker --version
docker compose version
```

### B2. 网络与安全组

必须确认：

- 允许公网访问：`80`、`443`
- 不允许公网访问：`5432`、`6379`、`8000`
- SSH / Workbench 入口仅允许可信来源访问。
- 如使用域名，DNS 已解析到目标 ECS。
- 如使用 HTTPS，TLS 证书已准备。

### B3. TLS 证书

必须确认：

- `TLS_CERT_PATH` 指向有效 `fullchain.pem`。
- `TLS_KEY_PATH` 指向有效 `privkey.pem`。
- 证书未过期。
- 私钥文件权限受限。

### B4. 数据库和 Redis

必须确认：

- PostgreSQL 生产数据已备份。
- PostgreSQL 管理账户只用于初始化和迁移。
- backend 使用低权限 `tiantong_app` 运行账户。
- Redis 设置强密码。
- Redis URL 包含认证信息。
- PostgreSQL / Redis 不对公网暴露。

## C. 环境变量清单

生产环境文件：

- `.env.production`

该文件只应存在于生产服务器，不应提交 Git。

必须配置：

```bash
APP_ENV=production
DATABASE_URL=postgresql+psycopg2://tiantong_app:<APP_DB_PASSWORD>@postgres:5432/tiantong_ai
POSTGRES_DB=tiantong_ai
POSTGRES_ADMIN_USER=postgres
POSTGRES_ADMIN_PASSWORD=<POSTGRES_ADMIN_PASSWORD>
REDIS_PASSWORD=<REDIS_PASSWORD>
REDIS_URL=redis://:<REDIS_PASSWORD>@redis:6379/0
JWT_SECRET=<JWT_SECRET_64_PLUS_CHARS>
AI_PROVIDER=mock
OPENAI_API_KEY=
DEEPSEEK_API_KEY=
TLS_CERT_PATH=/path/to/fullchain.pem
TLS_KEY_PATH=/path/to/privkey.pem
HTTP_PORT=80
HTTPS_PORT=443
```

可选配置：

```bash
ADMIN_RESET_PASSWORD=<ONE_TIME_ADMIN_RECOVERY_PASSWORD>
```

安全要求：

- `.env.production` 权限建议为 `600`。
- 不允许包含占位符。
- 不允许提交 Git。
- 不允许在日志中输出。
- `JWT_SECRET` 必须为长随机值。
- `ADMIN_RESET_PASSWORD` 如使用，完成恢复后必须轮换或移除。

部署前检查：

```bash
ls -l .env.production
grep -n '<.*>' .env.production && echo "ERROR: placeholder exists" || echo "OK: no placeholder"
chmod 600 .env.production
PRODUCTION_ENV_FILE=.env.production docker compose --env-file .env.production -f docker-compose.prod.yml config
```

## D. 数据库迁移注意事项

### D1. 迁移前要求

必须先完成：

- 生产数据库备份。
- 确认当前 Alembic 版本。
- 确认目标代码 commit。
- 确认 migration 文件完整。
- 确认 `tiantong_app` 低权限用户已创建。

建议命令：

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml exec -T postgres \
  pg_dump -U "$POSTGRES_ADMIN_USER" "$POSTGRES_DB" \
  > /data/backups/tiantong-ai-cloud/backup_$(date +%Y%m%d_%H%M%S).sql

docker compose --env-file .env.production -f docker-compose.prod.yml run --rm backend alembic current
docker compose --env-file .env.production -f docker-compose.prod.yml run --rm backend alembic heads
```

### D2. 执行迁移

建议命令：

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml run --rm backend alembic upgrade head
docker compose --env-file .env.production -f docker-compose.prod.yml run --rm backend alembic current
```

成功标准：

- migration 升级成功。
- `alembic current` 等于 head。
- backend 启动后 `/api/ready` 返回 200。

停止条件：

- 备份失败。
- migration 报错。
- 表结构异常。
- backend 无法连接数据库。

### D3. 禁止事项

- 禁止未备份直接迁移。
- 禁止执行破坏性数据库操作。
- 禁止删除 volume。
- 禁止为了通过部署而绕过 migration 错误。

## E. 第一次上线风险

### E1. Git 状态风险

风险：

- 本地 Sprint29.7 到 Sprint29.11 文档尚未提交和推送，生产服务器无法拉取这些最新部署文档。

处理：

- 老板确认后提交文档。
- 排除 `docs/SSH_FIX_REPORT.md`。
- 推送 GitHub main。
- 再执行生产拉取。

### E2. 环境变量风险

风险：

- `.env.production` 缺失或仍包含占位符会导致服务无法启动。
- `JWT_SECRET` 弱或复用会影响登录安全。
- Redis 密码未配置会导致 Redis 无认证。

处理：

- 部署前人工生成真实 `.env.production`。
- 使用长随机密钥。
- 执行 Compose 渲染检查。

### E3. HTTPS 风险

风险：

- TLS 证书路径错误会导致 nginx 启动失败。
- 如 Cookie Secure 依赖 HTTPS，未启用 HTTPS 会影响登录安全。

处理：

- 部署前验证证书路径。
- 先以 HTTPS 完成验收。

### E4. 数据库风险

风险：

- 首次生产迁移失败可能导致服务不可用。
- 误用 postgres 管理账户作为应用运行账户会扩大权限面。

处理：

- 迁移前备份。
- backend 使用低权限 `tiantong_app`。
- migration 失败立即停止上线。

### E5. 容器风险

风险：

- backend / worker / nginx 构建失败或启动失败。
- worker 反复重启可能影响任务执行链路。

处理：

- build 失败不执行 migration。
- up 失败先看日志再决定回滚。
- worker 不稳定不得开放正式使用。

### E6. 权限风险

风险：

- owner/admin 登录失败会阻塞验收。
- viewer 越权会阻塞上线。

处理：

- 上线后必须验证登录和权限。
- 不允许通过手工改权限绕过验收。

## F. 回滚方案

### F1. 回滚触发条件

出现以下任一情况，应停止上线并回滚：

- `/api/health` 非 200。
- `/api/ready` 非 200。
- backend / worker / nginx 任一核心服务无法稳定运行。
- 登录失败且无法在部署窗口内修复。
- viewer 越权。
- 日志出现持续 `500`。
- migration 失败。
- 发现敏感信息泄露。
- 发现 5432 / 6379 / 8000 暴露公网。

### F2. Git 回滚

前置：

- 记录部署前稳定 commit。
- 记录本次部署 commit。

命令模板：

```bash
cd /data/apps/tiantong-ai-cloud
git reset --hard <previous_stable_commit>
docker compose --env-file .env.production -f docker-compose.prod.yml build backend worker nginx
docker compose --env-file .env.production -f docker-compose.prod.yml up -d --force-recreate backend worker nginx
```

### F3. 数据库回滚

原则：

- 不自动降级 migration。
- 不自动恢复数据库。
- 必须由老板确认备份文件和恢复目标。

恢复模板：

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml exec -T postgres \
  psql -U "$POSTGRES_ADMIN_USER" "$POSTGRES_DB" \
  < /data/backups/tiantong-ai-cloud/<backup_file>.sql
```

### F4. Docker 回滚

如旧镜像仍可用：

```bash
docker images
docker compose --env-file .env.production -f docker-compose.prod.yml up -d --force-recreate
```

如旧镜像不可用：

- 使用 Git 回滚到稳定 commit。
- 重新 build backend / worker / nginx。
- 重启服务。

## G. 是否满足正式部署条件

当前结论：暂不满足直接正式部署条件，但满足进入正式部署前最后人工确认阶段。

已满足：

- 本地分支为 `main`。
- 当前最新 commit 已包含 Sprint29 生产配置基础。
- 生产 Docker 配置存在。
- Nginx 生产配置存在。
- `.env.production.example` 存在，且只使用占位符。
- 生产部署文档链路已基本完整。

未满足：

- Sprint29.7 到 Sprint29.11 文档尚未提交。
- Sprint29 文档尚未推送 GitHub main。
- 生产服务器真实 `.env.production` 尚未人工确认。
- 生产数据库备份尚未执行。
- TLS 证书尚未在服务器侧确认。
- 低权限数据库用户尚未在服务器侧确认。
- Redis 强密码尚未在服务器侧确认。

正式部署前必须完成：

1. 老板确认提交 Sprint29.7 到 Sprint29.11 文档。
2. 继续排除 `docs/SSH_FIX_REPORT.md`。
3. 推送 GitHub main。
4. 在服务器人工准备 `.env.production`。
5. 完成数据库备份。
6. 确认 TLS、Redis、PostgreSQL、阿里云安全组。
7. 再按 `docs/SPRINT29_10_PRODUCTION_DEPLOY_EXECUTION.md` 执行第一次正式部署。
