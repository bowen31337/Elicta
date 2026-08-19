"""Tests for the chapter manifest and the renderer.

The renderer is pure: facts in, Markdown out. Two properties matter more
than any particular wording -- it is reproducible (CI re-runs `build` and
requires no diff), and it never touches hand-written prose.
"""

import tempfile
import unittest
from pathlib import Path
from textwrap import dedent

import book
import render
import sources


def tmp_root() -> Path:
    tmp = tempfile.TemporaryDirectory()
    unittest.TestCase.addClassCleanup(tmp.cleanup)
    return Path(tmp.name)


MANIFEST = """
[handbook]
title = "The Test Handbook"

[[chapter]]
id = "intro"
file = "chapters/01-intro.md"
title = "Intro"
kind = "prose"
watches = ["README.md"]

[[chapter]]
id = "crates"
file = "chapters/02-crates.md"
title = "Crates"
kind = "generated"
generator = "crates"
"""


class ManifestTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        (self.root / "handbook").mkdir()
        (self.root / "handbook" / "book.toml").write_text(dedent(MANIFEST), encoding="utf-8")

    def test_chapters_load_in_manifest_order(self):
        loaded = book.load_book(self.root)
        self.assertEqual([c.id for c in loaded.chapters], ["intro", "crates"])
        self.assertEqual(loaded.title, "The Test Handbook")

    def test_a_generated_chapter_naming_an_unknown_generator_is_rejected(self):
        (self.root / "handbook" / "book.toml").write_text(
            dedent(MANIFEST).replace('generator = "crates"', 'generator = "nope"'),
            encoding="utf-8",
        )
        with self.assertRaises(book.ManifestError) as caught:
            book.load_book(self.root)
        self.assertIn("nope", str(caught.exception))

    def test_a_duplicate_chapter_id_is_rejected(self):
        (self.root / "handbook" / "book.toml").write_text(
            dedent(MANIFEST).replace('id = "crates"', 'id = "intro"'), encoding="utf-8"
        )
        with self.assertRaises(book.ManifestError):
            book.load_book(self.root)

    def test_prose_chapters_may_not_declare_a_generator(self):
        (self.root / "handbook" / "book.toml").write_text(
            dedent(MANIFEST).replace('kind = "generated"', 'kind = "prose"'), encoding="utf-8"
        )
        with self.assertRaises(book.ManifestError):
            book.load_book(self.root)

    def test_the_real_handbook_manifest_loads(self):
        repo = Path(__file__).resolve().parents[2]
        loaded = book.load_book(repo)
        self.assertGreaterEqual(len(loaded.chapters), 8)
        self.assertTrue(any(c.kind == "generated" for c in loaded.chapters))
        self.assertTrue(any(c.kind == "prose" for c in loaded.chapters))


class GeneratedPageTest(unittest.TestCase):
    def test_a_generated_page_opens_with_the_do_not_edit_marker(self):
        page = render.generated_page("Crates", ["core/crates"], ["Body."])
        self.assertTrue(page.startswith(render.GENERATED_MARKER))

    def test_a_generated_page_has_exactly_one_h1_matching_its_title(self):
        page = render.generated_page("Crates", ["core/crates"], ["Body."])
        headings = [ln for ln in page.splitlines() if ln.startswith("# ")]
        self.assertEqual(headings, ["# Crates"])

    def test_a_generated_page_names_the_sources_it_was_built_from(self):
        page = render.generated_page("Crates", ["core/crates", "core/shared"], ["Body."])
        self.assertIn("core/crates", page)
        self.assertIn("core/shared", page)

    def test_rendering_the_same_facts_twice_produces_identical_bytes(self):
        first = render.generated_page("Crates", ["core/crates"], ["Body."])
        second = render.generated_page("Crates", ["core/crates"], ["Body."])
        self.assertEqual(first, second)


