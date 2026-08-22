"""Debrief engines that answer from the fixture instead of from a model.

The live harness proves the pipeline works against Claude. This proves it
works *every time*, which a model cannot: a run against a real provider can be
rate limited, or overloaded, or simply drift by an entry, and none of those
says anything about whether the pipeline is correct.

So these are deterministic all the way down. Each stage does the real work its
contract describes over the recorded meeting — cleaning strips the fillers it
can see, classification sorts by the words the section is about, the analyst
chain draws its claims from named utterances and cites them by id — and does
it identically on every run. Nothing downstream can tell these from a vendor:
`run_debrief_pipeline` calls them through the same seam and applies the same
citation resolution, which is what makes an assertion about the output an
assertion about the product.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "apps" / "service" / "src"))

from app.modules.debrief.pipeline.models import (  # noqa: E402
    UNCLASSIFIED_SECTION_KEY,
    BmadAnalystChainOutput,
    BmadDecisionDraft,
    BmadFollowUpEmailDraft,
    BmadOpenQuestionDraft,
    BmadProjectBriefDraft,
    TranslationOutcome,
)
from app.orchestration.engines import DebriefEngines  # noqa: E402

ENGINE_NAME = "fixture-engines"

#: Filler this transcript contains, removed by cleaning.
_FILLER = ("um, ", "er, ", "uh, ")

#: Which section a sentence belongs to, by the words that decide it. First
#: match wins, so the order is the precedence.
_SECTIONS: list[tuple[str, tuple[str, ...]]] = [
    ("integrations", ("navistock", "sftp", "telemetry", "feed", "nightly file")),
    ("performance", ("fast", "under a minute", "minutes to produce", "report")),
    ("constraints-and-dependencies", ("handheld", "freezer", "dock rule", "february")),
    ("operations", ("marshalling", "trunk run", "despatch", "inbound", "depot flow")),
    ("volumes", ("pallets", "throughput")),
    ("roles-and-decision-authority", ("board", "quality team", "site manager")),
    ("scope-and-outcomes", ("phase one", "derby", "wolverhampton", "scope")),
]


def _section_for(text: str) -> str:
    lowered = text.lower()
    for key, words in _SECTIONS:
        if any(word in lowered for word in words):
            return key
    return UNCLASSIFIED_SECTION_KEY


def _find(utterances: list[Any], needle: str) -> Any | None:
    """The first utterance containing `needle`, or None if the run lacks it."""

    return next(
        (u for u in utterances if needle.lower() in u.cleaned_text.lower()), None
    )


def _ids(utterances: list[Any], *needles: str) -> list[str]:
    """The utterance ids behind a claim.

    Ids rather than text: `run_bmad_analyst_chain` resolves each one against
    the session's own utterances rather than trusting what a chain says it
    quoted, so a claim citing an id that is not there fails the run — which is
    exactly the fabrication check, and it applies to these engines too.
    """

    found = [_find(utterances, needle) for needle in needles]
    return [u.utterance_id for u in found if u is not None]


async def _clean(_session_id: str, utterances: list[Any]) -> list[str]:
    cleaned = []
    for utterance in utterances:
        text = utterance.text
        for filler in _FILLER:
            text = text.replace(filler, "")
        cleaned.append(text)
    return cleaned


async def _translate(
    _session_id: str, utterances: list[Any], document_language: str
) -> list[TranslationOutcome]:
    # The meeting is in the document language throughout, so every original is
    # retained untranslated — which FR-2.19 asks for anyway.
    return [
        TranslationOutcome(original_language=document_language, translated_text=None)
        for _ in utterances
    ]


async def _classify(
    _session_id: str, utterances: list[Any], sections: list[Any]
) -> list[str]:
    known = {section.key for section in sections}
    return [
        key if (key := _section_for(u.cleaned_text)) in known else UNCLASSIFIED_SECTION_KEY
        for u in utterances
    ]


async def _run_chain(_session_id: str, utterances: list[Any]) -> BmadAnalystChainOutput:
    """The four documents, drawn from named moments in the recorded meeting."""

    return BmadAnalystChainOutput(
        open_questions=[
            BmadOpenQuestionDraft(
                text="Is the Derby site in phase one? The board has not signed it off.",
                impact_rank=1,
                provenance="stated",
                citation_utterance_ids=_ids(utterances, "Whether it is in phase one"),
            ),
            BmadOpenQuestionDraft(
                text=(
                    "The fifteen minute dock rule is followed in practice but written "
                    "down nowhere. Who owns the documented service level?"
                ),
                impact_rank=2,
                provenance="inferred",
                citation_utterance_ids=_ids(utterances, "It is how we work"),
            ),
            BmadOpenQuestionDraft(
                text="Can the NAVISTOCK file format change, or is finance's copy fixed?",
                impact_rank=3,
                provenance="stated",
                citation_utterance_ids=_ids(utterances, "fixed as far as finance"),
            ),
        ],
        decisions=[
            BmadDecisionDraft(
                text=(
                    "Wolverhampton is certain for phase one; Derby is open pending "
                    "board sign-off."
                ),
                decided_by="SPEAKER_1",
                provenance="stated",
                citation_utterance_ids=_ids(utterances, "treat Wolverhampton as certain"),
            ),
            BmadDecisionDraft(
                text="Handhelds in the freezer aisles are out of scope.",
                decided_by="SPEAKER_2",
                provenance="stated",
                citation_utterance_ids=_ids(utterances, "The team will not accept them"),
            ),
            BmadDecisionDraft(
                text=(
                    "The daily throughput report must render in under a minute; the "
                    "other reports may take longer."
                ),
                decided_by="SPEAKER_2",
                provenance="stated",
                citation_utterance_ids=_ids(utterances, "Under a minute"),
            ),
        ],
        project_brief=BmadProjectBriefDraft(
            body=(
                "Replace FROSTLINE with a depot platform covering inbound booking, "
                "put-away, pick and despatch, and driver debrief. Wolverhampton is "
                "phase one; Derby is unresolved. The daily throughput report is a "
                "first-class product with a sub-minute target, not an export. "
                "Handhelds are excluded from the freezer aisles."
            ),
            provenance="inferred",
            citation_utterance_ids=_ids(
                utterances, "depot flow", "Under a minute", "freezer aisles are out"
            ),
        ),
        follow_up_email=BmadFollowUpEmailDraft(
            subject="Northgate discovery — what we agreed, and what is still open",
            body=(
                "Thank you both for this morning. We agreed Wolverhampton is phase "
                "one and that handhelds stay out of the freezer aisles, and we have "
                "a sub-minute target for the daily throughput report.\n\n"
                "Still open: whether Derby is in phase one, who owns the written "
                "dock service level, and whether the NAVISTOCK format can change."
            ),
            provenance="inferred",
            citation_utterance_ids=_ids(utterances, "Whether it is in phase one"),
        ),
    )


async def _converse(turns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{"type": "text", "text": "Answered from the recorded meeting."}]


def fixture_debrief_engines(diarize: Any) -> DebriefEngines:
    """The pipeline's five stages plus the conversation, answered deterministically."""

    return DebriefEngines(
        name=ENGINE_NAME,
        diarize=diarize,
        clean=_clean,
        translate=_translate,
        classify=_classify,
        run_chain=_run_chain,
        converse=_converse,
    )
