"""Diagrams, drawn as pictures.

The handbook is read by people who do not work on the code, and a block of
diagram source is not a picture -- it is homework. So chapters declare
diagrams in a small, readable format and this module draws them.

    ```diagram
    type: steps
    title: What happens around a meeting
    item: Before | The system reads the material you already have.
    item: During | It listens and offers one question at a time.
    ```

Five shapes, chosen because they are what an explanation actually needs:
`steps` for a sequence, `flow` for a chain, `timeline` for where the time
goes, `compare` for two things side by side, and `stack` for layers.

Two rules hold the whole thing together. A diagram knows its height before
it is drawn, so the paginator can decide whether it fits. And a diagram
this module does not understand is drawn as its own text, never dropped --
a reader should see something clumsy, never a hole.

Depends only on `pdf`, so there is no cycle with the typesetter.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pdf

KNOWN = ("steps", "flow", "timeline", "compare", "stack")

#: Kinds that are a list of independent rows, and can therefore be broken
#: between them. A flow is a single chain and a timeline is a single bar:
#: half of either is not a smaller diagram, it is a wrong one.
SPLITTABLE = ("steps", "compare", "stack")


@dataclass(frozen=True)
class Item:
    parts: list[str]


@dataclass
class Diagram:
    kind: str = ""
    title: str = ""
    caption: str = ""
    fields: dict[str, str] = field(default_factory=dict)
    items: list[Item] = field(default_factory=list)


def parse(lines: list[str]) -> Diagram:
    diagram = Diagram()
    for raw in lines:
        line = raw.strip()
        if not line or ":" not in line:
            continue
        key, _, value = line.partition(":")
        key, value = key.strip().lower(), value.strip()
        if key == "item":
            diagram.items.append(Item([part.strip() for part in value.split("|")]))
        elif key == "type":
            diagram.kind = value.lower()
        elif key == "title":
            diagram.title = value
        elif key == "caption":
            diagram.caption = value
        else:
            diagram.fields[key] = value
    return diagram


def is_known(diagram: Diagram) -> bool:
    return diagram.kind in KNOWN


def can_split(diagram: Diagram) -> bool:
    return diagram.kind in SPLITTABLE


def subset(diagram: Diagram, items: list[Item], keep_title: bool,
           keep_caption: bool) -> Diagram:
    """The same diagram over fewer rows.

    The title goes on the first piece only and the caption on the last, so
    a split reads as one diagram continuing rather than two diagrams.
    """
    return Diagram(
        kind=diagram.kind,
        title=diagram.title if keep_title else "",
        caption=diagram.caption if keep_caption else "",
        fields=dict(diagram.fields),
        items=list(items),
    )


def fit_count(diagram: Diagram, items: list[Item], style: "DiagramStyle",
              measure: float, available: float, keep_title: bool) -> int:
    """How many of `items` fit in `available` points.

    Returns 0 when nothing fits, which the caller answers with a page
    break. A kind that cannot split answers all or nothing.
    """
    if not items:
        return 0
    whole = subset(diagram, items, keep_title, True)
    if plan(whole, style, measure).height <= available:
        return len(items)
    if not can_split(diagram):
        return 0
    for count in range(len(items) - 1, 0, -1):
        part = subset(diagram, items[:count], keep_title, False)
        if plan(part, style, measure).height <= available:
            return count
    return 0


@dataclass(frozen=True)
class DiagramStyle:
    ink: tuple = (0.11, 0.11, 0.12)
    muted: tuple = (0.46, 0.47, 0.50)
    rule: tuple = (0.83, 0.84, 0.87)
    accent: tuple = (0.13, 0.24, 0.55)
    panel: tuple = (0.966, 0.972, 0.982)
    band: tuple = (0.906, 0.925, 0.957)
    strong: tuple = (0.20, 0.33, 0.60)
    waiting: tuple = (0.78, 0.79, 0.82)
    paper: tuple = (1.0, 1.0, 1.0)

    title_size: float = 10.4
    label_size: float = 9.0
    body_size: float = 8.4
    small_size: float = 7.6
    leading: float = 11.4
    tight_leading: float = 10.2

    pad: float = 9.0
    gap: float = 9.0
    radius: float = 4.5


# ── Plain-text wrapping, so this module needs nothing from the typesetter ─


def wrap(text: str, font: str, size: float, width: float) -> list[str]:
    words, lines, current = text.split(), [], ""
    for word in words:
        trial = f"{current} {word}".strip()
        if current and pdf.text_width(trial, font, size) > width:
            lines.append(current)
            current = word
        else:
            current = trial
        while pdf.text_width(current, font, size) > width and len(current) > 1:
            cut = len(current)
            while cut > 1 and pdf.text_width(current[:cut], font, size) > width:
                cut -= 1
            lines.append(current[:cut])
            current = current[cut:]
    if current:
        lines.append(current)
    return lines or [""]


# ── Plans: relative ops now, absolute coordinates at draw time ───────────


@dataclass
class Plan:
    """Draw operations in diagram-local space, plus the total height.

    `dy` runs downward from the top of the diagram, which is the natural
    way to lay a document out; `draw` flips it into the PDF's upward `y`.
    """
    height: float
    ops: list = field(default_factory=list)

    def text(self, dx, dy, text, font, size, color):
        if text:
            self.ops.append(("text", dx, dy, text, font, size, color))

    def centred(self, dx, width, dy, text, font, size, color):
        offset = (width - pdf.text_width(text, font, size)) / 2
        self.text(dx + max(0.0, offset), dy, text, font, size, color)

    def right(self, dx, width, dy, text, font, size, color):
        self.text(dx + max(0.0, width - pdf.text_width(text, font, size)), dy,
                  text, font, size, color)

    def box(self, dx, dy, width, height, fill=None, stroke=None, radius=0.0):
        self.ops.append(("box", dx, dy, width, height, fill, stroke, radius))

    def poly(self, points, fill):
        self.ops.append(("poly", points, fill))

    def line(self, dx1, dy1, dx2, dy2, color, width=0.6):
        self.ops.append(("line", dx1, dy1, dx2, dy2, color, width))

    def draw(self, page, x: float, top: float) -> None:
        for op in self.ops:
            if op[0] == "text":
                _, dx, dy, text, font, size, color = op
                page.text(x + dx, top - dy, text, font, size, color)
            elif op[0] == "box":
                _, dx, dy, width, height, fill, stroke, radius = op
                if radius > 0:
                    page.round_rect(x + dx, top - dy - height, width, height,
                                    radius=radius, fill=fill, stroke=stroke)
                else:
                    page.rect(x + dx, top - dy - height, width, height,
                              fill=fill, stroke=stroke)
            elif op[0] == "poly":
                _, points, fill = op
                page.polygon([(x + px, top - py) for px, py in points], fill=fill)
            else:
                _, dx1, dy1, dx2, dy2, color, width = op
                page.line(x + dx1, top - dy1, x + dx2, top - dy2, color, width)


# ── The shapes ───────────────────────────────────────────────────────────


def plan(diagram: Diagram, style: DiagramStyle, measure: float) -> Plan:
    body = _BUILDERS.get(diagram.kind, _unknown)
    result = Plan(0.0)
    dy = 0.0
    if diagram.title:
        dy += style.title_size
        result.text(0, dy, diagram.title, "Helvetica-Bold", style.title_size, style.ink)
        dy += 9.0
    dy = body(diagram, style, measure, result, dy)
    if diagram.caption:
        dy += 4.0
        for line in wrap(diagram.caption, "Helvetica-Oblique", style.small_size, measure):
            dy += style.small_size + 2.2
            result.text(0, dy, line, "Helvetica-Oblique", style.small_size, style.muted)
    result.height = dy
    return result


def _steps(diagram, style, measure, out, dy):
    badge = 17.0
    text_left = badge + 12.0
    text_width = measure - text_left
    starts = []
    for index, item in enumerate(diagram.items, start=1):
        heading = item.parts[0] if item.parts else ""
        body = item.parts[1] if len(item.parts) > 1 else ""
        top = dy
        starts.append(top)
        out.box(0, top, badge, badge, fill=style.strong, radius=badge / 2)
        out.centred(0, badge, top + badge / 2 + 3.0, str(index),
                    "Helvetica-Bold", style.body_size, style.paper)
        line_y = top
        if heading:
            line_y += style.label_size + 1.0
            out.text(text_left, line_y, heading, "Helvetica-Bold",
                     style.label_size, style.ink)
            line_y += 3.0
        for line in wrap(body, "Helvetica", style.body_size, text_width):
            line_y += style.tight_leading
            out.text(text_left, line_y, line, "Helvetica", style.body_size, style.ink)
        dy = max(line_y + 4.0, top + badge) + 11.0
        if index < len(diagram.items):
            out.line(badge / 2, top + badge + 3.0, badge / 2, dy - 3.0, style.rule, 1.0)
    return dy - 11.0 if diagram.items else dy


def _flow(diagram, style, measure, out, dy):
    count = max(1, len(diagram.items))
    gap = 20.0
    width = (measure - gap * (count - 1)) / count
    inner = width - 2 * style.pad
    wrapped = [wrap(item.parts[0] if item.parts else "", "Helvetica-Bold",
                    style.body_size, inner) for item in diagram.items]
    rows = max(len(lines) for lines in wrapped) if wrapped else 1
    height = 2 * style.pad + rows * style.tight_leading
    for index, lines in enumerate(wrapped):
        left = index * (width + gap)
        out.box(left, dy, width, height, fill=style.band, radius=style.radius)
        text_y = dy + style.pad + (rows - len(lines)) * style.tight_leading / 2
        for line in lines:
            text_y += style.tight_leading - 2.0
            out.centred(left, width, text_y, line, "Helvetica-Bold",
                        style.body_size, style.ink)
            text_y += 2.0
        if index < count - 1:
            middle = dy + height / 2
            start = left + width + 3.0
            end = left + width + gap - 3.0
            out.line(start, middle, end - 4.0, middle, style.strong, 1.1)
            out.poly([(end, middle), (end - 5.0, middle - 3.2),
                      (end - 5.0, middle + 3.2)], fill=style.strong)
    return dy + height


def _timeline(diagram, style, measure, out, dy):
    def amount(item):
        try:
            return max(0.0, float(item.parts[1]))
        except (IndexError, ValueError):
            return 0.0

    total = sum(amount(item) for item in diagram.items) or 1.0
    bar = 26.0
    seam = 1.2          # bands of one colour, drawn touching, read as one band
    count = max(1, len(diagram.items))
    usable = measure - seam * (count - 1)
    left = 0.0
    for index, item in enumerate(diagram.items):
        waiting = len(item.parts) > 2 and item.parts[2].lower() == "slow"
        width = max(3.0, amount(item) / total * usable)
        width = min(width, measure - left)
        fill = style.waiting if waiting else style.strong
        out.box(left, dy, width, bar, fill=fill)
        # A band with room for its own label should carry it: the bar is the
        # picture, and a reader should not have to cross-check the legend to
        # find out what the big block is.
        label = item.parts[0] if item.parts else ""
        label_width = pdf.text_width(label, "Helvetica-Bold", style.small_size)
        if label and width >= label_width + 16.0:
            ink = style.ink if waiting else style.paper
            out.centred(left, width, dy + bar / 2 + 2.6, label,
                        "Helvetica-Bold", style.small_size, ink)
        left += width + seam
    dy += bar + 10.0

    swatch = 8.0
    for item in diagram.items:
        waiting = len(item.parts) > 2 and item.parts[2].lower() == "slow"
        label = item.parts[0] if item.parts else ""
        share = amount(item) / total
        out.box(0, dy, swatch, swatch,
                fill=style.waiting if waiting else style.strong)
        out.text(swatch + 7.0, dy + swatch - 0.5, label, "Helvetica",
                 style.body_size, style.ink)
        note = f"{share * 100:.0f}%" + ("  · waiting on something else" if waiting else "")
        out.right(0, measure, dy + swatch - 0.5, note, "Helvetica",
                  style.small_size, style.muted)
        dy += style.leading + 2.0
    return dy


def _compare(diagram, style, measure, out, dy):
    first = measure * 0.40
    column = (measure - first) / 2
    header = 20.0
    top = dy
    out.box(0, dy, measure, header, fill=style.band)
    out.centred(first, column, dy + 13.5, diagram.fields.get("left", ""),
                "Helvetica-Bold", style.body_size, style.ink)
    out.centred(first + column, column, dy + 13.5, diagram.fields.get("right", ""),
                "Helvetica-Bold", style.body_size, style.ink)
    dy += header

    for item in diagram.items:
        cells = [
            wrap(item.parts[0] if item.parts else "", "Helvetica",
                 style.body_size, first - style.pad * 2),
            wrap(item.parts[1] if len(item.parts) > 1 else "", "Helvetica-Bold",
                 style.body_size, column - style.pad * 2),
            wrap(item.parts[2] if len(item.parts) > 2 else "", "Helvetica-Bold",
                 style.body_size, column - style.pad * 2),
        ]
        rows = max(len(lines) for lines in cells)
        height = rows * style.tight_leading + 10.0
        out.line(0, dy, measure, dy, style.rule, 0.5)
        for index, lines in enumerate(cells):
            box_left = 0.0 if index == 0 else first + (index - 1) * column
            box_width = first if index == 0 else column
            text_y = dy + 5.0
            for line in lines:
                text_y += style.tight_leading - 1.5
                if index == 0:
                    out.text(style.pad, text_y, line, "Helvetica",
                             style.body_size, style.ink)
                else:
                    out.centred(box_left, box_width, text_y, line, "Helvetica-Bold",
                                style.body_size, style.strong)
                text_y += 1.5
        dy += height
    out.box(0, top, measure, dy - top, stroke=style.rule)
    out.line(first, top, first, dy, style.rule, 0.5)
    out.line(first + column, top, first + column, dy, style.rule, 0.5)
    return dy


def _stack(diagram, style, measure, out, dy):
    label_width = measure * 0.34
    for item in diagram.items:
        heading = item.parts[0] if item.parts else ""
        body = item.parts[1] if len(item.parts) > 1 else ""
        lines = wrap(body, "Helvetica", style.body_size,
                     measure - label_width - style.pad * 2)
        height = max(len(lines), 1) * style.tight_leading + style.pad * 2 - 4.0
        out.box(0, dy, measure, height, fill=style.panel, radius=style.radius)
        out.box(0, dy, 3.5, height, fill=style.strong, radius=1.6)
        out.text(style.pad + 4.0, dy + style.pad + style.label_size - 3.0, heading,
                 "Helvetica-Bold", style.label_size, style.ink)
        text_y = dy + style.pad + 1.0
        for line in lines:
            text_y += style.tight_leading - 2.0
            out.text(label_width, text_y, line, "Helvetica", style.body_size, style.ink)
            text_y += 2.0
        dy += height + style.gap - 3.0
    return dy - (style.gap - 3.0) if diagram.items else dy


def _unknown(diagram, style, measure, out, dy):
    """Never drop a diagram. Show it as its own text and say what happened."""
    note = (f"[diagram of an unrecognised kind: {diagram.kind or 'none given'}]"
            if diagram.kind else "[diagram]")
    lines = [note] + [" — ".join(item.parts) for item in diagram.items]
    top = dy
    dy += style.pad
    for entry in lines:
        for line in wrap(entry, "Helvetica", style.body_size, measure - style.pad * 2):
            dy += style.tight_leading
            out.text(style.pad, dy, line, "Helvetica", style.body_size, style.ink)
    dy += style.pad
    out.box(0, top, measure, dy - top, stroke=style.rule, radius=style.radius)
    return dy


_BUILDERS = {
    "steps": _steps,
    "flow": _flow,
    "timeline": _timeline,
    "compare": _compare,
    "stack": _stack,
}
