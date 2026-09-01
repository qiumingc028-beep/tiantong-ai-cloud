# 天统京东只读采集客户端

每个店铺使用独立 Playwright persistent profile：`userData/stores/<store_id>`。用户在窗口中手工完成登录、验证码和风控操作；客户端不读取或导出 Cookie/Token。

采集器只允许白名单经营页面，非 GET 请求或写语义关键词请求都会计入 `BUSINESS_WRITE_BLOCKED` 并阻止上传。页面可见指标与白名单 JSON response 仅在内存中脱敏后上传 `/api/jd/capture`；云端接口拒绝未知字段并返回机器审计的 `business_write_count=0`。

构建：`npm install && npm run build`。真实验收前，将 `TIANTONG_API_BASE` 设置为内部云端地址，并为每家店铺分别执行一次 `capture-store`；不在命令行传入凭据。
