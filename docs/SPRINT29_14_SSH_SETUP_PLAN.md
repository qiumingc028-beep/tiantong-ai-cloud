# Sprint29.14 生产服务器 SSH 接入方案

目标：解决 Sprint29.13 中 Codex 无法通过 SSH 连接阿里云 ECS 的问题，为后续只读检查和正式部署建立安全、可审计的接入方式。

执行边界：

- 不修改服务器
- 不创建用户
- 不上传 SSH Key
- 不执行 SSH 命令
- 不部署应用
- 不修改业务代码

## 1. 当前 SSH 失败原因分析

### 1.1 已观察到的现象

Sprint29.13 中尝试连接：

```text
root@120.24.79.232: Permission denied (publickey,password).
ubuntu@120.24.79.232: Permission denied (publickey,password).
```

### 1.2 可能原因

当前失败最可能由以下原因之一导致：

1. Codex 本地环境没有目标服务器认可的私钥。
2. 服务器未为 `root` 或 `ubuntu` 配置对应公钥。
3. 服务器禁止密码登录，且没有匹配的 SSH Key。
4. 服务器实际登录用户不是 `root` 或 `ubuntu`。
5. 阿里云安全组或服务器防火墙限制了 SSH 来源。
6. sshd 配置禁用了 root 登录。
7. Workbench 能登录，但本地 SSH Key 未同步到服务器。

### 1.3 当前结论

- 当前不是应用部署问题。
- 当前不是 Docker / 数据库 / Nginx 问题。
- 当前阻断点是生产服务器的 SSH 认证链路未建立。
- 在 SSH 接入方案确认前，不应继续执行自动化部署。

## 2. 推荐部署用户方案

### 2.1 推荐用户

建议创建专用部署用户：

```text
deploy
```

不建议使用：

- `root` 作为日常部署用户
- 个人临时账号作为长期部署用户
- 无审计标识的共享账号

### 2.2 用户职责

`deploy` 用户仅用于：

- 拉取 GitHub main
- 执行 Docker Compose 部署命令
- 查看 Docker 服务状态和日志
- 执行 Alembic migration
- 执行健康检查

`deploy` 用户不应默认拥有：

- 修改系统级 sshd 配置的权限
- 修改数据库文件目录权限的权限
- 删除 Docker volume 的权限
- 修改防火墙和安全组的权限

### 2.3 推荐目录权限

项目目录：

```text
/data/apps/tiantong-ai-cloud
```

建议：

- 目录 owner：`deploy`
- 目录 group：`deploy` 或受控运维组
- 生产 `.env.production` 权限：`600`
- TLS 私钥权限：只允许 root 或 nginx 容器挂载只读访问

## 3. SSH Key 配置方案

### 3.1 Key 类型

推荐使用：

```text
ed25519
```

不建议：

- 使用无 passphrase 的长期私钥
- 使用个人主力私钥直接绑定生产服务器
- 将私钥提交到 Git 仓库
- 在聊天窗口、文档或日志中粘贴私钥

### 3.2 本地生成 Key 的建议命令

由老板或运维负责人在本地安全环境执行：

```bash
ssh-keygen -t ed25519 -C "tiantong-ai-prod-deploy" -f ~/.ssh/tiantong_ai_prod_deploy
```

生成后会得到：

```text
~/.ssh/tiantong_ai_prod_deploy
~/.ssh/tiantong_ai_prod_deploy.pub
```

安全要求：

- 只上传 `.pub` 公钥。
- 私钥 `.ssh/tiantong_ai_prod_deploy` 不得上传服务器、不得提交 Git。
- 私钥建议设置 passphrase。

### 3.3 服务器 authorized_keys 配置

通过阿里云 Workbench 登录后，由老板或运维负责人为 `deploy` 用户添加公钥。

参考命令：

```bash
sudo mkdir -p /home/deploy/.ssh
sudo chmod 700 /home/deploy/.ssh
sudo touch /home/deploy/.ssh/authorized_keys
sudo chmod 600 /home/deploy/.ssh/authorized_keys
sudo chown -R deploy:deploy /home/deploy/.ssh
```

然后将本地 `.pub` 公钥内容追加到：

```text
/home/deploy/.ssh/authorized_keys
```

注意：

- 只追加公钥，不追加私钥。
- 每个部署负责人建议使用独立公钥。
- 离职、设备丢失或授权结束后应移除对应公钥。

### 3.4 本地 SSH 配置建议

本地 `~/.ssh/config` 可配置：

```sshconfig
Host tiantong-prod
  HostName <ECS_PUBLIC_IP>
  User deploy
  IdentityFile ~/.ssh/tiantong_ai_prod_deploy
  IdentitiesOnly yes
  ServerAliveInterval 30
  ServerAliveCountMax 3
```

连接测试命令：

```bash
ssh tiantong-prod 'whoami && hostname && date'
```

成功标准：

```text
deploy
<server-hostname>
<server-date>
```

## 4. sudo 权限方案

### 4.1 推荐原则

部署用户 `deploy` 不应获得无限制 root 权限。

推荐：

