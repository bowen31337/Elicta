//! The managed per-participant capture path (PRD decision D4, FR-1.1).
//!
//! # The decision this module records
//!
//! Journey 2 ended on "the service that joins a meeting and captures each
//! participant separately has not been chosen", and an unmade decision does
//! not age well: everything downstream — speaker attribution, per-speaker
//! diarization, the whole authority-matching feature — assumes separated
//! streams exist. The choice is **a meeting-bot API that joins as a silent
//! participant and returns one audio stream per speaker**, reached through
//! the trait below rather than a specific vendor's SDK.
//!
//! Why that shape, in preference to the two alternatives:
//!
//! * **Platform SDKs** (Zoom, Teams, Meet, each natively) give the cleanest
//!   audio and separate participants properly — but they are three separate
//!   integrations with three review processes and three sets of breaking
//!   changes, and a consultancy does not get to choose which platform the
//!   client uses. That is three times the work to cover the same meetings.
//! * **Loopback plus diarization** needs no vendor at all, and is what the
//!   product already falls back to. But it separates speakers by *inference*,
//!   and every attribution error it makes lands in a requirements document
//!   attributed to the wrong person, which is the specific failure this
//!   product exists to avoid.
//!
//! The meeting-bot API covers every platform through one integration and
//! returns separation as a fact rather than an inference. Its costs are real
//! and stated here rather than discovered later: a visible bot in the
//! participant list, which the consent flow already has to disclose; a
//! per-minute charge; and a vendor in the audio path, which is exactly why
//! the boundary below is a trait.
//!
//! # Why a trait, and not a client
//!
//! Same reason `slow-lane`'s transport is a trait (ADR-013): the shared core
//! stays pure computation so the replay harness can run a meeting
//! deterministically with no network. The shell owns the socket; this crate
//! owns the contract. It also means the vendor is a swap of one
//! implementation rather than a rewrite — which, for a decision this young,
//! is the property worth paying for.

use crate::ring::{AudioFormat, RawFrame};

use super::kind::AudioSourceKind;
use super::source::{AudioSource, AudioSourceError};

/// One participant's identity, as the meeting platform reports it.
///
/// The vendor's own id is kept alongside the display name because display
/// names are not unique — two people called "Chen" in one meeting is ordinary,
/// and attributing a requirement to the wrong one is the failure this whole
/// path exists to prevent.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Participant {
    pub id: String,
    pub display_name: String,
}

/// One chunk of audio from one identified participant.
#[derive(Debug, Clone, PartialEq)]
pub struct ParticipantFrame {
    pub participant: Participant,
    pub frame: RawFrame,
}

/// A joined meeting that yields per-participant audio.
///
/// Implemented by the shell against the chosen vendor, and by
/// [`RecordedMeeting`] for tests and replay.
pub trait MeetingSession: Send {
    /// The format every participant stream arrives in.
    fn format(&self) -> AudioFormat;

    /// The next chunk from whichever participant spoke next, or `Ok(None)`
    /// when the meeting has ended.
    fn next_participant_frame(&mut self) -> Result<Option<ParticipantFrame>, AudioSourceError>;

    /// Everyone currently in the meeting.
    ///
    /// Needed separately from the frames because a silent participant still
    /// has to appear in the attendee list — authority matching (FR-4.7) is
    /// about who is *in the room*, not who has spoken so far.
    fn roster(&self) -> Vec<Participant>;
}

/// Adapts a [`MeetingSession`] to the one `AudioSource` trait every capture
/// path implements.
///
/// The adapter drops the participant tag on its way through, which looks like
/// a loss and is not: `AudioSource` feeds the ring buffer, which is a
/// real-time path that has no use for identity, and the attribution the tag
/// carries is consumed from [`last_speaker`](Self::last_speaker) by the
/// diarization side instead. Widening `AudioSource` to carry an optional
/// speaker for the one backend that has one would put a `None` in every other
/// backend's frames.
pub struct ManagedParticipantSource<S: MeetingSession> {
    session: S,
    last_speaker: Option<Participant>,
}

impl<S: MeetingSession> ManagedParticipantSource<S> {
    pub fn new(session: S) -> Self {
        Self { session, last_speaker: None }
    }

    /// Who produced the most recently yielded frame.
    pub fn last_speaker(&self) -> Option<&Participant> {
        self.last_speaker.as_ref()
    }

    /// Everyone in the meeting, speaking or not.
    pub fn roster(&self) -> Vec<Participant> {
        self.session.roster()
    }
}

impl<S: MeetingSession> AudioSource for ManagedParticipantSource<S> {
    fn kind(&self) -> AudioSourceKind {
        AudioSourceKind::ManagedParticipant
    }

    fn format(&self) -> AudioFormat {
        self.session.format()
    }

    fn next_frame(&mut self) -> Result<Option<RawFrame>, AudioSourceError> {
        match self.session.next_participant_frame()? {
            None => Ok(None),
            Some(tagged) => {
                self.last_speaker = Some(tagged.participant);
                Ok(Some(tagged.frame))
            }
        }
    }
}

