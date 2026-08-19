"""A minimal PDF 1.4 writer, standard library only.

The handbook generator has no dependencies and this file is why that stayed
true when a PDF was added: this machine has no pandoc, no browser, no LaTeX
and no reportlab, and CI installs nothing but Python. Rather than make the
PDF the one artifact that cannot be built anywhere, the format is written
directly.

Scope is deliberately narrow -- everything the handbook needs and nothing
else: the base-14 Type1 fonts with real glyph metrics, WinAnsi text,
rectangles, rules, internal links and an outline tree. No images, no
embedded fonts, no compression, no encryption.

Two properties are load-bearing:

* **Deterministic.** No creation date, no document ID, fixed-precision
  numbers. Two runs over the same content produce identical bytes, which is
  what lets the build be gated on "produces no diff".
* **Self-checking offsets.** The cross-reference table is built from the
  actual byte offsets of the objects as they are emitted, never predicted.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import images

#: Approximates a quarter circle with a cubic bezier, to within a fraction
#: of a point at the sizes used here.
KAPPA = 0.5522847498307936

#: Page sizes in points (1/72 inch).
A4 = (595.28, 841.89)
LETTER = (612.0, 792.0)

# ── Text encoding ────────────────────────────────────────────────────────

# WinAnsiEncoding is cp1252, so the standard library already has the table.
_WINANSI = "cp1252"

#: Characters outside WinAnsi that appear in this handbook, and the ASCII
#: they degrade to. A missing glyph should read as slightly clumsy prose,
#: never as a broken file or a silent hole in a sentence.
TRANSLITERATE = {
    "→": "->", "←": "<-", "↑": "^", "↓": "v", "⇒": "=>",
    "≤": "<=", "≥": ">=", "≠": "!=", "≈": "~",
    "─": "-", "│": "|", "├": "+", "└": "+", "┌": "+", "┐": "+", "┘": "+", "┬": "+",
    "•": "•",  # in WinAnsi; kept explicit so the bullet is never lost
    "✓": "y", "✗": "x", "★": "*", "⚠": "!",
    "　": " ", " ": " ", "​": "",
    "“": '"', "”": '"', "‘": "'", "’": "'",
}


def encode_text(text: str) -> bytes:
    """Encode a string as a PDF literal string body, in WinAnsi.

    Anything WinAnsi cannot represent is transliterated to ASCII, and
    anything left over becomes `?`. Then the three characters that would
    end the literal early are escaped.
    """
    out = bytearray()
    for char in text:
        try:
            out += char.encode(_WINANSI)
            continue
        except UnicodeEncodeError:
            pass
        replacement = TRANSLITERATE.get(char)
        if replacement is None:
            out += b"?"
            continue
        try:
            out += replacement.encode(_WINANSI)
        except UnicodeEncodeError:
            out += b"?"
    escaped = bytes(out).replace(b"\\", b"\\\\").replace(b"(", rb"\(").replace(b")", rb"\)")
    return escaped


# ── Font metrics ─────────────────────────────────────────────────────────

# Advance widths in 1/1000 em for printable ASCII (32..126), from the
# Adobe base-14 AFM files. Without these, every line break would be placed
# by character count, and a proportional font would overflow the measure.
_HELVETICA = (
    "278,278,355,556,556,889,667,191,333,333,389,584,278,333,278,278,"
    "556,556,556,556,556,556,556,556,556,556,"
    "278,278,584,584,584,556,1015,"
    "667,667,722,722,667,611,778,722,278,500,667,556,833,722,778,667,778,722,"
    "667,611,722,667,944,667,667,611,"
    "278,278,278,469,556,333,"
    "556,556,500,556,556,278,556,556,222,222,500,222,833,556,556,556,556,333,"
    "500,278,556,500,722,500,500,500,"
    "334,260,334,584"
)
_HELVETICA_BOLD = (
    "278,333,474,556,556,889,722,238,333,333,389,584,278,333,278,278,"
    "556,556,556,556,556,556,556,556,556,556,"
    "333,333,584,584,584,611,975,"
    "722,722,722,722,667,611,778,722,278,556,722,611,833,722,778,667,778,722,"
    "667,611,722,667,944,667,667,611,"
    "333,278,333,584,556,333,"
    "556,611,556,611,556,333,611,611,278,278,556,278,889,611,611,611,611,389,"
    "556,333,611,556,778,556,556,500,"
    "389,280,389,584"
)

#: Non-ASCII WinAnsi glyphs the handbook actually uses.
_EXTRA = {"—": 1000, "–": 556, "•": 350, "·": 278, "§": 556, "…": 1000,
          "°": 400, "©": 737, "®": 737, "±": 584, "«": 556, "»": 556}


def _table(spec: str) -> dict[str, int]:
    widths = [int(value) for value in spec.split(",")]
    assert len(widths) == 95, f"expected 95 ASCII widths, got {len(widths)}"
    table = {chr(32 + index): width for index, width in enumerate(widths)}
    table.update(_EXTRA)
    return table


@dataclass(frozen=True)
class FontMetrics:
    base_font: str
    widths: dict[str, int]
    #: Used for any glyph with no entry, so an exotic character costs a
    #: plausible amount of space instead of zero.
    default: int


_HELV = _table(_HELVETICA)
_HELV_BOLD = _table(_HELVETICA_BOLD)
_COURIER = {chr(code): 600 for code in range(32, 127)}
_COURIER.update({char: 600 for char in _EXTRA})

FONTS: dict[str, FontMetrics] = {
    "Helvetica": FontMetrics("Helvetica", _HELV, 556),
    "Helvetica-Bold": FontMetrics("Helvetica-Bold", _HELV_BOLD, 611),
    "Helvetica-Oblique": FontMetrics("Helvetica-Oblique", _HELV, 556),
    "Helvetica-BoldOblique": FontMetrics("Helvetica-BoldOblique", _HELV_BOLD, 611),
    "Courier": FontMetrics("Courier", _COURIER, 600),
    "Courier-Bold": FontMetrics("Courier-Bold", _COURIER, 600),
    "Courier-Oblique": FontMetrics("Courier-Oblique", _COURIER, 600),
}


def text_width(text: str, font: str, size: float) -> float:
    """Width of `text` in points, set in `font` at `size`."""
    metrics = FONTS[font]
    total = 0
    for char in text:
        width = metrics.widths.get(char)
        if width is None:
            # Measure what will actually be drawn: a transliterated arrow
            # occupies two glyphs, not one.
            replacement = TRANSLITERATE.get(char)
            if replacement:
                total += sum(metrics.widths.get(c, metrics.default) for c in replacement)
                continue
            width = metrics.default
        total += width
    return total * size / 1000.0


# ── Number formatting ────────────────────────────────────────────────────


def num(value: float) -> str:
    """Fixed-precision, so output never depends on float repr."""
    text = f"{value:.2f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


# ── Pages ────────────────────────────────────────────────────────────────


@dataclass
class _Link:
    x: float
    y: float
    width: float
    height: float
    target_page: int
    target_y: float


class Page:
    """One page's content stream, in PDF coordinates (origin bottom-left)."""

    def __init__(self, document: "Document", width: float, height: float):
        self._doc = document
        self.width = width
        self.height = height
        self._ops = bytearray()
        self.links: list[_Link] = []

    def _emit(self, text: str) -> None:
        self._ops += text.encode("ascii") + b"\n"

    def text(self, x: float, y: float, string: str, font: str, size: float,
             color: tuple[float, float, float] = (0, 0, 0)) -> None:
        if not string:
            return
        resource = self._doc._font_resource(font)
        self._emit(f"{num(color[0])} {num(color[1])} {num(color[2])} rg")
        self._emit("BT")
        self._emit(f"/{resource} {num(size)} Tf")
        self._emit(f"{num(x)} {num(y)} Td")
        self._ops += b"(" + encode_text(string) + b") Tj\n"
        self._emit("ET")

    def rect(self, x: float, y: float, width: float, height: float,
             fill: tuple[float, float, float] | None = None,
             stroke: tuple[float, float, float] | None = None,
             line_width: float = 0.5) -> None:
        if fill is None and stroke is None:
            return
        if fill:
            self._emit(f"{num(fill[0])} {num(fill[1])} {num(fill[2])} rg")
        if stroke:
            self._emit(f"{num(stroke[0])} {num(stroke[1])} {num(stroke[2])} RG")
            self._emit(f"{num(line_width)} w")
        self._emit(f"{num(x)} {num(y)} {num(width)} {num(height)} re")
        self._emit("B" if (fill and stroke) else ("f" if fill else "S"))

    def line(self, x1: float, y1: float, x2: float, y2: float,
             color: tuple[float, float, float] = (0, 0, 0), width: float = 0.5) -> None:
        self._emit(f"{num(color[0])} {num(color[1])} {num(color[2])} RG")
        self._emit(f"{num(width)} w")
        self._emit(f"{num(x1)} {num(y1)} m {num(x2)} {num(y2)} l")
        self._emit("S")

    def polygon(self, points: list[tuple[float, float]],
                fill: tuple[float, float, float] | None = None,
                stroke: tuple[float, float, float] | None = None,
                line_width: float = 0.5) -> None:
        """A closed polygon. Used for arrowheads."""
        if len(points) < 3 or (fill is None and stroke is None):
            return
        if fill:
            self._emit(f"{num(fill[0])} {num(fill[1])} {num(fill[2])} rg")
        if stroke:
            self._emit(f"{num(stroke[0])} {num(stroke[1])} {num(stroke[2])} RG")
            self._emit(f"{num(line_width)} w")
        first, *rest = points
        self._emit(f"{num(first[0])} {num(first[1])} m")
        for x, y in rest:
            self._emit(f"{num(x)} {num(y)} l")
        self._emit("h")
        self._emit("B" if (fill and stroke) else ("f" if fill else "S"))

    def round_rect(self, x: float, y: float, width: float, height: float,
                   radius: float = 4.0,
                   fill: tuple[float, float, float] | None = None,
                   stroke: tuple[float, float, float] | None = None,
                   line_width: float = 0.5) -> None:
        """A rectangle with soft corners.

        Drawn with four bezier arcs. `KAPPA` is the standard constant for
        approximating a quarter circle with a cubic curve; the eye cannot
        tell the difference at these sizes.
        """
        if fill is None and stroke is None:
            return
        radius = max(0.0, min(radius, width / 2, height / 2))
        if radius <= 0:
            self.rect(x, y, width, height, fill=fill, stroke=stroke,
                      line_width=line_width)
            return
        if fill:
            self._emit(f"{num(fill[0])} {num(fill[1])} {num(fill[2])} rg")
        if stroke:
            self._emit(f"{num(stroke[0])} {num(stroke[1])} {num(stroke[2])} RG")
            self._emit(f"{num(line_width)} w")
        k = radius * KAPPA
        right, top = x + width, y + height
        self._emit(f"{num(x + radius)} {num(y)} m")
        self._emit(f"{num(right - radius)} {num(y)} l")
        self._emit(f"{num(right - radius + k)} {num(y)} {num(right)} "
                   f"{num(y + radius - k)} {num(right)} {num(y + radius)} c")
        self._emit(f"{num(right)} {num(top - radius)} l")
        self._emit(f"{num(right)} {num(top - radius + k)} {num(right - radius + k)} "
                   f"{num(top)} {num(right - radius)} {num(top)} c")
        self._emit(f"{num(x + radius)} {num(top)} l")
        self._emit(f"{num(x + radius - k)} {num(top)} {num(x)} {num(top - radius + k)} "
                   f"{num(x)} {num(top - radius)} c")
        self._emit(f"{num(x)} {num(y + radius)} l")
        self._emit(f"{num(x)} {num(y + radius - k)} {num(x + radius - k)} {num(y)} "
                   f"{num(x + radius)} {num(y)} c")
        self._emit("h")
        self._emit("B" if (fill and stroke) else ("f" if fill else "S"))

    def image(self, x: float, y: float, width: float, height: float,
              picture: "images.Image", show_fraction: float = 1.0) -> None:
        """Place a picture with its bottom-left corner at (x, y).

        PDF draws images into a one-by-one unit square, so the size comes
        from the transformation matrix rather than from the image object --
        which is why the same picture can appear at two sizes without being
        stored twice.

        `show_fraction` below 1 shows only the top of the picture. The
        cropping is done with a clipping path rather than by cutting pixels:
        the image is drawn at the height the whole of it would need, with
        its top aligned to the top of the box, and the surplus hanging below
        is clipped away. Nothing is re-encoded, and the stored picture is
        untouched -- so the same file can appear cropped in one place and
        whole in another.
        """
        resource = self._doc._image_resource(picture)
        cropped = 0.0 < show_fraction < 1.0
        self._emit("q")
        if cropped:
            self._emit(f"{num(x)} {num(y)} {num(width)} {num(height)} re")
            self._emit("W n")
            full_height = height / show_fraction
            self._emit(f"{num(width)} 0 0 {num(full_height)} {num(x)} "
                       f"{num(y + height - full_height)} cm")
        else:
            self._emit(f"{num(width)} 0 0 {num(height)} {num(x)} {num(y)} cm")
        self._emit(f"/{resource} Do")
        self._emit("Q")

    def link(self, x: float, y: float, width: float, height: float,
             target_page: int, target_y: float) -> None:
        self.links.append(_Link(x, y, width, height, target_page, target_y))

    @property
    def content(self) -> bytes:
        return bytes(self._ops)


