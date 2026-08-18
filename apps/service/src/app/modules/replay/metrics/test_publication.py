from __future__ import annotations

from .models import RatedSuggestion
from .publication import MetricsPublication


def rating(
    language: str, *, useful: bool = False, embarrassing: bool = False
) -> RatedSuggestion:
    return RatedSuggestion(language=language, useful=useful, embarrassing=embarrassing)


def test_each_language_gets_its_own_figure():
    publication = MetricsPublication()

    publication.publish("en", [rating("en", useful=True), rating("en", useful=False)])
    publication.publish("vi", [rating("vi", useful=True), rating("vi", useful=True)])

    assert len(publication) == 2
    en_figure = publication.figure_for("en")
    vi_figure = publication.figure_for("vi")

    assert en_figure is not None
    assert vi_figure is not None
    # A blended figure across both languages would read 0.75; kept separate,
    # the struggling language stays visible instead of being averaged away.
    assert en_figure.precision_at_surfaced == 0.5
    assert vi_figure.precision_at_surfaced == 1.0


def test_a_non_zero_m2_in_one_language_does_not_bleed_into_another():
    publication = MetricsPublication()

    publication.publish("en", [rating("en", embarrassing=True)])
    publication.publish("vi", [rating("vi", embarrassing=False)])

    assert publication.figure_for("en").embarrassment_rate == 1.0
    assert publication.figure_for("vi").embarrassment_rate == 0.0


def test_republishing_the_same_language_replaces_rather_than_duplicates():
    publication = MetricsPublication()

    publication.publish("en", [rating("en", useful=False)])
    publication.publish("en", [rating("en", useful=True), rating("en", useful=True)])

    assert len(publication) == 1
    assert publication.figure_for("en").surfaced_count == 2
    assert publication.figure_for("en").precision_at_surfaced == 1.0


def test_unpublished_language_is_absent_not_zero():
    publication = MetricsPublication()

    assert publication.is_empty()
    assert publication.figure_for("en") is None


def test_figures_names_its_own_language():
    publication = MetricsPublication()

    publication.publish("en", [rating("en", useful=True)])
    publication.publish("vi", [rating("vi", useful=True)])

    languages = {figure.language for figure in publication.figures()}
    assert languages == {"en", "vi"}


def test_there_is_no_method_that_returns_a_combined_global_figure():
    public_names = {
        name for name in dir(MetricsPublication) if not name.startswith("_")
    }

    forbidden = {"overall", "global", "aggregate", "combined", "total", "blended"}
    assert not any(
        forbidden_word in name.lower()
        for name in public_names
        for forbidden_word in forbidden
    )
