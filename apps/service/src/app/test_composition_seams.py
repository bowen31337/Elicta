"""The invariant that would have caught the whole live-run failure class.

Every gap the live journey run found had one shape: `composition.py` bound a
write path and its matching read path to *different* `Backend` fields. A
meeting was created and could not be found; consent was recorded and read
back as never given; a replay run was started and answered "no replay run".
Seventeen of the sixty-four declared fields were read by the composition root
and written by nothing in it.

No unit test could see that. Each half passed in isolation, because a unit
test supplies the collection it reads. What catches it is a structural check
over the composition root itself: **a field the composition root reads, it
must also write** — or it must appear below with a reason.

The exception list is the point of the mechanism, not a hole in it. A field
lands there when the thing that would write it does not exist yet, and the
reason says which thing. Adding an entry is a deliberate act with a
justification attached; leaving one out means the test fails.

**What this cannot see.** It asks whether a field has *any* writer, not
whether the writer that matches a given read exists. A field written in one
place and read in three still passes if one of those reads was never wired
to anything. That is why the API-only seam tests in
`tests/e2e/api_integration/test_*_seam.py` exist alongside it: this catches
the field nothing fills, and those catch the journey that cannot complete.
Neither replaces the other.
"""

from __future__ import annotations

import pathlib
import re

COMPOSITION = pathlib.Path(__file__).with_name("composition.py")

# A read that has no writer, and why. Each entry names what would have to
# exist for the field to be written, so the list shrinks as those arrive
# rather than becoming a place to hide new breakage.
ACCEPTED_READ_ONLY: dict[str, str] = {
    "consent_models": (
        "No API surface sets an engagement's consent model; it takes "
        "DEFAULT_CONSENT_MODEL, which at this stage is ENGAGEMENT_LEVEL (D3). "
        "That is the fail-open of the two: an unwritten field skips the "
        "confirmation rather than asking for it, so no engagement asks and no "
        "consent record is ever written. This entry is the reason that is a "
        "deliberate stage decision and not an oversight; see the note on "
        "DEFAULT_CONSENT_MODEL in composition.py for what it costs."
    ),
    "nudge_signals": (
        "A recorded disposition says how a nudge was resolved, not what it "
        "said. The stub, question and trigger reason come from the live nudge "
        "path, which has no vendor implementation; deriving a record here "
        "would mean inventing the question the client was asked (FR-7.4)."
    ),
    "session_stream_events": (
        "The live session stream's source is the capture pipeline. "
        "`core/crates/asr-live` has three implementations of its vendor seam "
        "and all three are fakes, so nothing produces an event to replay."
    ),
    "reference_document_bodies": (
        "The body of a linked SharePoint or Teams document comes from a "
        "connector that does not exist. The attachment itself is real and is "
        "recorded; its text is empty until something can fetch it."
    ),
    "meeting_base_candidates": (
        "A per-meeting override, and nothing overrides yet. The bank a meeting "
        "actually serves is derived from its engagement's compiled candidates "
        "on read, so this being empty is the ordinary case rather than the "
        "broken one — which is the opposite of what it meant when the read had "
        "no fallback and every meeting's bank came back empty."
    ),
    "meeting_inherited_open_questions": (
        "The same override as `meeting_base_candidates`, from the other input: "
        "unset, a meeting inherits whatever its engagement still has open."
    ),
    "candidate_authority_requirements": (
        "FR-4.7 scores a candidate against the roster using requirements the "
        "compiler's agent pass produces. That pass returns candidates without "
        "them today, so the join runs against an empty set rather than a "
        "wrong one."
    ),
    "template_sections": (
        "The BMAD taxonomy the debrief classifies against, and the sections "
        "the compiler files a bank under. An engagement names its target "
        "template as free text (`target_requirements_template`) and nothing "
        "turns that name into a section list. The debrief still classifies "
        "against none rather than against a taxonomy nobody chose; the "
        "compiler no longer does, because being given no sections is what had "
        "it inventing a catch-all and filing two thirds of a bank in it — it "
        "falls back to `DEFAULT_TEMPLATE_SECTIONS`, which is a stated default "
        "rather than the engagement's own template. Resolving that name is "
        "what would let this field be written."
    ),
    "session_audio": (
        "Written, but not here: `session_audio` is handed to "
        "`audio_hold.build_audio_chunk_router` as the raw dict, and "
        "`append_chunk` — in `audio_hold.py`, not this file — is what fills "
        "it, so it can enforce chunk ordering in one place rather than "
        "composition.py duplicating that check before indexing in. The same "
        "reason covers `discard`: `delete_audio` calls it instead of "
        "`backend.session_audio.pop(...)` so the two collections a session's "
        "audio touches are forgotten by one call, not two kept in sync by "
        "hand."
    ),
}

# Calls that PUT something into a field, as opposed to reads of it. `pin`
# belongs here because a registry mutates through its own method rather than
# by assignment — a write is a write however it is spelled.
#
# `pop` and `clear` are deliberately absent. They remove, and a field that is
# only ever emptied was never filled: `retained_audio` was read in three
# places, written in none, and `.pop(...)` alone was enough to look like a
# writer — so NFR-2.4's audio destruction could never fire and this test said
# nothing. Removal is not provenance.
#
# `observe_success` is absent for the same reason. It clears a recorded
# failure, and "reachable" is already the default — so a lane observer that
# only ever saw successes has been told nothing it did not start out
# believing. `observe_failure` is the call that puts state there.
WRITE_METHODS = (
    "append",
    "add",
    "update",
    "setdefault",
    "extend",
    "pin",
    "observe_failure",
)


