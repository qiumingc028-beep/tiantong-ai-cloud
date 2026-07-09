# Sprint29.10 天统AI V1 第一次正式部署执行方案

目标：为天统AI云中台 V1 第一次阿里云正式部署提供可执行步骤。本文档只定义执行方案，不代表已经执行部署。

执行边界：

- 不连接阿里云
- 不执行 Docker 部署
- 不修改业务代码
- 不执行 `git push`
- 不写入真实密钥

## A. 阿里云部署前确认

### A1. ECS 环境

人工确认项：

- 目标 ECS 已确认。
- 部署目录为 `/data/apps/tiantong-ai-cloud`。
- 登录方式已确认：阿里云 Workbench / SSH Key / 其他已审批方式。
- 部署用户具备 Docker 操作权限。
- 部署窗口允许短暂服务重启。
- 服务器时间和时区正常。
- 磁盘可用空间不少于 10GB。

检查命令：

```bash
whoami
hostname
date
timedatectl
pwd
df -h
ls -la /data/apps/tiantong-ai-cloud
```

成功标准：

- 登录到正确服务器。
- 项目目录存在。
- 磁盘空间充足。
- 系统时间正常。

### A2. Docker 环境

人工确认项：

- Docker daemon 正常。
- Docker Compose v2 可用。
- 当前容器状态可查看。
- 旧服务可回滚。

检查命令：

```bash
docker --version
docker compose version
docker ps
docker system df
```

成功标准：

- Docker 和 Docker Compose 均正常返回版本。
- 可以查看当前容器状态。

### A3. 网络端口

生产端口要求：

- 允许公网访问：`80`、`443`
- 不允许公网访问：`5432`、`6379`、`8000`
- SSH / Workbench 登录端口只允许可信来源访问。

检查命令：

```bash
ss -tulpn
```

成功标准：

- nginx 负责公网入口。
- PostgreSQL / Redis / backend 不直接暴露公网。

### A4. 域名

人工确认项：

- 生产域名已解析到目标 ECS。
- DNS 记录生效。
- 如暂未绑定域名，只允许内部验收，不建议对外正式发布。

检查命令：

```bash
dig <domain>
curl -I http://<domain>
```

成功标准：

- 域名解析到目标服务器。
- HTTP 可进入 nginx。

### A5. SSL 证书

人工确认项：

- TLS 证书和私钥已准备。
- 证书路径与 `nginx/production.conf` 一致。
- 私钥文件权限受限。
- 证书未过期。

检查命令：

```bash
ls -l /data/apps/tiantong-ai-cloud/certs/fullchain.pem
ls -l /data/apps/tiantong-ai-cloud/certs/privkey.pem
openssl x509 -in /data/apps/tiantong-ai-cloud/certs/fullchain.pem -noout -dates
```

成功标准：

- 证书和私钥文件存在。
- 证书有效期正常。
- 私钥未被公开读取。

## B. 部署步骤

### B1. Git 版本确认

目的：确认服务器部署的是老板审批后的 GitHub main 版本。

执行命令：

```bash
cd /data/apps/tiantong-ai-cloud
git remote -v
git status --short
git rev-parse HEAD
git log -1 --oneline
```

成功标准：

- remote 指向正确 GitHub 仓库。
- 本地无未预期修改。
- 当前 HEAD 可记录。

停止条件：

- 发现未记录的生产热修复。
- remote 指向错误仓库。
- 当前目录不是项目目录。

### B2. 拉取代码

执行命令：

```bash
cd /data/apps/tiantong-ai-cloud
git fetch origin main
git reset --hard origin/main
git rev-parse HEAD
git log -1 --oneline
```

成功标准：

- 服务器 HEAD 与 GitHub main 一致。
- HEAD 为老板确认的部署 commit。

风险：

- `git reset --hard` 会覆盖服务器本地未提交修改。执行前必须确认服务器无未记录业务改动。

### B3. 环境变量配置

生产文件：

- `.env.production`

要求：

- 不提交 Git。
- 权限建议为 `600`。
- 不允许存在 `<PLACEHOLDER>`。
- 必须包含数据库、Redis、JWT、运行环境等必要变量。

