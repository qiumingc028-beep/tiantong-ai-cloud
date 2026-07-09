# Sprint29.6 阿里云部署前最终检查表

目标：在执行阿里云正式部署前，把每一步命令、风险、成功判断标准和回滚触发条件固定下来。

执行边界：

- 本文档仅用于部署前人工确认
- 当前不连接服务器
- 当前不执行生产操作
- 当前不修改业务代码
- 当前不修改数据库结构

## 1. 最终检查总表

| 步骤 | 执行命令 | 主要风险 | 成功判断标准 | 回滚 / 中止触发条件 |
|---|---|---|---|---|
| 1. ECS 环境检查 | `whoami`; `hostname`; `pwd`; `date`; `timedatectl`; `ls -la /data/apps/tiantong-ai-cloud` | 登录到错误服务器或错误目录 | 位于 `/data/apps/tiantong-ai-cloud`，时间正常，目录存在 | 目录不存在、服务器身份不符、时间异常 |
| 2. Docker 检查 | `docker --version`; `docker ps` | Docker daemon 不可用 | Docker 可执行，daemon 正常 | Docker 不可用或权限不足 |
| 3. Compose 检查 | `docker compose version` | Compose v1/v2 不一致 | Docker Compose v2 可用 | `docker compose` 不存在 |
| 4. 磁盘检查 | `df -h`; `docker system df`; `du -sh /data/apps/tiantong-ai-cloud` | 磁盘不足导致 build 或数据库备份失败 | 可用空间不少于 10GB | 空间不足或无法写入备份 |
| 5. 端口检查 | `ss -tulpn` | 端口冲突或误暴露数据库 | 80/443 可用，5432/6379/8000 不公网暴露 | 80/443 被异常占用，5432/6379/8000 暴露公网 |
| 6. 域名检查 | `dig <domain>`; `curl -I http://<domain>` | DNS 未生效 | 域名解析到目标入口 | DNS 指向错误或不可达 |
| 7. 证书检查 | `ls -l "$TLS_CERT_PATH" "$TLS_KEY_PATH"`; `openssl x509 -in "$TLS_CERT_PATH" -noout -dates -subject` | 证书缺失、过期或路径错误 | 证书和私钥存在且未过期 | 文件不存在、过期、权限错误 |
| 8. 记录当前版本 | `git rev-parse HEAD`; `git log -1 --oneline`; `docker compose --env-file .env.production -f docker-compose.prod.yml ps` | 无法回溯旧版本 | 已记录 commit 和服务状态 | 无法确认当前版本 |
| 9. 拉取 main | `git fetch origin main`; `git reset --hard origin/main`; `git rev-parse HEAD`; `git log -1 --oneline` | 拉到未审批版本 | HEAD 等于老板确认 commit | HEAD 不符、工作区异常 |
| 10. 环境变量检查 | `ls -l .env.production`; `grep -n '<.*>' .env.production`; `chmod 600 .env.production` | 缺少密钥、占位符未替换、权限过宽 | 文件存在、权限 600、无占位符 | 文件缺失、有占位符、权限异常 |
| 11. Compose 渲染 | `PRODUCTION_ENV_FILE=.env.production docker compose --env-file .env.production -f docker-compose.prod.yml config` | 环境变量缺失或端口配置错误 | config 成功，端口和挂载符合预期 | config 失败或发现错误配置 |
| 12. 数据库备份 | `mkdir -p /data/backups/tiantong-ai-cloud`; `docker compose --env-file .env.production -f docker-compose.prod.yml exec -T postgres pg_dump -U "$POSTGRES_ADMIN_USER" "$POSTGRES_DB" > /data/backups/tiantong-ai-cloud/backup_$(date +%Y%m%d_%H%M%S).sql` | 无备份导致不可恢复 | 备份文件生成且大小合理 | 备份失败或备份文件为空 |
| 13. PostgreSQL 权限确认 | `docker compose --env-file .env.production -f docker-compose.prod.yml exec -T postgres psql -U "$POSTGRES_ADMIN_USER" -d "$POSTGRES_DB" -c '\du'` | 应用用户权限过高或不存在 | `tiantong_app` 存在且非超级用户 | 用户不存在或仍是 Superuser |
| 14. Docker build | `docker compose --env-file .env.production -f docker-compose.prod.yml build backend worker nginx` | 构建失败或依赖下载失败 | 三个镜像构建成功 | 任一镜像构建失败 |
| 15. 数据库迁移 | `docker compose --env-file .env.production -f docker-compose.prod.yml run --rm backend alembic upgrade head`; `docker compose --env-file .env.production -f docker-compose.prod.yml run --rm backend alembic current` | migration 失败或破坏数据 | upgrade 成功，current 为 head | migration 失败或出现数据错误 |
| 16. 启动服务 | `docker compose --env-file .env.production -f docker-compose.prod.yml up -d` | 服务启动失败 | backend/postgres/redis/nginx healthy，worker running | 服务非 healthy 或反复重启 |
| 17. Health 检查 | `curl -i http://127.0.0.1/api/health`; `curl -i http://127.0.0.1/api/ready`; `curl -k -i https://127.0.0.1/api/health`; `curl -k -i https://127.0.0.1/api/ready` | 后端或依赖不可用 | health/ready 返回 200 | 任一 health/ready 非 200 |
| 18. 域名 Health | `curl -i https://<domain>/api/health`; `curl -i https://<domain>/api/ready` | TLS / Nginx / DNS 问题 | 域名 health/ready 返回 200 | HTTPS 不通或非 200 |
| 19. 页面检查 | `curl -I https://<domain>/`; `curl -I https://<domain>/index.html`; `curl -I https://<domain>/dashboard/overview.html`; `curl -I https://<domain>/task-center.html`; `curl -I https://<domain>/ai-employees.html` | 前端白屏或静态文件缺失 | 页面返回 200，浏览器不白屏 | 页面 404/500 或白屏 |
| 20. API 权限检查 | `curl -i https://<domain>/api/ceo-dashboard/daily-summary`; `curl -i https://<domain>/api/task-center/tasks`; `curl -i https://<domain>/api/ai-employees/runtime-status` | 权限绕过 | 未登录返回 401 | 未登录返回 200 或 500 |
| 21. 登录权限检查 | 浏览器登录 owner/boss/admin/viewer | 登录失败或越权 | 管理员可访问，viewer 被限制 | 管理员不可登录或 viewer 越权 |
| 22. 日志检查 | `docker compose --env-file .env.production -f docker-compose.prod.yml logs --tail=200 backend`; `docker compose --env-file .env.production -f docker-compose.prod.yml logs --tail=200 worker`; `docker compose --env-file .env.production -f docker-compose.prod.yml logs --tail=200 nginx` | 运行错误或密钥泄露 | 无 Traceback/持续 500/secret 泄露 | 有持续错误或敏感信息泄露 |

