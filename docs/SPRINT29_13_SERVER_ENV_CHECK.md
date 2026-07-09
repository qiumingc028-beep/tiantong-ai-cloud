# Sprint29.13 生产服务器环境检查报告

目标：在第一次正式部署前，对阿里云 ECS 生产环境进行只读环境检查。

执行边界：

- 未执行 `docker compose up`
- 未拉取代码
- 未执行数据库迁移
- 未启动生产服务
- 未修改业务代码
- 未修改服务器文件

## 1. 连接结果

目标服务器：

- `120.24.79.232`

本次尝试的 SSH 用户：

- `root`
- `ubuntu`

连接结果：

```text
root@120.24.79.232: Permission denied (publickey,password).
ubuntu@120.24.79.232: Permission denied (publickey,password).
```

结论：

- 当前 Codex 运行环境没有可用 SSH 凭据。
- 未进入阿里云服务器。
- 服务器侧环境检查未能实际执行。
- 需要老板通过阿里云 Workbench 执行下方只读命令，或提供已审批的 SSH Key / 用户名后再继续。

## 2. 待检查项目

由于 SSH 被拒绝，以下项目当前状态为待确认：

| 检查项 | 当前结果 | 说明 |
| --- | --- | --- |
| Docker 版本 | 未检查 | 需要服务器内执行 |
| Docker Compose 版本 | 未检查 | 需要服务器内执行 |
| Git 版本 | 未检查 | 需要服务器内执行 |
| Python 版本 | 未检查 | 需要服务器内执行 |
| Node 版本 | 未检查 | 需要服务器内执行 |
| 磁盘空间 | 未检查 | 需要服务器内执行 |
| 内存使用 | 未检查 | 需要服务器内执行 |
| 端口占用 | 未检查 | 需要服务器内执行 |
| 防火墙状态 | 未检查 | 需要服务器内执行 |
| Docker 服务状态 | 未检查 | 需要服务器内执行 |

## 3. Workbench 只读检查命令

请在阿里云 Workbench 登录服务器后执行以下命令。

### 3.1 基础身份与系统

```bash
whoami
hostname
date
timedatectl
uname -a
cat /etc/os-release
pwd
```

成功标准：

- 登录到目标生产服务器。
- 系统时间正常。
- 操作系统版本明确。

### 3.2 Docker 版本

```bash
docker --version
```

成功标准：

- 正常输出 Docker 版本。

缺失项判断：

- 如果提示 `command not found`，说明 Docker 未安装或未进入 PATH。
- 如果提示 permission denied，说明当前用户无 Docker 权限。

### 3.3 Docker Compose 版本

```bash
docker compose version
```

成功标准：

- 正常输出 Docker Compose v2 版本。

缺失项判断：

- 如果 `docker compose` 不存在，需要确认 Docker Compose v2 插件是否安装。

### 3.4 Git 版本

```bash
git --version
```

成功标准：

- 正常输出 Git 版本。

缺失项判断：

- 如果提示 `command not found`，部署前需要安装 Git 或改用已审批的代码同步方式。

### 3.5 Python 版本

```bash
python3 --version
```

成功标准：

- 正常输出 Python 版本。

说明：

- 生产应用主要在容器中运行，宿主机 Python 版本不是核心运行条件，但用于运维排查时仍应可用。

### 3.6 Node 版本

```bash
node --version
```

成功标准：

- 如果宿主机不构建前端，可以不强制要求 Node。
- 如果生产流程需要宿主机构建前端，应正常输出 Node 版本。

### 3.7 磁盘空间

```bash
df -h
docker system df
du -sh /data/apps/tiantong-ai-cloud 2>/dev/null || true
du -sh /data/backups/tiantong-ai-cloud 2>/dev/null || true
```

成功标准：

- 系统盘可用空间不少于 10GB。
- Docker 数据目录有足够空间构建新镜像。
- 备份目录存在或可创建。

阻断条件：

- 可用空间不足以保存数据库备份和新镜像。

### 3.8 内存使用

```bash
free -h
uptime
```

成功标准：

- 内存使用未接近耗尽。
- 系统负载正常。

阻断条件：

- 内存不足导致容器可能启动失败或频繁重启。

### 3.9 端口占用

```bash
ss -tulpn
```

成功标准：

- 允许公网入口：`80`、`443`
- 不应对公网暴露：`5432`、`6379`、`8000`

阻断条件：

- PostgreSQL、Redis 或 backend 端口暴露公网。
- 80 / 443 被非预期服务占用。

### 3.10 防火墙状态

```bash
ufw status 2>&1 || true
iptables -S 2>/dev/null | head -80 || true
```

成功标准：

- 防火墙状态明确。
- 仅开放生产必需入口。

说明：

- 阿里云安全组仍是主要边界，服务器内防火墙状态需要与安全组共同核对。

### 3.11 Docker 服务状态

```bash
systemctl is-active docker 2>&1 || true
systemctl status docker --no-pager 2>&1 | head -80 || true
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
```

成功标准：

- Docker 服务 active。
- 可以列出当前容器。
- 容器状态无持续 Restarting。

阻断条件：

- Docker 服务不可用。
- 当前容器异常重启。

## 4. 汇总判断

当前状态：

- Sprint29.13 服务器环境检查未完成。
- 原因是 SSH 登录被服务器拒绝。
- 当前不能确认服务器是否满足第一次正式部署条件。

必须补齐：

1. 通过阿里云 Workbench 执行本报告第 3 节命令。
2. 将输出结果反馈给天盾。
3. 确认 Docker、Compose、Git、磁盘、内存、端口、防火墙、Docker 服务均满足要求。
4. 再进入 Sprint29.14 正式部署前确认。

## 5. 是否允许继续部署

结论：暂不允许进入正式部署。

原因：

- 生产服务器环境检查没有实际完成。
- Docker / Compose / Git / 磁盘 / 内存 / 端口 / 防火墙 / Docker 服务状态均未确认。

下一步：

- 老板通过 Workbench 执行只读检查命令并反馈结果。
- 或提供已审批的 SSH 用户和 Key 后，由天盾重新执行 Sprint29.13 只读环境检查。
