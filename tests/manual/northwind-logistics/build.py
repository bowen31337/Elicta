#!/usr/bin/env python3
"""Builds the Northwind Logistics documents used for testing preparation by hand.

Run from anywhere:

    python3 tests/manual/northwind-logistics/build.py

The generated files are committed beside this script, so nobody has to run it to
use them — it exists so the *content* can be edited and the documents rebuilt,
rather than the documents being opaque binaries nobody can change.

Stdlib only, deliberately. Elicta reads a document with `zipfile` and `zlib` and
nothing else (`engagement/index/extraction.py`), so anything a real library
would produce that those two cannot read would make a fixture that tests the
fixture rather than the product. What this writes is what that reader can read.

The content is not filler. Each document carries something a specific part of
Elicta is supposed to react to, and the README beside it says which.
"""

from __future__ import annotations

import pathlib
import zipfile
import zlib

HERE = pathlib.Path(__file__).resolve().parent

# ── OOXML plumbing ───────────────────────────────────────────────────────
#
# Elicta reads exactly one part per format — `word/document.xml`,
# `ppt/slides/slideN.xml`, `xl/sharedStrings.xml` — and ignores everything
# else. That alone would make a valid fixture and an unopenable file, which is
# a bad trade for documents a person is meant to test with: the first thing
# anyone does with a test document is look inside it.
#
# So Word and Excel get the relationship parts that make a real package, and
# open normally. PowerPoint does not: a slide is meaningless to it without a
# layout, which needs a master, which needs a theme, and the theme alone is
# longer than this whole file. The deck is a reader fixture and says so.

_RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    "{items}</Relationships>"
)

_OFFICE = "http://schemas.openxmlformats.org/officeDocument/2006"
_W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
_A = 'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"'
_S = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _content_types(overrides: dict[str, str]) -> str:
    parts = "".join(
        f'<Override PartName="{name}" ContentType="{kind}"/>'
        for name, kind in overrides.items()
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.'
        'relationships+xml"/><Default Extension="xml" ContentType="application/xml"/>'
        f"{parts}</Types>"
    )


def write_docx(path: pathlib.Path, paragraphs: list[str]) -> None:
    body = "".join(
        f"<w:p><w:r><w:t xml:space='preserve'>{_escape(line)}</w:t></w:r></w:p>"
        for line in paragraphs
    )
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "[Content_Types].xml",
            _content_types(
                {
                    "/word/document.xml": "application/vnd.openxmlformats-officedocument."
                    "wordprocessingml.document.main+xml"
                }
            ),
        )
        archive.writestr(
            "_rels/.rels",
            _RELS.format(
                items=f'<Relationship Id="rId1" Type="{_OFFICE}/relationships/'
                f'officeDocument" Target="word/document.xml"/>'
            ),
        )
        archive.writestr(
            "word/document.xml",
            f"<?xml version='1.0' encoding='UTF-8' standalone='yes'?>"
            f"<w:document {_W}><w:body>{body}"
            f"<w:sectPr><w:pgSz w:w='11906' w:h='16838'/></w:sectPr>"
            f"</w:body></w:document>",
        )


def write_pptx(path: pathlib.Path, slides: list[list[str]]) -> None:
    """Slide parts only — a reader fixture, not a presentation. See above."""

    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", _content_types({}))
        for index, lines in enumerate(slides, start=1):
            paragraphs = "".join(
                f"<a:p><a:r><a:t>{_escape(line)}</a:t></a:r></a:p>" for line in lines
            )
            archive.writestr(
                f"ppt/slides/slide{index}.xml",
                f"<?xml version='1.0' encoding='UTF-8' standalone='yes'?>"
                f"<p:sld {_A} xmlns:p='http://schemas.openxmlformats.org/"
                f"presentationml/2006/main'><p:cSld><p:spTree>"
                f"<p:sp><p:txBody>{paragraphs}</p:txBody></p:sp>"
                f"</p:spTree></p:cSld></p:sld>",
            )