class CrateTableTest(unittest.TestCase):
    CRATES = [
        sources.Crate("alpha", "plugin", "core/crates/alpha", True, "Does alpha."),
        sources.Crate("beta", "plugin", "core/crates/beta", False, ""),
        sources.Crate("gamma", "shared", "core/shared/gamma", False, "Shared bits."),
    ]

    def test_crates_are_grouped_by_tier(self):
        body = "\n".join(render.crate_body(self.CRATES))
        self.assertLess(body.index("alpha"), body.index("gamma"))
        self.assertIn("## On the fast path", body)
        self.assertIn("## Shared building blocks", body)

    def test_an_unmounted_component_is_called_out_in_words_a_reader_can_use(self):
        body = "\n".join(render.crate_body(self.CRATES))
        self.assertIn("unreachable", body)
        self.assertNotIn("MOUNTED_CRATES", body, "identifier jargon reached the page")

    def test_a_crate_with_no_module_doc_shows_the_gap_rather_than_inventing_one(self):
        row = next(ln for ln in render.crate_body(self.CRATES) if "`beta`" in ln)
        self.assertIn(render.NO_DOC, row)

    def test_the_reachable_count_is_stated_so_an_empty_list_is_visible(self):
        body = "\n".join(render.crate_body(self.CRATES))
        self.assertIn("1 of 2", body)

    def test_the_generated_banner_explains_itself_without_jargon(self):
        page = render.generated_page("Crates", ["core/crates"], ["Body."])
        self.assertIn("assembled automatically", page)
        self.assertIn("cannot fall out of date", page)

    def test_the_banner_does_not_show_the_reader_a_file_path(self):
        page = render.generated_page("Crates", ["core/crates"], ["Body."])
        banner = page.split("# Crates", 1)[1].split("\n\n")[1]
        self.assertNotIn("core/crates", banner,
                         "a source path reached the visible banner")

    def test_the_sources_are_still_recorded_for_whoever_maintains_it(self):
        page = render.generated_page("Crates", ["core/crates", "core/shared"], ["Body."])
        self.assertIn("core/crates", page)
        self.assertIn("core/shared", page)
        # ...but only inside a comment, which no reader ever sees.
        for path in ("core/crates", "core/shared"):
            line = next(l for l in page.splitlines() if path in l)
            self.assertTrue(line.strip().startswith("<!--"), line)


class RouteTableTest(unittest.TestCase):
    ROUTES = [
        sources.Route("GET", "/api/a", "Read Alpha", "alpha"),
        sources.Route("POST", "/api/b", "Make Beta", "beta"),
        sources.Route("GET", "/api/c", "Read C", "alpha"),
    ]

    def test_routes_are_grouped_under_their_tag(self):
        body = "\n".join(render.route_body(self.ROUTES))
        self.assertIn("### alpha", body)
        self.assertIn("### beta", body)
        self.assertLess(body.index("### alpha"), body.index("### beta"))

    def test_the_total_is_stated_in_plain_words(self):
        body = "\n".join(render.route_body(self.ROUTES))
        self.assertIn("3 addresses", body)
        self.assertNotIn("FastAPI", body, "framework jargon reached the page")

    def test_an_empty_route_table_says_so_instead_of_rendering_a_blank_chapter(self):
        body = "\n".join(render.route_body([]))
        self.assertIn(render.EMPTY_NOTICE, body)


class EnvTableTest(unittest.TestCase):
    ENV = [
        sources.EnvVar(name="A_KEY", section="Core", default="x", summary="The key.", commented=False, marker="required"),
        sources.EnvVar(name="B_OPT", section="Core", default="1", summary="Optional thing.", commented=True, marker="optional"),
    ]

    def test_unmarked_variables_get_their_own_section_so_the_gap_is_visible(self):
        env = [*self.ENV, sources.EnvVar(name="C_RAW", section="Core", default="", summary="No marker.", commented=False, marker="unmarked")]
        body = "\n".join(render.env_body(env))
        self.assertIn("## Unmarked", body)
        self.assertIn("C_RAW", body)

    def test_an_unmarked_variable_is_not_quietly_filed_under_optional(self):
        env = [sources.EnvVar(name="C_RAW", section="Core", default="", summary="No marker.", commented=False, marker="unmarked")]
        body = "\n".join(render.env_body(env))
        self.assertNotIn("## Optional", body)

    def test_required_variables_are_listed_before_optional_ones(self):
        body = "\n".join(render.env_body(self.ENV))
        self.assertLess(body.index("A_KEY"), body.index("B_OPT"))
        self.assertIn("## Required", body)
        self.assertIn("## Optional", body)

    def test_a_citation_in_a_section_name_is_stripped_too(self):
        # `.env.example` writes "Inference (context compiler, ADR-012)" as a
        # section heading, and the heading becomes a table cell.
        env = [sources.EnvVar(name="K", section="Inference (compiler, ADR-012)",
                              default="", summary="A key.", commented=False,
                              marker="required")]
        body = "\n".join(render.env_body(env))
        self.assertNotIn("ADR-012", body)
        self.assertIn("Inference", body)

    def test_a_pipe_in_a_summary_cannot_break_the_table(self):
        env = [sources.EnvVar(name="P", section="Core", default="", summary="a | b", commented=False, marker="required")]
        row = next(ln for ln in render.env_body(env) if "`P`" in ln)
        self.assertEqual(row.count("|"), 4)


