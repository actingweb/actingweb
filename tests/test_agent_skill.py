"""The Agent Skill shipped in ``skills/`` loads in every agent that reads it.

Claude Code is lenient with a skill's front matter; Codex parses it as
strict YAML and drops a skill that does not parse, so a description that
runs onto unindented lines made the skill invisible there.
"""

from pathlib import Path

import pytest
import yaml

SKILLS_ROOT = Path(__file__).resolve().parent.parent / "skills"
SKILL_FILES = sorted(SKILLS_ROOT.glob("*/SKILL.md"))


def _front_matter(text: str) -> str:
    lines = text.splitlines()
    assert lines[0] == "---", "SKILL.md must open with a front-matter fence"
    end = lines.index("---", 1)
    return "\n".join(lines[1:end])


def test_there_is_a_skill() -> None:
    assert SKILL_FILES


@pytest.mark.parametrize("path", SKILL_FILES, ids=lambda p: p.parent.name)
def test_skill_front_matter_is_strict_yaml(path: Path) -> None:
    meta = yaml.safe_load(_front_matter(path.read_text(encoding="utf-8")))
    assert isinstance(meta, dict)
    assert meta.get("name") == path.parent.name
    description = meta.get("description")
    assert isinstance(description, str) and description.strip()
    assert "\n" not in description.strip()