def write_xlsx(path: pathlib.Path, rows: list[list[str]]) -> None:
    """A real single-sheet workbook, laid out as a grid rather than a list.

    Every value goes in the shared-string table — which is the part Elicta
    reads — *and* is referenced from a cell, which is what makes the sheet show
    anything when somebody opens it.
    """

    flat: list[str] = []
    index_of: dict[str, int] = {}
    for row in rows:
        for value in row:
            if value not in index_of:
                index_of[value] = len(flat)
                flat.append(value)

    sheet_rows = []
    for number, row in enumerate(rows, start=1):
        cells = "".join(
            f'<c r="{chr(ord("A") + column)}{number}" t="s">'
            f"<v>{index_of[value]}</v></c>"
            for column, value in enumerate(row)
        )
        sheet_rows.append(f'<row r="{number}">{cells}</row>')

    strings = "".join(f"<si><t xml:space='preserve'>{_escape(v)}</t></si>" for v in flat)

    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "[Content_Types].xml",
            _content_types(
                {
                    "/xl/workbook.xml": "application/vnd.openxmlformats-officedocument."
                    "spreadsheetml.sheet.main+xml",
                    "/xl/worksheets/sheet1.xml": "application/vnd.openxmlformats-"
                    "officedocument.spreadsheetml.worksheet+xml",
                    "/xl/sharedStrings.xml": "application/vnd.openxmlformats-"
                    "officedocument.spreadsheetml.sharedStrings+xml",
                }
            ),
        )
        archive.writestr(
            "_rels/.rels",
            _RELS.format(
                items=f'<Relationship Id="rId1" Type="{_OFFICE}/relationships/'
                f'officeDocument" Target="xl/workbook.xml"/>'
            ),
        )
        archive.writestr(
            "xl/_rels/workbook.xml.rels",
            _RELS.format(
                items=f'<Relationship Id="rId1" Type="{_OFFICE}/relationships/'
                f'worksheet" Target="worksheets/sheet1.xml"/>'
                f'<Relationship Id="rId2" Type="{_OFFICE}/relationships/'
                f'sharedStrings" Target="sharedStrings.xml"/>'
            ),
        )
        archive.writestr(
            "xl/workbook.xml",
            f"<?xml version='1.0' encoding='UTF-8' standalone='yes'?>"
            f"<workbook xmlns='{_S}' xmlns:r='{_OFFICE}/relationships'><sheets>"
            f"<sheet name='Throughput' sheetId='1' r:id='rId1'/></sheets></workbook>",
        )
        archive.writestr(
            "xl/worksheets/sheet1.xml",
            f"<?xml version='1.0' encoding='UTF-8' standalone='yes'?>"
            f"<worksheet xmlns='{_S}'><sheetData>{''.join(sheet_rows)}</sheetData>"
            f"</worksheet>",
        )
        archive.writestr(
            "xl/sharedStrings.xml",
            f"<?xml version='1.0' encoding='UTF-8' standalone='yes'?>"
            f"<sst xmlns='{_S}' count='{len(flat)}' uniqueCount='{len(flat)}'>"
            f"{strings}</sst>",
        )


# ── PDF ──────────────────────────────────────────────────────────────────


def write_pdf(path: pathlib.Path, lines: list[str]) -> None:
    """A one-page PDF whose text Elicta's reader can recover.

    Flate-compressed content stream of `Tj` operators, which is the shape
    `_from_pdf` handles. Anything cleverer — font subsetting, ligatures, a real
    layout engine — produces a file it reads as nothing, which is the "scanned
    page" case the journey already documents.
    """

    escaped = [line.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)") for line in lines]
    # Each string literal ends with a `\n` escape. A PDF renderer treats that as
    # a line feed inside the string and lays the line out using `T*` as usual,
    # so the page is unchanged — but Elicta's reader joins every literal in a
    # stream with nothing between them, and turns that escape into a real
    # newline. Without it the whole document extracts as one run-on line and the
    # chunker downstream has no structure to split on.
    body = (
        "BT /F1 11 Tf 56 760 Td 15 TL\n"
        + "\n".join(rf"({line}\n) Tj T*" for line in escaped)
        + "\nET"
    )
    stream = zlib.compress(body.encode("latin-1", errors="replace"))

    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length %d /Filter /FlateDecode >>\nstream\n" % len(stream)
        + stream
        + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]

    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, payload in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + payload + b"\nendobj\n"

    xref = len(out)
    out += b"xref\n0 %d\n" % (len(objects) + 1)
    out += b"0000000000 65535 f \n"
    for offset in offsets:
        out += b"%010d 00000 n \n" % offset
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1,
        xref,
    )
    path.write_bytes(bytes(out))


# ── The documents ────────────────────────────────────────────────────────
#
# Northwind Logistics is rebuilding depot scheduling across three sites, one of
# which is in Shenzhen. That last detail is what makes Elicta expect Mandarin in
# the room without anyone choosing a language.

SCOPING_DECK = [
    [
        "Northwind Logistics — Depot Scheduling Rebuild",
        "Scoping workshop pack, prepared by the Northwind operations team",
        "Sites in scope: Felixstowe, Rotterdam, Shenzhen (深圳)",
    ],
    [
        "Where we are now",
        "Depot slots are booked by phone and written on a whiteboard.",
        "Zephyr WMS holds stock but knows nothing about arrivals.",
        "The TMS handoff to Zephyr is a nightly CSV, and it is often wrong.",
        "Drivers wait an average of 41 minutes at Felixstowe before a bay frees up.",
    ],
    [
        "What good looks like",
        "Booking a slot should be fast.",
        "Planners should have visibility of the whole network.",
        "The system needs to scale.",
        "We want a modern, flexible platform.",
    ],
    [
        "Volumes, as measured in March",
        "Felixstowe handles 3,500,000 consignments a year.",
        "Rotterdam handles roughly half that.",
        "Shenzhen is growing and we do not have a firm number yet.",
        "Peak week is the third week of November.",
    ],
    [
        "Constraints we already know about",
        "Zephyr WMS cannot be replaced before its contract ends in 2028.",
        "Customs data for Shenzhen must stay inside mainland China.",
        "Any change to the driver app needs a two-week rollout window.",
    ],
    [
        "Open with the client",
        "Who owns the decision on the slot-booking rules?",
        "Is the 41 minutes measured door to door, or bay to bay?",
        "What happens to a booking when a vessel is late?",
    ],
]

