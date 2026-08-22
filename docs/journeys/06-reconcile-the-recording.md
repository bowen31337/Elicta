# 6. Check the recording

*For the person running the meeting, or a reviewer · afterwards*

During the meeting, transcription is tuned for speed — a suggestion that
arrives late is worthless. Afterwards it is tuned for being right, because
everything written up comes from this version and not from the live one.

## Two transcribers, on purpose

The recording is transcribed twice by two different companies. Not for
redundancy — for disagreement. Where two independent services produce the same
text, it is almost certainly right and needs nobody's attention. Where they
differ, something was genuinely unclear, and that is exactly what a human
should look at.

![Where the two transcriptions disagreed](screenshots/recording-divergences.png)

The two readings sit side by side because you are comparing them. Stacked, it
becomes a memory exercise.

Disagreements are always flagged, never quietly resolved by picking a winner.
The whole value is in surfacing the doubt.

For the same reason the screen refuses to put a number on an agreement it has
not measured. A meeting with no pair of transcripts to compare says so, rather
than reporting that the engines agreed on none of it — which is what it used to
say, beside a count of nought disagreements, on the same screen at the same
time.

## Then the audio is destroyed

The moment both transcriptions and the speaker identification have finished —
whether they succeeded or failed — the recording is deleted and the deletion is
recorded. Nothing still needs it, and keeping it only widens what could be
exposed if something went wrong later.

## Where this stands

| | |
|---|---|
| ✅ Ready | Comparing two transcripts, flagging every disagreement, and the automatic destruction of the audio — the last of which a live run photographed working, with the reason recorded beside it |
| ✅ Ready | **Refusing to report an agreement it has not measured.** A live run showed "Engines agreed 0%" next to "Needs a look 0" — two engines that had finished, no disagreements between them, and a headline saying they matched on nothing. Both numbers were on screen at once and they contradict each other. The screen now says nothing was compared, and separates that from the engines having agreed throughout, because an operator acts on those differently |
| ⏳ Not yet | **Running the two transcribers.** The record path accepts a transcription request and stores what it is given, but it makes no outbound call to any speech vendor — there is no client for one. So the pair this whole page is about is never actually produced here, and everything downstream of the pair is exercised against transcripts that were handed to it |
| ✅ Ready | The check for that is now built: given a recording and a correct transcript, it reports what share of the mistakes the pairing would actually have shown you. A sample containing no mistakes reports “cannot tell” rather than a clean pass, because it is no evidence either way |
| ⏳ Not yet | The check still has to be run against real client recordings. We can measure the answer now; we do not have it yet |
