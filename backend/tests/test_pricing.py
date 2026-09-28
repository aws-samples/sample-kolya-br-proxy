# Pyright cannot model this suite's legacy SQLAlchemy async fixtures and ORM
# Column instance values. Remove these overrides with the Mapped[] migration.
# pyright: reportCallIssue=false, reportArgumentType=false, reportGeneralTypeIssues=false, reportOptionalSubscript=false, reportOperatorIssue=false
"""
Unit tests for pricing system.
"""

import pytest
from decimal import Decimal
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.model_pricing import ModelPricing
from app.services.pricing_updater import PricingUpdater
from app.services.pricing import ModelPricing as PricingService


# Test database setup
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture
async def db_session():
    """Create a test database session."""
    engine = create_async_engine(
        TEST_DATABASE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    # Only create the model_pricing table for testing
    async with engine.begin() as conn:
        await conn.run_sync(ModelPricing.__table__.create, checkfirst=True)

    async_session_maker = sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )

    async with async_session_maker() as session:
        yield session

    # Clean up
    async with engine.begin() as conn:
        await conn.run_sync(ModelPricing.__table__.drop, checkfirst=True)

    await engine.dispose()


@pytest.fixture
def sample_pricing_data():
    """Sample pricing data for testing."""
    return [
        {
            "model_id": "claude-3-5-sonnet-20241022",
            "region": "us-east-1",
            "input_price_per_token": Decimal("0.000003"),
            "output_price_per_token": Decimal("0.000015"),
        },
        {
            "model_id": "claude-3-haiku-20240307",
            "region": "us-west-2",
            "input_price_per_token": Decimal("0.00000025"),
            "output_price_per_token": Decimal("0.00000125"),
        },
        {
            "model_id": "amazon.nova-pro-v1:0",
            "region": "default",
            "input_price_per_token": Decimal("0.0000008"),
            "output_price_per_token": Decimal("0.0000032"),
        },
    ]


class TestModelPricingModel:
    """Test ModelPricing database model."""

    @pytest.mark.asyncio
    async def test_create_pricing_record(self, db_session):
        """Test creating a pricing record."""
        pricing = ModelPricing(
            model_id="test-model",
            region="us-east-1",
            input_price_per_token=Decimal("0.000001"),
            output_price_per_token=Decimal("0.000002"),
            currency="USD",
            source="api",
            last_updated=datetime.utcnow(),
            created_at=datetime.utcnow(),
        )

        db_session.add(pricing)
        await db_session.commit()
        await db_session.refresh(pricing)

        assert pricing.id is not None
        assert pricing.model_id == "test-model"
        assert pricing.region == "us-east-1"
        assert pricing.input_price_per_token == Decimal("0.000001")
        assert pricing.output_price_per_token == Decimal("0.000002")
        assert pricing.currency == "USD"
        assert pricing.source == "api"

    @pytest.mark.asyncio
    async def test_unique_constraint(self, db_session):
        """Test unique constraint on model_id and region."""
        pricing1 = ModelPricing(
            model_id="test-model",
            region="us-east-1",
            input_price_per_token=Decimal("0.000001"),
            output_price_per_token=Decimal("0.000002"),
            currency="USD",
            source="api",
            last_updated=datetime.utcnow(),
            created_at=datetime.utcnow(),
        )

        db_session.add(pricing1)
        await db_session.commit()

        # Try to add duplicate
        pricing2 = ModelPricing(
            model_id="test-model",
            region="us-east-1",
            input_price_per_token=Decimal("0.000003"),
            output_price_per_token=Decimal("0.000004"),
            currency="USD",
            source="api",
            last_updated=datetime.utcnow(),
            created_at=datetime.utcnow(),
        )

        db_session.add(pricing2)

        with pytest.raises(Exception):  # Should raise IntegrityError
            await db_session.commit()


