#!/usr/bin/env python3
"""
Migrate ActingWeb data from DynamoDB to PostgreSQL.

This script provides three operations:
1. export: Export all DynamoDB tables to JSON files
2. import: Import JSON files to PostgreSQL
3. validate: Verify migration integrity

Usage:
    # Export from DynamoDB
    python migrate_dynamodb_to_postgresql.py export --output-dir /tmp/export

    # Import to PostgreSQL
    python migrate_dynamodb_to_postgresql.py import --input-dir /tmp/export

    # Validate migration
    python migrate_dynamodb_to_postgresql.py validate --input-dir /tmp/export
"""

import argparse
import json
import logging
import os
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))


def setup_logging(level: str = "INFO") -> None:
    """Configure logging."""
    log_level = getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def export_dynamodb(
    output_dir: str,
    table_prefix: str = "",
    aws_profile: str | None = None,
) -> None:
    """Export all DynamoDB tables to JSON files.

    Args:
        output_dir: Directory to write JSON files
        table_prefix: DynamoDB table prefix (e.g., 'prod_')
        aws_profile: AWS profile name (optional)
    """
    logger = logging.getLogger(__name__)
    logger.info("Starting DynamoDB export to %s", output_dir)

    # Create output directory
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    # Configure AWS if profile specified
    if aws_profile:
        os.environ["AWS_PROFILE"] = aws_profile

    # Set table prefix
    if table_prefix:
        os.environ["AWS_DB_PREFIX"] = table_prefix

    # Ensure DynamoDB backend
    os.environ["DATABASE_BACKEND"] = "dynamodb"

    # Import DynamoDB models
    try:
        from actingweb.db.dynamodb.actor import (
            ActorModel,  # type: ignore[import-untyped]
        )
        from actingweb.db.dynamodb.attribute import (
            AttributeModel,  # type: ignore[import-untyped]
        )
        from actingweb.db.dynamodb.peertrustee import (
            PeerTrusteeModel,  # type: ignore[import-untyped]
        )
        from actingweb.db.dynamodb.property import (
            PropertyModel,  # type: ignore[import-untyped]
        )
        from actingweb.db.dynamodb.subscription import (
            SubscriptionModel,  # type: ignore[import-untyped]
        )
        from actingweb.db.dynamodb.subscription_diff import (
            SubscriptionDiffModel,  # type: ignore[import-untyped]
        )
        from actingweb.db.dynamodb.trust import (
            TrustModel,  # type: ignore[import-untyped]
        )
    except ImportError as e:
        logger.error("Failed to import DynamoDB models. Install with: poetry install --extras dynamodb")
        logger.error("Error: %s", e)
        sys.exit(1)

    # Table mapping
    tables = {
        "actors": ActorModel,
        "properties": PropertyModel,
        "attributes": AttributeModel,
        "trusts": TrustModel,
        "peertrustees": PeerTrusteeModel,
        "subscriptions": SubscriptionModel,
        "subscription_diffs": SubscriptionDiffModel,
    }

    # Export each table
    total_records = 0
    for table_name, model_class in tables.items():
        logger.info("Exporting %s...", table_name)
        records = []

        try:
            # Scan entire table
            for item in model_class.scan():
                # Convert to dict
                record = item.to_dict()
                records.append(record)

            # Write to JSON file
            output_file = output_path / f"{table_name}.json"
            with open(output_file, "w") as f:
                json.dump(records, f, indent=2, default=str)

            count = len(records)
            total_records += count
            logger.info("Exported %d records from %s to %s", count, table_name, output_file)

        except Exception as e:
            logger.error("Failed to export %s: %s", table_name, e)
            raise

    logger.info("Export complete: %d total records exported to %s", total_records, output_dir)


