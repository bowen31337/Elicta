"""Tests for the Markdown reader.

Only the subset the handbook's own STYLE.md permits is supported, and the
reader is deliberately strict about it: an unsupported construct should
come out as visible plain text, never silently vanish from the PDF.
"""

import unittest
from textwrap import dedent

import mdread


def parse(text):
    return mdread.parse(dedent(text).lstrip("\n"))


class BlockTest(unittest.TestCase):
    def test_hashes_become_headings_at_their_level(self):
        blocks = parse("# One\n\n## Two\n\n### Three\n")
        self.assertEqual([(b.level, b.spans[0].text) for b in blocks],
                         [(1, "One"), (2, "Two"), (3, "Three")])

    def test_wrapped_lines_join_into_one_paragraph(self):
        blocks = parse("A sentence that runs\nacross two source lines.\n")
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0].spans[0].text, "A sentence that runs across two source lines.")

    def test_a_blank_line_separates_paragraphs(self):
        self.assertEqual(len(parse("First.\n\nSecond.\n")), 2)

    def test_a_fenced_block_keeps_its_language_and_its_lines_verbatim(self):
        blocks = parse("```bash\ncd handbook\n  indented\n```\n")
        self.assertIsInstance(blocks[0], mdread.CodeBlock)
        self.assertEqual(blocks[0].lang, "bash")
        self.assertEqual(blocks[0].lines, ["cd handbook", "  indented"])

    def test_a_hash_inside_a_fence_is_not_a_heading(self):
        blocks = parse("```bash\n# a comment\n```\n")
        self.assertEqual(len(blocks), 1)
        self.assertIsInstance(blocks[0], mdread.CodeBlock)

    def test_a_mermaid_fence_is_its_own_block_kind(self):
        blocks = parse("```mermaid\nflowchart TD\n  a --> b\n```\n")
        self.assertIsInstance(blocks[0], mdread.Mermaid)
        self.assertEqual(blocks[0].lines[0], "flowchart TD")

    def test_a_diagram_fence_becomes_a_diagram_block(self):
        blocks = parse("```diagram\ntype: steps\ntitle: How it goes\nitem: One | first\n```\n")
        self.assertIsInstance(blocks[0], mdread.DiagramBlock)
        self.assertEqual(blocks[0].diagram.kind, "steps")
        self.assertEqual(blocks[0].diagram.title, "How it goes")

    def test_a_diagram_fence_is_not_mistaken_for_code(self):
        blocks = parse("```diagram\ntype: flow\nitem: a\n```\n")
        self.assertNotIsInstance(blocks[0], mdread.CodeBlock)

    def test_a_line_that_is_only_a_picture_becomes_an_image_block(self):
        blocks = parse("![The panel before a meeting](shots/panel.png)\n")
        self.assertIsInstance(blocks[0], mdread.ImageBlock)
        self.assertEqual(blocks[0].path, "shots/panel.png")
        self.assertEqual(blocks[0].caption, "The panel before a meeting")

    def test_a_picture_between_paragraphs_is_its_own_block(self):
        blocks = parse("Before.\n\n![Shot](a.png)\n\nAfter.\n")
        self.assertEqual([type(b).__name__ for b in blocks],
                         ["Paragraph", "ImageBlock", "Paragraph"])

    def test_a_picture_mentioned_inside_a_sentence_stays_in_the_sentence(self):
        blocks = parse("See ![this](a.png) here.\n")
        self.assertIsInstance(blocks[0], mdread.Paragraph)

    def test_a_picture_with_no_caption_is_still_a_picture(self):
        blocks = parse("![](a.png)\n")
        self.assertIsInstance(blocks[0], mdread.ImageBlock)
        self.assertEqual(blocks[0].caption, "")

    def test_a_dash_rule_becomes_a_rule(self):
        self.assertIsInstance(parse("Text.\n\n---\n\nMore.\n")[1], mdread.Rule)

    def test_a_blockquote_becomes_a_quote_block(self):
        blocks = parse("> Never edit a generated chapter.\n> The build reverts it.\n")
        self.assertIsInstance(blocks[0], mdread.Quote)
        self.assertIn("reverts", blocks[0].blocks[0].spans[-1].text)