THROUGHPUT_STUDY = [
    ["Northwind Logistics — depot throughput study"],
    ["Prepared by Northwind operations, March"],
    [],
    ["Site", "Consignments per year", "Bays", "Average driver wait (minutes)", "Peak week uplift"],
    ["Felixstowe", "3,500,000", "14", "41", "2.3x"],
    ["Rotterdam", "1,700,000", "9", "26", "1.9x"],
    ["Shenzhen", "not yet measured", "6", "not yet measured", "not yet measured"],
    [],
    ["Note: Felixstowe figures are from the Zephyr WMS export and exclude "
     "consignments cancelled before arrival."],
    ["Note: the Shenzhen depot opened in January and has no full quarter of data."],
    ["Note: driver wait is measured from gate scan to bay assignment, not to departure."],
]

INTEGRATION_ASSUMPTIONS = [
    "Northwind Logistics — integration assumptions",
    "",
    "This is our working view before the workshop. None of it has been "
    "confirmed by the client, and every line here is something to verify "
    "rather than something to rely on.",
    "",
    "1. Zephyr WMS exposes a REST API we can call directly.",
    "",
    "We assume slot bookings can be written into Zephyr in near real time "
    "rather than batched overnight. If it turns out to be the nightly CSV "
    "the scoping pack describes, the whole real-time story changes.",
    "",
    "2. Felixstowe handles about 350,000 consignments a year.",
    "",
    "Taken from the 2024 proposal. Worth checking against the throughput "
    "study, which reports a different order of magnitude.",
    "",
    "3. There is one customs integration, not three.",
    "",
    "We assume a single customs interface across all sites. Shenzhen may "
    "need its own, and the data-residency constraint suggests it will.",
    "",
    "4. The driver app is ours to change.",
    "",
    "We assume Northwind owns the driver app outright. If it is licensed, "
    "the two-week rollout window is somebody else's to grant.",
    "",
    "5. Planners will accept a web interface.",
    "",
    "We assume no native application is required. This has not been tested "
    "with anyone who does the job.",
]

OLD_PROPOSAL = [
    "Northwind Logistics - depot scheduling proposal (2024)",
    "",
    "SUPERSEDED. This proposal was written before the Shenzhen depot opened",
    "and before the March throughput study. It is kept for background only.",
    "",
    "Scope",
    "",
    "Two sites: Felixstowe and Rotterdam. Shenzhen is not mentioned because",
    "the site did not exist when this was written.",
    "",
    "Volumes",
    "",
    "Felixstowe handles approximately 350,000 consignments a year.",
    "Rotterdam handles approximately 200,000 consignments a year.",
    "",
    "Approach",
    "",
    "Replace Zephyr WMS outright in the first phase, then build slot booking",
    "on top of the replacement.",
    "",
    "Commercials",
    "",
    "Fixed price, eleven months, one delivery team.",
]

BRIEFING_NOTE = [
    "Northwind Logistics — briefing note for the Shenzhen session",
    "",
    "The Shenzhen depot team will join the discovery session. The site "
    "manager and the two shift planners are more comfortable in Mandarin, "
    "and the customs lead speaks both.",
    "",
    "Expect the conversation to switch languages without warning, "
    "particularly around numbers.",
    "",
    "客户方参与人员:深圳仓库经理、两名排班主管、一名报关负责人。",
    "",
    "深圳仓目前每月处理约三百五十万件货物,但这个数字尚未经过核实。",
    "",
    "报关数据必须留在中国境内,这一点没有商量余地。",
    "",
    "他们提到「我们再看看」的时候,通常不是同意的意思。",
]


def build() -> list[pathlib.Path]:
    written: list[pathlib.Path] = []

    deck = HERE / "01-scoping-deck.pptx"
    write_pptx(deck, SCOPING_DECK)
    written.append(deck)

    study = HERE / "02-throughput-study.xlsx"
    write_xlsx(study, THROUGHPUT_STUDY)
    written.append(study)

    assumptions = HERE / "03-integration-assumptions.docx"
    write_docx(assumptions, INTEGRATION_ASSUMPTIONS)
    written.append(assumptions)

    proposal = HERE / "04-proposal-2024-superseded.pdf"
    write_pdf(proposal, OLD_PROPOSAL)
    written.append(proposal)

    briefing = HERE / "05-shenzhen-briefing-note.docx"
    write_docx(briefing, BRIEFING_NOTE)
    written.append(briefing)

    return written


if __name__ == "__main__":
    for written in build():
        print(f"{written.relative_to(HERE.parent.parent.parent)}  ({written.stat().st_size:,} bytes)")
