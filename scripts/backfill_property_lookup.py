#!/usr/bin/env python3
"""Deprecated entry point: use ``actingweb-property-lookup backfill``.

The backfill moved into the package (``scripts/`` is not in the wheel, so a
PyPI deployment could not run this file). This shim keeps documented
invocations working: it prints the new command and delegates.

Flag mapping (the script's opt-in ``--dry-run`` becomes the command's
default; running without it now means ``--apply``)::

    --dry-run          -> (no --apply)
    (no --dry-run)     -> --apply
    --rps, --segments, --checkpoint-file, --properties -> unchanged
"""

import argparse
import sys


def translate(argv: list[str]) -> list[str]:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--rps", default=None)
    parser.add_argument("--segments", default=None)
    parser.add_argument("--checkpoint-file", default=None)
    parser.add_argument("--properties", default=None)
    args = parser.parse_args(argv)
    out = ["backfill"]
    if not args.dry_run:
        out.append("--apply")
    for flag in ("rps", "segments", "checkpoint_file", "properties"):
        value = getattr(args, flag)
        if value is not None:
            out += [f"--{flag.replace('_', '-')}", str(value)]
    return out


def main(argv: list[str] | None = None) -> int:
    from actingweb.maintenance.property_lookup import main as command

    translated = translate(sys.argv[1:] if argv is None else argv)
    print(
        "scripts/backfill_property_lookup.py is deprecated; running "
        f"'actingweb-property-lookup {' '.join(translated)}'",
        file=sys.stderr,
    )
    return command(translated)


if __name__ == "__main__":
    sys.exit(main())
