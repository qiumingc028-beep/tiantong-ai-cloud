# Sprint29.9 生产部署最终安全门

目标：在进入阿里云真实部署前，确认生产配置、部署文档和安全边界是否满足上线条件。

执行边界：

- 未执行 `git push`
- 未连接阿里云
- 未执行 Docker 部署
- 未修改业务代码

## 1. 当前上线条件

### 1.1 Git 状态

当前待提交文件：

- `docs/SPRINT29_7_DEPLOY_DRY_RUN_REPORT.md`
- `docs/SPRINT29_7_PRODUCTION_DEPLOY_PLAN.md`
- `docs/SPRINT29_8_GO_LIVE_FINAL_CHECK.md`
- `docs/SPRINT29_8_RELEASE_SUMMARY.md`
- `docs/SPRINT29_9_FINAL_SECURITY_GATE.md`

本地未跟踪但不应提交：

- `docs/SSH_FIX_REPORT.md`

当前注意事项：

- Sprint29.7 / Sprint29.8 / Sprint29.9 文档尚未提交。
- 提交前必须继续排除 `docs/SSH_FIX_REPORT.md`。
- 推送前必须确认目标分支为 `main`。

### 1.2 Docker 生产配置

已检查：

- `docker-compose.prod.yml` 可以使用 `.env.production.example` 模板渲染。
- PostgreSQL 未配置公网端口映射。
- Redis 未配置公网端口映射。
- backend 只 `expose` 8000，不公网发布。
- nginx 仅发布 80 / 443。
- Redis 启用 `--requirepass`。
- Redis healthcheck 使用密码。
- backend / worker 使用生产环境变量。

说明：

- 渲染结果中出现 `8000` 是 backend 内部 expose 和 Nginx 反代目标，不是公网 published 端口。

### 1.3 Nginx 生产配置

已检查：

- HTTP 跳 HTTPS。
- TLS 证书路径配置存在。
- HSTS 存在。
- `X-Content-Type-Options` 存在。
- `X-Frame-Options` 存在。
- 登录限流存在。
- API 基础限流存在。
- API 反代存在。
- 静态资源 fallback 存在。
- 隐藏文件访问禁止。

### 1.4 生产环境模板

已检查：

- `.env.production.example` 不包含真实密码。
- `.env.production.example` 不包含真实 token。
- `.env.production.example` 不包含真实 API Key。
- `.env.production.example` 不包含真实私钥。
- 所有敏感项均为占位符。
- `.env` 已被 `.gitignore` 忽略。
- `.env.production` 已被 `.gitignore` 忽略。

### 1.5 Release Summary

已检查：

- `docs/SPRINT29_8_RELEASE_SUMMARY.md` 存在。
- 内容覆盖：
  - Sprint29 阶段完成内容
  - 当前系统状态
  - 已通过检查
  - 未完成事项
  - 下一步部署计划

## 2. 阻断问题

当前发现的阻断项：

1. Sprint29.7 / Sprint29.8 / Sprint29.9 文档尚未提交。
2. 当前本地 Sprint29 文档提交尚未推送 GitHub main。
3. `docs/SSH_FIX_REPORT.md` 仍为本地未跟踪文件，必须继续排除。

这些阻断项不代表配置错误，但在进入阿里云部署前必须处理。

## 3. 可以上线项目

在完成提交、推送和人工确认后，以下项目具备上线条件：

- V1 backend 服务
- V1 worker 服务
- V1 nginx 前端入口
- PostgreSQL 容器服务
- Redis 容器服务
- 老板驾驶舱
- AI员工中心
- Task Center
- Execution Engine
- Brain / Orchestrator 相关只读与执行链路
- Archive Sync / Review / Evolution 等 V1 已验收模块

上线前仍需按 Runbook 验证：

- `/api/health`
- `/api/ready`
- 首页
- 老板驾驶舱
- Task Center
- AI员工中心
- 登录权限
- 日志安全

## 4. 不能上线项目

以下内容不得在本次直接上线或不得绕过确认：

1. 未提交到 GitHub main 的本地文档状态。
2. `docs/SSH_FIX_REPORT.md`。
3. 真实 `.env.production` 文件。
4. 未经老板确认的 Cookie Secure 风险。
5. 未完成备份的数据库。
6. 未创建低权限用户 `tiantong_app` 的 PostgreSQL 运行方式。
7. 未设置 Redis 密码的 Redis 运行方式。
8. 未准备 TLS 证书的 HTTPS 配置。
9. 任何开放 5432 / 6379 / 8000 到公网的安全组配置。
10. 任何跳过天检 / 天监 / 天盾流程的部署。

## 5. 老板确认清单

进入真实部署前，老板需要确认：

```text
[ ] 确认 Sprint29.7 / Sprint29.8 / Sprint29.9 文档可以提交
[ ] 确认 docs/SSH_FIX_REPORT.md 不进入 Git
[ ] 确认允许推送 GitHub main
[ ] 确认目标部署 commit
[ ] 确认目标 ECS
[ ] 确认部署窗口
[ ] 确认 .env.production 已人工准备
[ ] 确认 .env.production 无占位符
[ ] 确认 .env.production 权限为 600
[ ] 确认 PostgreSQL 已备份
[ ] 确认 tiantong_app 低权限用户已创建
[ ] 确认 Redis 密码已配置
[ ] 确认 TLS 证书已准备
[ ] 确认阿里云安全组未开放 5432 / 6379 / 8000
[ ] 确认 Cookie Secure 短期风险接受或已安排修复
[ ] 确认回滚方案
[ ] 确认正式部署失败时停止上线
```

## 6. 安全结论

Sprint29.9 最终安全门结论：

- 生产配置本身通过静态检查。
- 生产文档完整。
- 未发现真实密码、真实 token、真实 API Key、真实私钥。
- 当前不能直接进入部署，因为 Sprint29.7 / Sprint29.8 / Sprint29.9 文档尚未提交和推送。

建议下一步：

1. 提交 Sprint29.7 / Sprint29.8 / Sprint29.9 文档。
2. 继续排除 `docs/SSH_FIX_REPORT.md`。
3. 推送 GitHub main。
4. 老板确认目标 commit。
5. 再进入阿里云正式部署执行。
