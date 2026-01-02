#!/usr/bin/env python3
"""
Database migration helper for ActingWeb PostgreSQL backend.

This script simplifies running Alembic migrations by automatically finding
the alembic.ini file in the installed actingweb package and running migrations
with the correct configuration.

Usage:
    python scripts/migrate_db.py upgrade head    # Apply all migrations
    python scripts/migrate_db.py current         # Show current migration version
    python scripts/migrate_db.py downgrade -1    # Rollback one migration

Environment Variables (required):
    DATABASE_BACKEND=postgresql
    PG_DB_HOST=localhost
    PG_DB_PORT=5432
    PG_DB_NAME=actingweb
    PG_DB_USER=actingweb
    PG_DB_PASSWORD=yourpassword
"""

import os
import sys
from pathlib import Path


def find_alembic_ini():
    """Find alembic.ini in the installed actingweb package."""
    try:
        import actingweb

        actingweb_path = Path(actingweb.__file__).parent
        alembic_ini = actingweb_path / "db" / "postgresql" / "alembic.ini"

        if not alembic_ini.exists():
            print(f"❌ Error: alembic.ini not found at {alembic_ini}")
            print("Make sure actingweb[postgresql] is installed:")
            print("  poetry add 'actingweb[postgresql]'")
            sys.exit(1)

        return alembic_ini
    except ImportError:
        print("❌ Error: actingweb package not found")
        print("Install with: poetry add 'actingweb[postgresql]'")
        sys.exit(1)


def check_environment():
    """Verify required environment variables are set."""
    required_vars = [
        "DATABASE_BACKEND",
        "PG_DB_HOST",
        "PG_DB_PORT",
        "PG_DB_NAME",
        "PG_DB_USER",
        "PG_DB_PASSWORD",
    ]

    missing = [var for var in required_vars if not os.getenv(var)]

    if missing:
        print("❌ Error: Missing required environment variables:")
        for var in missing:
            print(f"  - {var}")
        print("\nSet them in .env file or export them:")
        print("  export DATABASE_BACKEND=postgresql")
        print("  export PG_DB_HOST=localhost")
        print("  export PG_DB_PORT=5432")
        print("  export PG_DB_NAME=actingweb")
        print("  export PG_DB_USER=actingweb")
        print("  export PG_DB_PASSWORD=yourpassword")
        sys.exit(1)

    if os.getenv("DATABASE_BACKEND") != "postgresql":
        print("⚠️  Warning: DATABASE_BACKEND is not set to 'postgresql'")
        print(f"   Current value: {os.getenv('DATABASE_BACKEND')}")
        print()


def run_alembic(alembic_ini, args):
    """Run alembic with the specified arguments."""
    from alembic.config import main as alembic_main

    # Build alembic command line arguments
    alembic_args = ["-c", str(alembic_ini)] + args

    print(f"🔧 Running: alembic {' '.join(alembic_args)}")
    print(f"📁 Config: {alembic_ini}")
    print(f"🗄️  Database: {os.getenv('PG_DB_NAME')} @ {os.getenv('PG_DB_HOST')}:{os.getenv('PG_DB_PORT')}")
    print()

    try:
        alembic_main(argv=alembic_args)
        print("\n✅ Migration completed successfully")
    except Exception as e:
        print(f"\n❌ Migration failed: {e}")
        sys.exit(1)


def main():
    """Main entry point."""
    # Load .env file if it exists
    try:
        from dotenv import load_dotenv
        if Path(".env").exists():
            load_dotenv()
            print("✅ Loaded environment variables from .env")
    except ImportError:
        pass

    # Check environment
    check_environment()

    # Find alembic.ini
    alembic_ini = find_alembic_ini()

    # Get alembic command (default to 'current')
    args = sys.argv[1:] if len(sys.argv) > 1 else ["current"]

    # Run alembic
    run_alembic(alembic_ini, args)


if __name__ == "__main__":
    main()
