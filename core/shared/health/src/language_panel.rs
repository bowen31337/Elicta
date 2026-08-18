//! Language-panel display-health check (architecture §10, failure mode
//! "Silent language misdetection": detection is *"Token tag confidence, plus
//! operator-visible language display"*, behaviour is *"detected languages
//! always displayed (FR-2.20); one-tap override (FR-2.21); tier changes
//! announced (FR-2.23, NFR-5.8)"*).
//!
//! The detector can track every language perfectly and still leave the
//! operator misled, if what it knows never reaches the panel: a rendering
//! bug, a dropped event, or a stale frame all produce the exact same
//! symptom as the misdetection itself — plausible-looking output with no
//! error raised anywhere, because the operator only ever sees the panel,
//! never the detector's internal state. This check compares the two
//! directly, so a divergence between what the detector believes and what
//! the panel is actually showing is caught as its own explicit failure
//! rather than silently trusted as "the panel must be right."

use std::fmt;

/// What the language detector currently believes, independent of whatever
/// the panel is actually rendering right now.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DetectedLanguageState {
    /// Every language detected so far, in first-detected order (mirrors PRD
    /// FR-2.20's "every language detected so far" panel contract).
    pub languages: Vec<String>,
    /// The language currently active for the meeting: the user's override
    /// (FR-2.21) once tapped, otherwise the latest confident auto-detection.
    pub active_language: Option<String>,
    /// Whether `active_language` was set by an operator override rather
    /// than auto-detection, for the divergence message's wording.
    pub is_overridden: bool,
    /// A tier drop (FR-2.23) the detector has raised but does not yet know
    /// was announced to the operator. `None` once acknowledged.
    pub unannounced_tier_drift: Option<TierDriftSummary>,
}

/// The detector-side facts needed to word a tier-drift divergence message.
/// Deliberately narrower than `tags::tier_drift::TierAnnouncement` — this
/// check only needs to say *that* a drift went unannounced, not restate the
/// full capability summary the panel itself renders.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct TierDriftSummary {
    pub from_language: String,
    pub to_language: String,
}

/// What the panel is actually showing the operator right now.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PanelDisplayState {
    pub displayed_languages: Vec<String>,
    pub displayed_active_language: Option<String>,
    /// Whether the panel has surfaced an announcement for the detector's
    /// current tier drift, if any.
    pub tier_drift_announcement_shown: bool,
}

/// Result of comparing detector state against what the panel displays.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum LanguagePanelHealthStatus {
    /// The panel fully reflects the detector's current state.
    Consistent,
    SilentFailure(LanguagePanelDivergence),
}

/// Why the panel diverged from the detector, ordered by severity: a
/// completely blank panel is the worst case (nothing at all reaches the
/// operator), followed by one missing language, then a stale active
/// language, then an unannounced tier drop.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum LanguagePanelDivergenceReason {
    /// The detector has languages to show and the panel shows none at all.
    PanelEmptyDespiteDetection,
    /// A specific detected language never made it onto the panel, even
    /// though the panel isn't fully empty.
    DetectedLanguageMissingFromPanel(String),
    /// The detector's active language (auto-detected or overridden) is not
    /// what the panel currently displays as active.
    ActiveLanguageNotReflected {
        detected: String,
        displayed: Option<String>,
        is_overridden: bool,
    },
    /// A tier drop was raised but the panel has not shown the announcement.
    TierDriftNotAnnounced(TierDriftSummary),
}

/// The alert surfaced when the panel diverges from the detector — this *is*
/// the silent failure the architecture calls out, made explicit instead of
/// left to be discovered later from wrong artifacts.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct LanguagePanelDivergence {
    pub reason: LanguagePanelDivergenceReason,
}

impl fmt::Display for LanguagePanelDivergence {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match &self.reason {
            LanguagePanelDivergenceReason::PanelEmptyDespiteDetection => write!(
                f,
                "Language panel is empty even though the detector has identified at least one language — the operator is seeing nothing."
            ),
            LanguagePanelDivergenceReason::DetectedLanguageMissingFromPanel(language) => write!(
                f,
                "Detected language '{language}' is not shown on the panel."
            ),
            LanguagePanelDivergenceReason::ActiveLanguageNotReflected {
                detected,
                displayed,
                is_overridden,
            } => {
                let source = if *is_overridden { "operator override" } else { "auto-detection" };
                match displayed {
                    Some(displayed) => write!(
                        f,
                        "Panel shows '{displayed}' as active but the {source} says it should be '{detected}'."
                    ),
                    None => write!(
                        f,
                        "Panel shows no active language but the {source} says it should be '{detected}'."
                    ),
                }
            }
            LanguagePanelDivergenceReason::TierDriftNotAnnounced(drift) => write!(
                f,
                "Meeting drifted from {} to {} but the panel never announced it.",
                drift.from_language, drift.to_language
            ),
        }
    }
}

