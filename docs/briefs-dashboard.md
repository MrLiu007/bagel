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
5. **可视化**：图谱页使用 **3d-force-graph**（高度 `fy`）；倒锥居中、舞台无框透明、单行规模统计（`resources · 主题 · 关联`）
6. **交互**：点资源开知识卡（摘要 + URL）；SUBJECTS 切换 8 频道；先修边粒子；自动慢旋；学习记录复习

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

各总结页（新闻 / 项目 / 论文 / **教育** / 模型 / 股票 / 自媒体）：

- 周 / 月共用自定义提示词；可保存为 `data/brief_prompts.json` 默认
- 生成后可展开「本次使用的提示词」

## 投屏视图与 HTML 导出

各类型总结页在生成结果后提供：

| 入口 | 路径 | 说明 |
|------|------|------|
| 投屏视图 | `/briefs/{kind}/{period}/present` | 全屏讲解稿：大字号、独立样式、Mermaid 饼图、打印/PDF、Esc 返回 |
| 导出 HTML | `/briefs/{kind}/{period}.html` | 同结构自包含 HTML 附件，便于离线投屏或分享 |
| 导出 Markdown | `/briefs/{kind}/{period}.md` | 原稿（仍保留） |

HTML 由 `markdown_to_article_html` 即时渲染（不落库）；` ```mermaid ` 块在投屏/导出中渲染为图表。  
链接清单使用短域名锚点（如 `[infoq.cn](…)`），表格 `table-layout:fixed` + 横向滚动，避免长 URL 撑破版心。投屏页为墨青编辑风（Fraunces + Source Sans 3），非塑料蓝白卡片。

## 数据表

- `intel_search_event` — 搜索日志（迁移 `0005_search_event`）
- `wiki_page` / `wiki_edge` — Wiki 索引（迁移 `0006_wiki_index`）
- `gbrain_learn_event` — 图谱学习事件（迁移 `0007_gbrain_learn`）
- `intel_monthly_brief.metadata.prompt_used` — 本次生成提示词快照
