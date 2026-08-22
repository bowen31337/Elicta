"""Extracts text content from a reference document's raw bytes (PRD FR-3.3).

Documents arrive as `.docx`, `.pptx`, `.xlsx` and `.pdf` far more often than
as `.txt`. Decoding those as UTF-8 — which is all this did — produced a page
of U+FFFD that chunked, indexed and fed the compiler exactly as though it were
prose. Nothing raised and nothing was worth reading, which is the worst
combination: a document that contributes noise looks identical downstream to
one that contributes nothing.

Everything here is standard library. OOXML is a ZIP of XML parts, so `zipfile`
and a tag strip get the words out; a PDF's text lives in content streams that
are usually Flate-compressed, which is `zlib`. That keeps a documentation-grade
dependency out of the service — the same reasoning `handbook/tools/pdf.py`
records for writing PDFs — at the cost of being best-effort on PDFs, which is
stated rather than hidden: a scanned page yields nothing, and says nothing,
instead of yielding noise.
"""

from __future__ import annotations

import io
import re
import zipfile
import zlib
from xml.sax.saxutils import unescape

#: `PK\x03\x04` is a ZIP local file header, which every OOXML document opens
#: with. Sniffed rather than trusting a filename: the upload path takes a name
#: from the client and the link path derives one from a URL, and neither is a
#: promise about the bytes.
_ZIP_MAGIC = b"PK\x03\x04"
_PDF_MAGIC = b"%PDF"

_TAG_RE = re.compile(r"<[^>]+>")
_PDF_STREAM_RE = re.compile(rb"stream\r?\n(.*?)\r?\nendstream", re.S)
#: A PDF string literal, honouring backslash escapes so `\)` does not end it.
_PDF_LITERAL_RE = re.compile(rb"\((?:[^()\\]|\\.)*\)", re.S)
_SLIDE_NUMBER_RE = re.compile(r"(\d+)")


def extract_text(content: bytes) -> str:
    """Decodes a document's raw bytes into text for chunking (PRD FR-3.3)."""

    if not content:
        return ""
    if content.startswith(_ZIP_MAGIC):
        return _from_ooxml(content)
    if content.startswith(_PDF_MAGIC):
        return _from_pdf(content)
    return _decode(content)


def _decode(content: bytes) -> str:
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError:
        return content.decode("utf-8", errors="replace")


# ── OOXML: Word, PowerPoint, Excel ───────────────────────────────────────


def _from_ooxml(content: bytes) -> str:
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            names = set(archive.namelist())

            if "word/document.xml" in names:
                return _from_word(archive.read("word/document.xml"))

            slides = sorted(
                (name for name in names
                 if name.startswith("ppt/slides/slide") and name.endswith(".xml")),
                key=_slide_order,
            )
            if slides:
                return "\n\n".join(
                    _from_slide(archive.read(name)) for name in slides
                ).strip()

            if "xl/sharedStrings.xml" in names:
                return _from_shared_strings(archive.read("xl/sharedStrings.xml"))
    except (zipfile.BadZipFile, KeyError, OSError):
        # A truncated or malformed archive is a broken document, not a text
        # one. Decoding the bytes instead would turn it into the noise this
        # module exists to stop.
        return ""
    return ""


def _slide_order(name: str) -> tuple[int, str]:
    """`slide10.xml` sorts after `slide2.xml`, which a string sort reverses."""
    found = _SLIDE_NUMBER_RE.search(name.rsplit("/", 1)[-1])
    return (int(found.group(1)) if found else 0, name)


def _from_word(part: bytes) -> str:
    xml = part.decode("utf-8", errors="replace")
    # Paragraph and explicit line breaks are the only structure worth keeping:
    # the chunker downstream splits on what it can see, and a document flattened
    # to one line gives it nothing. Runs inside a paragraph are joined with no
    # separator, because Word splits a word across runs wherever formatting
    # changes mid-word — "Zephyr **WMS**" is two runs and one term.
    xml = re.sub(r"</w:p>", "\n", xml)
    xml = re.sub(r"<w:br\s*/?>", "\n", xml)
    xml = re.sub(r"<w:tab\s*/?>", "\t", xml)
    return _strip(xml)


def _from_slide(part: bytes) -> str:
    xml = part.decode("utf-8", errors="replace")
    xml = re.sub(r"</a:p>", "\n", xml)
    return _strip(xml)


def _from_shared_strings(part: bytes) -> str:
    xml = part.decode("utf-8", errors="replace")
    # One string per cell value; the sheet itself is mostly numbers and
    # references, and the words a spreadsheet contributes are all here.
    xml = re.sub(r"</si>", "\n", xml)
    return _strip(xml)


def _strip(xml: str) -> str:
    text = unescape(_TAG_RE.sub("", xml), {"&quot;": '"', "&apos;": "'"})
    lines = [line.strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line).strip()


# ── PDF ──────────────────────────────────────────────────────────────────


def _from_pdf(content: bytes) -> str:
    """Best-effort text from a PDF's content streams.

    Real coverage of PDF text extraction — encodings, font maps, ligatures,
    layout order — is a library's worth of work. What is here handles the
    common case (Flate-compressed streams of `Tj`/`TJ` operators) and returns
    nothing rather than guessing on anything else.
    """

    pieces: list[str] = []
    for raw in _PDF_STREAM_RE.findall(content):
        stream = raw
        try:
            stream = zlib.decompress(raw)
        except zlib.error:
            # Either uncompressed, or a filter this does not implement. Reading
            # it as-is costs nothing: a stream that is not text yields no
            # literals and contributes nothing.
            pass
        shown = [
            _pdf_literal(match) for match in _PDF_LITERAL_RE.findall(stream)
        ]
        line = "".join(shown).strip()
        if line:
            pieces.append(line)
    return "\n".join(pieces).strip()


def _pdf_literal(literal: bytes) -> str:
    body = literal[1:-1]
    body = re.sub(rb"\\([()\\])", rb"\1", body)
    body = body.replace(rb"\n", b"\n").replace(rb"\t", b"\t")
    return body.decode("utf-8", errors="replace")
