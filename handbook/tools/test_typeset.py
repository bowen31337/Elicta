"""Tests for the typesetter: blocks in, paginated PDF out.

The properties worth pinning are the ones a reader notices when they fail
-- text running off the measure, a table wider than the page, a diagram
silently dropped -- plus the one CI depends on: the same content producing
the same bytes.
"""

import re
import unittest
from pathlib import Path

import book as bookmod
import images
import mdread
import typeset

ROOT = Path(__file__).resolve().parents[2]


class WrappingTest(unittest.TestCase):
    def setUp(self):
        self.theme = typeset.Theme()

    def wrap(self, text, width=200.0):
        spans = mdread.parse_inline(text)
        return typeset.wrap_spans(spans, width, self.theme.body_size, self.theme)

    def test_a_long_paragraph_wraps_onto_several_lines(self):
        text = "the reasoning happens before the meeting and the meeting only does selection"
        self.assertGreater(len(self.wrap(text)), 1)

    def test_no_wrapped_line_is_wider_than_the_measure(self):
        text = ("Elicta listens to a requirements meeting, tracks coverage against a "
                "template, catches ambiguity in the moment, and surfaces a follow-up "
                "question to the operator within the conversational window.")
        for line in self.wrap(text, width=180.0):
            self.assertLessEqual(typeset.line_width(line), 180.0 + 0.01)

    def test_a_single_word_longer_than_the_measure_is_broken_rather_than_looping(self):
        lines = self.wrap("supercalifragilisticexpialidocious" * 3, width=60.0)
        self.assertGreater(len(lines), 1)
        for line in lines:
            self.assertLessEqual(typeset.line_width(line), 60.0 + 0.01)

    def test_wrapping_preserves_every_word_of_the_text(self):
        text = "Mix `code`, **bold** and plain words across a narrow measure here."
        rebuilt = " ".join(
            "".join(frag.text for frag in line) for line in self.wrap(text, 120.0)
        )
        self.assertEqual(rebuilt.split(), text.replace("`", "").replace("**", "").split())

    def test_an_empty_span_list_wraps_to_nothing(self):
        self.assertEqual(typeset.wrap_spans([], 200.0, 10.0, self.theme), [])


class FontChoiceTest(unittest.TestCase):
    def test_a_code_span_is_set_in_a_monospaced_face(self):
        self.assertTrue(typeset.font_for(mdread.Span("x", code=True)).startswith("Courier"))

    def test_bold_and_italic_together_pick_the_bold_oblique_face(self):
        span = mdread.Span("x", bold=True, italic=True)
        self.assertEqual(typeset.font_for(span), "Helvetica-BoldOblique")

    def test_plain_text_is_set_in_the_roman_face(self):
        self.assertEqual(typeset.font_for(mdread.Span("x")), "Helvetica")


class DocumentTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.book = bookmod.load_book(ROOT)
        cls.data = typeset.render_pdf(ROOT, cls.book, digest="testdigest")
        cls.text = cls.data.decode("latin-1")

    def test_the_output_is_a_pdf(self):
        self.assertTrue(self.data.startswith(b"%PDF-"))
        self.assertTrue(self.data.rstrip().endswith(b"%%EOF"))

    def test_it_runs_to_more_pages_than_it_has_chapters(self):
        count = int(re.search(r"/Type /Pages /Kids \[[^\]]*\] /Count (\d+)", self.text).group(1))
        self.assertGreater(count, len(self.book.chapters))

    def test_the_source_digest_is_embedded_so_staleness_is_detectable(self):
        self.assertIn("/SourceDigest (testdigest)", self.text)

    def test_the_book_title_is_the_document_title(self):
        self.assertIn(f"/Title ({self.book.title})", self.text)

    def test_every_chapter_gets_an_outline_bookmark(self):
        self.assertIn("/Type /Outlines", self.text)
        for chapter in self.book.chapters:
            self.assertIn(f"/Title ({chapter.title})", self.text,
                          f"no bookmark for {chapter.id}")

    def test_rendering_twice_produces_identical_bytes(self):
        again = typeset.render_pdf(ROOT, self.book, digest="testdigest")
        self.assertEqual(self.data, again)

    def test_a_different_digest_changes_the_file(self):
        other = typeset.render_pdf(ROOT, self.book, digest="otherdigest")
        self.assertNotEqual(self.data, other)

    def test_the_title_page_shows_the_reader_no_file_paths(self):
        # The guide is for people who use the product. A path to the tool
        # that made the document means nothing to them.
        first_page = self.data.split(b"/Contents")[0]
        drawn = " ".join(re.findall(r"\((.*?)\) Tj", self.text[:12000]))
        for fragment in ("gen.py", "handbook/", "tools/", ".py"):
            self.assertNotIn(fragment, drawn, f"{fragment!r} reached the title page")

    def test_the_source_digest_stays_in_the_metadata_not_on_the_page(self):
        drawn = " ".join(re.findall(r"\((.*?)\) Tj", self.text[:12000]))
        self.assertNotIn("testdigest", drawn)
        self.assertIn("/SourceDigest (testdigest)", self.text)

    def test_the_document_is_not_absurdly_small(self):
        # 15 chapters and 1200 lines of Markdown cannot fit in a few KB; a
        # tiny file would mean the body silently failed to render.
        self.assertGreater(len(self.data), 40_000)