检查命令：

```bash
cd /data/apps/tiantong-ai-cloud
ls -l .env.production
grep -n '<.*>' .env.production && echo "ERROR: placeholder exists" || echo "OK: no placeholder"
chmod 600 .env.production
```

Compose 渲染检查：

```bash
PRODUCTION_ENV_FILE=.env.production \
docker compose --env-file .env.production -f docker-compose.prod.yml config
```

成功标准：

- `.env.production` 存在。
- 无占位符。
- Compose 配置可以渲染。

停止条件：

- 缺少 `.env.production`。
- 存在占位符。
- 生产密钥来源不明。

### B4. Docker build

执行命令：

```bash
cd /data/apps/tiantong-ai-cloud
docker compose --env-file .env.production -f docker-compose.prod.yml build backend worker nginx
```

如需完全重建：

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml build --no-cache backend worker nginx
```

成功标准：

- backend 镜像构建成功。
- worker 镜像构建成功。
- nginx 镜像构建成功。

失败处理：

- 停止上线。
- 保持旧容器运行。
- 记录失败日志。
- 不执行数据库迁移和服务重启。

### B5. 数据库迁移

迁移前必须备份。

备份命令：

```bash
cd /data/apps/tiantong-ai-cloud
mkdir -p /data/backups/tiantong-ai-cloud
docker compose --env-file .env.production -f docker-compose.prod.yml exec -T postgres \
  pg_dump -U "$POSTGRES_ADMIN_USER" "$POSTGRES_DB" \
  > /data/backups/tiantong-ai-cloud/backup_$(date +%Y%m%d_%H%M%S).sql
```

迁移命令：

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml run --rm backend alembic upgrade head
docker compose --env-file .env.production -f docker-compose.prod.yml run --rm backend alembic current
```

成功标准：

- 数据库备份文件生成。
- Alembic 升级到 head。
- 无 migration error。

停止条件：

- 备份失败。
- migration 失败。
- 当前数据库版本异常。

### B6. 服务启动

执行命令：

```bash
cd /data/apps/tiantong-ai-cloud
docker compose --env-file .env.production -f docker-compose.prod.yml up -d
```

如需强制重建业务服务：

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml up -d --force-recreate backend worker nginx
```

成功标准：

- backend 运行。
- worker 运行。
- nginx 运行。
- postgres healthy。
- redis healthy。

检查命令：

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml ps
```

### B7. 健康检查

执行命令：

```bash
curl -i http://127.0.0.1/api/health
curl -i http://127.0.0.1/api/ready
curl -k -i https://127.0.0.1/api/health
curl -k -i https://127.0.0.1/api/ready
```

成功标准：

- `/api/health` 返回 200。
- `/api/ready` 返回 200。
- HTTPS 链路可访问。

失败处理：

- 查看 backend / nginx / worker 日志。
- 不开放公网验收。
- 必要时回滚到上一版本。

## C. 上线验证

### C1. API 验证

检查：

```bash
curl -i https://<domain>/api/health
curl -i https://<domain>/api/ready
```

成功标准：

- 均返回 200。
- 响应不泄露敏感配置。

### C2. 登录系统

检查项：

- 未登录访问受保护 API 返回 401。
- owner / admin 登录成功。
- viewer 无越权能力。
- 登录响应不返回 password / password_hash / token 明文敏感信息。

建议验证：

```bash
curl -i https://<domain>/api/ceo-dashboard/daily-operations
```

成功标准：

- 未登录返回 401。
- 登录后按权限返回数据。

### C3. 老板驾驶舱

页面：

- `/`
- `/index.html`

检查项：

- 页面 200。
- 今日运营摘要正常。
- 系统健康状态正常。
- 待老板确认事项正常。
- 无白屏。

### C4. AI员工中心

页面：

- `/ai-employees.html`

接口：

- `/api/ai-employees/runtime-status`

检查项：

- 员工列表正常。
- 员工运行状态正常。
- 不显示密钥或敏感配置。

