# Sprint29.7 阿里云生产部署计划

目标：在老板确认后，将天统AI V1 生产化版本部署到阿里云 ECS。

当前状态：计划阶段，尚未执行部署。

禁止事项：

- 禁止自动修改代码
- 禁止自动删除数据
- 禁止自动执行危险命令
- 禁止跳过老板确认
- 禁止跳过数据库备份

## 1. 阿里云连接前检查

### 检查项

- 确认目标服务器 IP / 域名。
- 确认登录方式：
  - 阿里云 Workbench
  - SSH Key
  - 其他已审批方式
- 确认登录用户具备 Docker 权限。
- 确认部署目录：
  - `/data/apps/tiantong-ai-cloud`
- 确认当前部署窗口允许短暂服务重启。

### 计划命令

```bash
whoami
hostname
pwd
date
timedatectl
ls -la /data/apps/tiantong-ai-cloud
```

### 成功标准

- 登录到正确 ECS。
- 系统时间正常。
- 项目目录存在。
- 部署用户权限明确。

### 老板确认点

```text
[ ] 确认目标 ECS 正确
[ ] 确认当前可以进入部署窗口
[ ] 确认部署人员和登录方式
```

## 2. 当前服务器状态检查

### 检查项

- Docker 状态
- Docker Compose 状态
- 当前容器状态
- 磁盘空间
- 端口占用

### 计划命令

```bash
docker --version
docker compose version
docker ps
df -h
docker system df
ss -tulpn
```

### 成功标准

- Docker daemon 正常。
- Docker Compose v2 可用。
- 磁盘可用空间不少于 10GB。
- 80 / 443 可用于 Nginx。
- 5432 / 6379 / 8000 不对公网暴露。

### 老板确认点

```text
[ ] Docker 正常
[ ] 磁盘空间充足
[ ] 网络端口符合生产要求
```

## 3. GitHub 版本确认

### 检查项

- 当前服务器本地 commit。
- GitHub main 最新 commit。
- 是否为老板确认版本。

### 计划命令

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

### 成功标准

- 当前分支代码与 GitHub main 一致。
- HEAD 为老板确认的部署 commit。
- 无未预期本地修改。

### 老板确认点

```text
[ ] 确认 GitHub main commit
[ ] 确认服务器 HEAD 与审批版本一致
[ ] 确认允许覆盖服务器本地未记录修改
```

## 4. Docker 部署步骤

### 检查生产环境变量

```bash
ls -l .env.production
grep -n '<.*>' .env.production && echo "ERROR: placeholder exists" || echo "OK: no placeholder"
chmod 600 .env.production
```

### 渲染生产 Compose

```bash
PRODUCTION_ENV_FILE=.env.production \
docker compose --env-file .env.production -f docker-compose.prod.yml config
```

### 构建镜像

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml build backend worker nginx
```

如需完全重建：

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml build --no-cache backend worker nginx
```

### 成功标准

- `.env.production` 存在且权限为 600。
- `.env.production` 无占位符。
- Compose config 成功。
- backend / worker / nginx 镜像构建成功。

### 老板确认点

```text
[ ] 确认 .env.production 已准备
[ ] 确认生产密钥未泄露
[ ] 确认允许开始 Docker build
```

## 5. 数据库迁移步骤

### 部署前数据库备份

```bash
mkdir -p /data/backups/tiantong-ai-cloud
docker compose --env-file .env.production -f docker-compose.prod.yml exec -T postgres \
  pg_dump -U "$POSTGRES_ADMIN_USER" "$POSTGRES_DB" \
  > /data/backups/tiantong-ai-cloud/backup_$(date +%Y%m%d_%H%M%S).sql
```

### 权限检查

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml exec -T postgres \
  psql -U "$POSTGRES_ADMIN_USER" -d "$POSTGRES_DB" -c '\du'
```

### 执行迁移

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml run --rm backend alembic upgrade head
docker compose --env-file .env.production -f docker-compose.prod.yml run --rm backend alembic current
```

### 成功标准

- 数据库备份文件生成。
- `tiantong_app` 低权限用户存在。
- `tiantong_app` 非 Superuser。
- Alembic 升级到 head。

### 老板确认点

```text
[ ] 确认数据库已备份
[ ] 确认 tiantong_app 低权限用户已创建
[ ] 确认允许执行 alembic upgrade head
```

## 6. 服务启动步骤

### 启动服务

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml up -d
```

如需强制重启业务服务：

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml up -d --force-recreate backend worker nginx
```

