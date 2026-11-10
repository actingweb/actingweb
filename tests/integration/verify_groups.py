#!/usr/bin/env python3
"""Verify xdist group isolation and independence, and the wire rows registry.

The wire check (``check_wire_rows``): every recording under
``tests/integration/wire/`` belongs to a row in ``wire/rows.toml``, every row
has its recordings, and every row names an existing scenario, its owners,
whether it is an exposure, what it records and why its file was written.
"""

import re
import sys
import tomllib
from pathlib import Path
from typing import Any

WIRE_TOPOLOGIES = ("same_host", "two_hosts")
WIRE_ROW_KEYS = {"test", "topologies", "owners", "exposure", "expected", "reason"}


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


def _in_ranges(row_id: str, ranges: list[str]) -> bool:
    """Whether a row id (``WD12``) falls in one of ``ranges`` (``WD1-WD20``,
    ``WM1``)."""
    match = re.fullmatch(r"([A-Z]+)(\d+)", row_id)
    if not match:
        return False
    prefix, number = match.group(1), int(match.group(2))
    for item in ranges:
        bounds = re.fullmatch(r"([A-Z]+)(\d+)(?:-([A-Z]+)(\d+))?", item)
        if not bounds or bounds.group(1) != prefix:
            continue
        low = int(bounds.group(2))
        high = int(bounds.group(4)) if bounds.group(4) else low
        if low <= number <= high:
            return True
    return False


def _expected_files(row: str, entry: dict[str, Any]) -> list[str]:
    topologies = entry.get("topologies")
    if topologies:
        return [f"{row}.{t}.json" for t in topologies]
    return [f"{row}.json"]


def check_wire_rows(
    wire_dir: Path = Path("tests/integration/wire"),
    test_dir: Path = Path("tests/integration"),
) -> tuple[list[str], list[str]]:
    """Check the wire rows registry; return (problems, exposure rows)."""
    registry_path = wire_dir / "rows.toml"
    if not registry_path.exists():
        return [f"{registry_path} is missing"], []
    try:
        registry = tomllib.loads(registry_path.read_text())
    except tomllib.TOMLDecodeError as exc:
        return [f"{registry_path}: {exc}"], []

    problems: list[str] = []
    exposures: list[str] = []
    rows: dict[str, dict[str, Any]] = registry.get("rows", {})
    reserved: dict[str, list[str]] = registry.get("reserved", {})
    expected_files: dict[str, str] = {}

    for row, entry in sorted(rows.items()):
        row_id = row.split(".", 1)[0]
        if not any(_in_ranges(row_id, ranges) for ranges in reserved.values()):
            problems.append(f"{row}: id {row_id} is in no [reserved] range")
        unknown = set(entry) - WIRE_ROW_KEYS
        if unknown:
            problems.append(f"{row}: unknown keys {sorted(unknown)}")
        test = entry.get("test", "")
        file_name, _, function = test.partition("::")
        test_file = test_dir / file_name
        if not function or not test_file.exists():
            problems.append(f"{row}: test {test!r} is not <file>::<function>")
        elif not re.search(
            rf"^def {re.escape(function)}\(", test_file.read_text(), re.MULTILINE
        ):
            problems.append(f"{row}: no scenario {function} in {file_name}")
        owners = entry.get("owners")
        if not isinstance(owners, list) or not all(
            isinstance(o, str) and re.fullmatch(r"[a-z0-9-]+:\d+", o) for o in owners
        ):
            problems.append(f"{row}: owners must be a list of '<plan>:<phase>'")
        else:
            for owner in owners:
                if owner.split(":", 1)[0] not in reserved:
                    problems.append(f"{row}: owner {owner} is not a [reserved] plan")
        if not isinstance(entry.get("exposure"), bool):
            problems.append(f"{row}: exposure must be true or false")
        elif entry["exposure"]:
            exposures.append(row)
            # An exposure is a known hole: some phase must be the one that
            # closes it.
            if isinstance(owners, list) and not owners:
                problems.append(f"{row}: an exposure row must name an owner")
        if not entry.get("expected"):
            problems.append(f"{row}: expected is empty")
        reason = entry.get("reason")
        if not isinstance(reason, list) or not reason:
            problems.append(f"{row}: reason must be a non-empty list")
        topologies = entry.get("topologies")
        if topologies is not None and (
            not topologies or any(t not in WIRE_TOPOLOGIES for t in topologies)
        ):
            problems.append(f"{row}: topologies must be from {WIRE_TOPOLOGIES}")
        for name in _expected_files(row, entry):
            expected_files[name] = row
            if not (wire_dir / name).exists():
                problems.append(f"{row}: no recording {name}")

    for path in sorted(wire_dir.glob("*.json")):
        if path.name.endswith(".actual.json"):
            problems.append(f"{path.name}: a failed comparison's output is left over")
        elif path.name not in expected_files:
            problems.append(f"{path.name}: no row in rows.toml")

    return problems, exposures


def main():
    """Verify all xdist groups are documented and the wire rows registry."""
    print("Verifying xdist group isolation...")
    groups = collect_groups()
    print(f"Found {len(groups)} xdist groups\n")
    failed = False

    # Check documentation
    undocumented = [g for g in groups if not verify_group_documented(g)]

    if undocumented:
        print(f"✗ Undocumented groups ({len(undocumented)}):")
        for group in sorted(undocumented):
            print(f"  - {group}")
        failed = True
    else:
        print(f"✓ All {len(groups)} groups documented")

    problems, exposures = check_wire_rows()
    if problems:
        print(f"✗ Wire rows registry ({len(problems)}):")
        for problem in problems:
            print(f"  - {problem}")
        failed = True
    else:
        print("✓ Wire rows registry consistent")
    if exposures:
        print(f"  Exposure rows ({len(exposures)}): {', '.join(exposures)}")

    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
