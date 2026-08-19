"""Tests for the linter.

The linter is what makes the handbook a gate rather than a suggestion.
Errors block CI; warnings ask a human to look. Every error must be
machine-fixable, or it will get suppressed instead of fixed.
"""

import tempfile
import unittest
from pathlib import Path

import lint
import render


def codes(findings, level=None):
    return sorted(f.code for f in findings if level is None or f.level == level)


class HeadingTest(unittest.TestCase):
    def test_a_page_with_no_h1_is_an_error(self):
        found = lint.check_page("chapters/a.md", "Body only.\n", "Alpha")
        self.assertIn("no-h1", codes(found))

    def test_a_page_with_two_h1s_is_an_error(self):
        found = lint.check_page("chapters/a.md", "# Alpha\n\n# Also Alpha\n", "Alpha")
        self.assertIn("multiple-h1", codes(found))

    def test_an_h1_that_disagrees_with_the_manifest_is_an_error(self):
        found = lint.check_page("chapters/a.md", "# Beta\n", "Alpha")
        self.assertIn("title-mismatch", codes(found))

    def test_a_correct_page_produces_no_findings(self):
        self.assertEqual(lint.check_page("chapters/a.md", "# Alpha\n\nText.\n", "Alpha"), [])

    def test_a_hash_inside_a_fenced_code_block_is_not_a_heading(self):
        page = "# Alpha\n\n```bash\n# Alpha\necho hi\n```\n"
        self.assertEqual(lint.check_page("chapters/a.md", page, "Alpha"), [])


class NavTest(unittest.TestCase):
    def test_two_nav_markers_are_an_error(self):
        page = f"# Alpha\n\n{render.NAV_MARKER}\n\n{render.NAV_MARKER}\n"
        self.assertIn("duplicate-nav", codes(lint.check_page("chapters/a.md", page, "Alpha")))


class MermaidTest(unittest.TestCase):
    def test_an_unknown_diagram_type_is_an_error(self):
        page = "# Alpha\n\n```mermaid\nwatercolour LR\n  a --> b\n```\n"
        self.assertIn("mermaid-unknown-type", codes(lint.check_page("chapters/a.md", page, "Alpha")))

    def test_a_known_diagram_type_passes(self):
        page = "# Alpha\n\n```mermaid\nflowchart LR\n  a --> b\n```\n"
        self.assertEqual(lint.check_page("chapters/a.md", page, "Alpha"), [])

    def test_unbalanced_brackets_are_an_error(self):
        page = "# Alpha\n\n```mermaid\nflowchart LR\n  a[Open --> b\n```\n"
        self.assertIn("mermaid-unbalanced", codes(lint.check_page("chapters/a.md", page, "Alpha")))

    def test_an_empty_mermaid_block_is_an_error(self):
        page = "# Alpha\n\n```mermaid\n```\n"
        self.assertIn("mermaid-empty", codes(lint.check_page("chapters/a.md", page, "Alpha")))


class LinkTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        (self.root / "handbook" / "chapters").mkdir(parents=True)
        (self.root / "handbook" / "index.md").write_text("# Index\n", encoding="utf-8")
        (self.root / "handbook" / "chapters" / "b.md").write_text("# B\n", encoding="utf-8")

    def test_a_link_to_a_missing_page_is_an_error(self):
        found = lint.check_links(self.root, "handbook/chapters/a.md", "[gone](missing.md)")
        self.assertIn("dead-link", codes(found))

    def test_a_link_to_a_sibling_chapter_resolves(self):
        self.assertEqual(lint.check_links(self.root, "handbook/chapters/a.md", "[b](b.md)"), [])

    def test_a_link_up_to_the_index_resolves(self):
        self.assertEqual(
            lint.check_links(self.root, "handbook/chapters/a.md", "[i](../index.md)"), []
        )

    def test_an_anchor_on_an_existing_page_resolves(self):
        self.assertEqual(
            lint.check_links(self.root, "handbook/chapters/a.md", "[b](b.md#part)"), []
        )

    def test_external_and_anchor_only_links_are_not_checked(self):
        text = "[x](https://example.com) [y](mailto:a@b.c) [z](#here)"
        self.assertEqual(lint.check_links(self.root, "handbook/chapters/a.md", text), [])

    def test_a_link_that_escapes_the_handbook_into_the_repo_resolves(self):
        (self.root / "docs").mkdir()
        (self.root / "docs" / "prd.md").write_text("x", encoding="utf-8")
        self.assertEqual(
            lint.check_links(self.root, "handbook/chapters/a.md", "[prd](../../docs/prd.md)"), []
        )


