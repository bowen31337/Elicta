"""Reading PNG files into something a PDF can embed. Standard library only.

There is a pleasant coincidence at the heart of this file. A PNG stores its
pixels as zlib-compressed scanlines, each prefixed with a filter byte — and
PDF's FlateDecode understands exactly that arrangement, under the name "PNG
predictor 15". So for an ordinary 8-bit colour or greyscale image the bytes
are handed straight across without being decompressed at all: no decoding,
no re-compression, no loss, and a smaller file than either.

The two cases that cannot take that path are transparency and a palette,
because PDF would need a separate mask or an indexed colour space to
reproduce them. Those are decoded here and flattened to plain colour —
transparency composited onto white, since these are screenshots of an
opaque interface.
"""

from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass
from pathlib import Path

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"

#: Bytes per pixel for each PNG colour type, at 8 bits per channel.
_CHANNELS = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}


class UnsupportedImage(Exception):
    """The file cannot be embedded, and the message says why."""


#: Never crop away more than this share of an image. A screenshot that is
#: genuinely mostly empty is showing you that it is mostly empty.
MAX_CROP = 0.65
#: Rows of clear space left below the content, so a crop does not look like
#: a mistake.
CROP_MARGIN = 24


@dataclass(frozen=True)
class Image:
    width: int
    height: int
    #: The zlib stream to embed, exactly as PDF will receive it.
    data: bytes
    #: 1 for greyscale, 3 for colour.
    colors: int
    #: True when `data` is still PNG-filtered and PDF must undo it.
    predictor: bool
    #: Height up to the last row that differs from the one above it. A
    #: screenshot of a mostly-empty panel carries half a page of dead space,
    #: and showing it whole wastes the page without telling the reader
    #: anything.
    content_height: int = 0

    @property
    def aspect(self) -> float:
        return self.height / self.width if self.width else 1.0

    @property
    def visible_share(self) -> float:
        """How much of the image, from the top, is worth showing."""
        if not self.height:
            return 1.0
        return min(1.0, self.content_height / self.height)


def read_png(path: Path) -> Image:
    return read_png_bytes(Path(path).read_bytes())


def read_png_bytes(data: bytes) -> Image:
    if not data.startswith(PNG_SIGNATURE):
        raise UnsupportedImage("not a PNG file")

    width = height = depth = colour_type = interlace = 0
    idat = bytearray()
    palette = b""
    position = len(PNG_SIGNATURE)
    while position + 8 <= len(data):
        length = struct.unpack(">I", data[position:position + 4])[0]
        kind = data[position + 4:position + 8]
        payload = data[position + 8:position + 8 + length]
        position += 12 + length
        if kind == b"IHDR":
            width, height, depth, colour_type, _comp, _filt, interlace = \
                struct.unpack(">IIBBBBB", payload)
        elif kind == b"IDAT":
            idat += payload            # large encoders split the pixels up
        elif kind == b"PLTE":
            palette = payload
        elif kind == b"IEND":
            break

    if not width or not height:
        raise UnsupportedImage("the PNG has no image header")
    if depth != 8:
        raise UnsupportedImage(f"only 8 bits per channel is supported, not {depth}")
    if interlace:
        raise UnsupportedImage("interlaced PNGs are not supported")
    if colour_type not in _CHANNELS:
        raise UnsupportedImage(f"unknown PNG colour type {colour_type}")

    if colour_type in (0, 2):
        # The pleasant case: PDF can undo the PNG filtering itself.
        channels = _CHANNELS[colour_type]
        content = _content_height_filtered(bytes(idat), width * channels, height)
        return Image(width, height, bytes(idat), channels, True, content)

    pixels = _decode(bytes(idat), width, height, _CHANNELS[colour_type])
    if colour_type == 3:
        pixels = _from_palette(pixels, palette)
    elif colour_type == 6:
        pixels = _flatten_alpha(pixels, 3)
    else:                                   # colour type 4: grey plus alpha
        pixels = _flatten_alpha(pixels, 1)
        content = _content_height_raw(pixels, width, height)
        return Image(width, height, zlib.compress(pixels, 9), 1, False, content)
    content = _content_height_raw(pixels, width * 3, height)
    return Image(width, height, zlib.compress(pixels, 9), 3, False, content)


