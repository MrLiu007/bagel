# Wiki 编译层 + 领域 Taxonomy + GBrain

## 分层（落地约定）

| 层 | 存放 | 职责 |
|---|---|---|
| Raw / IntelItem | 事务库 | 业务真相；LLM 永不覆盖 `IntelRawEvidence` |
| Taxonomy | 包内 `bagel/taxonomy/seed/*.json` | **结构**借鉴 os-taxonomy（topics / dependencies / clusters）；**内容**为 Bagel 自有 AI 情报主题，不引入 Marble 课标数据 |
| Wiki 正文 | `WIKI_DIR` Markdown | 资源页、主题页、簇页、`index.md`、`log.md` |
| Wiki 索引 | `wiki_page` / `wiki_edge` | 路径、哈希、item/topic 外键、可查询边 |

全类型资源（新闻 / GitHub / 论文 / 教育 / 模型 / 股票 / 自媒体 / 微信…）在同一用户空间统一挂到 taxonomy 主题上，GBrain 一张图呈现。

## 操作

- **手动**：采集页 →「编译 Wiki」→ 任务 kind `compile_wiki`
- **定时**：设置 → 定时任务 →「定时编译 Wiki」（默认每日 04:10，`enable_wiki_compile`）
- **浏览**：`/briefs/space?view=graph` 全幅 GBrain（主题实线 about / 先修虚线 prerequisite）

编译幂等：按 `content_hash` 跳过未变 MD；边表按 relation 重建 about/prerequisite/contains。

## GBrain 投影优先级

1. Taxonomy 主题 + 先修 / 簇包含边  
2. 编译后的 `wiki_edge`（若有）  
3. 类型 / 数据源 / 教育院校等轻量枢纽  
4. **不再**用正则实体碎片或开放 INCLUDE 标签当主概念节点

## 扩展 taxonomy（数据量少时怎么做）

1. **加 subtopic**：在 `topics.json` 写 `parentId` 指向父主题，并在 `dependencies.json` 加 hard/soft 先修边。  
2. **采更多情报**：继续跑各渠道采集；编译 Wiki 后资源会挂到主题（别名/分类匹配）。  
3. **不要导入 Marble 课标**：只复用结构；Bagel 域内容自维护。  
4. **可选 LLM 提案**：用 Lint/编译任务提议新 micro-topic，人工确认后再写入 seed（保持 ID 稳定）。

## 个人空间 · 看板 / 图谱

- `/briefs/space?view=board`：搜索统计、关键词、类型与数据源（看板）
- `/briefs/space?view=graph`：全幅 GBrain（SUBJECTS 仅 8 类资源频道）

SUBJECTS 固定：新闻 · GitHub项目 · 教育 · 论文 · 模型 · 股票 · 自媒体 · 微信（不含 AI 等 taxonomy subject）。

## 图谱 UX（3D 倒锥）

目标：资源优先、全幅沉浸、统计可读，避免「画布框」抢注意力。

| 项 | 约定 |
|----|------|
| 渲染 | `3d-force-graph`；高度层 `fy` = 资源/概念层；倒锥/龙卷风布局 |
| 顶部统计 | 单行：`N 资源 · N 主题 · N 关联`；数字用 `stats.resources` / topics / links（**勿用** Jinja `dict.items`，会撞方法名） |
| 禁止展示 | 不再展示 `taxonomy … micro-topics · 先修` 等内部 taxonomy 计数行（易误导） |
| 舞台 | `.gbrain-stage` 无边框、背景透明，与页面底色融合；高度约 `88vh` |
| 居中 | 锥体高度中点对齐世界原点（`midY = maxH * 0.5`）；生长结束后 `zoomToFit` 框住 |
| SUBJECTS | 左下半透明浮层；仅 8 资源频道 toggle |
| 知识卡 | 右上浮层；资源卡 = 摘要 + 打开原文；主题卡 = 挂载资源列表 |
| 学习记录 | 页底；`gbrain_learn_event`（view / focus / review） |

## 闪卡产品逻辑（资源优先）

Bagel 不是纯课标知识库，而是 **URL + 摘要** 情报图谱：

1. 点**红色资源点** → 卡片展示标题 / 摘要 / **打开原文**
2. 点关联资源 → 换卡（摘要+URL），图谱聚焦
3. 点主题枢纽 → 列出挂载资源（每条含摘要与原文链接）再下钻
4. 学习记录建议复习资源或主题；可直接开原文

## 相关文档

- [briefs-dashboard.md](./briefs-dashboard.md) — 个人空间入口、关联侧栏、关键词自增长
- [capabilities.md](./capabilities.md) — 能力全景归档
- [storage.md](./storage.md) — Wiki 目录与后端
