use std::ops::Range;

/// How a stretch of text should be broken into words.
///
/// `NoBoundary` scripts (Han, Kana, Thai, Lao, Myanmar, Khmer, ...) write
/// words with no separator at all, so a dictionary segmenter must run
/// before anything can match against them. `Bounded` scripts already mark
/// word edges with whitespace, so a run is a token as-is. `Separator` runs
/// carry no lexical content and are dropped.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum RunKind {
    NoBoundary,
    Bounded,
    Separator,
}

/// A maximal run of one `RunKind`, given as a byte range into the source text.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Run {
    pub kind: RunKind,
    pub range: Range<usize>,
}

/// Codepoint ranges for scripts with no orthographic word boundaries.
fn is_scriptio_continua(c: char) -> bool {
    matches!(c as u32,
        0x4E00..=0x9FFF   // CJK Unified Ideographs (Chinese, Japanese kanji)
        | 0x3400..=0x4DBF // CJK Unified Ideographs Extension A
        | 0xF900..=0xFAFF // CJK Compatibility Ideographs
        | 0x3040..=0x309F // Hiragana
        | 0x30A0..=0x30FF // Katakana
        | 0x0E00..=0x0E7F // Thai
        | 0x0E80..=0x0EFF // Lao
        | 0x1000..=0x109F // Myanmar
        | 0x1780..=0x17FF // Khmer
    )
}

fn classify_char(c: char) -> RunKind {
    if c.is_whitespace() {
        RunKind::Separator
    } else if is_scriptio_continua(c) {
        RunKind::NoBoundary
    } else {
        RunKind::Bounded
    }
}

/// Splits `text` into maximal runs of a single `RunKind`, in order.
///
/// This is the classification pass that decides, per stretch of the
/// utterance, whether a dictionary segmenter must run before any lexicon
/// match is possible (PRD FR-2.18).
pub fn split_runs(text: &str) -> Vec<Run> {
    let mut runs: Vec<Run> = Vec::new();
    let mut current_kind: Option<RunKind> = None;
    let mut current_start = 0usize;

    for (idx, c) in text.char_indices() {
        let kind = classify_char(c);
        match current_kind {
            Some(k) if k == kind => {}
            Some(k) => {
                runs.push(Run { kind: k, range: current_start..idx });
                current_kind = Some(kind);
                current_start = idx;
            }
            None => {
                current_kind = Some(kind);
                current_start = idx;
            }
        }
    }
    if let Some(k) = current_kind {
        runs.push(Run { kind: k, range: current_start..text.len() });
    }
    runs
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn classifies_han_as_no_boundary() {
        assert_eq!(classify_char('语'), RunKind::NoBoundary);
    }

    #[test]
    fn classifies_latin_as_bounded() {
        assert_eq!(classify_char('a'), RunKind::Bounded);
    }

    #[test]
    fn classifies_whitespace_as_separator() {
        assert_eq!(classify_char(' '), RunKind::Separator);
    }

    #[test]
    fn splits_code_switched_utterance_into_runs() {
        let runs = split_runs("这个API的latency要求");
        let kinds: Vec<RunKind> = runs.iter().map(|r| r.kind).collect();
        assert_eq!(
            kinds,
            vec![
                RunKind::NoBoundary, // 这个
                RunKind::Bounded,    // API
                RunKind::NoBoundary, // 的
                RunKind::Bounded,    // latency
                RunKind::NoBoundary, // 要求
            ]
        );
    }

    #[test]
    fn drops_no_content_from_separator_runs_by_kind_marker() {
        let runs = split_runs("hello 世界");
        assert_eq!(runs[1].kind, RunKind::Separator);
    }
}
