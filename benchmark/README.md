# Benchmark

Locust-based performance testing for kolya-br-proxy. Tests API endpoints for latency baseline, TTFT, throughput, and stability.

Supported endpoints:
- **OpenAI** `/v1/chat/completions` (Bearer token)
- **Anthropic** `/v1/messages` (x-api-key)
- **Gemini** `/v1beta/models/{model}:streamGenerateContent` (x-goog-api-key)

> **Note:** Anthropic models (e.g. `claude-sonnet-4-6`) do not support the Gemini protocol. Only use `GeminiUser` with actual Gemini models.

## Setup

```bash
uv sync --group dev   # locust is in dev dependencies
mkdir -p benchmark/results
```

## Quick Start

### 1. Set environment variables

```bash
export BENCHMARK_API_TOKEN=sk-ant-api03_YOUR_TOKEN
export BENCHMARK_OPENAI_MODEL=global.anthropic.claude-sonnet-4-6-v1:0
export BENCHMARK_ANTHROPIC_MODEL=global.anthropic.claude-sonnet-4-6-v1:0
```

For extended thinking scenarios:

```bash
export BENCHMARK_PROMPT_SIZE=large
export BENCHMARK_THINKING_BUDGET=10000
export BENCHMARK_MAX_TOKENS=16384   # must be > BENCHMARK_THINKING_BUDGET
```

### 2. Smoke test (verify connectivity, confirm 0 Fails)

```bash
# Headless — quick validation
uv run locust -f benchmark/locustfile.py --host https://api.kbp.kolya.fun \
  --headless -u 1 -r 1 -t 30s OpenAIUser

# Web UI — visual validation
uv run locust -f benchmark/locustfile.py --host https://api.kbp.kolya.fun AnthropicUser
# Open http://localhost:8089, set users=1, ramp up=1, run time=10s
```

### 3. Latency baseline + TTFT (single endpoint)

```bash
uv run locust -f benchmark/locustfile.py --host https://api.kbp.kolya.fun \
  --csv=benchmark/results/openai OpenAIUser

uv run locust -f benchmark/locustfile.py --host https://api.kbp.kolya.fun \
  --csv=benchmark/results/anthropic AnthropicUser
```

Web UI: users=3, ramp up=1, run time=5m.

### 4. Mixed load (multiple endpoints together)

```bash
uv run locust -f benchmark/locustfile.py --host https://api.kbp.kolya.fun \
  --csv=benchmark/results/mixed OpenAIUser AnthropicUser
```

Web UI: users=5, ramp up=1, run time=5m.

### 5. Stability test

Run with real business scenarios for extended periods to observe latency drift, memory leaks, or connection pool exhaustion.

```bash
uv run locust -f benchmark/locustfile.py --host https://api.kbp.kolya.fun \
  --csv=benchmark/results/stability OpenAIUser AnthropicUser
```

Web UI: users=3, ramp up=1, run time=30m.

### 6. Throughput limit (ramp up)

```bash
uv run locust -f benchmark/locustfile.py --host https://api.kbp.kolya.fun \
  --csv=benchmark/results/rampup OpenAIUser AnthropicUser
```

Start at 3 users, manually increase to 5 → 10 → 20 in Web UI. Watch for the error rate inflection point.

### 7. View results

CSV files are saved in `benchmark/results/`:

| File | Content |
|------|---------|
| `*_stats.csv` | Latency, RPS, error rate summary |
| `*_stats_history.csv` | Time series data |
| `*_failures.csv` | Failure details |

Combine with **CloudWatch Dashboard** to view proxy-side metrics + X-Ray traces, and determine whether bottlenecks are in the proxy or Bedrock.

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `BENCHMARK_API_TOKEN` | (required) | Proxy API token (`sk-ant-api03_...`) |
| `BENCHMARK_OPENAI_MODEL` | `global.anthropic.claude-sonnet-4-20250514-v1:0` | Model for OpenAI endpoint |
| `BENCHMARK_ANTHROPIC_MODEL` | `global.anthropic.claude-sonnet-4-20250514-v1:0` | Model for Anthropic endpoint |
| `BENCHMARK_GEMINI_MODEL` | `gemini-2.5-flash` | Model for Gemini endpoint |
| `BENCHMARK_MAX_TOKENS` | `256` | Max output tokens |
| `BENCHMARK_PROMPT_SIZE` | `small` | Prompt size: `small` (~50 tokens), `medium` (~500), `large` (~2000) |
| `BENCHMARK_TEMPERATURE` | `0.7` | Sampling temperature |
| `BENCHMARK_THINKING_BUDGET` | `0` | Extended thinking budget tokens (0=disabled, Anthropic only) |

## Custom Metrics

- **TTFT** (Time to First Token) — reported as a custom `TTFT` request type in Locust, appears as a separate row in statistics.
- **TTFT thinking** — when extended thinking is enabled, time to first thinking token is reported separately.

## Rate Limits

The proxy enforces Bedrock rate limits (~500 RPM = ~8.3 req/s global).
Keep total users reasonable to avoid excessive 429 errors.
