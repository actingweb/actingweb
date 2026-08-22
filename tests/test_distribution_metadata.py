"""
Guards the AI/MCP discovery metadata added to pyproject.toml (Phase 4 of
thoughts/plans/2026-08-22-ai-agent-discoverability.md) against silent
reversion.

Reads *installed* package metadata via importlib.metadata, not
pyproject.toml directly. After editing pyproject.toml locally, run
`poetry install` before running this test, or it asserts against stale
values and fails red locally while passing in CI (which installs fresh).
"""

import importlib.metadata


def test_distribution_metadata_has_ai_keywords():
    meta = importlib.metadata.metadata("actingweb")
    keywords = meta["Keywords"] if "Keywords" in meta else ""
    for expected in ("mcp", "ai", "llm", "agent", "model-context-protocol"):
        assert expected in keywords, (
            f"'{expected}' missing from installed Keywords metadata: {keywords!r}. "
            "Did you run `poetry install` after editing pyproject.toml?"
        )


def test_distribution_metadata_urls_are_https():
    meta = importlib.metadata.metadata("actingweb")
    project_urls = meta.get_all("Project-URL") or []
    urls = {}
    for entry in project_urls:
        name, _, url = entry.partition(",")
        urls[name.strip()] = url.strip()

    for name in ("Homepage", "Documentation", "Repository"):
        assert name in urls, f"Project-URL '{name}' missing: {urls}"
        assert urls[name].startswith("https://"), (
            f"{name} is not https://: {urls[name]}"
        )


def test_distribution_metadata_has_ai_classifier():
    meta = importlib.metadata.metadata("actingweb")
    classifiers = meta.get_all("Classifier") or []
    assert "Topic :: Scientific/Engineering :: Artificial Intelligence" in classifiers
