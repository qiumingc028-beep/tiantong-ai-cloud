# Sprint29.18.4 TLS 证书补齐阶段报告

目标：完成 HTTPS 上线前准备检查，确认域名配置、SSL 证书申请方案、Nginx 证书引用路径、`fullchain.pem` / `privkey.pem` 加载流程，以及 Redis requirepass 生产验证方案。

执行边界：

- 未执行正式部署
- 未启动公网 HTTPS
- 未执行 `docker compose up`
- 未重启 Nginx
- 未删除数据
- 未修改业务代码

## 1. 当前域名配置情况

服务器当前 commit：

```text
03b4e652a66e1943b5775641cbf02df89f44aab0
```

Nginx 当前 production 配置：

```text
server_name _;
listen 443 ssl http2;
return 301 https://$host$request_uri;
```

项目配置检查：

```text
.env.production does not define APP_DOMAIN
nginx/production.conf uses server_name _
docker-compose.prod.yml does not define domain variable
```

当前端口状态：

```text
80:  listening
443: not listening
```

结论：

```text
PARTIAL
```

说明：

- 当前 Nginx 配置可接受任意 Host，但未绑定明确生产域名。
- 当前未启用 443。
- 正式上线前必须确认生产域名和 DNS 解析。

必须人工确认：

```text
[ ] 生产域名
[ ] DNS A 记录指向 ECS 公网 IP
[ ] 阿里云安全组允许 80 / 443
[ ] 是否接受 server_name _，或改为明确域名
```

## 2. SSL 证书申请方案

推荐方案：Let's Encrypt / Certbot。

### 2.1 HTTP-01 方案

前置条件：

- 域名 A 记录已指向 ECS。
- 80 端口公网可访问。
- 当前没有其他服务阻断 ACME challenge。

建议流程：

```bash
certbot certonly --standalone -d <domain>
```

或在 Nginx 已稳定后：

```bash
certbot certonly --webroot -w /usr/share/nginx/html -d <domain>
```

风险：

- standalone 模式可能需要临时占用 80 端口。
- webroot 模式需要 Nginx 正确提供 ACME challenge 路径。

### 2.2 DNS-01 方案

适用场景：

- 不想临时调整 80 端口。
- 需要申请泛域名证书。
- DNS 解析可由人工或插件管理。

建议流程：

```bash
certbot certonly --manual --preferred-challenges dns -d <domain>
```

风险：

- 需要人工添加 DNS TXT 记录。
- 续期需要重新处理或使用 DNS 插件。

### 2.3 不推荐方案

不建议用于正式生产：

- 自签名证书
- 过期证书
- 私钥无权限控制
- 将证书私钥提交到 Git

## 3. nginx production.conf 证书引用路径

当前 Nginx 容器内引用路径：

```text
/etc/nginx/certs/fullchain.pem
/etc/nginx/certs/privkey.pem
```

`docker-compose.prod.yml` 当前挂载方式：

```text
${TLS_CERT_PATH}:/etc/nginx/certs/fullchain.pem:ro
${TLS_KEY_PATH}:/etc/nginx/certs/privkey.pem:ro
```

服务器 `.env.production` 当前路径配置：

```text
TLS_CERT_PATH configured
TLS_KEY_PATH configured
```

服务器文件检查：

```text
TLS_CERT_PATH_EXISTS=False
TLS_KEY_PATH_EXISTS=False
```

当前目录：

```text
/root/tiantong-ai-cloud/certs
permission: 700
content: empty
```

结论：

```text
BLOCKED
```

说明：

- 引用路径和加载方式正确。
- 证书文件尚未准备。

## 4. fullchain.pem / privkey.pem 加载流程

目标文件：

```text
/root/tiantong-ai-cloud/certs/fullchain.pem
/root/tiantong-ai-cloud/certs/privkey.pem
```

建议加载流程：

1. 获取正式证书。
2. 复制或软链接证书到项目 certs 目录。
3. 设置目录和私钥权限。
4. 验证证书有效期。
5. 验证 production compose config。
6. 在正式部署时启动 Nginx。

建议命令模板：

```bash
cd /root/tiantong-ai-cloud
mkdir -p certs
chmod 700 certs

# 二选一：复制证书
cp /etc/letsencrypt/live/<domain>/fullchain.pem certs/fullchain.pem
cp /etc/letsencrypt/live/<domain>/privkey.pem certs/privkey.pem

# 或二选一：软链接证书
ln -sf /etc/letsencrypt/live/<domain>/fullchain.pem certs/fullchain.pem
ln -sf /etc/letsencrypt/live/<domain>/privkey.pem certs/privkey.pem

chmod 600 certs/privkey.pem
chmod 644 certs/fullchain.pem
openssl x509 -in certs/fullchain.pem -noout -dates -subject
```

验证命令：

```bash
PRODUCTION_ENV_FILE=.env.production \
docker compose --env-file .env.production -f docker-compose.prod.yml config --quiet
```

成功标准：

```text
fullchain.pem exists
privkey.pem exists
certificate is not expired
private key permission is restricted
compose config passes
```

注意：

- 不得将 `certs/privkey.pem` 提交到 Git。
- 不得把私钥内容写入文档或聊天记录。

## 5. Redis requirepass 生产验证方案

当前状态：

```text
production config contains REDIS_PASSWORD
production config contains redis-server --requirepass
current runtime Redis has no requirepass
```

说明：

- 当前 Redis 仍是旧运行态。
- 本阶段未重启 Redis，符合“不启动生产服务”的限制。
- requirepass 需在 Sprint29.19 production compose 启动后验证。

正式部署后的验证命令：

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
[ ] 检查 REDIS_PASSWORD 是否为空
[ ] 检查 REDIS_URL 是否包含密码
[ ] 检查 redis 容器是否使用 docker-compose.prod.yml 创建
[ ] 检查 backend / worker 是否使用 .env.production
[ ] 不允许无密码 Redis 对外上线
```

## 6. 当前阻塞项

阻塞正式部署的问题：

1. 未确认生产域名。
2. TLS 证书文件缺失。
3. 443 尚未监听。
4. Redis requirepass 尚未在 production runtime 验证。

已完成：

1. Nginx HTTPS 配置存在。
2. TLS 目录存在且权限为 700。
3. `.env.production` 已配置 TLS 路径。
4. production compose 证书挂载方式正确。
5. Redis requirepass 生产方案已明确。

## 7. 是否允许进入 Sprint29.19 正式部署

当前结论：

```text
不允许进入 Sprint29.19 正式部署。
```

原因：

- TLS 证书缺失。
- 生产域名未确认。
- Redis requirepass 尚未在 production runtime 验证。

允许进入下一步：

```text
Sprint29.18.5 域名和 TLS 证书落地阶段
```

进入 Sprint29.19 前必须完成：

```text
[ ] 确认生产域名
[ ] 确认 DNS 解析到 ECS
[ ] 准备 fullchain.pem
[ ] 准备 privkey.pem
[ ] 验证证书未过期
[ ] 验证私钥权限受限
[ ] 再次执行 production compose config
[ ] 老板确认部署窗口
```
