"""Generate every Elicta icon and favicon raster from the vector masters.

Run from the repo root:

    uv run --no-project --with cairosvg --with pillow python docs/brand/generate-icons.py
    (cd apps/desktop && pnpm tauri icon ../../docs/brand/elicta-icon-1024.png)

The second command turns the 1024 master into the platform set under
`apps/desktop/src-tauri/icons/` (.icns, .ico, iOS, Android, Windows tiles).

Colours are the same tokens the UI uses (`apps/desktop/src/tokens.css`), so
the icon set and the interface cannot drift apart:

    --blue  #007AFF light / #0A84FF dark   the mark
    --bg-secondary #1C1C1E                 top of the icon ground
"""

import io
import math
import struct
from pathlib import Path

import cairosvg
from PIL import Image, ImageDraw

BRAND = Path("docs/brand")
PUBLIC = Path("apps/desktop/public")

BLUE_DARK = "#0A84FF"
BLUE_LIGHT = "#007AFF"
GROUND_TOP = (28, 28, 30)     # #1C1C1E
GROUND_BOTTOM = (11, 11, 13)  # #0B0B0D
SEPARATOR = (198, 198, 200)   # #C6C6C8, --separator-opaque
SS = 4                        # supersample factor for the squircle


def render_mark(px: int, colour: str, *, small: bool = False) -> Image.Image:
    """Rasterise a vector master at px on a transparent ground.

    `small` selects the two-ring variant. The four-ring master loses its seams
    below about 24px, so anything at or under 16px must use the simplified one.
    """
    name = "elicta-mark-16.svg" if small else "elicta-mark.svg"
    src = (BRAND / name).read_text().replace("currentColor", colour)
    png = cairosvg.svg2png(bytestring=src.encode(), output_width=px, output_height=px)
    return Image.open(io.BytesIO(png)).convert("RGBA")


def squircle(size: int, n: float = 5.0) -> Image.Image:
    """Apple-style continuous-curvature rounded square, as an alpha mask.

    A superellipse |x|^n + |y|^n = 1, not a rounded rectangle: the curvature
    flows continuously into the straight edges instead of meeting them at a
    tangent discontinuity. That difference is most of why an iOS icon reads
    as an iOS icon.
    """
    big = size * SS
    img = Image.new("L", (big, big), 0)
    a = big / 2
    points = []
    for i in range(4096):
        t = 2 * math.pi * i / 4096
        ct, st = math.cos(t), math.sin(t)
        points.append((
            a + a * math.copysign(abs(ct) ** (2 / n), ct),
            a + a * math.copysign(abs(st) ** (2 / n), st),
        ))
    ImageDraw.Draw(img).polygon(points, fill=255)
    return img.resize((size, size), Image.LANCZOS)


def vertical_ramp(size: int, top: tuple[int, int, int], bottom: tuple[int, int, int]) -> Image.Image:
    column = Image.new("RGB", (1, size))
    for y in range(size):
        t = y / max(size - 1, 1)
        column.putpixel((0, y), tuple(round(top[i] + (bottom[i] - top[i]) * t) for i in range(3)))
    return column.resize((size, size), Image.BICUBIC)


def rim(mask: Image.Image, size: int, inset: int) -> Image.Image:
    """The hairline between the tile edge and an inset copy of it."""
    inner = Image.new("L", (size, size), 0)
    inner.paste(squircle(size - inset * 2), (inset, inset))
    return Image.composite(Image.new("L", (size, size), 0), mask, inner.point(lambda v: 255 if v > 127 else 0))


