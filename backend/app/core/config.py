"""
Application configuration management using Pydantic Settings.
Cloud-native configuration following Twelve-Factor App principles.
"""

import functools
import os
from typing import List, Optional

from pydantic import Field, validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """
    Application settings configuration.

    Follows Twelve-Factor App principles:
    - Configuration is stored in environment variables
    - Strict separation between config and code
    - Type validation prevents invalid configurations
    """

    # Application settings
    DEBUG: bool = Field(default=False, description="Enable debug mode")
    PORT: int = Field(default=8000, description="Application port")
    ALLOWED_ORIGINS: str = Field(
        default="http://localhost:3000,http://localhost:8000",
        description="CORS allowed origins (comma-separated). CRITICAL: Set to specific domains in production. Never use '*' in production.",
    )

    # Database settings
    DATABASE_URL: str = Field(
        description="PostgreSQL database URL",
        examples=["postgresql+asyncpg://user:password@localhost:5432/kolya_br_proxy"],
    )
    DATABASE_POOL_SIZE: int = Field(
        default=10, description="Database connection pool size"
    )
    DATABASE_MAX_OVERFLOW: int = Field(
        default=20, description="Database max overflow connections"
    )

    # AWS settings
    AWS_REGION: str = Field(default="us-west-2", description="AWS region for Bedrock")
    AWS_PROFILE: Optional[str] = Field(
        default=None,
        description="AWS profile name (local development only, Pod Identity used in Kubernetes)",
    )
    AWS_ACCESS_KEY_ID: Optional[str] = Field(
        default=None,
        description="AWS access key ID (local development only, Pod Identity used in Kubernetes)",
    )
    AWS_SECRET_ACCESS_KEY: Optional[str] = Field(
        default=None,
        description="AWS secret access key (local development only, Pod Identity used in Kubernetes)",
    )

    # Google Gemini settings
    GEMINI_API_KEY: Optional[str] = Field(
        default=None,
        description="Google Gemini API key for direct Gemini model access",
    )

    # AWS Bedrock settings
    BEDROCK_MAX_CONCURRENT_REQUESTS: int = Field(
        default=50,
        description="Maximum concurrent requests to AWS Bedrock (controls semaphore limit)",
    )
    BEDROCK_ACCOUNT_RPM: int = Field(
        default=500,
        description="AWS Bedrock account-level RPM quota. Used to auto-compute rate limit. "
        "Check your Service Quotas in the AWS console for the actual value.",
    )
    BEDROCK_EXPECTED_PODS: int = Field(
        default=3,
        description="Expected number of backend Pods (only used in local mode without Redis). "
        "In Redis mode the global rate is account_rpm/60; in local mode each Pod gets account_rpm/60/expected_pods.",
    )
    BEDROCK_RATE_BURST: int = Field(
        default=10,
        description="Token bucket: maximum burst size. In Redis mode this is the global burst; "
        "in local mode it is per-Pod burst.",
    )
    PROMPT_CACHE_AUTO_INJECT: bool = Field(
        default=False,
        description="Default behavior for auto-injecting cache_control breakpoints (can be overridden per-request via bedrock_auto_cache)",
    )
    PROMPT_CACHE_TTL: str = Field(
        default="1h",
        description="Prompt cache TTL. Supported values: '5m' (default Anthropic TTL) or '1h' (extended). "
        "Using '1h' reduces cache misses in long-running sessions at no extra cost.",
    )

    # Redis configuration (for distributed rate limiting)
    REDIS_URL: Optional[str] = Field(
        default=None,
        description="Redis URL for distributed rate limiting. When set, rate limiting uses Redis "
        "for global coordination across Pods. Falls back to per-Pod memory when unavailable.",
    )

    # JWT settings
    JWT_SECRET_KEY: str = Field(description="JWT secret key for token signing")
    JWT_ALGORITHM: str = Field(default="HS256", description="JWT algorithm")
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(
        default=30, description="JWT access token expiration in minutes"
    )
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = Field(
        default=7, description="JWT refresh token expiration in days"
    )

    # Microsoft OAuth settings
    MICROSOFT_CLIENT_ID: Optional[str] = Field(
        default=None, description="Microsoft OAuth client ID"
    )
    MICROSOFT_CLIENT_SECRET: Optional[str] = Field(
        default=None, description="Microsoft OAuth client secret"
    )
    MICROSOFT_TENANT_ID: Optional[str] = Field(
        default=None, description="Microsoft OAuth tenant ID"
    )
    MICROSOFT_REDIRECT_URIS: str = Field(
        default="http://localhost:3000/auth/microsoft/callback",
        description="Allowed redirect URIs for Microsoft OAuth (comma-separated)",
    )

    # AWS Cognito OAuth settings
    COGNITO_USER_POOL_ID: Optional[str] = Field(
        default=None, description="AWS Cognito User Pool ID"
    )
    COGNITO_CLIENT_ID: Optional[str] = Field(
        default=None, description="AWS Cognito App Client ID"
    )
    COGNITO_CLIENT_SECRET: Optional[str] = Field(
        default=None, description="AWS Cognito App Client Secret"
    )
    COGNITO_REGION: Optional[str] = Field(
        default=None,
        description="AWS Cognito region (defaults to AWS_REGION if not specified)",
    )
    COGNITO_DOMAIN: Optional[str] = Field(
        default=None,
        description="AWS Cognito domain prefix (e.g., 'kbp-dev-612674025488')",
    )
    COGNITO_REDIRECT_URIS: str = Field(
        default="http://localhost:3000/auth/cognito/callback",
        description="Allowed redirect URIs for Cognito OAuth (comma-separated)",
    )

    # Observability settings
    LOG_LEVEL: str = Field(
        default="INFO",
        description="Log level: DEBUG, INFO, WARNING, ERROR",
    )
    LOG_FORMAT: str = Field(
        default="text",
        description="Log format: 'text' (human-readable) or 'json' (CloudWatch Logs Insights)",
    )
    ENABLE_METRICS: bool = Field(
        default=False,
        description="Enable CloudWatch EMF metrics emission",
    )
    OTEL_EXPORTER: str = Field(
        default="",
        description="OpenTelemetry exporter: '' (disabled), 'xray', 'otlp'",
    )

    # System configuration
    INITIAL_USER_BALANCE_USD: float = Field(
        default=5.0, description="Initial balance for new users in USD"
    )

    # Uvicorn server settings
    UVICORN_TIMEOUT_KEEP_ALIVE: int = Field(
        default=3700,
        description="Keep-alive timeout (seconds). Must be > ALB idle_timeout (3600s).",
    )
    UVICORN_LIMIT_CONCURRENCY: int = Field(
        default=100, description="Maximum concurrent connections per worker"
    )
    UVICORN_LIMIT_MAX_REQUESTS: int = Field(
        default=0,
        description="Max requests before worker restart (0=disabled). Set >0 only if memory leaks are observed.",
    )

    # Streaming settings
    STREAM_HEARTBEAT_INTERVAL: int = Field(
        default=15, description="Heartbeat interval for streaming responses (seconds)"
    )

    # Stream failover settings
    STREAM_FIRST_CONTENT_TIMEOUT: int = Field(
        default=600,
        description="Seconds to wait for first content chunk after stream starts. "
        "If exceeded, failover to next region/model. 0 disables failover.",
    )
    STREAM_MODEL_FALLBACK_CHAIN: str = Field(
        default="",
        description="Comma-separated model fallback chain for Level 2 degradation. "
        "Example: 'anthropic.claude-opus-4-0-20250514-v1:0,anthropic.claude-sonnet-4-20250514-v1:0'. "
        "Empty string disables model degradation.",
    )

    def get_allowed_origins(self) -> List[str]:
        """Get CORS allowed origins as a list."""
        if not self.ALLOWED_ORIGINS or self.ALLOWED_ORIGINS == "":
            return ["*"]
        # Remove quotes if present
        origins = self.ALLOWED_ORIGINS.strip('"').strip("'")
        return [origin.strip() for origin in origins.split(",") if origin.strip()]

    def get_microsoft_redirect_uris(self) -> List[str]:
        """Get allowed Microsoft OAuth redirect URIs as a list."""
        if not self.MICROSOFT_REDIRECT_URIS:
            return []
        # Remove quotes if present
        uris = self.MICROSOFT_REDIRECT_URIS.strip('"').strip("'")
        return [uri.strip() for uri in uris.split(",") if uri.strip()]

    def get_cognito_redirect_uris(self) -> List[str]:
        """Get allowed Cognito OAuth redirect URIs as a list."""
        if not self.COGNITO_REDIRECT_URIS:
            return []
        # Remove quotes if present
        uris = self.COGNITO_REDIRECT_URIS.strip('"').strip("'")
        return [uri.strip() for uri in uris.split(",") if uri.strip()]

    @validator("LOG_LEVEL")
    def validate_log_level(cls, v):
        valid = {"DEBUG", "INFO", "WARNING", "ERROR"}
        upper = v.upper()
        if upper not in valid:
            raise ValueError(f"LOG_LEVEL must be one of {valid}")
        return upper

    @validator("LOG_FORMAT")
    def validate_log_format(cls, v):
        if v not in ("text", "json"):
            raise ValueError("LOG_FORMAT must be 'text' or 'json'")
        return v

    @validator("JWT_SECRET_KEY")
    def validate_jwt_secret(cls, v):
        """Validate JWT secret key strength."""
        if len(v) < 32:
            raise ValueError("JWT_SECRET_KEY must be at least 32 characters long")
        return v

    @validator("DATABASE_URL")
    def validate_database_url(cls, v):
        """Validate database URL format."""
        if not v.startswith(("postgresql://", "postgresql+asyncpg://")):
            raise ValueError("DATABASE_URL must be a PostgreSQL URL")
        return v

    @validator("ALLOWED_ORIGINS")
    def validate_allowed_origins(cls, v, values):
        """Validate CORS origins configuration."""
        # Only allow wildcard CORS in local environment
        env = os.getenv("KBR_ENV", "non-prod")

        if v == "*" and env != "local":
            raise ValueError(
                f"Wildcard CORS origins ('*') not allowed in {env} environment. "
                "Only KBR_ENV=local supports '*'. Set specific allowed origins instead."
            )

        return v

    class Config:
        # Load both .env and environment-specific file
        # Priority: environment variables > .env.{KBR_ENV} > .env
        from pathlib import Path

        _backend_dir = Path(__file__).parent.parent.parent
        _env_name = os.getenv("KBR_ENV", "non-prod")
        _env_file_path = _backend_dir / f".env.{_env_name}"

        # Use environment-specific file if exists, otherwise fall back to .env
        env_file = (
            str(_env_file_path)
            if _env_file_path.exists()
            else str(_backend_dir / ".env")
        )
        env_file_encoding = "utf-8"
        case_sensitive = True
        # Use KBR_ prefix for environment variables
        env_prefix = "KBR_"
        extra = "ignore"  # Ignore extra environment variables not defined in the model


@functools.lru_cache()
def get_settings() -> Settings:
    """
    Get application settings (cached singleton).

    Settings are parsed once from environment variables and cached for the
    lifetime of the process. In Kubernetes, config changes (ConfigMap/env vars)
    require a pod restart to take effect, so caching is safe and avoids
    redundant env file reads and Pydantic validation on every call.
    """
    return Settings()


def get_environment() -> str:
    """Get the current environment from KBR_ENV variable. Only 'prod' and 'non-prod' are supported."""
    return os.getenv("KBR_ENV", "non-prod")


def is_production() -> bool:
    """Check if running in production mode."""
    return get_environment() == "prod"


def is_non_production() -> bool:
    """Check if running in non-production mode."""
    return get_environment() == "non-prod"
