# 能力全景（归档）

本表整理当前仓库已落地能力，便于开源读者与二次开发者快速摸底。产品叙事与上手见根目录 [README.md](../README.md)；文档总目录 [README.md](./README.md)。

## 采集与入库

| 能力 | 说明 |
|------|------|
| RSS / RSSHub 新闻 | 国内优先；海外源可在代理下采集，失败不阻断国内 |
| GitHub 项目 / Release | Token 可选；网络降级友好 |
| 论文源 | arXiv 等可配置源；可选 PDF 探测与全文识别（见下） |
| 教育源 | MIT / 斯坦福 / 清北等开放课 RSS（可配置） |
| 模型源 | Hugging Face Hub / ModelScope 魔搭 |
| 股票资讯 | 独立源管理 + enrichment / 时间线 / 行研草稿（非荐股） |
| 自媒体 | 对接 MediaCrawler（**本机克隆**）— 默认关键词发现；评论/媒体下载可在配置开启（默认关） |
| 音视频 | 对接 yt-dlp（**本机克隆**）— 订阅元数据 + 按需下载/字幕/ASR；自媒体视频可「提取文稿」 |
| 微信 | Gewe 回调入库，关键词过滤 |
| Reddit RSS | 预置源 + 浏览器态请求头 |
| 去重 / 归一 | 统一 `IntelItem`；原始证据不被 LLM 覆盖 |
| 源容错 | `source_guard`：单源重试 / 429 退避 / 跳过，不拖垮整批 |
| 回溯窗口 | `COLLECT_LOOKBACK_DAYS` 控制新鲜度 |

## 审阅与产品页

| 路径 | 能力 |
|------|------|
| `/news` `/github` `/papers` `/models` `/stocks` `/media` `/av` `/wechat` `/education` | 列表、**标题关键词搜索**（`q`）、分类、收藏、关联条目 |
| `/av` · `/av/{id}` | 采集元数据、下载、提取字幕/文稿、进度与日志 |
| `/github/learn/{id}` | 懒加载仓库 Wiki + Archify 架构图 |
| `/briefs/*` | 周 / 月总结、**投屏 / PPT / 导出 HTML·MD**、个人空间（看板 + 3D GBrain）、自定义提示词 |
| `/favorites` | 收藏夹 |
| `/collect` | 采集（手动 / 定时）+ 任务详情（进度百分比） |
| `/stocks/timeline` · 个股页 | 行情可视化（Yahoo OHLC，可关） |
| 明暗主题 | 本地持久化主题切换 |

## 音视频文稿与 ASR

| 步骤 | 说明 |
|------|------|
| 1. 平台 CC | yt-dlp `--write-subs`（有 soft CC 时） |
| 2. 本地 soft-sub | 从已下载容器 demux 字幕轨 |
| 3. ASR | 本地抽音轨 → **openspeech（豆包语音）** → OpenAI Whisper → faster-whisper |
| 4. 作者简介 | 默认关（`AV_FALLBACK_AUTHOR_DESC=false`）；≠ 画面字幕 |

抖音画面字幕多为**烧录 soft-sub 不存在**，必须走 ASR。凭证在 **系统设置 → 配置 → 音视频ASR**（`VOLC_ASR_APP_ID` + `VOLC_ASR_ACCESS_KEY` 或新版 `VOLC_ASR_API_KEY`）。详见 [media-vs-av.md](./media-vs-av.md)。

## 论文 PDF 识别

| 能力 | 说明 |
|------|------|
| 探测开放 PDF | Zenodo / `citation_pdf_url` / Unpaywall 等 → 写入 `pdf_url` |
| 下载并识别 | 本地下载后 MinerU / Kimi **round_robin 或 failover** → `content` |
| 配置 | 系统设置「论文」分组或 `.env`（见 [paper-parse.md](./paper-parse.md)） |

## 系统设置