## 2. 分步执行细则

### 2.1 ECS 环境

命令：

```bash
whoami
hostname
pwd
date
timedatectl
ls -la /data/apps/tiantong-ai-cloud
```

风险：

- 登录到错误 ECS。
- 当前目录不是部署目录。
- 系统时间错误导致 TLS / JWT / 日志异常。

成功标准：

- 服务器身份正确。
- `/data/apps/tiantong-ai-cloud` 存在。
- 系统时间正常。

中止条件：

- 服务器身份不明。
- 部署目录不存在。
- 时间严重异常。

### 2.2 Docker 与 Compose

命令：

```bash
docker --version
docker ps
docker compose version
```

风险：

- Docker 不可用。
- 当前用户没有 Docker 权限。
- Compose 版本不符合预期。

成功标准：

- `docker ps` 可执行。
- `docker compose version` 可执行。

中止条件：

- Docker daemon 不可用。
- Compose 不可用。

### 2.3 磁盘与端口

命令：

```bash
df -h
docker system df
du -sh /data/apps/tiantong-ai-cloud 2>/dev/null || true
ss -tulpn
```

风险：

- 磁盘不足导致镜像构建失败。
- 数据库备份失败。
- 端口冲突。
- 数据库或 Redis 暴露公网。

成功标准：