/// A meeting replayed from a fixed script — the deterministic stand-in the
/// replay harness needs, and what every test below drives.
pub struct RecordedMeeting {
    format: AudioFormat,
    roster: Vec<Participant>,
    frames: std::vec::IntoIter<Result<ParticipantFrame, AudioSourceError>>,
}

impl RecordedMeeting {
    pub fn new(
        format: AudioFormat,
        roster: Vec<Participant>,
        frames: Vec<Result<ParticipantFrame, AudioSourceError>>,
    ) -> Self {
        Self { format, roster, frames: frames.into_iter() }
    }
}

impl MeetingSession for RecordedMeeting {
    fn format(&self) -> AudioFormat {
        self.format
    }

    fn next_participant_frame(&mut self) -> Result<Option<ParticipantFrame>, AudioSourceError> {
        self.frames.next().transpose()
    }

    fn roster(&self) -> Vec<Participant> {
        self.roster.clone()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn person(id: &str, name: &str) -> Participant {
        Participant { id: id.into(), display_name: name.into() }
    }

    fn meeting(
        frames: Vec<Result<ParticipantFrame, AudioSourceError>>,
    ) -> ManagedParticipantSource<RecordedMeeting> {
        ManagedParticipantSource::new(RecordedMeeting::new(
            AudioFormat::new(48_000, 1),
            vec![person("p1", "Priya Raman"), person("p2", "Dan Okoro")],
            frames,
        ))
    }

    fn spoken(participant: Participant, sample: f32) -> Result<ParticipantFrame, AudioSourceError> {
        Ok(ParticipantFrame {
            participant,
            frame: RawFrame::new(AudioFormat::new(48_000, 1), vec![sample]),
        })
    }

    #[test]
    fn it_presents_as_the_managed_capture_path() {
        assert_eq!(meeting(vec![]).kind(), AudioSourceKind::ManagedParticipant);
    }

    #[test]
    fn each_frame_carries_forward_who_spoke_it() {
        // The whole reason for choosing a managed vendor: attribution is a
        // fact the platform reports, not something inferred from the audio.
        let mut source = meeting(vec![
            spoken(person("p1", "Priya Raman"), 0.5),
            spoken(person("p2", "Dan Okoro"), -0.5),
        ]);

        assert!(source.last_speaker().is_none(), "nobody has spoken yet");

        source.next_frame().expect("first frame");
        assert_eq!(source.last_speaker().map(|p| p.id.as_str()), Some("p1"));

        source.next_frame().expect("second frame");
        assert_eq!(source.last_speaker().map(|p| p.id.as_str()), Some("p2"));
    }

    #[test]
    fn the_roster_includes_participants_who_have_not_spoken() {
        // Authority matching (FR-4.7) is about who is in the room. A silent
        // decision-maker is exactly the person a question should be aimed at.
        let source = meeting(vec![spoken(person("p1", "Priya Raman"), 0.5)]);

        let names: Vec<String> =
            source.roster().into_iter().map(|p| p.display_name).collect();
        assert_eq!(names, vec!["Priya Raman", "Dan Okoro"]);
    }

    #[test]
    fn identity_is_by_id_not_display_name() {
        // Two people with the same display name in one meeting is ordinary,
        // and attributing a requirement to the wrong one is the failure this
        // path exists to prevent.
        let mut source = ManagedParticipantSource::new(RecordedMeeting::new(
            AudioFormat::new(48_000, 1),
            vec![person("p1", "Chen"), person("p2", "Chen")],
            vec![spoken(person("p2", "Chen"), 0.25)],
        ));

        source.next_frame().expect("frame");
        assert_eq!(source.last_speaker().map(|p| p.id.as_str()), Some("p2"));
    }

    #[test]
    fn the_end_of_a_meeting_is_not_an_error() {
        let mut source = meeting(vec![spoken(person("p1", "Priya Raman"), 0.5)]);

        assert!(source.next_frame().expect("frame").is_some());
        assert_eq!(source.next_frame(), Ok(None));
    }

    #[test]
    fn a_dropped_vendor_stream_reaches_the_operator() {
        // A vendor in the audio path is the cost of this decision, so its
        // failure has to surface rather than look like a quiet meeting.
        let mut source = meeting(vec![Err(AudioSourceError::Disconnected(
            "meeting bot was removed from the call".into(),
        ))]);

        match source.next_frame() {
            Err(AudioSourceError::Disconnected(reason)) => {
                assert!(reason.contains("removed from the call"), "{reason}");
            }
            other => panic!("expected a disconnect, got {other:?}"),
        }
    }

    #[test]
    fn the_last_speaker_is_unchanged_by_a_failed_read() {
        // Attribution must not silently roll onto the previous speaker when a
        // read fails — that would put one person's words under another's name.
        let mut source = meeting(vec![
            spoken(person("p1", "Priya Raman"), 0.5),
            Err(AudioSourceError::Disconnected("stream dropped".into())),
        ]);

        source.next_frame().expect("first frame");
        let before = source.last_speaker().cloned();
        assert!(source.next_frame().is_err());

        assert_eq!(source.last_speaker().cloned(), before);
    }
}
