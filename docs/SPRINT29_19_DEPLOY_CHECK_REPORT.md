# Sprint29.19 生产部署检查报告

## 1. 当前阶段

生产域名已确认：

```text
cloud.tiantongai.com
```

当前只完成生产配置准备，不启动生产服务，不执行正式部署。

## 2. 本地配置修改

已修改：

```text
nginx/production.conf
```

修改内容：

- HTTP server block：`server_name cloud.tiantongai.com;`
- HTTPS server block：`server_name cloud.tiantongai.com;`

未修改：

- 业务代码
- 数据库结构
- Task Center
- Orchestrator
- Execution Engine
- 权限逻辑

## 3. 服务器当前状态

服务器目录：

```text
/root/tiantong-ai-cloud
```

服务器当前 `nginx/production.conf` 尚未同步本次本地修改，仍为：

```nginx
server_name _;
```

说明：

- 这是预期状态，因为本阶段未执行部署同步。
- 等待证书上传完成后，再统一同步配置并重建 Nginx 镜像。

## 4. TLS 检查

服务器证书目录：

```text
/root/tiantong-ai-cloud/certs
```

当前状态：

- 目录存在
- 权限为 `700`
- 目录为空
- `fullchain.pem` 未上传
- `privkey.pem` 未上传

正式部署前必须补齐：

```text
/root/tiantong-ai-cloud/certs/fullchain.pem
/root/tiantong-ai-cloud/certs/privkey.pem
```

证书必须匹配：

```text
cloud.tiantongai.com
```

## 5. HTTPS 443 检查

当前服务器端口状态：

- 80：已监听
- 443：未监听
- 5432：仅本机监听
- 6379：仅本机监听
- 8000：仅本机监听

结论：

- 443 尚未正式启用。
- 当前没有启动公网 HTTPS。
- 符合“只配置、不上线”的阶段要求。

## 6. docker-compose.prod.yml 检查

生产 compose 配置校验结果：

```text
PROD_COMPOSE_CONFIG_OK
```

已确认：

- Backend / Worker 使用 `.env.production`
- Nginx 使用生产配置
- Nginx 配置 80 / 443
- TLS 通过变量挂载：
  - `TLS_CERT_PATH`
  - `TLS_KEY_PATH`
- Redis 配置 `requirepass`
- Redis healthcheck 使用密码校验
- PostgreSQL 使用生产变量：
  - `POSTGRES_DB`
  - `POSTGRES_ADMIN_USER`
  - `POSTGRES_ADMIN_PASSWORD`

## 7. .env.production 检查

服务器 `.env.production` 存在，权限为 `600`。

已确认存在变量键名：

```text
APP_ENV
DATABASE_URL
JWT_SECRET
POSTGRES_ADMIN_USER
POSTGRES_ADMIN_PASSWORD
POSTGRES_DB
REDIS_PASSWORD
REDIS_URL
TLS_CERT_PATH
TLS_KEY_PATH
```

未输出任何密钥值。

`DATABASE_URL` 解析结果：

```text
db_user=tiantong_app
db_host=postgres
db_name=tiantong_ai
```

## 8. PostgreSQL 权限检查

当前只读检查结果显示：

```text
postgres|superuser=true|createdb=true|createrole=true
```

未在当前检查输出中看到：

```text
tiantong_app
```

风险判断：

- `.env.production` 已配置后端使用 `tiantong_app`。
- 正式部署前必须确认生产 PostgreSQL 容器或目标数据库内存在 `tiantong_app`。
- `tiantong_app` 应为最小权限应用用户，不应具备 superuser / createdb / createrole。

正式部署前必须人工确认或安全创建：

```sql
SELECT rolname, rolsuper, rolcreatedb, rolcreaterole
FROM pg_roles
WHERE rolname = 'tiantong_app';
```

期望：

```text
rolsuper=false
rolcreatedb=false
rolcreaterole=false
```

## 9. Redis Requirepass 检查

生产 compose 已配置：

```text
redis-server --appendonly yes --requirepass
```

正式启动后验证命令：

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

## 10. 下一步执行计划

等待人工上传证书后，按顺序执行：

1. 确认证书文件：

   ```bash
   ls -l /root/tiantong-ai-cloud/certs/fullchain.pem
   ls -l /root/tiantong-ai-cloud/certs/privkey.pem
   ```

2. 验证证书域名：

   ```bash
   openssl x509 -in /root/tiantong-ai-cloud/certs/fullchain.pem -noout -subject -issuer -dates
   ```

3. 同步 GitHub main 最新配置到服务器。

4. 确认服务器 `nginx/production.conf` 已包含：

   ```nginx
   server_name cloud.tiantongai.com;
   ```

5. 验证 production compose：

   ```bash
   docker compose --env-file .env.production -f docker-compose.prod.yml config
   ```

6. 确认或创建最小权限 PostgreSQL 应用用户 `tiantong_app`。

7. 执行数据库备份。

8. 执行 migration。

9. 构建并启动生产服务。

10. 验证：

    ```bash
    curl -i https://cloud.tiantongai.com/api/health
    curl -i https://cloud.tiantongai.com/api/ready
    curl -I https://cloud.tiantongai.com/
    ```

## 11. 当前结论

当前可以继续：

- 上传 TLS 证书
- 同步本次 Nginx 域名配置
- 做 compose config 验证

当前不应执行：

- 正式启动公网 443
- 删除旧服务
- 跳过证书验证
- 跳过 PostgreSQL 最小权限用户确认

是否允许进入正式部署：

```text
暂不允许。等待 SSL 证书上传，并确认 tiantong_app 最小权限用户。
```
