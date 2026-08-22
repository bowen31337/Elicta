# 8. Carry what you learned into the next meeting

*For the person running the meetings · between them*

Requirements are not settled in one sitting. Everything that makes an
engagement-long tool better than a per-meeting one lives here.

## What survives a meeting

The confirmed requirements, the decisions, and — most usefully — the questions
that are still open.

![What carries into the next meeting](screenshots/arc-carried-forward.png)

Open questions lead the screen, not completed work. A question that has
survived three meetings is flagged, because it is now the most important thing
to ask: either it is genuinely hard, or it keeps getting deflected, and both
are worth knowing before you walk in.

The question list for the next meeting is weighted toward these. You do not
start from scratch, and you do not re-ask what was settled.

## Where this stands

| | |
|---|---|
| ✅ Ready | **The next meeting starts from the last one's work.** A meeting's question list is built from its engagement's prepared bank, with anything still open from previous meetings put at the top — and a question you pruned stays pruned in every meeting after it. This was written, tested and connected to nothing: both halves were read from per-meeting records nothing ever wrote, so every meeting of every engagement served an empty list. A live run failed on it with an empty bank and a fresh timestamp. Both halves already existed on the engagement; they only needed joining |
| ⏳ Not yet | **Carrying requirements and decisions.** Those are produced by the write-up, and the write-up stops at its first step for want of a transcription service — so there is nothing yet for a second meeting to inherit but the open questions an operator entered. The machinery is built and is waiting on the same missing piece as journeys 3, 4, 6 and 7 |
| ⏳ Not yet | **Watching the inheritance work end to end.** A second meeting inherits its engagement's prepared bank, and on the machine this was tested against that bank is empty — the credential available here cannot submit the drafting job at all, so nothing was ever drafted to carry forward. The join is proven against a bank supplied to it; it has not been seen carrying a bank a provider actually produced |
| ✅ Ready | All of it now survives restarting the service. The client, its meetings, the open questions, the standing requirements and the prepared question bank are written to a database as they change, and read back when Elicta next starts |
| ✅ By design | Only the five things above are stored. The working notes a debrief produces along the way are rebuilt from the recording rather than kept — slower, but a stored copy could go stale against the recording it came from, and a stale one is worse than none |