- 可用磁盘不少于 10GB。
- 80/443 可用于 Nginx。
- 5432/6379/8000 不对公网开放。

中止条件：

- 磁盘不足。
- 发现 5432/6379/8000 公网暴露。

### 2.4 域名与证书

命令：

```bash
dig <domain>
curl -I http://<domain>
ls -l "$TLS_CERT_PATH" "$TLS_KEY_PATH"
openssl x509 -in "$TLS_CERT_PATH" -noout -dates -subject
```

风险：

- DNS 指向错误。
- TLS 证书路径错误。
- 证书过期。
- 私钥权限不当。

成功标准：

- 域名解析正确。
- 证书存在且未过期。
- 证书路径与 `.env.production` 一致。

中止条件：

- 域名指向错误。
- 证书缺失或过期。

### 2.5 Git 同步

命令：

```bash
cd /data/apps/tiantong-ai-cloud
git rev-parse HEAD
git log -1 --oneline
git fetch origin main
git reset --hard origin/main
git rev-parse HEAD
git log -1 --oneline
```

风险：

- 拉取到未审批 commit。
- 覆盖服务器本地未记录修改。

成功标准：

- HEAD 等于老板确认的 GitHub main commit。
- 工作区无未预期修改。

中止条件：

- HEAD 与审批 commit 不一致。
- 发现服务器本地有未知业务修改。

### 2.6 生产环境变量

命令：

```bash
ls -l .env.production
grep -n '<.*>' .env.production && echo "ERROR: placeholder exists" || echo "OK: no placeholder"
chmod 600 .env.production
PRODUCTION_ENV_FILE=.env.production docker compose --env-file .env.production -f docker-compose.prod.yml config
```

风险：

- `.env.production` 缺失。
- 占位符未替换。
- 弱密钥。
- 文件权限过宽。

成功标准：

- `.env.production` 权限为 600。
- 无 `<...>` 占位符。
- compose config 成功。

中止条件：

- 有占位符。
- 缺少关键变量。
- config 失败。

### 2.7 数据库备份和权限

命令：

```bash
mkdir -p /data/backups/tiantong-ai-cloud
docker compose --env-file .env.production -f docker-compose.prod.yml exec -T postgres \
  pg_dump -U "$POSTGRES_ADMIN_USER" "$POSTGRES_DB" \
  > /data/backups/tiantong-ai-cloud/backup_$(date +%Y%m%d_%H%M%S).sql

docker compose --env-file .env.production -f docker-compose.prod.yml exec -T postgres \
  psql -U "$POSTGRES_ADMIN_USER" -d "$POSTGRES_DB" -c '\du'
```

风险：

- 备份失败。
- `tiantong_app` 不存在。
- `tiantong_app` 权限过高。

成功标准：

- 备份文件生成。
- `tiantong_app` 存在。
- `tiantong_app` 非超级用户。

中止条件：

- 无法完成备份。
- 低权限用户不存在或权限不符合要求。

### 2.8 构建、迁移、启动

命令：

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml build backend worker nginx
docker compose --env-file .env.production -f docker-compose.prod.yml run --rm backend alembic upgrade head
docker compose --env-file .env.production -f docker-compose.prod.yml run --rm backend alembic current
docker compose --env-file .env.production -f docker-compose.prod.yml up -d
docker compose --env-file .env.production -f docker-compose.prod.yml ps
```

风险：

- 构建失败。
- migration 失败。
- 服务启动失败。
- nginx 因证书路径失败。

成功标准：

- 镜像构建成功。
- migration 到 head。
- backend/postgres/redis/nginx healthy。
- worker running。

中止条件：

- 构建失败。
- migration 失败。
- 服务非 healthy。

### 2.9 健康、页面、API、日志

命令：

```bash
curl -i http://127.0.0.1/api/health
curl -i http://127.0.0.1/api/ready
curl -k -i https://127.0.0.1/api/health
curl -k -i https://127.0.0.1/api/ready
curl -i https://<domain>/api/health
curl -i https://<domain>/api/ready

