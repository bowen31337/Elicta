"""One recorded meeting, in the shape the missing vendors would deliver it.

Four seams in this product have no vendor behind them: the live transcriber,
the two record-path transcribers, and the diarizer. Everything downstream of
them is built, tested, and — because the debrief engines run on a credential
that *is* configured — able to run for real. What it has never had is an input.

This module is that input. It is not a mock of the pipeline: it is a recorded
meeting expressed as the three artefacts a speech vendor returns.

  * `vendor_transcript` — what each record-path engine returns for the audio.
    Two engines transcribe the same room and disagree in five places, which is
    the whole reason FR-2.6 runs two of them. The disagreements are the real
    failure mode: numbers, and product names nobody outside the client has
    heard. Four of the five are words the engagement's vocabulary list exists
    to prevent, which is the argument for keeping that list, made concrete.

  * `diarization_turns` — which speaker held the floor when. `tag_span_speaker`
    assigns each transcript span the speaker whose turns overlap it most, so
    this is exactly the shape a diarization vendor returns and nothing
    downstream can tell the difference.

  * `SESSION_SCRIPT` — the live path, and the one place this is openly a
    script rather than a stand-in. Turning an utterance into a surfaced nudge
    needs the trigger gate, the bank retrieval and the ranker, which live in
    the Rust crates and are not reachable from here. The events below are what
    those would have produced for this transcript; they exercise the stream,
    the panel's contract and the disposition route, and they prove nothing
    about the ranker itself.

The meeting is the one the documents in `docs/` describe: Northgate Chilled
Logistics, first discovery session, replacing a warehouse system called
FROSTLINE.
"""

from __future__ import annotations

from typing import Any

BA = "SPEAKER_1"
OPS = "SPEAKER_2"
IT = "SPEAKER_3"

#: (start_seconds, end_seconds, speaker_tag, text), in the order they were said.
UTTERANCES: list[tuple[float, float, str, str]] = [
    (0.0, 11.0, BA, "Thanks for making the time. I want to spend most of today on the depot flow, inbound booking through to driver debrief, and leave the integrations for our next session."),
    (11.5, 18.0, OPS, "That works. I should say up front that Derby is the one I am least sure about."),
    (18.5, 21.0, BA, "Least sure in what sense?"),
    (21.5, 28.0, OPS, "Whether it is in phase one at all. The board has not signed that off."),
    (28.5, 35.0, BA, "Understood. Let us treat Wolverhampton as certain and Derby as open for now."),
    (35.5, 47.0, OPS, "Yes. And the marshalling area at Derby is smaller, so whatever we put in there has to cope with a consignment missing its despatch window."),
    (47.5, 51.0, BA, "What happens today when it misses?"),
    (51.5, 59.0, OPS, "It waits for the next trunk run. Which can be the following morning."),
    (59.5, 69.0, BA, "Let us come back to that. On inbound, the fifteen minute dock rule. Is that written down anywhere?"),
    (69.5, 76.0, OPS, "No. It is how we work. Everybody on the floor knows it."),
    (76.5, 84.0, BA, "So it is a rule in practice but not a documented service level."),
    (84.5, 86.5, OPS, "Correct."),
    (87.0, 95.0, BA, "I will record it as a constraint we need to confirm with your quality team."),
    (95.5, 104.0, IT, "Can I add something about FROSTLINE? The reporting pack is the thing people complain about most."),
    (104.5, 106.5, BA, "Go on."),
    (107.0, 120.0, IT, "The daily throughput report takes between five and eleven minutes to produce. Two of the three site managers have stopped using it altogether."),
    (120.5, 126.0, BA, "And they keep their own spreadsheets instead."),
    (126.5, 128.5, IT, "They do."),
    (129.0, 137.0, BA, "When you say the reports need to be fast, what would fast actually mean?"),
    (137.5, 146.0, OPS, "Under a minute. Ideally you open it and it is simply there."),
    (146.5, 153.0, BA, "Under a minute for the daily throughput report specifically?"),
    (153.5, 161.0, OPS, "Yes. The others can take longer, nobody sits watching them."),
    (161.5, 170.0, BA, "That is useful. I will write that down as a target rather than a wish."),
    (170.5, 181.0, IT, "On the feeds, NAVISTOCK takes a nightly file from us. That has to keep working from day one."),
    (181.5, 185.0, BA, "Is the format fixed?"),
    (185.5, 197.0, IT, "It is fixed as far as finance are concerned. Whether we could change it is a conversation nobody has had."),
    (197.5, 204.0, BA, "Noted as open. And the trailer temperature telemetry?"),
    (204.5, 214.0, IT, "Captured. Consumed by nobody. It has been sitting there for two years."),
    (214.5, 222.0, BA, "Would joining it to the consignment record be in scope for phase one?"),
    (222.5, 231.0, OPS, "I would want it, but I would not hold phase one for it."),
    (231.5, 241.0, BA, "So desirable, not blocking. Last one before we finish, the February date."),
    (241.5, 252.0, OPS, "February has been said in board papers. It is not a commitment I have made."),
    (252.5, 261.0, BA, "Then I will record it as a planning target with no owner yet."),
    (261.5, 263.5, OPS, "That is fair."),
    (264.0, 273.0, BA, "One decision to confirm before we stop: handhelds in the freezer aisles are out."),
    (273.5, 283.0, OPS, "Out. The team will not accept them and I am not going to ask them to."),
    (283.5, 290.0, BA, "Agreed and recorded. Thank you both."),
]

