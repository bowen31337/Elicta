"""Tests for loading the versioned elicitation technique set and verifying candidate provenance against it (PRD FR-4.4)."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.modules.compiler.bank.models import BankCandidate
from app.modules.compiler.techniques.elicitation_technique_set import (
    DEFAULT_SKILL_DIR,
    _parse_frontmatter,
    load_elicitation_technique_set,
    verify_candidate_techniques,
)
from app.modules.compiler.techniques.models import (
    ElicitationTechniqueSet,
    TechniqueDrawnCandidate,
)


def write_skill(
    tmp_path: Path, *, version: str = "1.0.0", techniques: dict[str, str] | None = None
) -> Path:
    skill_dir = tmp_path / "skill"
    (skill_dir / "techniques").mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: elicitation-techniques\nversion: {version}\n---\nbody\n"
    )
    for technique_id, name in (techniques or {"five-whys": "Five Whys"}).items():
        (skill_dir / "techniques" / f"{technique_id}.md").write_text(
            f"---\ntechnique_id: {technique_id}\nname: {name}\n---\nAsk why repeatedly.\n"
        )
    return skill_dir


def make_candidate(candidate_id: str) -> BankCandidate:
    return BankCandidate(
        id=candidate_id, template_section="scope", phrasing=candidate_id, priority=1
    )


def test_bundled_default_skill_loads_and_has_at_least_one_technique():
    technique_set = load_elicitation_technique_set(DEFAULT_SKILL_DIR)

    assert technique_set.version
    assert len(technique_set.techniques) >= 1
    assert all(
        t.technique_id and t.name and t.strategy for t in technique_set.techniques
    )


def test_load_reads_version_and_techniques_from_the_skill_directory(tmp_path: Path):
    skill_dir = write_skill(
        tmp_path,
        version="2.3.1",
        techniques={"five-whys": "Five Whys", "swot": "SWOT analysis"},
    )

    technique_set = load_elicitation_technique_set(skill_dir)

    assert technique_set.version == "2.3.1"
    assert [t.technique_id for t in technique_set.techniques] == ["five-whys", "swot"]
    assert technique_set.techniques[0].name == "Five Whys"
    assert technique_set.techniques[0].strategy == "Ask why repeatedly."


def test_techniques_are_sorted_by_technique_id_regardless_of_file_order(tmp_path: Path):
    skill_dir = write_skill(tmp_path, techniques={"zeta": "Zeta", "alpha": "Alpha"})

    technique_set = load_elicitation_technique_set(skill_dir)

    assert [t.technique_id for t in technique_set.techniques] == ["alpha", "zeta"]


def test_missing_skill_md_version_field_raises(tmp_path: Path):
    skill_dir = tmp_path / "skill"
    (skill_dir / "techniques").mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: elicitation-techniques\n---\nbody\n"
    )

    with pytest.raises(ValueError, match="version"):
        load_elicitation_technique_set(skill_dir)


def test_technique_file_missing_required_field_raises(tmp_path: Path):
    skill_dir = tmp_path / "skill"
    (skill_dir / "techniques").mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("---\nversion: 1.0.0\n---\nbody\n")
    (skill_dir / "techniques" / "broken.md").write_text(
        "---\nname: Broken\n---\nstrategy\n"
    )

    with pytest.raises(ValueError, match="technique_id"):
        load_elicitation_technique_set(skill_dir)


def test_skill_file_without_frontmatter_delimiter_raises(tmp_path: Path):
    skill_dir = tmp_path / "skill"
    (skill_dir / "techniques").mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("no frontmatter here\n")

    with pytest.raises(ValueError, match="frontmatter"):
        load_elicitation_technique_set(skill_dir)


def test_candidates_drawn_from_known_techniques_are_verified_and_tagged_with_technique_id():
    technique_set = ElicitationTechniqueSet(
        version="1.0.0",
        techniques=load_elicitation_technique_set(DEFAULT_SKILL_DIR).techniques,
    )
    known_id = technique_set.techniques[0].technique_id
    drawn = [
        TechniqueDrawnCandidate(candidate=make_candidate("c1"), technique_id=known_id)
    ]

    result = verify_candidate_techniques(drawn, technique_set)

    assert len(result.candidates) == 1
    assert result.candidates[0].candidate.id == "c1"
    assert result.candidates[0].technique_id == known_id
    assert result.candidates[0].technique_version == "1.0.0"
    assert result.unknown_technique_count == 0


def test_candidates_drawn_from_an_unknown_technique_are_dropped_and_counted():
    technique_set = ElicitationTechniqueSet(
        version="1.0.0",
        techniques=load_elicitation_technique_set(DEFAULT_SKILL_DIR).techniques,
    )
    known_id = technique_set.techniques[0].technique_id
    drawn = [
        TechniqueDrawnCandidate(candidate=make_candidate("c1"), technique_id=known_id),
        TechniqueDrawnCandidate(
            candidate=make_candidate("c2"), technique_id="renamed-or-deleted"
        ),
    ]

    result = verify_candidate_techniques(drawn, technique_set)

    assert [c.candidate.id for c in result.candidates] == ["c1"]
    assert result.unknown_technique_count == 1


def test_no_drawn_candidates_verifies_to_an_empty_result_with_zero_unknown_count():
    technique_set = load_elicitation_technique_set(DEFAULT_SKILL_DIR)

    result = verify_candidate_techniques([], technique_set)

    assert result.candidates == []
    assert result.unknown_technique_count == 0


def test_frontmatter_with_no_closing_delimiter_is_refused():
    # Everything after the opening --- would otherwise be read as fields, so a
    # technique file truncated mid-write would load as a technique with a
    # plausible-looking id and no body.
    with pytest.raises(ValueError, match="missing its closing --- delimiter"):
        _parse_frontmatter("---\ntechnique_id: t1\nname: Interview\n")


def test_a_frontmatter_line_that_is_not_a_key_value_pair_is_refused():
    with pytest.raises(ValueError, match="malformed frontmatter line"):
        _parse_frontmatter("---\ntechnique_id: t1\nname Interview\n---\nbody\n")
