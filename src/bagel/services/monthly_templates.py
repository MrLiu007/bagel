"""Period sharing briefs — kind-specific, presentation-ready manuscripts.

Each brief kind has its own section recipe so a presenter has enough to say,
and the audience gets concrete knowledge (facts, contrasts, examples, takeaways).
No homework tone, no rhetorical question stacks, no cross-section copy-paste.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from typing import Sequence

from urllib.parse import urlparse

from bagel.domain.enums import BriefKind, ItemType
from bagel.domain.models import IntelItem
from bagel.pipeline.textutil import strip_html, truncate

TEMPLATE_VERSION = "share-period-v11-deck"

# Old LLM / template leftovers that must not reappear as “关键点”.
_BAD_WHY_RE = re.compile(
    r"(科普落脚|能否转化为|是否有助于|学员|作业|同学|费曼|苏格拉底|专业教育追问|"
    r"这股趋势会不会|若忽略它|最小可借鉴)",
    re.I,
)


@dataclass(frozen=True)
class TopicBridge:
    contrast: str  # “以前/常见 vs 现在” talking point
    example: str  # concrete example the presenter can speak
    takeaway: str  # education / work bridge


_BRIDGES: dict[str, TopicBridge] = {
    "大模型/LLM": TopicBridge(
        contrast="常见叙事只报「更强了」；更值得讲的是能力边界、成本，以及评测口径是否可核对。",
        example="例如同一道题，换提示策略或换模型档位，只比正确率与耗时——听众立刻懂「强」不是口号。",
        takeaway="教育与培训少追产品名，多讲「约束—验收—回退」；工作流程只收录能复现、能对质的结果。",
    ),
    "Agent": TopicBridge(
        contrast="常见做法是「把聊天框接上工具」；关键差距在于有没有目标、停止条件与失败可定位。",
        example="例如一次自动改稿：先定目标与禁改项，再跑 Agent，最后用 diff 验收——成功路径和失败路径都能讲。",
        takeaway="教育演示不能只播成功录像；交付自动化必须配验收标准，否则只是更快地出错。",
    ),
    "RAG": TopicBridge(
        contrast="朴素聊天靠参数里的记忆；RAG 先检索再生成，错在知识库与召回时可以追查。",
        example="例如固定 10 个问题，改 top-k 或切块大小，记录命中与胡编——比空讲「检索很重要」有用。",
        takeaway="课程知识库要谈更新与引用；写材料、做决策时「先证据后结论」能降幻觉风险。",
    ),
    "多模态": TopicBridge(
        contrast="炫技生成只追求「好看」；专业用法要求图文音对齐同一可验收任务。",
        example="例如课件配图：先写合格标准（信息是否正确、有无误导），再谈模型效果。",
        takeaway="岗位任务（质检、客服、课件）先定义合格输出；生活中看生成物也先问是否对齐真实用途。",
    ),
    "开源发布": TopicBridge(
        contrast="刷到仓库链接很容易；难的是半小时复现、许可证与依赖是否干净。",
        example="例如开分享前先跑通 README 最小命令，把「能跑/不能跑」和卡点说给听众听。",
        takeaway="进案例或工具链前以复现为准；工作选型里热度不等于可落地。",
    ),
    "推理/训练": TopicBridge(
        contrast="宣传常给单点指标；专业讲解要把精度、延迟、成本三个约束一起摆上台面。",
        example="例如同一题两种推理预算，只比一个指标，并写明硬件与超时条件。",
        takeaway="讲评测把数字和条件一起说；采购与排期也先对齐约束再谈指标。",
    ),
    "机器人/具身": TopicBridge(
        contrast="视频演示强调「会动」；专业讲解拆感知—规划—执行，并标安全边界。",
        example="例如只验证一个感知模块能否在干扰下稳定输出，比整段炫技短片更有信息量。",
        takeaway="能动手的系统，风险边界要说在能力前面；教育与工程都先谈可独立验证的一环。",
    ),
    "评测/基准": TopicBridge(
        contrast="榜单报道爱报名次；更有营养的是尺子量什么、量不到什么、如何被刷分。",
        example="例如点出一条「高分仍会系统性失败」的反例任务，听众对榜单的盲信立刻下降。",
        takeaway="引用榜单时补口径与反例；个人选工具也看评测是否匹配真实任务。",
    ),
    "教育应用": TopicBridge(
        contrast="营销常堆「AI+教育」故事；专业判断要拆开主张与证据（完课、迁移还是案例）。",
        example="例如只借鉴一个交互或评量环节，写清适用边界，比整包照搬更可讲、可落地。",
        takeaway="对外叙事用可验证能力表述；对内迁移「只迁一件事」并写边界。",
    ),
    "行业动态": TopicBridge(
        contrast="标题党推动情绪；讲解要区分叙事变化与真实能力/岗位要求变化。",
        example="例如把新闻改写成一句「对岗位能力的具体影响」，并标明证据强弱。",
        takeaway="课程承诺不被单条热点绑架；职业规划看要求是否真变，而非热搜词。",
    ),
    "其他": TopicBridge(
        contrast="信息噪声里，删掉专有名词仍说得清机制的，才值得占分享时间。",
        example="例如用「事实—机制—一个后果」三句话复述本条，听众能跟得上再展开。",
        takeaway="教育或业务只留一条可迁移结构（流程、指标或失败模式），其余当背景。",
    ),
    "宏观政策": TopicBridge(
        contrast="标题爱写「重磅」；讲解要拆清工具（利率/财政/监管）与传导链条是否说得通。",
        example="例如只讲清「谁宣布了什么、影响哪一类资产的预期」，不夸大即时价格解释。",
        takeaway="把政策当情景输入，而不是买卖信号；记录假设与可证伪点。",
    ),
    "个股动态": TopicBridge(
        contrast="个股新闻常混杂叙事与事实；专业讲解先对齐事件类型（订单/人事/回购/诉讼）。",
        example="例如用「事件—时间—可核对来源」三列复述，听众立刻知道证据强弱。",
        takeaway="单条个股新闻不足以定方向；只作情报线索，进入观察清单而非交易指令。",
    ),
    "板块轮动": TopicBridge(
        contrast="板块叙事容易事后解释；讲解时区分「资金关注」与「基本面改善」。",
        example="例如点名 1～2 个主题关键词，并说明新闻里有没有增量数据支撑。",
        takeaway="主题热度可跟踪，但轮动归因要克制；先建观察框架。",
    ),
    "财报业绩": TopicBridge(
        contrast="业绩通稿爱报「超预期」；讲解要对齐口径（收入/利润/指引）与对比基期。",
        example="例如只挑一个数字说明「相对上一季或一致预期」的变化方向。",
        takeaway="财报是核对事实的机会；把指引变化与风险披露一起读。",
    ),
    "监管合规": TopicBridge(
        contrast="监管新闻易被情绪放大；先弄清管辖机构、措施类型与适用范围。",
        example="例如用一句话写清「对谁、做什么、是否已生效」。",
        takeaway="合规事件优先看边界与时间表，不做短期方向臆测。",
    ),
    "大宗商品": TopicBridge(
        contrast="商品新闻常把价格波动直接归因单一事件；讲解要列出供给/需求/库存至少两项。",
        example="例如只讲清「价格变动 + 一条供需线索」，避免单因叙事。",
        takeaway="商品情报适合情景推演，不适合一句话结论。",
    ),
    "汇率利率": TopicBridge(
        contrast="汇利率解读常过度外推到股市；讲解要标明传导假设。",
        example="例如「利率预期变化 → 哪类资产贴现率敏感」只讲一条链路。",
        takeaway="把利率/汇率当宏观约束条件记录，而不是交易口令。",
    ),
    "市场情绪": TopicBridge(
        contrast="情绪指标有用但滞后且会被标题党污染；讲解时标注样本与来源。",
        example="例如区分「媒体措辞偏多/偏空」与「可核对的资金/波动数据」。",
        takeaway="情绪是滤镜，不是证据；与事实新闻交叉验证。",
    ),
}


@dataclass
class BriefSlotItem:
    title: str
    url: str
    category: str
    published: str
    body: str
    why: str
    score: float
    stars: int | None = None
    language: str | None = None
    community: str = ""


def _display_title(item: IntelItem) -> str:
    return strip_html(item.llm_title_zh or item.title) or item.title


def _body_text(item: IntelItem, *, limit: int = 560) -> str:
    text = item.llm_summary or item.summary or item.content or ""
    text = strip_html(text)
    if not text:
        return ""
    return truncate(text, limit)


def _why_text(item: IntelItem) -> str:
    if not item.llm_why:
        return ""
    text = strip_html(item.llm_why)
    if not text or _BAD_WHY_RE.search(text):
        return ""
    return text


def _pub(item: IntelItem) -> str:
    if item.published_at is None:
        return "时间未知"
    return item.published_at.strftime("%Y-%m-%d")


def _stars(item: IntelItem) -> int | None:
    meta = item.metadata_ or {}
    raw = meta.get("stars")
    try:
        return int(raw) if raw is not None else None
    except (TypeError, ValueError):
        return None


def to_slot(item: IntelItem) -> BriefSlotItem:
    body = _body_text(item)
    why = _why_text(item)
    if why and body and why in body:
        why = ""
    meta = item.metadata_ or {}
    community = str(meta.get("community_label") or meta.get("community") or "")
    return BriefSlotItem(
        title=_display_title(item),
        url=item.url,
        category=item.category or "其他",
        published=_pub(item),
        body=body,
        why=why,
        score=float(item.score or 0),
        stars=_stars(item),
        language=item.language or meta.get("language"),
        community=community,
    )


def _pick_top(items: Sequence[IntelItem], n: int = 8) -> list[IntelItem]:
    ranked = sorted(
        items,
        key=lambda i: (
            1 if i.is_top else 0,
            1 if i.is_favorite else 0,
            float(i.score or 0),
            i.published_at.timestamp() if i.published_at else 0.0,
        ),
        reverse=True,
    )
    return list(ranked[:n])


def _category_counts(items: Sequence[IntelItem]) -> list[tuple[str, int]]:
    counter: Counter[str] = Counter((i.category or "其他") for i in items)
    return counter.most_common(8)


def _bridge(category: str) -> TopicBridge:
    return _BRIDGES.get(category) or _BRIDGES["其他"]


def _facts(slot: BriefSlotItem) -> str:
    if slot.body and not _BAD_WHY_RE.search(slot.body):
        return slot.body
    if slot.body and _BAD_WHY_RE.search(slot.body):
        return (
            f"《{slot.title}》库内摘要仍是旧版套话，已跳过。"
            f"请打开原文，用一两句话说明它在解决什么问题、关键做法是什么。"
        )
    return f"《{slot.title}》原文摘要不足，讲解请打开链接核对事实后口头补充。"


def _distinct_why(slot: BriefSlotItem) -> str:
    """Return why only when it adds information beyond the body."""
    if not slot.why or _BAD_WHY_RE.search(slot.why):
        return ""
    if slot.body and (slot.why == slot.body or slot.why in slot.body):
        return ""
    return slot.why


def _mermaid_pie(counts: list[tuple[str, int]], title: str) -> str:
    if not counts:
        return "_（暂无分类数据）_"
    lines = ["```mermaid", "pie showData", f"    title {title}"]
    for name, n in counts:
        safe = name.replace('"', "'")
        lines.append(f'    "{safe}" : {n}')
    lines.append("```")
    return "\n".join(lines)


def _bar_table(counts: list[tuple[str, int]]) -> str:
    if not counts:
        return "| 主题 | 条数 | 比重 |\n| --- | ---: | --- |\n| （暂无） | 0 | |"
    rows = ["| 主题 | 条数 | 比重 |", "| --- | ---: | --- |"]
    total = sum(n for _, n in counts) or 1
    for name, n in counts:
        bar = "█" * max(1, round(n / total * 14))
        rows.append(f"| {name} | {n} | {bar} |")
    return "\n".join(rows)


def _item_separator(index: int, total: int) -> list[str]:
    return ["", "---", "", f"**〔 {index} / {total} 〕**", ""]


def _header_meta(slot: BriefSlotItem, *, with_stars: bool = False) -> list[str]:
    lines = [
        f"### {slot.title}",
        "",
        f"- **日期**：{slot.published}",
        f"- **主题**：{slot.category}",
        f"- **原文**：[打开链接]({slot.url})",
    ]
    if with_stars and slot.stars is not None:
        lines.append(
            f"- **Stars**：{slot.stars}"
            + (f" · {slot.language}" if slot.language else "")
        )
    lines.append("")
    return lines


def _entry_news(slot: BriefSlotItem) -> list[str]:
    bridge = _bridge(slot.category)
    why = _distinct_why(slot)
    lines = [
        "#### 发生了什么",
        "",
        _facts(slot),
        "",
        "#### 增量对比（以前 / 常见 vs 现在）",
        "",
        why or bridge.contrast,
        "",
        "#### 例子（方便听众记住）",
        "",
        bridge.example,
        "",
        "#### 对我们意味着什么",
        "",
        bridge.takeaway,
        "",
    ]
    return lines


def _entry_github(slot: BriefSlotItem) -> list[str]:
    bridge = _bridge(slot.category)
    why = _distinct_why(slot)
    lines = [
        "#### 项目是什么",
        "",
        _facts(slot),
        "",
        "#### 巧妙之处（对比常见做法）",
        "",
        why or bridge.contrast,
        "",
    ]
    if slot.stars is not None:
        lines.extend(
            [
                f"公开热度约 **{slot.stars}** stars"
                + (f"（{slot.language}）" if slot.language else "")
                + "——热度说明注意力，不说明可复现。",
                "",
            ]
        )
    lines.extend(
        [
            "#### 最小上手与边界",
            "",
            "- **上手**：先读 README 的最小命令，确认环境与许可证。",
            "- **边界**：数据、算力、授权、维护是否集中在少数人——讲清楚再谈引入。",
            "- **验收**：约定一个小任务，30 分钟内跑通或明确卡点，再决定是否进工具链。",
            "",
            "#### 可迁移启发",
            "",
            bridge.takeaway,
            "",
            f"可对照例子：{bridge.example}",
            "",
        ]
    )
    return lines


def _entry_science(slot: BriefSlotItem) -> list[str]:
    bridge = _bridge(slot.category)
    why = _distinct_why(slot)
    facts = _facts(slot)
    contrast = why or (
        f"围绕「{slot.category}」来看：{bridge.contrast} "
        f"结合本篇《{truncate(slot.title, 40)}》，讲解时抓住作者改了哪一个假设或结构，"
        "使结果比「直接套现成模型/公式」更站得住。"
    )
    if contrast.strip() == facts.strip():
        contrast = bridge.contrast
    return [
        "#### 要解决什么问题",
        "",
        facts,
        "",
        "#### 做法与朴素方法有何不同",
        "",
        contrast,
        "",
        "#### 直观例子",
        "",
        bridge.example,
        "",
        "#### 对教育 / 工程的启发",
        "",
        bridge.takeaway,
        "",
    ]


def _entry_model(slot: BriefSlotItem) -> list[str]:
    bridge = _bridge(slot.category)
    why = _distinct_why(slot)
    head = _facts(slot)
    if slot.community:
        head = f"[{slot.community}] {head}"
    return [
        "#### 模型是什么",
        "",
        head,
        "",
        "#### 相对常见基线的增量",
        "",
        why or bridge.contrast,
        "",
        "#### 许可 / 部署边界",
        "",
        "核对许可证、权重体量、推理成本与中文能力；没有实测数字时只讲「选型维度」，不夸大。",
        "",
        "#### 选型启发",
        "",
        bridge.takeaway,
        "",
    ]


def _entry_media(slot: BriefSlotItem) -> list[str]:
    bridge = _bridge(slot.category)
    why = _distinct_why(slot)
    return [
        "#### 帖子在说什么",
        "",
        _facts(slot),
        "",
        "#### 观点提炼（去情绪）",
        "",
        why or bridge.contrast,
        "",
        "#### 可信度一句话",
        "",
        "区分「亲历/数据」与「情绪/营销」；没有可核对来源的断言，讲解时降级为观点而非事实。",
        "",
        "#### 例子与启发",
        "",
        f"{bridge.example}",
        "",
        bridge.takeaway,
        "",
    ]


def _entry_stock(slot: BriefSlotItem) -> list[str]:
    bridge = _bridge(slot.category)
    why = _distinct_why(slot)
    return [
        "#### 发生了什么",
        "",
        _facts(slot),
        "",
        "#### 涉及标的 / 主题",
        "",
        f"主题归类：**{slot.category}**。讲解时点名新闻里出现的公司、指数或板块关键词，"
        "并标明哪些是明确标的、哪些只是行业联想。",
        "",
        "#### 情绪与分歧",
        "",
        why or bridge.contrast,
        "",
        "#### 对我们意味着什么（情报视角）",
        "",
        bridge.takeaway,
        "",
        f"可对照例子：{bridge.example}",
        "",
        "> 非投资建议：不据此给出买卖或仓位指令。",
        "",
    ]


def _entry_blocks(slot: BriefSlotItem, *, kind: str) -> list[str]:
    if kind == BriefKind.GITHUB:
        return _entry_github(slot)
    if kind == BriefKind.SCIENCE:
        return _entry_science(slot)
    if kind == BriefKind.EDUCATION:
        return _entry_science(slot)
    if kind == BriefKind.MODEL:
        return _entry_model(slot)
    if kind == BriefKind.MEDIA:
        return _entry_media(slot)
    if kind == BriefKind.STOCK:
        return _entry_stock(slot)
    return _entry_news(slot)


def _link_host(url: str) -> str:
    try:
        host = (urlparse(url).netloc or "").removeprefix("www.")
    except Exception:  # noqa: BLE001
        host = ""
    return host or "打开"


def _link_table(items: Sequence[IntelItem]) -> list[str]:
    lines = [
        "## 原文链接清单",
        "",
        "| # | 日期 | 主题 | 标题 | 链接 |",
        "| ---: | --- | --- | --- | --- |",
    ]
    ordered = sorted(
        items,
        key=lambda i: i.published_at.timestamp() if i.published_at else 0.0,
        reverse=True,
    )
    for idx, item in enumerate(ordered[:40], start=1):
        s = to_slot(item)
        title = s.title.replace("|", "/")
        # Short label — raw URLs blow out presentation table width.
        link = f"[{_link_host(s.url)}]({s.url})" if s.url else ""
        lines.append(f"| {idx} | {s.published} | {s.category} | {title} | {link} |")
    if not ordered:
        lines.append("|  |  |  | （暂无） |  |")
    lines.append("")
    return lines


def _render_kind_brief(
    *,
    kind: str,
    year_month: str,
    items: Sequence[IntelItem],
    period_type: str,
) -> str:
    scope = "本周" if period_type == "week" else "本月"
    cadence = "周总结" if period_type == "week" else "月总结"
    tops = _pick_top(items, 8)
    slots = [to_slot(i) for i in tops]
    counts = _category_counts(items)

    if kind == BriefKind.SCIENCE:
        title_label = "论文 / papers"
        duration = "约 8～10 分钟"
        guide = [
            "## 讲解口径（论文）",
            "",
            "- **问题**：这篇要解决什么（白话，少堆公式名）。",
            "- **对比**：做法与朴素 baseline 差在哪。",
            "- **例子**：给一个听众能记住的直观例子。",
            "- **启发**：教育或工程各落一句，不展开教案。",
            "",
        ]
        takeaways = [
            "1. **先问题后名词**：听众跟上问题，公式才有意义。",
            "2. **对比出知识**：讲清「比朴素做法好在哪」。",
            "3. **有链接才算数**：无法回溯原文的论文不进终稿。",
        ]
        section_title = "## 精选论文"
        with_stars = False
    elif kind == BriefKind.EDUCATION:
        title_label = "教育 / open courses"
        duration = "约 8～10 分钟"
        guide = [
            "## 讲解口径（教育）",
            "",
            "- **资源**：开放课/资料来自哪所高校或平台。",
            "- **适合谁**：前置知识与学习目标。",
            "- **对比**：相对自学路径多了什么结构。",
            "- **启发**：可迁到课程或自学清单的一点。",
            "",
        ]
        takeaways = [
            "1. **名校不等于适合**：先对齐学习者与目标。",
            "2. **路径比目录重要**：讲清怎么学完，而不是堆课名。",
            "3. **有链接才算数**：无法打开原文的资源不进终稿。",
        ]
        section_title = "## 精选教育资源"
        with_stars = False
    elif kind == BriefKind.MODEL:
        title_label = "模型 / model hubs"
        duration = "约 8～10 分钟"
        guide = [
            "## 讲解口径（模型）",
            "",
            "- **身份**：来自哪个社区、解决什么任务。",
            "- **增量**：相对常见基线强在哪（能力 / 成本 / 许可）。",
            "- **边界**：部署与合规要注意什么。",
            "- **启发**：课程案例或产品选型各落一句。",
            "",
        ]
        takeaways = [
            "1. **社区与任务先对齐**：HF / 魔搭只是货架，任务才是尺子。",
            "2. **热度不等于可落地**：下载量要配许可与复现成本一起看。",
            "3. **有链接才算数**：无法打开模型页的条目不进终稿。",
        ]
        section_title = "## 精选模型"
        with_stars = False
    elif kind == BriefKind.GITHUB:
        title_label = "好的产品 / 开源项目"
        duration = "约 8～10 分钟"
        guide = [
            "## 讲解口径（项目）",
            "",
            "- **是什么**：项目解决谁的什么痛点。",
            "- **巧妙处**：对比常见做法，讲清差异。",
            "- **上手与边界**：最小路径 + 不可忽视的约束。",
            "- **可迁移**：对我们产品/课程/工具链的一点启发。",
            "",
        ]
        takeaways = [
            "1. **热度≠可落地**：stars 只说明注意力。",
            "2. **先复现再引入**：30 分钟跑不通就先别写进工具链。",
            "3. **有链接才算数**：仓库或原文必须可打开。",
        ]
        section_title = "## 精选项目"
        with_stars = True
    elif kind == BriefKind.MEDIA:
        title_label = "自媒体"
        duration = "约 6 分钟"
        guide = [
            "## 讲解口径（自媒体）",
            "",
            "- **说什么**：先还原帖子事实与观点。",
            "- **提炼**：去掉情绪词后还剩什么判断。",
            "- **可信度**：亲历/数据 vs 营销/情绪。",
            "- **启发**：教育或工作可带走的一句。",
            "",
        ]
        takeaways = [
            "1. **观点不是事实**：讲解时要分开说。",
            "2. **例子帮记忆**：抽象判断配一个场景。",
            "3. **有链接才算数**：无法回溯的帖子不进终稿。",
        ]
        section_title = "## 精选动态"
        with_stars = False
    elif kind == BriefKind.STOCK:
        title_label = "股票 / 市场资讯"
        duration = "约 6～8 分钟"
        guide = [
            "## 讲解口径（股票资讯）",
            "",
            "- **事实**：这条资讯到底发生了什么。",
            "- **标的/主题**：涉及哪些公司、板块或宏观主题。",
            "- **情绪与分歧**：标题情绪 vs 可核对事实。",
            "- **情报启示**：观察清单与风险点（**非投资建议**）。",
            "",
        ]
        takeaways = [
            "1. **先事实后情绪**：情绪标签只是启发式。",
            "2. **有标的才可追踪**：能落到符号/主题再进观察清单。",
            "3. **有链接才算数**：无法回溯原文的不进终稿。",
        ]
        section_title = "## 精选资讯"
        with_stars = False
    else:
        title_label = "有趣的新闻"
        duration = "约 6～8 分钟"
        guide = [
            "## 讲解口径（新闻）",
            "",
            "- **事实**：这条新闻到底发生了什么。",
            "- **对比**：相对常见做法或上一阶段，增量在哪。",
            "- **例子**：给一个生活/工作中能感知的例子。",
            "- **启发**：对教育或业务的一句落地判断。",
            "",
        ]
        takeaways = [
            "1. **有增量才讲**：删掉专有名词仍有结构。",
            "2. **例子留住听众**：抽象判断要配场景。",
            "3. **有链接才算数**：无法回溯原文的不进终稿。",
        ]
        section_title = "## 精选新闻"
        with_stars = False

    lines: list[str] = [
        f"# {year_month} 汇总 · {title_label}（{cadence}）",
        "",
        f"> 投屏讲解终稿 · {duration}。按**原文发布时间**纳入{scope}条目；"
        f"每条结构服务「讲的人有的说、听的人有收获」。",
        "",
        *guide,
        f"## {scope}主题分布",
        "",
        _mermaid_pie(counts, f"{year_month} {title_label}"),
        "",
        _bar_table(counts),
        "",
        "---",
        "",
        section_title,
        "",
    ]

    if not slots:
        lines.append(f"{scope}暂无足够条目，完成采集后重新生成即可。")
        lines.append("")
    else:
        total = len(slots)
        for i, s in enumerate(slots, start=1):
            lines.extend(_item_separator(i, total))
            lines.extend(_header_meta(s, with_stars=with_stars))
            lines.extend(_entry_blocks(s, kind=kind))

    lines.extend(
        [
            "---",
            "",
            "## 带走的三句话",
            "",
            *takeaways,
            "",
            "---",
            "",
        ]
    )
    lines.extend(_link_table(items))
    if kind == BriefKind.STOCK:
        lines.extend(
            [
                "---",
                "",
                "> **免责声明**：本汇总仅基于公开资讯整理，供内部学习与讨论，"
                "**不构成投资建议**，不保证信息完整或及时，据此决策风险自担。",
                "",
            ]
        )
    return "\n".join(lines)


def render_monthly_brief(
    *,
    kind: str,
    year_month: str,
    items: Sequence[IntelItem],
    generated_at: datetime | None = None,
    period_type: str = "month",
    custom_prompt: str | None = None,
) -> str:
    _ = generated_at
    ordered = _prioritize_by_prompt(list(items), custom_prompt)
    body = _render_kind_brief(
        kind=kind, year_month=year_month, items=ordered, period_type=period_type
    )
    if custom_prompt and custom_prompt.strip():
        focus = custom_prompt.strip().replace("\n", " ")
        header = f"> **自定义聚焦**：{focus}\n\n"
        return header + body
    return body


def _prioritize_by_prompt(items: list[IntelItem], custom_prompt: str | None) -> list[IntelItem]:
    prompt = (custom_prompt or "").strip().lower()
    if not prompt or not items:
        return items
    tokens = [t for t in re.split(r"[\s,，、;；]+", prompt) if len(t) >= 2]

    def score(item: IntelItem) -> int:
        blob = f"{item.title} {item.summary or ''} {item.category or ''}".lower()
        return sum(1 for t in tokens if t in blob)

    return sorted(items, key=lambda i: (score(i), float(i.score or 0)), reverse=True)


def item_types_for_kind(kind: str) -> list[str]:
    if kind == BriefKind.GITHUB:
        return [ItemType.GITHUB_REPO, ItemType.GITHUB_RELEASE]
    if kind == BriefKind.SCIENCE:
        return [ItemType.PAPER]
    if kind == BriefKind.EDUCATION:
        return [ItemType.EDUCATION]
    if kind == BriefKind.MODEL:
        return [ItemType.MODEL]
    if kind == BriefKind.MEDIA:
        return [ItemType.MEDIA_POST]
    if kind == BriefKind.STOCK:
        return [ItemType.STOCK_NEWS]
    return [ItemType.NEWS]
