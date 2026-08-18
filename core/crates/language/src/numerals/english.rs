//! English spelled-out numbers -> numerals.

fn unit_value(word: &str) -> Option<i64> {
    Some(match word {
        "zero" => 0,
        "one" => 1,
        "two" => 2,
        "three" => 3,
        "four" => 4,
        "five" => 5,
        "six" => 6,
        "seven" => 7,
        "eight" => 8,
        "nine" => 9,
        "ten" => 10,
        "eleven" => 11,
        "twelve" => 12,
        "thirteen" => 13,
        "fourteen" => 14,
        "fifteen" => 15,
        "sixteen" => 16,
        "seventeen" => 17,
        "eighteen" => 18,
        "nineteen" => 19,
        _ => return None,
    })
}

fn tens_value(word: &str) -> Option<i64> {
    Some(match word {
        "twenty" => 20,
        "thirty" => 30,
        "forty" => 40,
        "fifty" => 50,
        "sixty" => 60,
        "seventy" => 70,
        "eighty" => 80,
        "ninety" => 90,
        _ => return None,
    })
}

/// Scales that flush the accumulated value into the running total, rather
/// than combining into the current hundred-group (unlike "hundred", which is
/// handled separately below because it stays within the current group).
fn scale_value(word: &str) -> Option<i64> {
    Some(match word {
        "thousand" => 1_000,
        "million" => 1_000_000,
        "billion" => 1_000_000_000,
        _ => return None,
    })
}

fn is_number_word(word: &str) -> bool {
    word == "hundred" || unit_value(word).is_some() || tens_value(word).is_some() || scale_value(word).is_some()
}

/// Convert a run of English number words (already split on whitespace and
/// hyphens, e.g. `["three", "thousand", "five", "hundred"]`) into its
/// integer value. `"and"` is treated as a no-op connector. Returns `None` if
/// the run contains no recognised number word.
pub fn english_words_to_number(words: &[&str]) -> Option<i64> {
    let mut total: i64 = 0;
    let mut current: i64 = 0;
    let mut matched = false;

    for raw in words {
        let word = raw.to_lowercase();
        if word == "and" {
            continue;
        }
        if let Some(v) = unit_value(&word) {
            current += v;
            matched = true;
        } else if let Some(v) = tens_value(&word) {
            current += v;
            matched = true;
        } else if word == "hundred" {
            current = if current == 0 { 1 } else { current } * 100;
            matched = true;
        } else if let Some(v) = scale_value(&word) {
            let multiplier = if current == 0 { 1 } else { current };
            total += multiplier * v;
            current = 0;
            matched = true;
        } else {
            return None;
        }
    }

    if !matched {
        return None;
    }
    Some(total + current)
}

/// Replace spelled-out numbers in `text` with their numeral form. See
/// [`super::normalize`] for the shared-across-both-paths rationale.
pub fn normalize_text(text: &str) -> String {
    let tokens: Vec<&str> = text.split_whitespace().collect();
    let core: Vec<String> = tokens
        .iter()
        .map(|t| {
            t.trim_matches(|c: char| !c.is_alphanumeric() && c != '-')
                .to_lowercase()
        })
        .collect();

    let mut is_num = vec![false; tokens.len()];
    for (i, word) in core.iter().enumerate() {
        if word.is_empty() {
            continue;
        }
        if word.contains('-') {
            is_num[i] = word.split('-').all(|w| !w.is_empty() && is_number_word(w));
        } else {
            is_num[i] = is_number_word(word);
        }
    }

    // Let a single "and" bridge two numeral tokens ("one hundred and fifty")
    // without merging unrelated numbers separated by "and" ("cats and dogs").
    if tokens.len() >= 3 {
        for i in 1..tokens.len() - 1 {
            if core[i] == "and" && is_num[i - 1] && is_num[i + 1] {
                is_num[i] = true;
            }
        }
    }

    let mut out: Vec<String> = Vec::new();
    let mut i = 0;
    while i < tokens.len() {
        if is_num[i] {
            let start = i;
            while i < tokens.len() && is_num[i] {
                i += 1;
            }
            let run: Vec<&str> = core[start..i].iter().flat_map(|w| w.split('-')).collect();
            match english_words_to_number(&run) {
                Some(n) => out.push(n.to_string()),
                None => out.extend(tokens[start..i].iter().map(|s| s.to_string())),
            }
        } else {
            out.push(tokens[i].to_string());
            i += 1;
        }
    }

    out.join(" ")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn small_numbers() {
        assert_eq!(english_words_to_number(&["seven"]), Some(7));
        assert_eq!(english_words_to_number(&["nineteen"]), Some(19));
    }

    #[test]
    fn tens_and_units() {
        assert_eq!(english_words_to_number(&["twenty", "three"]), Some(23));
    }

    #[test]
    fn hundreds_with_and() {
        assert_eq!(
            english_words_to_number(&["one", "hundred", "and", "fifty"]),
            Some(150)
        );
    }

    #[test]
    fn thousands_and_hundreds() {
        assert_eq!(
            english_words_to_number(&["three", "thousand", "five", "hundred", "twelve"]),
            Some(3512)
        );
    }

    #[test]
    fn bare_scale_word_implies_one() {
        assert_eq!(english_words_to_number(&["hundred"]), Some(100));
        assert_eq!(english_words_to_number(&["thousand"]), Some(1_000));
    }

    #[test]
    fn millions_and_billions() {
        assert_eq!(
            english_words_to_number(&["two", "million", "one", "hundred", "thousand"]),
            Some(2_100_000)
        );
        assert_eq!(english_words_to_number(&["one", "billion"]), Some(1_000_000_000));
    }

    #[test]
    fn non_numeral_input_is_rejected() {
        assert_eq!(english_words_to_number(&["hello"]), None);
        assert_eq!(english_words_to_number(&[]), None);
    }

    #[test]
    fn normalize_text_replaces_spelled_out_numbers_in_place() {
        assert_eq!(
            normalize_text("I have twenty three apples and five oranges"),
            "I have 23 apples and 5 oranges"
        );
    }

    #[test]
    fn normalize_text_handles_hyphenated_and_scaled_numbers() {
        assert_eq!(
            normalize_text("two thousand twenty-four was a busy year"),
            "2024 was a busy year"
        );
    }

    #[test]
    fn normalize_text_leaves_ordinary_text_untouched() {
        assert_eq!(
            normalize_text("the quick brown fox jumps over the lazy dog"),
            "the quick brown fox jumps over the lazy dog"
        );
    }

    #[test]
    fn normalize_text_preserves_and_between_unrelated_numbers() {
        assert_eq!(
            normalize_text("we need three chairs and twelve tables"),
            "we need 3 chairs and 12 tables"
        );
    }
}
