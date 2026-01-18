"""Tests for version consistency across package files."""

import re
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

    def test_changelog_has_unreleased_section(self):
        """
        Verify that the CHANGELOG.rst has an 'Unreleased' section for PRs.

        This allows PRs to add entries to the Unreleased section without
        needing to update version numbers or dates. The actual release
        process (via git tags) will handle version consistency validation.
        """
        root_dir = Path(__file__).parent.parent
        changelog_path = root_dir / "CHANGELOG.rst"

        with open(changelog_path) as f:
            changelog_content = f.read()

        # Check that "Unreleased" appears near the top (within first 200 chars)
        first_200 = changelog_content[:200]
        assert re.search(r"^Unreleased\s*$", first_200, re.MULTILINE), (
            "CHANGELOG.rst must have an 'Unreleased' section at the top. "
            "This allows PRs to add changelog entries before release. "
            "The section should appear as a heading like:\n\n"
            "Unreleased\n"
            "----------\n"
        )