class TestPricingUpdater:
    """Test PricingUpdater service."""

    @pytest.mark.asyncio
    async def test_save_pricing_data(self, db_session, sample_pricing_data):
        """Test saving pricing data to database."""
        updater = PricingUpdater(db_session)
        count = await updater._save_pricing_data(sample_pricing_data, "api")

        assert count == 3

        # Verify data was saved
        pricing = await updater.get_pricing("claude-3-5-sonnet-20241022", "us-east-1")
        assert pricing is not None
        assert pricing[0] == Decimal("0.000003")
        assert pricing[1] == Decimal("0.000015")

    @pytest.mark.asyncio
    async def test_save_pricing_data_update_existing(self, db_session):
        """Test updating existing pricing data."""
        updater = PricingUpdater(db_session)

        # Insert initial data
        initial_data = [
            {
                "model_id": "test-model",
                "region": "us-east-1",
                "input_price_per_token": Decimal("0.000001"),
                "output_price_per_token": Decimal("0.000002"),
            }
        ]
        await updater._save_pricing_data(initial_data, "api")

        # Update with new prices
        updated_data = [
            {
                "model_id": "test-model",
                "region": "us-east-1",
                "input_price_per_token": Decimal("0.000003"),
                "output_price_per_token": Decimal("0.000004"),
            }
        ]
        count = await updater._save_pricing_data(updated_data, "scraper")

        assert count == 1

        # Verify prices were updated
        pricing = await updater.get_pricing("test-model", "us-east-1")
        assert pricing[0] == Decimal("0.000003")
        assert pricing[1] == Decimal("0.000004")

    @pytest.mark.asyncio
    async def test_get_pricing_with_fallback(self, db_session):
        """Test getting pricing with cross-region prefix fallback."""
        updater = PricingUpdater(db_session)

        # Save pricing for base model (no prefix)
        data = [
            {
                "model_id": "amazon.nova-pro-v1:0",
                "region": "us-east-1",
                "input_price_per_token": Decimal("0.000001"),
                "output_price_per_token": Decimal("0.000002"),
            }
        ]
        await updater._save_pricing_data(data, "api")

        # Lookup with cross-region prefix should fall back to base model
        pricing = await updater.get_pricing("us.amazon.nova-pro-v1:0", "us-east-1")
        assert pricing is not None
        assert pricing[0] == Decimal("0.000001")
        assert pricing[1] == Decimal("0.000002")

    @pytest.mark.asyncio
    async def test_official_profile_does_not_fallback_to_different_scope(
        self, db_session
    ):
        """A missing Global rate must not silently use base or Geo pricing."""
        updater = PricingUpdater(db_session)
        await updater._save_pricing_data(
            [
                {
                    "model_id": "openai.gpt-6-sol",
                    "region": "us-west-2",
                    "input_price_per_token": Decimal("0.000003"),
                    "output_price_per_token": Decimal("0.000012"),
                },
                {
                    "model_id": "us.openai.gpt-6-sol",
                    "region": "us-west-2",
                    "input_price_per_token": Decimal("0.0000022"),
                    "output_price_per_token": Decimal("0.000011"),
                },
            ],
            "api",
        )

        pricing = await updater.get_pricing("global.openai.gpt-6-sol", "us-west-2")

        assert pricing is None

    @pytest.mark.asyncio
    async def test_get_pricing_not_found(self, db_session):
        """Test getting pricing for non-existent model."""
        updater = PricingUpdater(db_session)
        pricing = await updater.get_pricing("non-existent-model", "us-east-1")
        assert pricing is None

    def test_normalize_region(self, db_session):
        """Test region display name mapping."""
        updater = PricingUpdater(db_session)

        assert updater._REGION_DISPLAY_NAMES.get("us-east-1") == "US East (N. Virginia)"
        assert updater._REGION_DISPLAY_NAMES.get("us-west-2") == "US West (Oregon)"
        assert updater._REGION_DISPLAY_NAMES.get("eu-central-1") == "Europe (Frankfurt)"
        assert updater._REGION_DISPLAY_NAMES.get("nonexistent") is None

    @pytest.mark.asyncio
    async def test_fetch_from_price_list_api_success(self, db_session):
        """Test fetching from AWS Price List API."""
        updater = PricingUpdater(db_session)

        mock_settings = MagicMock()
        mock_settings.AWS_REGION = "us-east-1"

        # Mock API response
        mock_response = {
            "products": {
                "PROD123": {
                    "attributes": {
                        "modelId": "claude-3-5-sonnet-20241022",
                        "location": "US East (N. Virginia)",
                    }
                }
            },
            "terms": {
                "OnDemand": {
                    "PROD123": {
                        "TERM123": {
                            "priceDimensions": {
                                "DIM1": {
                                    "unit": "Input Tokens",
                                    "description": "Input tokens",
                                    "pricePerUnit": {"USD": "3.00"},
                                },
                                "DIM2": {
                                    "unit": "Output Tokens",
                                    "description": "Output tokens",
                                    "pricePerUnit": {"USD": "15.00"},
                                },
                            }
                        }
                    }
                }
            },
        }

        with patch(
            "app.services.pricing_updater.get_settings", return_value=mock_settings
        ):
            with patch("httpx.AsyncClient") as mock_client:
                mock_response_obj = MagicMock()
                mock_response_obj.raise_for_status = MagicMock()
                mock_response_obj.json = MagicMock(return_value=mock_response)

                async def mock_get(*args, **kwargs):
                    return mock_response_obj

                mock_client.return_value.__aenter__.return_value.get = mock_get

                pricing_data = await updater._fetch_from_price_list_api()
                assert isinstance(pricing_data, list)

    @pytest.mark.asyncio
    async def test_update_all_pricing_parses_modern_global_standard_dimensions(
        self, db_session
    ):
        """Modern Price List tokenType fields map to the exact global profile."""
        updater = PricingUpdater(db_session)
        mock_settings = MagicMock(AWS_REGION="us-west-2")

        products = {}
        terms = {"OnDemand": {}}
        dimensions = {
            "INPUT": ("input_tokens_mantle", "0.0020000000"),
            "OUTPUT": ("output_tokens_mantle", "0.0060000000"),
            "CACHE": ("Cache Read Input Tokens", "0.0005000000"),
        }
        for sku, (token_type, price) in dimensions.items():
            products[sku] = {
                "attributes": {
                    "model": "xai.grok-4.6",
                    "regionCode": "us-west-2",
                    "service_tier": "global-standard",
                    "tokenType": token_type,
                    "usagetype": f"USW2-grok-{sku.lower()}-global-standard",
                }
            }
            terms["OnDemand"][sku] = {
                "TERM": {
                    "priceDimensions": {
                        "DIM": {
                            "unit": "1K tokens",
                            "pricePerUnit": {"USD": price},
                        }
                    }
                }
            }

        response = MagicMock()
        response.raise_for_status = MagicMock()
        response.json = MagicMock(return_value={"products": products, "terms": terms})

        with (
            patch(
                "app.services.pricing_updater.get_settings",
                return_value=mock_settings,
            ),
            patch("httpx.AsyncClient") as mock_client,
            patch.object(updater, "_build_dynamic_mapping", return_value={}),
            patch(
                "app.services.pricing_updater.refresh_mantle_registry",
                new=AsyncMock(return_value={}),
            ),
            patch.object(updater, "_scrape_aws_pricing_page", return_value=[]),
            patch.object(updater, "_backfill_from_reference_region", return_value=0),
            patch.object(updater, "ensure_official_profile_pricing", return_value=0),
            patch.object(updater, "cleanup_stale_cross_region_entries", return_value=0),
        ):
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=response
            )
            stats = await updater.update_all_pricing()

        assert stats["api_count"] == 1
        result = await db_session.execute(select(ModelPricing))
        record = result.scalar_one()
        assert record.model_id == "global.xai.grok-4.6"
        assert record.input_price_per_token == Decimal("0.000002")
        assert record.output_price_per_token == Decimal("0.000006")
        assert record.cached_input_price_per_token == Decimal("0.0000005")

    @pytest.mark.asyncio
    async def test_fetch_from_web_scraper_success(self, db_session):
        """Test fetching from AWS pricing page scraper."""
        updater = PricingUpdater(db_session)

        mock_html = "<html><body></body></html>"
        mock_json = {"regions": {}}

        mock_settings = MagicMock()
        mock_settings.AWS_REGION = "us-east-1"

        with patch(
            "app.services.pricing_updater.get_settings", return_value=mock_settings
        ):
            with patch("httpx.AsyncClient") as mock_client:
                mock_resp = MagicMock()
                mock_resp.raise_for_status = MagicMock()
                mock_resp.text = mock_html
                mock_resp.json = MagicMock(return_value=mock_json)

                async def mock_gather(*args, **kwargs):
                    return mock_resp, mock_resp, mock_resp

                import asyncio as _asyncio

                with patch.object(_asyncio, "gather", side_effect=mock_gather):
                    mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                        return_value=mock_resp
                    )
                    pricing_data = await updater._scrape_aws_pricing_page()
                    # Empty HTML → no pricing extracted, but no crash
                    assert isinstance(pricing_data, list)

    @pytest.mark.asyncio
    async def test_update_all_pricing_api_success(self, db_session):
        """Test update_all_pricing with API success."""
        updater = PricingUpdater(db_session)

        mock_settings = MagicMock()
        mock_settings.AWS_REGION = "us-east-1"

        mock_pricing_data = [
            {
                "model_id": "test-model",
                "region": "us-east-1",
                "input_price_per_token": Decimal("0.000001"),
                "output_price_per_token": Decimal("0.000002"),
            }
        ]

        with patch(
            "app.services.pricing_updater.get_settings", return_value=mock_settings
        ):
            with patch.object(
                updater, "_fetch_from_price_list_api", return_value=mock_pricing_data
            ):
                with patch.object(updater, "_scrape_aws_pricing_page", return_value=[]):
                    stats = await updater.update_all_pricing()

                    assert "api" in stats["source"]
                    assert stats["updated"] == 1
                    assert stats["failed"] == 0

    @pytest.mark.asyncio
    async def test_update_all_pricing_fallback_to_scraper(self, db_session):
        """Test update_all_pricing falls back to scraper when API fails."""
        updater = PricingUpdater(db_session)

        mock_settings = MagicMock()
        mock_settings.AWS_REGION = "us-east-1"

        mock_pricing_data = [
            {
                "model_id": "test-model",
                "region": "default",
                "input_price_per_token": Decimal("0.000001"),
                "output_price_per_token": Decimal("0.000002"),
            }
        ]

        with patch(
            "app.services.pricing_updater.get_settings", return_value=mock_settings
        ):
            with patch.object(
                updater,
                "_fetch_from_price_list_api",
                side_effect=Exception("API Error"),
            ):
                with patch.object(
                    updater, "_scrape_aws_pricing_page", return_value=mock_pricing_data
                ):
                    stats = await updater.update_all_pricing()

                    assert "aws-scraper" in stats["source"]
                    assert stats["updated"] == 1

    @pytest.mark.asyncio
    async def test_update_all_pricing_both_fail(self, db_session):
        """Test update_all_pricing when both sources fail."""
        updater = PricingUpdater(db_session)

        mock_settings = MagicMock()
        mock_settings.AWS_REGION = "us-east-1"

        with patch(
            "app.services.pricing_updater.get_settings", return_value=mock_settings
        ):
            with patch.object(
                updater,
                "_fetch_from_price_list_api",
                side_effect=Exception("API Error"),
            ):
                with patch.object(
                    updater,
                    "_scrape_aws_pricing_page",
                    side_effect=Exception("Scraper Error"),
                ):
                    stats = await updater.update_all_pricing()

                    assert stats["updated"] == 0
                    assert stats["failed"] == 2

    @pytest.mark.asyncio
    async def test_update_all_pricing_seeds_available_official_profiles(
        self, db_session
    ):
        """AWS model-card rates fill profiles omitted from Price List data."""
        updater = PricingUpdater(db_session)
        mock_settings = MagicMock(AWS_REGION="us-west-2")
        profile_cache = MagicMock()
        profile_cache._local_profile_ids = {
            "global.openai.gpt-6-sol",
            "global.xai.grok-4.6",
            "us.openai.gpt-6-astra",
        }
        bedrock = MagicMock(_profile_cache=profile_cache)

        with (
            patch(
                "app.services.pricing_updater.get_settings",
                return_value=mock_settings,
            ),
            patch(
                "app.services.bedrock.BedrockClient.get_instance",
                return_value=bedrock,
            ),
            patch.object(updater, "_build_dynamic_mapping", return_value={}),
            patch(
                "app.services.pricing_updater.refresh_mantle_registry",
                new=AsyncMock(return_value={}),
            ),
            patch.object(updater, "_fetch_from_price_list_api", return_value=[]),
            patch.object(updater, "_scrape_aws_pricing_page", return_value=[]),
            patch.object(updater, "_backfill_from_reference_region", return_value=0),
            patch.object(updater, "cleanup_stale_cross_region_entries", return_value=0),
        ):
            stats = await updater.update_all_pricing()

        assert stats["model_card_count"] == 3
        assert stats["updated"] == 3
        assert "aws-model-card" in stats["sources"]

        expected = {
            "global.openai.gpt-6-sol": ("0.000002", "0.000010", "0.0000002"),
            "global.xai.grok-4.6": ("0.000002", "0.000006", "0.0000005"),
            "us.openai.gpt-6-astra": ("0.000011", "0.000055", "0.0000011"),
        }
        result = await db_session.execute(select(ModelPricing))
        records = {record.model_id: record for record in result.scalars()}
        assert set(records) == set(expected)
        for model_id, prices in expected.items():
            record = records[model_id]
            assert record.region == "us-west-2"
            assert record.input_price_per_token == Decimal(prices[0])
            assert record.output_price_per_token == Decimal(prices[1])
            assert record.cached_input_price_per_token == Decimal(prices[2])
            assert record.source == "aws-model-card"