### 查看状态

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml ps
```

### 成功标准

- backend healthy
- postgres healthy
- redis healthy
- worker running
- nginx healthy / running

### 老板确认点

```text
[ ] 确认允许启动生产服务
[ ] 确认服务状态满足上线要求
```

## 7. 健康检查

### 本机检查

```bash
curl -i http://127.0.0.1/api/health
curl -i http://127.0.0.1/api/ready
curl -k -i https://127.0.0.1/api/health
curl -k -i https://127.0.0.1/api/ready
```

### 域名检查

```bash
curl -I http://<domain>
curl -I https://<domain>
curl -i https://<domain>/api/health
curl -i https://<domain>/api/ready
```

### 页面检查

```bash
curl -I https://<domain>/
curl -I https://<domain>/index.html
curl -I https://<domain>/dashboard/overview.html
curl -I https://<domain>/task-center.html
curl -I https://<domain>/ai-employees.html
```

### 成功标准

- HTTP 跳 HTTPS。
- `/api/health` 返回 200。
- `/api/ready` 返回 200。
- 页面返回 200。
- 老板浏览器打开不白屏。

### 老板确认点

```text
[ ] 确认 health/ready 正常
[ ] 确认页面可打开
[ ] 确认无白屏
```

## 8. 登录测试

### 未登录权限检查

```bash
curl -i https://<domain>/api/ceo-dashboard/daily-summary
curl -i https://<domain>/api/task-center/tasks
curl -i https://<domain>/api/ai-employees/runtime-status
```

预期：

- 返回 401。

### 浏览器登录检查

需要人工在浏览器验证：

- owner 登录成功。
- boss 登录成功。
- admin 登录成功。
- viewer 不能访问管理接口。

### 成功标准

- 未登录接口返回 401。
- owner / boss / admin 可访问授权页面。
- viewer 权限受限。
- 响应不泄露 password / token / secret / private key。

### 老板确认点

```text
[ ] 确认 owner/boss/admin 登录正常
[ ] 确认 viewer 无越权
[ ] 确认核心页面可用
```

## 9. 日志检查

### 计划命令

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml logs --tail=200 backend
docker compose --env-file .env.production -f docker-compose.prod.yml logs --tail=200 worker
docker compose --env-file .env.production -f docker-compose.prod.yml logs --tail=200 nginx
```

### 成功标准

- 无 Traceback。
- 无 ImportError。
- 无 ModuleNotFoundError。
- 无持续 500。
- 无 password / token / secret / private key 泄露。

### 老板确认点

```text
[ ] 确认后端日志无异常
[ ] 确认 worker 日志无异常
[ ] 确认 nginx 日志无异常
[ ] 确认日志无敏感信息泄露
```

## 10. 回滚方案

### 10.1 回滚触发条件

满足任一条件，必须暂停上线并回滚或修复：

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

### 10.2 Git 回滚

```bash
git log --oneline -5
git reset --hard <previous_stable_commit>
docker compose --env-file .env.production -f docker-compose.prod.yml build backend worker nginx
docker compose --env-file .env.production -f docker-compose.prod.yml up -d --force-recreate backend worker nginx
```

### 10.3 Docker 回滚

部署前标记旧镜像：

```bash
docker image ls
docker tag tiantong-ai-cloud-backend:latest tiantong-ai-cloud-backend:backup-$(date +%Y%m%d_%H%M%S)
docker tag tiantong-ai-cloud-worker:latest tiantong-ai-cloud-worker:backup-$(date +%Y%m%d_%H%M%S)
```

必要时回退到旧镜像 tag，并重新启动。

### 10.4 数据库保护

原则：

- 不自动 downgrade。
- 不删除 volume。
- 不重建数据库。
- 不执行 `docker volume rm`。

如 migration 后异常：

1. 优先代码前滚修复。
2. 必须恢复时，停止 backend / worker。
3. 使用部署前备份恢复。
4. 恢复前必须老板二次确认。

### 10.5 单服务重启

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml up -d --force-recreate nginx
docker compose --env-file .env.production -f docker-compose.prod.yml up -d --force-recreate backend worker
docker compose --env-file .env.production -f docker-compose.prod.yml up -d --force-recreate redis backend worker
```

### 老板确认点

```text
[ ] 确认已理解回滚触发条件
[ ] 确认允许按 Runbook 回滚
[ ] 确认禁止删除数据库 volume
```

## 11. 最终确认

正式部署前必须逐项确认：

```text
[ ] 目标 ECS 已确认
[ ] 当前 GitHub main commit 已确认
[ ] .env.production 已确认
[ ] 数据库备份已确认
[ ] PostgreSQL 低权限用户已确认
[ ] Redis 密码已确认
[ ] TLS 证书已确认
[ ] 阿里云安全组已确认
[ ] 回滚方案已确认
[ ] 老板确认允许开始部署
```

## 12. 结论

Sprint29.7 当前只生成生产部署计划。

等待老板确认后，才能执行真实阿里云生产部署。
