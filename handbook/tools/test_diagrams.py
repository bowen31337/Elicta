"""Tests for the diagram engine.

Diagrams are declared in the chapters as fenced ```diagram blocks and drawn
as real pictures. The properties that matter: a diagram never draws outside
the space it was given, its height is known before it is drawn (so the
paginator can decide), and a diagram it cannot understand is shown as
readable text rather than dropped.
"""

import re
import unittest
from textwrap import dedent

import diagrams
import pdf


def parse(text):
    return diagrams.parse(dedent(text).strip().splitlines())


STEPS = """
    type: steps
    title: What happens around a meeting
    caption: The same three stages every time.
    item: Before | The system reads the material you already have.
    item: During | It listens and offers one question at a time.
    item: After | It writes up what was agreed.
"""

TIMELINE = """
    type: timeline
    title: The pause after someone says something vague
    item: Waiting for the words | 650 | slow
    item: Noticing the vague word | 5
    item: Choosing the question | 30
"""

COMPARE = """
    type: compare
    title: Two speeds
    left: The fast path
    right: The slower path
    item: How long it takes | Under a tenth of a second | About a minute
    item: Asks a language model? | No | Yes
"""

FLOW = """
    type: flow
    title: From speech to suggestion
    item: Someone speaks
    item: Words appear
    item: A gap is noticed
    item: A question is offered
"""

STACK = """
    type: stack
    title: What it is made of
    item: What you see | The panel during the meeting
    item: What decides | Matching and ranking
    item: What listens | Audio and transcription
"""


class ParsingTest(unittest.TestCase):
    def test_the_type_title_and_caption_are_read(self):
        diagram = parse(STEPS)
        self.assertEqual(diagram.kind, "steps")
        self.assertEqual(diagram.title, "What happens around a meeting")
        self.assertEqual(diagram.caption, "The same three stages every time.")

    def test_items_split_on_pipes(self):
        diagram = parse(STEPS)
        self.assertEqual(len(diagram.items), 3)
        self.assertEqual(diagram.items[0].parts[0], "Before")
        self.assertIn("reads the material", diagram.items[0].parts[1])

    def test_a_missing_caption_is_empty_rather_than_absent(self):
        self.assertEqual(parse(FLOW).caption, "")

    def test_named_fields_are_available_to_the_type_that_wants_them(self):
        diagram = parse(COMPARE)
        self.assertEqual(diagram.fields["left"], "The fast path")
        self.assertEqual(diagram.fields["right"], "The slower path")

    def test_a_trailing_flag_on_an_item_is_kept(self):
        self.assertEqual(parse(TIMELINE).items[0].parts[2], "slow")

    def test_an_unknown_type_is_still_parsed_so_it_can_be_shown_as_text(self):
        diagram = parse("type: sculpture\ntitle: Hm\nitem: a | b")
        self.assertEqual(diagram.kind, "sculpture")
        self.assertFalse(diagrams.is_known(diagram))

    def test_a_block_with_no_type_is_not_a_known_diagram(self):
        self.assertFalse(diagrams.is_known(parse("item: a")))

    def test_every_type_the_handbook_uses_is_known(self):
        for source in (STEPS, TIMELINE, COMPARE, FLOW, STACK):
            self.assertTrue(diagrams.is_known(parse(source)), parse(source).kind)


class LayoutTest(unittest.TestCase):
    MEASURE = 467.0

    def plan(self, source):
        return diagrams.plan(parse(source), diagrams.DiagramStyle(), self.MEASURE)

    def test_every_type_reports_a_positive_height_before_being_drawn(self):
        for source in (STEPS, TIMELINE, COMPARE, FLOW, STACK):
            self.assertGreater(self.plan(source).height, 0, parse(source).kind)

    def test_more_steps_make_a_taller_diagram(self):
        short = self.plan(STEPS).height
        longer = self.plan(STEPS + "    item: Later | And then some more text.\n").height
        self.assertGreater(longer, short)

    def test_a_longer_label_makes_a_step_taller(self):
        plain = self.plan(STEPS).height
        wordy = self.plan(STEPS.replace(
            "It writes up what was agreed.",
            "It writes up what was agreed, " + "in considerable detail, " * 12)).height
        self.assertGreater(wordy, plain)

    def test_the_height_is_the_same_whether_or_not_it_has_been_drawn(self):
        plan = self.plan(TIMELINE)
        before = plan.height
        doc = pdf.Document(*pdf.A4)
        plan.draw(doc.new_page(), 64.0, 700.0)
        self.assertEqual(plan.height, before)


