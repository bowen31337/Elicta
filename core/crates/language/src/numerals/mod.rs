//! Spoken-number normalisation, downstream of ASR (PRD FR-2.17).
//!
//! ASR vendors' own inverse-text-normalisation (e.g. Deepgram's
//! `numerals=true`) already turns most spoken numbers into digits, but no
//! vendor reliably groups Chinese 万/亿 magnitudes — a transcript that
//! reaches the trigger gate as anything but the correct order of magnitude
//! breaks the entire payload of the `quantify` trigger (architecture §14.1).
//!
//! This module is the safety net. It is a pure function of text with no
//! dependency on which transcription path produced that text, so the same
//! call normalises both the live (streaming) path and the record (batch,
//! dual-engine) path — "on both transcription paths" (FR-2.17) is satisfied
//! by there being exactly one implementation, not two kept in sync.

mod chinese;
mod english;

pub use chinese::chinese_to_number;
pub use english::english_words_to_number;

/// A language this module knows how to normalise. Deliberately scoped to
/// what numeral normalisation needs today (Tier 1 launch languages, PRD
/// §8.2a); the `tags` module owns the canonical per-token language tag type
/// once it lands, and this can be re-pointed at it.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Language {
    English,
    Mandarin,
}

/// Replace spelled-out numbers in `text` with their numeral form.
///
/// This is a best-effort whole-text scan built on the guaranteed-correct
/// phrase converters ([`english_words_to_number`], [`chinese_to_number`]).
/// For Mandarin specifically, whole-text scanning is inherently ambiguous —
/// single hanzi digits are common inside ordinary words (十分 "extremely",
/// 一起 "together") with no numeral meaning at all — so this only converts
/// runs of at least two numeral characters, which excludes lone digits at
/// the cost of also excluding a genuine solo numeral like standalone 十
/// ("ten"). Callers that already know a token span is a numeral phrase
/// (e.g. the upstream segmentation/tagging pipeline) should call
/// [`chinese_to_number`] directly on that span instead of relying on this
/// heuristic.
pub fn normalize(text: &str, language: Language) -> String {
    match language {
        Language::English => english::normalize_text(text),
        Language::Mandarin => chinese::normalize_text(text),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn normalize_is_a_pure_function_shared_by_both_transcription_paths() {
        // FR-2.17 requires normalisation "on both transcription paths". There is
        // no live-path/record-path branch in this module at all: both paths call
        // the same pure function, so they cannot drift out of sync with each other.
        let live_path_output = normalize("three hundred and fifty", Language::English);
        let record_path_output = normalize("three hundred and fifty", Language::English);
        assert_eq!(live_path_output, "350");
        assert_eq!(record_path_output, "350");
    }

    #[test]
    fn chinese_grouped_magnitude_normalises_to_correct_numeral() {
        // The specific FR-2.17 example from architecture §14.1: a vendor's ITN
        // reaching the gate as anything other than the correct order of
        // magnitude breaks the quantify trigger's entire payload.
        assert_eq!(normalize("三百五十万", Language::Mandarin), "3500000");
    }

    #[test]
    fn english_spelled_out_number_normalises_in_context() {
        assert_eq!(
            normalize("it will take three weeks", Language::English),
            "it will take 3 weeks"
        );
    }

    #[test]
    fn chinese_ordinary_word_with_lone_digit_hanzi_is_left_alone() {
        // Known limitation, documented above: a lone numeral-shaped hanzi inside
        // an ordinary multi-character word is not a numeral and must not be
        // rewritten. "十分" here is the adverb ("extremely"), not the number 10.
        assert_eq!(normalize("十分感谢", Language::Mandarin), "十分感谢");
    }
}