/// Compares what the language detector currently believes against what the
/// panel is actually displaying, returning the first (most severe)
/// divergence found. Returns [`LanguagePanelHealthStatus::Consistent`] only
/// when every detected language, the active language, and any pending tier
/// drift all agree with what the panel shows — anything less is treated as
/// the silent-misdetection failure this check exists to catch, per the
/// architecture's "fail loudly" rule (§10).
pub fn check_language_panel_health(
    detected: &DetectedLanguageState,
    panel: &PanelDisplayState,
) -> LanguagePanelHealthStatus {
    if !detected.languages.is_empty() && panel.displayed_languages.is_empty() {
        return LanguagePanelHealthStatus::SilentFailure(LanguagePanelDivergence {
            reason: LanguagePanelDivergenceReason::PanelEmptyDespiteDetection,
        });
    }

    for language in &detected.languages {
        if !panel.displayed_languages.contains(language) {
            return LanguagePanelHealthStatus::SilentFailure(LanguagePanelDivergence {
                reason: LanguagePanelDivergenceReason::DetectedLanguageMissingFromPanel(
                    language.clone(),
                ),
            });
        }
    }

    if let Some(active) = &detected.active_language {
        if panel.displayed_active_language.as_ref() != Some(active) {
            return LanguagePanelHealthStatus::SilentFailure(LanguagePanelDivergence {
                reason: LanguagePanelDivergenceReason::ActiveLanguageNotReflected {
                    detected: active.clone(),
                    displayed: panel.displayed_active_language.clone(),
                    is_overridden: detected.is_overridden,
                },
            });
        }
    }

    if let Some(drift) = &detected.unannounced_tier_drift {
        if !panel.tier_drift_announcement_shown {
            return LanguagePanelHealthStatus::SilentFailure(LanguagePanelDivergence {
                reason: LanguagePanelDivergenceReason::TierDriftNotAnnounced(drift.clone()),
            });
        }
    }

    LanguagePanelHealthStatus::Consistent
}

#[cfg(test)]
mod tests {
    use super::*;

    fn detected(languages: &[&str], active: Option<&str>) -> DetectedLanguageState {
        DetectedLanguageState {
            languages: languages.iter().map(|l| l.to_string()).collect(),
            active_language: active.map(|a| a.to_string()),
            is_overridden: false,
            unannounced_tier_drift: None,
        }
    }

    fn panel(languages: &[&str], active: Option<&str>) -> PanelDisplayState {
        PanelDisplayState {
            displayed_languages: languages.iter().map(|l| l.to_string()).collect(),
            displayed_active_language: active.map(|a| a.to_string()),
            tier_drift_announcement_shown: true,
        }
    }

    #[test]
    fn empty_detector_and_empty_panel_is_consistent() {
        let status = check_language_panel_health(&detected(&[], None), &panel(&[], None));
        assert_eq!(status, LanguagePanelHealthStatus::Consistent);
    }

    #[test]
    fn matching_languages_and_active_language_is_consistent() {
        let status = check_language_panel_health(
            &detected(&["en", "zh"], Some("zh")),
            &panel(&["en", "zh"], Some("zh")),
        );
        assert_eq!(status, LanguagePanelHealthStatus::Consistent);
    }

    #[test]
    fn a_fully_blank_panel_despite_detection_is_the_worst_case() {
        let status = check_language_panel_health(&detected(&["en"], Some("en")), &panel(&[], None));

        match status {
            LanguagePanelHealthStatus::SilentFailure(divergence) => {
                assert_eq!(
                    divergence.reason,
                    LanguagePanelDivergenceReason::PanelEmptyDespiteDetection
                );
            }
            other => panic!("expected a silent failure, got {other:?}"),
        }
    }

    #[test]
    fn one_missing_language_is_flagged_even_when_others_are_shown() {
        let status = check_language_panel_health(
            &detected(&["en", "zh"], Some("en")),
            &panel(&["en"], Some("en")),
        );

        match status {
            LanguagePanelHealthStatus::SilentFailure(divergence) => {
                assert_eq!(
                    divergence.reason,
                    LanguagePanelDivergenceReason::DetectedLanguageMissingFromPanel(
                        "zh".to_string()
                    )
                );
            }
            other => panic!("expected a silent failure, got {other:?}"),
        }
    }

    #[test]
    fn stale_active_language_is_flagged_once_the_language_list_matches() {
        let status = check_language_panel_health(
            &detected(&["en", "zh"], Some("zh")),
            &panel(&["en", "zh"], Some("en")),
        );

        match status {
            LanguagePanelHealthStatus::SilentFailure(divergence) => match divergence.reason {
                LanguagePanelDivergenceReason::ActiveLanguageNotReflected {
                    ref detected,
                    ref displayed,
                    is_overridden,
                } => {
                    assert_eq!(detected, "zh");
                    assert_eq!(displayed.as_deref(), Some("en"));
                    assert!(!is_overridden);
                }
                other => panic!("expected an active-language divergence, got {other:?}"),
            },
            other => panic!("expected a silent failure, got {other:?}"),
        }
    }

