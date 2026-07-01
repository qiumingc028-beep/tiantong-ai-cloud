# 天统AI云中台部署验证手册

## 项目目录

生产服务器统一使用：

```bash
/data/apps/tiantong-ai-cloud
```

不要与旧路径 `/data/apps/tiantong-ai` 混用。

## 上线前硬性要求

- `docker compose config` 必须通过。
- `docker compose up -d` 必须能启动 `postgres`、`redis`、`backend`、`worker`、`nginx`。
- Docker 部署和 systemd 部署不要混用 Nginx 配置。
- Docker 使用 `nginx/default.conf`，代理到 `backend:8000`。
- systemd 使用 `deploy/nginx-systemd.conf`，代理到 `127.0.0.1:8000`。

## 上线前检查表

- 已确认 `.env` 中数据库、Redis、JWT、OpenAI Key 等生产变量正确。
- 已执行 `docker compose config` 且无错误。
- 已执行 `./deploy.sh` 且五个服务全部启动。
- 已执行 `CHECK_DOCKER_INFRA=1 scripts/healthcheck.sh`。
- 已确认所有 HTML 页面可通过 Nginx 访问。
- 已确认 `/api/health` 返回 `database=true` 和 `redis=true`。
- 已确认 `/api/ready` 返回 `status=ready`。
- 已确认 worker 容器或 `tiantong-worker` systemd 服务可用。
- 已执行 `scripts/backup_db.sh` 生成上线前数据库备份。
- 已准备 `./rollback.sh <上一版本>` 回滚命令。

## Docker 部署验证

```bash
cd /data/apps/tiantong-ai-cloud
cp .env.example .env
chmod +x deploy.sh scripts/*.sh
./deploy.sh
docker compose ps
CHECK_DOCKER_INFRA=1 scripts/healthcheck.sh
```

## systemd 直部署验证

```bash
cd /data/apps/tiantong-ai-cloud
cp .env.example .env
chmod +x deploy.sh scripts/*.sh
DEPLOY_MODE=systemd ./deploy.sh
journalctl -u tiantong-api -n 80 --no-pager
journalctl -u tiantong-worker -n 80 --no-pager
```

systemd 手工排障命令：

```bash
sudo systemctl status tiantong-api --no-pager
sudo systemctl status tiantong-worker --no-pager
journalctl -u tiantong-api -n 80 --no-pager
journalctl -u tiantong-worker -n 80 --no-pager
scripts/healthcheck.sh
BASE_URL=http://127.0.0.1:8000 CHECK_PAGES=0 scripts/healthcheck.sh
```

## 回滚验证

Docker 回滚：

```bash
cd /data/apps/tiantong-ai-cloud
./rollback.sh <上一版本>
CHECK_DOCKER_INFRA=1 scripts/healthcheck.sh
```

systemd 回滚：

```bash
cd /data/apps/tiantong-ai-cloud
DEPLOY_MODE=systemd ./rollback.sh <上一版本>
CHECK_SYSTEMD=1 scripts/healthcheck.sh
```

## 健康检查

Docker 入口：

```bash
curl -i http://127.0.0.1/api/health
curl -i http://127.0.0.1/api/ready
```

systemd 后端直连：

```bash
curl -i http://127.0.0.1:8000/api/health
curl -i http://127.0.0.1:8000/api/ready
```

## Nginx 验证

```bash
sudo nginx -t
sudo systemctl reload nginx
```

Docker Nginx 使用 `backend:8000`。

systemd Nginx 使用 `127.0.0.1:8000`。

## Docker 安装提示

Ubuntu 24.04：

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl gnupg
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo ${VERSION_CODENAME}) stable" | sudo tee /etc/apt/sources.list.d/docker.list >/dev/null
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
docker compose version
```

CentOS：

```bash
sudo yum install -y yum-utils
sudo yum-config-manager --add-repo https://download.docker.com/linux/centos/docker-ce.repo
sudo yum install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo systemctl enable --now docker
docker compose version
```