def import_postgresql(
    input_dir: str,
    pg_host: str = "localhost",
    pg_port: int = 5432,
    pg_database: str = "actingweb",
    pg_user: str = "actingweb",
    pg_password: str = "actingweb",
    skip_duplicates: bool = False,
) -> None:
    """Import JSON files to PostgreSQL.

    Args:
        input_dir: Directory containing JSON files
        pg_host: PostgreSQL host
        pg_port: PostgreSQL port
        pg_database: PostgreSQL database name
        pg_user: PostgreSQL user
        pg_password: PostgreSQL password
        skip_duplicates: Skip duplicate records instead of failing
    """
    logger = logging.getLogger(__name__)
    logger.info("Starting PostgreSQL import from %s", input_dir)

    # Configure PostgreSQL environment
    os.environ["DATABASE_BACKEND"] = "postgresql"
    os.environ["PG_DB_HOST"] = pg_host
    os.environ["PG_DB_PORT"] = str(pg_port)
    os.environ["PG_DB_NAME"] = pg_database
    os.environ["PG_DB_USER"] = pg_user
    os.environ["PG_DB_PASSWORD"] = pg_password

    # Import psycopg
    try:
        from actingweb.db.postgresql.connection import get_connection
    except ImportError as e:
        logger.error("Failed to import PostgreSQL dependencies. Install with: poetry install --extras postgresql")
        logger.error("Error: %s", e)
        sys.exit(1)

    input_path = Path(input_dir)

    # Import order (actors first due to foreign keys)
    import_order = [
        "actors",
        "properties",
        "attributes",
        "trusts",
        "peertrustees",
        "subscriptions",
        "subscription_diffs",
    ]

    total_imported = 0
    total_skipped = 0

    for table_name in import_order:
        json_file = input_path / f"{table_name}.json"

        if not json_file.exists():
            logger.warning("File not found: %s (skipping)", json_file)
            continue

        logger.info("Importing %s...", table_name)

        # Load JSON data
        with open(json_file) as f:
            records = json.load(f)

        if not records:
            logger.info("No records in %s (skipping)", table_name)
            continue

        # Import records
        imported = 0
        skipped = 0

        with get_connection() as conn:
            with conn.cursor() as cur:
                for record in records:
                    try:
                        if table_name == "actors":
                            cur.execute(
                                "INSERT INTO actors (id, creator, passphrase) VALUES (%s, %s, %s)",
                                (record.get("id"), record.get("creator"), record.get("passphrase")),
                            )

                        elif table_name == "properties":
                            cur.execute(
                                "INSERT INTO properties (id, name, value) VALUES (%s, %s, %s)",
                                (record.get("id"), record.get("name"), record.get("value")),
                            )

                        elif table_name == "attributes":
                            # Convert bucket_name composite key
                            bucket_name = f"{record.get('bucket')}:{record.get('name')}"
                            cur.execute(
                                """
                                INSERT INTO attributes
                                (id, bucket_name, bucket, name, data, timestamp, ttl_timestamp)
                                VALUES (%s, %s, %s, %s, %s, %s, %s)
                                """,
                                (
                                    record.get("id"),
                                    bucket_name,
                                    record.get("bucket"),
                                    record.get("name"),
                                    json.dumps(record.get("data")) if record.get("data") else None,
                                    record.get("timestamp"),
                                    record.get("ttl_timestamp"),
                                ),
                            )

                        elif table_name == "trusts":
                            cur.execute(
                                """
                                INSERT INTO trusts
                                (id, peerid, baseuri, type, relationship, secret, desc_text,
                                 approved, peer_approved, verified, verification_token,
                                 peer_identifier, established_via, created_at, last_accessed,
                                 client_name, client_version, client_platform, oauth_client_id)
                                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                                """,
                                (
                                    record.get("id"),
                                    record.get("peerid"),
                                    record.get("baseuri"),
                                    record.get("type"),
                                    record.get("relationship"),
                                    record.get("secret"),
                                    record.get("desc"),
                                    record.get("approved", False),
                                    record.get("peer_approved", False),
                                    record.get("verified", False),
                                    record.get("verification_token"),
                                    record.get("peer_identifier"),
                                    record.get("established_via"),
                                    record.get("created_at"),
                                    record.get("last_accessed"),
                                    record.get("client_name"),
                                    record.get("client_version"),
                                    record.get("client_platform"),
                                    record.get("oauth_client_id"),
                                ),
                            )

                        elif table_name == "peertrustees":
                            cur.execute(
                                """
                                INSERT INTO peertrustees
                                (id, peerid, baseuri, peer_type, relationship, secret, desc_text)
                                VALUES (%s, %s, %s, %s, %s, %s, %s)
                                """,
                                (
                                    record.get("id"),
                                    record.get("peerid"),
                                    record.get("baseuri"),
                                    record.get("type"),
                                    record.get("relationship"),
                                    record.get("secret"),
                                    record.get("desc"),
                                ),
                            )

                        elif table_name == "subscriptions":
                            # Convert peer_sub_id composite key
                            peer_sub_id = f"{record.get('peerid')}:{record.get('subid')}"
                            cur.execute(
                                """
                                INSERT INTO subscriptions
                                (id, peer_sub_id, peerid, subid, granularity, target, subtarget, resource, seqnr, callback)
                                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                                """,
                                (
                                    record.get("id"),
                                    peer_sub_id,
                                    record.get("peerid"),
                                    record.get("subid"),
                                    record.get("granularity"),
                                    record.get("target"),
                                    record.get("subtarget"),
                                    record.get("resource"),
                                    record.get("seqnr", 0),
                                    record.get("callback"),
                                ),
                            )

                        elif table_name == "subscription_diffs":
                            # Convert subid_seqnr composite key
                            subid_seqnr = f"{record.get('subid')}:{record.get('seqnr')}"
                            cur.execute(
                                """
                                INSERT INTO subscription_diffs
                                (id, subid_seqnr, subid, timestamp, diff, seqnr)
                                VALUES (%s, %s, %s, %s, %s, %s)
                                """,
                                (
                                    record.get("id"),
                                    subid_seqnr,
                                    record.get("subid"),
                                    record.get("timestamp"),
                                    record.get("diff"),
                                    record.get("seqnr"),
                                ),
                            )

                        imported += 1

                    except Exception as e:
                        if skip_duplicates and "duplicate key" in str(e).lower():
                            skipped += 1
                            logger.debug("Skipped duplicate: %s", record)
                        else:
                            logger.error("Failed to import record from %s: %s", table_name, e)
                            logger.error("Record: %s", record)
                            raise

                # Commit after each table
                conn.commit()

        logger.info("Imported %d records from %s (%d skipped)", imported, table_name, skipped)
        total_imported += imported
        total_skipped += skipped

    logger.info("Import complete: %d total records imported, %d skipped", total_imported, total_skipped)


