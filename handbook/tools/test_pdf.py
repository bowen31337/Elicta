"""Tests for the minimal PDF writer.

A PDF is a container format with a byte-offset cross-reference table at the
end. Get an offset wrong by one and every reader rejects the file, so the
tests here parse the output back rather than eyeballing it -- the xref
entries are checked against the objects they claim to point at.
"""

import re
import unittest

import pdf


def parse_xref(data: bytes):
    """Read the trailer's startxref and return the object offsets it lists."""
    tail = data[-200:]
    match = re.search(rb"startxref\s+(\d+)\s+%%EOF", tail)
    assert match, "no startxref/%%EOF trailer"
    start = int(match.group(1))
    section = data[start:]
    header = re.match(rb"xref\s+0 (\d+)\s+", section)
    assert header, "xref table does not open with a 0-based subsection"
    count = int(header.group(1))
    entries = re.findall(rb"(\d{10}) (\d{5}) ([nf])\s", section)[:count]
    return [(int(off), kind.decode()) for off, _, kind in entries]


class StructureTest(unittest.TestCase):
    def build(self, pages=1):
        doc = pdf.Document(*pdf.A4)
        for index in range(pages):
            page = doc.new_page()
            page.text(72, 700, f"Page {index}", "Helvetica", 12)
        return doc.render()

    def test_the_file_opens_with_a_pdf_header_and_closes_with_eof(self):
        data = self.build()
        self.assertTrue(data.startswith(b"%PDF-1."))
        self.assertTrue(data.rstrip().endswith(b"%%EOF"))

    def test_every_xref_offset_points_at_the_object_it_claims(self):
        data = self.build(pages=3)
        entries = parse_xref(data)
        self.assertEqual(entries[0][1], "f", "object 0 is always the free head")
        for number, (offset, kind) in enumerate(entries):
            if kind == "f":
                continue
            self.assertTrue(
                data[offset:].startswith(f"{number} 0 obj".encode()),
                f"xref entry {number} points at {data[offset:offset + 20]!r}",
            )

    def test_the_page_tree_counts_the_pages_it_holds(self):
        data = self.build(pages=4)
        self.assertIn(b"/Type /Pages", data)
        self.assertIn(b"/Count 4", data)

    def test_rendering_the_same_document_twice_gives_identical_bytes(self):
        self.assertEqual(self.build(pages=2), self.build(pages=2))

    def test_no_timestamp_leaks_into_the_output(self):
        # A CreationDate would make every build differ from the last, which
        # would defeat the reproducibility gate the handbook is checked by.
        self.assertNotIn(b"/CreationDate", self.build())

    def test_document_info_reaches_the_trailer(self):
        doc = pdf.Document(*pdf.A4)
        doc.new_page()
        doc.set_info(title="The Handbook", custom={"SourceDigest": "abc123"})
        data = doc.render()
        self.assertIn(b"/Title (The Handbook)", data)
        self.assertIn(b"/SourceDigest (abc123)", data)
        self.assertIn(b"/Info", data)


class TextEncodingTest(unittest.TestCase):
    def test_parentheses_and_backslashes_are_escaped(self):
        self.assertEqual(pdf.encode_text(r"a(b)c\d"), rb"a\(b\)c\\d")

    def test_windows_ansi_characters_survive_as_single_bytes(self):
        # The em dash and the section sign are in WinAnsi; they must not be
        # transliterated away.
        self.assertEqual(pdf.encode_text("—"), b"\x97")
        self.assertEqual(pdf.encode_text("§"), b"\xa7")

    def test_characters_outside_windows_ansi_are_transliterated(self):
        self.assertEqual(pdf.encode_text("→"), b"->")
        self.assertEqual(pdf.encode_text("←"), b"<-")
        self.assertEqual(pdf.encode_text("≤"), b"<=")

    def test_an_unmappable_character_becomes_a_question_mark_not_a_crash(self):
        self.assertEqual(pdf.encode_text("中"), b"?")

    def test_the_box_drawing_characters_the_env_file_uses_do_not_break_it(self):
        self.assertNotIn(b"\\u", pdf.encode_text("─" * 3))


