//! The shape of one cell in the coverage matrix (PRD FR-8.2; architecture
//! §4: `CoverageSlot[] (template section → fill state → citations)`).
//!
//! This crate persists the `template section → fill state` half of that
//! mapping. Citations belong to whichever facility records what an
//! utterance actually said (`session::Decision`, `session::Contradiction`)
//! and are deliberately not modelled here.

use std::fmt;

/// How much of a template section the meeting has covered so far.
///
/// Three states rather than a `bool` because a coverage matrix exists to
/// show an operator *where attention is still needed*, and "nothing raised
/// yet" and "raised but not confirmed" call for different responses — the
/// former is worth a nudge (PRD FR-5.6: "coverage gap combined with topic
/// drift away from an unfilled section"), the latter usually isn't.
/// [`FillState::Filled`] is the state a `Asked it` chip action moves a slot
/// to (PRD FR-6.7: "marks the coverage slot satisfied").
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum FillState {
    /// No utterance has touched this section yet.
    Empty,
    /// Something relevant has been said, but the section isn't confirmed
    /// covered.
    Partial,
    /// The section is confirmed covered — including an operator's explicit
    /// `Asked it` (PRD FR-6.7).
    Filled,
}

impl FillState {
    /// The exact string this state round-trips through the `coverage_slots`
    /// table as. A fixed, hand-written mapping rather than a derived one so
    /// the on-disk representation never silently shifts under a variant
    /// rename.
    fn as_str(self) -> &'static str {
        match self {
            FillState::Empty => "empty",
            FillState::Partial => "partial",
            FillState::Filled => "filled",
        }
    }

    fn from_str(s: &str) -> Option<Self> {
        match s {
            "empty" => Some(FillState::Empty),
            "partial" => Some(FillState::Partial),
            "filled" => Some(FillState::Filled),
            _ => None,
        }
    }
}

impl fmt::Display for FillState {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(self.as_str())
    }
}

impl rusqlite::types::ToSql for FillState {
    fn to_sql(&self) -> rusqlite::Result<rusqlite::types::ToSqlOutput<'_>> {
        Ok(rusqlite::types::ToSqlOutput::from(self.as_str()))
    }
}

impl rusqlite::types::FromSql for FillState {
    fn column_result(value: rusqlite::types::ValueRef<'_>) -> rusqlite::types::FromSqlResult<Self> {
        let text = value.as_str()?;
        FillState::from_str(text).ok_or_else(|| {
            rusqlite::types::FromSqlError::Other(
                format!("'{text}' is not a recognised fill_state").into(),
            )
        })
    }
}

/// One row of the coverage matrix for a meeting: a template section and the
/// [`FillState`] it currently maps to.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CoverageSlot {
    pub template_section: String,
    pub fill_state: FillState,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn every_fill_state_round_trips_through_its_string_form() {
        for state in [FillState::Empty, FillState::Partial, FillState::Filled] {
            assert_eq!(FillState::from_str(state.as_str()), Some(state));
        }
    }

    #[test]
    fn an_unrecognised_string_does_not_parse_to_any_fill_state() {
        assert_eq!(FillState::from_str("covered"), None);
    }
}
