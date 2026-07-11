# 生产安全说明

## 基本要求

- 不提交真实生产 Secret。
- `.env.production` 只能保留在生产环境，不进入 Git。
- 生产 CORS 必须显式列出 origins，禁止 `*`。
- Debug 必须关闭。
- 默认凭证和 fallback secret 必须 fail-fast。

## 构建安全

- amd64 / arm64 依赖锁文件必须和目标平台一一对应。
- pip 安装必须使用 `--require-hashes`。
- 不允许静默回退到源码编译。

## 运行时安全

- 只允许使用经过验证的生产配置。
- 生产日志不得输出密钥、Token 或私钥。
- 不允许把生产备份、Secret 或数据库文件提交到 Git。
