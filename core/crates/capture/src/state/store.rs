use std::collections::HashMap;

use super::segment::{AudioSegmentId, AudioSegmentRef, RetainedSegment};

/// The one place captured audio samples are held after normalisation and
/// before transcription/diarization consume them (PRD FR-1.7).
///
/// This type never touches the filesystem: every segment lives as a
/// `Vec<i16>` behind a `HashMap`, and the only way a segment's memory is
/// freed is [`SegmentStore::discard`] or [`SegmentStore::discard_all`]
/// dropping it. There is no serialization, no path, no `std::fs` import
/// anywhere in this module — that absence is the guarantee, not an
/// implementation detail.
pub struct SegmentStore {
    segments: HashMap<AudioSegmentId, RetainedSegment>,
    next_id: u64,
}

impl SegmentStore {
    pub fn new() -> Self {
        Self {
            segments: HashMap::new(),
            next_id: 0,
        }
    }

    /// Takes ownership of one utterance's normalised samples and returns a
    /// handle to them. From this point on the samples live only in this map.
    pub fn insert(&mut self, samples: Vec<i16>) -> AudioSegmentRef {
        let id = AudioSegmentId::new(self.next_id);
        self.next_id += 1;
        self.segments.insert(id, RetainedSegment { samples });
        AudioSegmentRef::new(id)
    }

    /// Borrows a retained segment's samples, e.g. for the record path's
    /// transcription/diarization steps (architecture §7 steps 1/3). Returns
    /// `None` once the segment has been discarded.
    pub fn get(&self, segment_ref: &AudioSegmentRef) -> Option<&[i16]> {
        self.segments
            .get(&segment_ref.id())
            .map(|segment| segment.samples.as_slice())
    }

    /// Removes a segment, dropping its samples. Call this the moment the
    /// last of transcription/diarization finishes with it (NFR-2.4,
    /// ADR-008) — not before, since the record path needs the audio until
    /// then, and not later, which only widens the breach radius for no
    /// benefit.
    pub fn discard(&mut self, segment_ref: AudioSegmentRef) {
        self.segments.remove(&segment_ref.id());
    }

    /// Drops every retained segment, e.g. on capture pause/stop or session
    /// teardown, so nothing outlives the meeting it was captured for.
    pub fn discard_all(&mut self) {
        self.segments.clear();
    }

    /// Number of segments currently retained in memory.
    pub fn len(&self) -> usize {
        self.segments.len()
    }

    pub fn is_empty(&self) -> bool {
        self.segments.is_empty()
    }
}

impl Default for SegmentStore {
    fn default() -> Self {
        Self::new()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn inserted_segment_is_retrievable_by_its_ref() {
        let mut store = SegmentStore::new();
        let segment_ref = store.insert(vec![1, 2, 3]);
        assert_eq!(store.get(&segment_ref), Some(&[1, 2, 3][..]));
    }

    #[test]
    fn discarding_a_segment_frees_it_and_further_gets_return_none() {
        let mut store = SegmentStore::new();
        let segment_ref = store.insert(vec![1, 2, 3]);
        store.discard(segment_ref);
        assert_eq!(store.get(&segment_ref), None);
        assert!(store.is_empty());
    }

    #[test]
    fn distinct_inserts_get_distinct_refs_even_with_identical_samples() {
        let mut store = SegmentStore::new();
        let a = store.insert(vec![0; 10]);
        let b = store.insert(vec![0; 10]);
        assert_ne!(a, b);
        store.discard(a);
        assert!(
            store.get(&b).is_some(),
            "discarding one segment must not affect another"
        );
    }

    #[test]
    fn discard_all_clears_every_retained_segment() {
        let mut store = SegmentStore::new();
        let refs: Vec<_> = (0..5).map(|_| store.insert(vec![7; 4])).collect();
        store.discard_all();
        assert!(store.is_empty());
        for r in refs {
            assert_eq!(store.get(&r), None);
        }
    }

    #[test]
    fn discarding_an_unknown_ref_is_a_harmless_no_op() {
        let mut store = SegmentStore::new();
        let segment_ref = store.insert(vec![1]);
        store.discard(segment_ref);
        // Discarding twice must not panic.
        store.discard(segment_ref);
    }
}
