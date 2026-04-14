"""
AWS Bedrock client service.

Anthropic models use InvokeModel / InvokeModelWithResponseStream so that
native parameters (thinking, effort, prompt caching, etc.) are passed
through directly in the Messages API body.

Non-Anthropic models (Nova, DeepSeek, etc.) use the Bedrock Converse /
ConverseStream API, which is model-agnostic and handles format conversion
automatically.
"""

import asyncio
import json
import logging
import time
from typing import AsyncGenerator, Optional

import aioboto3
from botocore.config import Config
from botocore.exceptions import ClientError
from opentelemetry import trace

from app.core.config import get_settings
from app.core.metrics import emit_bedrock_call_metrics, emit_failover_metrics
from app.schemas.bedrock import (
    BedrockContentBlock,
    BedrockRequest,
    BedrockResponse,
    BedrockStreamEvent,
    BedrockUsage,
)

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)


class FirstContentTimeoutError(Exception):
    """Raised when no content chunk arrives within the configured timeout."""

    pass


class LocalTokenBucket:
    """Per-pod in-memory token bucket rate limiter.

    Used as the primary rate limiter when Redis is not configured,
    or as fallback when Redis is unavailable.
    """

    def __init__(self, rate: float, capacity: int):
        self._rate = rate
        self._capacity = capacity
        self._tokens = float(capacity)
        self._last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        """Wait until a token is available, then consume one."""
        while True:
            async with self._lock:
                self._refill()
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return
                wait = (1.0 - self._tokens) / self._rate
            await asyncio.sleep(wait)

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._tokens = min(self._capacity, self._tokens + elapsed * self._rate)
        self._last_refill = now


class RedisTokenBucket:
    """Distributed token bucket using Redis + Lua script.

    Provides globally coordinated rate limiting across all Pods.
    """

    LUA_SCRIPT = """
    local key = KEYS[1]
    local rate = tonumber(ARGV[1])
    local capacity = tonumber(ARGV[2])
    local now = tonumber(ARGV[3])

    local data = redis.call('HMGET', key, 'tokens', 'last_refill')
    local tokens = tonumber(data[1]) or capacity
    local last_refill = tonumber(data[2]) or now

    -- Refill tokens based on elapsed time
    local elapsed = now - last_refill
    tokens = math.min(capacity, tokens + elapsed * rate)

    if tokens >= 1 then
        tokens = tokens - 1
        redis.call('HMSET', key, 'tokens', tokens, 'last_refill', now)
        redis.call('EXPIRE', key, 300)
        return 1
    else
        redis.call('HMSET', key, 'tokens', tokens, 'last_refill', now)
        redis.call('EXPIRE', key, 300)
        return 0
    end
    """

    def __init__(self, rate: float, capacity: int, key: str = "kbp:rate_limit:bedrock"):
        self._rate = rate
        self._capacity = capacity
        self._key = key
        self._script_sha: Optional[str] = None

    async def acquire(self) -> bool:
        """Try to acquire a token from Redis.

        Returns True if token acquired, False if bucket empty.
        Raises exception if Redis is unavailable.
        """
        from app.core.redis import get_redis

        redis_client = await get_redis()
        if redis_client is None:
            raise ConnectionError("Redis not available")

        now = time.time()

        if self._script_sha is None:
            self._script_sha = await redis_client.script_load(self.LUA_SCRIPT)

        result = await redis_client.evalsha(
            self._script_sha,
            1,
            self._key,
            str(self._rate),
            str(self._capacity),
            str(now),
        )
        return result == 1


class TokenBucket:
    """Facade that uses Redis for distributed rate limiting with local fallback.

    When Redis is configured and available, uses RedisTokenBucket for
    globally coordinated rate limiting. Falls back to LocalTokenBucket
    (per-pod) when Redis is unavailable — never skips rate limiting.

    Rate computation:
      - Redis mode (global):  rate = account_rpm / 60
      - Local mode (per-pod): rate = account_rpm / 60 / expected_pods
    """

    def __init__(self, account_rpm: int, expected_pods: int, burst: int):
        self._redis_failures = 0
        self._max_redis_failures = 3

        global_rate = account_rpm / 60.0
        local_rate = global_rate / max(expected_pods, 1)

        settings = get_settings()
        self._redis: Optional[RedisTokenBucket] = None

        if settings.REDIS_URL:
            self._rate = global_rate
            self._redis = RedisTokenBucket(global_rate, burst)
            self._local = LocalTokenBucket(local_rate, burst)
            logger.info(
                f"Rate limiter: Redis distributed mode — "
                f"global {global_rate:.2f} req/s ({account_rpm} RPM), burst={burst}, "
                f"local fallback {local_rate:.2f} req/s (/{expected_pods} pods)"
            )
        else:
            self._rate = local_rate
            self._local = LocalTokenBucket(local_rate, burst)
            logger.info(
                f"Rate limiter: local per-pod mode — "
                f"{local_rate:.2f} req/s ({account_rpm} RPM / {expected_pods} pods), burst={burst}"
            )

    async def acquire(self) -> None:
        """Wait until a token is available, then consume one.

        Tries Redis first, falls back to local on failure.
        """
        if self._redis is not None and self._redis_failures < self._max_redis_failures:
            try:
                while True:
                    acquired = await self._redis.acquire()
                    if acquired:
                        self._redis_failures = 0
                        return
                    await asyncio.sleep((1.0 / self._rate) * 0.5)
            except Exception as e:
                self._redis_failures += 1
                if self._redis_failures >= self._max_redis_failures:
                    logger.warning(
                        f"Redis rate limiter failed {self._redis_failures} times, "
                        f"falling back to local: {e}"
                    )
                else:
                    logger.debug(f"Redis rate limiter error, using local fallback: {e}")

        await self._local.acquire()


