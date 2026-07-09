# Sprint29.6 阿里云正式部署执行计划

目标：将天统AI V1 生产化配置部署到阿里云 ECS。

状态：待老板人工确认后执行。

执行边界：

- 本文档只输出执行计划
- 当前不连接 ECS
- 当前不执行部署
- 当前不修改业务代码
- 当前不修改数据库结构

## 1. 执行前检查计划

### 1.1 ECS 环境

检查目标：

- 确认服务器可登录
- 确认部署目录存在
- 确认当前用户具备 Docker 执行权限

计划命令：

```bash
whoami
hostname
pwd
date
timedatectl
ls -la /data/apps/tiantong-ai-cloud
```

通过标准：

- 当前目录为 `/data/apps/tiantong-ai-cloud`
- 系统时间正常
- 部署用户权限正常

### 1.2 Docker 版本

计划命令：

```bash
docker --version
docker ps
```

通过标准：

- Docker daemon 正常
- 当前用户可执行 Docker

### 1.3 Docker Compose

计划命令：

```bash
docker compose version
```

通过标准：

- Docker Compose v2 可用

### 1.4 磁盘空间

计划命令：

```bash
df -h
docker system df
du -sh /data/apps/tiantong-ai-cloud 2>/dev/null || true
```

通过标准：

- 可用磁盘空间不少于 10GB
- 具备数据库备份空间

### 1.5 网络端口

计划命令：

```bash
ss -tulpn
```

阿里云安全组人工确认：

- 开放 80
- 开放 443
- 保留必要 SSH 端口
- 不开放 5432
- 不开放 6379
- 不开放 8000

### 1.6 域名

计划命令：

```bash
dig <domain>
curl -I http://<domain>
```

通过标准：

- 域名解析到目标 ECS / SLB / CDN
- HTTP 能到达 Nginx 或跳转 HTTPS

### 1.7 SSL 证书

计划命令：

```bash
ls -l "$TLS_CERT_PATH" "$TLS_KEY_PATH"
openssl x509 -in "$TLS_CERT_PATH" -noout -dates -subject
```

通过标准：

- 证书文件存在
- 私钥文件存在
- 证书未过期
- 路径与 `.env.production` 一致

### 1.8 数据库备份

计划命令：

```bash
mkdir -p /data/backups/tiantong-ai-cloud
docker compose --env-file .env.production -f docker-compose.prod.yml exec -T postgres \
  pg_dump -U "$POSTGRES_ADMIN_USER" "$POSTGRES_DB" \
  > /data/backups/tiantong-ai-cloud/backup_$(date +%Y%m%d_%H%M%S).sql
```

通过标准：

- 备份文件生成
- 备份文件大小合理
- 不删除 volume
- 不重建数据库

## 2. 部署执行步骤

### 2.1 拉取 GitHub main 最新版本

```bash
cd /data/apps/tiantong-ai-cloud
git fetch origin main
git reset --hard origin/main
git rev-parse HEAD
git log -1 --oneline
```

通过标准：

- 当前 commit 为老板确认版本
- 工作区无未预期修改

### 2.2 配置生产环境变量

检查 `.env.production`：

```bash
ls -l .env.production
grep -n '<.*>' .env.production && echo "ERROR: placeholder exists" || echo "OK: no placeholder"
```

设置权限：

```bash
chmod 600 .env.production
```

配置渲染：

```bash
PRODUCTION_ENV_FILE=.env.production \
docker compose --env-file .env.production -f docker-compose.prod.yml config
```

通过标准：

- `.env.production` 存在
- 权限为 600
- 无 `<...>` 占位符
- compose config 成功

### 2.3 Docker build

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml build backend worker nginx
```

如需完全重建：

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml build --no-cache backend worker nginx
```

通过标准：

- backend 镜像构建成功
- worker 镜像构建成功
- nginx 镜像构建成功

### 2.4 数据库迁移

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml run --rm backend alembic upgrade head
docker compose --env-file .env.production -f docker-compose.prod.yml run --rm backend alembic current
```

通过标准：

- migration 成功
- 当前版本为 head
- 不执行 downgrade

### 2.5 启动服务

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml up -d
```