class MetricsTest(unittest.TestCase):
    def test_an_empty_string_has_no_width(self):
        self.assertEqual(pdf.text_width("", "Helvetica", 10), 0)

    def test_courier_is_monospaced_at_six_tenths_of_the_point_size(self):
        self.assertAlmostEqual(pdf.text_width("abcd", "Courier", 10), 24.0, places=6)

    def test_helvetica_is_proportional(self):
        self.assertLess(
            pdf.text_width("i", "Helvetica", 10), pdf.text_width("m", "Helvetica", 10)
        )

    def test_bold_is_wider_than_regular_for_the_same_text(self):
        self.assertGreater(
            pdf.text_width("Handbook", "Helvetica-Bold", 10),
            pdf.text_width("Handbook", "Helvetica", 10),
        )

    def test_width_scales_linearly_with_point_size(self):
        self.assertAlmostEqual(
            pdf.text_width("Elicta", "Helvetica", 20),
            2 * pdf.text_width("Elicta", "Helvetica", 10),
            places=6,
        )

    def test_an_unknown_glyph_is_measured_rather_than_raising(self):
        self.assertGreater(pdf.text_width("中", "Helvetica", 10), 0)

    def test_every_declared_font_can_measure_the_printable_ascii_range(self):
        printable = "".join(chr(c) for c in range(32, 127))
        for name in pdf.FONTS:
            self.assertGreater(pdf.text_width(printable, name, 10), 0, name)


class DrawingTest(unittest.TestCase):
    def test_a_filled_rectangle_emits_a_fill_operator(self):
        doc = pdf.Document(*pdf.A4)
        doc.new_page().rect(10, 10, 100, 20, fill=(0.9, 0.9, 0.9))
        self.assertIn(b" re", doc.render())
        self.assertIn(b"\nf\n", doc.render())

    def test_a_link_annotation_lands_on_the_page_that_declared_it(self):
        doc = pdf.Document(*pdf.A4)
        page = doc.new_page()
        page.link(72, 700, 100, 12, target_page=0, target_y=500)
        data = doc.render()
        self.assertIn(b"/Annots", data)
        self.assertIn(b"/Link", data)

    def test_bookmarks_produce_an_outline_tree(self):
        doc = pdf.Document(*pdf.A4)
        doc.new_page()
        doc.new_page()
        doc.bookmark("Chapter One", page_index=0, y=800, level=0)
        doc.bookmark("A Section", page_index=1, y=700, level=1)
        data = doc.render()
        self.assertIn(b"/Type /Outlines", data)
        self.assertIn(b"(Chapter One)", data)
        self.assertIn(b"(A Section)", data)

    def test_a_document_with_no_bookmarks_omits_the_outline(self):
        doc = pdf.Document(*pdf.A4)
        doc.new_page()
        self.assertNotIn(b"/Outlines", doc.render())


if __name__ == "__main__":
    unittest.main()


class ShapeTest(unittest.TestCase):
    """Primitives the diagrams need: arrowheads and soft-cornered panels."""

    def page(self):
        doc = pdf.Document(*pdf.A4)
        return doc, doc.new_page()

    def test_a_polygon_fills_and_closes_its_path(self):
        doc, page = self.page()
        page.polygon([(10, 10), (20, 20), (10, 20)], fill=(0, 0, 0))
        content = doc.pages[0].content.decode("latin-1")
        self.assertIn("10 10 m", content)
        self.assertIn(" l", content)
        self.assertIn("\nh\nf\n", content, "the path must close before filling")

    def test_a_polygon_needs_at_least_three_points(self):
        doc, page = self.page()
        page.polygon([(10, 10), (20, 20)], fill=(0, 0, 0))
        self.assertNotIn(" m", doc.pages[0].content.decode("latin-1"))

    def test_a_rounded_rectangle_uses_curves(self):
        doc, page = self.page()
        page.round_rect(10, 10, 100, 40, radius=6, fill=(0.9, 0.9, 0.9))
        content = doc.pages[0].content.decode("latin-1")
        self.assertIn(" c", content, "no bezier operator, so the corners are square")
        self.assertIn("\nf\n", content)

    def test_a_zero_radius_rounded_rectangle_is_just_a_rectangle(self):
        doc, page = self.page()
        page.round_rect(10, 10, 100, 40, radius=0, fill=(0.9, 0.9, 0.9))
        self.assertIn(" re", doc.pages[0].content.decode("latin-1"))

    def test_the_radius_can_never_exceed_half_the_shorter_side(self):
        doc, page = self.page()
        page.round_rect(10, 10, 30, 20, radius=999, fill=(0, 0, 0))
        content = doc.pages[0].content.decode("latin-1")
        for value in re.findall(r"(-?\d+\.?\d*) (-?\d+\.?\d*) (?:m|l)", content):
            self.assertGreaterEqual(float(value[0]), 9.99)
            self.assertLessEqual(float(value[0]), 40.01)

    def test_a_stroked_rounded_rectangle_strokes_rather_than_fills(self):
        doc, page = self.page()
        page.round_rect(10, 10, 100, 40, radius=6, stroke=(0, 0, 0))
        self.assertIn("\nS\n", doc.pages[0].content.decode("latin-1"))

    def test_shapes_stay_deterministic(self):
        def build():
            doc = pdf.Document(*pdf.A4)
            page = doc.new_page()
            page.round_rect(10, 10, 100, 40, radius=6, fill=(0.5, 0.5, 0.5))
            page.polygon([(0, 0), (5, 5), (0, 10)], fill=(0, 0, 0))
            return doc.render()

        self.assertEqual(build(), build())


