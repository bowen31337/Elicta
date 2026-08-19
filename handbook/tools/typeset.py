"""Typesetting: a block tree in, a paginated PDF out.

The layout model is deliberately single-pass and greedy -- one column, one
measure, no floats, no hyphenation. What it does take seriously is the
handful of things a reader notices immediately when they are wrong:

* nothing is ever drawn outside the measure (a word too long for the line
  is broken rather than allowed to run off the page);
* a table wider than the page is scaled down, not clipped;
* a table that outgrows the page repeats its header on the next one;
* a mermaid diagram, which cannot be drawn here, is shown as its source
  rather than silently dropped.

The whole document is a pure function of its inputs, which is what lets the
build be gated on producing no diff.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from pathlib import Path

import diagrams
import images
import mdread
import pdf


@dataclass(frozen=True)
class Theme:
    page: tuple = pdf.A4
    margin_left: float = 64.0
    margin_right: float = 64.0
    margin_top: float = 68.0
    margin_bottom: float = 56.0

    body_size: float = 9.6
    body_leading: float = 13.6
    code_size: float = 8.2
    code_leading: float = 10.8
    table_size: float = 8.5
    table_leading: float = 11.4
    small_size: float = 7.4

    h1_size: float = 21.0
    h2_size: float = 13.4
    h3_size: float = 10.6

    ink: tuple = (0.11, 0.11, 0.12)
    muted: tuple = (0.46, 0.47, 0.50)
    rule: tuple = (0.85, 0.86, 0.88)
    accent: tuple = (0.13, 0.24, 0.55)
    code_ink: tuple = (0.17, 0.19, 0.26)
    code_bg: tuple = (0.963, 0.969, 0.980)
    band: tuple = (0.930, 0.940, 0.958)

    cell_pad: float = 5.0
    code_pad: float = 7.0

    @property
    def measure(self) -> float:
        return self.page[0] - self.margin_left - self.margin_right

    def diagram_style(self) -> diagrams.DiagramStyle:
        """Diagrams borrow the document's palette, so they never look
        pasted in from somewhere else."""
        return diagrams.DiagramStyle(
            ink=self.ink, muted=self.muted, rule=self.rule,
            accent=self.accent, panel=self.code_bg, band=self.band,
        )

    @property
    def content_top(self) -> float:
        return self.page[1] - self.margin_top

    @property
    def content_bottom(self) -> float:
        return self.margin_bottom + 14.0


# ── Fragments and wrapping ───────────────────────────────────────────────


@dataclass(frozen=True)
class Frag:
    text: str
    font: str
    size: float
    color: tuple
    href: str = ""


def font_for(span: mdread.Span) -> str:
    if span.code:
        return "Courier-Bold" if span.bold else "Courier"
    if span.bold and span.italic:
        return "Helvetica-BoldOblique"
    if span.bold:
        return "Helvetica-Bold"
    if span.italic:
        return "Helvetica-Oblique"
    return "Helvetica"


def size_for(span: mdread.Span, base: float) -> float:
    # Courier runs optically large beside Helvetica at the same point size.
    return base * 0.92 if span.code else base


def color_for(span: mdread.Span, theme: Theme) -> tuple:
    if span.href:
        return theme.accent
    if span.code:
        return theme.code_ink
    return theme.ink


def frag_width(frag: Frag) -> float:
    return pdf.text_width(frag.text, frag.font, frag.size)


def line_width(line: list[Frag]) -> float:
    return sum(frag_width(frag) for frag in line)


def _words(spans: list[mdread.Span], size: float, theme: Theme) -> list[list[Frag]]:
    """Group spans into whitespace-delimited words, keeping styles.

    Splitting per span rather than per word is what lets a single word
    carry more than one style -- `**bold**text` is one word, two frags,
    and must never be broken between them by the line breaker.
    """
    words: list[list[Frag]] = []
    current: list[Frag] = []
    for span in spans:
        for part in re.split(r"(\s+)", span.text):
            if not part:
                continue
            if part.isspace():
                if current:
                    words.append(current)
                    current = []
                continue
            current.append(Frag(part, font_for(span), size_for(span, size),
                                color_for(span, theme), span.href))
    if current:
        words.append(current)
    return words


def _break_word(word: list[Frag], width: float) -> list[list[Frag]]:
    """Split a word too wide for the measure, character by character."""
    pieces: list[list[Frag]] = []
    current: list[Frag] = []
    used = 0.0
    for frag in word:
        buffer = ""
        for char in frag.text:
            advance = pdf.text_width(char, frag.font, frag.size)
            if used + advance > width and (current or buffer):
                if buffer:
                    current.append(replace(frag, text=buffer))
                    buffer = ""
                pieces.append(current)
                current, used = [], 0.0
            buffer += char
            used += advance
        if buffer:
            current.append(replace(frag, text=buffer))
    if current:
        pieces.append(current)
    return pieces


def wrap_spans(spans, width: float, size: float, theme: Theme) -> list[list[Frag]]:
    words = _words(list(spans), size, theme)
    if not words:
        return []
    space = Frag(" ", "Helvetica", size, theme.ink)
    space_width = frag_width(space)

    lines: list[list[Frag]] = []
    current: list[Frag] = []
    used = 0.0

    def flush() -> None:
        nonlocal current, used
        if current:
            lines.append(current)
            current, used = [], 0.0

    for word in words:
        word_width = sum(frag_width(frag) for frag in word)
        if word_width > width:
            flush()
            pieces = _break_word(word, width)
            lines.extend(pieces[:-1])
            current = list(pieces[-1])
            used = sum(frag_width(frag) for frag in current)
            continue
        extra = word_width + (space_width if current else 0.0)
        if current and used + extra > width:
            flush()
            extra = word_width
        if current:
            current.append(space)
            used += space_width
        current.extend(word)
        used += word_width
    flush()
    return lines


# ── The typesetter ───────────────────────────────────────────────────────


@dataclass
class TocEntry:
    level: int
    title: str
    page_index: int
    y: float


class Typesetter:
    def __init__(self, doc: pdf.Document, theme: Theme, book_title: str = "",
                 targets: dict[str, tuple[int, float]] | None = None,
                 base_dir: Path | None = None):
        #: Pictures are named relative to the chapter that shows them.
        self.base_dir = Path(base_dir) if base_dir else None
        self._pictures: dict[str, object] = {}
        self.doc = doc
        self.theme = theme
        self.book_title = book_title
        self.page: pdf.Page | None = None
        self.y = theme.content_top
        self.chapter_title = ""
        self.plain = False
        self.toc: list[TocEntry] = []
        #: chapter file basename -> (page index, y). Filled by the caller
        #: on the pass that knows where chapters landed.
        self.targets = targets or {}
        self.deferred_links: list[tuple[pdf.Page, float, float, float, float, str]] = []

    # -- page management -------------------------------------------------

    def start_page(self) -> pdf.Page:
        self.page = self.doc.new_page()
        self.y = self.theme.content_top
        if not self.plain:
            self._chrome()
        return self.page

    def _chrome(self) -> None:
        theme, page = self.theme, self.page
        top = theme.page[1] - theme.margin_top + 22
        if self.book_title:
            page.text(theme.margin_left, top, self.book_title, "Helvetica",
                      theme.small_size, theme.muted)
        if self.chapter_title:
            width = pdf.text_width(self.chapter_title, "Helvetica", theme.small_size)
            page.text(theme.page[0] - theme.margin_right - width, top,
                      self.chapter_title, "Helvetica", theme.small_size, theme.muted)
        page.line(theme.margin_left, top - 6, theme.page[0] - theme.margin_right,
                  top - 6, theme.rule, 0.4)
        number = str(len(self.doc.pages))
        width = pdf.text_width(number, "Helvetica", theme.small_size)
        page.text((theme.page[0] - width) / 2, theme.margin_bottom - 14, number,
                  "Helvetica", theme.small_size, theme.muted)

    def ensure(self, height: float) -> None:
        if self.page is None:
            self.start_page()
            return
        if self.y - height < self.theme.content_bottom:
            self.start_page()

    # -- primitives ------------------------------------------------------

    def draw_line(self, line: list[Frag], x: float, y: float) -> None:
        for frag in line:
            if frag.text.strip():
                self.page.text(x, y, frag.text, frag.font, frag.size, frag.color)
                if frag.href:
                    width = frag_width(frag)
                    self.page.line(x, y - 1.6, x + width, y - 1.6, frag.color, 0.35)
                    self.deferred_links.append(
                        (self.page, x, y - 2.5, width, frag.size + 2, frag.href)
                    )
            x += frag_width(frag)

    def paragraph(self, spans, size=None, leading=None, indent=0.0, after=6.0,
                  measure=None) -> None:
        theme = self.theme
        size = size or theme.body_size
        leading = leading or theme.body_leading
        measure = measure if measure is not None else theme.measure - indent
        for line in wrap_spans(spans, measure, size, theme):
            self.ensure(leading)
            self.y -= leading
            self.draw_line(line, theme.margin_left + indent, self.y)
        self.y -= after

    # -- blocks ----------------------------------------------------------

    def render_blocks(self, blocks: list) -> None:
        for block in blocks:
            self.render_block(block)

    def render_block(self, block) -> None:
        if isinstance(block, mdread.Heading):
            self.heading(block)
        elif isinstance(block, mdread.Paragraph):
            self.paragraph(block.spans)
        elif isinstance(block, mdread.ListBlock):
            self.list_block(block)
        elif isinstance(block, mdread.CodeBlock):
            self.code_block(block.lines, framed=False)
        elif isinstance(block, mdread.ImageBlock):
            self.picture(block)
        elif isinstance(block, mdread.DiagramBlock):
            self.diagram(block)
        elif isinstance(block, mdread.Mermaid):
            self.mermaid(block)
        elif isinstance(block, mdread.Table):
            self.table(block)
        elif isinstance(block, mdread.Quote):
            self.quote(block)
        elif isinstance(block, mdread.Rule):
            self.rule()

    def heading(self, block: mdread.Heading) -> None:
        theme = self.theme
        text = "".join(span.text for span in block.spans)
        if block.level == 1:
            self.ensure(theme.h1_size * 2)
            self.y -= theme.h1_size + 4
            self.page.text(theme.margin_left, self.y, text, "Helvetica-Bold",
                           theme.h1_size, theme.ink)
            self.y -= 10
            self.page.line(theme.margin_left, self.y, theme.margin_left + 46,
                           self.y, theme.accent, 1.6)
            self.y -= 14
            return
        if block.level == 2:
            # Keep the heading with the two lines that follow it; a heading
            # alone at the foot of a page reads as a mistake.
            self.ensure(theme.h2_size + theme.body_leading * 2 + 18)
            self.y -= 17
            self.page.text(theme.margin_left, self.y, text, "Helvetica-Bold",
                           theme.h2_size, theme.ink)
            self.y -= 7
            self.toc.append(TocEntry(2, text, len(self.doc.pages) - 1, self.y))
            return
        self.ensure(theme.h3_size + theme.body_leading * 2 + 13)
        self.y -= 13
        self.page.text(theme.margin_left, self.y, text, "Helvetica-Bold",
                       theme.h3_size, theme.ink)
        self.y -= 5

    def list_block(self, block: mdread.ListBlock) -> None:
        theme = self.theme
        for item in block.items:
            offset = item.level * 15.0
            indent = offset + 15.0
            marker_width = pdf.text_width(item.marker, "Helvetica", theme.body_size)
            first = True
            lines = wrap_spans(item.spans, theme.measure - indent, theme.body_size, theme)
            for line in lines:
                self.ensure(theme.body_leading)
                self.y -= theme.body_leading
                if first:
                    self.page.text(theme.margin_left + offset + (11 - marker_width), self.y,
                                   item.marker, "Helvetica", theme.body_size, theme.muted)
                    first = False
                self.draw_line(line, theme.margin_left + indent, self.y)
            self.y -= 2.5
        self.y -= 5

    def code_block(self, source: list[str], framed: bool, caption: str = "") -> None:
        theme = self.theme
        inner = theme.measure - 2 * theme.code_pad
        lines: list[list[Frag]] = []
        for raw in source:
            frag = Frag(raw.rstrip(), "Courier", theme.code_size, theme.code_ink)
            if not frag.text:
                lines.append([frag])
                continue
            if frag_width(frag) <= inner:
                lines.append([frag])
            else:
                lines.extend(_break_word([frag], inner))

        index = 0
        while index < len(lines):
            self.ensure(theme.code_leading * 2 + 2 * theme.code_pad)
            available = self.y - theme.content_bottom - 2 * theme.code_pad
            fit = max(1, int(available // theme.code_leading))
            chunk = lines[index:index + fit]
            height = len(chunk) * theme.code_leading + 2 * theme.code_pad
            top = self.y
            self.page.rect(theme.margin_left, top - height, theme.measure, height,
                           fill=None if framed else theme.code_bg,
                           stroke=theme.rule if framed else None, line_width=0.5)
            if caption and index == 0:
                self.page.text(theme.margin_left + theme.code_pad,
                               top - theme.code_pad - theme.small_size + 1, caption,
                               "Helvetica-Oblique", theme.small_size, theme.muted)
            cursor = top - theme.code_pad
            for line in chunk:
                cursor -= theme.code_leading
                self.draw_line(line, theme.margin_left + theme.code_pad, cursor + 2.5)
            self.y = top - height
            index += fit
            if index < len(lines):
                self.start_page()
        self.y -= 9

    #: A picture may take at most this much of the text area, so that a tall
    #: screenshot never occupies a whole page on its own.
    PICTURE_SHARE = 0.66

    #: Share of the measure a taller-than-wide picture may occupy.
    PORTRAIT_WIDTH = 0.62

    def _load(self, path: str):
        """Read a picture, or None if it cannot be read. Cached per run."""
        if path in self._pictures:
            return self._pictures[path]
        picture = None
        if self.base_dir is not None:
            target = (self.base_dir / path).resolve()
            try:
                picture = images.read_png(target)
            except (OSError, images.UnsupportedImage):
                picture = None
        self._pictures[path] = picture
        return picture

    def picture(self, block: mdread.ImageBlock) -> None:
        """Place a screenshot, scaled to fit, with its caption beneath.

        A picture that cannot be read leaves a visible note naming the file
        rather than a silent gap: a renamed screenshot should be obvious in
        the document, not something a reader has to notice is missing.
        """
        theme = self.theme
        if self.page is None:
            self.start_page()
        picture = self._load(block.path)
        caption_lines = wrap_spans(mdread.parse_inline(block.caption),
                                   theme.measure, theme.small_size + 0.4, theme) \
            if block.caption else []
        caption_height = len(caption_lines) * (theme.small_size + 4.0)

        if picture is None:
            note = f"[picture not found: {block.path}]"
            self.ensure(theme.body_leading * 2 + 12)
            self.y -= 8
            box_height = theme.body_leading + 12
            self.page.rect(theme.margin_left, self.y - box_height, theme.measure,
                           box_height, stroke=theme.rule)
            self.page.text(theme.margin_left + 9, self.y - box_height + 9, note,
                           "Helvetica-Oblique", theme.body_size, theme.muted)
            self.y -= box_height + 8
            return

        # Only the part of the screenshot that carries content is shown. A
        # panel that is empty below the fold is a real thing about the
        # product, but half a blank page does not communicate it.
        share = picture.visible_share
        room = (theme.content_top - theme.content_bottom) * self.PICTURE_SHARE
        shape = picture.aspect * share
        # A picture taller than it is wide is a panel or a phone-shaped
        # screen. Run edge to edge it reads as a full-screen application,
        # so it is held back from the full measure.
        width = theme.measure * (self.PORTRAIT_WIDTH if shape > 1.0 else 1.0)
        height = width * shape
        if height > room:
            height = room
            width = height / shape

        total = height + caption_height + 14.0
        if self.y - total < theme.content_bottom:
            self.start_page()
        self.y -= 8.0
        left = theme.margin_left + (theme.measure - width) / 2
        self.page.image(left, self.y - height, width, height, picture,
                        show_fraction=share)
        # A hairline keeps a screenshot with a pale edge from bleeding into
        # the page.
        self.page.rect(left, self.y - height, width, height, stroke=theme.rule,
                       line_width=0.4)
        self.y -= height + 4.0
        for line in caption_lines:
            self.y -= theme.small_size + 4.0
            offset = (theme.measure - line_width(line)) / 2
            self.draw_line(line, theme.margin_left + max(0.0, offset), self.y)
        self.y -= 10.0

    def diagram(self, block: mdread.DiagramBlock) -> None:
        """Draw a picture.

        A row-based diagram breaks between its rows when it will not fit,
        the way a table does; anything else moves whole to the next page.
        Jumping every diagram whole leaves holes a third of a page deep,
        which in a document meant to be read straight through is worse than
        a break between two steps.
        """
        theme = self.theme
        style = theme.diagram_style()
        if self.page is None:
            self.start_page()
        self.y -= 7.0

        remaining = list(block.diagram.items)
        first = True
        while remaining:
            available = self.y - theme.content_bottom
            count = diagrams.fit_count(block.diagram, remaining, style,
                                       theme.measure, available, first)
            if count == 0:
                if self.y >= theme.content_top - 1.0:
                    # Already at the top of a fresh page and still nothing
                    # fits. Take one row and let it overflow rather than
                    # page-break for ever.
                    count = 1
                else:
                    self.start_page()
                    continue
            piece = diagrams.subset(block.diagram, remaining[:count],
                                    keep_title=first, keep_caption=count == len(remaining))
            plan = diagrams.plan(piece, style, theme.measure)
            plan.draw(self.page, theme.margin_left, self.y)
            self.y -= plan.height
            remaining = remaining[count:]
            first = False
            if remaining:
                self.start_page()
        self.y -= 12.0

    def mermaid(self, block: mdread.Mermaid) -> None:
        theme = self.theme
        self.ensure(theme.body_leading * 3)
        self.y -= theme.body_leading
        self.page.text(theme.margin_left, self.y,
                       "Diagram (mermaid) — shown as source; it renders in the Markdown:",
                       "Helvetica-Oblique", theme.small_size + 0.4, theme.muted)
        self.y -= 5
        self.code_block(block.lines, framed=True)

    def rule(self) -> None:
        theme = self.theme
        self.ensure(16)
        self.y -= 8
        self.page.line(theme.margin_left, self.y, theme.page[0] - theme.margin_right,
                       self.y, theme.rule, 0.6)
        self.y -= 10

    def quote(self, block: mdread.Quote) -> None:
        theme = self.theme
        start_page, start_y = self.page, self.y
        indent = 14.0
        for inner in block.blocks:
            if isinstance(inner, mdread.Paragraph):
                self.paragraph(inner.spans, indent=indent, after=4.0,
                               measure=theme.measure - indent - 6)
            else:
                self.render_block(inner)
        if self.page is start_page:
            start_page.line(theme.margin_left + 2, start_y - 2, theme.margin_left + 2,
                            self.y + 6, theme.accent, 1.8)
        self.y -= 4

    # -- tables ----------------------------------------------------------

    def _column_widths(self, table: mdread.Table) -> list[float]:
        """Auto table layout, on the usual two metrics.

        A column has a *minimum* (its longest unbreakable word) and a
        *natural* width (its content unwrapped). Scaling every column by
        one factor -- the obvious approach -- lets one paragraph-long cell
        crush its neighbours: in the crate reference it squeezed `Path`
        down to four characters and hyphenated every value in it. Instead
        each column is guaranteed its minimum, and only the slack above
        that is shared out in proportion to how much each column wants.
        """
        theme = self.theme
        columns = len(table.headers)
        padding = 2 * theme.cell_pad
        smallest = [0.0] * columns
        natural = [0.0] * columns
        for row, bold in ((table.headers, True), *((row, False) for row in table.rows)):
            for index, cell in enumerate(row[:columns]):
                full, word = self._cell_metrics(cell, bold)
                natural[index] = max(natural[index], full + padding)
                smallest[index] = max(smallest[index], word + padding)
        smallest = [min(width, theme.measure / 2) for width in smallest]

        if sum(natural) <= theme.measure:
            widths = list(natural)
            widths[natural.index(max(natural))] += theme.measure - sum(natural)
            return widths

        if sum(smallest) >= theme.measure:
            # Even the longest words do not fit; break them, proportionally.
            total = sum(smallest) or 1.0
            return [width * theme.measure / total for width in smallest]

        slack = theme.measure - sum(smallest)
        want = [nat - small for nat, small in zip(natural, smallest)]
        total_want = sum(want)
        if total_want <= 0:
            return [small + slack / columns for small in smallest]
        return [small + slack * share / total_want
                for small, share in zip(smallest, want)]

    def _cell_metrics(self, spans, bold: bool) -> tuple[float, float]:
        """(unwrapped width, longest single word) for one cell.

        Measured through the same `_words` path the wrapper uses, so the
        column is sized in the faces the cell is actually drawn in -- a
        Courier code span is wider than the same characters in Helvetica,
        and a header is drawn bold.
        """
        theme = self.theme
        if bold:
            spans = [replace(span, bold=True) for span in spans]
        words = _words(list(spans), theme.table_size, theme)
        if not words:
            return 0.0, 0.0
        space = pdf.text_width(" ", "Helvetica", theme.table_size)
        widths = [sum(frag_width(frag) for frag in word) for word in words]
        return sum(widths) + space * (len(words) - 1), max(widths)

    def _row_lines(self, row, widths, bold: bool):
        theme = self.theme
        cells = []
        for index, width in enumerate(widths):
            spans = row[index] if index < len(row) else [mdread.Span("")]
            if bold:
                spans = [replace(span, bold=True) for span in spans]
            cells.append(wrap_spans(spans, width - 2 * theme.cell_pad,
                                    theme.table_size, theme))
        return cells

    def _draw_row(self, cells, widths, height: float, fill=None) -> None:
        theme = self.theme
        top = self.y
        if fill:
            self.page.rect(theme.margin_left, top - height, sum(widths), height, fill=fill)
        x = theme.margin_left
        for index, lines in enumerate(cells):
            cursor = top - theme.cell_pad
            for line in lines:
                cursor -= theme.table_leading
                self.draw_line(line, x + theme.cell_pad, cursor + 2.6)
            x += widths[index]
        self.y = top - height

    def table(self, block: mdread.Table) -> None:
        theme = self.theme
        if not block.headers:
            return
        widths = self._column_widths(block)
        header_cells = self._row_lines(block.headers, widths, bold=True)
        header_height = self._height(header_cells)

        def draw_header() -> None:
            self._draw_row(header_cells, widths, header_height, fill=theme.band)
            self.page.line(theme.margin_left, self.y, theme.margin_left + sum(widths),
                           self.y, theme.rule, 0.6)

        self.ensure(header_height + theme.table_leading * 2 + 8)
        self.y -= 6
        draw_header()
        for row in block.rows:
            cells = self._row_lines(row, widths, bold=False)
            height = self._height(cells)
            if self.y - height < theme.content_bottom:
                self.start_page()
                self.y -= 4
                draw_header()
            self._draw_row(cells, widths, height)
            self.page.line(theme.margin_left, self.y, theme.margin_left + sum(widths),
                           self.y, theme.rule, 0.35)
        self.y -= 10

    def _height(self, cells) -> float:
        rows = max((len(lines) for lines in cells), default=1)
        return max(rows, 1) * self.theme.table_leading + 2 * self.theme.cell_pad


# ── Whole-document composition ───────────────────────────────────────────


def _title_page(setter: Typesetter, book, digest: str, chapters: int) -> None:
    theme = setter.theme
    setter.plain = True
    page = setter.start_page()
    setter.plain = False
    top = theme.page[1] * 0.62
    page.line(theme.margin_left, top + 42, theme.margin_left + 64, top + 42,
              theme.accent, 2.4)
    page.text(theme.margin_left, top, book.title, "Helvetica-Bold", 30, theme.ink)
    setter.y = top - 26
    intro = " ".join(book.intro.split())
    if intro:
        setter.paragraph(mdread.parse_inline(intro), size=10.4, leading=15.4,
                         measure=theme.measure * 0.82)
    footer = theme.margin_bottom + 40
    page.line(theme.margin_left, footer + 26, theme.page[0] - theme.margin_right,
              footer + 26, theme.rule, 0.5)
    page.text(theme.margin_left, footer + 12,
              f"{chapters} chapters — generated by handbook/tools/gen.py",
              "Helvetica", 8.4, theme.muted)
    page.text(theme.margin_left, footer,
              f"source digest {digest[:16]}", "Courier", 7.6, theme.muted)


def _toc_height(entries, theme: Theme) -> float:
    height = 34.0
    for entry in entries:
        height += 20.0 if entry.level == 0 else 15.2
    return height


def _fill_toc(doc: pdf.Document, theme: Theme, pages: list[int], entries,
              page_numbers: dict[str, int]) -> int:
    """Draw the contents onto the reserved pages; return pages needed."""
    used = 0
    page = doc.pages[pages[0]]
    y = theme.content_top - 6
    page.text(theme.margin_left, y, "Contents", "Helvetica-Bold", 17, theme.ink)
    y -= 22

    for entry in entries:
        step = 20.0 if entry.level == 0 else 15.2
        if y - step < theme.content_bottom:
            used += 1
            if used >= len(pages):
                return used + 1
            page = doc.pages[pages[used]]
            y = theme.content_top - 6
        y -= step
        if entry.level == 0:
            page.text(theme.margin_left, y, entry.title.upper(), "Helvetica-Bold",
                      theme.small_size + 0.6, theme.muted)
            continue
        number = str(entry.page_index + 1)
        title_font = "Helvetica"
        page.text(theme.margin_left + 10, y, entry.title, title_font,
                  theme.body_size, theme.ink)
        title_width = pdf.text_width(entry.title, title_font, theme.body_size)
        number_width = pdf.text_width(number, "Helvetica", theme.body_size)
        right = theme.page[0] - theme.margin_right
        page.text(right - number_width, y, number, "Helvetica", theme.body_size,
                  theme.muted)
        leader_start = theme.margin_left + 14 + title_width
        leader_end = right - number_width - 6
        if leader_end > leader_start:
            page.line(leader_start, y + 2.4, leader_end, y + 2.4, theme.rule, 0.4)
        page.link(theme.margin_left + 10, y - 2, title_width, theme.body_size + 3,
                  target_page=entry.page_index, target_y=entry.y)
    return used + 1


def _compose(root: Path, book, parsed, digest: str, theme: Theme, toc_pages: int):
    doc = pdf.Document(*theme.page)
    setter = Typesetter(doc, theme, book_title=book.title)
    _title_page(setter, book, digest, len(book.chapters))

    reserved = []
    for _ in range(toc_pages):
        setter.plain = True
        setter.start_page()
        reserved.append(len(doc.pages) - 1)
    setter.plain = False

    entries: list[TocEntry] = []
    targets: dict[str, int] = {}
    last_part = None
    for chapter, blocks in parsed:
        # Pictures are named relative to the chapter that shows them.
        setter.base_dir = chapter.path(root).parent
        setter.chapter_title = chapter.title
        setter.toc = []
        setter.start_page()
        index = len(doc.pages) - 1
        targets[chapter.basename] = index
        if chapter.part and chapter.part != last_part:
            last_part = chapter.part
            entries.append(TocEntry(0, chapter.part, index, theme.content_top))
            setter.page.text(theme.margin_left, setter.y - 2, chapter.part.upper(),
                             "Helvetica-Bold", theme.small_size, theme.accent)
            setter.y -= 14
        entries.append(TocEntry(1, chapter.title, index, theme.content_top))
        doc.bookmark(chapter.title, index, theme.page[1], level=0)
        setter.render_blocks(blocks)
        for sub in setter.toc:
            doc.bookmark(sub.title, sub.page_index, sub.y + 20, level=1)

    needed = _fill_toc(doc, theme, reserved, entries, targets)

    # Internal cross-references become real PDF links, now that every
    # chapter's page is known. Anything pointing outside the handbook is
    # left as coloured text -- there is nothing in the file to jump to.
    for page, x, y, width, height, href in setter.deferred_links:
        base = href.split("#")[0].split("/")[-1]
        if base in targets:
            page.link(x, y, width, height, target_page=targets[base],
                      target_y=theme.page[1])

    doc.set_info(title=book.title, subject="Generated from the Elicta repository",
                 custom={"SourceDigest": digest, "Producer": "handbook/tools/pdf.py"})
    return doc, needed


def render_pdf(root: Path, book, digest: str) -> bytes:
    """The whole handbook as one PDF."""
    theme = Theme()
    parsed = [
        (chapter, mdread.parse(chapter.path(root).read_text(encoding="utf-8")))
        for chapter in book.chapters
    ]
    toc_pages = 1
    doc = None
    for _ in range(5):
        doc, needed = _compose(root, book, parsed, digest, theme, toc_pages)
        if needed <= toc_pages:
            break
        toc_pages = needed
    return doc.render()
