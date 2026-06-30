# 天统AI云中台

天统AI云中台是公司内部电商经营管理系统，覆盖老板驾驶舱、员工登录、京东60店数据中心、今日数据录入、Excel批量导入、京东商智/京准通采集、AI店长分析和AI员工任务系统。

## 当前阶段

- 第一阶段：完成 `backend/` 和 `frontend/` 分离。
- 第二阶段：完成 Owner Dashboard、系统菜单、角色权限和统一指标表。
- 第三阶段：完成京东60店数据中心和 AI 员工任务系统。
- 第四阶段：完成 PostgreSQL、Redis、JWT、SQLAlchemy ORM、Alembic、Docker Compose。
- 第五阶段：完成京东统一数据采集平台骨架、Redis Queue、后台 worker、京东商智/京准通采集适配器和 AI店长分析任务。

## 数据库

核心表：

- `stores`：60店基础信息。
- `jd_accounts`：京东商智、京准通账号授权信息。
- `jd_daily_metrics`：京东商智每日指标，包括 GMV、利润、访客、支付订单、广告费、ROI、退款、售后、收藏、加购、转化率。
- `jd_ads`：京准通广告数据，包括消耗、点击、曝光、ROI、CPA、成交金额、广告计划。
- `jd_orders`：京东订单数据。
- `jd_products`：商品数据、销量、流量、转化、库存。

兼容表：

- `users`
- `roles`
- `permissions`
- `role_permissions`
- `metrics_daily`
- `employee_logs`
- `ai_tasks`
- `jd_integrations`

## API

登录与基础：

- `POST /api/login`
- `POST /api/logout`
- `GET /api/me`

店铺与老板驾驶舱：

- `GET /api/stores`
- `POST /api/stores`
- `GET /api/jd/dashboard`
- `GET /api/owner/dashboard`
- `GET /api/jd/metrics/summary`

今日数据与导入：

- `GET /api/metrics/today`
- `POST /api/metrics/manual`
- `POST /api/metrics/import`

京东采集：

- `GET /api/jd/accounts`
- `POST /api/jd/accounts`
- `POST /api/jd/sync/store/{store_id}`
- `POST /api/jd/sync/all`

AI店长与任务：

- `POST /api/ai/store-manager/analyze`
- `POST /api/ai/store-manager/enqueue`
- `GET /api/ai/tasks`
- `POST /api/ai/tasks/{task_id}`
- `POST /api/ai/tasks/{task_id}/run`

## 采集说明

京东商智和京准通采集器位于：

- `backend/services/jd_collectors.py`

当前实现已经建立生产级接口边界：

- 账号授权信息从 `jd_accounts` 读取。
- 采集任务进入 Redis Queue。
- worker 从队列消费任务。
- 采集结果写入 `jd_daily_metrics`、`jd_ads`、`jd_orders`、`jd_products`。

真实京东接口授权、Cookie 登录或浏览器自动化采集逻辑应继续接入到 `JdSmartCollector` 和 `JztCollector` 中。未授权时系统不会伪造数据。

## Redis Queue

队列名：

```text
tiantong:tasks
```

任务类型：

- `sync_jd_smart`
- `sync_jzt`
- `ai_store_manager_daily`

worker：

```bash
python -m backend.worker
```

## Docker

`docker-compose.yml` 服务：

- `postgres`
- `redis`
- `backend`
- `worker`
- `nginx`

启动：

```bash
cp .env.example .env
docker compose up -d --build
```

迁移：

```bash
alembic upgrade head
```

当前 Alembic head：

```text
0004_jd_sync_runtime
```

## 环境变量

`.env.example`：

```env
DATABASE_URL=postgresql+psycopg2://tiantong:tiantong@postgres:5432/tiantong_ai
REDIS_URL=redis://redis:6379/0
JWT_SECRET=change-this-to-a-long-random-secret
OPENAI_API_KEY=
POSTGRES_DB=tiantong_ai
POSTGRES_USER=tiantong
POSTGRES_PASSWORD=tiantong
```

## 测试

```bash
python -m pytest -q
```

当前覆盖：

- 登录
- 店铺读取
- 京东60店数据中心
- 今日指标写入
- AI任务读取与执行
- 京东账号配置
- 京东采集任务入队
- AI店长分析与入队
- 账号中心模板和导入
- worker 队列消费

## 生产部署：阿里云 Ubuntu 24.04

本项目支持两种生产部署方式：

- Docker Compose：推荐方式，统一启动 `postgres`、`redis`、`backend`、`worker`、`nginx`。
- systemd：适合服务器已有 PostgreSQL、Redis、Python venv 的直部署方式。

上线前硬性要求：

