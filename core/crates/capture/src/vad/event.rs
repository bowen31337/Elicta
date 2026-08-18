use std::time::Duration;

/// A closed span of continuous speech or continuous silence, expressed as
/// `[start, end)` offsets from the moment a [`super::SileroVad`] started
/// classifying a stream.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Interval {
    pub start: Duration,
    pub end: Duration,
}

impl Interval {
    pub fn duration(&self) -> Duration {
        self.end.saturating_sub(self.start)
    }
}

/// One interval [`super::SileroVad`] emits as it continuously classifies
/// incoming audio (architecture §3.1: "Silero VAD runs here to gate
/// downstream work and to detect the silence intervals that drive
/// endpointing"). Emitted only once an interval *closes* — i.e. once enough
/// contrary evidence has accumulated to confirm the transition — never
/// speculatively while the classification could still flip back.
///
/// This is the retrospective half of what the detector exposes; the live,
/// instant-by-instant half is [`super::SileroVad::is_speech`], which a
/// caller gating downstream work reads directly rather than waiting for an
/// interval to close.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum VadEvent {
    Speech(Interval),
    Silence(Interval),
}
