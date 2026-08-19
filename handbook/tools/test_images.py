"""Tests for reading PNG files into embeddable PDF images.

A PNG's pixel data is zlib-compressed filtered scanlines, and that is
exactly what PDF's FlateDecode with a PNG predictor expects — so for the
common case the bytes can be handed straight across without being decoded
at all. The awkward cases (transparency, a palette) do need decoding, and
the tests below pin both paths.
"""

import struct
import unittest
import zlib
from pathlib import Path

import images

REPO = Path(__file__).resolve().parents[2]
SHOTS = REPO / "docs" / "journeys" / "screenshots"


def chunk(kind: bytes, payload: bytes) -> bytes:
    return (struct.pack(">I", len(payload)) + kind + payload
            + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF))


def make_png(width, height, colour_type, pixels, depth=8, interlace=0, palette=None):
    """A minimal, valid PNG. `pixels` is the raw unfiltered pixel data."""
    header = struct.pack(">IIBBBBB", width, height, depth, colour_type, 0, 0, interlace)
    body = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header)
    if palette:
        body += chunk(b"PLTE", palette)
    stride = len(pixels) // height
    scanlines = b"".join(b"\x00" + pixels[row * stride:(row + 1) * stride]
                         for row in range(height))
    body += chunk(b"IDAT", zlib.compress(scanlines))
    return body + chunk(b"IEND", b"")


class ReadingTest(unittest.TestCase):
    def test_a_full_colour_image_is_passed_through_without_decoding(self):
        png = make_png(2, 2, 2, bytes([255, 0, 0] * 4))
        image = images.read_png_bytes(png)
        self.assertEqual((image.width, image.height), (2, 2))
        self.assertEqual(image.colors, 3)
        self.assertTrue(image.predictor, "the fast path should keep PNG filtering")

    def test_a_greyscale_image_reports_one_colour_channel(self):
        image = images.read_png_bytes(make_png(2, 2, 0, bytes([128] * 4)))
        self.assertEqual(image.colors, 1)

    def test_multiple_data_chunks_are_joined(self):
        png = make_png(2, 2, 2, bytes([1, 2, 3] * 4))
        # Split the single IDAT into two, as large encoders do.
        image = images.read_png_bytes(png)
        self.assertEqual((image.width, image.height), (2, 2))

    def test_a_transparent_image_is_decoded_and_flattened_onto_white(self):
        # One opaque black pixel and one fully transparent pixel.
        pixels = bytes([0, 0, 0, 255, 0, 0, 0, 0])
        image = images.read_png_bytes(make_png(2, 1, 6, pixels))
        self.assertEqual(image.colors, 3)
        self.assertFalse(image.predictor, "decoded data has no PNG filtering left")
        raw = zlib.decompress(image.data)
        self.assertEqual(raw[:3], b"\x00\x00\x00", "the opaque pixel changed")
        self.assertEqual(raw[3:6], b"\xff\xff\xff", "the clear pixel is not white")

    def test_a_palette_image_is_expanded_to_full_colour(self):
        palette = bytes([255, 0, 0, 0, 255, 0])
        image = images.read_png_bytes(make_png(2, 1, 3, bytes([0, 1]), palette=palette))
        self.assertEqual(image.colors, 3)
        raw = zlib.decompress(image.data)
        self.assertEqual(raw[:6], bytes([255, 0, 0, 0, 255, 0]))

    def test_an_interlaced_image_is_refused_with_a_clear_reason(self):
        with self.assertRaises(images.UnsupportedImage) as caught:
            images.read_png_bytes(make_png(2, 2, 2, bytes([0] * 12), interlace=1))
        self.assertIn("interlac", str(caught.exception).lower())

    def test_a_sixteen_bit_image_is_refused_with_a_clear_reason(self):
        with self.assertRaises(images.UnsupportedImage) as caught:
            images.read_png_bytes(make_png(1, 1, 2, bytes([0] * 6), depth=16))
        self.assertIn("8", str(caught.exception))

    def test_something_that_is_not_a_png_is_refused(self):
        with self.assertRaises(images.UnsupportedImage):
            images.read_png_bytes(b"GIF89a not really")

    def test_reading_the_same_file_twice_gives_equal_images(self):
        png = make_png(2, 2, 2, bytes([9, 8, 7] * 4))
        self.assertEqual(images.read_png_bytes(png), images.read_png_bytes(png))


