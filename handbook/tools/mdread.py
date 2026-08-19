"""Markdown to a block tree, for typesetting.

Only the subset `handbook/STYLE.md` permits is understood: headings,
paragraphs, fenced code, mermaid, lists, tables, blockquotes and rules,
with inline code, bold, italic and links. That is not a limitation to work
around -- the style contract exists so the PDF and the Markdown can agree,
and anything outside it should be caught by review rather than guessed at
here.

The reader never drops text it does not recognise. Unhandled inline syntax
falls through as literal characters, so a mistake shows up as clumsy
typography in the PDF rather than a sentence that quietly disappeared.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import diagrams

#: Everything below this marker is the generated per-page footer. In a
#: single bound document, page-to-page navigation links are noise.
NAV_MARKER = "<!-- HANDBOOK-NAV -->"

_COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
_FENCE_RE = re.compile(r"^\s*```\s*([\w-]*)\s*$")
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
_RULE_RE = re.compile(r"^\s*(-{3,}|\*{3,}|_{3,})\s*$")
_BULLET_RE = re.compile(r"^(\s*)[-*+]\s+(.*)$")
_ORDERED_RE = re.compile(r"^(\s*)(\d+[.)])\s+(.*)$")
_QUOTE_RE = re.compile(r"^\s*>\s?(.*)$")
#: A line that is nothing but a picture. Anything else containing a picture
#: is a sentence that happens to mention one, and stays a sentence.
_IMAGE_LINE_RE = re.compile(r"^\s*!\[([^\]]*)\]\(([^)\s]+)\)\s*$")
_TABLE_SEP_RE = re.compile(r"^\s*\|?[\s:|-]*-[\s:|-]*\|?\s*$")

_ENTITIES = {"&#124;": "|", "&amp;": "&", "&lt;": "<", "&gt;": ">", "&quot;": '"'}

#: A fenced block, matched whole, so nothing inside one is ever rewritten.
_FENCE_BLOCK_RE = re.compile(r"(^[ \t]*```.*?^[ \t]*```[ \t]*$)", re.M | re.S)
_INLINE_CODE_RE = re.compile(r"`+[^`\n]*`+")
#: The generated footer marker, anchored to its own line. A chapter that
#: *quotes* the marker in running prose -- chapter 30 documents it -- must
#: not be truncated at the quotation.
_NAV_LINE_RE = re.compile(r"^[ \t]*" + re.escape(NAV_MARKER) + r"[ \t]*$", re.M)


@dataclass(frozen=True)
class Span:
    text: str
    bold: bool = False
    italic: bool = False
    code: bool = False
    href: str = ""


@dataclass
class Heading:
    level: int
    spans: list[Span]


@dataclass
class Paragraph:
    spans: list[Span]


@dataclass
class ListItem:
    spans: list[Span]
    level: int = 0
    marker: str = "•"


@dataclass
class ListBlock:
    items: list[ListItem]
    ordered: bool = False


@dataclass
class CodeBlock:
    lang: str
    lines: list[str]


@dataclass
class Mermaid:
    lines: list[str]


@dataclass
class ImageBlock:
    """A picture from a file, with the caption printed beneath it."""
    path: str
    caption: str = ""


@dataclass
class DiagramBlock:
    """A picture, declared in the chapter and drawn by the typesetter."""
    diagram: diagrams.Diagram


@dataclass
class Table:
    headers: list[list[Span]]
    rows: list[list[list[Span]]] = field(default_factory=list)


@dataclass
class Quote:
    blocks: list


@dataclass
class Rule:
    pass


# ── Inline ───────────────────────────────────────────────────────────────

_INLINE_RE = re.compile(
    r"(?P<code>`+)(?P<code_text>.+?)(?P=code)"
    r"|\[(?P<link_text>[^\]]+)\]\((?P<href>[^)\s]+)\)"
    # Bold may contain a single asterisk -- `**`core/crates/*`**` is real
    # prose here -- but never the `**` that would close it early.
    r"|\*\*(?P<bold>(?:[^*]|\*(?!\*))+?)\*\*"
    r"|(?<![\w*])\*(?P<italic>[^*\n]+)\*(?![\w*])"
    # Underscore emphasis, but only between word boundaries, so
    # ELICTA_SETTINGS_DB and MODEL_FAST are left intact.
    r"|(?<![\w`])_(?P<uitalic>[^_\n]+)_(?![\w])"
)


def strip_comments(text: str) -> str:
    """Remove HTML comments from prose only.

    A comment inside a fenced block or a code span is content: chapter 30
    tells the reader to write `<!-- lint-allow: <tag> -->`, and a blanket
    regex over the whole document deletes the very thing being taught.
    """
    out: list[str] = []
    for index, segment in enumerate(_FENCE_BLOCK_RE.split(text)):
        if index % 2:  # the captured fence itself
            out.append(segment)
            continue
        held: list[str] = []

        def hold(match: re.Match) -> str:
            held.append(match.group(0))
            return f"\x00{len(held) - 1}\x00"

        cleaned = _COMMENT_RE.sub("", _INLINE_CODE_RE.sub(hold, segment))
        for slot, original in enumerate(held):
            cleaned = cleaned.replace(f"\x00{slot}\x00", original)
        out.append(cleaned)
    return "".join(out)


def _entities(text: str) -> str:
    for entity, char in _ENTITIES.items():
        text = text.replace(entity, char)
    return text


def parse_inline(text: str, **inherited) -> list[Span]:
    """Split a line into styled runs. Never loses characters."""
    spans: list[Span] = []
    position = 0
    for match in _INLINE_RE.finditer(text):
        if match.start() > position:
            spans.append(Span(_entities(text[position:match.start()]), **inherited))
        if match.group("code_text") is not None:
            # Backticks win: their contents are literal, so `a * b` keeps
            # its asterisk instead of turning into emphasis.
            spans.append(Span(_entities(match.group("code_text")), code=True,
                              **{k: v for k, v in inherited.items() if k != "code"}))
        elif match.group("link_text") is not None:
            nested = dict(inherited)
            nested["href"] = match.group("href")
            spans.extend(parse_inline(match.group("link_text"), **nested))
        elif match.group("bold") is not None:
            nested = dict(inherited)
            nested["bold"] = True
            spans.extend(parse_inline(match.group("bold"), **nested))
        else:
            nested = dict(inherited)
            nested["italic"] = True
            emphasised = match.group("italic")
            if emphasised is None:
                emphasised = match.group("uitalic")
            spans.extend(parse_inline(emphasised, **nested))
        position = match.end()
    if position < len(text):
        spans.append(Span(_entities(text[position:]), **inherited))
    return [span for span in spans if span.text] or [Span("", **inherited)]


def _cells(line: str) -> list[list[Span]]:
    stripped = line.strip()
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|"):
        stripped = stripped[:-1]
    return [parse_inline(cell.strip()) for cell in stripped.split("|")]


# ── Blocks ───────────────────────────────────────────────────────────────


def parse(text: str) -> list:
    text = _NAV_LINE_RE.split(text)[0]
    text = strip_comments(text)
    lines = text.splitlines()

    blocks: list = []
    paragraph: list[str] = []
    index = 0

    def flush() -> None:
        if paragraph:
            blocks.append(Paragraph(parse_inline(" ".join(paragraph))))
            paragraph.clear()

    while index < len(lines):
        line = lines[index]

        fence = _FENCE_RE.match(line)
        if fence:
            flush()
            lang = fence.group(1)
            body: list[str] = []
            index += 1
            while index < len(lines) and not _FENCE_RE.match(lines[index]):
                body.append(lines[index])
                index += 1
            index += 1  # closing fence
            if lang == "diagram":
                blocks.append(DiagramBlock(diagrams.parse(body)))
            elif lang == "mermaid":
                blocks.append(Mermaid(body))
            else:
                blocks.append(CodeBlock(lang, body))
            continue

        if not line.strip():
            flush()
            index += 1
            continue

        picture = _IMAGE_LINE_RE.match(line)
        if picture:
            flush()
            blocks.append(ImageBlock(picture.group(2), picture.group(1).strip()))
            index += 1
            continue

        heading = _HEADING_RE.match(line)
        if heading:
            flush()
            blocks.append(Heading(len(heading.group(1)), parse_inline(heading.group(2).strip())))
            index += 1
            continue

        if _RULE_RE.match(line):
            flush()
            blocks.append(Rule())
            index += 1
            continue

        # A table is a header row, a separator row, then body rows. The
        # separator is what distinguishes it from a paragraph containing
        # pipes, so both lines are required before committing.
        if "|" in line and index + 1 < len(lines) and _TABLE_SEP_RE.match(lines[index + 1]) \
                and "|" in lines[index + 1]:
            flush()
            table = Table(_cells(line))
            index += 2
            while index < len(lines) and "|" in lines[index] and lines[index].strip():
                table.rows.append(_cells(lines[index]))
                index += 1
            blocks.append(table)
            continue

        if _QUOTE_RE.match(line):
            flush()
            quoted: list[str] = []
            while index < len(lines) and _QUOTE_RE.match(lines[index]):
                quoted.append(_QUOTE_RE.match(lines[index]).group(1))
                index += 1
            blocks.append(Quote(parse("\n".join(quoted))))
            continue

        bullet, ordered = _BULLET_RE.match(line), _ORDERED_RE.match(line)
        if bullet or ordered:
            flush()
            index = _read_list(lines, index, blocks)
            continue

        paragraph.append(line.strip())
        index += 1

    flush()
    return blocks


def _read_list(lines: list[str], index: int, blocks: list) -> int:
    items: list[ListItem] = []
    is_ordered = bool(_ORDERED_RE.match(lines[index]))
    while index < len(lines):
        line = lines[index]
        bullet, ordered = _BULLET_RE.match(line), _ORDERED_RE.match(line)
        if bullet or ordered:
            if bullet:
                indent, marker, body = bullet.group(1), "•", bullet.group(2)
            else:
                indent, marker, body = ordered.group(1), ordered.group(2), ordered.group(3)
            items.append(ListItem([], level=len(indent) // 2, marker=marker))
            items[-1].spans = [Span(body)]  # raw for now; joined below
            index += 1
            continue
        if line.strip() and line.startswith((" ", "\t")) and items:
            # A continuation line: indented, and not itself a new item.
            items[-1].spans = [Span(items[-1].spans[0].text + " " + line.strip())]
            index += 1
            continue
        break
    for item in items:
        item.spans = parse_inline(item.spans[0].text)
    blocks.append(ListBlock(items, ordered=is_ordered))
    return index
