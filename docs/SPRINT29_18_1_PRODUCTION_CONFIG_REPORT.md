# Sprint29.18.1 生产环境配置阶段报告

目标：完成正式部署前生产配置检查，确认 `.env.production`、Docker Compose 变量、PostgreSQL 用户权限、Redis 密码、数据库备份目录和 Nginx HTTPS 前置条件。

执行边界：

- 未执行正式部署
- 未执行 `docker compose up`
- 未启动新服务
- 未执行数据库迁移
- 未删除数据
- 未修改业务代码

## 1. 服务器代码状态

服务器目录：

```text
/root/tiantong-ai-cloud
```

当前 commit：

```text
03b4e652a66e1943b5775641cbf02df89f44aab0
```

当前未跟踪文件：

```text
.env.save
.env.save.1
backend/ai_employees/tian_cai/
backend/ai_employees/tian_ce/
```

结论：

- 服务器代码已同步到 Sprint29.16 生产部署准备版本。
- 未跟踪旧文件未处理，正式部署前建议人工确认是否保留。

## 2. .env.production 模板检查流程

当前检查结果：

```text
.env.production: missing
.env.production.example: exists
```

`.env.production.example` 包含变量：

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

正式部署前必须执行的检查流程：

```bash
cd /root/tiantong-ai-cloud
cp .env.production.example .env.production
chmod 600 .env.production
grep -n '<.*>' .env.production && echo "ERROR: placeholder exists" || echo "OK: no placeholder"
```

注意：

- 上述 `cp` 仅为建议流程，本阶段尚未执行。
- `.env.production` 必须由老板或运维负责人填入真实生产值。
- 不得将 `.env.production` 提交 Git。

结论：

```text
BLOCKED: .env.production 尚未创建。
```

## 3. docker-compose.prod.yml 所需变量

从 `docker-compose.prod.yml` 检查到的必需变量：

```text
HTTPS_PORT
HTTP_PORT
POSTGRES_ADMIN_PASSWORD
POSTGRES_ADMIN_USER
POSTGRES_DB
PRODUCTION_ENV_FILE
REDIS_PASSWORD
TLS_CERT_PATH
TLS_KEY_PATH
```

同时 backend / worker 通过 `.env.production` 读取：

```text
APP_ENV
DATABASE_URL
REDIS_URL
JWT_SECRET
AI_PROVIDER
OPENAI_API_KEY
DEEPSEEK_API_KEY
ADMIN_RESET_PASSWORD
```

结论：

- Compose 变量设计完整。
- 当前服务器缺少真实 `.env.production`，因此不能渲染生产 compose 并正式启动。

## 4. PostgreSQL 用户权限检查

只读检查结果：

```text
postgres,t,t
tiantong,f,f
```

字段含义：

```text
username, is_superuser, can_create_db
```

当前状态：

- `postgres` 是超级用户。
- `tiantong` 不是超级用户。
- 目标生产应用用户 `tiantong_app` 尚未发现。

结论：

```text
BLOCKED: 正式生产 DATABASE_URL 设计要求使用 tiantong_app，当前用户尚未确认存在。
```

正式部署前要求：

```text
[ ] 创建或确认 tiantong_app
[ ] tiantong_app 不是 superuser
[ ] tiantong_app 不具备 CREATEDB 权限
[ ] DATABASE_URL 使用 tiantong_app
[ ] migration 使用受控管理员账号或明确审批流程
```

## 5. Redis 密码配置检查

当前运行 Redis 检查结果：

```text
requirepass
<empty>
```

含义：

- 当前运行中的 Redis 没有设置 `requirepass`。

生产配置检查结果：

```text
docker-compose.prod.yml contains REDIS_PASSWORD
docker-compose.prod.yml contains redis-server --requirepass
.env.production.example contains REDIS_PASSWORD
.env.production.example contains REDIS_URL
```

结论：

```text
BLOCKED: 当前运行 Redis 未启用密码；生产配置支持密码，但必须通过 .env.production 正式启用。
```

正式部署前要求：

```text
[ ] 设置 REDIS_PASSWORD
[ ] 设置 REDIS_URL=redis://:<REDIS_PASSWORD>@redis:6379/0
[ ] 使用 docker-compose.prod.yml 启动 Redis
[ ] 验证 redis-cli -a "$REDIS_PASSWORD" ping 返回 PONG
```

## 6. 数据库备份目录和备份方案

已创建备份目录：

```text
/data/backups/tiantong-ai-cloud
```

当前权限：

```text
drwxr-xr-x root root
```

说明：

- 本阶段只创建备份目录。
- 未执行数据库备份。
- 未导出数据。

建议备份命令：

```bash
cd /root/tiantong-ai-cloud
docker compose --env-file .env.production -f docker-compose.prod.yml exec -T postgres \
  pg_dump -U "$POSTGRES_ADMIN_USER" "$POSTGRES_DB" \
  > /data/backups/tiantong-ai-cloud/backup_$(date +%Y%m%d_%H%M%S).sql
ls -lh /data/backups/tiantong-ai-cloud
```

正式部署前要求：

```text
[ ] .env.production 已创建
[ ] PostgreSQL 容器可访问
[ ] 备份文件生成
[ ] 备份文件非空
[ ] 备份文件路径记录到部署日志
```

结论：

```text
PARTIAL: 备份目录已创建，正式备份尚未执行。
```

## 7. Nginx HTTPS 前置条件检查

代码配置检查结果：

```text
nginx/production.conf exists
listen 443 ssl http2 exists
ssl_certificate exists
ssl_certificate_key exists
Strict-Transport-Security exists
limit_req exists
proxy_pass exists
```

当前服务器状态：

```text
.env.production missing
TLS_CERT_PATH unknown
TLS_KEY_PATH unknown
443 not listening
```

结论：

```text
PARTIAL: Nginx HTTPS 代码配置已就绪，但服务器 TLS 文件和生产环境变量尚未确认。
```

正式部署前要求：

```text
[ ] TLS_CERT_PATH 指向有效 fullchain.pem
[ ] TLS_KEY_PATH 指向有效 privkey.pem
[ ] 证书未过期
[ ] 私钥权限受限
[ ] production compose 成功挂载证书
[ ] nginx 启动后 443 正常监听
```

## 8. 端口安全检查

当前只读检查结果：

```text
80:   0.0.0.0 / [::] docker-proxy listening
443:  not listening
5432: 127.0.0.1 / 127.0.1.1 only
6379: 127.0.0.1 / [::1] only
8000: 127.0.0.1 only
```

结论：

- 当前未发现 `5432` / `6379` / `8000` 公网监听。
- 443 尚未启用。
- 生产 HTTPS 上线前必须启用 443。

## 9. 是否允许进入 Sprint29.19 正式部署

当前结论：

```text
不允许进入 Sprint29.19 正式部署。
```

原因：

1. `.env.production` 尚未创建。
2. `tiantong_app` 低权限用户尚未确认存在。
3. 当前运行 Redis 未启用密码。
4. PostgreSQL 正式备份尚未执行。
5. TLS 证书路径尚未确认。
6. 443 尚未监听。

允许进入下一步：

```text
Sprint29.18.2 生产变量和数据库安全补齐阶段
```

下一步建议：

1. 人工创建 `.env.production`。
2. 创建或确认 `tiantong_app` 低权限 PostgreSQL 用户。
3. 配置 Redis 强密码。
4. 确认 TLS 证书路径。
5. 执行 PostgreSQL 备份。
6. 再次运行 production compose config。
