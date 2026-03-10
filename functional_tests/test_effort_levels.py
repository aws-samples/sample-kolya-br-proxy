#!/usr/bin/env python3
"""
测试不同 thinking effort 配置对响应的影响。

通过 additionalModelRequestFields 传递 Anthropic 模型参数：
  - disabled:      无 thinking
  - effort_low:    thinking=enabled + budget_tokens + effort="low"
  - effort_medium: thinking=enabled + budget_tokens + effort="medium"
  - effort_high:   thinking=enabled + budget_tokens + effort="high"
  - adaptive:      thinking=adaptive（模型自行决定）

对比维度：
  1. 响应内容长度和质量
  2. Token 使用量（input/output）
  3. 响应时间
"""

import json
import time

from openai import OpenAI

# ============ 配置区域 ============
API_BASE_URL = "http://127.0.0.1:8000/v1"
API_TOKEN = ""
MODEL_NAME = "global.anthropic.claude-opus-4-6-v1"

# 测试问题 — 选择需要推理的问题以体现 thinking 差异
TEST_QUESTIONS = [
    {
        "name": "数学推理",
        "message": "A bat and a ball cost $1.10 in total. The bat costs $1.00 more than the ball. How much does the ball cost? Show your reasoning step by step.",
        "max_tokens": 2000,
    },
    {
        "name": "逻辑分析",
        "message": "If all roses are flowers, and some flowers fade quickly, can we conclude that some roses fade quickly? Explain your reasoning.",
        "max_tokens": 2000,
    },
]

# Thinking 配置级别
# additionalModelRequestFields 直接传给 Anthropic 模型，使用 snake_case
EFFORT_LEVELS = [
    {
        "name": "disabled",
        "label": "无 thinking",
        "fields": None,
    },
    {
        "name": "effort_low",
        "label": "thinking=enabled + effort=low",
        "fields": {
            "thinking": {"type": "enabled", "budget_tokens": 2000},
            "effort": "low",
        },
    },
    {
        "name": "effort_medium",
        "label": "thinking=enabled + effort=medium",
        "fields": {
            "thinking": {"type": "enabled", "budget_tokens": 2000},
            "effort": "medium",
        },
    },
    {
        "name": "effort_high",
        "label": "thinking=enabled + effort=high",
        "fields": {
            "thinking": {"type": "enabled", "budget_tokens": 5000},
            "effort": "high",
        },
    },
    {
        "name": "adaptive",
        "label": "thinking=adaptive (无 effort)",
        "fields": {"thinking": {"type": "adaptive"}},
    },
]

client = OpenAI(api_key=API_TOKEN, base_url=API_BASE_URL)


def run_non_streaming(question: dict, effort: dict) -> dict:
    """非流式请求，返回结果和统计信息。"""
    kwargs = dict(
        model=MODEL_NAME,
        messages=[{"role": "user", "content": question["message"]}],
        max_tokens=question["max_tokens"],
    )
    if effort["fields"]:
        kwargs["extra_body"] = {
            "bedrock_additional_model_request_fields": effort["fields"]
        }

    start = time.time()
    try:
        response = client.chat.completions.create(**kwargs)
        elapsed = time.time() - start
        content = response.choices[0].message.content or ""
        return {
            "success": True,
            "content": content,
            "prompt_tokens": response.usage.prompt_tokens,
            "completion_tokens": response.usage.completion_tokens,
            "total_tokens": response.usage.total_tokens,
            "elapsed": elapsed,
        }
    except Exception as e:
        return {"success": False, "error": str(e), "elapsed": time.time() - start}