def _declared_fields(source: str) -> list[str]:
    return list(dict.fromkeys(re.findall(r"^\s{4}(\w+):\s*[^=\n]+= field\(", source, re.M)))


def _read_only_fields(source: str) -> dict[str, list[int]]:
    """Fields the composition root reads and never writes, by line number."""

    lines = source.split("\n")
    read_only: dict[str, list[int]] = {}
    for name in _declared_fields(source):
        writes = {
            number
            for number, line in enumerate(lines, 1)
            if re.search(rf"backend\.{name}\s*(=[^=]|\[[^\]]*\]\s*=)", line)
            or re.search(rf"backend\.{name}\.({'|'.join(WRITE_METHODS)})\(", line)
        }
        reads = [
            number
            for number, line in enumerate(lines, 1)
            if re.search(rf"backend\.{name}\b", line) and number not in writes
        ]
        if reads and not writes:
            read_only[name] = reads
    return read_only


def test_no_field_is_read_by_the_composition_root_without_being_written() -> None:
    source = COMPOSITION.read_text()

    unexplained = {
        name: lines
        for name, lines in _read_only_fields(source).items()
        if name not in ACCEPTED_READ_ONLY
    }

    assert not unexplained, (
        "these Backend fields are read by composition.py and written by nothing "
        "in it, which is the shape every live-run failure had — a write "
        "endpoint that returns an id and a read endpoint that 404s. Bind the "
        "write to the field the read uses, or add the field to "
        f"ACCEPTED_READ_ONLY with the reason it cannot be written yet: {unexplained}"
    )


def test_the_accepted_list_does_not_outlive_the_gaps_it_describes() -> None:
    """An entry that is no longer read-only has to go, or the list stops meaning anything."""

    source = COMPOSITION.read_text()
    read_only = _read_only_fields(source)

    stale = sorted(set(ACCEPTED_READ_ONLY) - set(read_only))

    assert not stale, (
        "these fields are now written, so their exemption is stale and should "
        f"be deleted from ACCEPTED_READ_ONLY: {stale}"
    )


def test_the_invariant_fails_when_a_new_read_only_field_is_introduced() -> None:
    """The check has to be able to fail, or it is decoration.

    Runs the same detector over a composition root with one field read and
    never written — the exact defect — and asserts it is reported.
    """

    contrived = """
@dataclass
class Backend:
    widget_statuses: dict[str, str] = field(default_factory=dict)
    widget_requests: dict[str, str] = field(default_factory=dict)


def build_app(backend):
    async def start_widget(request):
        backend.widget_requests["widget-1"] = request

    async def get_widget(widget_id):
        return backend.widget_statuses[widget_id]
"""

    read_only = _read_only_fields(contrived)

    assert "widget_statuses" in read_only
    assert "widget_requests" not in read_only


def test_every_accepted_exception_states_a_reason() -> None:
    for name, reason in ACCEPTED_READ_ONLY.items():
        assert len(reason.split()) >= 8, f"{name}'s exemption does not explain itself"


# --------------------------------------------------------------------------
# The other half: a test must not set up its own read side.
# --------------------------------------------------------------------------

SEAM_TESTS = sorted(
    (COMPOSITION.parents[4] / "tests" / "e2e" / "api_integration").glob("test_*_seam.py")
)

# One test per write/read pair in the live run's findings table.
COVERED_SEAMS = {
    "test_meeting_visibility.py": "POST /api/meetings -> GET /api/meetings/{id}",
    "test_consent_gate_seam.py": "POST .../consent-confirmation -> GET .../consent-record; "
    "the confirmation -> gate half needs a seeded consent model and lives in "
    "test_consent_and_egress.py",
    "test_document_intake_seam.py": "POST .../documents/link -> GET .../documents",
    "test_replay_seam.py": "POST /api/replay/runs -> GET /api/replay/runs/{id}, ratings -> metrics",
    "test_record_path_seam.py": "POST .../record/transcribe -> GET .../record/divergences",
    "test_debrief_artifacts_seam.py": "a debrief run -> GET .../artifacts",
    "test_debrief_conversation_seam.py": "POST .../debrief/message -> the model, or an honest refusal",
    "test_compile_input_seam.py": "POST .../bank/compile -> what the compiler was actually handed",
    "test_egress_audit_seam.py": "a call that leaves the machine -> GET /api/audit/egress",
}


def test_every_write_read_pair_the_live_run_found_has_a_test() -> None:
    present = {path.name for path in SEAM_TESTS} | {"test_meeting_visibility.py"}

    missing = sorted(set(COVERED_SEAMS) - present)

    assert not missing, f"a write/read pair from the live run has no test: {missing}"


def test_no_seam_test_sets_up_its_own_read_side() -> None:
    """The defect class hides behind `backend.some_field[...] = ...` in a test.

    A test that places state in the field the read uses proves only that the
    read works when someone else fills it, which is exactly what forty-five
    passing integration tests proved while no journey could complete. These
    tests write through the API and read through the API, so an unbound seam
    has nowhere to hide.
    """

    offenders: dict[str, list[str]] = {}
    for path in [*SEAM_TESTS, COMPOSITION.parents[4] / "tests" / "e2e" / "api_integration" / "test_meeting_visibility.py"]:
        assignments = [
            line.strip()
            for line in path.read_text().split("\n")
            if re.search(r"\bbackend\.\w+\s*(\[[^\]]*\]\s*)?=[^=]", line)
        ]
        if assignments:
            offenders[path.name] = assignments

    assert not offenders, (
        "these seam tests assign to a backend field to set up a read; build the "
        f"fixture with API calls instead: {offenders}"
    )
