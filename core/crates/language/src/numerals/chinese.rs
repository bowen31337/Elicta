//! Chinese spelled-out numbers -> numerals, including 万/亿 magnitude
//! grouping that no ASR vendor's inverse-text-normalisation reliably handles
//! (architecture §14.1). `三百五十万` must reach the trigger gate as
//! `3500000`, not as three separate, un-grouped tokens.

fn digit_value(c: char) -> Option<i64> {
    Some(match c {
        '零' | '〇' => 0,
        '一' | '幺' | '壹' => 1,
        '二' | '两' | '貳' | '贰' => 2,
        '三' | '叁' | '參' => 3,
        '四' | '肆' => 4,
        '五' | '伍' => 5,
        '六' | '陆' | '陸' => 6,
        '七' | '柒' => 7,
        '八' | '捌' => 8,
        '九' | '玖' => 9,
        _ => return None,
    })
}

/// Units below 万 that combine into the current group (十/百/千).
fn small_unit_value(c: char) -> Option<i64> {
    Some(match c {
        '十' | '拾' => 10,
        '百' | '佰' => 100,
        '千' | '仟' => 1_000,
        _ => return None,
    })
}

/// Grouping units that multiply everything accumulated so far and start a
/// new group (万/亿) — the magnitudes PRD FR-2.17 calls out by name.
fn big_unit_value(c: char) -> Option<i64> {
    Some(match c {
        '万' | '萬' => 10_000,
        '亿' | '億' => 100_000_000,
        _ => return None,
    })
}

pub fn is_numeral_char(c: char) -> bool {
    digit_value(c).is_some() || small_unit_value(c).is_some() || big_unit_value(c).is_some()
}

/// Parse a run of Chinese numeral characters (e.g. `"三百五十万"`) into its
/// integer value. Returns `None` if `s` contains anything other than
/// recognised numeral characters, or has no digits at all.
pub fn chinese_to_number(s: &str) -> Option<i64> {
    let s = s.trim();
    if s.is_empty() || !s.chars().all(is_numeral_char) {
        return None;
    }
    parse_grouped(s)
}

/// Find the first occurrence of any char in `targets`, splitting `s` into the
/// text before and after it.
fn split_on<'a>(s: &'a str, targets: &[char]) -> Option<(&'a str, &'a str)> {
    for (idx, c) in s.char_indices() {
        if targets.contains(&c) {
            return Some((&s[..idx], &s[idx + c.len_utf8()..]));
        }
    }
    None
}

/// Recursively split on the largest grouping unit present (亿, then 万) so
/// compound magnitudes come out right, e.g. `一亿二千三百万` = 1亿 + 2300万 =
/// 123,000,000. An empty side of the split defaults to a value of 1 (`万` ==
/// "one ten-thousand" == 10,000), matching how these numbers are spoken.
fn parse_grouped(s: &str) -> Option<i64> {
    if let Some((left, right)) = split_on(s, &['亿', '億']) {
        let left_value = if left.is_empty() { 1 } else { parse_grouped(left)? };
        let right_value = if right.is_empty() { 0 } else { parse_grouped(right)? };
        return Some(left_value * 100_000_000 + right_value);
    }
    if let Some((left, right)) = split_on(s, &['万', '萬']) {
        let left_value = if left.is_empty() { 1 } else { parse_grouped(left)? };
        let right_value = if right.is_empty() { 0 } else { parse_grouped(right)? };
        return Some(left_value * 10_000 + right_value);
    }
    parse_section(s)
}

/// Parse a magnitude-free section (below 万): digits combined with 十/百/千.
/// `零` is a placeholder for an omitted group and contributes nothing, e.g.
/// `一千零五` ("one thousand, oh, five") = 1005.
fn parse_section(s: &str) -> Option<i64> {
    let mut total: i64 = 0;
    let mut current: i64 = 0;
    let mut seen = false;
    for c in s.chars() {
        if let Some(v) = digit_value(c) {
            current = v;
            seen = true;
        } else if let Some(v) = small_unit_value(c) {
            let multiplier = if current == 0 { 1 } else { current };
            total += multiplier * v;
            current = 0;
            seen = true;
        } else {
            return None;
        }
    }
    if !seen {
        return None;
    }
    Some(total + current)
}

/// Replace spelled-out numbers in `text` with their numeral form. See
/// [`super::normalize`] for why only runs of two or more numeral characters
/// are converted.
pub fn normalize_text(text: &str) -> String {
    let chars: Vec<char> = text.chars().collect();
    let mut out = String::with_capacity(text.len());
    let mut i = 0;
    while i < chars.len() {
        if is_numeral_char(chars[i]) {
            let start = i;
            while i < chars.len() && is_numeral_char(chars[i]) {
                i += 1;
            }
            let run: String = chars[start..i].iter().collect();
            if run.chars().count() >= 2 {
                if let Some(n) = chinese_to_number(&run) {
                    out.push_str(&n.to_string());
                    continue;
                }
            }
            out.push_str(&run);
        } else {
            out.push(chars[i]);
            i += 1;
        }
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn bare_digits() {
        assert_eq!(chinese_to_number("五"), Some(5));
        assert_eq!(chinese_to_number("零"), Some(0));
    }

    #[test]
    fn tens() {
        assert_eq!(chinese_to_number("十"), Some(10));
        assert_eq!(chinese_to_number("十五"), Some(15));
        assert_eq!(chinese_to_number("二十"), Some(20));
        assert_eq!(chinese_to_number("二十三"), Some(23));
    }

    #[test]
    fn hundreds_and_thousands() {
        assert_eq!(chinese_to_number("一百二十三"), Some(123));
        assert_eq!(chinese_to_number("一千零五"), Some(1005));
    }

    #[test]
    fn wan_grouping_matches_the_fr_2_17_example() {
        // architecture §14.1 / feature 125: 三百五十万 must normalise to 3,500,000.
        assert_eq!(chinese_to_number("三百五十万"), Some(3_500_000));
    }

    #[test]
    fn wan_grouping_with_bare_wan() {
        assert_eq!(chinese_to_number("五万"), Some(50_000));
        assert_eq!(chinese_to_number("十万"), Some(100_000));
    }

    #[test]
    fn yi_grouping_compound() {
        // 一亿二千三百万 = 1亿 + 2300万 = 123,000,000.
        assert_eq!(chinese_to_number("一亿二千三百万"), Some(123_000_000));
        assert_eq!(chinese_to_number("两亿三千万"), Some(230_000_000));
    }

    #[test]
    fn traditional_characters() {
        assert_eq!(chinese_to_number("三百五十萬"), Some(3_500_000));
        assert_eq!(chinese_to_number("一億"), Some(100_000_000));
    }

    #[test]
    fn non_numeral_input_is_rejected() {
        assert_eq!(chinese_to_number("你好"), None);
        assert_eq!(chinese_to_number(""), None);
    }

    #[test]
    fn normalize_text_converts_grouped_magnitude_in_context() {
        assert_eq!(normalize_text("价格是三百五十万元"), "价格是3500000元");
    }

    #[test]
    fn normalize_text_leaves_ordinary_text_untouched() {
        assert_eq!(normalize_text("你好世界"), "你好世界");
    }

    #[test]
    fn normalize_text_does_not_rewrite_a_lone_ambiguous_digit_hanzi() {
        // "十分" here means "extremely", not the number 10.
        assert_eq!(normalize_text("十分感谢"), "十分感谢");
    }
}
