# Sprint29.4 阿里云生产部署执行 Runbook

目标：将天统AI V1 冻结版本部署到阿里云生产环境。

执行边界：

- 本文档只提供部署执行方案
- 不在本阶段连接服务器
- 不在本阶段执行真实部署
- 不修改业务代码

## 1. 阿里云部署前检查清单

### 1.1 ECS 环境

必须确认：

- 操作系统：Ubuntu 22.04+ / Ubuntu 24.04
- 服务器时间同步正常：
  - `timedatectl`
- 当前部署目录存在：
  - `/data/apps/tiantong-ai-cloud`
- 部署用户具备：
  - Git 拉取权限
  - Docker 执行权限
  - 读取 `.env.production` 权限
- 当前 GitHub main 可访问。

建议检查命令：

```bash
whoami
hostname
pwd
date
timedatectl
ls -la /data/apps/tiantong-ai-cloud
```

### 1.2 Docker 版本

必须确认：

- Docker 已安装
- Docker daemon 正常
- 当前用户可执行 Docker

检查命令：

```bash
docker --version
docker ps
```

### 1.3 Docker Compose

必须确认：

- 使用 Docker Compose v2
- `docker compose` 命令可用

检查命令：

```bash
docker compose version
```

### 1.4 磁盘空间

必须确认：

- 根分区空间充足
- Docker 数据目录空间充足
- PostgreSQL volume 有备份空间

检查命令：

```bash
df -h
docker system df
du -sh /data/apps/tiantong-ai-cloud 2>/dev/null || true
```

最低建议：

- 可用磁盘空间不少于 10GB
- 数据库备份空间不少于当前 PostgreSQL volume 2 倍

### 1.5 网络端口

阿里云安全组必须确认：

- 开放：
  - 80/tcp
  - 443/tcp
  - 必要 SSH 端口
- 禁止公网开放：
  - 5432/tcp
  - 6379/tcp
  - 8000/tcp

服务器本机检查：

```bash
ss -tulpn
```

### 1.6 SSL 证书

必须确认：

- 证书文件存在
- 私钥文件存在
- 路径与 `.env.production` 一致：
  - `TLS_CERT_PATH`
  - `TLS_KEY_PATH`
- 证书未过期

检查命令：

```bash
ls -l "$TLS_CERT_PATH" "$TLS_KEY_PATH"
openssl x509 -in "$TLS_CERT_PATH" -noout -dates -subject
```

注意：

- 证书和私钥不得提交 Git。
- 私钥文件权限应限制为部署用户或 root 可读。

### 1.7 域名解析

必须确认：

- 域名 A 记录指向当前 ECS 公网 IP
- DNS 已生效
- 如使用 CDN / SLB，确认转发到 ECS 80/443

检查命令：

```bash
dig <domain>
curl -I http://<domain>
```

### 1.8 生产环境变量

必须确认：

- 服务器存在 `.env.production`
- 文件权限为 `600`
- 不包含 `<...>` 占位符
- 不使用默认弱密钥

检查命令：

```bash
ls -l .env.production
grep -n '<.*>' .env.production && echo "ERROR: placeholder exists" || echo "OK: no placeholder"
```

必须包含：

- `APP_ENV=production`
- `DATABASE_URL`
- `POSTGRES_DB`
- `POSTGRES_ADMIN_USER`
- `POSTGRES_ADMIN_PASSWORD`
- `REDIS_PASSWORD`
- `REDIS_URL`
- `JWT_SECRET`
- `TLS_CERT_PATH`
- `TLS_KEY_PATH`

## 2. 生产部署步骤

### 2.1 进入部署目录

```bash
cd /data/apps/tiantong-ai-cloud
```

### 2.2 记录部署前版本

```bash
git rev-parse HEAD
git log -1 --oneline
docker compose --env-file .env.production -f docker-compose.prod.yml ps
```

建议保存输出到部署记录。

### 2.3 拉取 GitHub main

```bash
git fetch origin main
git reset --hard origin/main
git rev-parse HEAD
git log -1 --oneline
```

确认当前 commit 为已通过验收的 V1 冻结版本或后续批准版本。

### 2.4 检查生产配置渲染

```bash
PRODUCTION_ENV_FILE=.env.production \
docker compose --env-file .env.production -f docker-compose.prod.yml config
```

必须确认：

- 无缺失变量
- PostgreSQL 未暴露 5432
- Redis 未暴露 6379
- Nginx 暴露 80/443
- Redis command 包含 `--requirepass`

### 2.5 数据库备份

部署前必须备份。

示例：

```bash
mkdir -p /data/backups/tiantong-ai-cloud
docker compose --env-file .env.production -f docker-compose.prod.yml exec -T postgres \
  pg_dump -U "$POSTGRES_ADMIN_USER" "$POSTGRES_DB" \
  > /data/backups/tiantong-ai-cloud/backup_$(date +%Y%m%d_%H%M%S).sql
```

注意：

- 不删除 volume。
- 不执行 `docker volume rm`。
- 不执行数据库重建。

### 2.6 PostgreSQL 权限确认

确认低权限应用用户存在：

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml exec -T postgres \
  psql -U "$POSTGRES_ADMIN_USER" -d "$POSTGRES_DB" -c '\du'
