//! The cache lifetime the Messages API's ephemeral `cache_control` marker
//! carries (architecture §3.8, §14.3's caching table): the API's own
//! default is five minutes, and PRD FR-5.10's 60-second tick sits well
//! inside that window, so a meeting whose ticks keep firing on schedule
//! never lets the prefix actually expire -- every tick's read refreshes
//! the five-minute clock before it would otherwise run out. This module
//! makes that default explicit as configuration rather than an implicit
//! "we send no `ttl` field so the API assumes five minutes," and gives a
//! caller who does want the extended one-hour lifetime a typed way to
//! configure it that a meeting's requests then carry unchanged.
//!
//! [`CacheLifetimeSettings`] is deliberately the same "configured once,
//! read back until changed" shape as other tunable settings in this
//! codebase (compare `asr-live::stream::EndpointingThresholds`): a caller
//! sets it before pinning a [`crate::prompt::MeetingPromptContext`] via
//! [`crate::prompt::MeetingPromptContext::pin_with_cache_lifetime`], and
//! every tick's prompt built from that context carries the identical
//! lifetime for as long as the meeting runs.

use std::time::Duration;

/// The Messages API's ephemeral `cache_control.ttl` values this crate
/// targets: five minutes (the API's own default when no `ttl` is sent at
/// all) and the extended one-hour option.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CacheLifetime {
    FiveMinutes,
    OneHour,
}

impl CacheLifetime {
    /// The wire value the Messages API expects for `cache_control.ttl`.
    pub fn as_ttl_str(self) -> &'static str {
        match self {
            CacheLifetime::FiveMinutes => "5m",
            CacheLifetime::OneHour => "1h",
        }
    }

    /// How long a cache write under this lifetime survives without a read
    /// -- and, symmetrically, how much slack a tick source has to land
    /// before the prefix it would have read from expires.
    pub fn duration(self) -> Duration {
        match self {
            CacheLifetime::FiveMinutes => Duration::from_secs(5 * 60),
            CacheLifetime::OneHour => Duration::from_secs(60 * 60),
        }
    }

    /// Whether a tick source firing every `tick_interval` keeps this
    /// lifetime alive continuously -- i.e. never lets a cache write
    /// actually reach its TTL before the next tick reads it and resets the
    /// clock. PRD FR-5.10's 60-second tick against the five-minute default
    /// holds this with room to spare; this method lets a caller check the
    /// same holds for whatever interval and lifetime it is actually
    /// configured with, rather than assuming it from the two defaults.
    pub fn is_kept_alive_by(self, tick_interval: Duration) -> bool {
        tick_interval < self.duration()
    }
}

impl Default for CacheLifetime {
    /// The Messages API's own default when a request sends no `ttl` at
    /// all.
    fn default() -> Self {
        CacheLifetime::FiveMinutes
    }
}

/// The cache lifetime configured for a meeting, remembered once set.
/// Reading before ever calling [`CacheLifetimeSettings::set`] returns
/// [`CacheLifetime::default`] -- the API's own five-minute default -- so a
/// meeting that never touches this setting still behaves exactly as if it
/// had explicitly configured five minutes.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct CacheLifetimeSettings {
    configured: CacheLifetime,
}

impl CacheLifetimeSettings {
    pub fn new() -> Self {
        Self { configured: CacheLifetime::default() }
    }

    /// The lifetime this meeting is configured to use -- whatever was last
    /// passed to [`Self::set`], or the five-minute default if it never
    /// was.
    pub fn configured(&self) -> CacheLifetime {
        self.configured
    }

    /// Configures the lifetime for the rest of the meeting. Persists for
    /// every subsequent [`Self::configured`] call until set again.
    pub fn set(&mut self, lifetime: CacheLifetime) {
        self.configured = lifetime;
    }
}

impl Default for CacheLifetimeSettings {
    fn default() -> Self {
        Self::new()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::ticker::DEFAULT_TICK_INTERVAL;

    #[test]
    fn the_default_lifetime_is_five_minutes() {
        assert_eq!(CacheLifetime::default(), CacheLifetime::FiveMinutes);
        assert_eq!(CacheLifetime::default().duration(), Duration::from_secs(300));
        assert_eq!(CacheLifetime::default().as_ttl_str(), "5m");
    }

    #[test]
    fn settings_start_at_the_five_minute_default_before_anything_is_configured() {
        let settings = CacheLifetimeSettings::new();
        assert_eq!(settings.configured(), CacheLifetime::FiveMinutes);
    }

    #[test]
    fn configuring_a_lifetime_persists_it_across_every_subsequent_read() {
        let mut settings = CacheLifetimeSettings::new();
        settings.set(CacheLifetime::OneHour);

        assert_eq!(settings.configured(), CacheLifetime::OneHour);
        assert_eq!(settings.configured(), CacheLifetime::OneHour, "reading twice must not lose the configured value");
    }

    #[test]
    fn re_configuring_replaces_the_previous_value_rather_than_stacking() {
        let mut settings = CacheLifetimeSettings::new();
        settings.set(CacheLifetime::OneHour);
        settings.set(CacheLifetime::FiveMinutes);

        assert_eq!(settings.configured(), CacheLifetime::FiveMinutes);
    }

    #[test]
    fn the_default_tick_interval_keeps_the_default_cache_lifetime_alive_continuously() {
        assert!(
            CacheLifetime::default().is_kept_alive_by(DEFAULT_TICK_INTERVAL),
            "PRD FR-5.10's 60-second tick must land well inside the five-minute default lifetime, or a slow \
             meeting would let the cached prefix expire between ticks"
        );
    }

    #[test]
    fn a_one_hour_lifetime_is_also_kept_alive_by_the_default_tick_interval() {
        assert!(CacheLifetime::OneHour.is_kept_alive_by(DEFAULT_TICK_INTERVAL));
    }

    #[test]
    fn an_interval_longer_than_the_lifetime_would_not_be_kept_alive() {
        assert!(!CacheLifetime::FiveMinutes.is_kept_alive_by(Duration::from_secs(600)));
    }

    #[test]
    fn ttl_wire_values_match_the_messages_api() {
        assert_eq!(CacheLifetime::FiveMinutes.as_ttl_str(), "5m");
        assert_eq!(CacheLifetime::OneHour.as_ttl_str(), "1h");
    }

    #[test]
    fn default_trait_impl_matches_new() {
        assert_eq!(CacheLifetimeSettings::default(), CacheLifetimeSettings::new());
    }
}