class BlockRenderingTest(unittest.TestCase):
    def render(self, markdown):
        theme = typeset.Theme()
        doc = typeset.pdf.Document(*theme.page)
        setter = typeset.Typesetter(doc, theme)
        setter.start_page()
        setter.render_blocks(mdread.parse(markdown))
        return doc, theme

    def test_a_code_block_stays_inside_the_measure(self):
        doc, theme = self.render("```bash\n" + "x" * 400 + "\n```\n")
        content = doc.pages[0].content.decode("latin-1")
        self.assertIn("Tj", content)
        for match in re.finditer(r"([\d.]+) ([\d.]+) Td", content):
            self.assertLess(float(match.group(1)), theme.page[0] - theme.margin_right)

    def test_a_table_wider_than_the_page_is_scaled_to_fit(self):
        head = "| " + " | ".join(["a very wide column heading indeed"] * 6) + " |\n"
        sep = "|" + "---|" * 6 + "\n"
        row = "| " + " | ".join(["some fairly long cell text here"] * 6) + " |\n"
        doc, theme = self.render(head + sep + row)
        for page in doc.pages:
            for match in re.finditer(r"([\d.]+) ([\d.]+) ([\d.]+) ([\d.]+) re",
                                     page.content.decode("latin-1")):
                right = float(match.group(1)) + float(match.group(3))
                self.assertLessEqual(right, theme.page[0] - theme.margin_right + 1)

    def _widths(self, markdown):
        theme = typeset.Theme()
        table = mdread.parse(markdown)[0]
        setter = typeset.Typesetter(typeset.pdf.Document(*theme.page), theme)
        return setter._column_widths(table), theme

    def test_a_narrow_column_is_not_starved_by_a_verbose_neighbour(self):
        # The crate reference has a short Path column beside a paragraph-long
        # description. Scaling every column by the same factor crushes Path
        # to four characters and hyphenates every value in it.
        head = "| Crate | Path | What it does |\n|---|---|---|\n"
        row = ("| `asr-live` | `core/crates/asr-live` | "
               + "a long description that runs on and on " * 12 + "|\n")
        widths, theme = self._widths(head + row)
        longest = typeset.pdf.text_width("core/crates/asr-live", "Helvetica",
                                         theme.table_size)
        self.assertGreaterEqual(widths[1], longest,
                                "the Path column cannot hold its longest value")

    def test_column_widths_always_add_up_to_the_measure(self):
        head = "| A | B | C |\n|---|---|---|\n| x | y | z |\n"
        widths, theme = self._widths(head)
        self.assertAlmostEqual(sum(widths), theme.measure, places=4)

    def test_a_table_of_only_long_prose_still_fits_the_measure(self):
        head = "| A | B |\n|---|---|\n"
        row = "| " + "word " * 80 + " | " + "other " * 80 + " |\n"
        widths, theme = self._widths(head + row)
        self.assertAlmostEqual(sum(widths), theme.measure, places=4)

    def test_a_column_is_measured_in_the_face_its_cells_are_actually_set_in(self):
        # `core/crates/asr-live` is a code span, so it is set in Courier,
        # which is wider than Helvetica at the same size. Measuring it in
        # the wrong face makes the column too narrow and every value in it
        # wraps mid-word.
        head = ("| Crate | Path | What it does |\n|---|---|---|\n"
                "| `a` | `core/crates/asr-live` | "
                + "a long description that runs on and on " * 12 + "|\n")
        widths, theme = self._widths(head)
        courier = typeset.pdf.text_width("core/crates/asr-live", "Courier",
                                         theme.table_size * 0.92)
        self.assertGreaterEqual(widths[1], courier + 2 * theme.cell_pad)

    def test_a_header_is_measured_in_the_bold_face_it_is_drawn_in(self):
        head = ("| Mounted | X | What it does |\n|---|---|---|\n"
                "| yes | x | " + "a long description that runs on and on " * 12 + "|\n")
        widths, theme = self._widths(head)
        bold = typeset.pdf.text_width("Mounted", "Helvetica-Bold", theme.table_size)
        self.assertGreaterEqual(widths[0], bold + 2 * theme.cell_pad)

    def test_a_mermaid_block_is_shown_as_source_rather_than_dropped(self):
        doc, _ = self.render("```mermaid\nflowchart TD\n  a --> b\n```\n")
        self.assertIn("flowchart TD", doc.pages[0].content.decode("latin-1"))

    def test_a_diagram_is_drawn_rather_than_printed_as_source(self):
        doc, _ = self.render(
            "```diagram\ntype: steps\ntitle: Around a meeting\n"
            "item: Before | It prepares.\nitem: During | It listens.\n```\n")
        content = doc.pages[0].content.decode("latin-1")
        self.assertIn("Around a meeting", content)
        self.assertNotIn("type: steps", content, "the source leaked onto the page")
        # Steps draw rounded badges, so the shape operator is a bezier path
        # rather than `re`; what proves something was painted is a fill.
        self.assertIn("\nf\n", content, "nothing was actually painted")

    def test_a_diagram_that_does_not_fit_moves_to_the_next_page(self):
        filler = "\n\n".join(f"Paragraph {i} of some length here." for i in range(48))
        diagram = ("```diagram\ntype: steps\ntitle: Marker Title\n"
                   + "".join(f"item: Step {i} | Some explanatory text.\n" for i in range(6))
                   + "```\n")
        doc, _ = self.render(filler + "\n\n" + diagram)
        pages = [p.content.decode("latin-1") for p in doc.pages]
        holder = [i for i, c in enumerate(pages) if "Marker Title" in c]
        self.assertEqual(len(holder), 1, "the diagram was drawn twice or not at all")

    def test_a_long_diagram_splits_rather_than_leaving_a_hole(self):
        filler = "\n\n".join(f"Paragraph {i} of some length here." for i in range(40))
        steps = ("```diagram\ntype: steps\ntitle: A Long Sequence\n"
                 + "".join(f"item: Stage {i} | Some explanatory text about it.\n"
                           for i in range(26))
                 + "```\n")
        doc, _ = self.render(filler + "\n\n" + steps)
        pages = [p.content.decode("latin-1") for p in doc.pages]
        carrying = [i for i, c in enumerate(pages) if "Stage 0)" in c or "Stage 25)" in c]
        self.assertGreaterEqual(len(set(carrying)), 2,
                                "the whole diagram jumped to one page")

    def test_every_item_of_a_split_diagram_is_drawn_exactly_once(self):
        filler = "\n\n".join(f"Paragraph {i} here." for i in range(40))
        steps = ("```diagram\ntype: steps\ntitle: A Long Sequence\n"
                 + "".join(f"item: Stage {i} | Explanatory text.\n" for i in range(26))
                 + "```\n")
        doc, _ = self.render(filler + "\n\n" + steps)
        whole = "".join(p.content.decode("latin-1") for p in doc.pages)
        for index in range(26):
            self.assertEqual(whole.count(f"Stage {index})"), 1, f"Stage {index}")

    def test_a_flow_is_never_split(self):
        filler = "\n\n".join(f"Paragraph {i} of some length here." for i in range(46))
        flow = ("```diagram\ntype: flow\ntitle: Chain\n"
                + "".join(f"item: Box {i}\n" for i in range(4)) + "```\n")
        doc, _ = self.render(filler + "\n\n" + flow)
        pages = [p.content.decode("latin-1") for p in doc.pages]
        holders = [i for i, c in enumerate(pages) if "Box 0" in c]
        self.assertEqual(len(holders), 1)
        self.assertIn("Box 3", pages[holders[0]], "the flow was broken up")

    def test_a_screenshot_is_embedded_as_a_picture(self):
        shots = ROOT / "docs" / "journeys" / "screenshots"
        shot = sorted(shots.glob("*.png"))[0]
        theme = typeset.Theme()
        doc = typeset.pdf.Document(*theme.page)
        setter = typeset.Typesetter(doc, theme, base_dir=shots)
        setter.start_page()
        setter.render_blocks(mdread.parse(f"![A screen]({shot.name})\n"))
        content = doc.pages[0].content.decode("latin-1")
        self.assertRegex(content, r"/Im\d+ Do")
        # Words are drawn as separate fragments, so reassemble before
        # looking for the caption.
        drawn = " ".join(re.findall(r"\((.*?)\) Tj", content))
        self.assertIn("A", drawn.split())
        self.assertIn("screen", drawn.split(), "the caption is missing")

    def test_a_missing_picture_leaves_a_visible_note_rather_than_crashing(self):
        theme = typeset.Theme()
        doc = typeset.pdf.Document(*theme.page)
        setter = typeset.Typesetter(doc, theme, base_dir=ROOT)
        setter.start_page()
        setter.render_blocks(mdread.parse("![Gone](no-such-file.png)\n"))
        content = doc.pages[0].content.decode("latin-1")
        self.assertNotIn("Do", content)
        self.assertIn("no-such-file.png", content,
                      "a missing picture vanished without trace")

    def test_a_picture_is_never_wider_than_the_measure(self):
        shots = ROOT / "docs" / "journeys" / "screenshots"
        shot = sorted(shots.glob("*.png"))[0]
        theme = typeset.Theme()
        doc = typeset.pdf.Document(*theme.page)
        setter = typeset.Typesetter(doc, theme, base_dir=shots)
        setter.start_page()
        setter.render_blocks(mdread.parse(f"![A screen]({shot.name})\n"))
        content = doc.pages[0].content.decode("latin-1")
        placed = re.search(r"([\d.]+) 0 0 ([\d.]+) ([\d.]+) ([\d.]+) cm", content)
        width, height = float(placed.group(1)), float(placed.group(2))
        self.assertLessEqual(width, theme.measure + 0.5)
        self.assertLess(height, theme.page[1] - theme.margin_top)

    def _place(self, name):
        shots = ROOT / "docs" / "journeys" / "screenshots"
        theme = typeset.Theme()
        doc = typeset.pdf.Document(*theme.page)
        setter = typeset.Typesetter(doc, theme, base_dir=shots)
        setter.start_page()
        setter.render_blocks(mdread.parse(f"![Shot]({name})\n"))
        return doc.pages[0].content.decode("latin-1"), theme

    def test_a_mostly_empty_panel_is_cropped_rather_than_shown_blank(self):
        content, theme = self._place("panel-nudge-surfaced.png")
        box = re.search(r"([\d.]+) ([\d.]+) ([\d.]+) ([\d.]+) re\nW n", content)
        self.assertIsNotNone(box, "a mostly-empty panel should be cropped")
        width, height = float(box.group(3)), float(box.group(4))
        picture = images.read_png(
            ROOT / "docs" / "journeys" / "screenshots" / "panel-nudge-surfaced.png")
        self.assertLess(height, width * picture.aspect * 0.8,
                        "the blank half of the panel is still being shown")
        self.assertLessEqual(width, theme.measure + 0.5)
        placed = re.search(r"[\d.]+ 0 0 ([\d.]+) ", content)
        self.assertGreater(float(placed.group(1)), height,
                           "the image is not drawn taller than the window it shows through")

    def test_a_genuinely_tall_screenshot_is_held_back_from_the_full_measure(self):
        # This one has no blank tail, so it stays taller than it is wide and
        # the portrait rule applies: run edge to edge it would read as a
        # full-screen application, which it is not.
        content, theme = self._place("settings-configured.png")
        placed = re.search(r"([\d.]+) 0 0 ([\d.]+) ", content)
        self.assertLess(float(placed.group(1)), theme.measure * 0.9)

    def test_a_diagram_stays_inside_the_measure(self):
        doc, theme = self.render(
            "```diagram\ntype: compare\ntitle: Two speeds\nleft: Fast\nright: Slow\n"
            "item: How long | Under a tenth of a second | About a minute\n```\n")
        content = doc.pages[0].content.decode("latin-1")
        for a, b, w, h in re.findall(
                r"(-?[\d.]+) (-?[\d.]+) (-?[\d.]+) (-?[\d.]+) re", content):
            self.assertLessEqual(float(a) + float(w), theme.page[0] - theme.margin_right + 1)
            self.assertGreaterEqual(float(a), theme.margin_left - 1)

    def test_a_very_long_document_spills_onto_further_pages(self):
        doc, _ = self.render(
            "\n\n".join(f"Paragraph number {i} with some text in it." for i in range(200))
        )
        self.assertGreater(len(doc.pages), 1)

    def test_a_table_that_outgrows_the_page_repeats_its_header(self):
        head = "| Name | Meaning |\n|---|---|\n"
        rows = "".join(f"| row {i} | some explanatory text |\n" for i in range(120))
        doc, _ = self.render(head + rows)
        self.assertGreater(len(doc.pages), 1)
        for page in doc.pages:
            self.assertIn("Meaning", page.content.decode("latin-1"))


if __name__ == "__main__":
    unittest.main()
