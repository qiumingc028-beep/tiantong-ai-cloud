# V2 Skill Manifest Spec

日期：2026-07-12

## 1. 目的

Skill Manifest 是 Skill 的声明式元数据，用于在安装和调用前进行静态校验。

## 2. 必填字段

- `skill_code`
- `version`
- 中文名称
- 中文说明
- `entrypoint`
- `skill_type`
- `risk_level`
- `required_capabilities`
- `required_permissions`
- `allowed_employee_types`
- `input_schema`
- `output_schema`
- `timeout_seconds`
- `max_retries`
- `network_access`
- `filesystem_access`
- `browser_access`
- `computer_access`
- `mobile_access`
- `shell_access`
- `secrets_required`
- `audit_required`

## 3. 校验规则

必须满足：

- skill code 唯一
- 版本格式合法
- schema 合法
- 能力声明完整
- 权限声明明确
- 超时和重试有限
- 入口可解析
- 访问权限必须显式声明

禁止：

- 任意入口
- 任意文件路径
- 任意 Shell 命令
- 任意网络访问
- 未声明 Secret
- 无限超时
- 无限重试

## 4. 安全默认值

- 第三方 Skill 默认禁止
- 未签名 Skill 默认禁止
- 自动更新默认禁止
- 生产环境默认关闭

## 5. 与 Capability 的关系

Skill 不直接实现底层操作，只能声明依赖的 Capability，由 Skills Engine 与 Agent Runtime 共同完成解析和执行。