def run_streaming(question: dict, effort: dict) -> dict:
    """流式请求，返回结果和统计信息。"""
    kwargs = dict(
        model=MODEL_NAME,
        messages=[{"role": "user", "content": question["message"]}],
        max_tokens=question["max_tokens"],
        stream=True,
    )
    if effort["fields"]:
        kwargs["extra_body"] = {
            "bedrock_additional_model_request_fields": effort["fields"]
        }

    start = time.time()
    try:
        stream = client.chat.completions.create(**kwargs)
        chunks = []
        for chunk in stream:
            delta = chunk.choices[0].delta.content
            if delta:
                chunks.append(delta)
        elapsed = time.time() - start
        content = "".join(chunks)
        return {
            "success": True,
            "content": content,
            "elapsed": elapsed,
        }
    except Exception as e:
        return {"success": False, "error": str(e), "elapsed": time.time() - start}


def print_separator(char="=", width=80):
    print(char * width)


def print_header(title: str):
    print()
    print_separator()
    print(f"  {title}")
    print_separator()


def print_result(label: str, result: dict, show_content: bool = True):
    if not result["success"]:
        print(f"  [{label}] ❌ 错误: {result['error']}")
        print(f"    耗时: {result['elapsed']:.2f}s")
        return

    content = result["content"]
    print(f"  [{label}]")
    if "prompt_tokens" in result:
        print(
            f"    Tokens: prompt={result['prompt_tokens']}, "
            f"completion={result['completion_tokens']}, "
            f"total={result['total_tokens']}"
        )
    print(f"    耗时: {result['elapsed']:.2f}s")
    print(f"    回复长度: {len(content)} 字符")
    if show_content:
        preview = content[:300].replace("\n", "\n    | ")
        print(f"    内容预览:")
        print(f"    | {preview}")
        if len(content) > 300:
            print(f"    | ... (共 {len(content)} 字符)")


def main():
    print()
    print("🧪 Thinking Effort 级别对比测试")
    print_separator()
    print(f"API: {API_BASE_URL}")
    print(f"模型: {MODEL_NAME}")
    print(f"测试级别: {', '.join(e['name'] for e in EFFORT_LEVELS)}")

    # ---- 非流式测试 ----
    print_header("非流式 (Non-Streaming) 测试")

    for q in TEST_QUESTIONS:
        print(f"\n📝 问题: {q['name']}")
        print(f"   \"{q['message'][:60]}...\"")
        print()

        results = {}
        for effort in EFFORT_LEVELS:
            result = run_non_streaming(q, effort)
            results[effort["name"]] = result
            print_result(effort["label"], result)
            print()

        # 对比摘要
        print("  📊 对比摘要:")
        successful = {k: v for k, v in results.items() if v["success"]}
        if len(successful) >= 2:
            names = list(successful.keys())
            for name in names:
                r = successful[name]
                tokens = r.get("total_tokens", "N/A")
                print(
                    f"    {name:15s} → "
                    f"回复 {len(r['content']):>5} 字符, "
                    f"tokens={tokens}, "
                    f"耗时 {r['elapsed']:.2f}s"
                )
        print_separator("-")

    # ---- 流式测试 ----
    print_header("流式 (Streaming) 测试")

    for q in TEST_QUESTIONS:
        print(f"\n📝 问题: {q['name']}")
        print(f"   \"{q['message'][:60]}...\"")
        print()

        results = {}
        for effort in EFFORT_LEVELS:
            result = run_streaming(q, effort)
            results[effort["name"]] = result
            print_result(effort["label"], result)
            print()

        # 对比摘要
        print("  📊 对比摘要:")
        successful = {k: v for k, v in results.items() if v["success"]}
        if len(successful) >= 2:
            for name, r in successful.items():
                print(
                    f"    {name:15s} → "
                    f"回复 {len(r['content']):>5} 字符, "
                    f"耗时 {r['elapsed']:.2f}s"
                )
        print_separator("-")

    # ---- 总结 ----
    print_header("测试完成")
    print("预期行为:")
    print("  - disabled:      无 thinking，回复较短，token 较少，速度最快")
    print("  - effort_low:    少量 thinking，快速回复")
    print("  - effort_medium: 中等 thinking，平衡质量和速度")
    print("  - effort_high:   充分 thinking，回复更详细准确，token 更多")
    print("  - adaptive:      模型自行决定 thinking 量")
    print()


if __name__ == "__main__":
    main()