class TestPricingService:
    """Test ModelPricing service."""

    @pytest.mark.asyncio
    async def test_calculate_cost(self, db_session):
        """Test cost calculation."""
        # Setup pricing data
        updater = PricingUpdater(db_session)
        data = [
            {
                "model_id": "claude-3-5-sonnet-20241022",
                "region": "default",
                "input_price_per_token": Decimal("0.000003"),
                "output_price_per_token": Decimal("0.000015"),
            }
        ]
        await updater._save_pricing_data(data, "api")

        # Calculate cost
        pricing_service = PricingService(db_session)
        cost = await pricing_service.calculate_cost(
            model="claude-3-5-sonnet-20241022",
            prompt_tokens=1000,
            completion_tokens=500,
            region="default",
        )

        # Expected: (1000 * 0.000003) + (500 * 0.000015) = 0.003 + 0.0075 = 0.0105
        expected_cost = Decimal("0.0105")
        assert cost == expected_cost

    @pytest.mark.asyncio
    async def test_calculate_grok_uses_official_cache_read_rate(self, db_session):
        """Grok cache reads cost 25% of input, not the generic 10%."""
        model_id = "global.xai.grok-4.6"
        await PricingUpdater(db_session)._save_pricing_data(
            [
                {
                    "model_id": model_id,
                    "region": "us-west-2",
                    "input_price_per_token": Decimal("0.000002"),
                    "output_price_per_token": Decimal("0.000006"),
                    "cached_input_price_per_token": Decimal("0.0000005"),
                }
            ],
            "aws-model-card",
        )

        cost = await PricingService(db_session).calculate_cost(
            model=model_id,
            prompt_tokens=100,
            completion_tokens=20,
            cache_read_input_tokens=40,
            region="us-west-2",
        )

        assert cost == Decimal("0.000340")

    @pytest.mark.asyncio
    async def test_calculate_astra_uses_long_context_rates_for_full_request(
        self, db_session
    ):
        """Crossing 272K total input applies AWS long rates to every token."""
        model_id = "us.openai.gpt-6-astra"
        await PricingUpdater(db_session)._save_pricing_data(
            [
                {
                    "model_id": model_id,
                    "region": "us-west-2",
                    "input_price_per_token": Decimal("0.000011"),
                    "output_price_per_token": Decimal("0.000055"),
                    "cached_input_price_per_token": Decimal("0.0000011"),
                }
            ],
            "aws-model-card",
        )

        cost = await PricingService(db_session).calculate_cost(
            model=model_id,
            prompt_tokens=270_000,
            completion_tokens=10,
            cache_creation_input_tokens=1_000,
            cache_read_input_tokens=1_001,
            cache_ttl="5m",
            region="us-west-2",
        )

        assert cost == Decimal("5.9705272")

    @pytest.mark.asyncio
    async def test_calculate_cost_large_numbers(self, db_session):
        """Test cost calculation with large token counts."""
        updater = PricingUpdater(db_session)
        data = [
            {
                "model_id": "test-model",
                "region": "default",
                "input_price_per_token": Decimal("0.000003"),
                "output_price_per_token": Decimal("0.000015"),
            }
        ]
        await updater._save_pricing_data(data, "api")

        pricing_service = PricingService(db_session)
        cost = await pricing_service.calculate_cost(
            model="test-model",
            prompt_tokens=1_000_000,
            completion_tokens=500_000,
            region="default",
        )

        # Expected: (1M * 0.000003) + (500K * 0.000015) = 3.0 + 7.5 = 10.5
        expected_cost = Decimal("10.5")
        assert cost == expected_cost

    @pytest.mark.asyncio
    async def test_calculate_cost_model_not_found(self, db_session):
        """Test cost calculation when model pricing not found."""
        pricing_service = PricingService(db_session)

        with pytest.raises(ValueError) as exc_info:
            await pricing_service.calculate_cost(
                model="non-existent-model",
                prompt_tokens=1000,
                completion_tokens=500,
                region="default",
            )

        assert "Pricing not available" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_calculate_cost_zero_tokens(self, db_session):
        """Test cost calculation with zero tokens."""
        updater = PricingUpdater(db_session)
        data = [
            {
                "model_id": "test-model",
                "region": "default",
                "input_price_per_token": Decimal("0.000003"),
                "output_price_per_token": Decimal("0.000015"),
            }
        ]
        await updater._save_pricing_data(data, "api")

        pricing_service = PricingService(db_session)
        cost = await pricing_service.calculate_cost(
            model="test-model", prompt_tokens=0, completion_tokens=0, region="default"
        )

        assert cost == Decimal("0")

    @pytest.mark.asyncio
    async def test_get_model_pricing_info(self, db_session):
        """Test getting model pricing information."""
        updater = PricingUpdater(db_session)
        data = [
            {
                "model_id": "claude-3-5-sonnet-20241022",
                "region": "us-east-1",
                "input_price_per_token": Decimal("0.000003"),
                "output_price_per_token": Decimal("0.000015"),
            }
        ]
        await updater._save_pricing_data(data, "api")

        pricing_service = PricingService(db_session)
        info = await pricing_service.get_model_pricing_info(
            model="claude-3-5-sonnet-20241022", region="us-east-1"
        )

        assert info is not None
        assert info["model"] == "claude-3-5-sonnet-20241022"
        assert info["region"] == "us-east-1"
        assert Decimal(info["input_price_per_1m"]) == Decimal("3.0")
        assert Decimal(info["output_price_per_1m"]) == Decimal("15.0")
        assert Decimal(info["input_price_per_1k"]) == Decimal("0.003")
        assert Decimal(info["output_price_per_1k"]) == Decimal("0.015")

    @pytest.mark.asyncio
    async def test_get_model_pricing_info_not_found(self, db_session):
        """Test getting pricing info for non-existent model."""
        pricing_service = PricingService(db_session)
        info = await pricing_service.get_model_pricing_info(
            model="non-existent-model", region="us-east-1"
        )

        assert info is None

    @pytest.mark.asyncio
    async def test_calculate_cost_without_db(self):
        """Test cost calculation without database session."""
        pricing_service = PricingService(db=None)

        with pytest.raises(ValueError):
            await pricing_service.calculate_cost(
                model="test-model", prompt_tokens=1000, completion_tokens=500
            )


