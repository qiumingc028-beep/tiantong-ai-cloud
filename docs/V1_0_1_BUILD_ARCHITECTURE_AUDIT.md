# V1.0.1 Build Architecture Audit

## 结论

V1.0.1 的构建链路已改为平台显式选择：

- `Dockerfile.backend` 和 `Dockerfile.worker` 通过 `REQUIREMENTS_LOCK` 选择对应平台的 lock 文件。
- `docker-compose.prod.yml` 默认指向 amd64 lock，便于 linux/amd64 生产构建。
- arm64 路径仍可通过显式环境变量覆盖。

## 实际改动

- `VERSION`：`1.0.0 -> 1.0.1`
- `Dockerfile.backend`：从硬编码 arm64 lock 改为 build arg。
- `Dockerfile.worker`：同上。
- `docker-compose.prod.yml`：backend / worker build args 统一可配置。
- `backend/routers/release_center.py`：修复 Git worktree 下的 commit gate 误判。

## 兼容性说明

### amd64

推荐命令：

```bash
DOCKER_DEFAULT_PLATFORM=linux/amd64 \
REQUIREMENTS_LOCK=artifacts/wheelhouse/linux-amd64-cp312/requirements-linux-amd64-cp312.lock \
docker compose --env-file .env.production -f docker-compose.prod.yml up -d --build
```

### arm64

推荐命令：

```bash
DOCKER_DEFAULT_PLATFORM=linux/arm64 \
REQUIREMENTS_LOCK=artifacts/wheelhouse/linux-arm64-cp312/requirements-linux-arm64-cp312.lock \
docker compose --env-file .env.production -f docker-compose.prod.yml up -d --build
```

## 风险说明

- 如果宿主机平台和 `REQUIREMENTS_LOCK` 不匹配，pip 的 hash 校验会阻止错误平台 wheel 进入镜像。
- 这不是回退错误，而是正确的安全失败。
- 本机 arm64 宿主机上，强制将所有数据层服务都切到 amd64 会触发 qemu 不稳定；因此 amd64 生产验证优先针对 Backend / Worker / Frontend 镜像，数据层按本机稳定策略隔离验证。
