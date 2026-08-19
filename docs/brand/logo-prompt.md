# Elicta — logo & favicon brief

**Status:** assets generated and wired into the app
**Purpose:** the prompt sequence used to generate the Elicta mark, app icon and
favicon with Gemini, kept in the repo so the identity can be regenerated or
extended consistently rather than re-improvised.

The brief is derived from `docs/live-elicitation-assistant-prd.md` — the exclusion
list below is the PRD's non-goals (§3) restated visually, and the palette and
construction rules match the token layer in `apps/desktop/src/tokens.css`.

## The mark

Direction 1 ("the selected one") was explored but the concentric-arc aperture
from Prompt 3 is what shipped: four rings broken by a straight seam channel,
the seams alternating vertical and horizontal so the rings read as woven rather
than as a target.

Gemini's raster output is not the source of truth — `elicta-mark.svg` is, drawn
by hand on a 32-unit grid (its SVG output filled disconnected arcs instead of
stroking them, which renders as a blob). Two masters exist because the four-ring
mark does not survive 16px: the seams smear into a filled disc.

| File | Use |
|---|---|
| `elicta-mark.svg` | The mark. 32-unit grid, `stroke="currentColor"`. Use at 24px and above |
| `elicta-mark-16.svg` | Two-ring simplification for 16–24px — favicon, menu bar |
| `elicta-icon-1024.png` | App-icon master: mark on a dark squircle, macOS padding |
| `elicta-icon-1024-light.png` | Light-ground alternate |
| `generate-icons.py` | Regenerates every raster below from the two SVGs |

## Where the assets are

Regenerate everything with:

```bash
uv run --no-project --with cairosvg --with pillow python docs/brand/generate-icons.py
(cd apps/desktop && pnpm tauri icon ../../docs/brand/elicta-icon-1024.png)
```

| Target | Path |
|---|---|
| Web favicons, touch icon, manifest icons | `apps/desktop/public/` |
| Desktop/mobile app icons (`.icns`, `.ico`, iOS, Android, Windows tiles) | `apps/desktop/src-tauri/icons/` |
| Head links and theme colours | `apps/desktop/index.html` |
| Bundle icon list | `apps/desktop/src-tauri/tauri.conf.json` |

The favicon is `favicon.svg` (two-ring variant, switching colour on
`prefers-color-scheme`) with a `favicon.ico` fallback whose 16px entry carries
the simplified artwork and whose 32/48px entries carry the full mark.

---

## The prompts

Use in order. Prompt 0 is a preamble you paste **once** at the start of the chat;
prompts 1–5 are follow-ups in that same conversation so the model keeps the brief.

---

## Prompt 0 — the brief (paste first, on its own)

You are an identity designer working on a software product logo. Do not generate
any image yet. Read this brief and reply with a one-paragraph confirmation of the
constraints you will hold to.

PRODUCT
Elicta — a live requirements-elicitation assistant for client meetings. It listens
to a requirements meeting, tracks coverage against a template, detects vague or
contradictory statements as they are said, and surfaces one short follow-up
question to the human operator within the few seconds where asking it still sounds
natural. Afterwards it produces citation-backed planning documents. The name is
from "elicit".

THE ONE IDEA THE MARK SHOULD CARRY
All the expensive thinking happens *before* the meeting. A batch process
pre-reasons a bank of ~200 candidate questions; during the meeting the system only
*selects* from that bank. Many latent possibilities, one chosen at the right
moment. That is the identity: **selection under pressure, not generation.**

BRAND ATTRIBUTES
Precise. Restrained. Calm under load. Trustworthy enough to sit next to a client.
Quietly intelligent. It is an instrument, not an assistant with a personality.
Closer to a Leica or a Braun control than to a chatbot.

ANTI-ATTRIBUTES — these are product non-goals, so they must not appear
It is explicitly NOT a transcription tool, NOT a note-taker, NOT an autonomous
agent, NOT a chatbot. The single worst failure mode of the product is embarrassing
its user in front of a client, so nothing playful, loud, cute, or attention-seeking.

HARD EXCLUSION LIST — do not use any of these, they are all clichés for the
category we are deliberately not in:
microphones, sound waves, audio waveforms, equalizer bars, speech bubbles, chat
bubbles, red record dots, headphones, ears, robots, brains, lightbulbs, gears,
magnifying glasses, four-pointed "AI sparkles", stars, neural-network node webs,
generic swooshes, mesh gradients, iridescent purple-to-pink blends, 3D glossy
plastic, drop shadows, bevels, or any letter set in a script or handwritten face.