#: What the second engine hears differently, `{original: misheard}`.
#:
#: Every one of these is a number or a name — which is what two engines
#: actually disagree about, and what a divergence review is for. Four are words
#: the engagement's vocabulary list would have handed the transcriber up front.
MISHEARINGS: dict[str, str] = {
    "fifteen minute dock rule": "fifty minute dock rule",
    "FROSTLINE": "frost line",
    "NAVISTOCK": "Navistalk",
    "five and eleven minutes": "five and seven minutes",
    "Derby": "Darby",
}


#: The score below which `alignment.py` flags a span for review.
#:
#: Mirrored rather than imported: `app.modules.asr-record` is a hyphenated
#: package and only reachable through `importlib`, and a run that has to
#: import it to describe its own result would fail for the wrong reason.
DIVERGENCE_THRESHOLD = 0.8


def vendor_transcript(engine: str, *, mishear: bool) -> dict[str, Any]:
    """One engine's transcript of the whole session.

    `mishear=False` is the engine that got it right; `True` applies
    `MISHEARINGS`, so the pair disagree in exactly the places a real pair
    disagrees rather than in random noise.
    """

    segments = []
    for start, end, _speaker, text in UTTERANCES:
        heard = text
        if mishear:
            for original, misheard in MISHEARINGS.items():
                heard = heard.replace(original, misheard)
        segments.append(
            {"start_seconds": start, "end_seconds": end, "text": heard}
        )
    return {
        "engine": engine,
        "segments": segments,
        "text": " ".join(segment["text"] for segment in segments),
    }


def diarization_turns() -> list[dict[str, Any]]:
    """Who held the floor when, merged into continuous turns.

    Consecutive utterances by the same speaker become one turn, which is what
    a diarizer reports: it hears speech, not sentences.
    """

    turns: list[dict[str, Any]] = []
    for start, end, speaker, _text in UTTERANCES:
        if turns and turns[-1]["speaker_tag"] == speaker:
            turns[-1]["end_seconds"] = end
            continue
        turns.append(
            {"start_seconds": start, "end_seconds": end, "speaker_tag": speaker}
        )
    return turns


#: The template sections this meeting is scored against.
TEMPLATE_SECTIONS = [
    "Scope and outcomes",
    "Volumes",
    "Performance",
    "Operations",
    "Integrations",
    "Data and compliance",
    "Roles and decision authority",
    "Constraints and dependencies",
]


def _coverage(filled: list[str], remaining_ms: int) -> tuple[str, dict[str, Any]]:
    return (
        "coverage",
        {
            "slots": [
                {
                    "id": f"section-{index}",
                    "label": section,
                    "filled": section in filled,
                }
                for index, section in enumerate(TEMPLATE_SECTIONS, start=1)
            ],
            "time_remaining_ms": remaining_ms,
        },
    )


def _nudge(identifier: str, stub: str, question: str, reason: str, at: str) -> tuple[str, dict[str, Any]]:
    return (
        "nudge",
        {
            "id": identifier,
            "stub": stub,
            "question": question,
            "trigger_reason": reason,
            "created_at": at,
        },
    )


#: The live path, scripted. See this module's docstring for what that means.
#:
#: Each nudge is placed against the utterance that would have triggered it, and
#: the phrasings are ones the compiler actually drafted for this engagement
#: rather than wording invented here.
SESSION_SCRIPT: list[tuple[str, dict[str, Any]]] = [
    _coverage([], 3_600_000),
    _nudge(
        "nudge-1",
        "Is Derby in phase one?",
        "Is the Derby site included in phase one, or is phase one Wolverhampton and a third location only?",
        "Scope left open: 'least sure about Derby'",
        "2026-08-22T09:00:31Z",
    ),
    _coverage(["Scope and outcomes"], 3_540_000),
    _nudge(
        "nudge-2",
        "Fifteen minutes — written down?",
        "The fifteen-minute dock rule is described as a hard rule but is not documented anywhere. Is there a written service level, and who owns it?",
        "Unwritten constraint stated as fact",
        "2026-08-22T09:01:12Z",
    ),
    _coverage(["Scope and outcomes", "Operations"], 3_420_000),
    _nudge(
        "nudge-3",
        "What does 'fast' mean?",
        "When you say the reports need to be fast, what does fast mean — are we targeting sub-minute report generation, or something else?",
        "Vague adjective: 'fast', no quantity",
        "2026-08-22T09:02:09Z",
    ),
    _coverage(
        ["Scope and outcomes", "Operations", "Performance"], 3_300_000
    ),
    _nudge(
        "nudge-4",
        "Is February a commitment?",
        "The brief mentions a February go-live — is that still the target, and if so, is that firm or aspirational?",
        "Date mentioned twice, never committed",
        "2026-08-22T09:04:02Z",
    ),
    _coverage(
        [
            "Scope and outcomes",
            "Operations",
            "Performance",
            "Integrations",
            "Constraints and dependencies",
        ],
        3_180_000,
    ),
]

#: How the operator answered each one, in order.
#:
#: `taken` is the wire value behind the panel's `Asked it`; `parked` is
#: `Park it`. Those are the only two an operator can record.
DISPOSITIONS = [
    ("nudge-1", "taken"),
    ("nudge-2", "parked"),
    ("nudge-3", "taken"),
    ("nudge-4", "taken"),
]