    #[test]
    fn panel_showing_no_active_language_at_all_is_flagged() {
        let status =
            check_language_panel_health(&detected(&["en"], Some("en")), &panel(&["en"], None));

        match status {
            LanguagePanelHealthStatus::SilentFailure(divergence) => {
                assert!(matches!(
                    divergence.reason,
                    LanguagePanelDivergenceReason::ActiveLanguageNotReflected { .. }
                ));
            }
            other => panic!("expected a silent failure, got {other:?}"),
        }
    }

    #[test]
    fn override_that_never_reached_the_panel_is_flagged_as_an_override_mismatch() {
        let mut state = detected(&["en", "zh"], Some("zh"));
        state.is_overridden = true;

        let status = check_language_panel_health(&state, &panel(&["en", "zh"], Some("en")));

        match status {
            LanguagePanelHealthStatus::SilentFailure(divergence) => match divergence.reason {
                LanguagePanelDivergenceReason::ActiveLanguageNotReflected {
                    is_overridden, ..
                } => assert!(is_overridden),
                other => panic!("expected an active-language divergence, got {other:?}"),
            },
            other => panic!("expected a silent failure, got {other:?}"),
        }
    }

    #[test]
    fn unannounced_tier_drift_is_flagged_once_languages_and_active_agree() {
        let mut state = detected(&["en", "vi"], Some("vi"));
        state.unannounced_tier_drift = Some(TierDriftSummary {
            from_language: "en".to_string(),
            to_language: "vi".to_string(),
        });
        let mut panel_state = panel(&["en", "vi"], Some("vi"));
        panel_state.tier_drift_announcement_shown = false;

        let status = check_language_panel_health(&state, &panel_state);

        match status {
            LanguagePanelHealthStatus::SilentFailure(divergence) => {
                assert_eq!(
                    divergence.reason,
                    LanguagePanelDivergenceReason::TierDriftNotAnnounced(TierDriftSummary {
                        from_language: "en".to_string(),
                        to_language: "vi".to_string(),
                    })
                );
            }
            other => panic!("expected a silent failure, got {other:?}"),
        }
    }

    #[test]
    fn an_already_announced_tier_drift_does_not_flag() {
        let mut state = detected(&["en", "vi"], Some("vi"));
        state.unannounced_tier_drift = Some(TierDriftSummary {
            from_language: "en".to_string(),
            to_language: "vi".to_string(),
        });

        let status = check_language_panel_health(&state, &panel(&["en", "vi"], Some("vi")));

        assert_eq!(status, LanguagePanelHealthStatus::Consistent);
    }

    #[test]
    fn panel_empty_check_takes_priority_over_every_other_divergence() {
        // A blank panel is also, technically, missing every language and
        // showing no active language — but reporting "blank panel" once is
        // more actionable than a cascade of per-language alerts about the
        // exact same underlying symptom.
        let mut state = detected(&["en", "zh"], Some("zh"));
        state.unannounced_tier_drift = Some(TierDriftSummary {
            from_language: "en".to_string(),
            to_language: "zh".to_string(),
        });
        let mut panel_state = panel(&[], None);
        panel_state.tier_drift_announcement_shown = false;

        let status = check_language_panel_health(&state, &panel_state);

        assert_eq!(
            status,
            LanguagePanelHealthStatus::SilentFailure(LanguagePanelDivergence {
                reason: LanguagePanelDivergenceReason::PanelEmptyDespiteDetection,
            })
        );
    }

    #[test]
    fn divergence_message_names_the_missing_language() {
        let divergence = LanguagePanelDivergence {
            reason: LanguagePanelDivergenceReason::DetectedLanguageMissingFromPanel(
                "zh".to_string(),
            ),
        };
        assert!(divergence.to_string().contains("zh"));
    }

    #[test]
    fn divergence_message_for_a_blank_panel_says_the_operator_sees_nothing() {
        let divergence = LanguagePanelDivergence {
            reason: LanguagePanelDivergenceReason::PanelEmptyDespiteDetection,
        };
        assert!(divergence.to_string().contains("seeing nothing"));
    }

    #[test]
    fn divergence_message_for_an_override_mismatch_names_the_override_as_the_source() {
        let divergence = LanguagePanelDivergence {
            reason: LanguagePanelDivergenceReason::ActiveLanguageNotReflected {
                detected: "zh".to_string(),
                displayed: Some("en".to_string()),
                is_overridden: true,
            },
        };
        assert!(divergence.to_string().contains("operator override"));
    }

    #[test]
    fn divergence_message_for_an_auto_detection_mismatch_names_auto_detection_as_the_source() {
        let divergence = LanguagePanelDivergence {
            reason: LanguagePanelDivergenceReason::ActiveLanguageNotReflected {
                detected: "zh".to_string(),
                displayed: Some("en".to_string()),
                is_overridden: false,
            },
        };
        assert!(divergence.to_string().contains("auto-detection"));
    }

    #[test]
    fn divergence_message_for_tier_drift_names_both_languages() {
        let divergence = LanguagePanelDivergence {
            reason: LanguagePanelDivergenceReason::TierDriftNotAnnounced(TierDriftSummary {
                from_language: "en".to_string(),
                to_language: "vi".to_string(),
            }),
        };
        let message = divergence.to_string();
        assert!(message.contains("en"));
        assert!(message.contains("vi"));
    }
}