def validate_migration(
    input_dir: str,
    pg_host: str = "localhost",
    pg_port: int = 5432,
    pg_database: str = "actingweb",
    pg_user: str = "actingweb",
    pg_password: str = "actingweb",
) -> bool:
    """Validate migration integrity.

    Args:
        input_dir: Directory containing JSON export files
        pg_host: PostgreSQL host
        pg_port: PostgreSQL port
        pg_database: PostgreSQL database name
        pg_user: PostgreSQL user
        pg_password: PostgreSQL password

    Returns:
        True if validation passes, False otherwise
    """
    logger = logging.getLogger(__name__)
    logger.info("Starting migration validation")

    # Configure PostgreSQL environment
    os.environ["DATABASE_BACKEND"] = "postgresql"
    os.environ["PG_DB_HOST"] = pg_host
    os.environ["PG_DB_PORT"] = str(pg_port)
    os.environ["PG_DB_NAME"] = pg_database
    os.environ["PG_DB_USER"] = pg_user
    os.environ["PG_DB_PASSWORD"] = pg_password

    # Import psycopg
    try:
        from actingweb.db.postgresql.connection import get_connection
    except ImportError as e:
        logger.error("Failed to import PostgreSQL dependencies. Install with: poetry install --extras postgresql")
        logger.error("Error: %s", e)
        sys.exit(1)

    input_path = Path(input_dir)
    all_valid = True

    # Tables to validate
    tables = [
        "actors",
        "properties",
        "attributes",
        "trusts",
        "peertrustees",
        "subscriptions",
        "subscription_diffs",
    ]

    with get_connection() as conn:
        with conn.cursor() as cur:
            for table_name in tables:
                json_file = input_path / f"{table_name}.json"

                if not json_file.exists():
                    logger.warning("File not found: %s (skipping validation)", json_file)
                    continue

                # Load JSON data
                with open(json_file) as f:
                    records = json.load(f)

                json_count = len(records)

                # Get PostgreSQL count
                cur.execute(f"SELECT COUNT(*) FROM {table_name}")
                pg_count = cur.fetchone()[0]

                # Compare counts
                if json_count == pg_count:
                    logger.info("✓ %s: %d records (match)", table_name, pg_count)
                else:
                    logger.error("✗ %s: JSON=%d, PostgreSQL=%d (MISMATCH)", table_name, json_count, pg_count)
                    all_valid = False

                # Sample validation (check first record exists)
                if records and json_count > 0:
                    first_record = records[0]

                    if table_name == "actors":
                        cur.execute("SELECT id FROM actors WHERE id = %s", (first_record.get("id"),))
                    elif table_name == "properties":
                        cur.execute(
                            "SELECT id FROM properties WHERE id = %s AND name = %s",
                            (first_record.get("id"), first_record.get("name")),
                        )
                    elif table_name == "trusts":
                        cur.execute(
                            "SELECT id FROM trusts WHERE id = %s AND peerid = %s",
                            (first_record.get("id"), first_record.get("peerid")),
                        )
                    # Add more sample checks as needed

                    if cur.fetchone():
                        logger.debug("  Sample record found in PostgreSQL")
                    else:
                        logger.warning("  Sample record NOT found in PostgreSQL")
                        all_valid = False

    if all_valid:
        logger.info("✓ Validation PASSED")
    else:
        logger.error("✗ Validation FAILED")

    return all_valid


