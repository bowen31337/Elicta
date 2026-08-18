//! Continuous voice activity detection (architecture §3.1, §5): classifies
//! every normalized 16kHz mono frame as speech or silence to gate
//! downstream work — only audio worth transcribing needs to reach the ASR
//! adapter — and to emit the interval events that drive endpointing.
//!
//! Sits downstream of `crate::ring`'s normalization, on the capture worker
//! (architecture §6), and is cheap enough per frame to run continuously
//! rather than being invoked on demand (architecture §3.1: "small enough to
//! run continuously at negligible cost").
//!
//! [`SileroVad`] is generic over the frame-level [`SpeechProbabilityModel`]
//! it scores with; see that trait's module docs (`model.rs`) for why the
//! real Silero ONNX network isn't bound in here yet.

mod event;
mod model;
mod silero;

pub use event::{Interval, VadEvent};
pub use model::{EnergyProbabilityModel, SpeechProbabilityModel};
pub use silero::{SileroVad, SileroVadConfig};
