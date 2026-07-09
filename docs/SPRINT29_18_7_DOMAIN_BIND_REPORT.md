# Sprint29.18.7 生产域名绑定报告

## 1. 执行边界

- 本阶段只做生产域名确认和 HTTPS 上线前检查。
- 未修改业务代码。
- 未启动正式 443。
- 未删除任何配置。
- 未执行生产部署。

## 2. 当前 Nginx 生产配置检查

检查文件：

- 本地：`nginx/production.conf`
- 服务器：`/root/tiantong-ai-cloud/nginx/production.conf`

当前关键配置：

```nginx
server_name _;
listen 443 ssl http2;
ssl_certificate /etc/nginx/certs/fullchain.pem;
ssl_certificate_key /etc/nginx/certs/privkey.pem;
add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
```

检查结论：

- HTTP 与 HTTPS server block 当前均使用 `server_name _`。
- HTTPS 证书引用路径已经预留。
- 生产证书文件尚未落地。
- 服务器 `certs/` 目录已存在，权限为 `700`。
- 当前 443 未监听，符合“未正式启用 HTTPS”的阶段要求。

## 3. 正式生产域名确认状态

当前正式生产域名：待老板确认。

在正式域名确认前，不建议修改：

- `nginx/production.conf` 的 `server_name`
- 证书申请域名
- DNS 解析记录
- HTTPS 强制跳转策略

## 4. 域名绑定修改清单

老板确认正式生产域名后，需要修改：

1. `nginx/production.conf`

   将 HTTP block 与 HTTPS block 中的：

   ```nginx
   server_name _;
   ```

   修改为：

   ```nginx
   server_name <production-domain>;
   ```

2. 如需同时支持 `www`，需明确是否配置：

   ```nginx
   server_name <production-domain> www.<production-domain>;
   ```

3. 确认 `.env.production` 是否需要增加或同步公开访问域名变量，例如：

   - `APP_DOMAIN`
   - `PUBLIC_BASE_URL`

   当前阶段不强制新增，避免影响现有运行配置。

4. 证书文件不得提交 Git。

5. 修改后必须执行：

   ```bash
   docker compose --env-file .env.production -f docker-compose.prod.yml config
   ```

6. 正式上线前必须验证：

   ```bash
   nginx -t
   ```

## 5. DNS 解析要求

正式域名确认后，需要在域名 DNS 控制台配置：

| 记录类型 | 主机记录 | 记录值 | 说明 |
| --- | --- | --- | --- |
| A | `<production-domain>` | `120.24.79.232` | 指向阿里云 ECS 公网 IP |
| CNAME 或 A | `www` | `<production-domain>` 或 `120.24.79.232` | 仅在需要 www 访问时配置 |

DNS 要求：

- 域名必须已完成备案或满足云厂商访问要求。
- TTL 建议先设置为较短值，便于上线调整。
- DNS 生效后需验证：

  ```bash
  dig <production-domain>
  nslookup <production-domain>
  ```

安全组要求：

- 80：允许公网访问，用于 HTTP 跳转和证书校验。
- 443：正式 HTTPS 上线时允许公网访问。
- 5432：不得公网开放。
- 6379：不得公网开放。
- 8000：不得公网开放。

## 6. SSL 证书申请流程

推荐流程：

1. 老板确认正式生产域名。
2. 配置 DNS A 记录到 `120.24.79.232`。
3. 等待 DNS 生效。
4. 选择证书申请方式：

   - 推荐：DNS-01，适合避免中断现有服务。
   - 可选：HTTP-01，需要 80 可访问，并确保校验路径可正常响应。

5. 证书落地到服务器：

   ```text
   /root/tiantong-ai-cloud/certs/fullchain.pem
   /root/tiantong-ai-cloud/certs/privkey.pem
   ```

6. 文件权限建议：

   ```bash
   chmod 700 /root/tiantong-ai-cloud/certs
   chmod 644 /root/tiantong-ai-cloud/certs/fullchain.pem
   chmod 600 /root/tiantong-ai-cloud/certs/privkey.pem
   ```

7. 证书验证：

   ```bash
   openssl x509 -in /root/tiantong-ai-cloud/certs/fullchain.pem -noout -subject -issuer -dates
   openssl rsa -in /root/tiantong-ai-cloud/certs/privkey.pem -check -noout
   ```

8. Nginx 配置验证：

   ```bash
   docker compose --env-file .env.production -f docker-compose.prod.yml config
   nginx -t
   ```

## 7. Redis Requirepass 生产验证

Redis 生产密码机制已在生产配置方案中预留。正式部署后需要验证：

```bash
set -a
. ./.env.production
set +a
docker compose --env-file .env.production -f docker-compose.prod.yml exec -T redis redis-cli -a "$REDIS_PASSWORD" ping
```

期望结果：

```text
PONG
```

## 8. 上线前域名配置 Checklist

- [ ] 老板确认正式生产域名。
- [ ] 确认是否需要 `www` 域名。
- [ ] DNS A 记录指向 `120.24.79.232`。
- [ ] 阿里云安全组确认 80 / 443 策略。
- [ ] 5432 / 6379 / 8000 不公网开放。
- [ ] SSL 证书申请完成。
- [ ] `fullchain.pem` 和 `privkey.pem` 已放入 `certs/`。
- [ ] 证书权限符合要求。
- [ ] `nginx/production.conf` 的 `server_name` 已替换正式域名。
- [ ] `docker compose config` 通过。
- [ ] `nginx -t` 通过。
- [ ] HTTPS 页面访问通过。
- [ ] HTTP 自动跳转 HTTPS 验证通过。

## 9. 当前结论

当前不建议直接进入 Sprint29.19 正式部署。

阻断项：

- 正式生产域名尚未确认。
- DNS 解析尚未配置。
- TLS 证书尚未落地。
- `server_name` 仍为 `_`。
- 443 当前未监听。

允许的下一步：

1. 老板确认正式生产域名。
2. 配置 DNS 解析。
3. 完成 TLS 证书申请与文件落地。
4. 再进入 Sprint29.19 正式部署前检查。