- 默认不允许无密码 sudo。
- 仅为必要命令配置有限 sudo。
- 高风险命令保留人工审批。

### 4.2 需要 sudo 的典型场景

可能需要 sudo 的操作：

- 查看 Docker 服务状态
- 重启 Docker 服务
- 调整项目目录 owner
- 读取 TLS 证书路径权限

不建议由 `deploy` 直接执行：

- 修改 sshd 配置
- 修改系统防火墙
- 删除 `/var/lib/docker`
- 删除 Docker volume
- 修改数据库数据目录

### 4.3 最小 sudo 建议

如果部署用户已加入 `docker` 组，则日常部署不需要 sudo 执行 Docker。

如果必须配置 sudo，建议通过 `/etc/sudoers.d/tiantong-deploy` 控制，人工审查后再启用。

示例方向：

```text
deploy 可查看 systemctl status docker
deploy 可执行 docker compose
deploy 不可执行 rm -rf /var/lib/docker
deploy 不可直接修改 sshd_config
```

说明：

- 具体 sudoers 配置应由运维负责人在服务器上人工编写并审查。
- 不建议在应用仓库保存真实 sudoers 文件。

## 5. Docker 权限方案

### 5.1 推荐方式

将 `deploy` 加入 `docker` 组：

```bash
sudo usermod -aG docker deploy
```

生效方式：

- 退出重新登录。
- 或重新打开 Workbench / SSH 会话。

验证命令：

```bash
id deploy
docker ps
docker compose version
```

成功标准：

- `id deploy` 输出包含 `docker` 组。
- `docker ps` 可以正常执行。
- `docker compose version` 正常输出。

### 5.2 Docker 权限风险

重要说明：

- Docker 组权限接近 root。
- 只有可信部署用户才能加入 Docker 组。
- 禁止给普通 AI 员工账号、viewer 账号或临时账号授予 Docker 权限。

### 5.3 Docker 操作边界

允许：

- `docker ps`
- `docker compose config`
- `docker compose build`
- `docker compose up -d`
- `docker compose logs`
- `docker compose exec` 只读排查命令

高风险，需要人工确认：

- `docker compose down`
- `docker volume rm`
- `docker system prune`
- `docker compose down -v`
- 删除数据库 volume

## 6. 安全检查清单

### 6.1 接入前确认

```text
[ ] 确认目标 ECS 正确
[ ] 确认部署用户为 deploy 或等效专用用户
[ ] 确认不使用 root 作为日常部署用户
[ ] 确认 SSH Key 为独立部署 Key
[ ] 确认只上传公钥
[ ] 确认私钥不进入 Git
[ ] 确认私钥不写入文档
[ ] 确认阿里云安全组限制 SSH 来源
```

### 6.2 服务器侧确认

```text
[ ] /home/deploy/.ssh 权限为 700
[ ] authorized_keys 权限为 600
[ ] authorized_keys owner 为 deploy
[ ] deploy 用户可登录
[ ] deploy 用户具备必要 Docker 权限
[ ] deploy 用户无不必要 root 权限
[ ] root 密码登录禁用或受控
[ ] sshd 配置变更已备份
```

### 6.3 部署前确认

```text
[ ] deploy 可进入 /data/apps/tiantong-ai-cloud
[ ] deploy 可执行 git status
[ ] deploy 可执行 docker ps
[ ] deploy 可执行 docker compose version
[ ] deploy 可读取必要项目文件
[ ] deploy 不可读取不应访问的系统敏感文件
[ ] .env.production 权限为 600
[ ] TLS 私钥未暴露给无关用户
```

### 6.4 审计与回收

```text
[ ] 每个部署 Key 有明确负责人
[ ] 不再使用的 Key 已移除
[ ] 部署操作有日志
[ ] 安全组变更有记录
[ ] sudoers 变更有记录
[ ] Docker 高风险操作需要人工确认
```

## 7. 推荐执行顺序

建议由老板或运维负责人通过阿里云 Workbench 人工执行：

1. 确认当前可登录用户。
2. 创建或确认 `deploy` 用户。
3. 配置 `deploy` 的 `.ssh/authorized_keys`。
4. 将 `deploy` 加入 `docker` 组。
5. 重新登录验证 `deploy`。
6. 执行只读检查：
   - `whoami`
   - `hostname`
   - `docker ps`
   - `docker compose version`
   - `git --version`
7. 将检查结果反馈给天盾。
8. 重新进入 Sprint29.13 服务器环境检查。

## 8. 当前结论

当前不建议继续自动化部署。

原因：

- SSH 认证链路尚未建立。
- Codex 无法进入服务器执行只读环境检查。
- Docker、磁盘、端口、防火墙、服务状态仍未确认。

允许下一步：

- 老板通过 Workbench 按本方案配置专用部署用户和 SSH Key。
- 或继续使用 Workbench 手动执行 Sprint29.13 的只读检查命令。

禁止下一步：

- 在未确认 SSH 和部署用户权限前执行正式部署。
- 使用 root 长期作为日常部署用户。
- 将私钥写入仓库、文档或聊天记录。
