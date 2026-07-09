# Sprint29.12 天统AI V1 第一次正式部署计划

目标：在执行第一次正式生产部署前，明确将执行的命令、风险、回滚方法和老板确认点。本文档只生成部署计划，不代表已经连接阿里云或执行部署。

执行边界：

- 不执行 SSH
- 不连接阿里云
- 不执行 `docker compose up`
- 不修改代码
- 不修改数据库
- 不执行 `git push`

## 1. 部署前检查计划

### 1.1 阿里云连接方式

计划确认项：

- 连接方式：阿里云 Workbench / SSH Key / 已审批堡垒机方式。
- 目标目录：`/data/apps/tiantong-ai-cloud`。
- 登录用户：必须具备 Docker 操作权限。
- 部署窗口：必须由老板确认。
- 连接来源：仅允许可信 IP 或阿里云受控入口。

将执行的检查命令：

```bash
whoami
hostname
pwd
date
timedatectl
ls -la /data/apps/tiantong-ai-cloud
```

成功标准：

- 登录到正确 ECS。
- 项目目录存在。
- 系统时间正常。
- 当前用户权限清楚。

风险：

- 登录到错误服务器。
- 目录不存在或不是正式项目目录。
- 部署用户无 Docker 权限。

停止条件：

- 服务器身份无法确认。
- 部署目录不存在。
- 登录用户权限不明确。

### 1.2 当前服务器环境

将执行的检查命令：

```bash
uname -a
cat /etc/os-release
df -h
free -h
uptime
```

成功标准：

- 操作系统版本明确。
- 磁盘空间满足部署要求。
- 内存状态正常。
- 系统负载可接受。

风险：

- 磁盘空间不足导致 Docker build 失败。
- 内存不足导致容器重启。

停止条件：

- 可用磁盘低于 10GB。
- 系统负载异常或已有业务不稳定。

### 1.3 Docker 版本

将执行的检查命令：

```bash
docker --version
docker compose version
docker ps
docker system df
```

成功标准：

- Docker daemon 正常。
- Docker Compose v2 可用。
- 当前容器状态可查看。

风险：

- Docker 版本过旧。
- Docker daemon 未运行。
- 镜像或 volume 占用过多磁盘。

停止条件：

- Docker 不可用。
- Docker Compose 不可用。

### 1.4 磁盘空间

将执行的检查命令：

```bash
df -h
docker system df
du -sh /data/apps/tiantong-ai-cloud 2>/dev/null || true
du -sh /data/backups/tiantong-ai-cloud 2>/dev/null || true
```

成功标准：

- 系统盘和 Docker 数据目录有足够空间。
- 备份目录存在或可以创建。

风险：

- 构建镜像时磁盘耗尽。
- 数据库备份失败。

停止条件：

- 备份目录无法创建。
- 磁盘空间不足以同时保存备份和新镜像。

### 1.5 网络端口

生产端口策略：

- 允许公网访问：`80`、`443`
- 禁止公网访问：`5432`、`6379`、`8000`
- SSH / Workbench 入口仅允许可信来源。

将执行的检查命令：

```bash
ss -tulpn
docker compose --env-file .env.production -f docker-compose.prod.yml ps
```

成功标准：

- nginx 作为唯一公网 Web 入口。
- backend 仅容器网络内部访问。
- PostgreSQL / Redis 不暴露公网端口。

风险：

- 数据库或 Redis 被错误映射到公网。
- backend 8000 直接对公网开放。

停止条件：

- 发现 `5432`、`6379`、`8000` 对公网开放。

### 1.6 SSL 状态

将执行的检查命令：

```bash
ls -l /data/apps/tiantong-ai-cloud/certs/fullchain.pem
ls -l /data/apps/tiantong-ai-cloud/certs/privkey.pem
openssl x509 -in /data/apps/tiantong-ai-cloud/certs/fullchain.pem -noout -dates
```

成功标准：

- 证书文件存在。
- 私钥文件权限受限。
- 证书未过期。
- `TLS_CERT_PATH` 和 `TLS_KEY_PATH` 与 `.env.production` 一致。

风险：

- nginx 因证书路径错误无法启动。
- HTTPS 不可用导致登录 Cookie 安全策略无法落地。

停止条件：

- 证书缺失。
- 私钥缺失。
- 证书过期。

### 1.7 数据库备份方案

备份目录：

- `/data/backups/tiantong-ai-cloud`

将执行的备份命令：

```bash
cd /data/apps/tiantong-ai-cloud
mkdir -p /data/backups/tiantong-ai-cloud
docker compose --env-file .env.production -f docker-compose.prod.yml exec -T postgres \
  pg_dump -U "$POSTGRES_ADMIN_USER" "$POSTGRES_DB" \
  > /data/backups/tiantong-ai-cloud/backup_$(date +%Y%m%d_%H%M%S).sql
ls -lh /data/backups/tiantong-ai-cloud
```

成功标准：

