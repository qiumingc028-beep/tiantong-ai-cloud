# Sprint29.18.2 生产安全配置补齐报告

目标：补齐正式部署前最后生产配置，检查 `.env.production`、PostgreSQL 最小权限用户、Redis requirepass、数据库备份方案、Nginx HTTPS/TLS 前置条件，并验证 production compose config。

执行边界：

- 未执行正式上线
- 未执行 `docker compose up`
- 未重启服务
- 未执行数据库迁移
- 未删除数据
- 未修改业务逻辑

## 1. .env.production 配置

执行结果：

```text
.env.production created
permission: 600
placeholder check: PASS
```

已生成并配置的变量：

```text
ADMIN_RESET_PASSWORD
AI_PROVIDER
APP_ENV
DATABASE_URL
DEEPSEEK_API_KEY
HTTPS_PORT
HTTP_PORT
JWT_SECRET
OPENAI_API_KEY
POSTGRES_ADMIN_PASSWORD
POSTGRES_ADMIN_USER
POSTGRES_DB
REDIS_PASSWORD
REDIS_URL
TLS_CERT_PATH
TLS_KEY_PATH
```

安全说明：

- 所有密码和密钥使用服务器侧随机生成。
- 本报告不记录任何真实密码、JWT、Redis 密码或数据库密码。
- `.env.production` 未提交 Git。

结论：

```text
PASS
```

## 2. docker-compose.prod.yml 所需变量检查

Compose 变量来源：

- `.env.production`
- `docker-compose.prod.yml`

验证命令：

```bash
PRODUCTION_ENV_FILE=.env.production docker compose --env-file .env.production -f docker-compose.prod.yml config
```

执行结果：

```text
COMPOSE_CONFIG_PASS
```

服务清单：

```text
postgres
redis
backend
worker
nginx
```

结论：

```text
PASS
```

## 3. PostgreSQL tiantong_app 最小权限用户

执行结果：

```text
POSTGRES_APP_USER_READY
```

当前用户权限检查：

```text
postgres,t,t
tiantong,f,f
tiantong_app,f,f
```

字段含义：

```text
username,is_superuser,can_create_db
```

已完成：

- `tiantong_app` 已存在。
- `tiantong_app` 不是 superuser。
- `tiantong_app` 不具备 CREATEDB。
- 已授予 public schema 现有表基础 CRUD 权限。
- 已授予 public schema 序列使用权限。
- 已设置 public schema 默认表和序列权限。

结论：

```text
PASS
```

## 4. Redis requirepass

当前运行 Redis 检查：

```text
requirepass
<empty>
```

当前运行态说明：

- 旧 Redis 容器当前未启用密码。
- 本阶段未重启 Redis，符合“不正式上线、不启动新服务”的限制。

生产配置检查：

```text
docker-compose.prod.yml contains REDIS_PASSWORD
docker-compose.prod.yml contains redis-server --requirepass
docker-compose.prod.yml contains password healthcheck
.env.production contains REDIS_PASSWORD
.env.production contains REDIS_URL
```

结论：

```text
PARTIAL
```

说明：

- 生产配置已具备 Redis requirepass。
- 当前运行 Redis 需等正式切换到 production compose 后才会启用密码。
- Sprint29.19 正式部署后必须验证：

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml exec -T redis redis-cli -a "$REDIS_PASSWORD" ping
```

## 5. 数据库备份目录和备份方案

备份目录：

```text
/data/backups/tiantong-ai-cloud
```

检查结果：

```text
directory exists
owner: root
```

备份脚本检查：

- `scripts/backup_db.sh` 存在。
- 但当前脚本默认读取 `.env`。
- 该脚本默认备份目录为项目内 `backups/`。
- 该脚本默认用户为 `tiantong`。

结论：

```text
PARTIAL
```

正式部署前建议不要直接使用旧默认脚本，而使用 production compose 命令：

```bash
cd /root/tiantong-ai-cloud
docker compose --env-file .env.production -f docker-compose.prod.yml exec -T postgres \
  pg_dump -U "$POSTGRES_ADMIN_USER" "$POSTGRES_DB" \
  > /data/backups/tiantong-ai-cloud/backup_$(date +%Y%m%d_%H%M%S).sql
ls -lh /data/backups/tiantong-ai-cloud
```

阻塞项：

- 本阶段尚未执行真实数据库备份。

## 6. Nginx HTTPS / TLS 前置条件

代码配置检查：

```text
nginx/production.conf exists
listen 443 ssl http2 exists
ssl_certificate exists
ssl_certificate_key exists
Strict-Transport-Security exists
limit_req exists
proxy_pass exists
```

`.env.production` 中 TLS 路径：

```text
TLS_CERT_PATH configured
TLS_KEY_PATH configured
```

服务器文件检查：

```text
TLS_CERT_MISSING:/root/tiantong-ai-cloud/certs/fullchain.pem
TLS_KEY_MISSING:/root/tiantong-ai-cloud/certs/privkey.pem
```

结论：

```text
BLOCKED
```

说明：

- Nginx HTTPS 配置已具备。
- `.env.production` 已配置 TLS 路径。
- 但证书文件尚不存在。
- 正式部署前必须上传或签发 TLS 证书。

## 7. 端口与当前服务状态

当前仍未执行 production compose。

已知状态：

```text
80:   public listening
443:  not listening
5432: localhost only
6379: localhost only
8000: localhost only
```

结论：

- 未发现 `5432` / `6379` / `8000` 公网监听。
- 443 尚未启用。

## 8. 风险清单

### 阻塞项

1. TLS 证书文件缺失。
2. 数据库正式备份尚未执行。
3. 当前运行 Redis 未启用 requirepass，需正式切换 production compose 后验证。

### 注意项

1. `scripts/backup_db.sh` 默认仍偏向旧 `.env` 流程，不建议作为本次生产备份入口。
2. 当前旧容器仍在运行，本阶段未重启。
3. 正式部署时 Redis 连接会从无密码切换为有密码，需重点验证 backend / worker。
4. `.env.production` 已生成真实密钥，只能保留在服务器，不得复制到 Git 或文档。

## 9. 是否允许进入 Sprint29.19 正式部署

当前结论：

```text
不允许进入 Sprint29.19 正式部署。
```

原因：

- TLS 证书文件尚未准备。
- 数据库备份尚未执行。
- Redis requirepass 尚未通过正式 production compose 运行态验证。

允许进入下一步：

```text
Sprint29.18.3 TLS 和数据库备份完成阶段
```

进入 Sprint29.19 前必须完成：

```text
[ ] 准备 /root/tiantong-ai-cloud/certs/fullchain.pem
[ ] 准备 /root/tiantong-ai-cloud/certs/privkey.pem
[ ] 确认证书未过期
[ ] 确认私钥权限受限
[ ] 使用 production compose 命令完成 PostgreSQL 备份
[ ] 确认备份文件非空
[ ] 再次执行 docker compose config
[ ] 老板确认部署窗口和回滚负责人
```
