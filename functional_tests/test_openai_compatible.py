#!/usr/bin/env python3
"""
使用OpenAI SDK测试API Token
支持自定义header和body参数（包括effort参数）
"""

from openai import OpenAI
import json

# ============ 配置区域 ============
API_BASE_URL = "http://127.0.0.1:8000/v1"
API_TOKEN = ""  # 替换为你的API token
MODEL_NAME = "global.anthropic.claude-opus-4-6-v1"  # Opus 4.6模型

# ============ 初始化OpenAI客户端 ============
client = OpenAI(
    api_key=API_TOKEN,
    base_url=API_BASE_URL
)

print("\n🚀 OpenAI Compatible API 测试")
print("=" * 60)
print(f"Base URL: {API_BASE_URL}")
print(f"模型: {MODEL_NAME}")
print(f"Token: {'*' * 20} (hidden)")


# ============ 测试函数 ============

def test_basic_chat():
    """测试1: 基础聊天"""
    print("\n" + "="*60)
    print("测试 1: 基础聊天请求")
    print("="*60)

    try:
        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "user", "content": "Hello! Please respond in one sentence."}
            ],
            max_tokens=100,
            temperature=0.7
        )

        print(f"✅ 成功!")
        print(f"模型: {response.model}")
        print(f"回复: {response.choices[0].message.content}")
        print(f"Token使用: prompt={response.usage.prompt_tokens}, completion={response.usage.completion_tokens}")

    except Exception as e:
        print(f"❌ 错误: {str(e)}")


def test_with_thinking_in_body():
    """测试2: 通过extra_body传递thinking参数（adaptive模式）"""
    print("\n" + "="*60)
    print("测试 2: 使用 extra_body 传递 thinking 参数 (adaptive)")
    print("="*60)

    try:
        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "user", "content": "Explain quantum computing in simple terms."}
            ],
            max_tokens=2000,
            # Bedrock Converse API: thinking goes in additionalModelRequestFields
            # "adaptive" type requires no extra fields (effort is NOT supported on Bedrock)
            extra_body={
                "bedrock_additional_model_request_fields": {
                    "thinking": {
                        "type": "adaptive"
                    }
                }
            }
        )

        print(f"✅ 成功!")
        print(f"使用参数: thinking=adaptive")
        print(f"回复: {response.choices[0].message.content[:200]}...")
        print(f"Token使用: prompt={response.usage.prompt_tokens}, completion={response.usage.completion_tokens}")

    except Exception as e:
        print(f"❌ 错误: {str(e)}")


def test_with_thinking_in_headers():
    """测试3: 通过extra_headers传递thinking参数"""
    print("\n" + "="*60)
    print("测试 3: 使用 extra_headers 传递 thinking 参数 (adaptive)")
    print("="*60)

    try:
        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "user", "content": "What is 2+2? Answer briefly."}
            ],
            max_tokens=500,
            extra_headers={
                "X-Bedrock-Additional-Fields": json.dumps({
                    "thinking": {
                        "type": "adaptive"
                    }
                })
            }
        )

        print(f"✅ 成功!")
        print(f"使用Headers: thinking=adaptive")
        print(f"回复: {response.choices[0].message.content}")
        print(f"Token使用: prompt={response.usage.prompt_tokens}, completion={response.usage.completion_tokens}")

    except Exception as e:
        print(f"❌ 错误: {str(e)}")


def test_streaming():
    """测试4: 流式响应"""
    print("\n" + "="*60)
    print("测试 4: 流式响应 (Stream)")
    print("="*60)

    try:
        stream = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "user", "content": "Say hello in 3 different languages."}
            ],
            max_tokens=100,
            stream=True
        )

        print(f"✅ 流式响应:")
        print("-" * 60)
        for chunk in stream:
            if chunk.choices[0].delta.content:
                print(chunk.choices[0].delta.content, end='', flush=True)
        print("\n" + "-" * 60)

    except Exception as e:
        print(f"❌ 错误: {str(e)}")


def test_streaming_with_thinking():
    """测试5: 流式响应 + thinking参数"""
    print("\n" + "="*60)
    print("测试 5: 流式响应 + thinking 参数 (adaptive)")
    print("="*60)

    try:
        stream = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "user", "content": "Count from 1 to 5."}
            ],
            max_tokens=200,
            stream=True,
            extra_body={
                "bedrock_additional_model_request_fields": {
                    "thinking": {
                        "type": "adaptive"
                    }
                }
            }
        )

        print(f"✅ 流式响应 (thinking=adaptive):")
        print("-" * 60)
        for chunk in stream:
            if chunk.choices[0].delta.content:
                print(chunk.choices[0].delta.content, end='', flush=True)
        print("\n" + "-" * 60)

    except Exception as e:
        print(f"❌ 错误: {str(e)}")


def test_list_models():
    """测试6: 列出可用模型"""
    print("\n" + "="*60)
    print("测试 6: 列出可用模型")
    print("="*60)

    try:
        models = client.models.list()
        print(f"✅ 成功! 找到 {len(models.data)} 个模型:")
        for model in models.data[:5]:  # 只显示前5个
            print(f"  - {model.id}")
        if len(models.data) > 5:
            print(f"  ... 还有 {len(models.data) - 5} 个模型")

    except Exception as e:
        print(f"❌ 错误: {str(e)}")


# ============ 主函数 ============

def main():
    if API_TOKEN == "your-api-token-here":
        print("❌ 错误: 请先在脚本中配置 API_TOKEN")
        print("   修改脚本顶部的 API_TOKEN 变量")
        return

    try:
        test_basic_chat()
        test_with_thinking_in_body()
        test_with_thinking_in_headers()
        test_streaming()
        test_streaming_with_thinking()
        test_list_models()

        print("\n" + "="*60)
        print("✅ 所有测试完成!")
        print("="*60)

    except KeyboardInterrupt:
        print("\n\n⚠️  测试被用户中断")


if __name__ == "__main__":
    main()