VISUAL SYSTEM IT MUST LIVE INSIDE
The desktop app follows the Apple design language: SF Pro typography, system blue
accent (#007AFF on light, #0A84FF on dark), continuous "squircle" corner radii,
and a translucent frosted-glass floating panel. The logo has to sit on that glass
panel without fighting it.

PALETTE
Primary: system blue #0A84FF. Ground: near-black #000000 to #1C1C1E, or pure
white #FFFFFF. Neutrals: greys between. At most one accent colour plus neutrals.
No second hue. No gradient other than, at most, a single subtle tonal shift within
the blue.

CONSTRUCTION RULES
Flat 2D vector. Geometric, drawn on a strict grid with consistent stroke weights
and true circular arcs. No perspective, no texture, no illustration detail. The
whole mark must be reducible to 3–6 shapes. It must remain unambiguous at 16×16
pixels — if a detail disappears at that size, remove it at every size.

Confirm you understand, then wait.

---

## Prompt 1 — concept exploration (three directions, one image)

Generate one image: a clean white presentation sheet, 16:9, showing three
candidate logo marks for Elicta side by side, each in a generous amount of white
space, each rendered as a flat solid-blue (#0A84FF) geometric mark on white, with
a small grey caption number beneath (1, 2, 3). No other text on the sheet.

Direction 1 — "the selected one".
An arc or fan of small dots representing the pre-reasoned bank of many candidate
questions, arranged as a precise radial or horizontal array in light grey. Exactly
one dot is solid blue and displaced slightly out of the array — lifted, chosen,
surfaced. The composition should read as calm order with a single deliberate
exception. Geometric, mathematically even spacing.

Direction 2 — "the one nudge".
Three or four horizontal bars stacked like lines of text, the lower ones short and
pale grey (receding history), the topmost one solid blue, complete, and slightly
longer. Rounded ends, even gaps, strict left alignment. Reads as a single message
standing clear of quieter ones.

Direction 3 — "the E monogram".
A geometric letter E built from three separate horizontal bars with no vertical
spine, set inside an implied square. The bars represent the product's three
phases: before the meeting, during, after. The middle bar is solid blue and
extends slightly further right than the other two, which are grey — the live
moment being the one that reaches. Monoline, equal stroke weights, rounded caps.

All three must be flat, symmetrical where appropriate, drawn on a grid, and
legible at very small sizes.

---

## Prompt 2 — refine the chosen direction

Take direction [N] only. Generate a single image, 1:1, of that mark alone,
centred, flat solid #0A84FF on pure white, occupying about 60% of the frame with
even margins. Refine it: perfect the grid, equalise the optical spacing rather
than the mathematical spacing, and make the stroke weights consistent. Remove any
element that would not survive being scaled to 16 pixels. No text, no background
detail, no shadow, no container shape — just the mark.

## Prompt 2b — variations to choose between

Generate a 2×3 grid on white showing six tight variations of that same mark:
different counts of elements, slightly different proportions, one with rounded
terminals and one with flat terminals, one marginally heavier weight. Keep every
variation flat blue on white, same size, same centring, so they can be compared
directly. No captions.

---

## Prompt 3 — the app icon (macOS / Windows / Tauri)

Generate a 1:1 image of the finished mark as a desktop application icon.

The icon is a rounded square using Apple's continuous "squircle" curvature — not a
plain circular corner radius — filling the frame edge to edge. The square is a
deep near-black (#0B0B0D to #1C1C1E) with an extremely subtle vertical tonal
shift, lighter at the top. The mark sits centred within it in #0A84FF, occupying
roughly 55–60% of the width, optically centred rather than mathematically centred.
One hairline inner highlight along the top edge, no more. Flat, matte, no gloss,
no bevel, no outer drop shadow, no reflection. Render at the highest resolution
available, on a transparent background outside the squircle.

Then, as a separate image, generate the light-mode alternate: identical geometry,
#007AFF mark on a #FFFFFF squircle with a hairline #E5E5EA border.

---

## Prompt 4 — the favicon / small-size test

Generate one image: a white sheet showing the mark rendered at five decreasing
sizes in a single horizontal row — large, then progressively smaller down to a
16-pixel version shown pixel-crisp and unblurred, with the small ones magnified
beside them at 4× so their pixel structure is visible. Solid #0A84FF on white.
This is a legibility test sheet: if a size loses a shape, show it losing it
honestly rather than redrawing it. No captions.

Then generate a single-colour version of the mark suitable for a monochrome
favicon and a macOS menu-bar template icon: pure black on transparent, and pure
white on transparent, with any grey elements resolved into either solid or
removed. The white-on-transparent version must be readable on a dark background.

---

## Prompt 5 — the wordmark and lockup

Generate a 16:9 white sheet showing three things stacked vertically with generous
spacing:

1. The wordmark alone: "Elicta" in a geometric-humanist sans-serif very close to
   SF Pro Display, medium weight, tight but not cramped letter spacing, lowercase
   except the initial E, solid near-black on white. No stylisation of individual
   letters, no ligature tricks.
2. The horizontal lockup: the mark on the left, a clear gap of roughly one
   mark-width, then the wordmark, both optically aligned on their vertical
   centres.
3. The stacked lockup: mark above, wordmark centred beneath it.

No tagline, no other text, no borders.

---

## Prompt 6 — SVG source (do this too; it matters for favicons)

Do not generate an image. Instead, output the mark as hand-written SVG source
code: a single `<svg>` element with `viewBox="0 0 32 32"`, no `width`/`height`
attributes, using `fill="currentColor"` so it inherits colour, built only from
`<rect>`, `<circle>`, and `<path>` elements with exact integer or half-integer
coordinates snapped to the 32-unit grid. No embedded raster, no `<image>`, no
inline styles, no filters, no gradients. Output the code in a single block with
nothing else.

---

## After Gemini: what you actually need to ship

Gemini returns raster. Favicons want vector, so treat Prompt 6's SVG as the
source of truth and redraw/trace it if the generated code is rough.

Web (`apps/desktop/index.html` currently has no icon link at all):
- `favicon.svg`, plus `favicon.ico` at 16/32/48 for older surfaces
- `apple-touch-icon.png` at 180×180
- add `<link rel="icon" href="/favicon.svg" type="image/svg+xml">`

Tauri (`apps/desktop/src-tauri/tauri.conf.json` currently points at a single
`icons/icon.png`): run `pnpm tauri icon path/to/1024.png`, which emits the full
set — `32x32.png`, `128x128.png`, `128x128@2x.png`, `icon.icns` for macOS,
`icon.ico` for Windows, and the `Square*Logo.png` series — then widen the `icon`
array in the config to include them.

Note that macOS wants the mark *inside* Apple's squircle with its own padding,
while Windows wants it filling more of the square — so keep the 1024 master
generous with margin and let the tool crop.
