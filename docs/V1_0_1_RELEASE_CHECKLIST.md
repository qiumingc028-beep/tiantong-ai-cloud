# V1.0.1 Release Checklist

| 项目 | 结果 | 命令 |
| --- | --- | --- |
| Git 工作区审计 | 通过 | `git status --short --branch` |
| 敏感信息检查 | 通过 | `rg -n "SECRET|TOKEN|PASSWORD|API_KEY" ...` |
| 版本号检查 | 通过 | `cat VERSION` / `rg -n "1\\.0\\.1" README.md backend VERSION` |
| amd64 Wheelhouse | 通过 | `python3 scripts/build_wheelhouse.py --platform amd64 ...` |
| Backend Tests | 通过 | `docker run --rm --platform linux/amd64 --network none ... python -m pytest -q` |
| Frontend Validation | 通过 | 同上 |
| Python Import | 通过 | 同上 |
| Config Validation | 通过 | 同上 |
| Migration Upgrade | 通过 | `docker exec v101cand-backend-1 sh -lc 'alembic upgrade head'` |
| Migration Check | 通过 | `docker exec v101cand-backend-1 sh -lc 'alembic check'` |
| Static Security | 通过 | pytest 内安全测试覆盖 |
| Production Policy | 通过 | pytest 内生产配置测试覆盖 |
| Docker Production Validation | 通过 | amd64 候选栈构建与运行验证 |
| Health Check | 通过 | `curl -ksS https://127.0.0.1:18443/api/health` |
| Release Audit | 通过 | `pytest tests/test_release_center.py -q` |
| Release Notes | 通过 | `docs/RELEASE_NOTES_V1.0.1.md` |
| CHANGELOG | 通过 | `CHANGELOG.md` |
| Deploy 文档 | 通过 | `docs/DEPLOY.md` |
| Rollback 文档 | 通过 | `docs/ROLLBACK.md` |
| Git Commit | 待执行 | `git commit -m "release: TIANTONG AI Cloud V1.0.1 amd64 compatibility"` |
| Git Tag | 待执行 | `git tag -a v1.0.1 -m "TIANTONG AI Cloud V1.0.1 AMD64 Compatibility Patch"` |
