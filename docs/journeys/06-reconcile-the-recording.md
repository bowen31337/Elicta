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
| ✅ Ready | **One of the two transcribers is real, and it works.** Given the same raw, chunked linear16 audio the capture pipeline produces — posted chunk by chunk the way this journey describes, out of order once to confirm the gap is refused rather than silently joined — Deepgram returns a COMPLETE transcript, speaker-tagged. The engagement's own vocabulary (a product name, a person's surname) came back spelled correctly, which is the keyterm handshake actually reaching the wire rather than a test double standing in for it. Full diarization over the same audio, run separately for the write-up, told the two real speakers apart into two distinct tags rather than one — R7, open since the first spikes used a single narrator, is closed |
| ⏳ Not yet | **The second transcriber has never finished against real audio, so the pairing this page exists for is still unproven live.** AssemblyAI is handed the identical raw, headerless PCM that Deepgram accepts and completes — but AssemblyAI's own transcoder answers "file type ... may be unsupported," where Deepgram is told the encoding and sample rate on the request itself and AssemblyAI is told nothing and has to guess from the bytes. Wrapping the same bytes in a plain WAV header before sending confirms the diagnosis: AssemblyAI transcribes it correctly once a container says what it is. Nothing here was a rate limit or a bad key — both credentials probe as reachable — so no live `SessionAlignment` has actually been computed yet; comparison and divergence remain proven only against fixtures. AssemblyAI's own cleanup still ran and removed its half-made copy even though the run failed, so the failure did not leave a recording sitting on a third party's disk |
| ✅ Ready | The check for that is now built: given a recording and a correct transcript, it reports what share of the mistakes the pairing would actually have shown you. A sample containing no mistakes reports “cannot tell” rather than a clean pass, because it is no evidence either way |
| ⏳ Not yet | The check still has to be run against real client recordings. We can measure the answer now; we do not have it yet |
