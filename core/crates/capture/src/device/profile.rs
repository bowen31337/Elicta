//! The platform voice-processing options a capture backend's OS/vendor API
//! could apply on top of the raw signal, and this system's stance on all of
//! them (architecture §14.1).
//!
//! macOS voice-processing audio units and the Windows equivalents apply
//! automatic gain control, noise suppression, and beamforming tuned for a
//! human listener on the far end of a call. Every one of them removes
//! information an acoustic model needs, so every capture path takes the raw
//! input instead: do not instantiate the voice-processing IO unit, disable
//! voice isolation, disable AGC, skip beamforming. [`CaptureProfile`] is the
//! record of that decision an operator-facing UI reads to confirm it.

use std::fmt;

/// One platform voice-processing capability a capture path's OS/vendor API
/// may offer.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum VoiceProcessingOption {
    /// Automatic gain control — renormalises level for a human listener,
    /// destroying the loudness information an acoustic model uses.
    AutomaticGainControl,
    /// Noise suppression — attenuates exactly the low-level acoustic detail
    /// (fricatives, digit endings) that entity-weighted WER weights most.
    NoiseSuppression,
    /// Beamforming — steers the mic array toward the presumed talker,
    /// attenuating every other voice in the room.
    Beamforming,
}

impl fmt::Display for VoiceProcessingOption {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        let name = match self {
            VoiceProcessingOption::AutomaticGainControl => "automatic gain control",
            VoiceProcessingOption::NoiseSuppression => "noise suppression",
            VoiceProcessingOption::Beamforming => "beamforming",
        };
        f.write_str(name)
    }
}

/// The full set of platform voice-processing options this system knows
/// about, in display order.
pub const VOICE_PROCESSING_OPTIONS: [VoiceProcessingOption; 3] = [
    VoiceProcessingOption::AutomaticGainControl,
    VoiceProcessingOption::NoiseSuppression,
    VoiceProcessingOption::Beamforming,
];

/// Whether one [`VoiceProcessingOption`] is switched on for a capture path.
/// Every path in this system reports every option as [`Off`](Self::Off) —
/// there is no configuration that turns one on — so the variant exists to
/// give the operator-facing capture profile display something explicit to
/// render rather than an implicit absence.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ProcessingState {
    Off,
    On,
}

impl ProcessingState {
    pub fn is_disabled(&self) -> bool {
        matches!(self, ProcessingState::Off)
    }
}

/// The platform voice-processing profile a capture path reports to an
/// operator-facing UI (architecture §14.1). Every [`AudioSource`](super::AudioSource)
/// reports [`CaptureProfile::all_disabled`] — there is no capture path in
/// this system that leaves platform voice processing engaged.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct CaptureProfile {
    automatic_gain_control: ProcessingState,
    noise_suppression: ProcessingState,
    beamforming: ProcessingState,
}

impl CaptureProfile {
    /// The profile every capture path in this system uses: every platform
    /// voice-processing option disabled, so the acoustic model sees the raw
    /// input (architecture §14.1, PRD FR-1.2 rationale).
    pub fn all_disabled() -> Self {
        Self {
            automatic_gain_control: ProcessingState::Off,
            noise_suppression: ProcessingState::Off,
            beamforming: ProcessingState::Off,
        }
    }

    /// The state of one option, for callers that only care about a single
    /// lever rather than the whole profile.
    pub fn state_of(&self, option: VoiceProcessingOption) -> ProcessingState {
        match option {
            VoiceProcessingOption::AutomaticGainControl => self.automatic_gain_control,
            VoiceProcessingOption::NoiseSuppression => self.noise_suppression,
            VoiceProcessingOption::Beamforming => self.beamforming,
        }
    }

    /// Every option paired with its state, in display order — what an
    /// operator-facing capture profile view renders.
    pub fn options(&self) -> Vec<(VoiceProcessingOption, ProcessingState)> {
        VOICE_PROCESSING_OPTIONS
            .into_iter()
            .map(|option| (option, self.state_of(option)))
            .collect()
    }

    /// Whether every option in this profile is disabled — the invariant an
    /// operator-facing capture profile display checks before rendering.
    pub fn every_option_disabled(&self) -> bool {
        self.options().iter().all(|(_, state)| state.is_disabled())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn all_disabled_reports_every_option_off() {
        let profile = CaptureProfile::all_disabled();

        assert!(profile.every_option_disabled());
        for option in VOICE_PROCESSING_OPTIONS {
            assert_eq!(profile.state_of(option), ProcessingState::Off);
        }
    }

    #[test]
    fn options_lists_all_three_levers() {
        let profile = CaptureProfile::all_disabled();

        let options = profile.options();
        assert_eq!(options.len(), 3);
        assert!(options
            .iter()
            .all(|(_, state)| *state == ProcessingState::Off));
    }

    #[test]
    fn display_names_are_human_readable() {
        assert_eq!(
            VoiceProcessingOption::AutomaticGainControl.to_string(),
            "automatic gain control"
        );
        assert_eq!(
            VoiceProcessingOption::NoiseSuppression.to_string(),
            "noise suppression"
        );
        assert_eq!(
            VoiceProcessingOption::Beamforming.to_string(),
            "beamforming"
        );
    }
}