- `docker compose config` 必须通过。
- `docker compose up -d` 必须能启动 `postgres`、`redis`、`backend`、`worker`、`nginx`。
- Docker 部署和 systemd 部署不要混用 Nginx 配置。
- Docker 使用 `nginx/default.conf`，代理到 `backend:8000`。
- systemd 使用 `deploy/nginx-systemd.conf`，代理到 `127.0.0.1:8000`。

### Docker 部署步骤

```bash
cd /data/apps/tiantong-ai-cloud
cp .env.example .env
chmod +x deploy.sh rollback.sh scripts/*.sh
./deploy.sh
docker compose ps
CHECK_DOCKER_INFRA=1 scripts/healthcheck.sh
```

`docker-compose.yml` 包含：

- `postgres`：PostgreSQL 16，带健康检查和持久化卷。
- `redis`：Redis 7，开启 AOF，带健康检查和持久化卷。
- `backend`：执行 Alembic 迁移并启动 FastAPI。
- `worker`：等待 backend 就绪后启动后台任务 worker。
- `nginx`：对外监听 80，静态页面走 `/`，接口走 `/api/`。

### systemd 部署步骤

```bash
cd /data/apps/tiantong-ai-cloud
cp .env.example .env
chmod +x deploy.sh rollback.sh scripts/*.sh
DEPLOY_MODE=systemd ./deploy.sh
scripts/healthcheck.sh
BASE_URL=http://127.0.0.1:8000 CHECK_PAGES=0 scripts/healthcheck.sh
```

`DEPLOY_MODE=systemd ./deploy.sh` 会创建或复用 `venv`、安装 `requirements.txt`、执行 `alembic upgrade head`、复制 systemd/Nginx 配置、重启 `tiantong-api`、`tiantong-worker` 和 Nginx。

### Nginx

Docker 部署使用 `nginx/default.conf`：

- `/`：读取前端静态目录 `/usr/share/nginx/html`
- `/api` 和 `/api/`：反向代理到 `backend:8000`
- `client_max_body_size 100M`
- 开启 gzip
- 访问日志：`/var/log/nginx/tiantong_access.log`
- 错误日志：`/var/log/nginx/tiantong_error.log`

systemd 直部署使用 `deploy/nginx-systemd.conf`：

- `/`：读取 `/data/apps/tiantong-ai-cloud/frontend`
- `/api/`：反向代理到 `127.0.0.1:8000`

### 健康检查

```bash
curl -m 5 http://127.0.0.1/api/health
curl -m 5 http://127.0.0.1/api/ready
scripts/healthcheck.sh
```

`scripts/healthcheck.sh` 默认通过 Nginx 检查所有前端页面、`/api/health` 和 `/api/ready`。如需直连后端，只检查 API：

```bash
BASE_URL=http://127.0.0.1:8000 CHECK_PAGES=0 scripts/healthcheck.sh
```

`/api/health` 返回系统、数据库、Redis 状态；`/api/ready` 用于部署就绪检查，数据库和 Redis 不可用时会返回错误。

Docker 深度检查会额外验证 PostgreSQL、Redis 和 worker 容器：

```bash
CHECK_DOCKER_INFRA=1 scripts/healthcheck.sh
```

systemd 深度检查会额外验证 `tiantong-worker`：

```bash
CHECK_SYSTEMD=1 scripts/healthcheck.sh
```

### 日志

Docker：

```bash
docker compose logs --tail=100 backend
docker compose logs --tail=100 worker
docker compose logs --tail=100 nginx
```

systemd：

```bash
sudo journalctl -u tiantong-api -n 100 --no-pager
sudo journalctl -u tiantong-worker -n 100 --no-pager
sudo tail -n 100 /var/log/tiantong-ai/api.log
sudo tail -n 100 /var/log/tiantong-ai/worker.log
```

### 数据库备份方案

```bash
cd /data/apps/tiantong-ai-cloud
scripts/backup_db.sh
ls -lh backups/
```

备份文件会写入：

```text
backups/tiantong_tiantong_ai_YYYYmmdd_HHMMSS.sql.gz
```

### 回滚方案

Docker 回滚：

```bash
cd /data/apps/tiantong-ai-cloud
./rollback.sh <上一版本>
scripts/healthcheck.sh
```

systemd 回滚：

```bash
cd /data/apps/tiantong-ai-cloud
DEPLOY_MODE=systemd ./rollback.sh <上一版本>
BASE_URL=http://127.0.0.1:8000 CHECK_PAGES=0 scripts/healthcheck.sh
```

### Redis 修复方案

Docker：

```bash
docker compose restart redis
docker compose logs --tail=100 redis
scripts/healthcheck.sh
```

systemd 直部署如使用系统 Redis：

```bash
sudo systemctl restart redis-server
sudo systemctl status redis-server --no-pager -l
BASE_URL=http://127.0.0.1:8000 CHECK_PAGES=0 scripts/healthcheck.sh
```
