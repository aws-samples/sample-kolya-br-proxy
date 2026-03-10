#!/usr/bin/env python3
"""
测试 Bedrock 模型访问和请求格式

这个脚本会：
1. 检查哪些模型在 AWS Bedrock 中可用
2. 测试不同模型的调用
3. 诊断错误原因
"""

import asyncio
import json
import sys
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent / "backend"))

import aioboto3
from botocore.config import Config
from botocore.exceptions import ClientError


async def list_available_models(region: str = "us-west-2"):
    """列出所有可用的 Bedrock 模型"""
    print(f"\n{'='*60}")
    print(f"检查 {region} 区域的可用模型...")
    print(f"{'='*60}\n")
    
    session = aioboto3.Session()
    config = Config(region_name=region)
    
    try:
        async with session.client("bedrock", region_name=region, config=config) as client:
            # 列出基础模型
            response = await client.list_foundation_models()
            models = response.get("modelSummaries", [])
            
            print(f"找到 {len(models)} 个基础模型:\n")
            
            # 按提供商分组
            by_provider = {}
            for model in models:
                provider = model.get("providerName", "Unknown")
                if provider not in by_provider:
                    by_provider[provider] = []
                by_provider[provider].append(model)
            
            for provider, provider_models in sorted(by_provider.items()):
                print(f"\n{provider}:")
                for model in provider_models:
                    model_id = model.get("modelId", "")
                    model_name = model.get("modelName", "")
                    status = "✅" if model.get("modelLifecycle", {}).get("status") == "ACTIVE" else "❌"
                    print(f"  {status} {model_id}")
                    print(f"     名称: {model_name}")
                    
                    # 检查是否需要申请访问权限
                    inference_types = model.get("inferenceTypesSupported", [])
                    if inference_types:
                        print(f"     支持: {', '.join(inference_types)}")
            
            return models
            
    except ClientError as e:
        error_code = e.response.get("Error", {}).get("Code")
        error_msg = e.response.get("Error", {}).get("Message")
        print(f"❌ 错误: {error_code} - {error_msg}")
        return []
    except Exception as e:
        print(f"❌ 未知错误: {e}")
        return []


async def test_model_invoke(model_id: str, region: str = "us-west-2"):
    """测试调用特定模型"""
    print(f"\n{'='*60}")
    print(f"测试模型: {model_id}")
    print(f"{'='*60}\n")
    
    session = aioboto3.Session()
    config = Config(region_name=region, retries={"max_attempts": 1, "mode": "standard"})
    
    # 根据模型类型构建不同的请求体
    if "anthropic" in model_id:
        # Anthropic Messages API 格式
        body = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 100,
            "messages": [
                {"role": "user", "content": "Say 'Hello' in one word"}
            ]
        }
        print("使用 Anthropic Messages API 格式")
    elif "mistral" in model_id:
        # Mistral 格式
        body = {
            "prompt": "<s>[INST] Say 'Hello' in one word [/INST]",
            "max_tokens": 100,
            "temperature": 0.7
        }
        print("使用 Mistral 格式")
    elif "meta.llama" in model_id:
        # Llama 格式
        body = {
            "prompt": "Say 'Hello' in one word",
            "max_gen_len": 100,
            "temperature": 0.7
        }
        print("使用 Llama 格式")
    elif "amazon.nova" in model_id or "amazon.titan" in model_id:
        # Amazon 格式
        body = {
            "inputText": "Say 'Hello' in one word",
            "textGenerationConfig": {
                "maxTokenCount": 100,
                "temperature": 0.7
            }
        }
        print("使用 Amazon 格式")
    elif "cohere" in model_id:
        # Cohere 格式
        body = {
            "prompt": "Say 'Hello' in one word",
            "max_tokens": 100,
            "temperature": 0.7
        }
        print("使用 Cohere 格式")
    else:
        # 默认尝试 Anthropic 格式
        body = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 100,
            "messages": [
                {"role": "user", "content": "Say 'Hello' in one word"}
            ]
        }
        print("使用默认 Anthropic 格式")
    
    print(f"请求体: {json.dumps(body, indent=2)}\n")
    
    try:
        async with session.client("bedrock-runtime", region_name=region, config=config) as client:
            response = await client.invoke_model(
                modelId=model_id,
                body=json.dumps(body),
                contentType="application/json",
                accept="application/json"
            )
            
            response_body = json.loads(await response["body"].read())
            print(f"✅ 成功! 响应:")
            print(json.dumps(response_body, indent=2, ensure_ascii=False))
            return True
            
    except ClientError as e:
        error_code = e.response.get("Error", {}).get("Code")
        error_msg = e.response.get("Error", {}).get("Message")
        print(f"❌ 调用失败:")
        print(f"   错误代码: {error_code}")
        print(f"   错误信息: {error_msg}")
        
        if error_code == "AccessDeniedException":
            print(f"\n💡 解决方案: 需要在 AWS Bedrock Console 中申请此模型的访问权限")
            print(f"   访问: https://console.aws.amazon.com/bedrock/home?region={region}#/modelaccess")
        elif error_code == "ValidationException":
            print(f"\n💡 解决方案: 请求格式不正确，需要使用该模型特定的 API 格式")
        
        return False
    except Exception as e:
        print(f"❌ 未知错误: {e}")
        import traceback
        traceback.print_exc()
        return False


async def main():
    """主函数"""
    region = "us-west-2"
    
    # 1. 列出所有可用模型
    models = await list_available_models(region)
    
    if not models:
        print("\n无法获取模型列表，请检查 AWS 凭证和权限")
        return
    
    # 2. 测试几个常见模型
    test_models = [
        "anthropic.claude-3-5-sonnet-20241022-v2:0",  # Anthropic
        "mistral.mistral-7b-instruct-v0:2",  # Mistral
        "meta.llama3-8b-instruct-v1:0",  # Llama
        "us.amazon.nova-micro-v1:0",  # Nova (需要跨区域前缀)
    ]
    
    print(f"\n\n{'='*60}")
    print("开始测试模型调用...")
    print(f"{'='*60}")
    
    results = {}
    for model_id in test_models:
        success = await test_model_invoke(model_id, region)
        results[model_id] = success
        await asyncio.sleep(1)  # 避免请求过快
    
    # 3. 总结
    print(f"\n\n{'='*60}")
    print("测试总结")
    print(f"{'='*60}\n")
    
    for model_id, success in results.items():
        status = "✅ 成功" if success else "❌ 失败"
        print(f"{status} - {model_id}")
    
    print("\n\n建议:")
    print("1. 如果看到 AccessDeniedException，需要在 AWS Console 中申请模型访问权限")
    print("2. 如果看到 ValidationException，说明代码需要支持该模型的特定 API 格式")
    print("3. 当前代码只支持 Anthropic Messages API 格式")


if __name__ == "__main__":
    asyncio.run(main())