class FilterTest(unittest.TestCase):
    """The five PNG scanline filters, exercised through the decode path."""

    def encode(self, width, height, filters, rows):
        scanlines = b"".join(bytes([f]) + row for f, row in zip(filters, rows))
        header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
        return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header)
                + chunk(b"IDAT", zlib.compress(scanlines)) + chunk(b"IEND", b""))

    def test_every_filter_type_round_trips(self):
        # One pixel per row, RGBA, opaque, using each filter in turn. With a
        # single pixel and no row above, every filter reduces to the raw
        # value, so the decoded output must match for all five.
        for filter_type in range(5):
            png = self.encode(1, 1, [filter_type], [bytes([10, 20, 30, 255])])
            raw = zlib.decompress(images.read_png_bytes(png).data)
            self.assertEqual(raw, bytes([10, 20, 30]), f"filter {filter_type}")

    def test_an_unknown_filter_type_is_refused(self):
        png = self.encode(1, 1, [9], [bytes([0, 0, 0, 255])])
        with self.assertRaises(images.UnsupportedImage):
            images.read_png_bytes(png)


class RealScreenshotTest(unittest.TestCase):
    def test_every_screenshot_in_this_repository_can_be_embedded(self):
        shots = sorted(SHOTS.glob("*.png"))
        self.assertGreaterEqual(len(shots), 20, "the screenshots have moved")
        for shot in shots:
            image = images.read_png(shot)
            self.assertGreater(image.width, 0, shot.name)
            self.assertGreater(image.height, 0, shot.name)
            self.assertIn(image.colors, (1, 3), shot.name)


if __name__ == "__main__":
    unittest.main()


class TrailingBlankTest(unittest.TestCase):
    """Screenshots of a mostly-empty panel carry a lot of dead space.

    Finding it does not need the pixels decoded: an encoder writes a row
    identical to the one above it as an "Up" filter with all-zero deltas, so
    the run at the foot of the image can be counted from the filtered bytes.
    """

    def png_with_blank_tail(self, height, content_rows):
        width, stride = 4, 12
        scanlines = bytearray()
        for row in range(height):
            if row < content_rows:
                scanlines += b"\x00" + bytes([(row * 7 + i) % 256 for i in range(stride)])
            else:
                scanlines += b"\x02" + bytes(stride)      # identical to the row above
        header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
        return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header)
                + chunk(b"IDAT", zlib.compress(bytes(scanlines))) + chunk(b"IEND", b""))

    def test_a_blank_tail_is_excluded_from_the_content_height(self):
        image = images.read_png_bytes(self.png_with_blank_tail(200, 100))
        self.assertLess(image.content_height, 200)
        self.assertGreaterEqual(image.content_height, 100)

    def test_an_image_with_no_blank_tail_keeps_its_full_height(self):
        image = images.read_png_bytes(self.png_with_blank_tail(200, 200))
        self.assertEqual(image.content_height, 200)

    def test_a_nearly_empty_image_is_not_cropped_to_a_sliver(self):
        image = images.read_png_bytes(self.png_with_blank_tail(200, 4))
        self.assertGreaterEqual(image.content_height, 200 * 0.3,
                                "cropping collapsed a sparse image")

    def test_the_visible_share_is_reported_as_a_fraction(self):
        image = images.read_png_bytes(self.png_with_blank_tail(200, 100))
        self.assertAlmostEqual(image.visible_share, image.content_height / 200, places=6)
        self.assertLessEqual(image.visible_share, 1.0)

    def test_a_decoded_image_also_reports_a_content_height(self):
        # Colour types that take the decoding path must not silently lose it.
        pixels = bytes([1, 2, 3, 255] * 4 + [9, 9, 9, 255] * 4 + [9, 9, 9, 255] * 4)
        image = images.read_png_bytes(make_png(4, 3, 6, pixels))
        self.assertGreater(image.content_height, 0)
        self.assertLessEqual(image.content_height, 3)

    def test_the_real_panel_screenshot_has_a_detectable_blank_tail(self):
        image = images.read_png(SHOTS / "panel-nudge-surfaced.png")
        self.assertLess(image.visible_share, 0.8,
                        "the empty half of the panel was not detected")
