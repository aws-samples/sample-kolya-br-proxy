"""Benchmark configuration from environment variables."""

import os
import sys


def _require_env(name: str) -> str:
    val = os.getenv(name)
    if not val:
        print(f"ERROR: {name} environment variable is required", file=sys.stderr)
        sys.exit(1)
    return val


API_TOKEN: str = _require_env("BENCHMARK_API_TOKEN")

# Models (defaults to Sonnet for Bedrock endpoints, Flash for Gemini)
OPENAI_MODEL = os.getenv(
    "BENCHMARK_OPENAI_MODEL",
    "global.anthropic.claude-sonnet-4-20250514-v1:0",
)
ANTHROPIC_MODEL = os.getenv(
    "BENCHMARK_ANTHROPIC_MODEL",
    "global.anthropic.claude-sonnet-4-20250514-v1:0",
)
GEMINI_MODEL = os.getenv("BENCHMARK_GEMINI_MODEL", "gemini-2.5-flash")

# Request parameters
MAX_TOKENS = int(os.getenv("BENCHMARK_MAX_TOKENS", "256"))
PROMPT_SIZE = os.getenv("BENCHMARK_PROMPT_SIZE", "small")  # small | medium | large
TEMPERATURE = float(os.getenv("BENCHMARK_TEMPERATURE", "0.7"))
