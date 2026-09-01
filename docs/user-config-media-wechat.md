# 用户配置说明：自媒体（MediaCrawler）与微信（Gewe）

两者均对最终用户「无感」底层细节：UI 只暴露平台勾选、关键词、启停；密钥与路径全部进 `.env`。

---

## 1. 自媒体 Tab（`/media`）

### 交互设计

1. 进入 **自媒体**（不与「AI 新闻」并列成多个平台 Tab）。
2. **平台矩阵**：勾选要采的平台（小红书 / 抖音 / 快手 / B 站 / 微博 / 贴吧 / 知乎）。
3. **关键词**：逗号分隔，与情报过滤标签可独立。
4. **开始抓取**：后台任务 + 进度条（本页轮询，不跳转「手动采集」）。
5. **结果列表**：落入统一 `IntelItem`（类型 `MEDIA_POST`），可收藏 / 忽略 / 进月报。

底层调用外部 [MediaCrawler](https://github.com/NanmiCoder/MediaCrawler) 进程；**源码不进本仓库**（gitignore）。

- **启动自动下载**：`ENABLE_MEDIA_CRAWLER=true` 且本地缺少 checkout 时，`bagel dev` 会先 `git clone`（仅首次）。
- **VPN**：默认拉 GitHub，国内常需代理或 `MEDIA_CRAWLER_GIT_URL` 镜像；失败不阻断主站。
- **已 `git add .` 报错**：按 [git-and-mediacrawler.md](./git-and-mediacrawler.md) 从索引移除即可。

也可手动：`uv run bagel setup-media`。详见 [third_party/README.md](../third_party/README.md)。
### 多平台与扫码登录（重要）

MediaCrawler **每次进程只支持一个** `--platform`。本系统勾选多个平台时会：

1. **按勾选顺序依次**启动独立进程（小红书 → B 站 → …）。
2. 某一平台失败（退出码非 0、CDP 连不上、扫码超时等）→ **跳过该平台**，继续下一个；任务结果为「部分完成」，并列出失败原因。
3. 进度条会显示 `[1/2] 小红书：等待扫码…`，避免长时间停在 0%。

`MEDIA_CRAWLER_LOGIN_TYPE=qrcode` 时：

| 问题 | 说明 |
|------|------|
| 二维码在哪？ | 在 **弹出的 Playwright 浏览器窗口**，或桌面二维码图片窗口；**不在** Bagel 网页里。日志应为 `Launching browser using standard mode`。 |
| 多平台怎么扫？ | 每个平台第一次通常要扫一次；登录态写在该平台的 `browser_data/*_user_data_dir`，下次同平台一般免扫。建议先只勾 1 个平台完成登录，再多选。 |
| 为何浏览器不弹窗、黄字像乱码？ | 常见原因：1) 未安装 Playwright Chromium；2) 从 Cursor 终端启动时继承了 `PLAYWRIGHT_BROWSERS_PATH=.../cursor-sandbox-cache/...`，指向空目录。适配层会清除该变量并尝试自动 `playwright install chromium`。 |
| 为何曾卡在 CDP/9222 且无二维码？ | CDP 模式会开 Chrome 调试口，子进程下常连不上。默认 `MEDIA_CRAWLER_ENABLE_CDP_MODE=false`，经 `bagel_entry.py` 强制 Playwright。 |

### `.env` 必填/可选

```env
ENABLE_MEDIA_CRAWLER=true
# 本机克隆的 MediaCrawler 根目录（勿提交到 git）
MEDIA_CRAWLER_PATH=./third_party/MediaCrawler
# 无 .venv 时的回退命令
MEDIA_CRAWLER_CMD=uv run main.py
# 默认平台（逗号分隔）：xhs,dy,ks,bili,wb,tieba,zhihu
MEDIA_CRAWLER_PLATFORMS=xhs,bili
MEDIA_CRAWLER_KEYWORDS=大模型,AI Agent,RAG
# 登录方式：qrcode | cookie | phone（以 MediaCrawler 为准）
MEDIA_CRAWLER_LOGIN_TYPE=qrcode
MEDIA_CRAWLER_MAX_NOTES=20
MEDIA_CRAWLER_CDP_CONNECT_EXISTING=false
MEDIA_CRAWLER_ENABLE_CDP_MODE=false
```

### 用户步骤

1. `uv run bagel setup-media`，再按提示在 MediaCrawler 目录安装依赖 / Playwright。
2. `.env` 填写 `MEDIA_CRAWLER_PATH`，`ENABLE_MEDIA_CRAWLER=true`，`MEDIA_CRAWLER_CDP_CONNECT_EXISTING=false`。
3. 打开 `/media`，**先勾一个平台** → 开始抓取 → 到弹出窗口扫码。
4. 登录成功后再勾多个平台批量抓；失败平台会跳过，看进度条旁的提示与服务端日志。

### 常见失败

- **退出码 1 + Connecting port 9222**：未开远程调试却 `CDP_CONNECT_EXISTING=true`。改为 `false` 后重试。
- **一直 running 0%**：旧版本用阻塞 `subprocess.run` 且无分平台进度；请使用当前适配层（按平台流式进度）。
- **未解析到帖子**：扫码未完成，或 `data/<platform>/jsonl/` 无输出。

---

## 2. 微信 Tab（`/wechat`）

### 为什么用 Gewe

自研个人微信协议风控极高。Gewe 提供 HTTP API + Webhook，本系统只做：

- 配置状态展示（Token / AppId 是否齐全）
- 关键词订阅（命中的会话摘要进情报流）
- Webhook 接收回调 → 标准化为 `IntelItem`（`WECHAT_MSG`）

### 交互设计

1. **连接状态**：已配置 / 未配置 / 最近回调时间。
2. **关键词订阅**：如 `大模型,招生,Agent`。
3. **消息流**：只读列表（脱敏展示），可「纳入候选」。
4. **测试**：调用 Gewe 发一条到文件传输助手（可选）。

### `.env`

```env
ENABLE_WECHAT=false
GEWE_ENABLED=false
GEWE_BASE_URL=http://api.geweapi.com/gewe/v2/api
GEWE_TOKEN=
GEWE_APP_ID=
# 本应用对外可访问的回调（Gewe 控制台填写）
GEWE_CALLBACK_URL=http://127.0.0.1:8000/api/wechat/webhook
GEWE_KEYWORDS=大模型,AI,Agent
```

### 用户步骤

1. 在 [Gewe](https://geweapi.com/) 注册，获取 Token，扫码登录拿 `appId`。
2. 控制台回调地址填 `GEWE_CALLBACK_URL`。
3. `.env` 写入 Token/AppId，`ENABLE_WECHAT=true`。
4. 打开 `/wechat` 确认「已连接」，设置关键词。
5. 用微信发测一条含关键词的消息，应出现在消息流。

### 风险声明

个人微信号第三方协议存在封号风险；请控制频率，仅用于私域情报，勿群发骚扰。
