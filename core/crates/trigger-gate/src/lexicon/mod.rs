//! Routes a code-switched utterance's tokens to the ambiguity lexicon for
//! their own tagged language, and only that one (PRD section 8.2a, feature
//! 145).
//!
//! A prior, simpler design ran a single lexicon over an utterance's full
//! text, which forces a single language choice for the whole utterance —
//! wrong for a sentence like "这个 API 的 latency 要求是什么", which has no
//! one language. Choosing English discards every Chinese token from the
//! scan (and vice versa), so an ambiguity like 一些 ("some") sitting right
//! next to a perfectly good English token never gets a chance to match. The
//! fix mirrors `language::segment`'s "group by language tag" step (features
//! 120-122): split tokens into one group per tagged language first, then
//! scan each group with *only* the lexicon built for that language (FR-5.2,
//! section 8.2a — "a separate ambiguity lexicon per language, rebuilt for
//! that language rather than translated from English"). No group is ever
//! handed to another language's lexicon, and no group is dropped for lack of
//! one — a language with no registered lexicon simply contributes no
//! matches, rather than falling back to a different language's terms.
//!
//! ```text
//! utterance tokens ──▶ group by language tag (this module)
//!                        ├─ zh tokens ──▶ zh lexicon ──▶ zh matches
//!                        └─ en tokens ──▶ en lexicon ──▶ en matches
//!                                               │
//!                        merge matches, ordered by original token index
//! ```
//!
//! [`grouping::TaggedToken`]/[`grouping::PositionedToken`]/[`grouping::LanguageGroup`]/
//! [`grouping::group_by_language`] mirror `language::segment`'s types of the
//! same name field-for-field. Duplicated locally rather than imported:
//! `trigger-gate` and `language` are separate crates with no `Cargo.toml`
//! linking them yet (neither crate has one in this worktree), so there is no
//! way to depend on the other crate today. Re-point these at the shared
//! types once crate wiring lands — the field sets are deliberately
//! identical.

pub mod evaluation;
pub mod grouping;
pub mod hold;
pub mod router;
pub mod terms;

pub use evaluation::{evaluate_utterance, FinalisedUtterance, GateDecision, SpeakerTag};
pub use grouping::{group_by_language, LanguageGroup, PositionedToken, TaggedToken};
pub use hold::{CandidateHold, DiscardReason, HeldCandidate, Resolution};
pub use router::LexiconRouter;
pub use terms::{Lexicon, LexiconMatch};