class ImageTest(unittest.TestCase):
    """Embedding pictures as PDF image objects."""

    def picture(self, predictor=True, colors=3):
        return pdf.images.Image(width=4, height=2, data=b"compressed-bytes",
                                colors=colors, predictor=predictor)

    def test_drawing_an_image_places_it_with_a_transform(self):
        doc = pdf.Document(*pdf.A4)
        doc.new_page().image(72, 600, 200, 100, self.picture())
        content = doc.pages[0].content.decode("latin-1")
        # Save state, scale and place, draw, restore -- in that order, or the
        # transform leaks into whatever is drawn next.
        self.assertRegex(content, r"(?s)^q\n200 0 0 100 72 600 cm\n/Im\d+ Do\nQ\n")

    def test_showing_only_the_top_of_an_image_clips_the_rest(self):
        doc = pdf.Document(*pdf.A4)
        doc.new_page().image(72, 600, 200, 100, self.picture(), show_fraction=0.5)
        content = doc.pages[0].content.decode("latin-1")
        self.assertIn("72 600 200 100 re", content)
        self.assertIn("W n", content, "no clipping path, so nothing is cropped")
        placed = re.search(r"200 0 0 ([\d.]+) 72 ([\d.-]+) cm", content)
        self.assertIsNotNone(placed, "the image was not placed")
        self.assertAlmostEqual(float(placed.group(1)), 200.0, places=1,
                               msg="the image should be drawn at twice the box height")
        self.assertAlmostEqual(float(placed.group(2)), 500.0, places=1,
                               msg="the top of the image should meet the top of the box")

    def test_showing_a_whole_image_uses_no_clipping_path(self):
        doc = pdf.Document(*pdf.A4)
        doc.new_page().image(72, 600, 200, 100, self.picture(), show_fraction=1.0)
        self.assertNotIn("W n", doc.pages[0].content.decode("latin-1"))

    def test_an_absurd_fraction_is_ignored_rather_than_dividing_by_zero(self):
        doc = pdf.Document(*pdf.A4)
        doc.new_page().image(72, 600, 200, 100, self.picture(), show_fraction=0.0)
        self.assertNotIn("W n", doc.pages[0].content.decode("latin-1"))

    def test_the_image_object_declares_its_size_and_colour_space(self):
        doc = pdf.Document(*pdf.A4)
        doc.new_page().image(0, 0, 10, 5, self.picture())
        data = doc.render()
        self.assertIn(b"/Subtype /Image", data)
        self.assertIn(b"/Width 4", data)
        self.assertIn(b"/Height 2", data)
        self.assertIn(b"/ColorSpace /DeviceRGB", data)

    def test_a_greyscale_image_declares_the_grey_colour_space(self):
        doc = pdf.Document(*pdf.A4)
        doc.new_page().image(0, 0, 10, 5, self.picture(colors=1))
        self.assertIn(b"/ColorSpace /DeviceGray", doc.render())

    def test_a_still_filtered_image_asks_pdf_to_undo_the_filtering(self):
        doc = pdf.Document(*pdf.A4)
        doc.new_page().image(0, 0, 10, 5, self.picture(predictor=True))
        data = doc.render()
        self.assertIn(b"/Predictor 15", data)
        self.assertIn(b"/Columns 4", data)

    def test_an_already_decoded_image_declares_no_predictor(self):
        doc = pdf.Document(*pdf.A4)
        doc.new_page().image(0, 0, 10, 5, self.picture(predictor=False))
        self.assertNotIn(b"/Predictor", doc.render())

    def test_the_same_picture_used_twice_is_stored_once(self):
        doc = pdf.Document(*pdf.A4)
        picture = self.picture()
        doc.new_page().image(0, 0, 10, 5, picture)
        doc.new_page().image(0, 0, 10, 5, picture)
        self.assertEqual(doc.render().count(b"/Subtype /Image"), 1)

    def test_a_page_that_draws_an_image_lists_it_in_its_resources(self):
        doc = pdf.Document(*pdf.A4)
        doc.new_page().image(0, 0, 10, 5, self.picture())
        self.assertIn(b"/XObject <<", doc.render())

    def test_a_page_with_no_images_declares_no_image_resources(self):
        doc = pdf.Document(*pdf.A4)
        doc.new_page().text(10, 10, "words", "Helvetica", 10)
        self.assertNotIn(b"/XObject", doc.render())

    def test_embedding_stays_deterministic(self):
        def build():
            doc = pdf.Document(*pdf.A4)
            doc.new_page().image(0, 0, 10, 5, self.picture())
            return doc.render()

        self.assertEqual(build(), build())
