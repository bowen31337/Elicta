//! A minimal Aho-Corasick multi-pattern matcher (PRD FR-5.2: "detects
//! unquantified adjectives and vague quantifiers by Aho-Corasick match over
//! a curated lexicon, returning the matched span"). [`super::terms::Lexicon`]
//! builds one of these per registered term list, so scanning a token for
//! every curated term is one left-to-right trie walk over the token's text
//! regardless of how many terms are registered, rather than one
//! `str::contains` pass per term as the earlier substring scan did.
//!
//! Patterns and haystacks are matched byte-for-byte, not `char`-by-`char`:
//! [`super::terms::Lexicon`] already lower-cases both sides before this
//! runs, and UTF-8's self-synchronising encoding guarantees a byte-level
//! match can never start or end mid-character, so this is exact for the
//! curated multi-byte (e.g. Chinese) terms already covered by this crate's
//! tests.
//!
//! [`AhoCorasick::find_all`] reports every occurrence of every pattern,
//! including overlapping ones and repeats of the same pattern within one
//! haystack — the same term appearing twice is two matches, each with its
//! own span, not one.

use std::collections::{HashMap, VecDeque};
use std::ops::Range;

const ROOT: usize = 0;

#[derive(Default)]
struct Node {
    children: HashMap<u8, usize>,
    fail: usize,
    /// Indices into the original `patterns` slice that end at this node —
    /// both patterns inserted to end exactly here, and (once fail links are
    /// built) every pattern ending at a proper suffix of this node's prefix,
    /// so a single lookup after each byte finds every pattern ending at that
    /// position.
    output: Vec<usize>,
}

/// A trie of patterns with Aho-Corasick failure links, built once per
/// [`super::terms::Lexicon`] and reused across every token it scans.
pub struct AhoCorasick {
    nodes: Vec<Node>,
    pattern_len: Vec<usize>,
}

impl AhoCorasick {
    /// Builds the automaton over `patterns`. An empty `patterns` slice is a
    /// valid, permanently-empty-result automaton — a lexicon with no
    /// curated terms is not an error, just one that never matches anything.
    pub fn new(patterns: &[String]) -> Self {
        let mut nodes = vec![Node::default()];
        let pattern_len = patterns.iter().map(|p| p.len()).collect();

        for (pattern_index, pattern) in patterns.iter().enumerate() {
            let mut state = ROOT;
            for &byte in pattern.as_bytes() {
                state = match nodes[state].children.get(&byte) {
                    Some(&next) => next,
                    None => {
                        nodes.push(Node::default());
                        let next = nodes.len() - 1;
                        nodes[state].children.insert(byte, next);
                        next
                    }
                };
            }
            nodes[state].output.push(pattern_index);
        }

        let mut queue: VecDeque<usize> = VecDeque::new();
        let root_children: Vec<usize> = nodes[ROOT].children.values().copied().collect();
        for child in root_children {
            nodes[child].fail = ROOT;
            queue.push_back(child);
        }

        while let Some(u) = queue.pop_front() {
            let children: Vec<(u8, usize)> =
                nodes[u].children.iter().map(|(&b, &s)| (b, s)).collect();
            for (byte, v) in children {
                let mut f = nodes[u].fail;
                while f != ROOT && !nodes[f].children.contains_key(&byte) {
                    f = nodes[f].fail;
                }
                nodes[v].fail = nodes[f]
                    .children
                    .get(&byte)
                    .copied()
                    .filter(|&candidate| candidate != v)
                    .unwrap_or(ROOT);

                let fail_output = nodes[nodes[v].fail].output.clone();
                nodes[v].output.extend(fail_output);

                queue.push_back(v);
            }
        }

        AhoCorasick { nodes, pattern_len }
    }

    /// Every occurrence of every pattern in `haystack`, as `(pattern_index,
    /// byte_range)`, ordered by the byte position the occurrence ends at;
    /// patterns ending at the same byte keep their registration order.
    pub fn find_all(&self, haystack: &str) -> Vec<(usize, Range<usize>)> {
        let mut state = ROOT;
        let mut matches = Vec::new();

        for (byte_index, &byte) in haystack.as_bytes().iter().enumerate() {
            loop {
                if let Some(&next) = self.nodes[state].children.get(&byte) {
                    state = next;
                    break;
                } else if state == ROOT {
                    break;
                } else {
                    state = self.nodes[state].fail;
                }
            }

            let end = byte_index + 1;
            for &pattern_index in &self.nodes[state].output {
                let start = end - self.pattern_len[pattern_index];
                matches.push((pattern_index, start..end));
            }
        }

        matches
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn patterns(terms: &[&str]) -> Vec<String> {
        terms.iter().map(|t| t.to_string()).collect()
    }

    #[test]
    fn finds_a_single_pattern_and_reports_its_span() {
        let automaton = AhoCorasick::new(&patterns(&["several"]));

        let matches = automaton.find_all("we need several");

        assert_eq!(matches, vec![(0, 8..15)]);
    }

    #[test]
    fn finds_no_match_when_no_pattern_appears() {
        let automaton = AhoCorasick::new(&patterns(&["several"]));

        assert!(automaton.find_all("precisely three").is_empty());
    }

    #[test]
    fn one_pass_finds_every_distinct_pattern_present() {
        // The Aho-Corasick advantage over one `contains` scan per term: all
        // curated terms are found in a single left-to-right walk.
        let automaton = AhoCorasick::new(&patterns(&["several", "a lot", "some"]));

        let matches = automaton.find_all("there were several, a lot, and some issues");

        let pattern_indices: Vec<usize> = matches.iter().map(|(index, _)| *index).collect();
        assert_eq!(pattern_indices, vec![0, 1, 2]);
    }

    #[test]
    fn repeated_occurrences_of_the_same_pattern_are_each_reported() {
        let automaton = AhoCorasick::new(&patterns(&["some"]));

        let matches = automaton.find_all("some issues, and then some more");

        assert_eq!(matches.len(), 2);
        assert_eq!(matches[0].1, 0..4);
        assert_eq!(matches[1].1, 22..26);
    }

    #[test]
    fn overlapping_patterns_sharing_a_prefix_are_both_reported() {
        // Classic Aho-Corasick textbook case: "he" is a prefix of "she", and
        // "his"/"hers" share no letters with either — proving fail links
        // correctly re-enter the trie rather than dropping back to the root
        // and missing the shorter, overlapping match.
        let automaton = AhoCorasick::new(&patterns(&["he", "she", "his", "hers"]));

        let matches = automaton.find_all("she saw his hers");

        let mut spans: Vec<Range<usize>> = matches.iter().map(|(_, span)| span.clone()).collect();
        spans.sort_by_key(|s| s.start);
        assert_eq!(spans, vec![0..3, 1..3, 8..11, 12..14, 12..16]);
    }

    #[test]
    fn matches_a_multi_byte_curated_term() {
        let automaton = AhoCorasick::new(&patterns(&["一些"]));

        let matches = automaton.find_all("有一些问题");

        assert_eq!(matches.len(), 1);
        let (_, span) = &matches[0];
        assert_eq!(&"有一些问题"[span.clone()], "一些");
    }

    #[test]
    fn empty_haystack_yields_no_matches() {
        let automaton = AhoCorasick::new(&patterns(&["several"]));

        assert!(automaton.find_all("").is_empty());
    }

    #[test]
    fn empty_pattern_list_never_matches() {
        let automaton = AhoCorasick::new(&[]);

        assert!(automaton.find_all("several a lot some").is_empty());
    }
}
