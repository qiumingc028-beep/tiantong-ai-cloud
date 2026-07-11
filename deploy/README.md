# 天统AI云中台部署运行说明

## 部署方式

生产建议优先使用 Docker Compose 部署：

```bash
cd /data/apps/tiantong-ai-cloud
cp .env.production.example .env.production
# 人工填写全部生产秘密，禁止沿用占位符
docker compose --env-file .env.production -f docker-compose.prod.yml config
docker compose --env-file .env.production -f docker-compose.prod.yml up -d --build
```

如服务器采用 venv + systemd 直部署，使用：

```bash
DEPLOY_MODE=systemd ./deploy.sh
```

上线前硬性要求：

- `docker compose config` 必须通过。
- `docker compose up -d` 必须能启动 `postgres`、`redis`、`backend`、`worker`、`nginx`。
- Docker 部署和 systemd 部署不要混用 Nginx 配置。
- Docker 使用 `nginx/default.conf`，代理到 `backend:8000`。
- systemd 使用 `deploy/nginx-systemd.conf`，代理到 `127.0.0.1:8000`。

## Docker Compose 部署

```bash
cd /data/apps/tiantong-ai-cloud
scripts/backup_db.sh
docker compose --env-file .env.production -f docker-compose.prod.yml config
docker compose --env-file .env.production -f docker-compose.prod.yml run --rm backend alembic upgrade head
docker compose --env-file .env.production -f docker-compose.prod.yml up -d --build
docker compose --env-file .env.production -f docker-compose.prod.yml ps
curl -fsS https://<production-host>/health
curl -fsS https://<production-host>/ready
```

`.env.production` 必须显式设置 `APP_ENV=production`、`DATABASE_URL`、带认证的 `REDIS_URL`、至少 32 个非默认字符的 `JWT_SECRET`、非默认 `BOSS_INITIAL_PASSWORD`、非空且不含 `*` 的 `CORS_ALLOWED_ORIGINS`，并设置 `DEBUG=false`。真实值不得进入 Git、日志或工单正文。

停止服务但保留 volume：

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml down
```

排错入口：

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml logs --tail=100 backend worker nginx postgres redis
```

Docker 部署包含：

- postgres
- redis
- backend
- worker
- nginx

Nginx 容器使用 `nginx/default.conf`，其中：

- `/` 读取 `/usr/share/nginx/html` 静态页面
- `/api` 和 `/api/` 代理到 `backend:8000`
- `client_max_body_size 100M`
- 开启 gzip
- 日志写入 `/var/log/nginx/tiantong_access.log` 和 `/var/log/nginx/tiantong_error.log`

## systemd 服务

```bash
cd /data/apps/tiantong-ai-cloud
cp .env.example .env
chmod +x deploy.sh scripts/*.sh
DEPLOY_MODE=systemd ./deploy.sh
scripts/healthcheck.sh
BASE_URL=http://127.0.0.1:8000 CHECK_PAGES=0 scripts/healthcheck.sh
```

systemd 部署脚本会安装 Python 依赖、执行 Alembic 迁移、复制服务文件、重启 `tiantong-api`、`tiantong-worker` 和 Nginx。

API 服务启动命令：

```bash
/data/apps/tiantong-ai-cloud/venv/bin/uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

Worker 服务启动命令：

```bash
/data/apps/tiantong-ai-cloud/venv/bin/python -m backend.worker
```

## 启停和重启

```bash
sudo systemctl start tiantong-api
sudo systemctl start tiantong-worker
sudo systemctl stop tiantong-api
sudo systemctl stop tiantong-worker
sudo systemctl restart tiantong-api
sudo systemctl restart tiantong-worker
sudo systemctl status tiantong-api --no-pager -l
sudo systemctl status tiantong-worker --no-pager -l
```

预期状态：

```text
Active: active (running)
```

## 健康检查

```bash
cd /data/apps/tiantong-ai-cloud
chmod +x scripts/healthcheck.sh deploy/healthcheck.sh
scripts/healthcheck.sh
```

`scripts/healthcheck.sh` 会检查所有 `frontend/*.html` 页面入口，以及 `/api/health`、`/api/ready`。

Docker 深度检查会额外验证 PostgreSQL、Redis 和 worker 容器：

```bash
CHECK_DOCKER_INFRA=1 scripts/healthcheck.sh
```

systemd 深度检查会额外验证 `tiantong-worker`：

```bash
CHECK_SYSTEMD=1 scripts/healthcheck.sh
```

直连后端只检查 API：

```bash
BASE_URL=http://127.0.0.1:8000 CHECK_PAGES=0 scripts/healthcheck.sh
```

直连后端时：

```bash
curl -m 5 http://127.0.0.1:8000/api/health
curl -m 5 http://127.0.0.1:8000/api/ready
```

预期返回包含：

```json
{
  "status": "running",
  "database": true,
  "redis": true
}
```

## 数据库备份

```bash
cd /data/apps/tiantong-ai-cloud
scripts/backup_db.sh
ls -lh backups/
```

备份文件格式：

```text
backups/tiantong_tiantong_ai_YYYYmmdd_HHMMSS.sql.gz
```

## 回滚方案

Docker 部署回滚：

```bash
cd /data/apps/tiantong-ai-cloud
./rollback.sh <上一版本>
scripts/healthcheck.sh
```

systemd 部署回滚：

```bash
cd /data/apps/tiantong-ai-cloud
DEPLOY_MODE=systemd ./rollback.sh <上一版本>
BASE_URL=http://127.0.0.1:8000 CHECK_PAGES=0 scripts/healthcheck.sh
```

## Redis 修复方案

Docker 部署：

```bash
docker compose restart redis
docker compose logs --tail=100 redis
scripts/healthcheck.sh
```

systemd 部署如使用系统 Redis：

```bash
sudo systemctl restart redis-server
sudo systemctl status redis-server --no-pager -l
BASE_URL=http://127.0.0.1:8000 CHECK_PAGES=0 scripts/healthcheck.sh
```

## 日志

Docker 日志：

```bash
docker compose logs --tail=100 backend
docker compose logs --tail=100 worker
docker compose logs --tail=100 nginx
```

systemd 日志：

```bash
sudo journalctl -u tiantong-api -n 100 --no-pager
sudo journalctl -u tiantong-worker -n 100 --no-pager
sudo tail -n 100 /var/log/tiantong-ai/api.log
sudo tail -n 100 /var/log/tiantong-ai/worker.log
```

Nginx 日志：

```bash
sudo tail -n 100 /var/log/nginx/tiantong_access.log
sudo tail -n 100 /var/log/nginx/tiantong_error.log
```

## 故障排查

```bash
ss -ltnp | grep ':8000'
docker compose ps
docker compose exec redis redis-cli ping
docker compose exec postgres pg_isready -U tiantong -d tiantong_ai
```

确认开机自启：

```bash
systemctl is-enabled tiantong-api
systemctl is-enabled tiantong-worker
```