class ListTest(unittest.TestCase):
    def test_dashes_become_an_unordered_list(self):
        blocks = parse("- first\n- second\n")
        self.assertIsInstance(blocks[0], mdread.ListBlock)
        self.assertFalse(blocks[0].ordered)
        self.assertEqual(len(blocks[0].items), 2)

    def test_numbers_become_an_ordered_list_keeping_their_markers(self):
        blocks = parse("1. first\n2. second\n")
        self.assertTrue(blocks[0].ordered)
        self.assertEqual([item.marker for item in blocks[0].items], ["1.", "2."])

    def test_an_indented_item_records_its_nesting_level(self):
        blocks = parse("- top\n  - nested\n")
        self.assertEqual([item.level for item in blocks[0].items], [0, 1])

    def test_a_continuation_line_joins_the_item_it_belongs_to(self):
        blocks = parse("- an item that wraps\n  onto the next line\n- second\n")
        self.assertEqual(blocks[0].items[0].spans[0].text,
                         "an item that wraps onto the next line")
        self.assertEqual(len(blocks[0].items), 2)


class TableTest(unittest.TestCase):
    SOURCE = """
    | Command | What it does |
    |---|---|
    | `build` | Regenerates |
    | `check` | Fails on errors |
    """

    def test_the_header_row_is_separated_from_the_body(self):
        table = parse(self.SOURCE)[0]
        self.assertIsInstance(table, mdread.Table)
        self.assertEqual([cell[0].text for cell in table.headers], ["Command", "What it does"])
        self.assertEqual(len(table.rows), 2)

    def test_cells_carry_inline_formatting(self):
        table = parse(self.SOURCE)[0]
        self.assertTrue(table.rows[0][0][0].code)

    def test_an_escaped_pipe_entity_becomes_a_pipe_in_the_cell(self):
        table = parse("| A |\n|---|\n| a &#124; b |\n")[0]
        self.assertEqual(table.rows[0][0][0].text, "a | b")

    def test_a_rule_line_outside_a_table_is_not_mistaken_for_a_separator(self):
        blocks = parse("Text.\n\n---\n")
        self.assertNotIsInstance(blocks[-1], mdread.Table)


class InlineTest(unittest.TestCase):
    def spans(self, text):
        return parse(text)[0].spans

    def test_backticks_mark_a_code_span(self):
        spans = self.spans("Run `gen.py build` now.\n")
        self.assertEqual([s.code for s in spans], [False, True, False])
        self.assertEqual(spans[1].text, "gen.py build")

    def test_double_asterisks_mark_bold(self):
        spans = self.spans("This is **important** text.\n")
        self.assertTrue(spans[1].bold)
        self.assertEqual(spans[1].text, "important")

    def test_single_asterisks_mark_italic(self):
        spans = self.spans("This is *emphasis* here.\n")
        self.assertTrue(spans[1].italic)

    def test_underscores_mark_italic(self):
        # render.py writes `_no module doc_` for a crate with no doc
        # comment; leaving the underscores on the page looks like a bug in
        # the generator rather than a gap in the source.
        spans = self.spans("The cell says _no module doc_ here.\n")
        italic = [s for s in spans if s.italic]
        self.assertEqual(italic[0].text, "no module doc")
        self.assertEqual("".join(s.text for s in spans), "The cell says no module doc here.")

    def test_underscores_inside_an_identifier_are_left_alone(self):
        spans = self.spans("Set ELICTA_SETTINGS_DB and MODEL_FAST now.\n")
        self.assertFalse(any(s.italic for s in spans))
        self.assertEqual("".join(s.text for s in spans),
                         "Set ELICTA_SETTINGS_DB and MODEL_FAST now.")

    def test_a_link_keeps_its_text_and_its_target(self):
        spans = self.spans("See [the runbook](../../docs/RUNBOOK.md) for more.\n")
        self.assertEqual(spans[1].text, "the runbook")
        self.assertEqual(spans[1].href, "../../docs/RUNBOOK.md")

    def test_formatting_inside_a_link_survives(self):
        spans = self.spans("See [**bold link**](x.md).\n")
        linked = [s for s in spans if s.href]
        self.assertTrue(linked[0].bold)

    def test_bold_survives_an_asterisk_in_its_content(self):
        # `**`core/crates/*`**` is real prose in chapter 2: a glob inside a
        # code span inside bold. A bold pattern that forbids any asterisk
        # leaves the ** markers on the page.
        spans = self.spans("See **`core/crates/*`** for that.\n")
        rebuilt = "".join(s.text for s in spans)
        self.assertNotIn("**", rebuilt)
        self.assertEqual(rebuilt, "See core/crates/* for that.")
        starred = [s for s in spans if s.text == "core/crates/*"]
        self.assertTrue(starred[0].bold and starred[0].code)

    def test_two_bold_runs_on_one_line_stay_separate(self):
        spans = self.spans("**first** middle **second**\n")
        bold = [s.text for s in spans if s.bold]
        self.assertEqual(bold, ["first", "second"])
        self.assertEqual("".join(s.text for s in spans), "first middle second")

    def test_an_unpaired_double_asterisk_is_left_as_text(self):
        self.assertEqual("".join(s.text for s in self.spans("a ** b\n")), "a ** b")

    def test_asterisks_inside_a_code_span_are_literal(self):
        spans = self.spans("Use `a * b` here.\n")
        self.assertEqual(spans[1].text, "a * b")
        self.assertTrue(spans[1].code)

    def test_all_of_a_paragraphs_text_survives_span_splitting(self):
        source = "Mix `code`, **bold**, *italic* and [a link](x.md) together.\n"
        rebuilt = "".join(s.text for s in self.spans(source))
        self.assertEqual(rebuilt, "Mix code, bold, italic and a link together.")


