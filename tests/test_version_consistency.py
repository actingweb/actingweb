"""Tests for version consistency across package files."""

import re
from datetime import datetime
from pathlib import Path


class TestVersionConsistency:
    """Test that version numbers are consistent across all package files."""

    def test_version_consistency(self):
        """Verify that CHANGELOG.rst, __init__.py, and pyproject.toml have matching versions."""
        # Get the root directory of the actingweb package
        root_dir = Path(__file__).parent.parent

        # 1. Extract version from CHANGELOG.rst
        changelog_path = root_dir / "CHANGELOG.rst"
        with open(changelog_path) as f:
            changelog_content = f.read()

        # Match version pattern like "v3.4.1: Nov 8, 2025"
        changelog_match = re.search(
            r"^v(\d+\.\d+(?:\.\d+)?):.*$", changelog_content, re.MULTILINE
        )
        assert changelog_match, "Could not find version in CHANGELOG.rst"
        changelog_version = changelog_match.group(1)

        # 2. Extract version from actingweb/__init__.py
        init_path = root_dir / "actingweb" / "__init__.py"
        with open(init_path) as f:
            init_content = f.read()

        # Match __version__ = "3.4.1"
        init_match = re.search(
            r'^__version__\s*=\s*["\'](\d+\.\d+(?:\.\d+)?)["\']',
            init_content,
            re.MULTILINE,
        )
        assert init_match, "Could not find __version__ in actingweb/__init__.py"
        init_version = init_match.group(1)

        # 3. Extract version from pyproject.toml
        pyproject_path = root_dir / "pyproject.toml"
        with open(pyproject_path) as f:
            pyproject_content = f.read()

        # Match version = "3.4.1"
        pyproject_match = re.search(
            r'^version\s*=\s*["\'](\d+\.\d+(?:\.\d+)?)["\']',
            pyproject_content,
            re.MULTILINE,
        )
        assert pyproject_match, "Could not find version in pyproject.toml"
        pyproject_version = pyproject_match.group(1)

        # 4. Assert all versions match
        assert changelog_version == init_version == pyproject_version, (
            f"Version mismatch detected:\n"
            f"  CHANGELOG.rst: {changelog_version}\n"
            f"  actingweb/__init__.py: {init_version}\n"
            f"  pyproject.toml: {pyproject_version}\n"
            f"All three files must have the same version number."
        )

    def test_changelog_has_recent_entry(self):
        """Verify that the CHANGELOG.rst has been updated with a recent entry."""
        root_dir = Path(__file__).parent.parent
        changelog_path = root_dir / "CHANGELOG.rst"

        with open(changelog_path) as f:
            changelog_content = f.read()

        # Check that the first version entry appears early in the file (within first 500 chars)
        # This ensures the CHANGELOG is being maintained at the top
        first_500 = changelog_content[:500]
        assert re.search(r"^v\d+\.\d+", first_500, re.MULTILINE), (
            "No version entry found at the top of CHANGELOG.rst. "
            "Ensure the changelog is updated with new versions at the top."
        )

    def test_changelog_date_not_tbd(self):
        """Verify that the topmost CHANGELOG entry has today's date, not TBD."""
        root_dir = Path(__file__).parent.parent
        changelog_path = root_dir / "CHANGELOG.rst"

        with open(changelog_path) as f:
            changelog_content = f.read()

        # Match version pattern like "v3.4.2: TBD, 2025" or "v3.4.1: Nov 8, 2025"
        version_match = re.search(
            r"^v(\d+\.\d+(?:\.\d+)?): (.+), (\d{4})$", changelog_content, re.MULTILINE
        )
        assert version_match, "Could not find version entry in CHANGELOG.rst"

        version = version_match.group(1)
        date_part = version_match.group(2).strip()
        year_part = version_match.group(3)

        # Check that date is not "TBD"
        assert date_part != "TBD", (
            f"CHANGELOG.rst version {version} has 'TBD' as the date. "
            f"Please update the date to today's date (e.g., '{datetime.now().strftime('%b %d, %Y')}')."
        )

        # Verify the date format and that it's today's date
        try:
            # Parse the date (e.g., "Nov 8")
            parsed_date = datetime.strptime(f"{date_part}, {year_part}", "%b %d, %Y")
        except ValueError as e:
            raise AssertionError(
                f"CHANGELOG.rst version {version} has invalid date format '{date_part}, {year_part}'. "
                f"Expected format: 'Mon DD, YYYY' (e.g., 'Nov 8, 2025'). Error: {e}"
            ) from e

        # Get today's date (ignoring time)
        today = datetime.now().date()
        changelog_date = parsed_date.date()

        # Verify it's today's date
        assert changelog_date == today, (
            f"CHANGELOG.rst version {version} has date {changelog_date.strftime('%b %d, %Y')} "
            f"but today is {today.strftime('%b %d, %Y')}. "
            f"Please update the CHANGELOG date to today's date."
        )