def icon_tile(size: int, *, padded: bool, dark: bool = True, mark_ratio: float = 0.56) -> Image.Image:
    """One app-icon tile: squircle ground, centred mark, lit top edge.

    `padded` insets the tile inside the canvas, which is what macOS expects.
    Full-bleed is what iOS, Android and Windows expect — they apply their own
    mask, so a tile that carries its own margin ends up looking shrunken.
    """
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    tile = round(size * (0.80 if padded else 1.0))
    offset = (size - tile) // 2

    mask = squircle(tile)
    ground = (
        vertical_ramp(tile, GROUND_TOP, GROUND_BOTTOM).convert("RGBA")
        if dark
        else Image.new("RGBA", (tile, tile), (255, 255, 255, 255))
    )
    ground.putalpha(mask)

    edge = rim(mask, tile, max(round(tile * 0.004), 1))
    if dark:
        # Specular highlight: the rim, faded out over the top third, as light
        # would catch a physical surface rather than outlining it uniformly.
        fade = Image.new("L", (1, tile))
        for y in range(tile):
            fade.putpixel((0, y), round(255 * max(0.0, 1.0 - (y / max(tile - 1, 1)) / 0.30) ** 1.6))
        lit = Image.composite(
            fade.resize((tile, tile), Image.BICUBIC),
            Image.new("L", (tile, tile), 0),
            edge.point(lambda v: 255 if v > 60 else 0),
        )
        overlay = Image.new("RGBA", (tile, tile), (255, 255, 255, 255))
        overlay.putalpha(lit.point(lambda v: round(v * 0.42)))
    else:
        # A white tile needs a real edge to exist on a white page.
        overlay = Image.new("RGBA", (tile, tile), SEPARATOR + (255,))
        overlay.putalpha(edge)
    ground = Image.alpha_composite(ground, overlay)

    mark_px = round(tile * mark_ratio)
    mark = render_mark(mark_px, BLUE_DARK if dark else BLUE_LIGHT)
    ground.alpha_composite(mark, ((tile - mark_px) // 2, (tile - mark_px) // 2))
    canvas.alpha_composite(ground, (offset, offset))
    return canvas


def write_ico(path: Path, images: list[Image.Image]) -> None:
    """A multi-resolution .ico carrying *different artwork per size*.

    Pillow's own ICO writer resamples one source image for every entry, which
    is exactly what must not happen here: the 16px entry has to be the
    simplified mark, not a shrunken four-ring one.
    """
    payloads = []
    for image in images:
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        payloads.append(buffer.getvalue())

    offset = 6 + 16 * len(images)
    header = struct.pack("<HHH", 0, 1, len(images))
    for image, payload in zip(images, payloads):
        header += struct.pack(
            "<BBBBHHII",
            0 if image.width >= 256 else image.width,
            0 if image.height >= 256 else image.height,
            0, 0, 1, 32, len(payload), offset,
        )
        offset += len(payload)
    path.write_bytes(header + b"".join(payloads))


def main() -> None:
    PUBLIC.mkdir(parents=True, exist_ok=True)

    # Masters. The padded one feeds `pnpm tauri icon`.
    icon_tile(1024, padded=True).save(BRAND / "elicta-icon-1024.png")
    icon_tile(1024, padded=True, dark=False).save(BRAND / "elicta-icon-1024-light.png")

    write_ico(PUBLIC / "favicon.ico", [
        render_mark(16, BLUE_LIGHT, small=True),
        render_mark(32, BLUE_LIGHT),
        render_mark(48, BLUE_LIGHT),
    ])

    icon_tile(180, padded=False).save(PUBLIC / "apple-touch-icon.png")
    icon_tile(192, padded=False).save(PUBLIC / "icon-192.png")
    icon_tile(512, padded=False).save(PUBLIC / "icon-512.png")
    # A maskable icon is cropped to a platform-chosen shape, so the mark has
    # to sit inside the 80% safe zone.
    icon_tile(512, padded=False, mark_ratio=0.42).save(PUBLIC / "icon-512-maskable.png")

    for path in sorted(list(BRAND.glob("elicta-icon*")) + list(PUBLIC.glob("*"))):
        print(f"  {path}  {path.stat().st_size:>7} bytes")


if __name__ == "__main__":
    main()
