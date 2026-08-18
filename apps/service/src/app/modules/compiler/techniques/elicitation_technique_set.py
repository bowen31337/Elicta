"""Loads the versioned elicitation technique set from its Agent Skill directory, and verifies candidate provenance against it (PRD FR-4.4).

PRD FR-4.4 requires the Analyst pass to "draw question strategies from an
explicit elicitation technique set, not from persona prompting alone."
Architecture §3.11 names the mechanism: "Templates, elicitation technique
set" map onto Claude **Agent Skills** -- "versioned, filesystem-backed,
editable without a redeploy" -- so a delivery lead can revise elicitation
strategy by editing skill files rather than requesting an engineering
change. `load_elicitation_technique_set` is that filesystem read: it parses
`SKILL.md`'s frontmatter for the set's own `version` and one
`ElicitationTechnique` per file under `techniques/`, each providing its own
`technique_id`, `name`, and strategy body. No YAML dependency exists
anywhere else in this codebase, so frontmatter parsing here is a minimal
flat `key: value` reader -- exactly as much structure as a Skill's
frontmatter (`.models.ElicitationTechnique`, `.models.ElicitationTechniqueSet`)
actually needs, not a general-purpose YAML parser.

`DEFAULT_SKILL_DIR` points at the technique set bundled with this package
(`elicitation_technique_skill/`) so a fresh install has a working default;
`load_elicitation_technique_set` accepts any `skill_dir`, so an operator can
point it at a different filesystem path -- e.g. one mounted separately from
the service's own deploy -- without redeploying the service itself.

Running the Analyst chain against the loaded set (out of this feature's
footprint -- that chain lives in `compiler/agent/`) is responsible for
tagging its own draft candidates with the `technique_id` it drew each one
from and handing them to `verify_candidate_techniques` as
`.models.TechniqueDrawnCandidate`s, the same handoff shape
`.models`'s module docstring describes. `verify_candidate_techniques` is
the acceptance gate PRD FR-4.4 implies: it confirms every claimed
`technique_id` is still present in the *current* versioned set before a
candidate is trusted to carry that provenance onward, dropping any that
name a technique a delivery lead has since renamed or deleted from the
skill (mirroring `stage_suppression.py`'s keep-and-count shape) rather than
persisting a candidate with a dangling technique reference.
"""

from __future__ import annotations

from pathlib import Path

from .models import (
    ElicitationTechnique,
    ElicitationTechniqueSet,
    TechniqueDrawnCandidate,
    TechniqueVerificationResult,
    VerifiedTechniqueCandidate,
)

DEFAULT_SKILL_DIR = Path(__file__).parent / "elicitation_technique_skill"


def _parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """Split a Skill file into its leading `---`-delimited frontmatter fields and its body.

    Only flat scalar `key: value` frontmatter is supported -- exactly what
    `SKILL.md` and each technique file actually carries -- so this stays a
    plain text reader rather than pulling in a YAML dependency this
    codebase does not otherwise need.
    """

    stripped = text.lstrip()
    if not stripped.startswith("---"):
        raise ValueError("skill file is missing its --- frontmatter delimiter")

    _, _, remainder = stripped.partition("---")
    frontmatter_block, delimiter, body = remainder.partition("---")
    if not delimiter:
        raise ValueError(
            "skill file's frontmatter is missing its closing --- delimiter"
        )

    fields: dict[str, str] = {}
    for line in frontmatter_block.splitlines():
        line = line.strip()
        if not line:
            continue
        key, separator, value = line.partition(":")
        if not separator:
            raise ValueError(f"malformed frontmatter line: {line!r}")
        fields[key.strip()] = value.strip()
    return fields, body.strip()


def _parse_technique_file(path: Path) -> ElicitationTechnique:
    fields, body = _parse_frontmatter(path.read_text())
    for required in ("technique_id", "name"):
        if required not in fields:
            raise ValueError(
                f"{path}: frontmatter is missing required field {required!r}"
            )

    return ElicitationTechnique(
        technique_id=fields["technique_id"], name=fields["name"], strategy=body
    )


def load_elicitation_technique_set(
    skill_dir: Path = DEFAULT_SKILL_DIR,
) -> ElicitationTechniqueSet:
    """Load the versioned elicitation technique set from `skill_dir`'s Agent Skill files (PRD FR-4.4).

    `skill_dir` must contain a `SKILL.md` whose frontmatter names the set's
    `version`, plus a `techniques/` subdirectory holding one `*.md` file per
    technique. Techniques are returned sorted by `technique_id` for a
    deterministic result regardless of filesystem directory-listing order.
    """

    skill_md = skill_dir / "SKILL.md"
    skill_fields, _ = _parse_frontmatter(skill_md.read_text())
    if "version" not in skill_fields:
        raise ValueError(f"{skill_md}: frontmatter is missing required field 'version'")

    technique_paths = sorted((skill_dir / "techniques").glob("*.md"))
    techniques = sorted(
        (_parse_technique_file(path) for path in technique_paths),
        key=lambda technique: technique.technique_id,
    )

    return ElicitationTechniqueSet(
        version=skill_fields["version"], techniques=techniques
    )


def verify_candidate_techniques(
    drawn: list[TechniqueDrawnCandidate], technique_set: ElicitationTechniqueSet
) -> TechniqueVerificationResult:
    """Confirm each drawn candidate's `technique_id` is present in `technique_set`, dropping any that are not (PRD FR-4.4).

    Surviving candidates keep their original relative order and carry
    `technique_set.version` forward as `technique_version`, so a persisted
    candidate names both which technique produced it and which revision of
    the technique set was live when that provenance was confirmed.
    """

    known_technique_ids = {
        technique.technique_id for technique in technique_set.techniques
    }

    candidates: list[VerifiedTechniqueCandidate] = []
    unknown_technique_count = 0

    for entry in drawn:
        if entry.technique_id not in known_technique_ids:
            unknown_technique_count += 1
            continue
        candidates.append(
            VerifiedTechniqueCandidate(
                candidate=entry.candidate,
                technique_id=entry.technique_id,
                technique_version=technique_set.version,
            )
        )

    return TechniqueVerificationResult(
        candidates=candidates, unknown_technique_count=unknown_technique_count
    )
