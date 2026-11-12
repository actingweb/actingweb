#!/usr/bin/env python3
"""Verify xdist group isolation and independence, and the wire rows registry.

The wire check (``check_wire_rows``): every recording under
``tests/integration/wire/`` belongs to a row in ``wire/rows.toml``, every row
has its recordings, and every row names an existing scenario, its owners,
whether it is an exposure, what it records and why its file was written.

The phase check (``check_wire_phase``): every commit on the branch since it
left ``master`` (merges included) that changes or removes a recording that
exists at the merge base names, in a ``Wire-Phase: <plan>:<phase>`` trailer,
a phase that ``rows.toml`` at the merge base lists among that row's owners.
A recording added on the branch needs no owner. The check needs the
branch's history; on a shallow checkout (CI's test job) it reports that it
was skipped, so it is a local gate over commits already made.
"""

import re
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any

WIRE_TOPOLOGIES = ("same_host", "two_hosts")
WIRE_ROW_KEYS = {
    "test",
    "topologies",
    "owners",
    "exposure",
    "expected",
    "reason",
    "second",
}
WIRE_DIR = "tests/integration/wire"


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
    files = [f"{row}.{t}.json" for t in topologies] if topologies else [f"{row}.json"]
    second = entry.get("second")
    if isinstance(second, dict) and isinstance(second.get("file"), str):
        files.append(second["file"])
    return files


def recording_rows(rows: dict[str, dict[str, Any]]) -> dict[str, str]:
    """Each recording file a registry names, mapped to its row."""
    return {
        name: row for row, entry in rows.items() for name in _expected_files(row, entry)
    }


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
        second = entry.get("second")
        if second is not None and (
            not isinstance(second, dict)
            or not isinstance(second.get("file"), str)
            or not str(second.get("file", "")).startswith(f"{row}.")
            or not second.get("why")
        ):
            problems.append(
                f'{row}: second must be {{ file = "{row}.<...>.json", why = "..." }}'
            )
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


def wire_phase_problems(
    commit: str,
    changes: list[tuple[str, str]],
    trailers: list[str],
    rows_base: dict[str, dict[str, Any]],
    base_files: set[str],
) -> list[str]:
    """What is wrong with one commit's recording changes.

    ``changes``: ``(status, file name)`` for each recording the commit
    touches (``A`` added, ``M`` modified, ``D`` deleted). ``trailers``: its
    ``Wire-Phase`` values. ``rows_base``: the registry's rows at the merge
    base with ``master``; ``base_files``: the recordings that exist there.

    Owners are read at the merge base, never on the branch, so no commit on
    a branch can make its own phase an owner: an ownership change lands on
    ``master`` first. A recording that does not exist at the merge base was
    added on this branch and is not in the regression set yet, so the
    branch may change it freely."""
    problems: list[str] = []
    short = commit[:10]
    touched = [
        (st, name) for st, name in changes if st in ("M", "D") and name in base_files
    ]
    if not touched:
        return problems
    if len(trailers) != 1:
        names = ", ".join(sorted(name for _, name in touched))
        problems.append(
            f"{short}: changes {names} and must carry exactly one"
            f" 'Wire-Phase: <plan>:<phase>' trailer (has {len(trailers)})"
        )
        return problems
    phase = trailers[0].strip()
    base = recording_rows(rows_base)
    for _status, name in touched:
        row = base.get(name)
        if row is None:
            problems.append(f"{short}: {name} belongs to no row in rows.toml")
            continue
        owners = rows_base[row].get("owners") or []
        if phase not in owners:
            problems.append(
                f"{short}: {name} ({row}) changed under Wire-Phase {phase},"
                f" which is not among its owners {owners} at the merge base"
            )
    return problems


_REPO = Path(__file__).resolve().parents[2]


def _git(*args: str) -> str:
    """Run git at the repository root, wherever this script is run from."""
    return subprocess.run(
        ["git", "-C", str(_REPO), *args], check=True, capture_output=True, text=True
    ).stdout


def _merge_base(bases: tuple[str, ...]) -> tuple[str | None, str]:
    """The newest merge base of HEAD with any of ``bases`` that exists (a
    stale local ``master`` must not pull upstream commits into the range)."""
    found: list[str] = []
    for base in bases:
        try:
            found.append(_git("merge-base", "HEAD", base).strip())
        except (subprocess.CalledProcessError, FileNotFoundError):
            continue
    if not found:
        return None, " or ".join(bases)
    newest = found[0]
    for candidate in found[1:]:
        try:
            _git("merge-base", "--is-ancestor", newest, candidate)
            newest = candidate
        except subprocess.CalledProcessError:
            pass
    return newest, ""


def check_wire_phase(
    bases: tuple[str, ...] = ("origin/master", "master"),
) -> tuple[list[str], str | None]:
    """Check the ``Wire-Phase`` trailers of the commits since the merge base
    (merges included: a merge is read against its first parent, less what
    it took unchanged from its other parents). It checks
    commits already made, so run it after committing and amend if needed.

    Returns (problems, why it was skipped or None)."""
    merge_base, tried = _merge_base(bases)
    if merge_base is None:
        return [], f"no merge base with {tried} (a shallow checkout?)"
    try:
        rows_base = tomllib.loads(
            _git("show", f"{merge_base}:{WIRE_DIR}/rows.toml")
        ).get("rows", {})
    except subprocess.CalledProcessError:
        rows_base = {}
    except tomllib.TOMLDecodeError as exc:
        return [f"rows.toml at the merge base does not parse: {exc}"], None
    base_files = {
        Path(path).name
        for path in _git(
            "ls-tree", "-r", "--name-only", merge_base, "--", WIRE_DIR
        ).splitlines()
        if path.endswith(".json")
    }
    commits = _git("rev-list", "--reverse", f"{merge_base}..HEAD")
    problems: list[str] = []
    for commit in commits.split():
        listing = _git(
            "diff",
            "--name-status",
            "--no-renames",
            f"{commit}^1",
            commit,
            "--",
            WIRE_DIR,
        )
        changes = []
        for line in listing.splitlines():
            status, _, path = line.partition("\t")
            if path.endswith(".json"):
                changes.append((status[:1], Path(path).name))
        # A merge's own change is what differs from every parent. A file
        # taken unchanged from another parent (``master`` merged in, or a
        # side branch) was checked where that parent changed it: on
        # ``master``, or at its own commit in this range.
        parents = _git("rev-list", "--parents", "-n", "1", commit).split()[1:]
        for other in parents[1:]:
            differs = {
                Path(path).name
                for path in _git(
                    "diff", "--name-only", "--no-renames", other, commit, "--", WIRE_DIR
                ).splitlines()
            }
            changes = [(st, name) for st, name in changes if name in differs]
        if not any(status in ("M", "D") for status, _ in changes):
            continue
        trailers = [
            t
            for t in _git(
                "log", "-1", "--format=%(trailers:key=Wire-Phase,valueonly)", commit
            ).splitlines()
            if t.strip()
        ]
        problems += wire_phase_problems(
            commit, changes, trailers, rows_base, base_files
        )
    return problems, None


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

    phase_problems, skipped = check_wire_phase()
    if skipped:
        print(f"- Wire-Phase trailers not checked: {skipped}")
    elif phase_problems:
        print(f"✗ Wire-Phase trailers ({len(phase_problems)}):")
        for problem in phase_problems:
            print(f"  - {problem}")
        failed = True
    else:
        print("✓ Wire-Phase trailers match the owners of every changed recording")

    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
