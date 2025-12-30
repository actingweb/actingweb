"""
Performance benchmarks for ActingWeb database backends.

This package contains performance tests comparing DynamoDB and PostgreSQL backends.

Usage:
    # Run all performance tests
    pytest tests/performance/ -v

    # Run with specific backend
    DATABASE_BACKEND=postgresql pytest tests/performance/ -v

    # Generate JSON benchmark results
    pytest tests/performance/ --benchmark-json=results.json

    # Compare benchmarks (requires pytest-benchmark)
    pytest tests/performance/ --benchmark-compare

Installation:
    poetry add --group dev pytest-benchmark
"""