class _ProfileCache:
    """Caches inference profiles and foundation models from AWS Bedrock.

    Populated at startup and refreshed daily.  ``resolve_model`` uses this
    cache to decide:
      * which inference-profile ID to use (``us.`` / ``global.`` / bare),
      * which AWS region to send the request to.
    """

    TTL = 86400  # 24 hours

    # Geo prefix priority for choosing the "best" local profile.
    # Lower index = higher priority (prefer geo-locked over global).
    _GEO_PRIORITY: dict[str, int] = {
        "us.": 0,
        "eu.": 1,
        "apac.": 2,
        "au.": 3,
        "ca.": 4,
        "jp.": 5,
        "global.": 10,
    }

    def __init__(self) -> None:
        self._local_profile_ids: set[str] = set()
        self._local_profiles: dict[str, str] = {}  # bare_model → best profile_id
        self._all_profiles_by_bare: dict[
            str, list[str]
        ] = {}  # bare → [pids by priority]
        self._local_fm: set[str] = set()
        self._fallback_fm: set[str] = set()
        self._last_refresh: float = 0
        self._lock = asyncio.Lock()

    @property
    def is_stale(self) -> bool:
        return (time.time() - self._last_refresh) > self.TTL

    @property
    def is_empty(self) -> bool:
        return not self._local_profile_ids and not self._local_fm

    @staticmethod
    def _strip_geo_prefix(model_id: str) -> tuple[str, str]:
        """Strip the geographic prefix from a profile ID.

        Returns ``(bare_model, prefix_str)`` — e.g.
        ``("anthropic.claude-…", "us.")`` or ``("anthropic.claude-…", "")``
        if there is no prefix.
        """
        from app.services.bedrock import BedrockClient

        for pfx in BedrockClient.INFERENCE_PROFILE_PREFIXES:
            if model_id.startswith(pfx):
                return model_id[len(pfx) :], pfx
        return model_id, ""

    def get_alternative_profiles(self, model_id: str) -> list[str]:
        """Return other geo-variant profile IDs for the given model.

        For example, if *model_id* is ``us.anthropic.claude-sonnet-4-20250514-v1:0``,
        this returns ``["eu.anthropic.…", "apac.anthropic.…", …]`` (sorted by
        geo priority) **excluding** *model_id* itself.
        """
        bare, _ = self._strip_geo_prefix(model_id)
        return [p for p in self._all_profiles_by_bare.get(bare, []) if p != model_id]

    # ------------------------------------------------------------------

    async def refresh(
        self,
        session: "aioboto3.Session",
        region: str,
        fallback_region: str,
        config: "Config",
    ) -> None:
        """Fetch latest profiles and foundation models from AWS."""
        async with self._lock:
            await self._do_refresh(session, region, fallback_region, config)

    async def _do_refresh(
        self,
        session: "aioboto3.Session",
        region: str,
        fallback_region: str,
        config: "Config",
    ) -> None:
        local_profile_ids: set[str] = set()
        local_profiles: dict[str, str] = {}
        local_fm: set[str] = set()
        fallback_fm: set[str] = set()

        try:
            # 1. Local region inference profiles
            async with session.client("bedrock", region_name=region) as client:
                resp = await client.list_inference_profiles()
                for p in resp.get("inferenceProfileSummaries", []):
                    pid = p.get("inferenceProfileId", "")
                    if not pid or p.get("status") != "ACTIVE":
                        continue
                    local_profile_ids.add(pid)

                    # Build bare_model → best profile mapping
                    bare, prefix_str = self._strip_geo_prefix(pid)

                    priority = self._GEO_PRIORITY.get(prefix_str, 5)
                    existing = local_profiles.get(bare)
                    if existing is None:
                        local_profiles[bare] = pid
                    else:
                        # Replace only if new profile has higher priority (lower number)
                        _, existing_pfx = self._strip_geo_prefix(existing)
                        existing_priority = self._GEO_PRIORITY.get(existing_pfx, 5)
                        if priority < existing_priority:
                            local_profiles[bare] = pid

            # 2. Local region foundation models
            async with session.client("bedrock", region_name=region) as client:
                resp = await client.list_foundation_models()
                for m in resp.get("modelSummaries", []):
                    mid = m.get("modelId", "")
                    if mid and mid.count(":") <= 1:  # skip throughput variants
                        local_fm.add(mid)

            # 3. Fallback region foundation models (only those not in local)
            if fallback_region != region:
                async with session.client(
                    "bedrock", region_name=fallback_region
                ) as client:
                    resp = await client.list_foundation_models()
                    for m in resp.get("modelSummaries", []):
                        mid = m.get("modelId", "")
                        if mid and mid.count(":") <= 1 and mid not in local_fm:
                            # Also exclude models already covered by a local profile
                            if mid not in local_profiles:
                                fallback_fm.add(mid)

            # Build bare → all profiles mapping (sorted by geo priority)
            all_by_bare: dict[str, list[tuple[int, str]]] = {}
            for pid in local_profile_ids:
                bare_key, pfx_str = self._strip_geo_prefix(pid)
                prio = self._GEO_PRIORITY.get(pfx_str, 5)
                all_by_bare.setdefault(bare_key, []).append((prio, pid))

            self._local_profile_ids = local_profile_ids
            self._local_profiles = local_profiles
            self._all_profiles_by_bare = {
                k: [pid for _, pid in sorted(v)] for k, v in all_by_bare.items()
            }
            self._local_fm = local_fm
            self._fallback_fm = fallback_fm
            self._last_refresh = time.time()

            logger.info(
                f"Profile cache refreshed: {len(local_profile_ids)} profiles, "
                f"{len(local_fm)} local FM, {len(fallback_fm)} fallback FM"
            )

        except Exception as e:
            logger.error(f"Failed to refresh profile cache: {e}", exc_info=True)
            # Keep stale data if refresh fails

    def get_all_available_models(self) -> list[dict]:
        """Return all available models for the admin model list.

        Returns a list of dicts with model info, combining local profiles,
        local foundation models, and fallback foundation models.
        """
        from app.services.bedrock import BedrockClient

        models: list[dict] = []

        # Profiles (cross-region)
        for pid in sorted(self._local_profile_ids):
            bare = pid
            prefix = None
            for pfx in BedrockClient.INFERENCE_PROFILE_PREFIXES:
                if pid.startswith(pfx):
                    bare = pid[len(pfx) :]
                    prefix = pfx.rstrip(".")
                    break
            # Skip embedding/rerank
            if any(kw in bare for kw in ("embed-", "rerank-")):
                continue
            models.append(
                {
                    "model_id": pid,
                    "base_model_id": bare,
                    "is_cross_region": True,
                    "cross_region_type": prefix,
                    "is_fallback": False,
                }
            )

        # Local foundation models (not already covered by profiles)
        profile_bases = set(self._local_profiles.keys())
        for mid in sorted(self._local_fm):
            if mid in profile_bases:
                continue
            if any(kw in mid for kw in ("embed-", "rerank-")):
                continue
            models.append(
                {
                    "model_id": mid,
                    "base_model_id": mid,
                    "is_cross_region": False,
                    "cross_region_type": None,
                    "is_fallback": False,
                }
            )

        # Fallback foundation models
        for mid in sorted(self._fallback_fm):
            if any(kw in mid for kw in ("embed-", "rerank-")):
                continue
            models.append(
                {
                    "model_id": mid,
                    "base_model_id": mid,
                    "is_cross_region": False,
                    "cross_region_type": None,
                    "is_fallback": True,
                }
            )

        return models


