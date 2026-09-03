# 能力全景（归档）

本表整理当前仓库已落地能力，便于开源读者与二次开发者快速摸底。产品叙事与上手见根目录 [README.md](../README.md)。

## 采集与入库

| 能力 | 说明 |
|------|------|
| RSS / RSSHub 新闻 | 国内优先；海外源可在代理下采集，失败不阻断国内 |
| GitHub 项目 / Release | Token 可选；网络降级友好 |
| 论文源 | arXiv 等可配置源 |
| 教育源 | MIT / 斯坦福 / 清北等开放课 RSS（可配置） |
| 模型源 | Hugging Face Hub / ModelScope 魔搭 |
| 股票资讯 | 独立源管理 + enrichment / 时间线 / 行研草稿（非荐股） |
| 自媒体 | 对接 MediaCrawler（**本机克隆**，不进仓库；`bagel setup-media`） |
| 微信 | Gewe 回调入库，关键词过滤 |
| Reddit RSS | 预置源 + 浏览器态请求头 |
| 去重 / 归一 | 统一 `IntelItem`；原始证据不被 LLM 覆盖 |
| 回溯窗口 | `COLLECT_LOOKBACK_DAYS` 控制新鲜度 |

## 审阅与产品页

| 路径 | 能力 |
|------|------|
| `/news` `/github` `/papers` `/models` `/stocks` `/media` `/wechat` `/education` | 列表、**标题关键词搜索**（`q`）、分类、收藏、关联条目 |
| `/briefs/*` | 周 / 月总结、**投屏视图 / 导出 HTML**、个人空间（看板 + 3D GBrain）、自定义提示词 |
| `/favorites` | 收藏夹 |
| `/collect` | 采集（手动 / 定时）+ 任务详情 + Wiki 编译 |
| `/stocks/timeline` · 个股页 | 行情可视化（Yahoo OHLC，可关） |
| 明暗主题 | 本地持久化主题切换 |

## 系统设置

| 页签 | 能力 |
|------|------|
| 新闻数据源 | RSS 源 CRUD、启停；**兴趣标签 INCLUDE**（本类目） |
| GitHub | Search Query 启停；兴趣标签 INCLUDE |
| 论文 / 教育 / 模型 / 股票源 | CRUD、启停；各页兴趣标签 INCLUDE |
| 系统排除词 | EXCLUDE：多选类目（含自媒体/微信）、添加/删除/启停 |
| 定时任务 | 间隔 30～720 分钟 + 抖动；采集 + **关键词自增长** + 可选 **Wiki 编译** |
| CLI · 飞书 | Webhook / lark-cli；昨日列表 / 周汇总推送；定时后异步推送 |
| 配置 | 可视化编辑 `.env`（路径对外相对化，不泄露本机绝对路径） |
| 用户管理 | 多用户登录、管理员、改密 |
| 系统状态 | DB / RSSHub / GitHub / LLM / 网络健康检查 |

兴趣过滤按资源类型分散：各数据源页配置 INCLUDE；**系统排除词**统一管理 EXCLUDE。详见 [filter-tags.md](./filter-tags.md)。

## 飞书双场景

| 场景 | 行为 |
|------|------|
| **指令查询** | 飞书发「把 8/20–8/21 体操新闻发我」→ 查库 → 空则补采最新 → 回复；事件入口 `POST /api/feishu/events`，调试 `POST /api/feishu/command` |
| **定时推送** | 定时采集入库后异步推摘要（设置里勾选「定时采集完成后异步推送飞书」） |

```bash
uv run bagel cli feishu-send "你好"
uv run bagel cli feishu-digest yesterday
uv run bagel cli feishu-ask "把8月20号到8月21号的体操方向新闻发我" --push
```

## Wiki · Taxonomy · GBrain

| 能力 | 说明 |
|------|------|
| 领域 Taxonomy | 包内 seed（topics / dependencies / clusters）；结构借鉴 os-taxonomy |
| Wiki 编译 | MD 正文 + `wiki_page` / `wiki_edge` 索引；手动或定时 |
| 个人空间看板 | `/briefs/space?view=board` 搜索 / 关键词 / 类型 / 数据源统计 |
| 个人空间图谱 | `/briefs/space?view=graph` 全幅 3D 倒锥图；SUBJECTS 仅 8 类资源频道 |
| 知识卡 | 资源优先：摘要 + 打开原文；主题为枢纽 |
| 学习记录 | `gbrain_learn_event`（view / focus / review） |

详见 [wiki-taxonomy-gbrain.md](./wiki-taxonomy-gbrain.md)、[briefs-dashboard.md](./briefs-dashboard.md)。

## 功能入口速查

| 路径 | 说明 |
|------|------|
| `/` | 首页 |
| `/news` … `/wechat` | 各渠道审阅 |
| `/briefs/space` | 个人空间（`view=board\|graph`）；旧 `/briefs/dashboard` 已重定向 |
| `/briefs/*` | 周/月总结 |
| `/favorites` `/collect` `/settings` | 收藏 / 采集 / 设置 |
| `/health` | 存活探针 |
| `/api/feishu/events` · `/api/feishu/command` | 飞书事件与调试 |

## 工程与运维

| 项 | 说明 |
|----|------|
| CLI | `bagel doctor` / `bagel dev` / `bagel setup-media` / `bagel cli …` |
| 存储 | SQLite 默认；Postgres 可选；Wiki Markdown 导出可选 |
| 调度 | 进程内 APScheduler（建议单 worker） |
| 鉴权 | Session；可 `AUTH_REQUIRED=false` 本地调试 |
| 测试 | `uv run pytest` |
| 代理 | `NETWORK_MODE=AUTO` + `HTTPS_PROXY=…` |

## 验收清单（维护者）

- [ ] `uv run bagel dev` 后打开 http://127.0.0.1:8000
- [ ] 默认 SQLite 可采集国内新闻
- [ ] 系统设置 → 各数据源页可管理兴趣标签；系统排除词可多选类目并启停
- [ ] 汇总 → 个人空间看板与图谱（3D GBrain、SUBJECTS、知识卡）正常
- [ ] 教育 Tab：设置源、采集、收藏、关联侧栏、教育总结
- [ ] 列表「关联」打开侧栏（列表 + 图谱），可进完整个人空间
- [ ] 周/月总结支持自定义提示词并显示生成所用提示词
- [ ] 主题切换与列表页正常
- [ ] `uv run pytest` 通过
