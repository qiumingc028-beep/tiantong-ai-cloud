# 生产部署说明

## 环境要求

- Linux/amd64 生产宿主机，或显式指定 `DOCKER_DEFAULT_PLATFORM=linux/amd64`。
- Docker Compose 可用。
- `.env.production` 已创建并通过校验。
- 已完成数据库备份和配置备份。

## 必需环境变量

- `ENVIRONMENT=production`
- `DEBUG=false`
- `SECRET_KEY`
- `JWT_SECRET`
- `DATABASE_URL`
- `REDIS_URL`
- `CORS_ORIGINS`
- `HTTP_PORT`
- `HTTPS_PORT`
- `TLS_CERT_PATH`
- `TLS_KEY_PATH`
- `REQUIREMENTS_LOCK`

## amd64 构建

```bash
DOCKER_DEFAULT_PLATFORM=linux/amd64 \
REQUIREMENTS_LOCK=artifacts/wheelhouse/linux-amd64-cp312/requirements-linux-amd64-cp312.lock \
docker compose --env-file .env.production -f docker-compose.prod.yml up -d --build
```

## arm64 构建

```bash
DOCKER_DEFAULT_PLATFORM=linux/arm64 \
REQUIREMENTS_LOCK=artifacts/wheelhouse/linux-arm64-cp312/requirements-linux-arm64-cp312.lock \
docker compose --env-file .env.production -f docker-compose.prod.yml up -d --build
```

## 健康检查

```bash
curl -fsS https://127.0.0.1/api/health
curl -fsS https://127.0.0.1/api/ready
```

## 停止

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml stop
```

## 注意

- 不提交真实 `.env.production`。
- 不允许 `CORS_ORIGINS=*`。
- 不允许默认 Secret。
