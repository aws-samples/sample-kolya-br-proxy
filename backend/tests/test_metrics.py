"""
Tests for CloudWatch EMF metrics module.
"""

import pytest
from unittest.mock import patch, MagicMock

from app.core.metrics import (
    configure_metrics,
    emit_request_metrics,
    emit_bedrock_call_metrics,
    emit_failover_metrics,
    emit_http_metrics,
)


class TestMetricsGuard:
    """All emit functions should be no-ops when metrics are disabled."""

    def setup_method(self):
        # Ensure _configured is False
        import app.core.metrics as m

        self._orig = m._configured
        m._configured = False

    def teardown_method(self):
        import app.core.metrics as m

        m._configured = self._orig

    @pytest.mark.asyncio
    async def test_emit_request_metrics_noop_when_disabled(self):
        # Should return immediately without error
        await emit_request_metrics(
            endpoint="/v1/chat/completions",
            model="test-model",
            duration_s=1.0,
            input_tokens=100,
            output_tokens=50,
        )

    @pytest.mark.asyncio
    async def test_emit_bedrock_call_metrics_noop_when_disabled(self):
        await emit_bedrock_call_metrics(
            model="test-model",
            region="us-east-1",
            duration_s=0.5,
            api="invoke_model",
        )

    @pytest.mark.asyncio
    async def test_emit_failover_metrics_noop_when_disabled(self):
        await emit_failover_metrics(
            primary_model="claude-sonnet",
            failover_target="claude-haiku",
            level="L2",
            duration_s=2.0,
            success=True,
        )

    @pytest.mark.asyncio
    async def test_emit_http_metrics_noop_when_disabled(self):
        await emit_http_metrics(
            method="POST",
            path="/v1/chat/completions",
            status_code=200,
            duration_s=0.5,
        )


class TestConfigureMetrics:
    """Test configure_metrics() initialization."""

    def teardown_method(self):
        import app.core.metrics as m

        m._configured = False

    @patch("app.core.metrics.get_settings")
    def test_disabled_by_default(self, mock_settings):
        mock_settings.return_value = MagicMock(ENABLE_METRICS=False)
        import app.core.metrics as m

        m._configured = False
        configure_metrics()
        assert m._configured is False

    @patch("app.core.metrics.get_settings")
    def test_enabled_sets_configured(self, mock_settings):
        mock_settings.return_value = MagicMock(ENABLE_METRICS=True)

        # Mock the aws_embedded_metrics config (may not be installed in dev)
        mock_emf_config = MagicMock()
        mock_emf_module = MagicMock()
        mock_emf_module.get_config.return_value = mock_emf_config

        import sys

        with patch.dict(sys.modules, {"aws_embedded_metrics.config": mock_emf_module}):
            import app.core.metrics as m

            m._configured = False
            configure_metrics()
            assert m._configured is True
