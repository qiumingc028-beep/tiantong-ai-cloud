# V2 Skill Security Policy

日期：2026-07-12

## 1. 原则

Skill 必须可审计、可撤销、可追溯。任何高风险能力都不能绕过权限、审批和运行时。

## 2. 安全边界

- 不允许 Skill 直接执行 Shell
- 不允许 Skill 直接操作电脑/手机
- 不允许 Skill 直接控制真实浏览器
- 不允许 Skill 直接访问未声明网络
- 不允许 Skill 读取 Secret
- 不允许 Skill 修改权限或自升级

## 3. 审批要求

必须审批的情况：

- 第三方 Skill
- 网络访问 Skill
- 文件写入 Skill
- 浏览器控制 Skill
- 电脑控制 Skill
- 手机控制 Skill
- Shell Skill
- 数据库写入 Skill
- 财务 / 法务 / 高风险 Skill

## 4. 调用防护

校验顺序：

1. Skill 是否已安装
2. Skill 是否已启用
3. 员工是否有权限
4. Capability 是否满足
5. Feature Flag 是否开启
6. 风险等级是否允许
7. 审批状态是否满足
8. 是否存在脱敏要求
9. 是否已进入 Agent Runtime

## 5. 审计要求

每次调用都必须记录：

- Skill
- 版本
- 员工
- 任务
- 执行记录
- 风险等级
- 审批记录
- Trace ID
- 输入/输出摘要

禁止在日志中保存：

- 密码
- Token
- Cookie
- Secret
- 私钥
- 完整认证信息

## 6. 默认关闭项

- `THIRD_PARTY_SKILLS_ENABLED=false`
- `UNSIGNED_SKILLS_ENABLED=false`
- `AUTO_SKILL_UPDATE_ENABLED=false`
- `SKILL_MARKETPLACE_ENABLED=false`
- `SKILLS_ENGINE_ENABLED=false`

## 7. 结论

Skills Engine 只允许受控、最小权限、可审计的技能调用，且生产默认关闭。
