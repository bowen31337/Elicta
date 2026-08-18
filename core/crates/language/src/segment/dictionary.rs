use std::collections::HashSet;
use std::ops::Range;

use super::SegmentToken;

/// A small built-in Mandarin dictionary covering common function words and
/// the vagueness markers called out in the PRD (差不多, 应该, 尽快, 大概 and
/// friends) so a fresh engagement segments sensibly before any per-engagement
/// vocabulary (FR-2.9) is layered on top.
const BUILTIN_ZH_WORDS: &[&str] = &[
    "我们", "你们", "他们", "这个", "那个", "什么", "怎么", "时间", "系统",
    "需求", "客户", "大概", "差不多", "应该", "尽快", "也许", "可能", "左右",
    "大约", "要求", "功能", "问题", "今天", "明天", "昨天", "会议", "产品",
    "服务",
];

/// Forward maximum-matching segmenter over a word dictionary.
///
/// This is the concrete `Segmenter` used for scripts with no orthographic
/// word boundaries (Han, Kana, Thai, Lao, Myanmar, Khmer). At each position
/// it tries the longest dictionary entry starting there; on no match it
/// falls back to a single-character token rather than stalling, so
/// segmentation always terminates and always produces tokens — including on
/// vocabulary the dictionary has never seen.
pub struct DictionarySegmenter {
    words: HashSet<String>,
    max_word_chars: usize,
}

impl DictionarySegmenter {
    pub fn new<I: IntoIterator<Item = String>>(words: I) -> Self {
        let words: HashSet<String> = words.into_iter().collect();
        let max_word_chars = words.iter().map(|w| w.chars().count()).max().unwrap_or(1);
        Self { words, max_word_chars: max_word_chars.max(1) }
    }

    /// A ready-to-use segmenter seeded with common Mandarin words.
    pub fn with_builtin_zh() -> Self {
        Self::new(BUILTIN_ZH_WORDS.iter().map(|w| w.to_string()))
    }

    /// Segments a run already known to be a single no-boundary script.
    /// Byte ranges are relative to `text`.
    pub(super) fn segment_range(&self, text: &str) -> Vec<SegmentToken> {
        let chars: Vec<(usize, char)> = text.char_indices().collect();
        let n = chars.len();
        let mut tokens = Vec::with_capacity(n);
        let mut i = 0;

        while i < n {
            let max_len = self.max_word_chars.min(n - i);
            let mut matched_len = 1; // fallback: a single character is always a valid token

            for len in (2..=max_len).rev() {
                let end_idx = i + len;
                let end_byte = end_byte_at(&chars, end_idx, text.len());
                let start_byte = chars[i].0;
                if self.words.contains(&text[start_byte..end_byte]) {
                    matched_len = len;
                    break;
                }
            }

            let end_idx = i + matched_len;
            let start_byte = chars[i].0;
            let end_byte = end_byte_at(&chars, end_idx, text.len());
            let range: Range<usize> = start_byte..end_byte;
            tokens.push(SegmentToken { text: text[range.clone()].to_string(), byte_range: range });
            i = end_idx;
        }

        tokens
    }
}

fn end_byte_at(chars: &[(usize, char)], idx: usize, text_len: usize) -> usize {
    chars.get(idx).map(|&(b, _)| b).unwrap_or(text_len)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn matches_the_longest_dictionary_word_first() {
        let seg = DictionarySegmenter::new(vec!["差不多".to_string(), "差".to_string()]);
        let tokens = seg.segment_range("差不多");
        assert_eq!(tokens.len(), 1);
        assert_eq!(tokens[0].text, "差不多");
    }

    #[test]
    fn falls_back_to_single_characters_on_unknown_text() {
        let seg = DictionarySegmenter::new(Vec::<String>::new());
        let tokens = seg.segment_range("你好");
        assert_eq!(tokens.len(), 2);
        assert_eq!(tokens[0].text, "你");
        assert_eq!(tokens[1].text, "好");
    }

    #[test]
    fn byte_ranges_slice_back_to_the_token_text() {
        let seg = DictionarySegmenter::with_builtin_zh();
        let text = "我们尽快确认";
        for tok in seg.segment_range(text) {
            assert_eq!(&text[tok.byte_range.clone()], tok.text);
        }
    }

    #[test]
    fn builtin_zh_segments_vagueness_markers_as_single_tokens() {
        let seg = DictionarySegmenter::with_builtin_zh();
        let tokens = seg.segment_range("我们大概尽快处理");
        let texts: Vec<&str> = tokens.iter().map(|t| t.text.as_str()).collect();
        assert!(texts.contains(&"我们"));
        assert!(texts.contains(&"大概"));
        assert!(texts.contains(&"尽快"));
    }
}
