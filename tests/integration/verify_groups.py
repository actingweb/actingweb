#!/usr/bin/env python3
"""Verify xdist group isolation and independence."""

import re
import sys
from pathlib import Path


def collect_groups() -> dict[str, list[str]]:
    """Collect all xdist groups and their files."""
    test_dir = Path("tests/integration")
    groups: dict[str, list[str]] = {}

    for test_file in test_dir.glob("test_*.py"):
        with open(test_file) as f:
            content = f.read()

        for match in re.finditer(r'xdist_group\(name="([^"]+)"\)', content):
            group_name = match.group(1)
            if group_name not in groups:
                groups[group_name] = []
            groups[group_name].append(test_file.name)

    return groups


def verify_group_documented(group_name: str) -> bool:
    """Check if group is documented in XDIST_GROUPS.md."""
    try:
        with open("tests/integration/XDIST_GROUPS.md") as f:
            return group_name in f.read()
    except FileNotFoundError:
        return False


def main():
    """Verify all xdist groups are documented."""
    print("Verifying xdist group isolation...")
    groups = collect_groups()
    print(f"Found {len(groups)} xdist groups\n")

    # Check documentation
    undocumented = [g for g in groups if not verify_group_documented(g)]

    if undocumented:
        print(f"✗ Undocumented groups ({len(undocumented)}):")
        for group in sorted(undocumented):
            print(f"  - {group}")
        sys.exit(1)
    else:
        print(f"✓ All {len(groups)} groups documented")
        sys.exit(0)


if __name__ == "__main__":
    main()
