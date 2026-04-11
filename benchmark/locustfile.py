"""Locust benchmark for kolya-br-proxy — three API endpoints.

Usage:
    # Web UI
    BENCHMARK_API_TOKEN=sk-ant-api03_xxx locust -f benchmark/locustfile.py --host https://api.kbp.kolya.fun

    # Headless
    BENCHMARK_API_TOKEN=sk-ant-api03_xxx locust -f benchmark/locustfile.py \
        --host https://api.kbp.kolya.fun --headless -u 10 -r 2 -t 5m --csv=results/run

    # Single endpoint
    BENCHMARK_API_TOKEN=sk-ant-api03_xxx locust -f benchmark/locustfile.py \
        --host https://api.kbp.kolya.fun -T openai
"""

import json

from locust import HttpUser, between, tag, task

from benchmark.config import (
    ANTHROPIC_MODEL,
    API_TOKEN,
    GEMINI_MODEL,
    MAX_TOKENS,
    OPENAI_MODEL,
    PROMPT_SIZE,
    TEMPERATURE,
)
from benchmark.prompts import anthropic_payload, gemini_payload, openai_messages
from benchmark.sse_client import fire_ttft_event, stream_and_measure


# ---------------------------------------------------------------------------
# OpenAI-compatible endpoint
# ---------------------------------------------------------------------------


class OpenAIUser(HttpUser):
    """Load test /v1/chat/completions (OpenAI format)."""

    wait_time = between(1, 3)
    weight = 1

    def on_start(self):
        self.client.headers.update(
            {
                "Authorization": f"Bearer {API_TOKEN}",
                "Content-Type": "application/json",
            }
        )
        self._messages = openai_messages(PROMPT_SIZE)

    def _body(self, stream: bool) -> dict:
        return {
            "model": OPENAI_MODEL,
            "messages": self._messages,
            "max_tokens": MAX_TOKENS,
            "temperature": TEMPERATURE,
            "stream": stream,
        }

    @tag("openai")
    @task(3)
    def stream_chat(self):
        name = "/v1/chat/completions [stream]"
        with self.client.post(
            "/v1/chat/completions",
            json=self._body(stream=True),
            stream=True,
            catch_response=True,
            name=name,
        ) as resp:
            if resp.status_code != 200:
                resp.failure(f"HTTP {resp.status_code}")
                return
            result = stream_and_measure(resp, "openai")
            if result["error"]:
                resp.failure(result["error"])
            else:
                resp.success()
            if result["ttft_s"] is not None:
                fire_ttft_event(name, result["ttft_s"] * 1000, self.environment)

    @tag("openai")
    @task(1)
    def nonstream_chat(self):
        with self.client.post(
            "/v1/chat/completions",
            json=self._body(stream=False),
            catch_response=True,
            name="/v1/chat/completions [non-stream]",
        ) as resp:
            if resp.status_code != 200:
                resp.failure(f"HTTP {resp.status_code}")
                return
            try:
                data = resp.json()
                if "choices" not in data:
                    resp.failure("No choices in response")
                else:
                    resp.success()
            except json.JSONDecodeError:
                resp.failure("Invalid JSON response")


# ---------------------------------------------------------------------------
# Anthropic Messages endpoint
# ---------------------------------------------------------------------------


class AnthropicUser(HttpUser):
    """Load test /v1/messages (Anthropic format)."""

    wait_time = between(1, 3)
    weight = 1

    def on_start(self):
        self.client.headers.update(
            {
                "x-api-key": API_TOKEN,
                "Content-Type": "application/json",
                "anthropic-version": "2023-06-01",
            }
        )

    def _body(self, stream: bool) -> dict:
        payload = anthropic_payload(PROMPT_SIZE, ANTHROPIC_MODEL, MAX_TOKENS)
        payload["stream"] = stream
        return payload

    @tag("anthropic")
    @task(3)
    def stream_messages(self):
        name = "/v1/messages [stream]"
        with self.client.post(
            "/v1/messages",
            json=self._body(stream=True),
            stream=True,
            catch_response=True,
            name=name,
        ) as resp:
            if resp.status_code != 200:
                resp.failure(f"HTTP {resp.status_code}")
                return
            result = stream_and_measure(resp, "anthropic")
            if result["error"]:
                resp.failure(result["error"])
            else:
                resp.success()
            if result["ttft_s"] is not None:
                fire_ttft_event(name, result["ttft_s"] * 1000, self.environment)

    @tag("anthropic")
    @task(1)
    def nonstream_messages(self):
        with self.client.post(
            "/v1/messages",
            json=self._body(stream=False),
            catch_response=True,
            name="/v1/messages [non-stream]",
        ) as resp:
            if resp.status_code != 200:
                resp.failure(f"HTTP {resp.status_code}")
                return
            try:
                data = resp.json()
                if "content" not in data:
                    resp.failure("No content in response")
                else:
                    resp.success()
            except json.JSONDecodeError:
                resp.failure("Invalid JSON response")


# ---------------------------------------------------------------------------
# Gemini native endpoint
# ---------------------------------------------------------------------------


class GeminiUser(HttpUser):
    """Load test /v1beta/models/{model}:generateContent (Gemini format)."""

    wait_time = between(1, 3)
    weight = 1

    def on_start(self):
        self.client.headers.update(
            {
                "x-goog-api-key": API_TOKEN,
                "Content-Type": "application/json",
            }
        )
        self._model = GEMINI_MODEL

    @tag("gemini")
    @task(3)
    def stream_generate(self):
        name = f"/v1beta/models/{self._model}:streamGenerateContent"
        url = f"/v1beta/models/{self._model}:streamGenerateContent?alt=sse"
        body = gemini_payload(PROMPT_SIZE)
        with self.client.post(
            url,
            json=body,
            stream=True,
            catch_response=True,
            name=name,
        ) as resp:
            if resp.status_code != 200:
                resp.failure(f"HTTP {resp.status_code}")
                return
            result = stream_and_measure(resp, "gemini")
            if result["error"]:
                resp.failure(result["error"])
            else:
                resp.success()
            if result["ttft_s"] is not None:
                fire_ttft_event(name, result["ttft_s"] * 1000, self.environment)

    @tag("gemini")
    @task(1)
    def nonstream_generate(self):
        url = f"/v1beta/models/{self._model}:generateContent"
        body = gemini_payload(PROMPT_SIZE)
        with self.client.post(
            url,
            json=body,
            catch_response=True,
            name=f"/v1beta/models/{self._model}:generateContent",
        ) as resp:
            if resp.status_code != 200:
                resp.failure(f"HTTP {resp.status_code}")
                return
            try:
                data = resp.json()
                if "candidates" not in data:
                    resp.failure("No candidates in response")
                else:
                    resp.success()
            except json.JSONDecodeError:
                resp.failure("Invalid JSON response")
