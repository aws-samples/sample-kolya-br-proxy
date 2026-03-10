# Testing Guide

## Overview

This guide covers running unit tests for the Kolya BR Proxy pricing system.

## Prerequisites

Install test dependencies:

```bash
cd backend
pip install pytest pytest-asyncio httpx
```

## Running Tests

### Run All Tests

```bash
cd backend
pytest
```

### Run Specific Test File

```bash
pytest tests/test_pricing.py
```

### Run Specific Test Class

```bash
pytest tests/test_pricing.py::TestPricingService
```

### Run Specific Test Method

```bash
pytest tests/test_pricing.py::TestPricingService::test_calculate_cost
```

### Run with Verbose Output

```bash
pytest -v
```

### Run with Coverage Report

```bash
pip install pytest-cov
pytest --cov=app --cov-report=html
```

View coverage report:
```bash
open htmlcov/index.html
```

## Test Structure

### Test Files

- `tests/test_pricing.py` - Pricing system tests

### Test Classes

1. **TestModelPricingModel**
   - Tests for database model
   - CRUD operations
   - Unique constraints

2. **TestPricingUpdater**
   - Tests for PricingUpdater service
   - AWS API fetching
   - Web scraping fallback
   - Database operations

3. **TestPricingService**
   - Tests for cost calculation
   - Pricing queries
   - Error handling

4. **TestPricingIntegration**
   - End-to-end workflow tests
   - Multi-region scenarios

## Test Coverage

### ModelPricing Model
- ✅ Create pricing record
- ✅ Unique constraint validation
- ✅ Field validation

### PricingUpdater Service
- ✅ Save pricing data (insert)
- ✅ Save pricing data (update existing)
- ✅ Get pricing with region fallback
- ✅ Get pricing not found
- ✅ Normalize region names
- ✅ Fetch from AWS Price List API
- ✅ Fetch from web scraper
- ✅ Update all pricing (API success)
- ✅ Update all pricing (fallback to scraper)
- ✅ Update all pricing (both sources fail)

### PricingService
- ✅ Calculate cost (normal case)
- ✅ Calculate cost (large numbers)
- ✅ Calculate cost (model not found)
- ✅ Calculate cost (zero tokens)
- ✅ Get model pricing info
- ✅ Get pricing info not found
- ✅ Calculate cost without database

### Integration Tests
- ✅ Full pricing workflow
- ✅ Multiple regions for same model

## Writing New Tests

### Test Template

```python
import pytest
from decimal import Decimal

class TestNewFeature:
    """Test description."""

    @pytest.mark.asyncio
    async def test_feature(self, db_session):
        """Test specific behavior."""
        # Arrange
        # ... setup test data

        # Act
        # ... execute code under test

        # Assert
        # ... verify results
        assert result == expected
```

### Using Fixtures

```python
@pytest.fixture
async def sample_data():
    """Provide sample data for tests."""
    return {
        "model_id": "test-model",
        "region": "us-east-1",
    }

@pytest.mark.asyncio
async def test_with_fixture(db_session, sample_data):
    """Test using fixture."""
    # Use sample_data in test
    pass
```

### Mocking External APIs

```python
from unittest.mock import patch, AsyncMock

@pytest.mark.asyncio
async def test_api_call(db_session):
    """Test with mocked API."""
    with patch("httpx.AsyncClient") as mock_client:
        mock_response = AsyncMock()
        mock_response.json.return_value = {"data": "value"}
        mock_client.return_value.__aenter__.return_value.get.return_value = mock_response

        # Test code that uses httpx.AsyncClient
        pass
```

## Continuous Integration

### GitHub Actions Example

```yaml
name: Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest

    steps:
    - uses: actions/checkout@v2

    - name: Set up Python
      uses: actions/setup-python@v2
      with:
        python-version: '3.12'

    - name: Install dependencies
      run: |
        cd backend
        pip install -r requirements.txt
        pip install pytest pytest-asyncio pytest-cov

    - name: Run tests
      run: |
        cd backend
        pytest --cov=app --cov-report=xml

    - name: Upload coverage
      uses: codecov/codecov-action@v2
```

## Troubleshooting

### Issue: Tests fail with "No module named 'app'"

**Solution:**
```bash
cd backend
export PYTHONPATH="${PYTHONPATH}:$(pwd)"
pytest
```

### Issue: Async tests not running

**Solution:**
Ensure `pytest-asyncio` is installed:
```bash
pip install pytest-asyncio
```

### Issue: Database connection errors

**Solution:**
Tests use in-memory SQLite database. Ensure `aiosqlite` is installed:
```bash
pip install aiosqlite
```

## Best Practices

1. **Test Isolation**: Each test should be independent
2. **Use Fixtures**: Share common setup code
3. **Mock External Services**: Don't make real API calls
4. **Test Edge Cases**: Zero values, null values, errors
5. **Clear Test Names**: Describe what is being tested
6. **Arrange-Act-Assert**: Structure tests clearly
7. **Clean Up**: Use fixtures to handle cleanup automatically

## Performance

### Fast Tests
- Use in-memory database
- Mock external API calls
- Avoid unnecessary I/O

### Slow Tests
- Mark with `@pytest.mark.slow`
- Run separately: `pytest -m "not slow"`

## Code Coverage Goals

- Overall: > 80%
- Critical paths: 100%
- Error handling: 100%

Check current coverage:
```bash
pytest --cov=app --cov-report=term-missing
```
