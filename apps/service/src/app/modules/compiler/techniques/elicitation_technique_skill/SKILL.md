---
name: elicitation-techniques
description: The versioned set of elicitation techniques the BMAD Analyst pass draws question strategies from (PRD FR-4.4)
version: 1.0.0
---

# Elicitation technique set

This skill is the explicit technique set PRD FR-4.4 requires the Analyst
pass to draw question strategies from, instead of persona prompting alone.
Each file under `techniques/` names one technique: a `technique_id`, a
`name`, and a body giving the strategy's own instructions for turning
engagement context into candidate questions.

Editing a technique file, or adding or removing one, changes what strategies
the next compile draws from. Bump `version` above whenever the set of
techniques or their strategies changes, so a compiled candidate's recorded
`technique_version` reflects the revision that actually produced it.
