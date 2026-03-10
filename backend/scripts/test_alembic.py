#!/usr/bin/env python3
"""
Test script to verify Alembic configuration with async support.
"""

import sys
from pathlib import Path

# Add backend directory to Python path
backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))


def test_alembic_config():
    """Test Alembic configuration and database connectivity."""
    print("🔧 Testing Alembic Configuration")
    print("=" * 50)

    try:
        # Test configuration loading
        from app.core.config import get_settings

        settings = get_settings()

        print("✅ Configuration loaded successfully")
        print(f"📍 Database URL: {settings.DATABASE_URL[:50]}...")

        # Test database URL format
        if settings.DATABASE_URL.startswith("postgresql+asyncpg://"):
            print("✅ Database URL uses asyncpg driver (async compatible)")
        elif settings.DATABASE_URL.startswith("postgresql://"):
            print("⚠️  Database URL uses sync driver, will be converted to asyncpg")
        else:
            print("❌ Invalid database URL format")
            return False

        # Test Alembic environment
        print("\n🔍 Testing Alembic Environment...")

        # Import alembic env functions
        sys.path.insert(0, str(backend_dir / "alembic"))
        from env import get_url, target_metadata

        # Test URL retrieval
        alembic_url = get_url()
        print(f"✅ Alembic can retrieve database URL: {alembic_url[:50]}...")

        # Test metadata
        if target_metadata is not None:
            table_count = len(target_metadata.tables)
            print(f"✅ SQLAlchemy metadata loaded: {table_count} tables registered")

            # List registered tables
            if table_count > 0:
                table_names = list(target_metadata.tables.keys())
                print(f"   Tables: {', '.join(table_names)}")
        else:
            print("❌ No metadata found - models may not be imported correctly")
            return False

        print("\n🎯 Alembic Commands to Try:")
        print("   uv run alembic current              # Show current revision")
        print("   uv run alembic history              # Show migration history")
        print("   uv run alembic revision --autogenerate -m 'Initial migration'")
        print("   uv run alembic upgrade head         # Apply migrations")

        print("\n✨ Alembic configuration test completed successfully!")
        return True

    except ImportError as e:
        print(f"❌ Import Error: {e}")
        print("💡 Make sure all dependencies are installed: uv sync")
        return False
    except Exception as e:
        print(f"❌ Configuration Error: {e}")
        print("\n💡 Troubleshooting:")
        print("   1. Check that KBR_DATABASE_URL is set in environment or .env")
        print(
            "   2. Ensure database URL format: postgresql+asyncpg://user:pass@host:port/db"
        )
        print("   3. Verify database server is running and accessible")
        return False


def test_database_connection():
    """Test actual database connection."""
    print("\n🔗 Testing Database Connection...")

    try:
        import asyncio
        from app.core.database import init_db, engine

        async def test_connection():
            await init_db()

            # Test a simple query
            async with engine.begin() as conn:
                result = await conn.execute("SELECT 1 as test")
                row = result.fetchone()
                if row and row[0] == 1:
                    print("✅ Database connection successful")
                    return True
            return False

        success = asyncio.run(test_connection())
        return success

    except Exception as e:
        print(f"❌ Database connection failed: {e}")
        print("\n💡 Make sure:")
        print("   1. PostgreSQL server is running")
        print("   2. Database exists and is accessible")
        print("   3. Connection credentials are correct")
        return False


if __name__ == "__main__":
    print("🚀 Kolya BR Proxy - Alembic Configuration Test")
    print("=" * 60)

    # Test configuration
    config_ok = test_alembic_config()

    if config_ok:
        # Test database connection
        db_ok = test_database_connection()

        if db_ok:
            print("\n🎉 All tests passed! Alembic is ready to use.")
            print("\n📋 Next steps:")
            print(
                "   1. Create initial migration: uv run alembic revision --autogenerate -m 'Initial migration'"
            )
            print("   2. Apply migration: uv run alembic upgrade head")
        else:
            print("\n⚠️  Configuration OK, but database connection failed.")
            print("   Fix database connection before running migrations.")
    else:
        print("\n❌ Configuration test failed. Fix issues before proceeding.")

    sys.exit(0 if config_ok else 1)
