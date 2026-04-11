# Benchmark

Locust-based load testing for kolya-br-proxy. Tests three API endpoints:
- **OpenAI** `/v1/chat/completions` (Bearer token)
- **Anthropic** `/v1/messages` (x-api-key)
- **Gemini** `/v1beta/models/{model}:streamGenerateContent` (x-goog-api-key)

## Setup

```bash
uv sync --group dev   # locust is in dev dependencies
```

## Usage

### Web UI (recommended)

```bash
BENCHMARK_API_TOKEN=sk-ant-api03_xxx \
  locust -f benchmark/locustfile.py --host https://api.kbp.kolya.fun
```

Open http://localhost:8089, set users and spawn rate, start.

### Headless

```bash
BENCHMARK_API_TOKEN=sk-ant-api03_xxx \
  locust -f benchmark/locustfile.py --host https://api.kbp.kolya.fun \
  --headless -u 10 -r 2 -t 5m --csv=benchmark/results/run
```

### Single endpoint

```bash
# Only OpenAI
locust -f benchmark/locustfile.py -T openai --host ...

# Only Anthropic
locust -f benchmark/locustfile.py -T anthropic --host ...

# Only Gemini
locust -f benchmark/locustfile.py -T gemini --host ...
```

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

## Custom Metrics

TTFT (Time to First Token) is reported as a custom `TTFT` request type in Locust.
It appears as a separate row in the statistics table and chart.

## Test Scenarios

| Scenario | Users | Duration | Purpose |
|----------|-------|----------|---------|
| Smoke test | 1 | 2min | Verify connectivity |
| Baseline | 3 | 5min | P50/P95/P99 latency |
| Concurrency | 10-25 | 10min | Throughput ceiling, error rates |
| Sustained | 5 | 30min | Stability, memory leaks |
| Mixed | 10 | 10min | All three endpoints |

## Rate Limits

The proxy enforces Bedrock rate limits (~500 RPM = ~8.3 req/s global).
Keep total users reasonable to avoid excessive 429 errors.
