"""Extracting text from the formats a real reference document arrives in.

`extract_text` decoded every document as UTF-8. For the `.txt` and `.md` the
tests covered that was right; for the `.docx`, `.pptx` and `.pdf` a client
actually sends it produced a page of U+FFFD, which chunked and indexed
perfectly well and meant nothing. Nothing failed — the document simply
contributed noise to retrieval and to the compiler that reads it.

The fixtures here are built rather than checked in: a real ZIP with real
OOXML parts, and a real PDF with a real Flate-compressed content stream, so
what is under test is the format and not a recording of one file.
"""

from __future__ import annotations

import io
import zipfile
import zlib

from .extraction import extract_text

WORD_NS = (
    'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
)
DRAW_NS = 'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"'
SHEET_NS = (
    'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
)


def _zip(parts: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, text in parts.items():
            archive.writestr(name, text)
    return buffer.getvalue()


def _docx(paragraphs: list[str]) -> bytes:
    body = "".join(
        f"<w:p><w:r><w:t>{text}</w:t></w:r></w:p>" for text in paragraphs
    )
    return _zip({
        "[Content_Types].xml": "<Types/>",
        "word/document.xml": f"<w:document {WORD_NS}><w:body>{body}</w:body></w:document>",
    })


def _pptx(slides: list[list[str]]) -> bytes:
    parts = {"[Content_Types].xml": "<Types/>"}
    for number, runs in enumerate(slides, start=1):
        text = "".join(f"<a:p><a:r><a:t>{run}</a:t></a:r></a:p>" for run in runs)
        parts[f"ppt/slides/slide{number}.xml"] = f"<p:sld {DRAW_NS}>{text}</p:sld>"
    return _zip(parts)


def _xlsx(strings: list[str]) -> bytes:
    items = "".join(f"<si><t>{value}</t></si>" for value in strings)
    return _zip({
        "[Content_Types].xml": "<Types/>",
        "xl/sharedStrings.xml": f"<sst {SHEET_NS}>{items}</sst>",
    })


def _pdf(lines: list[str]) -> bytes:
    shown = " ".join(f"({line}) Tj" for line in lines)
    stream = zlib.compress(f"BT /F1 12 Tf {shown} ET".encode())
    return b"".join([
        b"%PDF-1.4\n",
        b"4 0 obj\n<< /Length ",
        str(len(stream)).encode("ascii"),
        b" /Filter /FlateDecode >>\nstream\n",
        stream,
        b"\nendstream\nendobj\n%%EOF\n",
    ])


class TestWordDocuments:
    def test_the_words_come_out_and_the_markup_does_not(self):
        result = extract_text(_docx(["Scope: rebuild the intake pipeline."]))

        assert "Scope: rebuild the intake pipeline." in result
        assert "<w:t>" not in result
        assert "�" not in result

    def test_each_paragraph_is_kept_apart(self):
        result = extract_text(_docx(["First requirement.", "Second requirement."]))

        # Joined without a break the two sentences run together into one line,
        # and the chunker downstream splits on structure it can see.
        assert "First requirement." in result
        assert "Second requirement." in result
        assert result.index("First") < result.index("Second")
        assert "\n" in result.strip()

    def test_a_run_split_by_formatting_is_rejoined(self):
        # Word splits a word across runs whenever formatting changes mid-word,
        # so "Zephyr WMS" with a bolded "WMS" is two runs in one paragraph.
        split = _zip({
            "word/document.xml": (
                f"<w:document {WORD_NS}><w:body><w:p>"
                "<w:r><w:t>Zephyr </w:t></w:r><w:r><w:t>WMS</w:t></w:r>"
                "</w:p></w:body></w:document>"
            ),
        })

        assert "Zephyr WMS" in extract_text(split)


class TestPresentations:
    def test_text_from_every_slide_is_included(self):
        result = extract_text(_pptx([["Current state"], ["Target state"]]))

        assert "Current state" in result
        assert "Target state" in result

    def test_slides_are_read_in_order_not_alphabetically(self):
        # slide10 sorts before slide2 as a string, which silently reorders a
        # deck of ten or more.
        deck = _pptx([[f"Slide {n}"] for n in range(1, 12)])

        result = extract_text(deck)

        assert result.index("Slide 2") < result.index("Slide 10")


class TestSpreadsheets:
    def test_the_shared_strings_are_read(self):
        result = extract_text(_xlsx(["Consignment volume", "Cross-dock"]))

        assert "Consignment volume" in result
        assert "Cross-dock" in result


class TestPdfs:
    def test_text_in_a_compressed_stream_is_recovered(self):
        result = extract_text(_pdf(["Warehouse throughput study 2025"]))

        assert "Warehouse throughput study 2025" in result

    def test_a_pdf_with_nothing_extractable_returns_empty_rather_than_binary(self):
        # A scanned page is an image with no text operators at all. Returning
        # the raw bytes decoded would hand retrieval a page of noise that reads
        # as content; empty is honest and the caller can say so.
        scanned = b"%PDF-1.4\n4 0 obj\n<< /Length 3 >>\nstream\n\x00\x01\x02\nendstream\nendobj\n%%EOF\n"

        assert extract_text(scanned).strip() == ""


class TestTheFormatsThatAlreadyWorked:
    def test_plain_text_is_still_verbatim(self):
        assert extract_text(b"Scope: rebuild.") == "Scope: rebuild."

    def test_a_zip_that_is_not_an_office_document_does_not_raise(self):
        assert isinstance(extract_text(_zip({"notes.txt": "hello"})), str)

    def test_a_truncated_zip_degrades_rather_than_raising(self):
        assert isinstance(extract_text(_docx(["x"])[:40]), str)