```

必须确认：

- `tiantong_app` 存在
- `tiantong_app` 不是 Superuser
- `tiantong_app` 没有 Create DB / Create Role / Replication / Bypass RLS

### 2.7 Docker 构建

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml build backend worker nginx
```

如需完全重建：

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml build --no-cache backend worker nginx
```

### 2.8 数据库迁移

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml run --rm backend alembic upgrade head
```

迁移后检查：

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml run --rm backend alembic current
```

### 2.9 启动服务

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml up -d
```

如需要强制重建服务：

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml up -d --force-recreate backend worker nginx
```

### 2.10 服务状态检查

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml ps
```

必须确认：

- backend healthy
- postgres healthy
- redis healthy
- worker running
- nginx healthy / running

### 2.11 健康检查

本机检查：

```bash
curl -i http://127.0.0.1/api/health
curl -i http://127.0.0.1/api/ready
curl -k -i https://127.0.0.1/api/health
curl -k -i https://127.0.0.1/api/ready
```

域名检查：

```bash
curl -I http://<domain>
curl -I https://<domain>
curl -i https://<domain>/api/health
curl -i https://<domain>/api/ready
```

预期：

- HTTP 跳转 HTTPS
- HTTPS health/ready 返回 200

### 2.12 页面检查

```bash
curl -I https://<domain>/
curl -I https://<domain>/index.html
curl -I https://<domain>/dashboard/overview.html
curl -I https://<domain>/task-center.html
curl -I https://<domain>/ai-employees.html
```

预期：

- 返回 200
- 页面不白屏

### 2.13 API 权限检查

未登录应返回 401：

```bash
curl -i https://<domain>/api/ceo-dashboard/daily-summary
curl -i https://<domain>/api/task-center/tasks
curl -i https://<domain>/api/ai-employees/runtime-status
```

登录后检查：

- boss / owner / admin 可以访问授权页面和 API。
- viewer 不得访问管理接口。

### 2.14 日志检查

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml logs --tail=200 backend
docker compose --env-file .env.production -f docker-compose.prod.yml logs --tail=200 worker
docker compose --env-file .env.production -f docker-compose.prod.yml logs --tail=200 nginx
```

必须确认没有：

- Traceback
- ImportError
- ModuleNotFoundError
- 500 持续错误
- password / token / secret / private key 泄露

## 3. 回滚方案

### 3.1 Git 回滚

记录上一稳定版本：

```bash
git log --oneline -5
```

回滚到上一稳定 commit：

```bash
git reset --hard <previous_stable_commit>
```

重新构建并启动：

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml build backend worker nginx
docker compose --env-file .env.production -f docker-compose.prod.yml up -d --force-recreate backend worker nginx
```

### 3.2 Docker 回滚

如果保留了旧镜像 tag，可直接回滚 tag。

建议部署前标记当前镜像：

```bash
docker image ls
docker tag tiantong-ai-cloud-backend:latest tiantong-ai-cloud-backend:backup-$(date +%Y%m%d_%H%M%S)
docker tag tiantong-ai-cloud-worker:latest tiantong-ai-cloud-worker:backup-$(date +%Y%m%d_%H%M%S)
```

如果新镜像异常：

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml up -d --force-recreate backend worker nginx
```

必要时将 compose 指回旧镜像 tag，经过人工确认后再启动。

### 3.3 数据库保护

原则：

- 不自动 downgrade
- 不删除 volume
- 不重建数据库
- 不执行 `docker volume rm`

如果 migration 后业务异常：

1. 先判断是否可用代码前滚修复。
2. 如必须恢复数据库：
   - 停止 backend / worker。
   - 使用部署前 `pg_dump` 备份恢复。
   - 恢复前必须人工二次确认。

示例停止业务层：

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml stop backend worker
```

### 3.4 Redis 回滚

Redis 只保存队列和 session 类运行态数据。

如果 Redis 密码配置错误：

1. 修复 `.env.production` 中 `REDIS_PASSWORD` 和 `REDIS_URL`。
2. 重启 redis / backend / worker：

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml up -d --force-recreate redis backend worker
```

禁止删除 Redis volume，除非老板明确批准。

### 3.5 Nginx 回滚

如果 HTTPS 配置导致 nginx 无法启动：

1. 检查证书路径：
   - `TLS_CERT_PATH`
   - `TLS_KEY_PATH`
2. 检查证书权限。
3. 如需临时回滚，使用上一版 nginx 配置和 80 端口，但必须记录风险。

重启 nginx：

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml up -d --force-recreate nginx
```

### 3.6 回滚后验证

必须检查：

```bash
curl -i https://<domain>/api/health
curl -i https://<domain>/api/ready
curl -I https://<domain>/
```

并检查：

- 登录
- 老板驾驶舱
- Task Center
- AI员工中心
- backend / worker / nginx 日志

## 4. 部署完成记录模板

部署完成后记录：

```text
部署时间：
部署负责人：
Git commit：
Docker 镜像：
Alembic 版本：
健康检查：
页面检查：
权限检查：
日志检查：
风险项：
是否完成：
```

## 5. 结论

本 Runbook 可用于人工执行 Sprint29 生产部署。

执行前必须完成：

- `.env.production`
- PostgreSQL 低权限用户
- Redis 密码
- TLS 证书
- 阿里云安全组
- 数据库备份

完成以上检查后，才能进入正式部署执行。