class ReferenceTest(unittest.TestCase):
    """The handbook is read by people outside the team, in one bound PDF.

    Sending them to another chapter, or to a requirement number they cannot
    look up, does not help them -- so both are errors, and both are
    machine-decidable.
    """

    def test_a_link_to_another_chapter_is_an_error(self):
        found = lint.check_references("chapters/a.md", "See [How It Works](02-how.md).")
        self.assertIn("cross-reference", codes(found))

    def test_the_finding_names_the_chapter_being_pointed_at(self):
        found = lint.check_references("chapters/a.md", "See [How It Works](02-how.md).")
        self.assertIn("How It Works", found[0].message)

    def test_a_link_out_of_the_repository_is_also_a_cross_reference(self):
        found = lint.check_references("chapters/a.md", "See [the runbook](../../docs/RUN.md).")
        self.assertIn("cross-reference", codes(found))

    def test_a_web_link_is_left_alone(self):
        self.assertEqual(
            lint.check_references("chapters/a.md", "See [the console](https://x.com)."), [])

    def test_a_file_path_in_backticks_is_not_a_reference(self):
        self.assertEqual(
            lint.check_references("chapters/a.md", "It lives in `docs/RUNBOOK.md`."), [])

    def test_a_picture_is_not_a_cross_reference(self):
        # `![caption](shot.png)` is content, not a pointer somewhere else.
        found = lint.check_references("chapters/a.md", "![The panel](../screens/p.png)")
        self.assertEqual(found, [])

    def test_a_picture_path_is_still_checked_for_existing(self):
        # The dead-link check must keep covering images, or a renamed
        # screenshot silently becomes a blank space in the PDF.
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "handbook" / "chapters").mkdir(parents=True)
            found = lint.check_links(root, "handbook/chapters/a.md", "![x](gone.png)")
            self.assertIn("dead-link", codes(found))

    def test_a_requirement_number_is_an_error(self):
        for text in ("as FR-5.4 requires", "see NFR-3.1", "architecture §3.7", "per ADR-012"):
            self.assertIn("spec-reference", codes(lint.check_references("a.md", text)), text)

    def test_an_unexplained_document_acronym_is_an_error(self):
        self.assertIn("spec-reference", codes(lint.check_references("a.md", "the PRD says so")))

    def test_the_generated_navigation_footer_is_not_a_cross_reference(self):
        # `build` writes those links itself, and they are stripped before the
        # PDF is typeset. Flagging them would make every chapter fail for a
        # thing no author wrote.
        page = ("# A\n\nProse.\n\n" + render.NAV_MARKER +
                "\n\n---\n\n[Contents](../index.md) · [Next](02-b.md) \u2192\n")
        self.assertEqual(lint.check_references("chapters/a.md", page), [])

    def test_a_reference_above_the_footer_is_still_caught(self):
        page = ("# A\n\nSee [B](02-b.md).\n\n" + render.NAV_MARKER +
                "\n\n[Contents](../index.md)\n")
        self.assertIn("cross-reference", codes(lint.check_references("chapters/a.md", page)))

    def test_ordinary_prose_passes(self):
        text = "The system listens to the meeting and offers a question."
        self.assertEqual(lint.check_references("chapters/a.md", text), [])

    def test_a_lint_allow_comment_permits_a_reference_on_that_page(self):
        text = "<!-- lint-allow: cross-reference -->\nSee [How](02-how.md)."
        self.assertEqual(lint.check_references("chapters/a.md", text), [])

    def test_a_section_sign_inside_a_code_span_is_not_a_reference(self):
        self.assertEqual(lint.check_references("a.md", "The doc comment reads `§3.7`."), [])


class FalseClaimTest(unittest.TestCase):
    def test_a_claim_this_repo_knows_to_be_untrue_is_an_error(self):
        found = lint.check_false_claims("chapters/a.md", "Run `./run.sh dev` to start.")
        self.assertIn("false-claim", codes(found))

    def test_a_lint_allow_comment_permits_the_claim_on_that_page_only(self):
        page = "<!-- lint-allow: run-sh -->\nRun `./run.sh dev` to start."
        self.assertEqual(lint.check_false_claims("chapters/a.md", page), [])

    def test_a_lint_allow_for_a_different_tag_does_not_permit_the_claim(self):
        page = "<!-- lint-allow: something-else -->\nRun `./run.sh dev` to start."
        self.assertIn("false-claim", codes(lint.check_false_claims("chapters/a.md", page)))

    def test_the_finding_names_the_tag_so_the_fix_is_obvious(self):
        found = lint.check_false_claims("chapters/a.md", "Run `./run.sh dev` to start.")
        self.assertIn("run-sh", found[0].message)

    def test_saying_formatting_is_not_gated_is_permitted(self):
        # The banned claim is "formatting is enforced". Stating the truth --
        # that it is not -- must not trip the same pattern, or the chapter
        # that documents reality is the one that fails CI.
        text = "Formatting is not gated: `cargo fmt --check` reports 328 hunks."
        self.assertEqual(lint.check_false_claims("chapters/a.md", text), [])

    def test_saying_formatting_is_enforced_is_still_an_error(self):
        text = "Formatting is enforced by CI on every pull request."
        self.assertIn("false-claim", codes(lint.check_false_claims("chapters/a.md", text)))

    def test_explaining_that_app_routes_under_reports_is_permitted(self):
        text = "Note that `app.routes` under-reports included routers here."
        self.assertEqual(lint.check_false_claims("chapters/a.md", text), [])

    def test_every_banned_claim_carries_a_reason(self):
        for claim in lint.BANNED_CLAIMS:
            self.assertTrue(claim.why.strip(), f"{claim.tag} has no reason")

    def test_no_banned_claim_fires_on_ordinary_prose(self):
        self.assertEqual(
            lint.check_false_claims("chapters/a.md", "The service exposes 42 routes.\n"), []
        )


if __name__ == "__main__":
    unittest.main()