- 备份文件生成。
- 备份文件大小非 0。
- 备份文件路径记录到部署日志。

风险：

- 数据库容器未运行导致备份失败。
- 用户权限不足导致备份失败。
- 磁盘空间不足导致备份不完整。

停止条件：

- 备份失败。
- 备份文件为空。
- 无法确认备份文件。

## 2. 正式部署命令计划

### 2.1 GitHub main 同步

将执行：

```bash
cd /data/apps/tiantong-ai-cloud
git remote -v
git status --short
git rev-parse HEAD
git log -1 --oneline
git fetch origin main
git reset --hard origin/main
git rev-parse HEAD
git log -1 --oneline
```

成功标准：

- 服务器 HEAD 等于老板确认的 GitHub main commit。
- 无未预期本地修改。

风险：

- `git reset --hard` 覆盖服务器本地未提交文件。

控制措施：

- reset 前必须记录 `git status --short` 和 `git rev-parse HEAD`。
- 如存在生产热修复，停止部署。

### 2.2 生产环境变量检查

将执行：

```bash
cd /data/apps/tiantong-ai-cloud
ls -l .env.production
grep -n '<.*>' .env.production && echo "ERROR: placeholder exists" || echo "OK: no placeholder"
chmod 600 .env.production
PRODUCTION_ENV_FILE=.env.production docker compose --env-file .env.production -f docker-compose.prod.yml config
```

成功标准：

- `.env.production` 存在。
- 无占位符。
- Compose config 渲染成功。

风险：

- 密钥缺失导致服务启动失败。
- TLS 路径错误导致 nginx 启动失败。

停止条件：

- `.env.production` 不存在。
- 存在占位符。
- Compose config 失败。

### 2.3 Docker build

将执行：

```bash
cd /data/apps/tiantong-ai-cloud
docker compose --env-file .env.production -f docker-compose.prod.yml build backend worker nginx
```

必要时才执行完全重建：

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml build --no-cache backend worker nginx
```

成功标准：

- backend 构建成功。
- worker 构建成功。
- nginx 构建成功。

风险：

- pip 下载失败。
- Docker 缓存或磁盘不足。
- nginx 配置编译失败。

停止条件：

- 任一镜像构建失败。
- 构建失败时不得继续 migration。

### 2.4 数据库迁移

将执行：

```bash
cd /data/apps/tiantong-ai-cloud
docker compose --env-file .env.production -f docker-compose.prod.yml run --rm backend alembic current
docker compose --env-file .env.production -f docker-compose.prod.yml run --rm backend alembic heads
docker compose --env-file .env.production -f docker-compose.prod.yml run --rm backend alembic upgrade head
docker compose --env-file .env.production -f docker-compose.prod.yml run --rm backend alembic current
```

成功标准：

- migration 升级到 head。
- 无 Alembic 报错。

风险：

- migration 与当前数据库不兼容。
- 数据库权限不足。

停止条件：

- 备份未完成。
- migration 失败。
- backend 无法连接数据库。

### 2.5 服务启动

将执行：

```bash
cd /data/apps/tiantong-ai-cloud
docker compose --env-file .env.production -f docker-compose.prod.yml up -d
docker compose --env-file .env.production -f docker-compose.prod.yml ps
```

如只需重启业务服务：

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml up -d --force-recreate backend worker nginx
```

成功标准：

- backend healthy。
- worker running。
- postgres healthy。
- redis healthy。
- nginx healthy 或 running。

风险：

- nginx TLS 配置错误。
- backend healthcheck 失败。
- worker 反复重启。

停止条件：

- backend 不健康。
- postgres / redis 不健康。
- nginx 无法启动。

### 2.6 健康检查

将执行：

```bash
curl -i http://127.0.0.1/api/health
curl -i http://127.0.0.1/api/ready
curl -k -i https://127.0.0.1/api/health
curl -k -i https://127.0.0.1/api/ready
```

成功标准：

- `/api/health` 返回 200。
- `/api/ready` 返回 200。
- HTTP / HTTPS 链路符合预期。

风险：

- API 200 但页面异常。
- ready 失败暴露数据库或 Redis 问题。

停止条件：

- health 或 ready 非 200。

### 2.7 页面与 API 验收

将执行：

```bash
curl -I https://<domain>/
curl -I https://<domain>/index.html
curl -I https://<domain>/task-center.html
curl -I https://<domain>/ai-employees.html
curl -i https://<domain>/api/ceo-dashboard/daily-operations
curl -i https://<domain>/api/approval-center/pending
curl -i https://<domain>/api/ai-employees/runtime-status
```

成功标准：

- 页面返回 200。
- 未登录 API 返回 401。
- 登录后 owner/admin 权限正常。
- viewer 不能越权。

风险：

- 静态页面 200 但 API 权限异常。
- 登录 Cookie / HTTPS 策略不匹配。

停止条件：

- 登录失败。
- 权限越权。
- 关键页面不可访问。