def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Migrate ActingWeb data from DynamoDB to PostgreSQL",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Export from DynamoDB
  %(prog)s export --output-dir /tmp/export --table-prefix prod_

  # Import to PostgreSQL
  %(prog)s import --input-dir /tmp/export --pg-host localhost --pg-database actingweb

  # Validate migration
  %(prog)s validate --input-dir /tmp/export --pg-host localhost --pg-database actingweb
        """,
    )

    parser.add_argument(
        "operation",
        choices=["export", "import", "validate"],
        help="Operation to perform",
    )

    parser.add_argument(
        "--output-dir",
        help="Output directory for export (required for export)",
    )

    parser.add_argument(
        "--input-dir",
        help="Input directory for import/validate (required for import/validate)",
    )

    # DynamoDB options
    parser.add_argument(
        "--table-prefix",
        default="",
        help="DynamoDB table prefix (e.g., 'prod_')",
    )

    parser.add_argument(
        "--aws-profile",
        help="AWS profile name",
    )

    # PostgreSQL options
    parser.add_argument(
        "--pg-host",
        default="localhost",
        help="PostgreSQL host (default: localhost)",
    )

    parser.add_argument(
        "--pg-port",
        type=int,
        default=5432,
        help="PostgreSQL port (default: 5432)",
    )

    parser.add_argument(
        "--pg-database",
        default="actingweb",
        help="PostgreSQL database name (default: actingweb)",
    )

    parser.add_argument(
        "--pg-user",
        default="actingweb",
        help="PostgreSQL user (default: actingweb)",
    )

    parser.add_argument(
        "--pg-password",
        default="actingweb",
        help="PostgreSQL password (default: actingweb)",
    )

    # Import options
    parser.add_argument(
        "--skip-duplicates",
        action="store_true",
        help="Skip duplicate records during import instead of failing",
    )

    # General options
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level (default: INFO)",
    )

    args = parser.parse_args()

    # Setup logging
    setup_logging(args.log_level)

    # Validate arguments
    if args.operation == "export":
        if not args.output_dir:
            parser.error("--output-dir is required for export operation")
        export_dynamodb(
            output_dir=args.output_dir,
            table_prefix=args.table_prefix,
            aws_profile=args.aws_profile,
        )

    elif args.operation == "import":
        if not args.input_dir:
            parser.error("--input-dir is required for import operation")
        import_postgresql(
            input_dir=args.input_dir,
            pg_host=args.pg_host,
            pg_port=args.pg_port,
            pg_database=args.pg_database,
            pg_user=args.pg_user,
            pg_password=args.pg_password,
            skip_duplicates=args.skip_duplicates,
        )

    elif args.operation == "validate":
        if not args.input_dir:
            parser.error("--input-dir is required for validate operation")
        success = validate_migration(
            input_dir=args.input_dir,
            pg_host=args.pg_host,
            pg_port=args.pg_port,
            pg_database=args.pg_database,
            pg_user=args.pg_user,
            pg_password=args.pg_password,
        )
        sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