class TestPricingIntegration:
    """Integration tests for pricing system."""

    @pytest.mark.asyncio
    async def test_full_pricing_workflow(self, db_session, sample_pricing_data):
        """Test complete pricing workflow: update -> calculate -> query."""
        # Step 1: Update pricing
        updater = PricingUpdater(db_session)
        count = await updater._save_pricing_data(sample_pricing_data, "api")
        assert count == 3

        # Step 2: Calculate cost
        pricing_service = PricingService(db_session)
        cost = await pricing_service.calculate_cost(
            model="claude-3-5-sonnet-20241022",
            prompt_tokens=1000,
            completion_tokens=500,
            region="us-east-1",
        )
        assert cost > 0

        # Step 3: Query pricing info
        info = await pricing_service.get_model_pricing_info(
            model="claude-3-5-sonnet-20241022", region="us-east-1"
        )
        assert info is not None
        assert info["model"] == "claude-3-5-sonnet-20241022"

    @pytest.mark.asyncio
    async def test_multiple_regions_same_model(self, db_session):
        """Test handling multiple regions for same model."""
        updater = PricingUpdater(db_session)

        # Add pricing for multiple regions
        data = [
            {
                "model_id": "test-model",
                "region": "us-east-1",
                "input_price_per_token": Decimal("0.000003"),
                "output_price_per_token": Decimal("0.000015"),
            },
            {
                "model_id": "test-model",
                "region": "eu-west-1",
                "input_price_per_token": Decimal("0.0000035"),
                "output_price_per_token": Decimal("0.0000175"),
            },
        ]
        await updater._save_pricing_data(data, "api")

        # Get pricing for each region
        pricing_us = await updater.get_pricing("test-model", "us-east-1")
        pricing_eu = await updater.get_pricing("test-model", "eu-west-1")

        assert pricing_us[0] == Decimal("0.000003")
        assert pricing_eu[0] == Decimal("0.0000035")
        assert pricing_us[0] != pricing_eu[0]

    @pytest.mark.asyncio
    async def test_auto_initialize_pricing_on_empty_database(self, db_session):
        """Test automatic pricing initialization when database is empty (simulates app startup)."""
        from sqlalchemy import select

        updater = PricingUpdater(db_session)

        # Step 1: Verify database is empty
        result = await db_session.execute(select(ModelPricing))
        existing_records = result.scalars().all()
        assert len(existing_records) == 0, "Database should be empty at start"

        # Step 2: Mock API response
        mock_pricing_data = [
            {
                "model_id": "claude-3-5-sonnet-20241022",
                "region": "us-east-1",
                "input_price_per_token": Decimal("0.000003"),
                "output_price_per_token": Decimal("0.000015"),
            },
            {
                "model_id": "claude-3-haiku-20240307",
                "region": "us-west-2",
                "input_price_per_token": Decimal("0.00000025"),
                "output_price_per_token": Decimal("0.00000125"),
            },
            {
                "model_id": "amazon.nova-pro-v1:0",
                "region": "default",
                "input_price_per_token": Decimal("0.0000008"),
                "output_price_per_token": Decimal("0.0000032"),
            },
        ]

        mock_settings = MagicMock()
        mock_settings.AWS_REGION = "us-east-1"

        # Step 3: Simulate auto-fetch from API when database is empty
        with patch(
            "app.services.pricing_updater.get_settings", return_value=mock_settings
        ):
            with patch.object(
                updater, "_fetch_from_price_list_api", return_value=mock_pricing_data
            ):
                with patch.object(updater, "_scrape_aws_pricing_page", return_value=[]):
                    stats = await updater.update_all_pricing()

                    assert "api" in stats["source"]
                    assert stats["updated"] == 3
                    assert stats["failed"] == 0

        # Step 4: Verify data was inserted into database
        result = await db_session.execute(select(ModelPricing))
        all_records = result.scalars().all()
        assert len(all_records) == 3, "Should have 3 pricing records"

        # Step 5: Verify each model's pricing is accessible
        claude_sonnet = await updater.get_pricing(
            "claude-3-5-sonnet-20241022", "us-east-1"
        )
        assert claude_sonnet is not None
        assert claude_sonnet[0] == Decimal("0.000003")
        assert claude_sonnet[1] == Decimal("0.000015")

        claude_haiku = await updater.get_pricing("claude-3-haiku-20240307", "us-west-2")
        assert claude_haiku is not None
        assert claude_haiku[0] == Decimal("0.00000025")
        assert claude_haiku[1] == Decimal("0.00000125")

        nova_pro = await updater.get_pricing("amazon.nova-pro-v1:0", "default")
        assert nova_pro is not None
        assert nova_pro[0] == Decimal("0.0000008")
        assert nova_pro[1] == Decimal("0.0000032")

        # Step 6: Verify pricing service can calculate costs
        pricing_service = PricingService(db_session)
        cost = await pricing_service.calculate_cost(
            model="claude-3-5-sonnet-20241022",
            prompt_tokens=1000,
            completion_tokens=500,
            region="us-east-1",
        )
        # Expected: (1000 * 0.000003) + (500 * 0.000015) = 0.003 + 0.0075 = 0.0105
        assert cost == Decimal("0.0105")


