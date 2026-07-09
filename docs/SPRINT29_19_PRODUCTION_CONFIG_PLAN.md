# Sprint29.19 生产配置执行计划

## 1. 当前目标

生产主域名已确认：

```text
cloud.tiantongai.com
```

本阶段只完成生产配置准备，不启动生产服务，不执行正式部署。

## 2. 已修改配置

文件：

```text
nginx/production.conf
```

修改内容：

- HTTP server block `server_name` 改为 `cloud.tiantongai.com`
- HTTPS server block `server_name` 改为 `cloud.tiantongai.com`

## 3. 等待人工完成事项

需要人工上传或生成 SSL 证书文件：

```text
/root/tiantong-ai-cloud/certs/fullchain.pem
/root/tiantong-ai-cloud/certs/privkey.pem
```

证书文件权限建议：

```bash
chmod 700 /root/tiantong-ai-cloud/certs
chmod 644 /root/tiantong-ai-cloud/certs/fullchain.pem
chmod 600 /root/tiantong-ai-cloud/certs/privkey.pem
```

证书必须匹配：

```text
cloud.tiantongai.com
```

## 4. 生产配置检查项

### docker-compose.prod.yml

已检查：

- Backend / Worker 使用 `.env.production`
- Nginx 使用 `nginx/production.conf`
- Nginx 暴露 80 / 443
- TLS 证书通过变量挂载：
  - `TLS_CERT_PATH`
  - `TLS_KEY_PATH`
- Redis 使用 `REDIS_PASSWORD`
- Redis healthcheck 使用密码校验
- PostgreSQL 使用管理账号变量：
  - `POSTGRES_ADMIN_USER`
  - `POSTGRES_ADMIN_PASSWORD`

### .env.production

正式部署前必须确认以下变量存在且不为空：

```text
DATABASE_URL
POSTGRES_DB
POSTGRES_ADMIN_USER
POSTGRES_ADMIN_PASSWORD
REDIS_PASSWORD
REDIS_URL
JWT_SECRET
APP_ENV=production
TLS_CERT_PATH
TLS_KEY_PATH
```

建议 TLS 路径：

```text
TLS_CERT_PATH=/root/tiantong-ai-cloud/certs/fullchain.pem
TLS_KEY_PATH=/root/tiantong-ai-cloud/certs/privkey.pem
```

### Redis Requirepass

生产 compose 已配置：

```text
redis-server --appendonly yes --requirepass
```

正式启动后验证：

```bash
set -a
. ./.env.production
set +a
docker compose --env-file .env.production -f docker-compose.prod.yml exec -T redis redis-cli -a "$REDIS_PASSWORD" ping
```

期望：

```text
PONG
```

### PostgreSQL 权限

正式部署前确认：

- Backend `DATABASE_URL` 使用最小权限应用用户。
- PostgreSQL 容器初始化管理账号仅用于数据库初始化与维护。
- 5432 不公网开放。

## 5. 下一步执行计划

证书上传完成后，按顺序执行：

1. 检查证书文件存在：

   ```bash
   ls -l /root/tiantong-ai-cloud/certs/fullchain.pem
   ls -l /root/tiantong-ai-cloud/certs/privkey.pem
   ```

2. 验证证书域名：

   ```bash
   openssl x509 -in /root/tiantong-ai-cloud/certs/fullchain.pem -noout -subject -issuer -dates
   ```

3. 验证生产 compose：

   ```bash
   cd /root/tiantong-ai-cloud
   docker compose --env-file .env.production -f docker-compose.prod.yml config
   ```

4. 构建镜像：

   ```bash
   docker compose --env-file .env.production -f docker-compose.prod.yml build backend worker nginx
   ```

5. 执行数据库迁移：

   ```bash
   docker compose --env-file .env.production -f docker-compose.prod.yml run --rm backend alembic upgrade head
   ```

6. 启动生产服务：

   ```bash
   docker compose --env-file .env.production -f docker-compose.prod.yml up -d
   ```

7. 健康检查：

   ```bash
   curl -i https://cloud.tiantongai.com/api/health
   curl -i https://cloud.tiantongai.com/api/ready
   ```

8. 页面检查：

   ```bash
   curl -I https://cloud.tiantongai.com/
   ```

## 6. 当前阻塞项

- SSL 证书文件尚未确认上传。
- 生产服务尚未启动。
- HTTPS 443 尚未正式验证。

## 7. 当前结论

Sprint29.19 当前处于生产配置准备阶段。

允许继续：

- 上传 TLS 证书。
- 检查 `.env.production`。
- 执行 compose config 验证。

暂不允许：

- 正式启动生产 443。
- 删除旧服务。
- 修改业务逻辑。
- 跳过证书验证直接上线。
