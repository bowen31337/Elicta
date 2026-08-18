"""Derives the engagement's expected-language set from client context (PRD FR-2.14).

FR-2.14 constrains ASR language detection to an engagement-scoped set derived
from client context (FR-3) rather than asked for explicitly, preserving
FR-2.11 ("the operator never chooses a language before a meeting"). This
module supplies the derivation plus a `save` callback for persistence, since
that layer does not live in this package (`app/modules/engagement/vocabulary`)
— same reasoning as `router.py` in this package. Whoever wires the app
factory (out of this feature's footprint) supplies the real,
persistence-backed `SaveExpectedLanguages` implementation and calls
`derive_and_persist_expected_languages` once client context becomes known
(engagement creation, PRD FR-3.1).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from pydantic import BaseModel, Field

DEFAULT_LANGUAGE = "en"

# Keyword -> ISO 639-1 (or 639-3 for "yue") signal, scanned across
# organisation, sector, and commercial context together, since any of the
# three may carry the signal (a sector of "APAC manufacturing" or a
# commercial_context mentioning "Shenzhen suppliers" both imply the same
# language). Kept to the launch languages PRD §8.2a names or neighbours them
# (English and Mandarin are Tier 1; everything else is Tier 2 by default). An
# unmatched context still yields `["en"]` rather than nothing — FR-2.14
# ranks languages outside the set lower, it never excludes them, so a missed
# signal here costs ranking, not transcription coverage.
_LANGUAGE_SIGNALS: dict[str, str] = {
    "mandarin": "zh",
    "cantonese": "yue",
    "chinese": "zh",
    "china": "zh",
    "shenzhen": "zh",
    "shanghai": "zh",
    "beijing": "zh",
    "hong kong": "yue",
    "taiwan": "zh",
    "japanese": "ja",
    "japan": "ja",
    "tokyo": "ja",
    "korean": "ko",
    "korea": "ko",
    "seoul": "ko",
    "vietnamese": "vi",
    "vietnam": "vi",
    "german": "de",
    "germany": "de",
    "french": "fr",
    "france": "fr",
    "spanish": "es",
    "spain": "es",
    "latin america": "es",
    "mexico": "es",
    "portuguese": "pt",
    "brazil": "pt",
}


class ClientContext(BaseModel):
    """The subset of engagement client background FR-2.14 derives from (PRD FR-3.1).

    Mirrors the corresponding fields of `EngagementCreateRequest`
    (`app/modules/engagement/api/schemas.py`) rather than importing it, for
    the same reason `router.py` in this package takes callbacks instead of a
    persistence import: that schema lives in a sibling package outside this
    feature's footprint.
    """

    client_organisation: str = Field(min_length=1)
    sector: str = Field(min_length=1)
    commercial_context: str = Field(min_length=1)


class ExpectedLanguageSet(BaseModel):
    """The derived, engagement-scoped ASR language bias list (PRD FR-2.14)."""

    engagement_id: str = Field(min_length=1)
    languages: list[str] = Field(min_length=1)


SaveExpectedLanguages = Callable[[ExpectedLanguageSet], Awaitable[None]]


def derive_expected_languages(context: ClientContext) -> list[str]:
    """Derives the expected-language set for ASR biasing from client context (PRD FR-2.14).

    Scans organisation, sector, and commercial context text for the language
    and region signals in `_LANGUAGE_SIGNALS` and returns their matched
    languages plus `DEFAULT_LANGUAGE`, deduplicated with English always
    first — English is the Tier 1 baseline every engagement can expect
    (PRD §8.2a), and outside languages still transcribe under FR-2.14, they
    just rank lower.
    """

    haystack = (
        f"{context.client_organisation} {context.sector} {context.commercial_context}"
    ).lower()

    derived = [DEFAULT_LANGUAGE]
    for signal, language in _LANGUAGE_SIGNALS.items():
        if signal in haystack and language not in derived:
            derived.append(language)

    return derived


async def derive_and_persist_expected_languages(
    engagement_id: str,
    context: ClientContext,
    save: SaveExpectedLanguages,
) -> ExpectedLanguageSet:
    """Derives the expected-language set and persists it on the engagement record (PRD FR-2.14).

    Persistence goes through the injected `save` callback rather than a
    direct write, mirroring `state/reference_claims.py`'s
    `set_verify_with_client`: the real, persistence-backed implementation is
    supplied by whoever wires the app factory, outside this feature's
    footprint.
    """

    expected = ExpectedLanguageSet(
        engagement_id=engagement_id,
        languages=derive_expected_languages(context),
    )
    await save(expected)
    return expected
