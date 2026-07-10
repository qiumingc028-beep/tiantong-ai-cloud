# 天统AI云中台 V1.0.0 回滚方案

## 1. 适用场景

当 V1.0.0 出现以下问题时使用本方案：

- 服务启动失败。
- 登录异常。
- Boss Dashboard 无法访问。
- AI员工中心无法访问。
- Task Center 核心流程异常。
- 数据库迁移或连接异常。
- Redis 或 worker 异常。
- Nginx 代理异常。

## 2. 回滚原则

- 先保护数据，再回滚代码。
- 先确认故障范围，再执行操作。
- 不直接删除历史报告。
- 不直接删除数据库。
- 不直接清空 Redis。
- 不绕过审批执行高风险动作。

安全边界：

```text
readonly=true
boss_confirm=true
security_audited=true
```

## 3. 回滚前检查

记录当前状态：

```bash
git status
git rev-parse --short HEAD
git tag --points-at HEAD
docker compose ps
docker compose logs --tail=100 backend
docker compose logs --tail=100 worker
docker compose logs --tail=100 nginx
curl -fsS http://127.0.0.1/api/health
curl -fsS http://127.0.0.1/api/ready
```

备份数据库：

```bash
scripts/backup_db.sh
ls -lh backups/
```

确认备份成功后再继续。

## 4. 恢复代码

### 4.1 回到 V1.0.0 tag

如果当前故障发生在 V1.0.0 之后，回到 V1.0.0：

```bash
git fetch --tags
git checkout v1.0.0
```

如需创建恢复分支：

```bash
git checkout -b rollback/v1.0.0
```

### 4.2 回到上一稳定 commit

如果 V1.0.0 本身不可用，回到上一稳定 commit：

```bash
git log --oneline --decorate -20
git checkout <stable_commit>
```

注意：

- 不使用 `git reset --hard` 删除用户未备份改动。
- 如工作区有未提交文件，先归档或另建分支处理。

## 5. 恢复部署

### 5.1 Docker Compose 部署

本地开发环境：

```bash
cp .env.example .env
docker compose config
docker compose up -d --build
docker compose ps
```

生产环境：

```bash
./deploy.sh
docker compose --env-file .env.production -f docker-compose.prod.yml ps
```

检查日志：

```bash
docker compose logs --tail=100 backend
docker compose logs --tail=100 worker
docker compose logs --tail=100 nginx
```

### 5.2 systemd 部署

```bash
DEPLOY_MODE=systemd ./deploy.sh
sudo systemctl status tiantong-api --no-pager -l
sudo systemctl status tiantong-worker --no-pager -l
sudo nginx -t
sudo systemctl reload nginx
```

## 6. 数据库恢复

如果只是应用代码异常，不要回滚数据库。

如果数据库出现误迁移或数据损坏：

1. 停止写入流量。
2. 确认最近备份文件。
3. 由负责人确认恢复窗口。
4. 执行恢复。

Docker 示例：

```bash
docker compose stop backend worker nginx
gunzip -c backups/<backup_file>.sql.gz | docker compose exec -T postgres psql -U "${POSTGRES_USER:-tiantong}" -d "${POSTGRES_DB:-tiantong_ai}"
docker compose up -d backend worker nginx
```

恢复后检查：

```bash
curl -fsS http://127.0.0.1/api/health
curl -fsS http://127.0.0.1/api/ready
```

## 7. Redis 恢复

普通异常优先重启：

```bash
docker compose restart redis
docker compose logs --tail=100 redis
```

不要默认清空 Redis。

如必须清空队列，需要：

```text
boss_confirm=true
security_audited=true
```

并记录原因、影响范围和执行人。

## 8. 服务检查

执行：

```bash
scripts/healthcheck.sh
CHECK_DOCKER_INFRA=1 scripts/healthcheck.sh
```

检查页面：

```text
/
/login.html
/index.html
/ai-workforce.html
/ai-employee-detail.html
/task-center.html
/orchestrator.html
```

检查 API：

```text
/api/health
/api/ready
/api/me
/api/owner/dashboard
/api/ai-workforce/overview
/api/task-center/tasks
```

## 9. 回滚后验证

运行核心测试：

```bash
python -m pytest tests/test_auth.py
python -m pytest tests/test_ceo_dashboard.py tests/test_task_center.py
python -m pytest tests/test_ai_workforce.py tests/test_ai_employee_detail.py tests/test_ai_employee_detail_frontend.py
```

如需 Docker Python 3.12：

```bash
docker run --rm \
  -v "$PWD:/app" \
  -w /app \
  -e DATABASE_URL=sqlite:///./test.db \
  -e REDIS_URL=redis://redis:6379/0 \
  -e JWT_SECRET=tiantong-test-secret-32-bytes-minimum \
  tiantong-ai-cloud-backend \
  python -m pytest tests/test_auth.py tests/test_ceo_dashboard.py tests/test_task_center.py tests/test_ai_workforce.py tests/test_ai_employee_detail.py tests/test_ai_employee_detail_frontend.py
```

## 10. 回滚完成标准

满足以下条件后可标记回滚完成：

- 登录正常。
- Boss Dashboard 正常。
- AI员工中心正常。
- AI员工详情正常。
- Task Center 正常。
- `/api/health` 正常。
- `/api/ready` 正常。
- PostgreSQL 正常。
- Redis 正常。
- Worker 正常。
- 核心测试通过。

标记：

```text
V1 ROLLBACK COMPLETE = YES
```
