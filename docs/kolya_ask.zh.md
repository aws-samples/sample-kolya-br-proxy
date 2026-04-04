# 修复 403 的过程与 Claude Code 内部机制探索

## 背景

使用 `ANTHROPIC_API_KEY` + `ANTHROPIC_BASE_URL` 指向 kolya-br-proxy 时，Claude Code 偶发 403 Forbidden，而主请求（Opus）正常返回 200。

---

## 问题排查过程

### 第一步：发现两次请求

日志显示每轮对话都有两个 `POST /v1/messages` 请求，来源端口不同（客户端随机 TCP 源端口，正常现象）：

```
POST /v1/messages?beta=true  →  200 OK       (model=global.anthropic.claude-opus-4-6-v1)
POST /v1/messages?beta=true  →  403 Forbidden (model=claude-haiku-4-5-20251001)
```

用户并未主动发起 Haiku 请求。

### 第二步：确认发起方是 Claude Code 自身

Haiku 请求特征：
- `messages=1`，`input=17`，`output=381`
- 每隔数轮对话触发一次
- 用户没有配置 Haiku 模型

**结论**：这是 Claude Code 的 **auto-memory** 功能，用 `smallFastModel`（默认 Haiku）在后台更新 `MEMORY.md`。

### 第三步：定位 403 原因

`messages.py` 的 model 验证逻辑做**精确字符串匹配**：

```python
if request_data.model not in allowed_model_names:
    raise HTTPException(403, ...)
```

| 来源 | 格式 |
|------|------|
| Claude Code 请求 | `claude-haiku-4-5-20251001` |
| DB 存储（token 权限） | `global.anthropic.claude-haiku-4-5-20251001-v1:0` |

两者格式不同 → 匹配失败 → 403。

### 第四步：修复方案

在验证前 normalize 两边的 model 名称（去除 geo 前缀和版本后缀），验证通过后再把 `request_data.model` 替换成 DB 里的 Bedrock 格式，确保后续路由正确：

```python
def _normalize_model(name: str) -> str:
    import re
    for prefix in ("global.anthropic.", "us.anthropic.", "eu.anthropic.", "ap.anthropic.", "anthropic."):
        if name.startswith(prefix):
            name = name[len(prefix):]
            break
    return re.sub(r"-v\d+(?::\d+)?$", "", name)

normalized_requested = _normalize_model(request_data.model)
normalized_allowed = {_normalize_model(m) for m in allowed_model_names}

if normalized_requested not in normalized_allowed:
    raise HTTPException(403, ...)

# 替换为 DB 中的 Bedrock ID 用于路由
matched = next((m for m in allowed_model_names if _normalize_model(m) == normalized_requested), None)
if matched and matched != request_data.model:
    request_data.model = matched
```

---

## Claude Code 内部机制整理

### auto-memory

Claude Code 会定期用 `smallFastModel` 把对话内容写入 `MEMORY.md`，实现跨会话记忆。

- 存储路径：`~/.claude/projects/<路径编码>/memory/MEMORY.md`（路径中 `/` 替换为 `-`）
- 触发特征：`messages=1`，input token 极少（~17），output 为记忆内容（~381 token）
- 禁用方式：启动时加 `--bare` 或设置 `CLAUDE_CODE_SIMPLE=1`

### smallFastModel

控制后台轻量任务（auto-memory、对话压缩等）使用的模型，在 `~/.claude/settings.json` 中配置：

```json
{
  "smallFastModel": "global.anthropic.claude-haiku-4-5-20251001-v1:0"
}
```

注意：即使配置了 Bedrock 格式，Claude Code 发给 `ANTHROPIC_BASE_URL` 时仍使用 Anthropic 短格式（`claude-haiku-4-5-20251001`），因此代理需要做 normalize 处理。

### auto-compact（对话压缩）

当对话历史接近 context 上限时，Claude Code 用 Haiku 把历史压缩成摘要，替换原始历史。特征与 auto-memory 类似，但 input token 更多。

---

## 启动日志解读

```
INFO: 等待应用启动
10:18:22 - 启动 Kolya BR Proxy...
         - 数据库引擎初始化、表创建/验证完成
         - 限流器：Redis 分布式模式，全局 8.33 req/s（500 RPM），burst=10
           本地 fallback 2.78 req/s（÷3 pods）
         - BedrockClient 单例初始化完成
         - Profile 缓存刷新：23 个 inference profile，15 个本地 FM，91 个 fallback FM
         - 定价数据库已有 104 条记录

         [WARNING] mistral.mistral-small-2402-v1:0 未在缓存中找到，尝试本地 region
         [WARNING] qwen.qwen3-coder-next 未在缓存中找到，尝试本地 region
         - 回填：142 个本地可用模型缺少定价，检查参考 region ['us-east-1', 'us-west-2']
         - HTTP GET AWS 定价 JSON → 200 OK

         ... [以下为大量模型在 us-west-1 不可用，自动路由到 us-west-2 并从
              us-east-1 回填定价，涉及 meta/mistral/qwen/deepseek/nvidia/
              google/zai/moonshot/minimax/openai/amazon 等共 43 个模型] ...

         - 启动时回填了 43 条定价记录

         - Gemini 定价 tier-1（Google 官方）：17 个模型
         - Gemini 定价 tier-2（LiteLLM 补充）：新增 17 个模型
         - Gemini 定价 tier-3（静态 legacy）：新增 3 个模型
         - Gemini 定价保存完毕：共 37 个模型

         - 定时任务注册：
             刷新 Bedrock inference profile 缓存（01:50 UTC）
             从 AWS 更新模型定价（02:00 UTC）
             从 Google 更新 Gemini 模型定价（02:30 UTC）
         - 定价更新调度器已启动
         - Kolya BR Proxy 启动成功

INFO: 应用启动完成
INFO: Uvicorn 运行在 http://0.0.0.0:8000

--- [20 分钟后，第一批请求] ---

10:38:12 - [Haiku] 收到请求：model=claude-haiku-4-5-20251001，1 条消息，流式
         - Normalize 后路由到 global.anthropic.claude-haiku-4-5-20251001-v1:0
         → 200 OK ✅
         - Redis 连接成功（延迟连接，首次使用时建立）
         - Prompt cache: 1bp（system，5min TTL）

10:38:12 - [Opus] 收到请求：model=global.anthropic.claude-opus-4-6-v1，15 条消息，流式
10:38:13 - Bedrock 流式传输开始
10:38:17 - Bedrock 流式传输完成
         - Haiku 流式成功：耗时 5.061s，input=17，output=381（auto-memory 写入）
         - Prompt cache: 3bp（tools+system+msgs，5min TTL）
         → 200 OK ✅
         - 用量记录完成

10:38:22 - Bedrock 流式传输开始（Opus 实际对话）
10:39:44 - Bedrock 流式传输完成
         - Opus 流式成功：耗时 91.592s，input=16，output=3685
           cache_write=41658（首次写入 prompt cache，后续请求可复用）
         - 用量记录完成
```

---

## 相关文件

| 文件 | 说明 |
|------|------|
| `backend/app/api/anthropic/endpoints/messages.py` | model 归一化验证逻辑 |
| `backend/app/core/security.py` | `hash_token` 使用 SHA256 |
| `~/.claude/settings.json` | `smallFastModel` 配置 |
| `~/.claude/projects/.../memory/MEMORY.md` | auto-memory 存储位置 |