如需强制重启业务服务：

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml up -d --force-recreate backend worker nginx
```

通过标准：

- backend healthy
- postgres healthy
- redis healthy
- worker running
- nginx healthy / running

### 2.6 Health 检查

本机检查：

```bash
curl -i http://127.0.0.1/api/health
curl -i http://127.0.0.1/api/ready
curl -k -i https://127.0.0.1/api/health
curl -k -i https://127.0.0.1/api/ready
```

域名检查：

```bash
curl -i https://<domain>/api/health
curl -i https://<domain>/api/ready
```

通过标准：

- `/api/health` 返回 200
- `/api/ready` 返回 200

### 2.7 页面检查

```bash
curl -I https://<domain>/
curl -I https://<domain>/index.html
curl -I https://<domain>/dashboard/overview.html
curl -I https://<domain>/task-center.html
curl -I https://<domain>/ai-employees.html
```

通过标准：

- 页面返回 200
- 老板浏览器打开不白屏

### 2.8 API 检查

未登录权限：

```bash
curl -i https://<domain>/api/ceo-dashboard/daily-summary
curl -i https://<domain>/api/task-center/tasks
curl -i https://<domain>/api/ai-employees/runtime-status
```

通过标准：

- 未登录返回 401
- owner / boss / admin 登录后可访问授权接口
- viewer 不能访问管理接口

### 2.9 日志检查

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml logs --tail=200 backend
docker compose --env-file .env.production -f docker-compose.prod.yml logs --tail=200 worker
docker compose --env-file .env.production -f docker-compose.prod.yml logs --tail=200 nginx
```

通过标准：

- 无 Traceback
- 无 ImportError
- 无 ModuleNotFoundError
- 无持续 500
- 无 password / token / secret / private key 泄露

## 3. 风险列表

### 3.1 数据库风险

风险：低权限用户 `tiantong_app` 若未提前创建，backend 将无法连接数据库。

控制：

- 部署前人工确认 `\du`
- 部署前确认 `DATABASE_URL`
- 部署前做 pg_dump 备份

### 3.2 Redis 风险

风险：`REDIS_PASSWORD` 与 `REDIS_URL` 不一致会导致 backend / worker 无法连接 Redis。

控制：

- 部署前执行 compose config
- 启动后检查 `/api/ready`

### 3.3 TLS 风险

风险：证书路径错误或证书过期会导致 nginx 无法启动。

控制：

- 部署前检查证书路径
- 部署前检查证书有效期
- 如失败，按 nginx 回滚方案处理

### 3.4 Cookie Secure 风险

风险：当前后端仍需后续小改以在生产环境设置 cookie `secure=True`。

控制：

- 如果本次直接公网发布，需老板确认接受该短期风险
- 建议作为部署后 P0 小修进入天王开发

### 3.5 Docker 风险

风险：容器尚未完全非 root / read-only rootfs。

控制：

- 当前不阻塞 V1 受控部署
- V2 做容器安全硬化

### 3.6 密钥风险

风险：人工创建 `.env.production` 时误填弱密钥或误提交。

控制：

- `.env.production` 已加入 `.gitignore`
- 部署前确认权限 600
- 部署后检查日志无 secret 泄露

## 4. 回滚计划

### 4.1 Git 回滚

```bash
git log --oneline -5
git reset --hard <previous_stable_commit>
docker compose --env-file .env.production -f docker-compose.prod.yml build backend worker nginx
docker compose --env-file .env.production -f docker-compose.prod.yml up -d --force-recreate backend worker nginx
```

### 4.2 Docker 回滚

部署前标记旧镜像：

```bash
docker image ls
docker tag tiantong-ai-cloud-backend:latest tiantong-ai-cloud-backend:backup-$(date +%Y%m%d_%H%M%S)
docker tag tiantong-ai-cloud-worker:latest tiantong-ai-cloud-worker:backup-$(date +%Y%m%d_%H%M%S)
```

必要时回退到旧镜像 tag，并重新 `up -d`。

### 4.3 数据库保护

原则：

- 不自动 downgrade
- 不删除 volume
- 不重建数据库
- 不执行 `docker volume rm`

如迁移后异常：

1. 优先代码前滚修复。
2. 必须恢复时，停止 backend / worker。
3. 使用部署前备份恢复。
4. 恢复前必须老板二次确认。

### 4.4 Nginx 回滚

如果 HTTPS 配置失败：

1. 检查证书路径和权限。
2. 修复 `.env.production` 的 TLS 路径。
3. 重新启动 nginx。
4. 如仍失败，临时回退上一版 nginx 配置，并记录风险。

## 5. 人工确认清单

正式执行前，老板/部署负责人必须确认：

```text
[ ] 当前 GitHub main commit 已确认
[ ] ECS 可登录
[ ] Docker 可用
[ ] Docker Compose v2 可用
[ ] 磁盘空间充足
[ ] 80 / 443 / SSH 安全组已确认
[ ] 5432 / 6379 / 8000 未开放公网
[ ] 域名解析正确
[ ] SSL 证书存在且未过期
[ ] .env.production 已创建
[ ] .env.production 权限为 600
[ ] .env.production 无占位符
[ ] PostgreSQL 已备份
[ ] tiantong_app 低权限用户已创建
[ ] DATABASE_URL 使用 tiantong_app
[ ] REDIS_PASSWORD 与 REDIS_URL 一致
[ ] Runbook 已阅读
[ ] 回滚方案已确认
[ ] Cookie Secure 短期风险已确认或已安排修复
```

## 6. 结论

Sprint29.6 当前只完成部署执行计划，不执行任何生产操作。

等待老板人工确认后，才能进入阿里云正式部署执行。
