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

from PIL import ImageFont

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
