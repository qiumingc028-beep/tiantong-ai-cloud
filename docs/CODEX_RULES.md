# CODEX_RULES

## 基本原则

- 先读代码，再修改。
- 保持最小改动。
- 不回滚用户或其他阶段已有变更。
- 不修改无关模块。
- 不在文档或代码中写入真实 password、token、secret、API key。

## Git 规则

- 未经明确要求，不自动 push。
- 提交前必须确认 `git status`。
- 提交信息必须说明 Sprint 和变更主题。
- 发布同步与业务开发分开处理。

## 测试规则

后端改动通常需要：

- `git diff --check`
- Docker Python 环境下 `py_compile`
- 相关 pytest
- 全量 pytest

当前项目使用 Docker Python 3.12 作为主要测试环境。

## 安全规则

禁止新增：

- Shell 执行入口
- 自动部署入口
- 自动修改代码
- 自动修改权限
- 自动调用外部 API
- 自动安装未知插件
- 自动付款或投放
- 浏览器自动化

如必须引入真实工具：

1. 先做架构设计。
2. 经过天检验收。
3. 经过天监安全审计。
4. 经过天盾部署验证。

## 文档规则

每个 Sprint 完成后必须更新：

- `docs/PROJECT_STATUS.md`
- `docs/CHANGELOG.md`
- 必要时更新 `docs/ARCHITECTURE.md`
- 必要时更新 `docs/AI_EMPLOYEE_MAP.md`
- 重大决策写入 `docs/DECISION_LOG.md`

## Sprint 交接规则

标准顺序：

1. 天道：产品设计
2. 天工：架构设计
3. 天王：后端开发
4. 天颜：前端开发
5. 天检：测试验收
6. 天监：安全审计
7. 天盾：部署验证
8. 天藏：知识沉淀
