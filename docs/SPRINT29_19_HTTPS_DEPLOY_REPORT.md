# Sprint29.19 HTTPS 正式部署报告

## 1. 部署目标

为天统AI云中台启用正式 HTTPS 域名：

```text
https://cloud.tiantongai.com
```

本次仅处理生产部署配置和 Nginx 接入层，不修改业务代码，不删除文件，不改变数据库结构。

## 2. 已完成操作

### SSL 证书上传

已上传：

```text
/root/tiantong-ai-cloud/certs/fullchain.pem
/root/tiantong-ai-cloud/certs/privkey.pem
```

权限：

```text
fullchain.pem 644
privkey.pem   600
certs/        700
```

证书验证：

```text
subject=CN = cloud.tiantongai.com
issuer=C = US, O = DigiCert Inc, OU = www.digicert.com, CN = Encryption Everywhere DV TLS CA - G2
notBefore=Jul  9 00:00:00 2026 GMT
notAfter=Oct  6 23:59:59 2026 GMT
SAN=DNS:cloud.tiantongai.com, DNS:www.cloud.tiantongai.com
```

私钥验证：

```text
RSA key ok
```

### Nginx 生产配置

已同步服务器：

```text
/root/tiantong-ai-cloud/nginx/production.conf
```

关键配置：

```nginx
server_name cloud.tiantongai.com;
listen 443 ssl http2;
ssl_certificate /etc/nginx/certs/fullchain.pem;
ssl_certificate_key /etc/nginx/certs/privkey.pem;
```

### Production Compose 检查

执行结果：

```text
PROD_COMPOSE_CONFIG_OK
```

已确认：

- `.env.production` 存在。
- `TLS_CERT_PATH` 指向 `certs/fullchain.pem`。
- `TLS_KEY_PATH` 指向 `certs/privkey.pem`。
- Redis production compose 配置 `requirepass`。
- PostgreSQL `tiantong_app` 用户存在，且不是 superuser / createdb / createrole。

### Nginx 接入层启动

执行范围：

- 只重建并重启 `nginx` 接入层。
- 未重建 backend。
- 未重建 worker。
- 未重建 postgres。
- 未重建 redis。
- 未执行数据库结构变更。

当前容器状态：

```text
backend   Up healthy
nginx     Up healthy, 80/443 listening
postgres  Up healthy
redis     Up healthy
worker    Up
```

## 3. 验证结果

### 端口

当前端口状态：

```text
80   listening
443  listening
5432 localhost only
6379 localhost only
8000 localhost only
```

### HTTPS 页面

```text
https://cloud.tiantongai.com/
HTTP/2 200
```

### Health

```text
https://cloud.tiantongai.com/api/health
HTTP/2 200
```

返回状态：

```text
database=true
redis=true
worker=true
```

### Ready

```text
https://cloud.tiantongai.com/api/ready
HTTP/2 200
```

### 安全 Header

已返回：

```text
Strict-Transport-Security
X-Content-Type-Options
X-Frame-Options
Referrer-Policy
Permissions-Policy
```

## 4. 发现的问题

### HTTP 80 访问异常

外部访问：

```text
http://cloud.tiantongai.com/
```

当前返回：

```text
HTTP/1.1 403 Forbidden
Server: Beaver
```

源站 Nginx 日志中可见 301 记录，但外部 HTTP 返回被 `Beaver` 层拦截或处理。

影响：

- HTTPS 正常。
- API health / ready 正常。
- 不阻塞 HTTPS 上线。

建议：

- 后续检查阿里云边缘代理、WAF、安全策略或 HTTP 流量转发设置。
- 当前正式访问建议直接使用 `https://cloud.tiantongai.com`。

### Nginx HTTP/2 配置提示

Nginx 日志提示：

```text
the "listen ... http2" directive is deprecated, use the "http2" directive instead
```

影响：

- 当前不影响启动。
- 当前不影响 HTTPS 访问。

建议：

- 后续维护窗口可将配置调整为新版 Nginx 写法。

## 5. Git 与服务器状态

服务器当前有部署配置变更：

```text
M nginx/production.conf
?? certs/
```

说明：

- `nginx/production.conf` 是本次生产域名配置。
- `certs/` 为生产证书目录，不应提交 Git。

本次未提交代码，未推送 Git。

## 6. 结论

Sprint29.19 HTTPS 正式部署结果：

```text
PASS
```

当前可访问地址：

```text
https://cloud.tiantongai.com
```

已满足：

- HTTPS 443 已启动。
- 正式证书有效。
- Nginx healthy。
- Backend health 200。
- Ready 200。
- PostgreSQL 正常。
- Redis 正常。
- Worker 正常。

暂缓优化：

- HTTP 80 外部 403 / Beaver 返回排查。
- Nginx `listen ... http2` deprecated warning 后续调整。
