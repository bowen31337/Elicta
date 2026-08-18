"""Tests for deriving and persisting an engagement's expected-language set (PRD FR-2.14)."""

from __future__ import annotations

import asyncio

from app.modules.engagement.vocabulary.language import (
    ClientContext,
    ExpectedLanguageSet,
    derive_and_persist_expected_languages,
    derive_expected_languages,
)


def make_context(
    client_organisation: str = "Acme Corp",
    sector: str = "Retail",
    commercial_context: str = "Domestic expansion into new store formats",
) -> ClientContext:
    return ClientContext(
        client_organisation=client_organisation,
        sector=sector,
        commercial_context=commercial_context,
    )


def test_a_context_with_no_language_signals_derives_only_english():
    assert derive_expected_languages(make_context()) == ["en"]


def test_a_mandarin_signal_in_commercial_context_adds_mandarin_after_english():
    context = make_context(
        commercial_context="Sourcing negotiations with Mandarin-speaking suppliers in Shenzhen"
    )

    assert derive_expected_languages(context) == ["en", "zh"]


def test_a_language_signal_in_the_sector_field_is_also_scanned():
    context = make_context(sector="APAC manufacturing, Japan-based plants")

    assert derive_expected_languages(context) == ["en", "ja"]


def test_a_language_signal_in_the_organisation_name_is_also_scanned():
    context = make_context(client_organisation="Berlin Logistics Germany", sector="Logistics")

    assert derive_expected_languages(context) == ["en", "de"]


def test_multiple_distinct_signals_each_appear_once_in_signal_order():
    context = make_context(
        commercial_context="Merging the Tokyo and Seoul back offices with the Shenzhen plant"
    )

    assert derive_expected_languages(context) == ["en", "zh", "ja", "ko"]


def test_repeated_signals_for_the_same_language_are_not_duplicated():
    context = make_context(
        commercial_context="Chinese suppliers in China, expanding to Shanghai and Beijing"
    )

    assert derive_expected_languages(context) == ["en", "zh"]


def test_matching_is_case_insensitive():
    context = make_context(commercial_context="Partnering with a MANDARIN-speaking distributor")

    assert derive_expected_languages(context) == ["en", "zh"]


def test_deriving_and_persisting_saves_and_returns_the_expected_language_set():
    saved: list[ExpectedLanguageSet] = []

    async def save(expected: ExpectedLanguageSet) -> None:
        saved.append(expected)

    context = make_context(commercial_context="Expanding into the Mandarin-speaking market")

    result = asyncio.run(
        derive_and_persist_expected_languages("engagement-1", context, save)
    )

    assert result.engagement_id == "engagement-1"
    assert result.languages == ["en", "zh"]
    assert saved == [result]


def test_deriving_and_persisting_with_no_signals_still_persists_the_english_default():
    saved: list[ExpectedLanguageSet] = []

    async def save(expected: ExpectedLanguageSet) -> None:
        saved.append(expected)

    result = asyncio.run(
        derive_and_persist_expected_languages("engagement-2", make_context(), save)
    )

    assert result.languages == ["en"]
    assert saved == [result]
