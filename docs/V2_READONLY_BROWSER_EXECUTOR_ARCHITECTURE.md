# V2 只读浏览器执行器架构说明

## 1. 目标

本 Sprint 建立“公开网页只读采集”的统一执行底座，支持 AI 员工在受控条件下读取公开网页、提取结构化文本并回写 Task Center。

本能力只做只读采集，不登录、不提交表单、不上传文件、不保存 Cookie、不控制真实浏览器会话。

## 2. 架构分层

执行链路：

AI 员工
→ Agent Runtime
→ 能力注册表
→ 权限与风险判断
→ 浏览器策略校验
→ 只读浏览器执行器
→ 内容提取与脱敏
→ 审计日志
→ Task Center 回写

禁止任何模块绕过 Agent Runtime 直接访问浏览器或网络。

## 3. 后端模块边界

新增后端模块：

- `backend/agent_runtime/executors/browser/executor.py`
- `backend/agent_runtime/executors/browser/policy.py`
- `backend/agent_runtime/executors/browser/extractor.py`
- `backend/agent_runtime/executors/browser/sanitizer.py`
- `backend/agent_runtime/executors/browser/schemas.py`
- `backend/agent_runtime/executors/browser/exceptions.py`

核心职责：

- `policy.py`：URL、域名、私网、重定向、协议白名单校验。
- `executor.py`：执行只读 HTTP 采集、控制超时、控制响应体大小、汇总结果。
- `extractor.py`：HTML / JSON 文本提取与结构化字段提取。
- `sanitizer.py`：URL Query 脱敏、正文截断、内容 Hash。
- `schemas.py`：采集输入、响应和 HTML 结构的轻量数据结构。

## 4. 能力定义

新增能力：

- 能力标识：`browser.public.read`
- 中文名称：公开网页读取
- 能力类型：浏览器操作
- 风险等级：低风险
- 只读：是
- 是否需要老板审批：否
- 是否需要安全审计：是
- 默认启用：否
- 默认执行器：`browser`
- 默认授权员工：`tiancai_data`

能力输入：

- URL
- 采集目标
- 提取字段
- 最大页面大小
- 超时时间
- 是否允许重定向

能力输出：

- 最终 URL
- 页面标题
- 状态码
- 提取文本
- 结构化字段
- 来源列表
- 采集时间
- 内容 Hash
- 执行耗时

## 5. 特性开关

新增配置：

- `BROWSER_READONLY_ENABLED=false`
- `BROWSER_CONTROL_ENABLED=false`
- `BROWSER_ALLOW_HTTP=false`
- `BROWSER_ALLOWED_DOMAINS=`
- `BROWSER_BLOCK_PRIVATE_NETWORKS=true`
- `BROWSER_MAX_REDIRECTS=3`
- `BROWSER_DEFAULT_TIMEOUT_SECONDS=20`
- `BROWSER_MAX_RESPONSE_BYTES=2000000`
- `BROWSER_USER_AGENT=TiantongAIReadonlyBrowser/1.0`

生产环境默认：

- 只读浏览器关闭
- 完整浏览器控制关闭

## 6. 数据回写

浏览器只读执行成功后，可通过现有 `Task Center` 任务链路回写执行摘要。

回写内容应只包含：

- 来源 URL
- 页面标题
- 摘要
- 结构化字段摘要
- 执行结果

不得写入：

- Cookie
- Token
- 密码
- 私钥
- 认证头

## 7. 未来扩展边界

本 Sprint 只建立稳定底座，不接入：

- Playwright
- OpenClaw
- Browser Use
- Desktop / Mobile 控制
- Shell 执行

未来如果接入真实浏览器控制，必须：

1. 先扩展策略层
2. 再扩展执行器层
3. 再升级审批与审计
4. 最后才允许在隔离环境中启用

## 8. 验收状态

本 Sprint 完成后，浏览器只读执行器、能力注册、权限判断、Task Center 回写、审计记录、页面展示与测试都已打通。