class TestCacheWriteMultiplier:
    """Cache-write multiplier must match the TTL actually applied at Bedrock.

    Per Anthropic's docs the extended 1h TTL (2.0x write) is supported by all
    active Claude models on Bedrock, so a 1h cache_ttl bills 2.0x for them.
    Legacy Claude families (Claude 3.x and older) do not support the ``ttl``
    field: the proxy strips it and Bedrock writes a 5m cache billed at 1.25x,
    so billing must fall back to 1.25x for them. Billing is gated on the same
    predicate the request pipeline uses (``_model_supports_cache_ttl``),
    otherwise a 1h cache_ttl on an unsupported model over-bills the 0.75x
    difference on every cache-write token (see the hotspot over-billing
    incident that stemmed from a stale model allowlist).
    """

    INPUT_PRICE = Decimal("0.000005")

    async def _seed(self, db_session, model_id):
        updater = PricingUpdater(db_session)
        await updater._save_pricing_data(
            [
                {
                    "model_id": model_id,
                    "region": "us-west-2",
                    "input_price_per_token": self.INPUT_PRICE,
                    "output_price_per_token": Decimal("0.000025"),
                }
            ],
            "api",
        )

    async def _write_multiplier(self, db_session, model_id, cache_ttl):
        """Return the effective cache-write multiplier calculate_cost applied."""
        cw = 100_000
        cost = await PricingService(db_session).calculate_cost(
            model=model_id,
            prompt_tokens=0,
            completion_tokens=0,
            cache_creation_input_tokens=cw,
            cache_read_input_tokens=0,
            cache_ttl=cache_ttl,
            region="us-west-2",
        )
        return cost / (Decimal(cw) * self.INPUT_PRICE)

    @pytest.mark.asyncio
    async def test_legacy_model_1h_billed_as_5m(self, db_session):
        # Claude 3.x does NOT support the 1h ttl field -> must bill 1.25x
        model = "anthropic.claude-3-5-sonnet-20241022-v2:0"
        await self._seed(db_session, model)
        for ttl in ("1h", "5m", None):
            mult = await self._write_multiplier(db_session, model, ttl)
            assert mult == Decimal("1.25"), f"ttl={ttl} should bill 1.25x, got {mult}"

    @pytest.mark.asyncio
    async def test_active_models_honor_1h_ttl(self, db_session):
        # All active Claude models (incl. Opus 4.8) support 1h -> 1h bills 2.0x,
        # 5m bills 1.25x. Opus 4.8 is the model behind the hotspot incident.
        for model in (
            "global.anthropic.claude-opus-4-8",
            "global.anthropic.claude-opus-4-5-20251101-v1:0",
            "global.anthropic.claude-sonnet-4-6",
            "global.anthropic.claude-fable-5",
        ):
            await self._seed(db_session, model)
            assert await self._write_multiplier(db_session, model, "1h") == Decimal(
                "2.0"
            ), f"{model} 1h should bill 2.0x"
            assert await self._write_multiplier(db_session, model, "5m") == Decimal(
                "1.25"
            ), f"{model} 5m should bill 1.25x"

    @pytest.mark.asyncio
    async def test_cache_components_are_billed_once_at_their_own_rates(
        self, db_session
    ):
        model = "global.anthropic.claude-opus-4-8"
        await self._seed(db_session, model)

        cost = await PricingService(db_session).calculate_cost(
            model=model,
            prompt_tokens=100,
            completion_tokens=20,
            cache_creation_input_tokens=30,
            cache_read_input_tokens=40,
            cache_ttl="5m",
            region="us-west-2",
        )

        expected = (
            Decimal(100) * self.INPUT_PRICE
            + Decimal(20) * Decimal("0.000025")
            + Decimal(30) * self.INPUT_PRICE * Decimal("1.25")
            + Decimal(40) * self.INPUT_PRICE * Decimal("0.1")
        )
        assert cost == expected


def test_marketplace_model_id_mapping_is_exact_and_non_speculative():
    updater = PricingUpdater(MagicMock())

    assert updater._map_model_name_to_id("xai.grok-4.3") == "xai.grok-4.3"
    assert updater._map_model_name_to_id("Minimax M2.1") is None
    assert updater._map_model_name_to_id("Devstral") is None
    assert updater._map_model_name_to_id("Claude Mythos 5.1") is None
    assert updater._map_model_name_to_id("Llama 3.3 70B Custom") is None
    assert updater._map_model_name_to_id("Command") is None
    assert updater._map_model_name_to_id("Command-Light") is None
