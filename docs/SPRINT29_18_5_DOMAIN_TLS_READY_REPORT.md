# Sprint29.18.5 域名和 TLS 正式落地准备报告

目标：完成 HTTPS 上线前的域名、TLS、Nginx 证书加载、Redis requirepass 切换方案和上线 Checklist 检查。

执行边界：

- 未执行正式部署
- 未启动公网 443
- 未执行 `docker compose up`
- 未修改业务逻辑
- 未删除数据

## 1. 当前 server_name 配置

服务器检查结果：

```text
server_name _;
listen 443 ssl http2;
return 301 https://$host$request_uri;
```

结论：

```text
PARTIAL
```

说明：

- 当前 `nginx/production.conf` 使用 `server_name _`，可以作为默认 server 接收请求。
- 正式生产更建议改为明确域名，例如 `server_name example.com;`。
- 本阶段未修改 Nginx 配置。

上线前人工确认：

```text
[ ] 生产域名已确定
[ ] DNS A 记录已指向 ECS 公网 IP
[ ] 是否接受 server_name _
[ ] 如不接受，需在下一阶段修改 server_name 为正式域名
```

## 2. 生产域名接入要求

正式上线前必须满足：

```text
[ ] 域名已备案或符合当前地区访问要求
[ ] DNS A 记录指向生产 ECS
[ ] HTTP 80 可从公网访问
[ ] HTTPS 443 已在阿里云安全组放行
[ ] SSH / Workbench 仅可信来源访问
[ ] 5432 / 6379 / 8000 不对公网开放
```

建议验证命令：

```bash
dig <domain>
curl -I http://<domain>
curl -k -I https://<domain>
```

当前状态：

```text
生产域名未在项目配置中确认。
```

## 3. Nginx 证书加载流程

当前容器内引用路径：

```text
/etc/nginx/certs/fullchain.pem
/etc/nginx/certs/privkey.pem
```

production compose 加载方式：

```text
${TLS_CERT_PATH}:/etc/nginx/certs/fullchain.pem:ro
${TLS_KEY_PATH}:/etc/nginx/certs/privkey.pem:ro
```

服务器 `.env.production` 路径：

```text
TLS_CERT_PATH configured
TLS_KEY_PATH configured
```

服务器当前证书目录：

```text
/root/tiantong-ai-cloud/certs
permission: 700
content: empty
```

结论：

```text
LOADING FLOW READY, CERT FILES MISSING
```

## 4. fullchain.pem 和 privkey.pem 格式检查

检查结果：

```text
TLS_CERT_PATH_FILE_EXISTS=False
TLS_KEY_PATH_FILE_EXISTS=False
CERT_FORMAT_NOT_CHECKED_MISSING_FILE
KEY_FORMAT_NOT_CHECKED_MISSING_FILE
```

结论：

```text
BLOCKED
```

原因：

- `fullchain.pem` 不存在。
- `privkey.pem` 不存在。
- 无法执行证书有效期和私钥格式检查。

证书准备后必须执行：

```bash
openssl x509 -in /root/tiantong-ai-cloud/certs/fullchain.pem -noout -subject -dates
openssl rsa -in /root/tiantong-ai-cloud/certs/privkey.pem -check -noout
ls -l /root/tiantong-ai-cloud/certs/fullchain.pem
ls -l /root/tiantong-ai-cloud/certs/privkey.pem
```

成功标准：

```text
fullchain.pem exists
privkey.pem exists
certificate not expired
private key valid
private key permission restricted
```

## 5. Redis requirepass 生产切换方案

生产配置检查结果：

```text
docker-compose.prod.yml contains REDIS_PASSWORD
docker-compose.prod.yml contains redis-server --requirepass
docker-compose.prod.yml contains redis-cli -a healthcheck
.env.production.example contains REDIS_PASSWORD
.env.production.example contains REDIS_URL
```

当前说明：

- Redis requirepass 需要通过 production compose 启动后生效。
- 本阶段未重启 Redis。
- 当前旧 Redis 运行态不代表生产配置。

Sprint29.19 部署后验证命令：

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

失败处理：

```text
[ ] 检查 REDIS_PASSWORD
[ ] 检查 REDIS_URL
[ ] 检查 Redis 容器是否由 docker-compose.prod.yml 创建
[ ] 检查 backend / worker 是否读取 .env.production
```

## 6. HTTPS 上线 Checklist

进入 HTTPS 上线前必须确认：

```text
[ ] 生产域名已确认
[ ] DNS 解析已指向 ECS
[ ] 阿里云安全组开放 80 / 443
[ ] 阿里云安全组不开放 5432 / 6379 / 8000
[ ] fullchain.pem 已存在
[ ] privkey.pem 已存在
[ ] 证书未过期
[ ] 私钥权限受限
[ ] .env.production 中 TLS_CERT_PATH 正确
[ ] .env.production 中 TLS_KEY_PATH 正确
[ ] docker compose prod config 通过
[ ] production nginx 启动后 443 监听
[ ] HTTP 自动跳转 HTTPS
[ ] /api/health 返回 200
[ ] /api/ready 返回 200
[ ] 登录系统正常
[ ] viewer 无越权
[ ] Redis requirepass 验证 PONG
```

## 7. 当前验证结果

已完成：

```text
nginx production config exists
listen 443 ssl http2 configured
TLS env paths configured
certs directory exists
certs directory permission 700
production compose config PASS
Redis requirepass production config exists
```

未完成：

```text
production domain not confirmed
fullchain.pem missing
privkey.pem missing
443 not listening
Redis requirepass runtime verification pending
```

## 8. 是否允许进入 Sprint29.19 正式部署

当前结论：

```text
不允许进入 Sprint29.19 正式部署。
```

原因：

- 生产域名未确认。
- TLS 证书文件缺失。
- 443 尚未监听。
- Redis requirepass 尚未在 production runtime 验证。

允许进入下一步：

```text
Sprint29.18.6 生产域名确认和证书文件落地
```

进入 Sprint29.19 前必须完成：

```text
[ ] 确认生产域名
[ ] 准备 fullchain.pem
[ ] 准备 privkey.pem
[ ] 验证证书格式和有效期
[ ] 验证 production compose config
[ ] 老板确认部署窗口和回滚负责人
```
