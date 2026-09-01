"""Category classifier + text helpers."""

from __future__ import annotations

from bagel.pipeline.category import classify_title
from bagel.pipeline.textutil import strip_html, truncate


def test_strip_html_and_truncate() -> None:
    assert strip_html("<p>Hello <b>AI</b></p>") == "Hello AI"
    assert truncate("a" * 200, 20).endswith("…")
    assert len(truncate("短文本", 20)) == 3


def test_classify_title_reuses_fixed_categories() -> None:
    assert classify_title("OpenAI 发布新大模型 GPT") == "大模型/LLM"
    assert classify_title("多智能体 AI Agent 框架") == "Agent"
    assert classify_title("GraphRAG 检索增强实践") == "RAG"
    assert classify_title("今天天气不错") == "其他"
    # Similar wording maps to same bucket
    assert classify_title("LLM 推理加速") == classify_title("大语言模型推理优化")