class PlainSummaryTest(unittest.TestCase):
    """Doc comments in the code cite requirement numbers. The handbook is
    read by people who cannot look those up, so they come out."""

    def test_a_parenthesised_requirement_citation_is_removed(self):
        self.assertEqual(
            render.plain_summary("The coverage tracker (architecture §3; PRD FR-8.2): "
                                 "maps each section."),
            "The coverage tracker: maps each section.")

    def test_a_trailing_citation_is_removed_with_its_punctuation(self):
        self.assertEqual(
            render.plain_summary("Entity-weighted word error rate (PRD NFR-5.1)."),
            "Entity-weighted word error rate.")

    def test_an_inline_citation_is_removed(self):
        self.assertEqual(
            render.plain_summary("Fires a pass on a tick, per FR-5.10, without blocking."),
            "Fires a pass on a tick, without blocking.")

    def test_a_possessive_section_reference_becomes_the_document_it_names(self):
        # "Architecture §6's concurrency table puts the two on separate
        # footing" cannot simply have the citation deleted -- that leaves a
        # sentence with no subject. Name the document instead.
        self.assertEqual(
            render.plain_summary("Architecture §6's concurrency table puts the two apart."),
            "The architecture document's concurrency table puts the two apart.")

    def test_an_inline_section_reference_becomes_the_document_it_names(self):
        self.assertEqual(
            render.plain_summary("Runs as architecture §3.7 requires."),
            "Runs as the architecture document requires.")

    def test_a_bare_section_number_is_simply_removed(self):
        self.assertEqual(render.plain_summary("Fires on a tick §4.2 every minute."),
                         "Fires on a tick every minute.")

    def test_no_section_sign_survives_any_of_that(self):
        for text in ("Architecture §6's table", "see §9", "architecture §3.7"):
            self.assertNotIn("§", render.plain_summary(text), text)

    def test_ordinary_parentheses_survive(self):
        text = "Runs its tick source (a dedicated thread) outside the fast lane."
        self.assertEqual(render.plain_summary(text), text)

    def test_text_with_no_citation_is_returned_unchanged(self):
        self.assertEqual(render.plain_summary("Audio capture."), "Audio capture.")

    def test_double_spaces_left_behind_are_tidied(self):
        self.assertNotIn("  ", render.plain_summary("A (PRD FR-1.1) B"))

    def test_an_empty_summary_stays_empty(self):
        self.assertEqual(render.plain_summary(""), "")


class ReadinessTableTest(unittest.TestCase):
    NOTES = [
        sources.ReadinessNote("The panel", "working", "All four responses"),
        sources.ReadinessNote("Two languages", "planned", "A native speaker must review"),
        sources.ReadinessNote("Preparing", "setup", "Needs a provider configured"),
        sources.ReadinessNote("The panel", "working", "Coverage tracking"),
    ]

    def body(self):
        return "\n".join(render.readiness_body(self.NOTES))

    def test_what_works_comes_first(self):
        body = self.body()
        self.assertLess(body.index("## Working today"), body.index("## Still to come"))

    def test_each_state_gets_its_own_section(self):
        body = self.body()
        for heading in ("## Working today", "## Still to come",
                        "## Needs setting up first"):
            self.assertIn(heading, body)

    def test_a_state_with_no_notes_gets_no_empty_section(self):
        body = "\n".join(render.readiness_body([self.NOTES[0]]))
        self.assertNotIn("## Still to come", body)

    def test_notes_from_the_same_area_are_kept_together(self):
        rows = [line for line in self.body().splitlines() if "The panel" in line]
        self.assertEqual(len(rows), 2)

    def test_no_emoji_reaches_the_page(self):
        for symbol in ("\u2705", "\u23f3", "\u2699"):
            self.assertNotIn(symbol, self.body())

    def test_the_counts_are_stated_so_an_empty_read_is_visible(self):
        self.assertIn("4", self.body())

    def test_nothing_at_all_says_so(self):
        self.assertIn(render.EMPTY_NOTICE, "\n".join(render.readiness_body([])))


class NavTest(unittest.TestCase):
    PROSE = "# Intro\n\nHand-written prose that must survive.\n"

    def test_nav_is_appended_below_the_marker(self):
        out = render.apply_nav(self.PROSE, prev=None, next=("crates", "Crates", "02-crates.md"))
        self.assertIn(render.NAV_MARKER, out)
        self.assertIn("02-crates.md", out)

    def test_prose_above_the_marker_is_preserved_byte_for_byte(self):
        out = render.apply_nav(self.PROSE, prev=None, next=None)
        self.assertTrue(out.startswith(self.PROSE.rstrip() + "\n"))

    def test_re_applying_nav_replaces_it_rather_than_stacking_a_second_copy(self):
        once = render.apply_nav(self.PROSE, prev=None, next=("c", "C", "c.md"))
        twice = render.apply_nav(once, prev=None, next=("c", "C", "c.md"))
        self.assertEqual(once, twice)
        self.assertEqual(twice.count(render.NAV_MARKER), 1)

    def test_changing_the_neighbour_rewrites_the_existing_nav(self):
        once = render.apply_nav(self.PROSE, prev=None, next=("c", "C", "c.md"))
        moved = render.apply_nav(once, prev=None, next=("d", "D", "d.md"))
        self.assertIn("d.md", moved)
        self.assertNotIn("c.md", moved)


if __name__ == "__main__":
    unittest.main()
