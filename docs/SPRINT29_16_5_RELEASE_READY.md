# Sprint29.16.5 上线前代码状态整理报告

目标：整理天统AI V1 正式部署前代码与文档状态，确认可提交内容、剩余风险和进入 Sprint29.17 的条件。

执行边界：

- 未部署
- 未连接阿里云
- 未执行 `docker compose up`
- 未修改业务代码
- 未修改数据库

## A. Git 状态

当前分支：

```text
main
```

本次整理包含两类变更：

1. Sprint29 生产部署文档。
2. Sprint29.15 生产部署配置修复。

已处理：

- `docs/SSH_FIX_REPORT.md` 已加入 `.gitignore`。
- `docs/SSH_FIX_REPORT.md` 不进入 Git 提交。
- `.env` 和 `.env.production` 仍被 `.gitignore` 排除。

## B. 提交文件

计划提交文件：

```text
.gitignore
deploy.sh
deploy/tiantong-api.service
deploy/tiantong-worker.service
docs/SPRINT29_7_DEPLOY_DRY_RUN_REPORT.md
docs/SPRINT29_7_PRODUCTION_DEPLOY_PLAN.md
docs/SPRINT29_8_GO_LIVE_FINAL_CHECK.md
docs/SPRINT29_8_RELEASE_SUMMARY.md
docs/SPRINT29_9_FINAL_SECURITY_GATE.md
docs/SPRINT29_10_PRODUCTION_DEPLOY_EXECUTION.md
docs/SPRINT29_11_PRE_DEPLOY_CHECK.md
docs/SPRINT29_12_FIRST_DEPLOY_PLAN.md
docs/SPRINT29_13_SERVER_ENV_CHECK.md
docs/SPRINT29_14_SSH_SETUP_PLAN.md
docs/SPRINT29_14_DEPLOY_AUDIT_REPORT.md
docs/SPRINT29_15_PRODUCTION_CONFIG_FIX.md
docs/SPRINT29_16_DEPLOY_DRY_RUN_REPORT.md
docs/SPRINT29_16_5_RELEASE_READY.md
```

不提交文件：

```text
docs/SSH_FIX_REPORT.md
.env
.env.production
```

## C. 上线前剩余风险

### C1. 生产服务器接入

- SSH 认证链路仍未由 Codex 验证成功。
- 需要通过 Workbench 或已审批 SSH Key 完成服务器只读检查。

### C2. 生产环境变量

- 真实 `.env.production` 尚未在服务器侧确认。
- `.env.production` 必须无 `<...>` 占位符。
- `.env.production` 权限应为 `600`。

### C3. 数据库

- 正式 migration 前必须完成 PostgreSQL 备份。
- 需要确认 `tiantong_app` 低权限用户存在。
- 禁止未备份直接执行 migration。

### C4. Redis

- 需要确认 Redis 强密码已配置。
- 需要确认 `REDIS_URL` 使用带密码连接。

### C5. TLS / Nginx

- 需要确认 TLS 证书路径存在。
- 需要确认证书未过期。
- 需要确认私钥权限受限。

### C6. 安全组

- 需要确认公网只开放 `80` / `443` 和受控 SSH / Workbench。
- 禁止开放 `5432` / `6379` / `8000` 到公网。

## D. 是否允许进入 Sprint29.17

当前结论：允许进入 Sprint29.17 正式部署准备，但不允许跳过人工确认直接部署。

进入 Sprint29.17 前必须确认：

```text
[ ] 本次提交已推送 GitHub main
[ ] docs/SSH_FIX_REPORT.md 未提交
[ ] 目标 ECS 已确认
[ ] 生产 .env.production 已准备
[ ] 数据库备份方案已确认
[ ] TLS 证书已确认
[ ] Redis 密码已确认
[ ] PostgreSQL 低权限用户已确认
[ ] 阿里云安全组已确认
[ ] 回滚负责人已确认
```

建议提交信息：

```text
Sprint29.16 production deployment preparation
```
