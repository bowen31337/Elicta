"""Drive one meeting end to end, and report what each step actually produced.

    uv run --project apps/service python -m tests.e2e.fixture_run.run
    uv run --project apps/service python -m tests.e2e.fixture_run.run --compile
    uv run --project apps/service python -m tests.e2e.fixture_run.run --live

The steps are the happy path, numbered as the guide numbers them. Each one
prints what it asked for and what came back, and says PASS only on evidence:
a step that finds nothing says so rather than staying silent, because a run
that quietly skips the half that matters reads exactly like one that worked.

`--compile` drafts the question bank from the attached documents first. That
is a real call to a real model and takes minutes, so it is off by default;
without it steps 6 and 18 report the bank as not drafted rather than pretending
otherwise. `--live` writes into the deployment's own state database instead of
a scratch one, which is what makes the run show up in the running desktop app.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from . import fixtures
from .harness import build_fixture_app

TIMEOUT = 900.0
SCRATCH = Path(__file__).resolve().parent / ".state"

PASS, FAIL, SKIP = "PASS", "FAIL", "SKIP"


class Report:
    """What each step asked for, and what came back."""

    def __init__(self) -> None:
        self.rows: list[tuple[str, str, str, str]] = []

    def record(self, step: str, title: str, verdict: str, detail: str) -> None:
        self.rows.append((step, title, verdict, detail))
        mark = {PASS: "✓", FAIL: "✗", SKIP: "–"}[verdict]
        print(f"  {mark} {step:>4}  {title}\n         {detail}", flush=True)

    @property
    def failed(self) -> list[tuple[str, str, str, str]]:
        return [row for row in self.rows if row[2] == FAIL]

    def summary(self) -> str:
        counts = {verdict: 0 for verdict in (PASS, FAIL, SKIP)}
        for _, _, verdict, _ in self.rows:
            counts[verdict] += 1
        return (
            f"{counts[PASS]} passed, {counts[FAIL]} failed, {counts[SKIP]} skipped "
            f"of {len(self.rows)} steps"
        )


def _documents() -> list[tuple[str, bytes, str]]:
    """The two documents the guide tells a first-time user to attach."""

    here = Path(__file__).resolve().parents[3] / "docs"
    scoping = here / "fixture-northgate-scoping-brief.txt"
    if not scoping.exists():
        # Written inline rather than shipped as a binary: the point is that the
        # compiler has something real to read, not which file format it is in.
        return [
            (
                "Northgate-Scoping-Brief.txt",
                (
                    b"Northgate Chilled Logistics - Discovery Scoping Brief\n"
                    b"Three chilled distribution centres, 140 vehicles, Midlands.\n"
                    b"The warehouse system FROSTLINE dates from 2011 and is supported by "
                    b"one contractor. Handhelds fail below four degrees, so picking runs "
                    b"on paper in the chilled aisles.\n"
                    b"Chilled stock must not sit on the dock longer than fifteen minutes; "
                    b"the site manager calls this a hard rule but it is written down "
                    b"nowhere.\n"
                    b"FROSTLINE sends a nightly flat file to the finance system NAVISTOCK "
                    b"and receives customer orders over SFTP. Trailer temperature "
                    b"telemetry is captured and consumed by nobody.\n"
                    b"A February go-live has been mentioned twice, never as a commitment. "
                    b"Whether the Derby site is in phase one is unresolved.\n"
                ),
                "hypothesis",
            ),
            (
                "Northgate-Throughput-Study.txt",
                (
                    b"Chilled Throughput Study - Wolverhampton and Derby, nine weeks.\n"
                    b"Wolverhampton averages 268 pallets per shift. The 95th percentile "
                    b"inbound gate queue is 41 minutes against a stated target of 20.\n"
                    b"Derby averages 191 pallets per shift; its marshalling area is "
                    b"smaller, so a consignment missing its despatch window waits for the "
                    b"next trunk run.\n"
                    b"The FROSTLINE reporting pack takes between five and eleven minutes "
                    b"to produce the daily throughput report. Two of the three site "
                    b"managers keep their own spreadsheets instead.\n"
                ),
                "ground truth",
            ),
        ]
    return [(scoping.name, scoping.read_bytes(), "ground truth")]


def _planted_scores() -> list[float]:
    """The agreement score each planted mishearing actually earns.

    Reported rather than asserted from memory: the point of step 14c is what
    the comparison does with a realistic error, and a number carries that where
    "0 surfaced" does not.
    """

    import difflib
    import re

    words = lambda text: re.findall(r"[a-z0-9']+", text.lower())  # noqa: E731
    scores = []
    for _start, _end, _speaker, text in fixtures.UTTERANCES:
        heard = text
        for original, misheard in fixtures.MISHEARINGS.items():
            heard = heard.replace(original, misheard)
        if heard != text:
            scores.append(difflib.SequenceMatcher(a=words(text), b=words(heard)).ratio())
    return scores


def _show_write_up(client: TestClient, meeting_id: str) -> None:
    """Print the documents the run produced, with what each claim rests on.

    Read in this process because they are not durable: only the engagement,
    its meetings, the open questions, the requirements state and the bank
    survive a restart, and a debrief's working notes are rebuilt from the
    recording rather than kept.
    """

    def claims(suffix: str, label: str) -> None:
        response = client.get(f"/api/sessions/{meeting_id}/{suffix}")
        if not response.is_success:
            print(f"\n  {label}: {response.status_code}")
            return
        rows = response.json()
        print(f"\n  {label} ({len(rows)})")
        for row in rows:
            citation = (row.get("citations") or [{}])[0]
            print(f"    · [{row.get('provenance')}] {row.get('text')}")
            quoted = citation.get("quoted_text", "")
            if quoted:
                print(
                    f"        ↳ “{quoted[:78]}”"
                    f" — {citation.get('speaker_tag')} at {citation.get('start_seconds')}s"
                )

    print("\n  ── what the write-up produced " + "─" * 44)
    claims("open-questions", "Open questions")
    claims("decision-log", "Decisions")

    brief = client.get(f"/api/sessions/{meeting_id}/project-brief")
    if brief.is_success:
        print(f"\n  Project brief\n    {brief.json().get('body', '')[:600]}")
    email = client.get(f"/api/sessions/{meeting_id}/follow-up-email")
    if email.is_success:
        body = email.json()
        print(f"\n  Follow-up email — {body.get('subject', '')}\n    {str(body.get('body', ''))[:600]}")
    print("\n  " + "─" * 74)


def run(*, compile_bank: bool, live: bool, show: bool, offline: bool = False) -> int:
    app, backend, info = build_fixture_app(
        state_dir=None if live else SCRATCH, offline=offline
    )
    report = Report()

    print("\nElicta — fixture-driven end-to-end run")
    print(f"  model    {info['model']}")
    print(f"  state    {info['database']}")
    print("  stood in for:")
    for item in info["substituted"]:
        print(f"    · {item}")
    print()

    with TestClient(app) as client:
        client.timeout = TIMEOUT

        # ---- 2. the engagement ----------------------------------------
        created = client.post(
            "/api/engagements",
            json={
                "client_organisation": "Northgate Chilled Logistics",
                "sector": "Cold-chain distribution",
                "commercial_context": "Fixed-price discovery, three meetings",
            },
        )
        engagement_id = created.json()["engagement_id"]
        report.record(
            "2", "Create the engagement",
            PASS if created.status_code == 201 else FAIL,
            f"{engagement_id} — Northgate Chilled Logistics",
        )

        # ---- 3. the meeting -------------------------------------------
        meeting = client.post(
            "/api/meetings",
            json={"engagement_id": engagement_id, "capture_mode": "record"},
        )
        meeting_id = meeting.json()["meeting_id"]
        report.record(
            "3", "Add the meeting",
            PASS if meeting.status_code == 201 else FAIL,
            f"{meeting_id} — capture {meeting.json()['capture_mode']}, "
            f"state {meeting.json()['state']}",
        )

        # ---- 4. documents ---------------------------------------------
        attached = []
        for name, content, status in _documents():
            response = client.post(
                f"/api/engagements/{engagement_id}/documents",
                files={"file": (name, content, "text/plain")},
                data={"status": status},
            )
            if response.status_code == 201:
                attached.append(response.json()["document_id"])
        report.record(
            "4", "Attach the documents",
            PASS if len(attached) == len(_documents()) else FAIL,
            f"{len(attached)} attached and read: {', '.join(attached)}",
        )

        # ---- 5. vocabulary --------------------------------------------
        terms = ["FROSTLINE", "NAVISTOCK", "Wolverhampton", "Derby", "marshalling"]
        added = 0
        for term in terms:
            response = client.post(
                f"/api/engagements/{engagement_id}/vocabulary",
                json={"term": term, "term_type": "internal_system"},
            )
            added += response.status_code == 201
        report.record(
            "5", "Add the client's vocabulary",
            PASS if added == len(terms) else FAIL,
            f"{added} terms: {', '.join(terms)}",
        )

        # ---- 6. the question bank -------------------------------------
        if compile_bank:
            accepted = client.post(f"/api/engagements/{engagement_id}/bank/compile")
            candidates = 0
            deadline = time.monotonic() + 600
            while time.monotonic() < deadline:
                outcome = client.get(f"/api/engagements/{engagement_id}/bank/compile")
                bank = client.get(f"/api/engagements/{engagement_id}/bank").json()
                candidates = sum(len(s["candidates"]) for s in bank["sections"])
                if outcome.status_code == 200 and outcome.json().get("complete"):
                    break
                time.sleep(10)
            report.record(
                "6", "Draft and review the question bank",
                PASS if candidates > 0 else FAIL,
                f"compile accepted {accepted.status_code}; {candidates} candidates "
                f"across {len(bank['sections'])} sections",
            )
        else:
            report.record(
                "6", "Draft and review the question bank", SKIP,
                "not compiled — pass --compile to draft it against the live model",
            )

        # ---- 9-12. the live path (scripted; see fixtures) -------------
        backend.session_stream_events[meeting_id] = list(fixtures.SESSION_SCRIPT)
        session = client.post(f"/api/meetings/{meeting_id}/session/start")
        report.record(
            "9", "Start the live session",
            PASS if session.status_code in (200, 201) else FAIL,
            f"session {session.json().get('session_id', '?')}",
        )

        with client.stream("GET", f"/api/meetings/{meeting_id}/session/stream") as stream:
            body = "".join(stream.iter_text())
        frames = [
            line.removeprefix("event: ")
            for line in body.splitlines()
            if line.startswith("event: ")
        ]
        nudges = frames.count("nudge")
        report.record(
            "10-11", "Coverage and nudges reach the panel",
            PASS if nudges == 4 and frames[0] == "lane" else FAIL,
            f"{len(frames)} frames: lane first, {frames.count('language')} language, "
            f"{frames.count('coverage')} coverage, {nudges} nudge",
        )

        recorded = 0
        for nudge_id, disposition in fixtures.DISPOSITIONS:
            response = client.post(
                f"/api/meetings/{meeting_id}/nudges/{nudge_id}/disposition",
                json={"disposition": disposition},
            )
            recorded += response.status_code in (200, 201)
        report.record(
            "12", "One-tap responses are recorded",
            PASS if recorded == len(fixtures.DISPOSITIONS) else FAIL,
            f"{recorded} dispositions: "
            + ", ".join(f"{n}={d}" for n, d in fixtures.DISPOSITIONS),
        )

        # ---- 14. the record path, twice -------------------------------
        started = time.monotonic()
        transcribed = client.post(
            f"/api/sessions/{meeting_id}/record-path-transcript",
            json={"audio_ref": "fixture://northgate-discovery-1"},
            timeout=TIMEOUT,
        )
        elapsed = time.monotonic() - started
        rows = transcribed.json() if transcribed.status_code == 201 else []
        report.record(
            "14a", "Both engines transcribe the session",
            PASS if len(rows) == 2 and all(r["status"] == "complete" for r in rows) else FAIL,
            f"{len(rows)} transcripts, "
            f"{sum(len(r['segments']) for r in rows)} segments, in {elapsed:.1f}s",
        )

        keyterms = [engine[1].sent_keyterms for engine in info["engines"]]
        report.record(
            "14b", "The vocabulary reaches the transcriber as keyterms",
            PASS if all(call and set(terms) <= set(call[0]) for call in keyterms) else FAIL,
            f"engine A received {len(keyterms[0][0]) if keyterms[0] else 0} keyterms",
        )

        divergences = client.get(f"/api/meetings/{meeting_id}/record/divergences")
        payload = divergences.json() if divergences.is_success else {}
        found = payload.get("spans", []) if isinstance(payload, dict) else []
        scores = _planted_scores()
        report.record(
            "14c", "Where the engines disagreed",
            PASS if len(found) >= len(scores) else FAIL,
            f"{len(found)} of {len(scores)} planted mishearings surfaced for review"
            + (
                f"\n         each one is a single word in a long span, so agreement "
                f"scores {min(scores):.2f}–{max(scores):.2f} against a "
                f"{fixtures.DIVERGENCE_THRESHOLD} threshold — the substitutions that "
                f"matter most (a number, four product names) are diluted by sentence "
                f"length and never flagged"
                if not found else ""
            ),
        )

        # ---- 15. the audio is destroyed --------------------------------
        destruction = client.get(f"/api/sessions/{meeting_id}/audio-destruction")
        record = destruction.json() if destruction.is_success else {}
        report.record(
            "15", "The audio is destroyed, and the destruction recorded",
            PASS if record.get("status") == "complete" else FAIL,
            f"status {record.get('status', 'none')}, audio_ref "
            f"{record.get('audio_ref', 'none')}, completed "
            f"{record.get('completed_at', 'never')}",
        )

        # ---- 16. the write-up ------------------------------------------
        completion = client.get(f"/api/meetings/{meeting_id}/debrief/completion")
        run_record = completion.json() if completion.is_success else {}
        stages = run_record.get("stages_completed", [])
        report.record(
            "16", "The write-up runs, stage by stage",
            PASS if run_record.get("complete") else FAIL,
            f"complete={run_record.get('complete')}, stopped_at="
            f"{run_record.get('stopped_at')}, cause={run_record.get('cause')}, "
            f"{len(stages)} stages: {', '.join(stages)}"
            + (f"\n         reason: {run_record.get('reason')}" if run_record.get("reason") else ""),
        )

        # ---- 17. the documents, with citations -------------------------
        artifacts = client.get(f"/api/meetings/{meeting_id}/artifacts")
        listed = artifacts.json() if artifacts.is_success else []
        report.record(
            "17a", "The four documents exist",
            PASS if len(listed) >= 4 else FAIL,
            f"{len(listed)} artifacts: "
            + ", ".join(sorted({row.get("artifact_type", "?") for row in listed})),
        )

        claims: list[dict[str, Any]] = []
        for suffix in ("open-questions", "decision-log"):
            response = client.get(f"/api/sessions/{meeting_id}/{suffix}")
            if response.is_success and isinstance(response.json(), list):
                claims.extend(response.json())
        brief = client.get(f"/api/sessions/{meeting_id}/project-brief")
        cited = [c for c in claims if c.get("citations")]
        report.record(
            "17b", "Every claim carries the moment it came from",
            PASS if claims and len(cited) == len(claims) else FAIL,
            f"{len(claims)} claims, {len(cited)} cited"
            + (
                f"\n         e.g. “{cited[0]['citations'][0]['quoted_text'][:60]}”"
                f" — {cited[0]['citations'][0]['speaker_tag']}"
                if cited else ""
            ),
        )
        report.record(
            "17c", "The project brief was drafted",
            PASS if brief.is_success and brief.json().get("body") else FAIL,
            (brief.json().get("body", "")[:120] + "…") if brief.is_success else f"{brief.status_code}",
        )

        if show:
            _show_write_up(client, meeting_id)

        # ---- 18. what carries forward ----------------------------------
        state = client.get(f"/api/engagements/{engagement_id}/requirements-state")
        carried = state.json() if state.is_success else {}
        report.record(
            "18", "It carries into the next meeting",
            PASS if state.is_success and carried else FAIL,
            f"{len(carried.get('confirmed_requirements', []))} confirmed, "
            f"{len(carried.get('open_questions', []))} open questions carried",
        )

    print(f"\n{report.summary()}")
    if report.failed:
        print("\nfailed steps:")
        for step, title, _, detail in report.failed:
            print(f"  {step} {title}: {detail}")
    return 1 if report.failed else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compile", action="store_true", dest="compile_bank",
                        help="draft the question bank first (minutes, live model)")
    parser.add_argument("--live", action="store_true",
                        help="write into the deployment's own state database")
    parser.add_argument("--offline", action="store_true",
                        help="answer the stages from the fixture instead of a model")
    parser.add_argument("--show", action="store_true",
                        help="print the documents the run produced")
    parser.add_argument("--json", action="store_true", help="machine-readable report")
    args = parser.parse_args()

    code = run(
        compile_bank=args.compile_bank, live=args.live, show=args.show,
        offline=args.offline,
    )
    if args.json:
        print(json.dumps({"exit": code}))
    return code


if __name__ == "__main__":
    sys.exit(main())
