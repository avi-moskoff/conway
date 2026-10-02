"""Self-hosted bitmap fonts shared across every screen with text.

Unscii, chosen for its terminal/hacker character over a web-pixel-font or
arcade-marquee feel - see the design doc's Typography section for the full
comparison against Pixel Operator, Press Start 2P, Silkscreen, and Tom
Thumb. Public domain (vendored under assets/fonts/ - see
UNSCII-LICENSE.txt there; the one Unscii variant that isn't public domain,
unscii-16-full, is never used here).

Loaded at these specific point sizes on purpose, not as an arbitrary
choice: these TTFs are vector traces of an 8x8 (unscii-8) or 8x16
(unscii-16) pixel grid, built to reproduce that exact grid only when
rendered at its native size - any other size would blur or misalign it.
"""

from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

_ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets" / "fonts"

_cache: dict[str, ImageFont.FreeTypeFont] = {}


def _load(filename: str, size: int) -> ImageFont.FreeTypeFont:
    key = f"{filename}:{size}"
    cached = _cache.get(key)
    if cached is None:
        cached = ImageFont.truetype(str(_ASSETS_DIR / filename), size=size)
        _cache[key] = cached
    return cached


def ticker_font() -> ImageFont.FreeTypeFont:
    """unscii-8 at its native 8px size - the shared ticker/menu font."""
    return _load("unscii-8.ttf", 8)


def boot_font() -> ImageFont.FreeTypeFont:
    """unscii-16 at its native 16px size - the boot title only. Its
    larger grid stands in for a bold weight Unscii doesn't have; see the
    design doc's Boot sequence section.
    """
    return _load("unscii-16.ttf", 16)


def preload_fonts() -> None:
    """Load and cache every font up front. GameRunner calls this before
    constructing MatrixDisplay: RGBMatrix drops root privileges to the
    unprivileged `daemon` user as soon as it's built, and that user can't
    read these files out of /home/avi - so any font first loaded after
    that point fails with PIL's generic "cannot open resource". Cached
    fonts survive the privilege drop; uncached ones don't.
    """
    ticker_font()
    boot_font()


def draw_text(
    draw: ImageDraw.ImageDraw,
    xy: tuple[float, float],
    text: str,
    font: ImageFont.FreeTypeFont,
    fill: int = 1,
) -> None:
    """Draw `text` one glyph at a time, so every glyph lands on the same
    rows whatever string it's in.

    Drawing a whole string in one call isn't safe for these bitmap fonts:
    with the installed Pillow, a string containing a space is placed one
    pixel lower than the same letters without one (e.g. "W E" sits a row
    below "WE"). That made a flight-radar direction letter, drawn on its
    own, sit a row higher than the " ETA 5M" beside it. Placing each glyph
    individually (Unscii is monospace, so the advance is just each
    glyph's own width) removes the dependence on what else is in the
    string. Spaces just advance.
    """
    if not text:
        return
    advance = glyph_advance(draw, font)
    x, y = xy
    for glyph in text:
        if glyph != " ":
            draw.text((x, y), glyph, fill=fill, font=font)
        x += advance


def glyph_advance(draw: ImageDraw.ImageDraw, font: ImageFont.FreeTypeFont) -> float:
    """The one advance every character in a monospace font moves by,
    measured from a real glyph ("M") - never from a space. A space's
    measured width isn't trustworthy here: on the Pi it came back much
    wider than a letter, which spread words far apart. Since the font is
    monospace, a space simply advances by the same amount as any other
    character.
    """
    return draw.textlength("M", font=font)


def text_width(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont) -> float:
    """Width of `text` as draw_text will lay it out: characters times the
    single monospace advance."""
    return len(text) * glyph_advance(draw, font)


_mask_cache: dict[str, np.ndarray] = {}


def text_mask(text: str) -> np.ndarray:
    """`text` rendered in the ticker font as an 8-row boolean mask, cached
    per string - for screens that stamp text straight into an RGB frame.
    """
    cached = _mask_cache.get(text)
    if cached is None:
        width = len(text) * 8
        canvas = Image.new("1", (width, 8), 0)
        draw_text(ImageDraw.Draw(canvas), (0, 0), text, ticker_font())
        # Same idiom as games.menu / games.ticker: np.asarray on a 1-bit
        # PIL image goes through Image.tobytes(), which lazily imports
        # PIL.ImageFile and fails once the matrix has dropped root.
        pixels = np.asarray(list(canvas.get_flattened_data()), dtype=np.uint8)
        cached = pixels.reshape(8, width).astype(bool)
        _mask_cache[text] = cached
    return cached


def stamp_text(
    frame: np.ndarray, text: str, x: int, y: int, color: tuple[int, int, int]
) -> None:
    """Draw `text` into an RGB frame in place, clipped to the frame."""
    mask = text_mask(text)
    region = frame[y : y + 8, x : x + mask.shape[1]]
    region[mask[: region.shape[0], : region.shape[1]]] = color


def stamp_game_over(frame: np.ndarray, score: int) -> None:
    """The shared arcade game-over screen: GAME / OVER over the score,
    centred, wrapping after four digits."""
    width = frame.shape[1]
    for text, y in (("GAME", 14), ("OVER", 24), (str(score % 10_000), 42)):
        stamp_text(frame, text, (width - len(text) * 8) // 2, y, (255, 255, 255))
