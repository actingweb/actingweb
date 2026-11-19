"""Where the migration guide for this release is, for the library's messages.

A message that tells a reader to act names a section of the guide through
:func:`guide_section`, so renaming the guide is one edit here and
``tests/test_migration_guide.py`` can check that every quoted section is a
heading of the guide. The URL is what a ``pip`` user can open; the path is
the file in the source tree.
"""

GUIDE_PATH = "docs/migration/v4.0.rst"
GUIDE_URL = "https://actingweb.readthedocs.io/en/latest/docs/migration/v4.0.html"


def guide_section(title: str) -> str:
    """``title`` as a pointer into the guide, for an error or log message."""
    return f'the migration guide, "{title}" ({GUIDE_URL})'
