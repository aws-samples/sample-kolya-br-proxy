"""
Unit tests for pricing system.
"""

import pytest
from decimal import Decimal
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
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
        """Test getting pricing with fallback to default region."""
        updater = PricingUpdater(db_session)

        # Save pricing for default region only
        data = [
            {
                "model_id": "test-model",
                "region": "default",
                "input_price_per_token": Decimal("0.000001"),
                "output_price_per_token": Decimal("0.000002"),
            }
        ]
        await updater._save_pricing_data(data, "api")

        # Try to get pricing for specific region (should fallback to default)
        pricing = await updater.get_pricing("test-model", "eu-west-1")
        assert pricing is not None
        assert pricing[0] == Decimal("0.000001")
        assert pricing[1] == Decimal("0.000002")

    @pytest.mark.asyncio
    async def test_get_pricing_not_found(self, db_session):
        """Test getting pricing for non-existent model."""
        updater = PricingUpdater(db_session)
        pricing = await updater.get_pricing("non-existent-model", "us-east-1")
        assert pricing is None

    def test_normalize_region(self, db_session):
        """Test region normalization."""
        updater = PricingUpdater(db_session)

        assert updater._normalize_region("US East (N. Virginia)") == "us-east-1"
        assert updater._normalize_region("US West (Oregon)") == "us-west-2"
        assert updater._normalize_region("Europe (Frankfurt)") == "eu-central-1"
        assert updater._normalize_region("Unknown Region") == "default"

    @pytest.mark.asyncio
    async def test_fetch_from_price_list_api_success(self, db_session):
        """Test fetching from AWS Price List API."""
        updater = PricingUpdater(db_session)

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

        with patch("httpx.AsyncClient") as mock_client:
            # Create mock response object with synchronous json() method
            mock_response_obj = MagicMock()
            mock_response_obj.raise_for_status = MagicMock()
            mock_response_obj.json = MagicMock(return_value=mock_response)

            # Make get() return an awaitable that returns the mock response
            async def mock_get(*args, **kwargs):
                return mock_response_obj

            mock_client.return_value.__aenter__.return_value.get = mock_get

            pricing_data = await updater._fetch_from_price_list_api()

            assert len(pricing_data) > 0
            assert pricing_data[0]["model_id"] == "claude-3-5-sonnet-20241022"
            assert pricing_data[0]["region"] == "us-east-1"
            assert pricing_data[0]["input_price_per_token"] == Decimal("3.00") / 1000
            assert pricing_data[0]["output_price_per_token"] == Decimal("15.00") / 1000

    @pytest.mark.asyncio
    async def test_fetch_from_web_scraper_success(self, db_session):
        """Test fetching from web scraper."""
        updater = PricingUpdater(db_session)

        # Mock HTML response
        mock_html = """
        <html>
            <body>
                <div>Claude 3.5 Sonnet pricing: $3.00 per million input tokens, $15.00 per million output tokens</div>
                <div>Nova Pro pricing: $0.80 per million input tokens, $3.20 per million output tokens</div>
            </body>
        </html>
        """

        with patch("httpx.AsyncClient") as mock_client:
            mock_response_obj = AsyncMock()
            mock_response_obj.raise_for_status = MagicMock()
            mock_response_obj.text = mock_html

            mock_client.return_value.__aenter__.return_value.get.return_value = (
                mock_response_obj
            )

            pricing_data = await updater._fetch_from_web_scraper()

            # Should find Claude 3.5 Sonnet
            claude_pricing = [
                p for p in pricing_data if "claude-3-5-sonnet" in p["model_id"]
            ]
            assert len(claude_pricing) > 0
            assert (
                claude_pricing[0]["input_price_per_token"]
                == Decimal("3.00") / 1_000_000
            )
            assert (
                claude_pricing[0]["output_price_per_token"]
                == Decimal("15.00") / 1_000_000
            )

    @pytest.mark.asyncio
    async def test_update_all_pricing_api_success(self, db_session):
        """Test update_all_pricing with API success."""
        updater = PricingUpdater(db_session)

        mock_pricing_data = [
            {
                "model_id": "test-model",
                "region": "us-east-1",
                "input_price_per_token": Decimal("0.000001"),
                "output_price_per_token": Decimal("0.000002"),
            }
        ]

        with patch.object(
            updater, "_fetch_from_price_list_api", return_value=mock_pricing_data
        ):
            stats = await updater.update_all_pricing()

            assert stats["source"] == "api"
            assert stats["updated"] == 1
            assert stats["failed"] == 0

    @pytest.mark.asyncio
    async def test_update_all_pricing_fallback_to_scraper(self, db_session):
        """Test update_all_pricing falls back to scraper when API fails."""
        updater = PricingUpdater(db_session)

        mock_pricing_data = [
            {
                "model_id": "test-model",
                "region": "default",
                "input_price_per_token": Decimal("0.000001"),
                "output_price_per_token": Decimal("0.000002"),
            }
        ]

        with patch.object(
            updater, "_fetch_from_price_list_api", side_effect=Exception("API Error")
        ):
            with patch.object(
                updater, "_fetch_from_web_scraper", return_value=mock_pricing_data
            ):
                stats = await updater.update_all_pricing()

                assert stats["source"] == "scraper"
                assert stats["updated"] == 1
                assert stats["failed"] == 0

    @pytest.mark.asyncio
    async def test_update_all_pricing_both_fail(self, db_session):
        """Test update_all_pricing when both sources fail."""
        updater = PricingUpdater(db_session)

        with patch.object(
            updater, "_fetch_from_price_list_api", side_effect=Exception("API Error")
        ):
            with patch.object(
                updater,
                "_fetch_from_web_scraper",
                side_effect=Exception("Scraper Error"),
            ):
                stats = await updater.update_all_pricing()

                assert stats["updated"] == 0
                assert stats["failed"] == 1


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

        # Step 3: Simulate auto-fetch from API when database is empty
        with patch.object(
            updater, "_fetch_from_price_list_api", return_value=mock_pricing_data
        ):
            stats = await updater.update_all_pricing()

            # Verify API was called and data was saved
            assert stats["source"] == "api"
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
