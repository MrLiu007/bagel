"""Fixed taxonomy category classifier — never invent unbounded labels."""

from __future__ import annotations

from bagel.pipeline.textutil import strip_html

# Canonical categories only. Aliases map similar wording onto one label.
CATEGORIES: tuple[str, ...] = (
    "大模型/LLM",
    "Agent",
    "RAG",
    "多模态",
    "开源发布",
    "推理/训练",
    "机器人/具身",
    "评测/基准",
    "教育应用",
    "行业动态",
    "其他",
)

# Longer / more specific aliases first within each group.
_ALIAS_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "大模型/LLM",
        (
            "large language model",
            "大语言模型",
            "foundation model",
            "chatgpt",
            "openai",
            "claude",
            "gemini",
            "deepseek",
            "qwen",
            "llama",
            "大模型",
            "llm",
            "gpt",
        ),
    ),
    (
        "Agent",
        (
            "multi-agent",
            "多智能体",
            "ai agent",
            "autogen",
            "crewai",
            "langchain",
            "智能体",
            "agent",
        ),
    ),
    (
        "RAG",
        (
            "retrieval augmented",
            "graphrag",
            "graph rag",
            "vector database",
            "向量数据库",
            "embedding",
            "rag",
            "检索增强",
        ),
    ),
    (
        "多模态",
        (
            "vision-language",
            "vision language",
            "multimodal",
            "多模态",
            "vlm",
            "文生图",
            "图像生成",
        ),
    ),
    (
        "开源发布",
        (
            "open source",
            "opensource",
            "github release",
            "正式发布",
            "开源",
            "release",
            "发布",
        ),
    ),
    (
        "推理/训练",
        (
            "fine-tuning",
            "finetune",
            "quantization",
            "推理引擎",
            "tensorrt",
            "vllm",
            "lora",
            "训练",
            "推理",
            "inference",
        ),
    ),
    (
        "机器人/具身",
        (
            "embodied ai",
            "embodied",
            "具身智能",
            "robotics",
            "机器人",
            "ros2",
            "vla",
        ),
    ),
    (
        "评测/基准",
        (
            "benchmark",
            "lm-eval",
            "评测",
            "基准",
            "排行榜",
            "leaderboard",
        ),
    ),
    (
        "教育应用",
        (
            "ai education",
            "edu agent",
            "智能教学",
            "教育",
            "tutor",
            "培训",
        ),
    ),
    (
        "行业动态",
        (
            "融资",
            "并购",
            "上市",
            "政策",
            "监管",
            "industry",
            "startup",
            "创业",
        ),
    ),
)


def classify_title(title: str, summary: str | None = None) -> str:
    """Map title/summary onto one fixed category (similarity via aliases)."""
    text = f"{strip_html(title)}\n{strip_html(summary)}".lower()
    best: str | None = None
    best_len = -1
    for category, aliases in _ALIAS_GROUPS:
        for alias in aliases:
            needle = alias.lower()
            if needle in text and len(needle) > best_len:
                best = category
                best_len = len(needle)
    return best or "其他"


def list_categories() -> list[str]:
    return list(CATEGORIES)