### C5. Task Center

页面：

- `/task-center.html`

检查项：

- 任务列表可访问。
- 未登录接口返回 401。
- viewer 不可越权修改任务。
- 不触发自动部署或危险执行。

### C6. 日志检查

检查命令：

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml logs --tail=120 backend
docker compose --env-file .env.production -f docker-compose.prod.yml logs --tail=120 worker
docker compose --env-file .env.production -f docker-compose.prod.yml logs --tail=120 nginx
```

成功标准：

- 无 `ImportError`。
- 无 `ModuleNotFoundError`。
- 无持续 `500`。
- 无敏感信息打印。
- worker 不持续重启。

## D. 回滚方案

### D1. Git 回滚

前置要求：

- 记录部署前 commit。
- 记录部署后 commit。

回滚命令：

```bash
cd /data/apps/tiantong-ai-cloud
git reset --hard <previous_stable_commit>
docker compose --env-file .env.production -f docker-compose.prod.yml build backend worker nginx
docker compose --env-file .env.production -f docker-compose.prod.yml up -d --force-recreate backend worker nginx
```

### D2. Docker 回滚

如果本地仍保留旧镜像：

```bash
docker images
docker compose --env-file .env.production -f docker-compose.prod.yml up -d --force-recreate
```

要求：

- 优先使用明确镜像 tag。
- 如果没有 tag，按 Git 回滚重新 build。

### D3. 数据库保护

原则：

- 生产回滚不自动执行数据库降级。
- 如 migration 已写入新结构，先评估兼容性。
- 必须使用部署前备份恢复时，由人工确认。

恢复示例：

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml exec -T postgres \
  psql -U "$POSTGRES_ADMIN_USER" "$POSTGRES_DB" \
  < /data/backups/tiantong-ai-cloud/<backup_file>.sql
```

执行恢复前必须二次确认备份文件和目标数据库。

## E. 部署失败处理方案

### E1. Git 拉取失败

处理：

- 停止部署。
- 检查网络和 GitHub 权限。
- 不继续 build / migration。

### E2. 环境变量失败

处理：

- 停止部署。
- 修复 `.env.production`。
- 确认无占位符和无权限问题后重试。

### E3. Docker build 失败

处理：

- 保持旧容器运行。
- 保存 build 日志。
- 不执行 migration。
- 不重启服务。

### E4. Migration 失败

处理：

- 停止上线。
- 保存 Alembic 日志。
- 检查数据库备份。
- 不启动新版本业务服务。

### E5. 服务启动失败

处理：

- 查看容器日志。
- 如果 backend / worker / nginx 无法稳定运行，回滚 Git 和镜像。
- 不开放正式访问。

### E6. 健康检查失败

处理：

- 停止上线。
- 检查 `/api/health`、`/api/ready`、数据库、Redis、worker。
- 如果 10 分钟内无法修复，执行回滚。

### E7. 权限验证失败

处理：

- 停止上线。
- 检查 JWT、Cookie、用户角色、生产 `.env.production`。
- 不绕过权限上线。

## F. 最终上线判定

允许上线条件：

- GitHub main commit 已由老板确认。
- `.env.production` 已人工准备且无占位符。
- PostgreSQL 已备份。
- Docker build 成功。
- Alembic 当前版本为 head。
- backend / worker / nginx / postgres / redis 状态正常。
- `/api/health` 返回 200。
- `/api/ready` 返回 200。
- 登录、老板驾驶舱、AI员工中心、Task Center 验证通过。
- 日志无阻断错误。
- 无敏感信息泄露。

禁止上线条件：

- 数据库未备份。
- 生产环境变量存在占位符。
- backend / worker / nginx 任一核心服务不稳定。
- `/api/health` 或 `/api/ready` 失败。
- 权限验证失败。
- 发现真实密钥泄露。
- 发现 5432 / 6379 / 8000 暴露公网。

结论：本文档仅为 Sprint29.10 第一次正式部署执行方案。执行前必须由老板确认部署窗口、目标 commit、生产环境变量、数据库备份和回滚负责人。
