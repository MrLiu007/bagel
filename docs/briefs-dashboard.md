# 汇总 · 个人空间与 GBrain

## 个人空间（`/briefs/space`）

原「看板」已更名为 **个人空间**。旧路径 `/briefs/dashboard` 301 跳转到 `/briefs/space`。

| 模块 | 说明 |
|------|------|
| 搜索统计 | 近 90 天搜索次数（含飞书指令、个人空间试搜） |
| 关键词排名 | 搜索词频次与命中条目数 |
| 常用数据类型 | 近 90 天各 `ItemType` 入库量（含教育） |
| 常用数据源 | 绑定 `IntelSource` 的条目计数 |
| GBrain 知识图谱 | ECharts 力导向关系图：类型 / 分类 / 标签 / 数据源 / 条目共现 |

顶部可 **试搜并记录**，行为写入 `intel_search_event`。

## GBrain（WikiItem 适配层）

进程内轻量图谱（无 Neo4j / 向量库）：

1. **Adapter**：各资源类型 → 统一 `WikiItem`（含 `topic_ids`）
2. **Taxonomy**：包内 seed（topics / dependencies / clusters），结构对齐 os-taxonomy，内容自有
3. **Core**：资源优先；边为 `about` / `prerequisite` / `contains` / `typed_as` 等；可选合并 `wiki_edge`
4. **Wiki 编译**：MD 正文 + DB 索引（见 [wiki-taxonomy-gbrain.md](./wiki-taxonomy-gbrain.md)）
5. **可视化**：个人空间使用 **3d-force-graph**（高度 `fy` = 资源/概念层）；统计文案对齐 micro-topics / deps / clusters；`stats.resources`（勿用 `items`，Jinja 会撞上 `dict.items`）
6. **交互**：点击节点打开 URL；先修边虚线粒子；自动慢旋

关联抽屉默认 `hidden`，仅点击列表「关联」时打开。

## 关联侧栏（列表 + 图谱）

各资源列表「关联」不再整页跳转，改为右侧抽屉（图1 混合模式）：

1. **列表视图**（默认）：按类型分组的相关资源（新闻 / 论文 / 教育 / …）
2. **图谱视图**：约 560px 高的 ECharts 子图（一阶关联）
3. **底部**：「在新页面打开完整 GBrain」→ `/briefs/space?seed=…`

API：`GET /api/items/{id}/related`（JSON）。全页 `/items/{id}/related` 仍保留作兜底。

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

## 数据表

- `intel_search_event` — 搜索日志（迁移 `0005_search_event`）
- `intel_monthly_brief.metadata.prompt_used` — 本次生成提示词快照
