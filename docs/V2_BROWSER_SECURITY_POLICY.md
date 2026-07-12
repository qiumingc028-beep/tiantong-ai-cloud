# V2 浏览器安全策略

## 1. 基本原则

浏览器只读执行器只允许访问公开网页。默认禁止所有可能产生写入、登录、会话持久化或内网探测的行为。

## 2. 允许范围

仅允许：

- `https://` 公网公开页面
- 白名单域名及其子域名
- 明确配置的开发 / 隔离测试域名

## 3. 默认禁止项

禁止访问：

- `localhost`
- `127.0.0.1`
- `0.0.0.0`
- `::1`
- 私有 IPv4 / IPv6
- 内网域名
- Docker 内部服务名
- 云 Metadata 地址
- `file://`
- `ftp://`
- `data:`
- `javascript:`
- `websocket`
- 本地路径
- 用户名 / 密码嵌入 URL

## 4. SSRF 防护

执行前必须校验：

1. 协议
2. 主机名
3. 域名白名单
4. DNS 解析结果
5. 私网地址
6. 重定向目标

任何一步不通过，立即拒绝执行。

## 5. 重定向规则

- 最大重定向次数：`BROWSER_MAX_REDIRECTS`
- 默认：`3`
- 禁止重定向到白名单外域名
- 禁止重定向到内网 / 私网 / Metadata
- 禁止无限重定向

## 6. 响应体与超时

- 默认超时：`20` 秒
- 默认最大响应体：`2,000,000` 字节
- 不允许无限制下载
- 不允许压缩炸弹

## 7. 内容提取

支持：

- HTML 标题
- HTML 正文文本
- HTML 表格 / 列表文本
- JSON Key Path
- CSS Selector（基础常见选择器）

不执行页面脚本，不保存 Cookie，不使用用户浏览器 Session。

## 8. 审计与脱敏

每次执行必须记录：

- 请求 URL
- 最终 URL
- 域名
- 页面标题
- 状态码
- 采集时间
- 内容 Hash
- 提取字段
- 任务 / 执行 / Trace 关联信息

脱敏要求：

- URL Query 中敏感参数必须脱敏
- `password` / `secret` / `token` / `cookie` / `authorization` / `private_key` 等字段不得明文进入审计

## 9. 员工授权

默认只允许 `天采`（`tiancai_data`）使用该能力。

其他员工默认无权限。

## 10. Feature Flag

- `BROWSER_READONLY_ENABLED=false`
- `BROWSER_CONTROL_ENABLED=false`

含义：

- `BROWSER_READONLY_ENABLED`：只读采集能力开关
- `BROWSER_CONTROL_ENABLED`：完整浏览器控制能力开关，仍然保持关闭

## 11. 失败策略

允许重试：

- 502
- 503
- 504
- 明确超时

禁止重试：

- URL 不允许
- 域名不允许
- 私有网络
- 401 / 403 / 404
- 不支持内容类型
- Schema 错误

## 12. 结论

浏览器只读执行器已按“默认关闭、白名单、低风险、可审计、可回写”原则完成基础策略。