class SplittingTest(unittest.TestCase):
    """A diagram that will not fit should break between its items rather
    than jump whole to the next page and leave a hole behind it."""

    MEASURE = 467.0

    def test_row_based_kinds_may_split_and_others_may_not(self):
        self.assertTrue(diagrams.can_split(parse(STEPS)))
        self.assertTrue(diagrams.can_split(parse(COMPARE)))
        self.assertTrue(diagrams.can_split(parse(STACK)))
        self.assertFalse(diagrams.can_split(parse(FLOW)))
        self.assertFalse(diagrams.can_split(parse(TIMELINE)))

    def test_a_subset_keeps_the_items_it_was_given(self):
        whole = parse(STEPS)
        part = diagrams.subset(whole, whole.items[:2], keep_title=True, keep_caption=False)
        self.assertEqual(len(part.items), 2)
        self.assertEqual(part.title, whole.title)
        self.assertEqual(part.caption, "")

    def test_a_later_subset_drops_the_title_so_it_is_not_repeated(self):
        whole = parse(STEPS)
        part = diagrams.subset(whole, whole.items[2:], keep_title=False, keep_caption=True)
        self.assertEqual(part.title, "")
        self.assertEqual(part.caption, whole.caption)

    def test_generous_space_fits_every_item(self):
        whole = parse(STEPS)
        self.assertEqual(
            diagrams.fit_count(whole, whole.items, diagrams.DiagramStyle(),
                               self.MEASURE, 900.0, keep_title=True),
            len(whole.items))

    def test_tight_space_fits_only_some(self):
        whole = parse(STEPS)
        count = diagrams.fit_count(whole, whole.items, diagrams.DiagramStyle(),
                                   self.MEASURE, 90.0, keep_title=True)
        self.assertGreater(count, 0)
        self.assertLess(count, len(whole.items))

    def test_no_space_at_all_fits_nothing(self):
        whole = parse(STEPS)
        self.assertEqual(
            diagrams.fit_count(whole, whole.items, diagrams.DiagramStyle(),
                               self.MEASURE, 5.0, keep_title=True),
            0)

    def test_a_kind_that_cannot_split_reports_all_or_nothing(self):
        whole = parse(FLOW)
        self.assertEqual(
            diagrams.fit_count(whole, whole.items, diagrams.DiagramStyle(),
                               self.MEASURE, 40.0, keep_title=True),
            0, "a flow was allowed to split")


