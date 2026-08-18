from __future__ import annotations

import pytest

from .models import RatedSuggestion
from .scoring import group_by_language, score_language


def rating(
    language: str, *, useful: bool = False, embarrassing: bool = False
) -> RatedSuggestion:
    return RatedSuggestion(language=language, useful=useful, embarrassing=embarrassing)


def test_precision_at_surfaced_is_the_fraction_rated_useful():
    ratings = [
        rating("en", useful=True),
        rating("en", useful=True),
        rating("en", useful=False),
        rating("en", useful=False),
    ]

    figure = score_language("en", ratings)

    assert figure.surfaced_count == 4
    assert figure.useful_count == 2
    assert figure.precision_at_surfaced == 0.5


def test_embarrassment_rate_is_the_fraction_rated_embarrassing():
    ratings = [
        rating("en", embarrassing=True),
        rating("en", embarrassing=False),
        rating("en", embarrassing=False),
        rating("en", embarrassing=False),
    ]

    figure = score_language("en", ratings)

    assert figure.embarrassing_count == 1
    assert figure.embarrassment_rate == 0.25


def test_zero_surfaced_suggestions_scores_zero_rather_than_dividing_by_zero():
    figure = score_language("en", [])

    assert figure.surfaced_count == 0
    assert figure.precision_at_surfaced == 0.0
    assert figure.embarrassment_rate == 0.0


def test_a_rating_s_own_language_is_ignored_in_favour_of_the_caller_s_partition():
    ratings = [rating("vi", useful=True)]

    figure = score_language("en", ratings)

    assert figure.language == "en"
    assert figure.surfaced_count == 1
    assert figure.useful_count == 1


def test_a_rated_suggestion_must_carry_a_language():
    with pytest.raises(ValueError):
        RatedSuggestion(language="", useful=True, embarrassing=False)


def test_group_by_language_partitions_ratings_preserving_order():
    en_first = rating("en", useful=True)
    vi_first = rating("vi", embarrassing=True)
    en_second = rating("en", useful=False)

    grouped = group_by_language([en_first, vi_first, en_second])

    assert grouped == {"en": [en_first, en_second], "vi": [vi_first]}