curl -I https://<domain>/
curl -I https://<domain>/index.html
curl -I https://<domain>/dashboard/overview.html
curl -I https://<domain>/task-center.html
curl -I https://<domain>/ai-employees.html

curl -i https://<domain>/api/ceo-dashboard/daily-summary
curl -i https://<domain>/api/task-center/tasks
curl -i https://<domain>/api/ai-employees/runtime-status

docker compose --env-file .env.production -f docker-compose.prod.yml logs --tail=200 backend
docker compose --env-file .env.production -f docker-compose.prod.yml logs --tail=200 worker
docker compose --env-file .env.production -f docker-compose.prod.yml logs --tail=200 nginx
```

风险：

- health/ready 非 200。
- 页面白屏。
- 权限绕过。
- 日志泄露密钥。

成功标准：

- health/ready 200。
- 页面 200。
- 未登录 API 401。
- 日志无 Traceback、ImportError、持续 500、secret 泄露。

回滚触发：

- health/ready 非 200 且无法快速修复。
- 页面不可访问。
- 未登录接口返回 200。
- 日志出现敏感信息泄露。

## 3. 回滚触发条件

满足任一条件，必须暂停上线并进入回滚或修复流程：

1. Git HEAD 与审批 commit 不一致。
2. `.env.production` 有占位符或权限不是 600。
3. PostgreSQL 备份失败。
4. `tiantong_app` 不存在或权限过高。
5. Redis 密码和 `REDIS_URL` 不一致。
6. TLS 证书不存在或过期。
7. Docker build 失败。
8. Alembic migration 失败。
9. backend / postgres / redis / nginx 非 healthy。
10. worker 持续退出或重启。
11. `/api/health` 或 `/api/ready` 非 200。
12. 核心页面 404 / 500 / 白屏。
13. 未登录管理 API 返回 200。
14. 日志出现 password / token / secret / private key 泄露。
15. 发现数据库或 Redis 端口公网暴露。

## 4. 回滚命令索引

### 4.1 Git 回滚

```bash
git log --oneline -5
git reset --hard <previous_stable_commit>
docker compose --env-file .env.production -f docker-compose.prod.yml build backend worker nginx
docker compose --env-file .env.production -f docker-compose.prod.yml up -d --force-recreate backend worker nginx
```

### 4.2 停止业务层

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml stop backend worker
```

### 4.3 重启单个服务

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml up -d --force-recreate nginx
docker compose --env-file .env.production -f docker-compose.prod.yml up -d --force-recreate backend worker
docker compose --env-file .env.production -f docker-compose.prod.yml up -d --force-recreate redis backend worker
```

### 4.4 禁止操作

禁止在未获老板明确确认前执行：

```bash
docker volume rm
docker compose down -v
alembic downgrade
rm -rf /var/lib/postgresql/data
```

## 5. 最终人工确认

执行正式部署前必须确认：

```text
[ ] 已阅读 Sprint29.6 执行计划
[ ] 已阅读本最终检查表
[ ] 已确认目标 ECS
[ ] 已确认目标 Git commit
[ ] 已确认 .env.production
[ ] 已确认 PostgreSQL 备份
[ ] 已确认 PostgreSQL 低权限用户
[ ] 已确认 Redis 密码
[ ] 已确认 TLS 证书
[ ] 已确认阿里云安全组
[ ] 已确认 Cookie Secure 短期风险处理方案
[ ] 已确认回滚方案
```

## 6. 结论

本检查表完成后，不代表已经部署。

必须等待老板明确确认后，才能执行阿里云生产部署命令。