class StrippingTest(unittest.TestCase):
    def test_html_comments_are_removed(self):
        blocks = parse("<!-- lint-allow: run-sh -->\n\nReal text.\n")
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0].spans[0].text, "Real text.")

    def test_everything_from_the_nav_marker_down_is_dropped(self):
        source = "# Chapter\n\nBody.\n\n<!-- HANDBOOK-NAV -->\n\n---\n\n[Contents](../index.md)\n"
        rendered = [b for b in parse(source)]
        self.assertEqual(len(rendered), 2)
        self.assertNotIsInstance(rendered[-1], mdread.Rule)

    def test_the_generated_banner_is_dropped_but_the_body_is_not(self):
        source = "<!-- HANDBOOK-GENERATED: do not edit by hand -->\n\n# Crates\n\nBody.\n"
        blocks = parse(source)
        self.assertEqual(blocks[0].level, 1)
        self.assertEqual(len(blocks), 2)


    def test_a_html_comment_inside_a_code_span_is_not_stripped(self):
        # Chapter 30 tells readers to add `<!-- lint-allow: <tag> -->`.
        # Stripping comments before inline parsing guts that sentence.
        blocks = parse("Add `<!-- lint-allow: run-sh -->` to that page.\n")
        rebuilt = "".join(s.text for s in blocks[0].spans)
        self.assertEqual(rebuilt, "Add <!-- lint-allow: run-sh --> to that page.")

    def test_a_comment_inside_a_fenced_block_survives(self):
        blocks = parse("```html\n<!-- keep me -->\n```\n")
        self.assertEqual(blocks[0].lines, ["<!-- keep me -->"])

    def test_a_quoted_nav_marker_does_not_truncate_the_chapter(self):
        source = "Prose owns everything above `<!-- HANDBOOK-NAV -->`.\n\nMore text.\n"
        self.assertEqual(len(parse(source)), 2)

    def test_the_real_nav_footer_is_still_dropped(self):
        source = "Body.\n\n<!-- HANDBOOK-NAV -->\n\nFooter text.\n"
        blocks = parse(source)
        self.assertEqual(len(blocks), 1)


class RealChapterTest(unittest.TestCase):
    def test_every_chapter_in_this_repo_parses_into_blocks(self):
        from pathlib import Path

        chapters = sorted((Path(__file__).resolve().parents[1] / "chapters").glob("*.md"))
        self.assertGreaterEqual(len(chapters), 15)
        for chapter in chapters:
            blocks = mdread.parse(chapter.read_text(encoding="utf-8"))
            self.assertTrue(blocks, chapter.name)
            self.assertIsInstance(blocks[0], mdread.Heading, chapter.name)
            self.assertEqual(blocks[0].level, 1, chapter.name)


if __name__ == "__main__":
    unittest.main()
