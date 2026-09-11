# 汇总 · 个人空间与 GBrain

## 个人空间（`/briefs/space`）

原「看板」已更名为 **个人空间**。旧路径 `/briefs/dashboard` 301 跳转到 `/briefs/space`。

子视图：

| 视图 | URL | 说明 |
|------|-----|------|
| 看板 | `?view=board`（默认） | 搜索统计、关键词、类型与数据源 |
| 图谱 | `?view=graph` | 全幅 3D GBrain（倒锥布局） |

| 模块 | 说明 |
|------|------|
| 搜索统计 | 近 90 天搜索次数（含飞书指令、个人空间试搜） |
| 关键词排名 | 搜索词频次与命中条目数 |
| 常用数据类型 | 近 90 天各 `ItemType` 入库量（含教育） |
| 常用数据源 | 绑定 `IntelSource` 的条目计数 |
| GBrain 知识图谱 | 见下节；taxonomy 投影 + SUBJECTS 筛选 + 知识卡 |

顶部可 **试搜并记录**，行为写入 `intel_search_event`。

## GBrain（WikiItem 适配层）

进程内轻量图谱（无 Neo4j / 向量库）：

1. **Adapter**：各资源类型 → 统一 `WikiItem`（含 `topic_ids`）
2. **Taxonomy**：包内 seed（topics / dependencies / clusters），结构对齐 os-taxonomy，内容自有
3. **Core**：资源优先；边为 `about` / `prerequisite` / `contains` / `typed_as` 等；可选合并 `wiki_edge`
4. **Wiki 编译**：MD 正文 + DB 索引（见 [wiki-taxonomy-gbrain.md](./wiki-taxonomy-gbrain.md)）
5. **可视化**：图谱页使用 **3d-force-graph** + `gbrain-tornado.js`（螺旋锥 / 生长 / 自转）；倒锥居中、径向暗底、单行规模统计（`resources · 主题 · 关联`）
6. **交互**：点资源开知识卡（摘要 + URL）；SUBJECTS 切换 8 频道；先修边粒子；自动慢旋；学习记录复习
7. **关联抽屉**：与个人空间共用 tornado 布局，避免两套样式

统计字段用 `stats.resources`（勿用模板里的 `items`，Jinja 会撞上 `dict.items`）。

关联抽屉默认 `hidden`，仅点击列表「关联」时打开。

## 关联侧栏（列表 + 图谱）

各资源列表「关联」不再整页跳转，改为右侧抽屉（混合模式）：

1. **列表视图**（默认）：按类型分组的相关资源（新闻 / 论文 / 教育 / …）
2. **图谱视图**：抽屉内 3D 子图（一阶关联）
3. **底部**：「在新页面打开完整 GBrain」→ `/briefs/space?view=graph&seed=…`

API：`GET /api/items/{id}/related`（JSON）。全页 `/items/{id}/related` 仍保留作兜底。

知识卡 / 学习 API：

- `GET /api/gbrain/card?key=…`
- `POST /api/gbrain/learn`
- `GET /api/gbrain/review`

## 关键词自增长

定时任务 `keyword_growth`（默认每日 03:15，需调度开启并勾选扩展开关）：

1. 聚合近 30 天、出现 ≥2 次的搜索词 → 按类目写入 **兴趣标签 INCLUDE**（含 `education`）
2. 命中营销/敏感模式 → **系统排除词 EXCLUDE**（全类目）
3. 从 `REJECTED` 标题补充 EXCLUDE

## 教育总结

- 列表：`/education`；设置：`/settings?tab=education`；总结：`/briefs/education`
- 默认源含 MIT OCW、Class Central、Coursera、edX、Stanford 等（清北等可经 RSSHub 启用）
- 能力对齐论文：采集、兴趣标签、收藏、关联侧栏、周/月总结、自定义提示词

## 自定义总结提示词

各总结页（新闻 / 项目 / 论文 / **教育** / 模型 / 股票 / 自媒体 / 音视频）：

- 周 / 月共用自定义提示词；可保存为 `data/brief_prompts.json` 默认
- **上方「生成」**：固定结构模板（不调 LLM）
- **「按自定义提示词生成」**：调用 LLM，按提示词重写终稿；自动注入条目素材（可用 `{{新闻池}}` / `{{条目池}}` 等占位）
- 「本次使用的提示词」仅可展开查看，不再写入稿件正文（避免与输入框重复）
- **正文优先、不裁编辑限额**：模板路径事实段按类型取 `content → summary → llm_summary`（论文优先 abstract/`summary`）；新闻入库会把 RSS 全文写入 `content`

## 投屏视图与 HTML 导出

各类型总结页在生成结果后提供：

| 入口 | 路径 | 说明 |
|------|------|------|
| 投屏视图 | `/briefs/{kind}/{period}/present` | 全屏讲解稿：大字号、独立样式、Mermaid 饼图、打印/PDF、Esc 返回 |
| PPT 模式 | `/briefs/{kind}/{period}/present?mode=ppt` | [reveal.js](https://revealjs.com/) 幻灯片：按 h2 / 条目分页，方向键翻页 |
| 导出 HTML | `/briefs/{kind}/{period}.html` | 同结构自包含 HTML 附件，便于离线投屏或分享 |
| 导出 Markdown | `/briefs/{kind}/{period}.md` | 原稿（仍保留） |

HTML 由 `markdown_to_article_html` 即时渲染（不落库）；` ```mermaid ` 块在投屏/导出中渲染为图表。  
链接清单使用短域名锚点（如 `[infoq.cn](…)`），表格 `table-layout:fixed` + 横向滚动，避免长 URL 撑破版心。投屏页为墨青编辑风（Fraunces + Source Sans 3）：版心约 1180px 居中、正文全宽（不再 `68ch` 收窄），顶栏细强调线。

### PPT 模式细节

| 项 | 行为 |
|----|------|
| 分页 | 封面 + 按章节 / 条目拆页；内容过长截断并提示看文档模式 |
| LLM | 可选调用 LLM 提炼要点（`brief_ppt`）；失败回退规则拆页 |
| 缓存 | `data/cache/brief_ppt/{brief_id}.json`，按**稿件内容指纹**命中则跳过重算 |
| 强制重算 | URL 加 `rebuild=1` |
| 布局 | Reveal `center: false`；当前页垂直居中，避免后页空白或顶贴 |

实现：`src/bagel/services/brief_ppt.py`；路由：`web/routes/briefs.py`。

自媒体 / 音视频周月报生成前可自动对缺正文的视频条目提字幕（`BRIEF_AUTO_ENRICH_MEDIA`，见 [media-vs-av.md](./media-vs-av.md)）。

## 数据表

- `intel_search_event` — 搜索日志（迁移 `0005_search_event`）
- `wiki_page` / `wiki_edge` — Wiki 索引（迁移 `0006_wiki_index`）
- `gbrain_learn_event` — 图谱学习事件（迁移 `0007_gbrain_learn`）
- `intel_monthly_brief.metadata.prompt_used` — 本次生成提示词快照
