# Sprint29.18.6 生产域名确认和 TLS 证书落地报告

目标：完成正式部署前域名和证书准备检查，明确 Nginx `server_name` 修改点、生产域名接入要求、证书加载流程、证书文件要求和 Redis requirepass 生产启动验证方案。

执行边界：

- 未启动公网 443
- 未执行正式部署
- 未执行 `docker compose up`
- 未修改业务逻辑
- 未删除数据

## 1. 当前 Nginx production 配置

服务器当前 commit：

```text
03b4e652a66e1943b5775641cbf02df89f44aab0
```

检查文件：

```text
/root/tiantong-ai-cloud/nginx/production.conf
```

当前关键配置：

```text
line 5:  listen 80;
line 6:  server_name _;
line 7:  return 301 https://$host$request_uri;
line 11: listen 443 ssl http2;
line 12: server_name _;
line 17: ssl_certificate /etc/nginx/certs/fullchain.pem;
line 18: ssl_certificate_key /etc/nginx/certs/privkey.pem;
line 29: Strict-Transport-Security
```

结论：

```text
PARTIAL
```

说明：

- Nginx production 配置具备 HTTPS 能力。
- 当前 `server_name` 仍为 `_`，可作为默认服务接收请求。
- 正式生产建议将第 6 行和第 12 行改为明确生产域名。

## 2. server_name 需要修改的位置

建议修改位置：

```nginx
server {
    listen 80;
    server_name <production-domain>;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;
    server_name <production-domain>;
    ...
}
```

需要修改的行：

```text
nginx/production.conf line 6
nginx/production.conf line 12
```

是否必须修改：

- 如果老板接受默认 server：可短期保留 `_`。
- 如果正式公网域名上线：建议改为明确域名，便于安全审计、证书匹配和后续多域名管理。

当前未修改：

```text
本阶段只检查，不改配置。
```

## 3. 生产域名配置模板

建议新增生产域名变量：

```env
APP_DOMAIN=<production-domain>
PUBLIC_BASE_URL=https://<production-domain>
```

建议 Nginx 模板：

```nginx
server {
    listen 80;
    server_name <production-domain>;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;
    server_name <production-domain>;

    ssl_certificate /etc/nginx/certs/fullchain.pem;
    ssl_certificate_key /etc/nginx/certs/privkey.pem;
}
```

生产域名接入要求：

```text
[ ] 生产域名已确定
[ ] 域名备案/合规状态满足上线要求
[ ] DNS A 记录指向 ECS 公网 IP
[ ] 阿里云安全组允许 80 / 443
[ ] 阿里云安全组不开放 5432 / 6379 / 8000
[ ] 证书 CN/SAN 包含该域名
```

## 4. certs 目录权限和证书加载流程

服务器证书目录：

```text
/root/tiantong-ai-cloud/certs
```

当前权限：

```text
drwx------
```

当前内容：

```text
empty
```

`.env.production` TLS 路径：

```text
TLS_CERT_PATH=/root/tiantong-ai-cloud/certs/fullchain.pem
TLS_KEY_PATH=/root/tiantong-ai-cloud/certs/privkey.pem
```

`docker-compose.prod.yml` 加载方式：

```text
${TLS_CERT_PATH}:/etc/nginx/certs/fullchain.pem:ro
${TLS_KEY_PATH}:/etc/nginx/certs/privkey.pem:ro
```

结论：

```text
LOADING FLOW READY
```

说明：

- 目录权限合格。
- Compose 只读挂载方案合格。
- 证书文件尚未落地。

## 5. fullchain.pem 和 privkey.pem 要求

当前检查：

```text
TLS_CERT_PATH_EXISTS=False
TLS_KEY_PATH_EXISTS=False
FULLCHAIN_MISSING
PRIVKEY_MISSING
```

正式部署前必须准备：

```text
/root/tiantong-ai-cloud/certs/fullchain.pem
/root/tiantong-ai-cloud/certs/privkey.pem
```

文件要求：

```text
fullchain.pem:
  - PEM 格式证书链
  - 证书未过期
  - 证书域名匹配生产域名
  - 建议权限 644

privkey.pem:
  - PEM 格式私钥
  - 与 fullchain.pem 匹配
  - 不进入 Git
  - 不写入文档
  - 建议权限 600
```

证书落地后必须执行：

```bash
openssl x509 -in /root/tiantong-ai-cloud/certs/fullchain.pem -noout -subject -dates
openssl rsa -in /root/tiantong-ai-cloud/certs/privkey.pem -check -noout
ls -l /root/tiantong-ai-cloud/certs/fullchain.pem
ls -l /root/tiantong-ai-cloud/certs/privkey.pem
```

成功标准：

```text
certificate not expired
private key valid
private key permission restricted
```

## 6. Redis requirepass 生产启动验证方案

生产配置现状：

```text
docker-compose.prod.yml contains REDIS_PASSWORD
docker-compose.prod.yml contains redis-server --requirepass
docker-compose.prod.yml contains redis-cli -a healthcheck
.env.production contains REDIS_PASSWORD
.env.production contains REDIS_URL
```

当前运行态：

- 旧 Redis 仍在运行。
- 未切换 production compose。
- 本阶段不验证 runtime requirepass。

Sprint29.19 正式部署后验证命令：

```bash
cd /root/tiantong-ai-cloud
set -a
. ./.env.production
set +a
docker compose --env-file .env.production -f docker-compose.prod.yml exec -T redis \
  redis-cli -a "$REDIS_PASSWORD" ping
```

成功标准：

```text
PONG
```

失败时处理：

```text
[ ] 检查 REDIS_PASSWORD 是否为空
[ ] 检查 REDIS_URL 是否与 REDIS_PASSWORD 一致
[ ] 确认 Redis 容器来自 docker-compose.prod.yml
[ ] 确认 backend / worker 均读取 .env.production
[ ] 不允许无密码 Redis 上线
```

## 7. 当前端口状态

检查结果：

```text
80:   public listening
443:  not listening
5432: localhost only
6379: localhost only
8000: localhost only
```

结论：

- 443 尚未启用，符合本阶段“不启动公网 443”的限制。
- 未发现 `5432` / `6379` / `8000` 公网监听。

## 8. Production Compose 验证

验证命令：

```bash
PRODUCTION_ENV_FILE=.env.production \
docker compose --env-file .env.production -f docker-compose.prod.yml config --quiet
```

结果：

```text
COMPOSE_CONFIG_PASS
```

结论：

```text
PASS
```

## 9. 是否允许进入 Sprint29.19 正式部署

当前结论：

```text
不允许进入 Sprint29.19 正式部署。
```

阻塞项：

1. 生产域名尚未确认。
2. `server_name` 尚未替换为正式域名。
3. `fullchain.pem` 缺失。
4. `privkey.pem` 缺失。
5. 证书格式和有效期尚未验证。
6. Redis requirepass 尚未在 production runtime 验证。

已满足项：

1. Nginx HTTPS 配置存在。
2. certs 目录存在且权限为 `700`。
3. TLS 路径已在 `.env.production` 配置。
4. production compose config 通过。
5. Redis requirepass 生产配置存在。

建议下一步：

```text
Sprint29.18.7 生产域名确认、server_name 更新和证书文件落地
```

进入 Sprint29.19 前必须完成：

```text
[ ] 确认生产域名
[ ] 更新 nginx/production.conf 的 server_name
[ ] 准备 fullchain.pem
[ ] 准备 privkey.pem
[ ] 验证证书有效期
[ ] 验证私钥格式
[ ] 再次执行 production compose config
[ ] 老板确认部署窗口和回滚负责人
```
