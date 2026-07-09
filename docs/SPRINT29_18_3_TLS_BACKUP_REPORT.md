# Sprint29.18.3 TLS 和数据库备份完成阶段报告

目标：完成正式部署最后安全条件检查，包括 Nginx HTTPS、TLS 证书目录、证书加载方式、Redis requirepass 生产方案、Redis 密码连接验证和 PostgreSQL 备份验证。

执行边界：

- 未执行正式上线
- 未执行 `docker compose up`
- 未启动生产服务
- 未执行数据库迁移
- 未删除数据
- 未修改业务代码

## 1. Nginx HTTPS 配置检查

检查文件：

```text
/root/tiantong-ai-cloud/nginx/production.conf
```

检查结果：

```text
listen 443 ssl http2 exists
ssl_certificate exists
ssl_certificate_key exists
Strict-Transport-Security exists
limit_req exists
proxy_pass exists
```

结论：

```text
PASS
```

说明：

- Nginx 生产配置已经具备 HTTPS 入口。
- 当前没有启动 production nginx，因此 443 尚未监听。

## 2. TLS 证书目录结构

已创建目录：

```text
/root/tiantong-ai-cloud/certs
```

目录权限：

```text
drwx------
```

结论：

```text
PASS
```

说明：

- TLS 证书目录结构已准备。
- 本阶段未上传或生成正式证书文件。

## 3. fullchain.pem / privkey.pem 加载方式检查

`.env.production` 中 TLS 路径已配置：

```text
TLS_CERT_PATH configured
TLS_KEY_PATH configured
```

`docker-compose.prod.yml` 中加载方式：

```text
${TLS_CERT_PATH}:/etc/nginx/certs/fullchain.pem:ro
${TLS_KEY_PATH}:/etc/nginx/certs/privkey.pem:ro
```

服务器文件检查：

```text
TLS_CERT_PATH_EXISTS=False
TLS_KEY_PATH_EXISTS=False
```

结论：

```text
BLOCKED
```

说明：

- 加载方式正确。
- 证书文件尚未准备。
- 正式部署前必须提供：
  - `/root/tiantong-ai-cloud/certs/fullchain.pem`
  - `/root/tiantong-ai-cloud/certs/privkey.pem`

## 4. Redis requirepass 生产方案

生产配置已具备：

```text
docker-compose.prod.yml contains REDIS_PASSWORD
docker-compose.prod.yml contains redis-server --requirepass
docker-compose.prod.yml contains password healthcheck
.env.production contains REDIS_PASSWORD
.env.production contains REDIS_URL
```

结论：

```text
CONFIG READY
```

说明：

- Redis requirepass 会在 production compose 启动 Redis 时生效。
- 本阶段未重启 Redis，因此当前运行态仍是旧配置。

## 5. Redis 密码连接测试

测试方式：

- 使用 `.env.production` 中的 `REDIS_PASSWORD`
- 对当前正在运行的旧 Redis 容器执行密码连接测试
- 不输出真实密码

测试结果：

```text
REDIS_AUTH_EXIT=0
REDIS_AUTH_STATUS=FAILED_CURRENT_RUNTIME_NO_REQUIREPASS
```

结论：

```text
EXPECTED BEFORE PRODUCTION RESTART
```

说明：

- 当前旧 Redis 运行态没有启用 requirepass。
- 使用密码连接当前旧 Redis 不代表生产配置失败。
- 正式部署切换到 `docker-compose.prod.yml` 后必须重新验证：

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml exec -T redis \
  redis-cli -a "$REDIS_PASSWORD" ping
```

成功标准：

```text
PONG
```

## 6. PostgreSQL 备份验证

已创建备份目录：

```text
/data/backups/tiantong-ai-cloud
```

已执行备份：

```text
/data/backups/tiantong-ai-cloud/backup_20260709_131650.sql
```

备份文件大小：

```text
344K
```

验证结果：

```text
BACKUP_NON_EMPTY
```

结论：

```text
PASS
```

说明：

- 数据库备份已生成。
- 备份文件非空。
- 本阶段未执行数据库恢复测试。

## 7. Production Compose 验证

验证命令：

```bash
PRODUCTION_ENV_FILE=.env.production \
docker compose --env-file .env.production -f docker-compose.prod.yml config --quiet
```

验证结果：

```text
COMPOSE_CONFIG_PASS
```

结论：

```text
PASS
```

## 8. 当前端口状态

检查结果：

```text
80:   public listening
443:  not listening
5432: localhost only
6379: localhost only
8000: localhost only
```

说明：

- 443 未监听，因为尚未启动 production nginx。
- 未发现 `5432` / `6379` / `8000` 公网监听。

## 9. 阻塞项

当前仍存在正式部署阻塞：

1. TLS 证书文件不存在：
   - `/root/tiantong-ai-cloud/certs/fullchain.pem`
   - `/root/tiantong-ai-cloud/certs/privkey.pem`
2. Redis requirepass 尚未在运行态验证，需等 production compose 启动后验证。
3. 当前 443 尚未监听。

## 10. 是否允许进入 Sprint29.19 正式部署

当前结论：

```text
不允许进入 Sprint29.19 正式部署。
```

原因：

- TLS 证书文件缺失会导致 production nginx 无法启动。

已满足：

- `.env.production` 已创建。
- `tiantong_app` 低权限用户已创建。
- production compose config 通过。
- PostgreSQL 备份已完成且非空。
- Redis requirepass 生产配置已具备。
- TLS 目录已创建。

进入 Sprint29.19 前必须完成：

```text
[ ] 准备 /root/tiantong-ai-cloud/certs/fullchain.pem
[ ] 准备 /root/tiantong-ai-cloud/certs/privkey.pem
[ ] 确认证书未过期
[ ] 确认私钥权限受限
[ ] 再次执行 production compose config
[ ] 老板确认部署窗口和回滚负责人
```

建议下一步：

```text
Sprint29.18.4 TLS 证书补齐阶段
```