def _clamp(content: int, height: int) -> int:
    return max(int(height * (1.0 - MAX_CROP)), min(height, content + CROP_MARGIN))


def _content_height_filtered(compressed: bytes, stride: int, height: int) -> int:
    """Find the blank tail without undoing a single filter.

    A row identical to the one above is written as filter 2 with all-zero
    deltas, so the run at the foot of the image can be counted straight off
    the decompressed-but-still-filtered bytes. Decompression is C; the loop
    below touches one row per iteration, not one pixel.
    """
    try:
        raw = zlib.decompress(compressed)
    except zlib.error:
        return height
    zeros = b"\x00" * stride
    blank = 0
    for row in range(height - 1, 0, -1):
        start = row * (stride + 1)
        if raw[start:start + 1] == b"\x02" and raw[start + 1:start + 1 + stride] == zeros:
            blank += 1
        else:
            break
    return _clamp(height - blank, height)


def _content_height_raw(pixels: bytes, stride: int, height: int) -> int:
    """The same question, for images that had to be decoded anyway."""
    blank = 0
    for row in range(height - 1, 0, -1):
        this = pixels[row * stride:(row + 1) * stride]
        above = pixels[(row - 1) * stride:row * stride]
        if this == above:
            blank += 1
        else:
            break
    return _clamp(height - blank, height)


# ── The decoding path ────────────────────────────────────────────────────


def _decode(compressed: bytes, width: int, height: int, channels: int) -> bytes:
    """Undo zlib and the per-scanline PNG filters."""
    try:
        raw = zlib.decompress(compressed)
    except zlib.error as error:
        raise UnsupportedImage(f"the pixel data could not be read: {error}") from error

    stride = width * channels
    out = bytearray()
    previous = bytearray(stride)
    position = 0
    for _row in range(height):
        if position >= len(raw):
            break
        filter_type = raw[position]
        line = bytearray(raw[position + 1:position + 1 + stride])
        position += 1 + stride
        if filter_type == 0:
            pass
        elif filter_type == 1:                                  # Sub
            for i in range(channels, len(line)):
                line[i] = (line[i] + line[i - channels]) & 0xFF
        elif filter_type == 2:                                  # Up
            for i in range(len(line)):
                line[i] = (line[i] + previous[i]) & 0xFF
        elif filter_type == 3:                                  # Average
            for i in range(len(line)):
                left = line[i - channels] if i >= channels else 0
                line[i] = (line[i] + ((left + previous[i]) >> 1)) & 0xFF
        elif filter_type == 4:                                  # Paeth
            for i in range(len(line)):
                left = line[i - channels] if i >= channels else 0
                up = previous[i]
                upper_left = previous[i - channels] if i >= channels else 0
                line[i] = (line[i] + _paeth(left, up, upper_left)) & 0xFF
        else:
            raise UnsupportedImage(f"unknown PNG scanline filter {filter_type}")
        out += line
        previous = line
    return bytes(out)


def _paeth(left: int, up: int, upper_left: int) -> int:
    estimate = left + up - upper_left
    da, db, dc = abs(estimate - left), abs(estimate - up), abs(estimate - upper_left)
    if da <= db and da <= dc:
        return left
    return up if db <= dc else upper_left


def _flatten_alpha(pixels: bytes, colours: int) -> bytes:
    """Composite onto white. These are screenshots of an opaque interface,
    so anything transparent is background rather than meaningful."""
    step = colours + 1
    out = bytearray()
    for start in range(0, len(pixels) - colours, step):
        alpha = pixels[start + colours]
        for channel in range(colours):
            value = pixels[start + channel]
            out.append(value if alpha == 255 else
                       (value * alpha + 255 * (255 - alpha)) // 255)
    return bytes(out)


def _from_palette(indexes: bytes, palette: bytes) -> bytes:
    if not palette:
        raise UnsupportedImage("a palette image with no palette")
    out = bytearray()
    for index in indexes:
        start = index * 3
        out += palette[start:start + 3] or b"\x00\x00\x00"
    return bytes(out)