@dataclass
class _Bookmark:
    title: str
    page_index: int
    y: float
    level: int
    children: list = field(default_factory=list)


class Document:
    def __init__(self, width: float = A4[0], height: float = A4[1]):
        self.width = width
        self.height = height
        self.pages: list[Page] = []
        self._fonts: list[str] = []
        self._images: list["images.Image"] = []
        self._bookmarks: list[_Bookmark] = []
        self._info: dict[str, str] = {}

    # -- construction ----------------------------------------------------

    def new_page(self) -> Page:
        page = Page(self, self.width, self.height)
        self.pages.append(page)
        return page

    def _font_resource(self, font: str) -> str:
        if font not in FONTS:
            raise KeyError(f"unknown font {font!r}; known: {', '.join(sorted(FONTS))}")
        if font not in self._fonts:
            self._fonts.append(font)
        return f"F{self._fonts.index(font)}"

    def _image_resource(self, picture: "images.Image") -> str:
        # Identical pictures share one object: a screenshot used in two
        # chapters should not be stored twice.
        for index, existing in enumerate(self._images):
            if existing == picture:
                return f"Im{index}"
        self._images.append(picture)
        return f"Im{len(self._images) - 1}"

    def set_info(self, title: str = "", author: str = "", subject: str = "",
                 custom: dict[str, str] | None = None) -> None:
        for key, value in (("Title", title), ("Author", author), ("Subject", subject)):
            if value:
                self._info[key] = value
        self._info.update(custom or {})

    def bookmark(self, title: str, page_index: int, y: float, level: int = 0) -> None:
        entry = _Bookmark(title, page_index, y, level)
        if level > 0 and self._bookmarks:
            self._bookmarks[-1].children.append(entry)
        else:
            self._bookmarks.append(entry)

    # -- rendering -------------------------------------------------------

    def render(self) -> bytes:
        # Object numbering is fixed up front so page objects can reference
        # fonts, and links can reference pages, without a second pass.
        catalog, pages_obj = 1, 2
        first_font = 3
        font_numbers = {name: first_font + index for index, name in enumerate(self._fonts)}
        first_image = first_font + len(self._fonts)
        image_numbers = [first_image + index for index in range(len(self._images))]
        first_page = first_image + len(self._images)
        page_numbers = [first_page + 2 * index for index in range(len(self.pages))]
        content_numbers = [number + 1 for number in page_numbers]
        next_number = first_page + 2 * len(self.pages)

        outline_root = 0
        outline_objects: list[tuple[int, bytes]] = []
        if self._bookmarks:
            outline_root = next_number
            next_number += 1
            outline_objects, next_number = self._render_outline(
                outline_root, page_numbers, next_number
            )
        info_number = next_number

        objects: dict[int, bytes] = {}

        catalog_body = f"<< /Type /Catalog /Pages {pages_obj} 0 R"
        if outline_root:
            catalog_body += f" /Outlines {outline_root} 0 R /PageMode /UseOutlines"
        objects[catalog] = (catalog_body + " >>").encode("ascii")

        kids = " ".join(f"{number} 0 R" for number in page_numbers)
        objects[pages_obj] = (
            f"<< /Type /Pages /Kids [{kids}] /Count {len(self.pages)} >>"
        ).encode("ascii")

        for index, picture in enumerate(self._images):
            colour_space = "/DeviceRGB" if picture.colors == 3 else "/DeviceGray"
            parms = ""
            if picture.predictor:
                parms = (f" /DecodeParms << /Predictor 15 /Colors {picture.colors} "
                         f"/BitsPerComponent 8 /Columns {picture.width} >>")
            objects[image_numbers[index]] = (
                f"<< /Type /XObject /Subtype /Image /Width {picture.width} "
                f"/Height {picture.height} /ColorSpace {colour_space} "
                f"/BitsPerComponent 8 /Filter /FlateDecode{parms} "
                f"/Length {len(picture.data)} >>\nstream\n".encode("ascii")
                + picture.data + b"\nendstream"
            )

        for name, number in font_numbers.items():
            objects[number] = (
                f"<< /Type /Font /Subtype /Type1 /BaseFont /{FONTS[name].base_font} "
                f"/Encoding /WinAnsiEncoding >>"
            ).encode("ascii")

        resources = " ".join(f"/F{index} {font_numbers[name]} 0 R"
                             for index, name in enumerate(self._fonts))
        image_resources = " ".join(f"/Im{index} {number} 0 R"
                                   for index, number in enumerate(image_numbers))
        xobjects = f" /XObject << {image_resources} >>" if image_resources else ""
        for index, page in enumerate(self.pages):
            annots = ""
            if page.links:
                items = []
                for link in page.links:
                    target = page_numbers[link.target_page]
                    items.append(
                        f"<< /Type /Annot /Subtype /Link /Border [0 0 0] "
                        f"/Rect [{num(link.x)} {num(link.y)} "
                        f"{num(link.x + link.width)} {num(link.y + link.height)}] "
                        f"/Dest [{target} 0 R /XYZ null {num(link.target_y)} null] >>"
                    )
                annots = " /Annots [" + " ".join(items) + "]"
            objects[page_numbers[index]] = (
                f"<< /Type /Page /Parent {pages_obj} 0 R "
                f"/MediaBox [0 0 {num(self.width)} {num(self.height)}] "
                f"/Resources << /Font << {resources} >>{xobjects} >> "
                f"/Contents {content_numbers[index]} 0 R{annots} >>"
            ).encode("ascii")
            body = page.content
            objects[content_numbers[index]] = (
                f"<< /Length {len(body)} >>\nstream\n".encode("ascii")
                + body
                + b"endstream"
            )

        for number, body in outline_objects:
            objects[number] = body

        info_items = "".join(
            f" /{key} ({encode_text(value).decode('latin-1')})"
            for key, value in self._info.items()
        )
        objects[info_number] = f"<<{info_items} >>".encode("latin-1")

        return self._serialise(objects, catalog, info_number)

    def _render_outline(self, root: int, page_numbers: list[int], next_number: int):
        """Lay out the outline tree, returning (objects, next free number)."""
        flat: list[tuple[_Bookmark, int, int]] = []  # entry, number, parent
        for top in self._bookmarks:
            top_number = next_number
            next_number += 1
            flat.append((top, top_number, root))
            for child in top.children:
                flat.append((child, next_number, top_number))
                next_number += 1

        by_parent: dict[int, list[int]] = {}
        numbers: dict[int, _Bookmark] = {}
        for entry, number, parent in flat:
            by_parent.setdefault(parent, []).append(number)
            numbers[number] = entry

        objects: list[tuple[int, bytes]] = []
        top_level = by_parent.get(root, [])
        objects.append((root, (
            f"<< /Type /Outlines /First {top_level[0]} 0 R /Last {top_level[-1]} 0 R "
            f"/Count {len(top_level)} >>"
        ).encode("ascii")))

        for entry, number, parent in flat:
            siblings = by_parent[parent]
            position = siblings.index(number)
            parts = [f"/Title ({encode_text(entry.title).decode('latin-1')})",
                     f"/Parent {parent} 0 R"]
            if position > 0:
                parts.append(f"/Prev {siblings[position - 1]} 0 R")
            if position < len(siblings) - 1:
                parts.append(f"/Next {siblings[position + 1]} 0 R")
            children = by_parent.get(number, [])
            if children:
                parts.append(f"/First {children[0]} 0 R")
                parts.append(f"/Last {children[-1]} 0 R")
                parts.append(f"/Count {len(children)}")
            target = page_numbers[min(entry.page_index, len(page_numbers) - 1)]
            parts.append(f"/Dest [{target} 0 R /XYZ null {num(entry.y)} null]")
            objects.append((number, ("<< " + " ".join(parts) + " >>").encode("latin-1")))
        return objects, next_number

    def _serialise(self, objects: dict[int, bytes], catalog: int, info: int) -> bytes:
        out = bytearray(b"%PDF-1.4\n")
        # A binary comment marks the file as binary for transfer tools.
        out += b"%\xe2\xe3\xcf\xd3\n"
        offsets: dict[int, int] = {}
        for number in sorted(objects):
            offsets[number] = len(out)
            out += f"{number} 0 obj\n".encode("ascii") + objects[number] + b"\nendobj\n"

        size = max(objects) + 1
        xref_offset = len(out)
        out += f"xref\n0 {size}\n".encode("ascii")
        out += b"0000000000 65535 f \n"
        for number in range(1, size):
            out += f"{offsets.get(number, 0):010d} 00000 n \n".encode("ascii")
        out += (
            f"trailer\n<< /Size {size} /Root {catalog} 0 R /Info {info} 0 R >>\n"
            f"startxref\n{xref_offset}\n%%EOF\n"
        ).encode("ascii")
        return bytes(out)
