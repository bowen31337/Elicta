//! Named `{slot}` interpolation over a phrasing template, mirroring the
//! `phrasing.format(**values)` contract `apps/service`'s
//! `compiler/tagging/tag_candidates.py` documents for the live runtime:
//! values are gathered by placeholder name, never by position, and `{{`/`}}`
//! escape a literal brace the way Python's `str.format` does.

use std::collections::HashMap;

/// A phrasing string's placeholders didn't parse or resolve.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum SlotError {
    /// A `{` was never closed, or a bare `}` appeared outside an escape.
    UnbalancedBrace,
    /// An anonymous `{}` placeholder -- nothing to resolve it by name.
    AnonymousPlaceholder,
    /// A named placeholder with no matching entry in `values`.
    UnresolvedSlot(String),
}

/// Fills every named `{slot}` in `template` from `values`, escaping `{{` and
/// `}}` to a literal brace. Scans by `char`, not by byte, so a multi-byte
/// phrasing (any non-Latin `lang` column value, per architecture §3.6) is
/// sliced correctly rather than risking a mid-codepoint split.
pub fn format_named(template: &str, values: &HashMap<&str, String>) -> Result<String, SlotError> {
    let mut out = String::with_capacity(template.len());
    let mut chars = template.chars().peekable();

    while let Some(c) = chars.next() {
        match c {
            '{' => {
                if chars.peek() == Some(&'{') {
                    chars.next();
                    out.push('{');
                    continue;
                }

                let mut name = String::new();
                let mut closed = false;
                for next in chars.by_ref() {
                    if next == '}' {
                        closed = true;
                        break;
                    }
                    name.push(next);
                }

                if !closed {
                    return Err(SlotError::UnbalancedBrace);
                }
                if name.is_empty() {
                    return Err(SlotError::AnonymousPlaceholder);
                }

                match values.get(name.as_str()) {
                    Some(value) => out.push_str(value),
                    None => return Err(SlotError::UnresolvedSlot(name)),
                }
            }
            '}' => {
                if chars.peek() == Some(&'}') {
                    chars.next();
                    out.push('}');
                } else {
                    return Err(SlotError::UnbalancedBrace);
                }
            }
            other => out.push(other),
        }
    }

    Ok(out)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn values(pairs: &[(&'static str, &str)]) -> HashMap<&'static str, String> {
        pairs.iter().map(|(k, v)| (*k, v.to_string())).collect()
    }

    #[test]
    fn fills_a_single_named_slot() {
        let out = format_named("Quantify {term}.", &values(&[("term", "fast")])).unwrap();
        assert_eq!(out, "Quantify fast.");
    }

    #[test]
    fn fills_more_than_one_named_slot() {
        let out = format_named(
            "What's the slowest {term} the {function} team would still accept?",
            &values(&[("term", "latency"), ("function", "backend")]),
        )
        .unwrap();
        assert_eq!(
            out,
            "What's the slowest latency the backend team would still accept?"
        );
    }

    #[test]
    fn unescapes_doubled_braces_to_a_literal_brace() {
        let out = format_named("{{literal}} {term}", &values(&[("term", "fast")])).unwrap();
        assert_eq!(out, "{literal} fast");
    }

    #[test]
    fn rejects_an_anonymous_placeholder() {
        let err = format_named("Quantify {}.", &HashMap::new()).unwrap_err();
        assert_eq!(err, SlotError::AnonymousPlaceholder);
    }

    #[test]
    fn rejects_an_unclosed_brace() {
        let err = format_named("Quantify {term.", &HashMap::new()).unwrap_err();
        assert_eq!(err, SlotError::UnbalancedBrace);
    }

    #[test]
    fn rejects_a_bare_closing_brace() {
        let err = format_named("Quantify term}.", &HashMap::new()).unwrap_err();
        assert_eq!(err, SlotError::UnbalancedBrace);
    }

    #[test]
    fn rejects_a_slot_with_no_matching_value() {
        let err = format_named("Quantify {term}.", &HashMap::new()).unwrap_err();
        assert_eq!(err, SlotError::UnresolvedSlot("term".to_string()));
    }
}
