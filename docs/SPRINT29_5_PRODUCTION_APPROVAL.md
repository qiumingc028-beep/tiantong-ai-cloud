# Sprint29.5 生产部署最终审批检查

目标：确认系统是否可以进入阿里云正式部署。

执行边界：

- 未连接服务器
- 未执行部署
- 未修改业务代码
- 未修改数据库

## A. 可以部署

### 1. Sprint29 文档完整

以下文档已存在：

- `docs/SPRINT29_DEPLOY_SECURITY_PLAN.md`
- `docs/SPRINT29_2_DEPLOY_CHECK_REPORT.md`
- `docs/SPRINT29_3_PRODUCTION_READY_CHECK.md`
- `docs/SPRINT29_4_PRODUCTION_DEPLOY_RUNBOOK.md`

本阶段新增最终审批文件：

- `docs/SPRINT29_5_PRODUCTION_APPROVAL.md`

### 2. 生产配置已准备

生产部署配置文件已准备：

- `.env.production.example`
- `docker-compose.prod.yml`
- `nginx/production.conf`
- `Dockerfile.frontend`

检查结论：

- `docker-compose.prod.yml` 可使用模板环境渲染。
- PostgreSQL 未暴露公网端口。
- Redis 未暴露公网端口。
- Redis 启用密码机制。
- Redis healthcheck 使用密码。
- backend / worker 读取生产环境变量。
- nginx 暴露 80 / 443。
- nginx 包含 HTTPS、安全 Header、API 限流和静态资源配置。

### 3. 密钥与敏感文件策略

检查结论：

- `.env` 被 `.gitignore` 忽略。
- `.env.production` 被 `.gitignore` 忽略。
- `.env.production.example` 不包含真实密钥。
- `docs/SSH_FIX_REPORT.md` 仍为本地未跟踪文件，应继续排除。
- Sprint29 配置和文档未发现真实私钥、真实 token、真实 API key。

### 4. 部署 Runbook 可执行

`docs/SPRINT29_4_PRODUCTION_DEPLOY_RUNBOOK.md` 已覆盖：

- ECS 环境检查
- Docker / Docker Compose 检查
- 磁盘空间检查
- 网络端口检查
- SSL 证书检查
- 域名解析检查
- Git 拉取
- 环境变量配置
- Docker 构建
- 数据库备份
- 数据库迁移
- 服务启动
- 健康检查
- 页面检查
- 权限检查
- 日志检查
- 回滚方案

## B. 必须人工确认

### 1. 数据库风险

必须确认：

- 生产 PostgreSQL 已创建低权限应用用户 `tiantong_app`。
- `tiantong_app` 只具备业务表和 sequence 的必要权限。
- `tiantong_app` 不具备：
  - Superuser
  - Create DB
  - Create Role
  - Replication
  - Bypass RLS
- `.env.production` 中 `DATABASE_URL` 使用 `tiantong_app`，不是 PostgreSQL 管理用户。
- 部署前已经完成数据库备份。

### 2. Redis 风险

必须确认：

- `.env.production` 中 `REDIS_PASSWORD` 是强随机值。
- `.env.production` 中 `REDIS_URL` 与 `REDIS_PASSWORD` 一致。
- 阿里云安全组未开放 6379。
- Redis 只在 Docker 内部网络中供 backend / worker 使用。

### 3. Nginx 风险

必须确认：

- `TLS_CERT_PATH` 指向有效 fullchain 证书。
- `TLS_KEY_PATH` 指向有效 private key。
- 证书文件存在于生产服务器。
- 证书未过期。
- 私钥文件没有进入 Git。
- 80 / 443 在阿里云安全组中开放。
- HTTP 到 HTTPS 跳转符合预期。

### 4. Docker 风险

必须确认：

- 生产部署使用：
  - `docker-compose.prod.yml`
  - `.env.production`
- 不使用开发 `docker-compose.yml` 对公网部署。
- PostgreSQL / Redis / backend 没有映射公网端口。
- Docker volume 不会被删除。
- 不执行 `docker volume rm`。
- 部署前记录旧镜像和旧 commit。

### 5. 权限风险

必须确认：

- owner / boss / admin 管理账号可登录。
- viewer 不能访问管理接口。
- 未登录 API 返回 401。
- 高风险执行路径仍需要老板确认和安全审计。
- 不跳过天检 / 天监 / 天盾流程。

### 6. 密钥风险

必须确认：

- `.env.production` 不包含 `<...>` 占位符。
- `.env.production` 权限为 `600`。
- `JWT_SECRET` 是强随机值，不是示例值。
- `POSTGRES_ADMIN_PASSWORD` 是强随机值。
- `REDIS_PASSWORD` 是强随机值。
- `ADMIN_RESET_PASSWORD` 如启用，必须一次性使用并轮换。
- 不在聊天、文档、日志、Git commit 中粘贴真实密钥。

## C. 暂缓事项

以下事项不阻塞受控生产部署，但建议在公网长期运行前排期：

1. Cookie Secure 后端配合
   - 当前 Nginx 已准备 HTTPS。
   - 后端仍需根据 `APP_ENV=production` 设置 cookie `secure=True`。
   - 建议作为部署后第一优先级小修。

2. 容器安全硬化
   - backend / worker 改为非 root 用户。
   - 开启只读 rootfs。
   - 最小化 Linux capabilities。

3. JWT 响应策略优化
   - 后续可考虑不在 response body 返回 JWT，仅使用 HttpOnly Secure Cookie。

4. 登录安全增强
   - 登录失败次数限制。
   - 临时锁定策略。
   - 审计日志查询。

5. Secret 管理升级
   - 阿里云 KMS / Secrets Manager。
   - Docker secrets。

6. WAF / CDN / SLB
   - 公网正式大规模访问前建议接入。

7. CSP
   - 需要先评估前端 inline script，再启用严格 CSP。

## D. 正式部署负责人确认项

正式部署前，负责人必须逐项确认：

```text
[ ] 当前 GitHub main commit 已确认
[ ] 生产服务器代码目录已确认
[ ] .env.production 已创建
[ ] .env.production 权限为 600
[ ] .env.production 无占位符
[ ] PostgreSQL 已备份
[ ] PostgreSQL tiantong_app 低权限用户已创建
[ ] DATABASE_URL 使用 tiantong_app
[ ] Redis 密码已配置
[ ] REDIS_URL 与 REDIS_PASSWORD 一致
[ ] TLS 证书路径正确
[ ] TLS 证书未过期
[ ] 阿里云安全组只开放必要端口
[ ] docker compose prod config 检查通过
[ ] 部署前旧 commit 已记录
[ ] 部署前旧镜像已记录或可回滚
[ ] 部署 Runbook 已阅读
[ ] 回滚方案已确认
[ ] 老板确认允许进入部署窗口
```

## 最终审批结论

Sprint29.5 生产部署最终审批检查结论：

- 当前配置和文档已具备进入阿里云正式部署的条件。
- 不允许跳过人工确认项直接部署。
- 通过人工确认后，可以进入 Sprint29 天盾正式部署执行阶段。
