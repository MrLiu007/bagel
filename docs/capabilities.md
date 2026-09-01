# 能力归档 · Capability Archive

> 随版本维护的能力清单；README「能力全景」以其摘要为准。最后整理：2026-09。

## v0.3 · 开源品牌化

- 工程 / 包 / CLI 统一为 **Bagel（贝果）**
- MIT 许可；README 截图与能力归档

## 采集

- [x] RSS / RSSHub / Manual 新闻源
- [x] GitHub repos & releases
- [x] 论文源
- [x] 股票资讯源 + enrichment / timeline / research draft
- [x] MediaCrawler 自媒体（本机克隆，不进 git；`bagel setup-media`）
- [x] Gewe 微信
- [x] Reddit RSS seeds
- [x] 关键词过滤（INCLUDE / EXCLUDE）
- [x] 回溯天数、去重、分类

## 产品 UI

- [x] 新闻 / 项目 / 论文 / 股票 / 自媒体 / 微信列表
- [x] 收藏、关联条目、明暗主题
- [x] 周月汇总 briefs + Markdown 导出
- [x] 手动采集任务进度
- [x] 系统设置全页签（源 / 调度 / CLI / .env 可视化 / 用户 / 健康）

## 飞书

- [x] Webhook / lark-cli 出站
- [x] 昨日列表 / 周汇总推送
- [x] 定时采集后异步推送（场景 2）
- [x] 自然语言指令查库 + 空库补采 + 回复（场景 1）
- [x] `POST /api/feishu/events` · `/api/feishu/command` · `bagel cli feishu-ask`

## 工程

- [x] SQLite 默认 / Postgres 可选 / Wiki 导出
- [x] APScheduler 抖动调度
- [x] `bagel doctor` / `bagel dev`
- [x] 路径相对化（不泄露本机绝对路径）
- [x] 单元测试覆盖核心链路