class BedrockClient:
    """AWS Bedrock client using async aioboto3."""

    _instance: Optional["BedrockClient"] = None

    def __init__(self):
        """Initialize Bedrock client with aioboto3 session."""
        import os

        settings = get_settings()

        # Configure with retry logic and connection pooling
        self.config = Config(
            region_name=settings.AWS_REGION,
            retries={"max_attempts": 3, "mode": "adaptive"},
            connect_timeout=10,  # 10 seconds for connection
            read_timeout=3600,  # 1 hour: covers very long non-streaming tasks
            max_pool_connections=settings.BEDROCK_MAX_CONCURRENT_REQUESTS,
            tcp_keepalive=True,  # Enable TCP keepalive
        )

        # Semaphore to limit concurrent Bedrock requests and provide
        # backpressure instead of queuing against the connection pool
        self._semaphore = asyncio.Semaphore(settings.BEDROCK_MAX_CONCURRENT_REQUESTS)

        # Token bucket for rate limiting (controls requests per second)
        # Semaphore limits concurrency; token bucket limits rate
        # Rate auto-computed from account RPM:
        #   Redis mode  → global rate = account_rpm / 60
        #   Local mode  → per-pod rate = account_rpm / 60 / expected_pods
        self._rate_limiter = TokenBucket(
            account_rpm=settings.BEDROCK_ACCOUNT_RPM,
            expected_pods=settings.BEDROCK_EXPECTED_PODS,
            burst=settings.BEDROCK_RATE_BURST,
        )

        # Set AWS profile if configured
        if settings.AWS_PROFILE:
            os.environ["AWS_PROFILE"] = settings.AWS_PROFILE
            logger.info(f"Using AWS profile: {settings.AWS_PROFILE}")

        # Create aioboto3 session
        session_kwargs = {}
        if settings.AWS_ACCESS_KEY_ID and settings.AWS_SECRET_ACCESS_KEY:
            session_kwargs["aws_access_key_id"] = settings.AWS_ACCESS_KEY_ID
            session_kwargs["aws_secret_access_key"] = settings.AWS_SECRET_ACCESS_KEY

        self.session = aioboto3.Session(**session_kwargs)
        self.region_name = settings.AWS_REGION

        # Profile cache — populated by refresh_profile_cache()
        self._profile_cache = _ProfileCache()

    async def refresh_profile_cache(self) -> None:
        """Refresh the inference profile / foundation model cache."""
        await self._profile_cache.refresh(
            self.session,
            self.region_name,
            self.FALLBACK_REGION,
            self.config,
        )

    @classmethod
    def get_instance(cls) -> "BedrockClient":
        """Get the singleton BedrockClient instance. Created on first call."""
        if cls._instance is None:
            cls._instance = cls()
            logger.info("BedrockClient singleton initialized")
        return cls._instance

    MAX_CACHE_BREAKPOINTS = 4

    # Fallback region — has the broadest model catalog.
    FALLBACK_REGION = "us-west-2"

    # Valid cross-region inference profile prefixes
    INFERENCE_PROFILE_PREFIXES = ("global.", "us.", "eu.", "apac.", "au.", "ca.", "jp.")

    # Prefixes that identify Anthropic models (base or with inference profile)
    ANTHROPIC_BASE_PREFIX = "anthropic."

    @classmethod
    def is_anthropic_model(cls, model_id: str) -> bool:
        """Return True if *model_id* refers to an Anthropic model.

        Handles both bare IDs (``anthropic.claude-...``) and inference-profile
        IDs (``us.anthropic.claude-...``).
        """
        # Strip optional inference-profile geo prefix
        base = model_id
        for prefix in cls.INFERENCE_PROFILE_PREFIXES:
            if model_id.startswith(prefix):
                base = model_id[len(prefix) :]
                break
        return base.startswith(cls.ANTHROPIC_BASE_PREFIX)

    # Map AWS region prefix to geographic inference profile prefix
    REGION_TO_GEO_PREFIX = {
        "us": "us",
        "eu": "eu",
        "ap": "apac",
        "ca": "ca",
        "me": "eu",  # Middle East uses EU prefix
        "af": "eu",  # Africa uses EU prefix
        "sa": "us",  # South America uses US prefix
    }

    @classmethod
    def get_geo_prefix(cls, aws_region: str) -> str:
        """
        Get the geographic inference profile prefix for an AWS region.

        Examples:
            us-west-2 → "us"
            eu-central-1 → "eu"
            ap-northeast-1 → "apac"

        Args:
            aws_region: AWS region code (e.g., "us-west-2")

        Returns:
            Geographic prefix (e.g., "us")
        """
        region_prefix = aws_region.split("-")[0]
        return cls.REGION_TO_GEO_PREFIX.get(region_prefix, "us")

    def resolve_model(self, model_name: str) -> tuple[str, str]:
        """Resolve a model name into ``(model_id, region)`` for the Bedrock API.

        Uses the cached profile / foundation-model data populated by
        ``refresh_profile_cache()``.

        Resolution order:
        1. Has geo prefix and known locally → pass through, local region.
        2. Has geo prefix but NOT known locally → strip prefix, re-resolve.
        3. Bare ID found in local profiles → return best profile, local region.
        4. Bare ID found in local foundation models → bare ID, local region.
        5. Bare ID found in fallback foundation models → bare ID, fallback region.
        6. Unknown → bare ID, local region (best effort).
        """
        cache = self._profile_cache

        # Step 1 / 1b: model already has a geo prefix
        for prefix in self.INFERENCE_PROFILE_PREFIXES:
            if model_name.startswith(prefix):
                if model_name in cache._local_profile_ids:
                    # 1a — known locally
                    return model_name, self.region_name
                # 1b — not available locally, strip and re-resolve
                bare = model_name[len(prefix) :]
                logger.info(
                    f"Profile {model_name} not available in {self.region_name}, "
                    f"re-resolving bare model: {bare}"
                )
                return self._resolve_bare(bare)

        return self._resolve_bare(model_name)

    def _resolve_bare(self, bare: str) -> tuple[str, str]:
        """Resolve a bare model ID (no geo prefix) using the cache."""
        cache = self._profile_cache

        # Step 2: local inference profile
        profile_id = cache._local_profiles.get(bare)
        if profile_id:
            return profile_id, self.region_name

        # Step 3: local foundation model
        if bare in cache._local_fm:
            return bare, self.region_name

        # Step 4: fallback foundation model
        if bare in cache._fallback_fm:
            logger.info(
                f"Model {bare} not in {self.region_name}, "
                f"routing to fallback {self.FALLBACK_REGION}"
            )
            return bare, self.FALLBACK_REGION

        # Step 5: unknown — best effort
        logger.warning(f"Model {bare} not found in cache, trying local region")
        return bare, self.region_name

    # ------------------------------------------------------------------
    # Stream failover helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _is_content_event(event: BedrockStreamEvent) -> bool:
        """Return True if the event contains actual generated content.

        Metadata events (``message_start``, ``content_block_start``) return
        False; only ``content_block_delta`` with real text/json/thinking counts.
        """
        if event.type == "content_block_delta" and event.delta:
            return bool(
                event.delta.get("text")
                or event.delta.get("partial_json")
                or event.delta.get("thinking")
            )
        return False

    def _get_failover_targets(
        self,
        primary_model_id: str,
        primary_region: str,
        fallback_models: list[str] | None = None,
    ) -> list[tuple[str, str, str]]:
        """Build an ordered list of ``(model_id, region, label)`` failover targets.

        * **Level 1** — same model, different region (cross-region profiles).
        * **Level 2** — different model from *fallback_models* list.

        The *primary* target is **not** included.
        """
        targets: list[tuple[str, str, str]] = []

        # Level 1: cross-region alternatives for the same model
        for alt_pid in self._profile_cache.get_alternative_profiles(primary_model_id):
            targets.append((alt_pid, self.region_name, f"L1-region:{alt_pid}"))

        # Level 2: model degradation
        if fallback_models:
            for fb_name in fallback_models:
                fb_id, fb_region = self.resolve_model(fb_name)
                if fb_id != primary_model_id:
                    targets.append((fb_id, fb_region, f"L2-model:{fb_name}"))

        return targets

    async def _try_stream_with_content_timeout(
        self,
        model_id: str,
        target_region: str,
        request: BedrockRequest,
        content_timeout: float,
    ) -> AsyncGenerator[BedrockStreamEvent, None]:
        """Stream from a single model/region with a first-content deadline.

        Events are **buffered** until the first real content chunk arrives.
        Once content is confirmed the buffer is flushed and subsequent events
        stream through immediately.  If the deadline fires before content,
        :class:`FirstContentTimeoutError` is raised and **no events have been
        yielded** — so the caller can safely move on to the next target
        without the consumer seeing partial metadata from a failed attempt.
        """
        use_converse = not self.is_anthropic_model(model_id)

        if use_converse:
            converse_params = self._build_converse_params(request, model_id)
        else:
            body = self._build_anthropic_body(request)
            invoke_kwargs = self._build_invoke_kwargs(request, model_id)

        content_received = False
        buffer: list[BedrockStreamEvent] = []  # hold events until content arrives
        api_label = "converse_stream" if use_converse else "invoke_model_stream"

        span = tracer.start_span(
            "bedrock.invoke_stream",
            attributes={
                "bedrock.model_id": model_id,
                "bedrock.region": target_region,
                "bedrock.api": api_label,
                "bedrock.failover": True,
            },
        )
        start_time = time.monotonic()

        try:
            async with self.session.client(
                "bedrock-runtime",
                region_name=target_region,
                config=self.config,
            ) as client:
                if use_converse:
                    response = await client.converse_stream(**converse_params)
                    event_source = response["stream"]
                else:
                    response = await client.invoke_model_with_response_stream(
                        body=json.dumps(body), **invoke_kwargs
                    )
                    event_source = response["body"]

                logger.info(
                    "Bedrock streaming started (failover path)",
                    extra={
                        "model_id": model_id,
                        "region": target_region,
                        "api": api_label,
                        "content_timeout": content_timeout,
                    },
                )

                # Deadline starts NOW — covers the real-world case where the
                # stream connection succeeds but zero events ever arrive.
                deadline = time.monotonic() + content_timeout

                aiter = event_source.__aiter__()
                while True:
                    # Apply per-__anext__ timeout only until content arrives
                    try:
                        if not content_received:
                            remaining = deadline - time.monotonic()
                            if remaining <= 0:
                                raise FirstContentTimeoutError(
                                    f"No content within {content_timeout}s"
                                )
                            raw_event = await asyncio.wait_for(
                                aiter.__anext__(), timeout=remaining
                            )
                        else:
                            raw_event = await aiter.__anext__()
                    except StopAsyncIteration:
                        break
                    except asyncio.TimeoutError:
                        raise FirstContentTimeoutError(
                            f"No content within {content_timeout}s"
                        )

                    # Parse event
                    if use_converse:
                        bedrock_event = self._converse_stream_event_to_bedrock(
                            raw_event
                        )
                    else:
                        chunk_bytes = raw_event.get("chunk", {}).get("bytes")
                        if not chunk_bytes:
                            continue
                        anthropic_event = json.loads(chunk_bytes)
                        bedrock_event = self._anthropic_event_to_bedrock(
                            anthropic_event
                        )

                    if not bedrock_event:
                        continue

                    if not content_received:
                        buffer.append(bedrock_event)
                        if self._is_content_event(bedrock_event):
                            content_received = True
                            # Flush buffer
                            for buffered in buffer:
                                yield buffered
                            buffer.clear()
                    else:
                        yield bedrock_event

                # Stream ended without error — flush any remaining buffered events
                # (e.g. very short response that was all metadata)
                for buffered in buffer:
                    yield buffered

                logger.info(
                    "Bedrock streaming completed (failover path)",
                    extra={
                        "model_id": model_id,
                        "region": target_region,
                        "duration_seconds": round(time.monotonic() - start_time, 3),
                    },
                )
        except GeneratorExit:
            raise
        except BaseException as exc:
            span.record_exception(exc)
            raise
        finally:
            span.set_attribute(
                "bedrock.duration_s", round(time.monotonic() - start_time, 3)
            )
            span.end()

    # ------------------------------------------------------------------

    @staticmethod
    def _new_cache_marker(ttl: str | None = None) -> dict:
        """Create a cache_control marker with configured TTL."""
        cache_ttl = ttl or get_settings().PROMPT_CACHE_TTL
        marker: dict = {"type": "ephemeral"}
        if cache_ttl != "5m":
            marker["ttl"] = cache_ttl
        return marker

    @staticmethod
    def _collect_cache_blocks(body: dict) -> list[dict]:
        """Collect all blocks that already have cache_control markers."""
        blocks: list[dict] = []

        def collect(items: list) -> None:
            for item in items:
                if isinstance(item, dict) and "cache_control" in item:
                    blocks.append(item)

        # Check tools
        collect(body.get("tools") or [])
        # Check system
        system = body.get("system")
        if isinstance(system, list):
            collect(system)
        # Check message content blocks
        for msg in body.get("messages", []):
            if isinstance(msg, dict):
                content = msg.get("content")
                if isinstance(content, list):
                    collect(content)

        return blocks

    @staticmethod
    def _body_has_cache_control(body: dict) -> bool:
        """Check if the body already contains any cache_control markers."""
        return len(BedrockClient._collect_cache_blocks(body)) > 0

    @staticmethod
    def _inject_prompt_cache_breakpoints(body: dict, ttl: str | None = None) -> None:
        """Inject up to 4 cache_control breakpoints into the request body.

        Strategy aligned with claudecode-bedrock-proxy:
        1. Upgrade TTL on all pre-existing breakpoints
        2. Inject new breakpoints (up to remaining budget):
           a. Last tool definition
           b. System prompt — last block (string → converted to array)
           c. Last assistant message — last non-thinking content block

        The API limit is 4 breakpoints per request. Pre-existing breakpoints
        count against this budget.
        """
        cache_ttl = ttl or get_settings().PROMPT_CACHE_TTL
        marker = BedrockClient._new_cache_marker(ttl=cache_ttl)

        # --- Step 1: Upgrade TTL on pre-existing breakpoints ---
        existing_blocks = BedrockClient._collect_cache_blocks(body)
        upgraded = 0
        if cache_ttl != "5m":
            for block in existing_blocks:
                cc = block.get("cache_control")
                if isinstance(cc, dict):
                    cc["ttl"] = cache_ttl
                    upgraded += 1

        existing = len(existing_blocks)
        budget = BedrockClient.MAX_CACHE_BREAKPOINTS - existing
        if budget <= 0:
            if upgraded > 0:
                logger.info(
                    f"Prompt cache: ttl-upgrade({upgraded}->{cache_ttl}, existing={existing})"
                )
            return

        added = 0
        parts: list[str] = []

        # --- Step 2a: Last tool definition ---
        tools = body.get("tools")
        if tools and added < budget:
            last_tool = tools[-1]
            if isinstance(last_tool, dict) and "cache_control" not in last_tool:
                last_tool["cache_control"] = marker
                added += 1
                parts.append("tools")

        # --- Step 2b: System prompt ---
        if added < budget:
            system = body.get("system")
            if system is not None:
                if isinstance(system, str) and system:
                    body["system"] = [
                        {"type": "text", "text": system, "cache_control": marker}
                    ]
                    added += 1
                    parts.append("system")
                elif isinstance(system, list) and system:
                    last_block = system[-1]
                    if (
                        isinstance(last_block, dict)
                        and "cache_control" not in last_block
                    ):
                        last_block["cache_control"] = marker
                        added += 1
                        parts.append("system")

        # --- Step 2c: Last assistant message (skip thinking blocks) ---
        if added < budget:
            messages = body.get("messages", [])
            for i in range(len(messages) - 1, -1, -1):
                msg = messages[i]
                if not isinstance(msg, dict) or msg.get("role") != "assistant":
                    continue

                content = msg.get("content")
                if isinstance(content, str) and content:
                    msg["content"] = [
                        {"type": "text", "text": content, "cache_control": marker}
                    ]
                    added += 1
                    parts.append("msgs")
                elif isinstance(content, list) and content:
                    # Find last non-thinking block
                    for j in range(len(content) - 1, -1, -1):
                        block = content[j]
                        if not isinstance(block, dict):
                            continue
                        typ = block.get("type", "")
                        if typ in ("thinking", "redacted_thinking"):
                            continue
                        if "cache_control" not in block:
                            block["cache_control"] = marker
                            added += 1
                            parts.append("msgs")
                        break
                break  # Only process the last assistant message

        if added > 0 or upgraded > 0:
            upg = f",upg={upgraded}" if upgraded > 0 else ""
            logger.info(
                f"Prompt cache: {added}bp({'+'.join(parts)},{cache_ttl},pre={existing}{upg})"
            )

    @staticmethod
    def _build_anthropic_body(request: BedrockRequest) -> dict:
        """
        Build an Anthropic Messages API request body from a BedrockRequest.

        This body is sent as JSON to invoke_model / invoke_model_with_response_stream.
        """
        from app.schemas.bedrock import BedrockContentPart

        # --- messages ---
        messages = []
        for msg in request.messages:
            if isinstance(msg.content, str):
                messages.append({"role": msg.role, "content": msg.content})
            elif isinstance(msg.content, list):
                parts = []
                for part in msg.content:
                    if isinstance(part, BedrockContentPart):
                        p = part.model_dump(exclude_none=True)
                    else:
                        p = dict(part) if isinstance(part, dict) else part
                    parts.append(p)
                messages.append({"role": msg.role, "content": parts})

        body: dict = {
            "anthropic_version": request.anthropic_version,
            "max_tokens": request.max_tokens,
            "messages": messages,
        }

        # --- optional scalar fields ---
        if request.system:
            body["system"] = request.system
        if request.temperature is not None:
            body["temperature"] = request.temperature
        if request.top_p is not None:
            body["top_p"] = request.top_p
        if request.stop_sequences:
            body["stop_sequences"] = request.stop_sequences

        # --- tools / tool_choice ---
        if request.tools:
            body["tools"] = [
                {
                    "name": t.name,
                    "description": t.description,
                    "input_schema": t.input_schema,
                }
                for t in request.tools
            ]
        if request.tool_choice:
            body["tool_choice"] = request.tool_choice

        # --- additional_model_request_fields (thinking / effort live here) ---
        if request.additional_model_request_fields:
            body.update(request.additional_model_request_fields)

        # --- prompt caching ---
        if request.prompt_caching:
            body.update(request.prompt_caching)

        # --- auto-inject prompt cache breakpoints ---
        should_inject = request.auto_cache  # per-request override
        if should_inject is None:
            should_inject = get_settings().PROMPT_CACHE_AUTO_INJECT  # server default
        has_cache = (
            BedrockClient._body_has_cache_control(body) if should_inject else False
        )
        if should_inject and not has_cache:
            BedrockClient._inject_prompt_cache_breakpoints(body, ttl=request.cache_ttl)

        # --- effort parameter: requires beta flag + output_config wrapper ---
        # Users may pass "effort" as a top-level field (via additional_model_request_fields).
        # Bedrock invoke_model expects it inside "output_config" with a beta flag.
        if "effort" in body:
            effort_value = body.pop("effort")
            # Wrap in output_config
            output_config = body.get("output_config", {})
            output_config["effort"] = effort_value
            body["output_config"] = output_config
            # Ensure the beta flag is present
            beta_flags = body.get("anthropic_beta", [])
            effort_beta = "effort-2025-11-24"
            if effort_beta not in beta_flags:
                beta_flags.append(effort_beta)
            body["anthropic_beta"] = beta_flags
            logger.info(
                f"Effort parameter '{effort_value}' wrapped in output_config with beta flag"
            )

        # --- auto-fix thinking.budget_tokens constraints ---
        # Bedrock requires budget_tokens >= 1024 and max_tokens > budget_tokens.
        thinking_cfg = body.get("thinking")
        if isinstance(thinking_cfg, dict) and "budget_tokens" in thinking_cfg:
            budget = thinking_cfg["budget_tokens"]
            if budget < 1024:
                logger.info(
                    f"Adjusting thinking.budget_tokens from {budget} to 1024 "
                    f"(Bedrock minimum)"
                )
                thinking_cfg["budget_tokens"] = 1024
                budget = 1024
            if body["max_tokens"] <= budget:
                new_max = budget + body["max_tokens"]
                logger.info(
                    f"Adjusting max_tokens from {body['max_tokens']} to {new_max} "
                    f"(must be > thinking.budget_tokens={budget})"
                )
                body["max_tokens"] = new_max

        # --- fields not supported by invoke_model — warn and skip ---
        if request.prompt_variables:
            logger.warning(
                "prompt_variables is not supported by invoke_model; ignoring"
            )
        if request.request_metadata:
            logger.warning(
                "request_metadata is not supported by invoke_model; ignoring"
            )
        if request.additional_model_response_field_paths:
            logger.warning(
                "additional_model_response_field_paths is not supported by invoke_model; ignoring"
            )

        return body

    @staticmethod
    def _build_invoke_kwargs(request: BedrockRequest, model_id: str) -> dict:
        """
        Build the top-level keyword arguments for invoke_model /
        invoke_model_with_response_stream (everything except ``body``).
        """
        kwargs: dict = {
            "modelId": model_id,
            "contentType": "application/json",
            "accept": "application/json",
        }

        # Guardrail config → top-level parameters
        if request.guardrail_config:
            gc = request.guardrail_config
            if "guardrailIdentifier" in gc:
                kwargs["guardrailIdentifier"] = gc["guardrailIdentifier"]
            if "guardrailVersion" in gc:
                kwargs["guardrailVersion"] = gc["guardrailVersion"]

        # Trace (invoke_model supports it as a top-level parameter)
        if request.trace:
            kwargs["trace"] = request.trace

        # Performance config
        if request.performance_config:
            kwargs["performanceConfig"] = request.performance_config

        return kwargs

    # ------------------------------------------------------------------
    # Converse API helpers (non-Anthropic models)
    # ------------------------------------------------------------------

    @staticmethod
    def _build_converse_params(request: BedrockRequest, model_id: str) -> dict:
        """Build parameters for the Converse / ConverseStream API.

        Converts the internal ``BedrockRequest`` (which uses Anthropic-style
        field names) into the structure expected by
        ``bedrock-runtime.converse()`` / ``converse_stream()``.
        """
        from app.schemas.bedrock import BedrockContentPart
        import base64

        # --- messages ---
        messages = []
        for msg in request.messages:
            converse_content: list[dict] = []

            if isinstance(msg.content, str):
                converse_content.append({"text": msg.content})
            elif isinstance(msg.content, list):
                for part in msg.content:
                    if isinstance(part, BedrockContentPart):
                        part_dict = part.model_dump(exclude_none=True)
                    else:
                        part_dict = part

                    ptype = part_dict.get("type")

                    if ptype == "text":
                        converse_content.append({"text": part_dict.get("text", "")})

                    elif ptype == "image":
                        # Anthropic format: source.type="base64", source.media_type, source.data
                        source = part_dict.get("source", {})
                        media_type = source.get("media_type", "image/jpeg")
                        # Converse wants format without the "image/" prefix
                        fmt = media_type.split("/")[-1]  # e.g. "jpeg", "png"
                        raw_bytes = base64.b64decode(source.get("data", ""))
                        converse_content.append(
                            {
                                "image": {
                                    "format": fmt,
                                    "source": {"bytes": raw_bytes},
                                }
                            }
                        )

                    elif ptype == "tool_use":
                        converse_content.append(
                            {
                                "toolUse": {
                                    "toolUseId": part_dict.get("id", ""),
                                    "name": part_dict.get("name", ""),
                                    "input": part_dict.get("input", {}),
                                }
                            }
                        )

                    elif ptype == "tool_result":
                        result_content = []
                        text_val = part_dict.get("content")
                        if text_val:
                            result_content.append({"text": text_val})
                        converse_content.append(
                            {
                                "toolResult": {
                                    "toolUseId": part_dict.get("tool_use_id", ""),
                                    "content": result_content,
                                }
                            }
                        )

            messages.append({"role": msg.role, "content": converse_content})

        params: dict = {
            "modelId": model_id,
            "messages": messages,
        }

        # --- system ---
        if request.system:
            params["system"] = [{"text": request.system}]

        # --- inferenceConfig ---
        inference_config: dict = {"maxTokens": request.max_tokens}
        if request.temperature is not None:
            inference_config["temperature"] = request.temperature
        if request.top_p is not None:
            inference_config["topP"] = request.top_p
        if request.stop_sequences:
            inference_config["stopSequences"] = request.stop_sequences
        params["inferenceConfig"] = inference_config

        # --- toolConfig ---
        if request.tools:
            tool_specs = []
            for t in request.tools:
                tool_specs.append(
                    {
                        "toolSpec": {
                            "name": t.name,
                            "description": t.description,
                            "inputSchema": {"json": t.input_schema},
                        }
                    }
                )
            tool_config: dict = {"tools": tool_specs}

            # tool_choice mapping (already in Anthropic-style dict from translator)
            if request.tool_choice:
                tc_type = request.tool_choice.get("type")
                if tc_type == "auto":
                    tool_config["toolChoice"] = {"auto": {}}
                elif tc_type == "any":
                    tool_config["toolChoice"] = {"any": {}}
                elif tc_type == "tool":
                    tool_config["toolChoice"] = {
                        "tool": {"name": request.tool_choice.get("name", "")}
                    }

            params["toolConfig"] = tool_config

        # --- guardrail ---
        if request.guardrail_config:
            gc = request.guardrail_config
            guardrail: dict = {}
            if "guardrailIdentifier" in gc:
                guardrail["guardrailIdentifier"] = gc["guardrailIdentifier"]
            if "guardrailVersion" in gc:
                guardrail["guardrailVersion"] = gc["guardrailVersion"]
            if guardrail:
                params["guardrailConfig"] = guardrail

        # --- additional model request fields (pass-through) ---
        if request.additional_model_request_fields:
            params["additionalModelRequestFields"] = (
                request.additional_model_request_fields
            )

        # --- performance config ---
        if request.performance_config:
            params["performanceConfig"] = request.performance_config

        return params

    def _parse_converse_response(
        self, response: dict, model_name: str
    ) -> BedrockResponse:
        """Convert a Converse API response dict into a ``BedrockResponse``."""
        output = response.get("output", {})
        message = output.get("message", {})
        content_list = message.get("content", [])

        content_blocks: list[BedrockContentBlock] = []
        for item in content_list:
            if "text" in item:
                content_blocks.append(
                    BedrockContentBlock(type="text", text=item["text"])
                )
            elif "toolUse" in item:
                tu = item["toolUse"]
                content_blocks.append(
                    BedrockContentBlock(
                        type="tool_use",
                        id=tu.get("toolUseId"),
                        name=tu.get("name"),
                        input=tu.get("input"),
                    )
                )

        usage_data = response.get("usage", {})
        usage = BedrockUsage(
            input_tokens=usage_data.get("inputTokens", 0),
            output_tokens=usage_data.get("outputTokens", 0),
        )

        stop_reason_raw = response.get("stopReason", "end_turn")
        # Converse uses "end_turn", "tool_use", "max_tokens", "stop_sequence"
        # which aligns with our internal format already.

        return BedrockResponse(
            id=response.get("ResponseMetadata", {}).get("RequestId", ""),
            type="message",
            role="assistant",
            content=content_blocks,
            model=model_name,
            stop_reason=stop_reason_raw,
            usage=usage,
        )

    @staticmethod
    def _converse_stream_event_to_bedrock(
        event: dict,
    ) -> Optional[BedrockStreamEvent]:
        """Convert a Converse Stream event into a ``BedrockStreamEvent``.

        The Converse stream yields dicts with exactly one key per event:
        ``messageStart``, ``contentBlockStart``, ``contentBlockDelta``,
        ``contentBlockStop``, ``messageStop``, ``metadata``.
        """
        if "messageStart" in event:
            data = event["messageStart"]
            return BedrockStreamEvent(
                type="message_start",
                message={"role": data.get("role", "assistant")},
            )

        if "contentBlockStart" in event:
            data = event["contentBlockStart"]
            index = data.get("contentBlockIndex", 0)
            start = data.get("start", {})

            if "toolUse" in start:
                tu = start["toolUse"]
                return BedrockStreamEvent(
                    type="content_block_start",
                    index=index,
                    content_block={
                        "type": "tool_use",
                        "id": tu.get("toolUseId", ""),
                        "name": tu.get("name", ""),
                    },
                )
            else:
                return BedrockStreamEvent(
                    type="content_block_start",
                    index=index,
                    content_block={"type": "text"},
                )

        if "contentBlockDelta" in event:
            data = event["contentBlockDelta"]
            index = data.get("contentBlockIndex", 0)
            delta = data.get("delta", {})

            if "text" in delta:
                return BedrockStreamEvent(
                    type="content_block_delta",
                    index=index,
                    delta={"text": delta["text"]},
                )
            elif "toolUse" in delta:
                return BedrockStreamEvent(
                    type="content_block_delta",
                    index=index,
                    delta={"partial_json": delta["toolUse"].get("input", "")},
                )

        if "contentBlockStop" in event:
            data = event["contentBlockStop"]
            return BedrockStreamEvent(
                type="content_block_stop",
                index=data.get("contentBlockIndex", 0),
            )

        if "messageStop" in event:
            data = event["messageStop"]
            return BedrockStreamEvent(
                type="message_delta",
                delta={"stop_reason": data.get("stopReason", "end_turn")},
            )

        if "metadata" in event:
            meta = event["metadata"]
            usage_data = meta.get("usage", {})
            return BedrockStreamEvent(
                type="message_delta",
                usage=BedrockUsage(
                    input_tokens=usage_data.get("inputTokens", 0),
                    output_tokens=usage_data.get("outputTokens", 0),
                ),
            )

        return None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def invoke(self, model_name: str, request: BedrockRequest) -> BedrockResponse:
        """
        Invoke Bedrock model with retry logic (async).

        Args:
            model_name: Model name
            request: Bedrock request

        Returns:
            Bedrock response

        Raises:
            Exception: If all retries fail
        """
        await self._rate_limiter.acquire()
        async with self._semaphore:
            return await self._invoke_inner(model_name, request)

    async def _invoke_inner(
        self, model_name: str, request: BedrockRequest
    ) -> BedrockResponse:
        """Inner invoke logic with retry, called under semaphore."""
        model_id, target_region = self.resolve_model(model_name)
        use_converse = not self.is_anthropic_model(model_id)
        api_name = "converse" if use_converse else "invoke_model"

        if use_converse:
            converse_params = self._build_converse_params(request, model_id)
            logger.info(
                "Using Converse API for non-Anthropic model",
                extra={
                    "model": model_name,
                    "model_id": model_id,
                    "region": target_region,
                },
            )
        else:
            body = self._build_anthropic_body(request)
            invoke_kwargs = self._build_invoke_kwargs(request, model_id)

        max_retries = 3
        base_delay = 1.0

        for attempt in range(max_retries):
            try:
                start_time = time.time()

                with tracer.start_as_current_span(
                    "bedrock.invoke",
                    attributes={
                        "bedrock.model": model_name,
                        "bedrock.model_id": model_id,
                        "bedrock.region": target_region,
                        "bedrock.api": api_name,
                        "bedrock.attempt": attempt + 1,
                    },
                ) as span:
                    async with self.session.client(
                        "bedrock-runtime",
                        region_name=target_region,
                        config=self.config,
                    ) as client:
                        if use_converse:
                            response = await client.converse(**converse_params)
                            duration = time.time() - start_time
                            bedrock_response = self._parse_converse_response(
                                response, model_name
                            )
                        else:
                            response = await client.invoke_model(
                                body=json.dumps(body), **invoke_kwargs
                            )
                            duration = time.time() - start_time

                            # Parse Anthropic Messages API response
                            response_body = json.loads(await response["body"].read())

                            # Build content blocks
                            content_blocks = []
                            for item in response_body.get("content", []):
                                block_type = item.get("type")
                                if block_type == "text":
                                    content_blocks.append(
                                        BedrockContentBlock(
                                            type="text", text=item["text"]
                                        )
                                    )
                                elif block_type == "tool_use":
                                    content_blocks.append(
                                        BedrockContentBlock(
                                            type="tool_use",
                                            id=item.get("id"),
                                            name=item.get("name"),
                                            input=item.get("input"),
                                        )
                                    )
                                elif block_type == "thinking":
                                    content_blocks.append(
                                        BedrockContentBlock(
                                            type="thinking",
                                            thinking=item.get("thinking", ""),
                                            signature=item.get("signature"),
                                        )
                                    )
                                elif block_type == "redacted_thinking":
                                    content_blocks.append(
                                        BedrockContentBlock(
                                            type="redacted_thinking",
                                            data=item.get("data", ""),
                                        )
                                    )

                            # Usage — Anthropic format uses snake_case
                            usage_data = response_body.get("usage", {})
                            usage = BedrockUsage(
                                input_tokens=usage_data.get("input_tokens", 0),
                                output_tokens=usage_data.get("output_tokens", 0),
                                cache_creation_input_tokens=usage_data.get(
                                    "cache_creation_input_tokens", 0
                                ),
                                cache_read_input_tokens=usage_data.get(
                                    "cache_read_input_tokens", 0
                                ),
                            )

                            bedrock_response = BedrockResponse(
                                id=response_body.get("id", ""),
                                type="message",
                                role="assistant",
                                content=content_blocks,
                                model=model_name,
                                stop_reason=response_body.get(
                                    "stop_reason", "end_turn"
                                ),
                                usage=usage,
                            )

                        span.set_attribute(
                            "bedrock.input_tokens",
                            bedrock_response.usage.input_tokens,
                        )
                        span.set_attribute(
                            "bedrock.output_tokens",
                            bedrock_response.usage.output_tokens,
                        )
                        span.set_attribute("bedrock.duration_s", round(duration, 3))

                        cache_info = ""
                        if bedrock_response.usage.cache_creation_input_tokens:
                            cache_info += f", cache_write={bedrock_response.usage.cache_creation_input_tokens}"
                        if bedrock_response.usage.cache_read_input_tokens:
                            cache_info += f", cache_read={bedrock_response.usage.cache_read_input_tokens}"
                        logger.info(
                            f"Bedrock invocation successful: model={model_name}, "
                            f"api={api_name}, "
                            f"attempt={attempt + 1}, duration={round(duration, 3)}s, "
                            f"input={bedrock_response.usage.input_tokens}, "
                            f"output={bedrock_response.usage.output_tokens}"
                            f"{cache_info}"
                        )

                        await emit_bedrock_call_metrics(
                            model=model_name,
                            region=target_region,
                            duration_s=round(duration, 3),
                            api=api_name,
                            attempt=attempt + 1,
                            success=True,
                        )

                        return bedrock_response

            except ClientError as e:
                error_code = e.response.get("Error", {}).get("Code", "Unknown")
                error_message = e.response.get("Error", {}).get("Message", str(e))

                logger.warning(
                    f"Bedrock invocation failed (attempt {attempt + 1}/{max_retries})",
                    extra={
                        "model": model_name,
                        "error_code": error_code,
                        "error_message": error_message,
                    },
                )

                # Don't retry on client errors (4xx)
                if error_code in [
                    "ValidationException",
                    "AccessDeniedException",
                    "ThrottlingException",
                ]:
                    raise

                # Retry on server errors (5xx) with exponential backoff
                if attempt < max_retries - 1:
                    delay = base_delay * (2**attempt)
                    import random

                    delay = delay * (0.5 + random.random())
                    logger.info(f"Retrying in {delay:.2f} seconds...")
                    await asyncio.sleep(delay)
                else:
                    raise

            except Exception as e:
                logger.error(
                    f"Unexpected error in Bedrock invocation (attempt {attempt + 1}/{max_retries})",
                    extra={"model": model_name, "error": str(e)},
                    exc_info=True,
                )

                if attempt < max_retries - 1:
                    delay = base_delay * (2**attempt)
                    await asyncio.sleep(delay)
                else:
                    raise

    async def invoke_stream(
        self,
        model_name: str,
        request: BedrockRequest,
        fallback_models: list[str] | None = None,
    ) -> AsyncGenerator[BedrockStreamEvent, None]:
        """Invoke Bedrock model with streaming and two-level failover.

        When ``STREAM_FIRST_CONTENT_TIMEOUT > 0``, the method implements:

        * **Level 1** — same model in a different region (transparent).
        * **Level 2** — degradation to a model from *fallback_models*
          (the first yielded event carries ``actual_model``).

        Falls back to the original (non-failover) path when the timeout is
        disabled.

        Args:
            model_name: Primary model name.
            request: Bedrock request (reusable across retries).
            fallback_models: Optional ordered list of fallback model names
                for Level 2 degradation.

        Yields:
            BedrockStreamEvent instances.
        """
        settings = get_settings()
        content_timeout = settings.STREAM_FIRST_CONTENT_TIMEOUT

        if content_timeout <= 0:
            # Failover disabled — original behaviour
            await self._rate_limiter.acquire()
            async with self._semaphore:
                async for event in self._invoke_stream_inner(model_name, request):
                    yield event
            return

        # --- Failover enabled ---------------------------------------------------
        primary_model_id, primary_region = self.resolve_model(model_name)
        targets: list[tuple[str, str, str]] = [
            (primary_model_id, primary_region, "primary")
        ]
        targets.extend(
            self._get_failover_targets(
                primary_model_id, primary_region, fallback_models
            )
        )

        last_error: BaseException | None = None
        failover_start: float | None = None
        for idx, (model_id, region, label) in enumerate(targets):
            is_last = idx == len(targets) - 1
            await self._rate_limiter.acquire()
            try:
                async with self._semaphore:
                    is_degraded = label.startswith("L2-")
                    first_event = True

                    async for event in self._try_stream_with_content_timeout(
                        model_id, region, request, content_timeout
                    ):
                        if first_event and is_degraded:
                            event.actual_model = model_id
                        first_event = False
                        yield event

                    # Stream completed successfully — emit failover metric
                    # if we are NOT on the primary target
                    if idx > 0 and failover_start is not None:
                        level = "L2" if is_degraded else "L1"
                        await emit_failover_metrics(
                            primary_model=primary_model_id,
                            failover_target=model_id,
                            level=level,
                            duration_s=round(time.time() - failover_start, 3),
                            success=True,
                        )
                    return

            except FirstContentTimeoutError as exc:
                if failover_start is None:
                    failover_start = time.time()
                last_error = exc
                logger.warning(
                    "Stream failover: %s timed out (%s, region=%s, timeout=%ss).%s",
                    label,
                    model_id,
                    region,
                    content_timeout,
                    " Trying next target…" if not is_last else " No more targets.",
                )
                continue

            except ClientError as exc:
                error_code = exc.response.get("Error", {}).get("Code", "Unknown")
                if error_code in ("ValidationException", "AccessDeniedException"):
                    raise
                if failover_start is None:
                    failover_start = time.time()
                last_error = exc
                logger.warning(
                    "Stream failover: %s failed with %s (%s, region=%s).%s",
                    label,
                    error_code,
                    model_id,
                    region,
                    " Trying next target…" if not is_last else " No more targets.",
                )
                continue

        # All targets exhausted
        if failover_start is not None:
            await emit_failover_metrics(
                primary_model=primary_model_id,
                failover_target=model_id,
                level="L2" if targets[-1][2].startswith("L2-") else "L1",
                duration_s=round(time.time() - failover_start, 3),
                success=False,
            )
        raise last_error or RuntimeError("All failover targets exhausted")

    async def _invoke_stream_inner(
        self, model_name: str, request: BedrockRequest
    ) -> AsyncGenerator[BedrockStreamEvent, None]:
        """Inner streaming logic with retry, called under semaphore."""
        model_id, target_region = self.resolve_model(model_name)
        use_converse = not self.is_anthropic_model(model_id)
        api_name = "converse_stream" if use_converse else "invoke_model_stream"

        if use_converse:
            converse_params = self._build_converse_params(request, model_id)
            logger.info(
                "Using ConverseStream API for non-Anthropic model",
                extra={
                    "model": model_name,
                    "model_id": model_id,
                    "region": target_region,
                },
            )
        else:
            body = self._build_anthropic_body(request)
            invoke_kwargs = self._build_invoke_kwargs(request, model_id)

        max_retries = 4
        base_delay = 1.0
        stream_started = False

        for attempt in range(max_retries):
            try:
                start_time = time.time()
                span = tracer.start_span(
                    "bedrock.invoke_stream",
                    attributes={
                        "bedrock.model": model_name,
                        "bedrock.model_id": model_id,
                        "bedrock.region": target_region,
                        "bedrock.api": api_name,
                        "bedrock.attempt": attempt + 1,
                    },
                )

                try:
                    async with self.session.client(
                        "bedrock-runtime",
                        region_name=target_region,
                        config=self.config,
                    ) as client:
                        if use_converse:
                            response = await client.converse_stream(**converse_params)
                        else:
                            response = await client.invoke_model_with_response_stream(
                                body=json.dumps(body), **invoke_kwargs
                            )

                        logger.info(
                            "Bedrock streaming started",
                            extra={
                                "model": model_name,
                                "model_id": model_id,
                                "api": api_name,
                                "attempt": attempt + 1,
                            },
                        )

                        event_count = 0

                        if use_converse:
                            async for event in response["stream"]:
                                stream_started = True
                                bedrock_event = self._converse_stream_event_to_bedrock(
                                    event
                                )
                                if bedrock_event:
                                    yield bedrock_event
                                    event_count += 1
                        else:
                            async for event in response["body"]:
                                stream_started = True
                                chunk_bytes = event.get("chunk", {}).get("bytes")
                                if not chunk_bytes:
                                    continue

                                anthropic_event = json.loads(chunk_bytes)
                                bedrock_event = self._anthropic_event_to_bedrock(
                                    anthropic_event
                                )
                                if bedrock_event:
                                    yield bedrock_event
                                    event_count += 1

                        duration = time.time() - start_time
                        span.set_attribute("bedrock.duration_s", round(duration, 3))
                        span.set_attribute("bedrock.events", event_count)
                        logger.info(
                            "Bedrock streaming completed",
                            extra={
                                "model": model_name,
                                "duration_seconds": round(duration, 3),
                                "events_processed": event_count,
                            },
                        )

                        await emit_bedrock_call_metrics(
                            model=model_name,
                            region=target_region,
                            duration_s=round(duration, 3),
                            api=api_name,
                            attempt=attempt + 1,
                            success=True,
                        )

                        # Success — exit retry loop
                        return
                except BaseException as exc:
                    span.record_exception(exc)
                    raise
                finally:
                    span.end()

            except ClientError as e:
                error_code = e.response.get("Error", {}).get("Code", "Unknown")
                error_message = e.response.get("Error", {}).get("Message", str(e))

                if stream_started:
                    logger.error(
                        "Stream failed mid-stream, cannot retry",
                        extra={
                            "model": model_name,
                            "error_code": error_code,
                            "error_message": error_message,
                        },
                    )
                    raise

                logger.warning(
                    f"Bedrock streaming failed before stream started (attempt {attempt + 1}/{max_retries})",
                    extra={
                        "model": model_name,
                        "error_code": error_code,
                        "error_message": error_message,
                    },
                )

                if error_code in ["ValidationException", "AccessDeniedException"]:
                    raise

                if attempt < max_retries - 1:
                    delay = base_delay * (2**attempt)
                    import random

                    delay = delay * (0.5 + random.random())
                    logger.info(f"Retrying streaming in {delay:.2f} seconds...")
                    await asyncio.sleep(delay)
                else:
                    logger.error(
                        "Bedrock streaming failed after all retries",
                        extra={"model": model_name, "error_code": error_code},
                    )
                    raise

            except Exception as e:
                if stream_started:
                    logger.error(
                        "Stream failed mid-stream, cannot retry",
                        extra={"model": model_name, "error": str(e)},
                        exc_info=True,
                    )
                    raise

                logger.error(
                    f"Unexpected error in Bedrock streaming before stream started (attempt {attempt + 1}/{max_retries})",
                    extra={"model": model_name, "error": str(e)},
                    exc_info=True,
                )

                if attempt < max_retries - 1:
                    delay = base_delay * (2**attempt)
                    import random

                    delay = delay * (0.5 + random.random())
                    logger.info(f"Retrying streaming in {delay:.2f} seconds...")
                    await asyncio.sleep(delay)
                else:
                    logger.error(
                        "Bedrock streaming failed after all retries",
                        extra={"model": model_name},
                    )
                    raise

    @staticmethod
    def _anthropic_event_to_bedrock(
        event: dict,
    ) -> Optional[BedrockStreamEvent]:
        """
        Convert an Anthropic Messages API streaming event to BedrockStreamEvent.

        Args:
            event: Parsed JSON event from invoke_model_with_response_stream

        Returns:
            BedrockStreamEvent or None if the event should be skipped
        """
        event_type = event.get("type")

        if event_type == "message_start":
            message = event.get("message", {})
            usage_data = message.get("usage", {})
            return BedrockStreamEvent(
                type="message_start",
                message={"role": message.get("role", "assistant")},
                usage=BedrockUsage(
                    input_tokens=usage_data.get("input_tokens", 0),
                    output_tokens=0,
                    cache_creation_input_tokens=usage_data.get(
                        "cache_creation_input_tokens", 0
                    ),
                    cache_read_input_tokens=usage_data.get(
                        "cache_read_input_tokens", 0
                    ),
                ),
            )

        elif event_type == "content_block_start":
            index = event.get("index", 0)
            content_block = event.get("content_block", {})
            block_type = content_block.get("type", "text")

            if block_type == "tool_use":
                return BedrockStreamEvent(
                    type="content_block_start",
                    index=index,
                    content_block={
                        "type": "tool_use",
                        "id": content_block.get("id", ""),
                        "name": content_block.get("name", ""),
                    },
                )
            elif block_type == "thinking":
                return BedrockStreamEvent(
                    type="content_block_start",
                    index=index,
                    content_block={"type": "thinking"},
                )
            else:
                return BedrockStreamEvent(
                    type="content_block_start",
                    index=index,
                    content_block={"type": "text"},
                )

        elif event_type == "content_block_delta":
            index = event.get("index", 0)
            delta = event.get("delta", {})
            delta_type = delta.get("type")

            if delta_type == "text_delta":
                return BedrockStreamEvent(
                    type="content_block_delta",
                    index=index,
                    delta={"text": delta.get("text", "")},
                )
            elif delta_type == "input_json_delta":
                return BedrockStreamEvent(
                    type="content_block_delta",
                    index=index,
                    delta={"partial_json": delta.get("partial_json", "")},
                )
            elif delta_type == "thinking_delta":
                return BedrockStreamEvent(
                    type="content_block_delta",
                    index=index,
                    delta={"thinking": delta.get("thinking", "")},
                )
            elif delta_type == "signature_delta":
                return BedrockStreamEvent(
                    type="content_block_delta",
                    index=index,
                    delta={"signature": delta.get("signature", "")},
                )

        elif event_type == "content_block_stop":
            return BedrockStreamEvent(
                type="content_block_stop",
                index=event.get("index", 0),
            )

        elif event_type == "message_delta":
            delta = event.get("delta", {})
            usage_data = event.get("usage", {})
            return BedrockStreamEvent(
                type="message_delta",
                delta={"stop_reason": delta.get("stop_reason", "end_turn")},
                usage=BedrockUsage(
                    input_tokens=0,
                    output_tokens=usage_data.get("output_tokens", 0),
                    cache_creation_input_tokens=usage_data.get(
                        "cache_creation_input_tokens", 0
                    ),
                    cache_read_input_tokens=usage_data.get(
                        "cache_read_input_tokens", 0
                    ),
                ),
            )

        elif event_type == "message_stop":
            return BedrockStreamEvent(
                type="message_stop",
            )

        # ping / unknown → skip
        return None


# ======================================================================
# Helpers for endpoint handlers
# ======================================================================


def get_fallback_models(
    allowed_model_names: list[str],
    primary_model: str,
) -> list[str] | None:
    """Compute the fallback model list for Level 2 stream failover.

    Uses ``STREAM_MODEL_FALLBACK_CHAIN`` to determine order, filtered to
    only include models the token is authorised to use.  Returns ``None``
    when model degradation is disabled or no valid fallbacks remain.
    """
    settings = get_settings()
    chain_str = settings.STREAM_MODEL_FALLBACK_CHAIN
    if not chain_str:
        return None

    chain = [m.strip() for m in chain_str.split(",") if m.strip()]
    allowed = set(allowed_model_names)
    fallbacks = [m for m in chain if m in allowed and m != primary_model]
    return fallbacks or None
