//! Entity-weighted word error rate (PRD NFR-5.1).
//!
//! Overall WER weights every token equally, which hides exactly the
//! failures this product cannot tolerate: a transcript that gets every
//! filler word right and every number wrong scores well on overall WER and
//! is useless for the `quantify` trigger, whose entire payload is a number
//! (architecture §3.2, "Measurement"; PRD NFR-5.1 rationale). This crate
//! weights alignment errors toward the four categories NFR-5.1 names
//! explicitly — numerals, proper nouns, negations, and engagement
//! vocabulary — so the published figure reflects the errors that actually
//! break a trigger, not the errors that don't.
//!
//! Five entry points cover what a caller needs: [`score_utterance`] scores
//! one reference/hypothesis pair, [`score_run`] folds a whole run's pairs
//! into one figure for a single partition, [`WerPublication`] is the
//! caller-facing surface for NFR-5.7 — it scores and keeps every
//! language/capture-mode partition's figure separate, with no method
//! anywhere that folds them into one global number — [`RecordPathGate`]
//! turns a partition's figure into a pass/fail verdict against the record
//! path's per-tier bar (NFR-5.4, NFR-5.5), and [`LivePathGate`] turns it
//! into a pass/fail verdict against the live path's per-capture-mode bar
//! (NFR-5.2 monolingual, NFR-5.3 code-switched).

mod entity;
mod gate;
mod publish;
mod score;

pub use entity::{classify, EngagementVocabulary, EntityClass};
pub use gate::{
    CaptureMode, GateReport, LanguageTier, LiveGateReport, LivePathBar, LivePathGate,
    RecordPathBar, RecordPathGate, Verdict,
};
pub use publish::{PublishKey, PublishedFigure, WerPublication};
pub use score::{score_run, score_utterance, AlignmentWeights, RunReport, UtteranceReport};