### 2.8 日志检查

将执行：

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml logs --tail=160 backend
docker compose --env-file .env.production -f docker-compose.prod.yml logs --tail=160 worker
docker compose --env-file .env.production -f docker-compose.prod.yml logs --tail=160 nginx
```

成功标准：

- 无 `ImportError`。
- 无 `ModuleNotFoundError`。
- 无持续 `500`。
- 无敏感信息输出。
- worker 不持续重启。

停止条件：

- 日志出现阻断错误。
- 日志出现密码、token、secret、API Key。

## 3. 风险清单

### 高风险

1. 未备份数据库直接执行 migration。
2. `.env.production` 缺失或包含占位符。
3. PostgreSQL / Redis / backend 暴露公网。
4. TLS 证书路径错误导致 nginx 启动失败。
5. owner/admin 登录失败导致无法验收。
6. viewer 权限越权。

### 中风险

1. Docker build 下载依赖失败。
2. worker 运行但无法消费队列。
3. ready 依赖数据库或 Redis 导致启动延迟。
4. Cookie Secure 与 HTTPS 配置不一致。

### 低风险

1. 部署文档未同步到生产目录。
2. 非关键页面样式异常。
3. 日志量偏大但未阻断服务。

## 4. 回滚方法

### 4.1 Git 回滚

触发条件：

- 新版本服务无法启动。
- 核心 API 验证失败。
- 权限系统异常。

命令模板：

```bash
cd /data/apps/tiantong-ai-cloud
git reset --hard <previous_stable_commit>
docker compose --env-file .env.production -f docker-compose.prod.yml build backend worker nginx
docker compose --env-file .env.production -f docker-compose.prod.yml up -d --force-recreate backend worker nginx
```

### 4.2 Docker 回滚

触发条件：

- Git 版本正确但新镜像异常。
- 旧镜像仍保留且可用。

命令模板：

```bash
docker images
docker compose --env-file .env.production -f docker-compose.prod.yml up -d --force-recreate
```

说明：

- 如果没有明确镜像 tag，优先使用 Git 回滚重新 build。

### 4.3 数据库恢复

触发条件：

- migration 已造成不可兼容状态。
- 老板确认需要恢复备份。

命令模板：

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml exec -T postgres \
  psql -U "$POSTGRES_ADMIN_USER" "$POSTGRES_DB" \
  < /data/backups/tiantong-ai-cloud/<backup_file>.sql
```

安全要求：

- 不自动恢复数据库。
- 恢复前必须确认备份文件、目标库和影响范围。
- 恢复后重新运行 health / ready / 登录验证。

## 5. 部署失败处理

### 5.1 Git 同步失败

处理：

- 停止部署。
- 检查 remote、网络和 GitHub 权限。
- 不执行 build、migration、服务重启。

### 5.2 环境变量失败

处理：

- 停止部署。
- 修正 `.env.production`。
- 不使用 `.env.production.example` 直接部署。

### 5.3 Docker build 失败

处理：

- 保持旧服务运行。
- 保存 build 日志。
- 不执行 migration。

### 5.4 Migration 失败

处理：

- 停止上线。
- 保存 Alembic 输出。
- 检查数据库备份。
- 不启动新版本服务。

### 5.5 服务启动失败

处理：

- 查看 backend / worker / nginx 日志。
- 10 分钟内不能恢复则回滚。

### 5.6 健康检查失败

处理：

- 停止开放公网验收。
- 检查数据库、Redis、backend、worker。
- 必要时回滚。

### 5.7 权限验收失败

处理：

- 停止上线。
- 检查 JWT、Cookie、用户角色和生产环境变量。
- 不允许通过临时放宽权限上线。

## 6. 老板确认点

执行前必须确认：

```text
[ ] 确认目标 ECS 和部署窗口
[ ] 确认连接方式
[ ] 确认 GitHub main 已包含部署目标 commit
[ ] 确认 .env.production 已人工准备且无占位符
[ ] 确认数据库备份路径
[ ] 确认 TLS 证书路径
[ ] 确认 Redis 密码
[ ] 确认 PostgreSQL 低权限运行用户
[ ] 确认阿里云安全组未开放 5432 / 6379 / 8000
[ ] 确认回滚负责人
[ ] 确认失败时立即停止上线
```

## 7. 当前是否可以执行

当前结论：尚不可立即执行。

原因：

- 本地 Sprint29.7 到 Sprint29.12 部署文档尚未提交。
- 部署文档尚未推送 GitHub main。
- 阿里云服务器 `.env.production`、TLS、数据库备份、Redis 密码、PostgreSQL 低权限用户尚未在本次会话中确认。

建议下一步：

1. 老板确认是否提交 Sprint29.7 到 Sprint29.12 文档。
2. 排除 `docs/SSH_FIX_REPORT.md`。
3. 推送 GitHub main。
4. 老板确认目标 commit。
5. 再按本文档进入首次正式部署执行。