class DrawingTest(unittest.TestCase):
    MEASURE = 467.0
    LEFT = 64.0
    TOP = 760.0

    def draw(self, source):
        style = diagrams.DiagramStyle()
        plan = diagrams.plan(parse(source), style, self.MEASURE)
        doc = pdf.Document(*pdf.A4)
        page = doc.new_page()
        plan.draw(page, self.LEFT, self.TOP)
        return page.content.decode("latin-1"), plan

    def coordinates(self, content):
        """Every point the content stream actually touches.

        A rectangle is `x y w h re`, so both its corners have to be derived
        rather than read off the last two numbers -- doing that was how an
        earlier version of this test passed a diagram that drew off-page.
        """
        points = []
        for a, b, w, h in re.findall(
                r"(-?\d+\.?\d*) (-?\d+\.?\d*) (-?\d+\.?\d*) (-?\d+\.?\d*) re",
                content):
            x, y, width, height = float(a), float(b), float(w), float(h)
            points += [(x, y), (x + width, y + height)]
        points += [(float(a), float(b)) for a, b in
                   re.findall(r"(-?\d+\.?\d*) (-?\d+\.?\d*) (?:m|l|Td)\b", content)]
        return points

    def test_nothing_is_drawn_outside_the_measure(self):
        for source in (STEPS, TIMELINE, COMPARE, FLOW, STACK):
            content, _ = self.draw(source)
            for x, _y in self.coordinates(content):
                self.assertGreaterEqual(x, self.LEFT - 0.5, parse(source).kind)
                self.assertLessEqual(x, self.LEFT + self.MEASURE + 0.5, parse(source).kind)

    def test_nothing_is_drawn_below_the_height_it_declared(self):
        for source in (STEPS, TIMELINE, COMPARE, FLOW, STACK):
            content, plan = self.draw(source)
            for _x, y in self.coordinates(content):
                self.assertLessEqual(y, self.TOP + 0.5, parse(source).kind)
                self.assertGreaterEqual(y, self.TOP - plan.height - 1.0, parse(source).kind)

    def test_a_flow_draws_arrowheads_between_its_boxes(self):
        content, _ = self.draw(FLOW)
        self.assertIn("\nh\nf\n", content, "no filled closed path, so no arrowhead")

    def test_a_timeline_band_is_proportional_to_its_number(self):
        content, _ = self.draw(TIMELINE)
        widths = [float(w) for _x, _y, w, _h in
                  re.findall(r"(-?\d+\.?\d*) (-?\d+\.?\d*) (\d+\.?\d*) (\d+\.?\d*) re", content)]
        bands = sorted(widths, reverse=True)[:3]
        self.assertGreater(bands[0], bands[1] * 3,
                           "the 650-unit band should dwarf the 30-unit one")

    def test_adjacent_bands_are_separated_so_they_do_not_read_as_one(self):
        # Three small bands of the same colour, drawn touching, look like a
        # single band. The eye needs the seam.
        content, _ = self.draw(TIMELINE)
        rects = [(float(x), float(w), float(h)) for x, _y, w, h in re.findall(
            r"(-?[\d.]+) (-?[\d.]+) ([\d.]+) ([\d.]+) re", content)]
        # The bands are the rectangles sharing the bar's height; picking the
        # three widest instead catches a legend swatch.
        tallest = max(h for _x, _w, h in rects)
        edges = sorted([(x, w) for x, w, h in rects if h == tallest])
        self.assertEqual(len(edges), 3, "expected one rectangle per band")
        for (left, width), (next_left, _) in zip(edges, edges[1:]):
            self.assertGreater(next_left - (left + width), 0.4,
                               "bands are touching")

    def test_a_wide_band_carries_its_own_label(self):
        content, _ = self.draw(TIMELINE)
        # "Waiting for the words" takes 92% of the bar; there is room.
        self.assertGreaterEqual(content.count("Waiting for the words"), 2,
                                "the label appears only in the legend")

    def test_a_narrow_band_does_not_have_a_label_crammed_into_it(self):
        content, _ = self.draw(TIMELINE)
        self.assertEqual(content.count("Choosing the question"), 1,
                         "a label was drawn into a band too small to hold it")

    def test_every_item_label_reaches_the_page(self):
        for source in (STEPS, COMPARE, FLOW, STACK):
            content, _ = self.draw(source)
            for item in parse(source).items:
                first_word = item.parts[0].split()[0]
                self.assertIn(first_word, content, f"{parse(source).kind}: {first_word}")

    def test_the_title_reaches_the_page(self):
        content, _ = self.draw(STEPS)
        self.assertIn("What happens around a meeting", content)

    def test_an_unknown_type_is_drawn_as_readable_text(self):
        content, plan = self.draw("type: sculpture\ntitle: Marble\nitem: chisel | stone")
        self.assertGreater(plan.height, 0)
        self.assertIn("chisel", content)

    def test_drawing_is_deterministic(self):
        first, _ = self.draw(COMPARE)
        second, _ = self.draw(COMPARE)
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
