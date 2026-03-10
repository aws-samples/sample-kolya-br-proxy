#!/bin/bash

# Kolya BR Proxy Development Setup Script

set -e

echo "🚀 Setting up Kolya BR Proxy for development..."

# Check if uv is installed
if ! command -v uv &> /dev/null; then
    echo "❌ uv is not installed. Please install uv first:"
    echo "   curl -LsSf https://astral.sh/uv/install.sh | sh"
    exit 1
fi

# Install dependencies
echo "📦 Installing dependencies..."
uv sync

# Create .env file if it doesn't exist
if [ ! -f .env ]; then
    echo "📝 Creating .env file from template..."
    cp .env.example .env
    echo "⚠️  Please edit .env file with your configuration before running the application"
else
    echo "✅ .env file already exists"
fi

# Validate .env file
if [ -f .env ]; then
    echo "✅ .env file exists"
    echo "🔍 Checking required environment variables..."

    # Check if required variables are set
    if grep -q "KBR_DATABASE_URL=" .env && grep -q "KBR_REDIS_URL=" .env && grep -q "KBR_JWT_SECRET_KEY=" .env; then
        echo "✅ Required environment variables found in .env"
    else
        echo "⚠️  Some required environment variables may be missing in .env"
        echo "   Please ensure KBR_DATABASE_URL, KBR_REDIS_URL, and KBR_JWT_SECRET_KEY are set"
    fi
else
    echo "⚠️  .env file not found"
fi

# Test configuration
echo "🔧 Testing configuration..."
cd backend
uv run python scripts/test_config.py

echo ""
echo "🔧 Testing Alembic configuration..."
uv run python scripts/test_alembic.py

echo ""
echo "✨ Setup completed!"
echo ""
echo "📋 Next steps:"
echo "   1. Edit .env file with your database and Redis URLs"
echo "   2. Ensure KBR_JWT_SECRET_KEY is at least 32 characters"
echo "   3. Run database migrations: cd backend && uv run alembic upgrade head"
echo "   4. Start development server: cd backend && uv run python run_dev.py"
echo ""
echo "🌐 The API will be available at: http://localhost:8000"
echo "📚 API docs will be available at: http://localhost:8000/docs"
echo ""
echo "📖 Documentation:"
echo "   - Quick Reference: docs/QUICK_REFERENCE.md"
echo "   - Development Guide: docs/DEVELOPMENT.md"
echo "   - Database Migrations: backend/MIGRATIONS.md"
