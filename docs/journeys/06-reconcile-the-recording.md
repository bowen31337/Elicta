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

## Then the audio is destroyed

The moment both transcriptions and the speaker identification have finished —
whether they succeeded or failed — the recording is deleted and the deletion is
recorded. Nothing still needs it, and keeping it only widens what could be
exposed if something went wrong later.

## Where this stands

| | |
|---|---|
| ✅ Ready | Running both transcribers, comparing them, flagging every disagreement, and the automatic destruction of the audio |
| ✅ Ready | The check for that is now built: given a recording and a correct transcript, it reports what share of the mistakes the pairing would actually have shown you. A sample containing no mistakes reports “cannot tell” rather than a clean pass, because it is no evidence either way |
| ⏳ Not yet | The check still has to be run against real client recordings. We can measure the answer now; we do not have it yet |
