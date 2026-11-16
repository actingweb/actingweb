"""Every option tag the library can advertise is defined in the
specification's option tag list, so the two cannot drift (spec-1-5 Phase 5)."""

import re
from pathlib import Path

from actingweb.config import Config

SPEC = (
    Path(__file__).resolve().parent.parent / "docs" / "protocol" / "actingweb-spec.rst"
)


def _defined_tags() -> set[str]:
    text = SPEC.read_text(encoding="utf-8")
    start = text.index("Option tags\n")
    end = text.index("Response Conventions\n", start)
    section = text[start:end]
    return (
        set(re.findall(r"^\s*\*?\*?\*?([a-z][a-z0-9]+)\*?\*?\*?\s*$", section, re.M))
        | set(re.findall(r"\*([a-z][a-z0-9]+)\*", section))
        | set(re.findall(r"``([a-z][a-z0-9]+)``", section))
    )


def _every_tag_the_library_can_advertise() -> set[str]:
    config = Config(oauth={"client_id": "cid", "redirect_uri": "x"}, mcp=True)
    config.peer_permissions_caching = True
    return set(config.aw_supported.split(","))


def test_every_advertised_tag_is_defined_in_the_specification() -> None:
    missing = _every_tag_the_library_can_advertise() - _defined_tags()
    assert not missing, f"advertised but not defined in the specification: {missing}"


def test_the_specification_announces_the_version_the_library_announces() -> None:
    first_line = SPEC.read_text(encoding="utf-8").splitlines()[1]
    assert first_line.endswith(f"version {Config().aw_version}")
