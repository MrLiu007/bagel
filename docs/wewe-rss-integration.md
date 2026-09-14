# WeWe-RSS 集成设计（Bagel）

## 目标

- 源码**不入库**（与 MediaCrawler / yt-dlp / Archify 一致）
- 需要时自动 `git clone` → `third_party/wewe-rss/`
- `uv run bagel dev …` **自动启动** sidecar，用户尽量零配置
- 公众号近期文章走 WeWe，避免搜狗稀疏/过时索引

## 为何 Docker 优先、仍 clone

| 路径 | 作用 |
|------|------|
| **clone** | 与其它 third_party 一致；便于本地 `WEWE_RSS_RUNTIME=local` 与排障 |
| **Docker 运行** | 官方 `cooderl/wewe-rss-sqlite` 免 Node/pnpm/Prisma；与「长驻 HTTP 服务」形态匹配 |

WeWe 是 NestJS 长驻服务，不像 MediaCrawler 按需 `Popen`。因此：

- **clone** 在 lifespan / `bagel dev` ensure（幂等）
- **start** 仅在 `bagel dev` 父进程、uvicorn 之前（避免 `--reload` 子进程重复拉起）

## 启动流程

```
bagel dev
  → ensure MediaCrawler / yt-dlp / Archify / WeWe（clone）
  → ensure_wewe_rss_running()
       · 已可访问 /feeds → 复用
       · runtime=auto|docker → Docker 容器 bagel-wewe-rss
       · 失败且 auto → 尝试 local（Node≥20 + pnpm）
  → uvicorn（reload 排除 third_party/wewe-rss）
```

数据目录：`data/wewe-rss/`（SQLite 卷）。状态：`data/wewe_rss_runtime.json`。

默认 `WEWE_RSS_BASE_URL` 留空 → 客户端使用 `http://127.0.0.1:{WEWE_RSS_PORT}`。

## 用户仍需的一次性步骤

微信读书扫码 + 在 WeWe Web 用样例文章添加公众号（WeWe 产品约束，Bagel 无法绕过）。

之后在 Bagel 按名称订阅 / 定时采集即可。

## 关闭

```env
ENABLE_WEWE_RSS=false
# 或
WEWE_RSS_AUTO_START=false
WEWE_RSS_RUNTIME=off
```

容器默认 `--restart unless-stopped`，退出 bagel 不强制停 WeWe（与本机 RSSHub 习惯一致）。
