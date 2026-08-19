#!/usr/bin/env python3
"""Regenerates docs/journeys/coverage.md from the PRD.

The point of generating rather than hand-maintaining it: a requirement added to
the PRD and not placed in a journey becomes a visible gap here, instead of
being quietly missed. Run it after editing the PRD:

    uv run --no-project python scripts/coverage.py

Exits non-zero if any requirement has no journey, so it can gate CI.
"""

from __future__ import annotations

import collections
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
PRD = ROOT / "docs/live-elicitation-assistant-prd.md"
OUT = ROOT / "docs/journeys/coverage.md"


def _range(prefix: str, lo: int, hi: int) -> list[str]:
    return [f"{prefix}.{i}" for i in range(lo, hi + 1)]


# Which journey carries which requirement. Every id in the PRD must appear.
ASSIGNMENTS: list[tuple[int, list[str]]] = [
    (11, ["FR-1.2", "FR-1.3", "FR-1.4", "FR-1.5", "FR-1.6", "FR-2.10"]),
    (2, ["FR-1.1", "FR-1.7", "FR-3.8", "FR-3.9", "FR-3.10"] + _range("NFR-2", 1, 4)),
    (
        1,
        ["FR-3.1", "FR-3.2", "FR-3.3", "FR-3.4", "FR-3.5", "FR-3.6", "FR-3.12",
         "FR-3.13", "FR-3.14", "FR-2.14"] + _range("FR-4", 1, 9),
    ),
    (3, _range("FR-5", 1, 11) + _range("FR-6", 1, 10) + _range("FR-2", 1, 4)),
    (4, _range("FR-2", 11, 26)),
    (5, ["NFR-4.1", "NFR-4.2", "NFR-4.3"]),
    (6, ["FR-2.5", "FR-2.6", "FR-2.7", "FR-2.8", "FR-7.2", "NFR-5.1", "NFR-5.2"]),
    (7, _range("FR-7", 1, 4) + _range("FR-8", 1, 8) + ["FR-8.10"]),
    (8, ["FR-3.7", "FR-3.11", "FR-8.9", "FR-4.8"]),
    (9, _range("NFR-5", 3, 8)),
    (10, ["FR-2.9", "NFR-2.5", "NFR-2.6", "NFR-2.7"]),
    (12, _range("NFR-3", 1, 8)),
]

JOURNEYS = {
    1: ("Prepare an engagement", "01-prepare-an-engagement"),
    2: ("Start a meeting with consent", "02-start-a-meeting-with-consent"),
    3: ("Catch a vague answer live", "03-catch-a-vague-answer-live"),
    4: ("Run a code-switched meeting", "04-run-a-code-switched-meeting"),
    5: ("Keep working when the model is unreachable", "05-degraded-mode"),
    6: ("Reconcile the recording", "06-reconcile-the-recording"),
    7: ("Produce the debrief artifacts", "07-produce-the-debrief"),
    8: ("Carry state to the next meeting", "08-carry-state-forward"),
    9: ("Tune ranking with the replay harness", "09-replay-and-tune-ranking"),
    10: ("Configure providers and connectors", "10-configure-providers"),
    11: ("Control capture during the meeting", "11-control-capture"),
    12: ("Install and roll out", "12-install-and-roll-out"),
}


def main() -> int:
    prd = PRD.read_text()
    ids = sorted(
        set(re.findall(r"\b(?:FR|NFR)-\d+\.\d+", prd)),
        key=lambda s: (s.split("-")[0], int(s.split("-")[1].split(".")[0]), int(s.split(".")[1])),
    )

    summary: dict[str, str] = {}
    for rid in ids:
        match = re.search(rf"\| {re.escape(rid)} \| ([^|]+)\|", prd)
        if match:
            line = re.sub(r"\*\*|`", "", match.group(1).strip())
            summary[rid] = line[:74] + "…" if len(line) > 75 else line

    placed: dict[str, int] = {}
    for journey, reqs in ASSIGNMENTS:
        for rid in reqs:
            placed.setdefault(rid, journey)

    unplaced = [rid for rid in ids if rid not in placed]

    by_journey: dict[int, list[str]] = collections.defaultdict(list)
    for rid in ids:
        if rid in placed:
            by_journey[placed[rid]].append(rid)

    out = [
        "# Requirement coverage",
        "",
        "Every requirement in the PRD, and the journey that carries it. Generated",
        "from the PRD by `scripts/coverage.py`, so a requirement added there and",
        "not placed in a journey shows up as a gap rather than being quietly",
        "missed.",
        "",
        f"**{len(ids) - len(unplaced)} of {len(ids)} requirements are covered by a journey.**",
        "",
    ]
    if unplaced:
        out += ["## Not covered by any journey", ""]
        out += [f"- `{rid}` — {summary.get(rid, '')}" for rid in unplaced]
        out.append("")

    for journey in sorted(by_journey):
        title, slug = JOURNEYS[journey]
        out += [
            f"## {journey}. [{title}]({slug}.md) — {len(by_journey[journey])} requirements",
            "",
            "| Req | |",
            "|---|---|",
        ]
        out += [f"| `{rid}` | {summary.get(rid, '')} |" for rid in by_journey[journey]]
        out.append("")

    OUT.write_text("\n".join(out))

    if unplaced:
        print(f"{len(unplaced)} requirement(s) have no journey: {' '.join(unplaced)}")
        return 1
    print(f"coverage.md: {len(ids)} requirements across {len(by_journey)} journeys, none unplaced")
    return 0


if __name__ == "__main__":
    sys.exit(main())