| 页签 | 能力 |
|------|------|
| 新闻数据源 | RSS 源 CRUD、启停；**兴趣标签 INCLUDE**（本类目） |
| GitHub | Search Query 启停；兴趣标签 INCLUDE |
| 论文 / 教育 / 模型 / 股票 / **音视频**源 | CRUD、启停；各页兴趣标签 INCLUDE |
| 系统排除词 | EXCLUDE：多选类目（含自媒体/微信）、添加/删除/启停 |
| 定时任务 | 间隔 30～720 分钟 + 抖动；采集 + **关键词自增长** + 可选 **Wiki 编译** |
| CLI · 飞书 | Webhook / lark-cli；昨日列表 / 周汇总推送；定时后异步推送 |
| 配置 | 可视化编辑 `.env`（路径对外相对化）；含 **音视频 / ASR / 论文解析 / yt-dlp** 等分组 |
| 用户管理 | 多用户登录、管理员、改密；采集任务与用户配置隔离 |
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
| Wiki 编译 | MD 正文 + `wiki_page` / `wiki_edge` 索引；**定时任务**（设置页） |
| 个人空间看板 | `/briefs/space?view=board` 搜索 / 关键词 / 类型 / 数据源统计 |
| 个人空间图谱 | `/briefs/space?view=graph` 全幅 3D 倒锥图；SUBJECTS 仅 8 类资源频道 |
| 知识卡 | 资源优先：摘要 + 打开原文；主题为枢纽 |
| 学习记录 | `gbrain_learn_event`（view / focus / review） |

详见 [wiki-taxonomy-gbrain.md](./wiki-taxonomy-gbrain.md)、[briefs-dashboard.md](./briefs-dashboard.md)。

## 汇总投屏与 PPT

| 入口 | 说明 |
|------|------|
| 投屏 | `/briefs/{kind}/{period}/present` 全屏讲解稿 |
| PPT | `?mode=ppt`，reveal.js；可选 LLM 提炼要点；**指纹缓存** `data/cache/brief_ppt/` |
| HTML / MD | `.html` / `.md` 导出 |

详见 [briefs-dashboard.md](./briefs-dashboard.md)。

## 功能入口速查

| 路径 | 说明 |
|------|------|
| `/` | 首页 |
| `/news` … `/wechat` · `/av` | 各渠道审阅 |
| `/github/learn/{id}` | GitHub 学习 Wiki |
| `/briefs/space` | 个人空间（`view=board\|graph`）；旧 `/briefs/dashboard` 已重定向 |
| `/briefs/*` | 周/月总结、投屏、导出 |
| `/favorites` `/collect` `/settings` | 收藏 / 采集 / 设置 |
| `/health` | 存活探针 |
| `/api/feishu/events` · `/api/feishu/command` | 飞书事件与调试 |
| `/api/av/*` · `/api/papers/*` | 音视频下载/字幕、论文解析任务 |

反向代理挂载前缀（如 `/bagel`）时，对外 URL 自动加前缀；见 README「反向代理前缀」。

## 工程与运维

| 项 | 说明 |
|----|------|
| CLI | `bagel doctor` / `bagel dev` / `setup-media` / `setup-ytdlp` / `setup-archify` / `cli …` |
| 存储 | SQLite 默认；Postgres 可选；Wiki Markdown 导出可选 |
| 本地缓存 | `data/av/`、`data/cache/brief_ppt/`、`data/github/learn/` 等（见 [storage.md](./storage.md)） |
| 调度 | 进程内 APScheduler（建议单 worker）；任务幂等 |
| 鉴权 | Session；可 `AUTH_REQUIRED=false` 本地调试 |
| 测试 | `uv run pytest` |
| 代理 | `NETWORK_MODE=AUTO` + `HTTPS_PROXY=…` |

## 验收清单（维护者）

- [ ] `uv run bagel dev` 后打开 http://127.0.0.1:8000
- [ ] 默认 SQLite 可采集国内新闻
- [ ] `/av`：验通直链样片可下载；进度条可见（[default-av-sources.md](./default-av-sources.md)）
- [ ] 配置 openspeech 凭证后，无 soft-sub 的抖音可 ASR 出文稿（[media-vs-av.md](./media-vs-av.md)）
- [ ] 论文：探测 PDF → 下载识别写入 `content`（配置 Token 后）
- [ ] GitHub「学习」页可 bootstrap；有 Node 时可出 Archify 图
- [ ] 汇总页：投屏 / PPT / HTML / MD 导出；再次打开 PPT 命中缓存
- [ ] 系统设置 → 各数据源页可管理兴趣标签；系统排除词可多选类目并启停
- [ ] 汇总 → 个人空间看板与图谱（3D GBrain、SUBJECTS、知识卡）正常
- [ ] 教育 Tab：设置源、采集、收藏、关联侧栏、教育总结
- [ ] 列表「关联」打开侧栏（列表 + 图谱），可进完整个人空间
- [ ] 周/月总结支持自定义提示词并显示生成所用提示词
- [ ] 主题切换与列表页正常
- [ ] `uv run pytest` 通过
