"""Shared ticker-line rendering for every live-data screen.

Centered when a label fits, scrolling at a constant rate when it doesn't -
identical behavior and typography everywhere a screen shows text, rather
than each screen reimplementing its own copy (this used to be duplicated,
nearly verbatim, between flight_radar.py and weather_radar.py).
"""

import numpy as np
from PIL import Image, ImageDraw

from games.fonts import ticker_font


class Ticker:
    """Owns one screen's ticker state (current label, scroll position) and
    draws it into the bottom rows of a frame.
    """

    def __init__(self, width: int, height: int, text_color: tuple[int, int, int]) -> None:
        self.width = width
        self.height = height
        self.text_color = text_color
        self.scrolls = False
        self._font = ticker_font()
        self._last_label = ""
        self._scroll_offset = 0

    def reset(self) -> None:
        """Call when the screen switches to a new context (mode change,
        game reset) so scrolling restarts from the beginning."""
        self._scroll_offset = 0

    def advance(self) -> None:
        """Call once per game frame - advances the scroll position while
        the current label doesn't fit; a no-op otherwise."""
        if self.scrolls:
            self._scroll_offset += 1

    def draw(
        self,
        frame: np.ndarray,
        label: str,
        leading_color: tuple[int, int, int] | None = None,
    ) -> None:
        """Render `label` into the bottom `self.height` rows of `frame`.

        leading_color optionally tints the label's first character to a
        categorical color while the rest stays self.text_color - the
        "leading token" convention (e.g. flight radar's rail direction
        letter) any screen's label can use; see the design doc's
        Typography section.
        """
        if label != self._last_label:
            self._scroll_offset = 0
        self._last_label = label
        canvas = Image.new("1", (self.width, self.height), 0)
        draw = ImageDraw.Draw(canvas)
        text_width = int(draw.textlength(label, font=self._font))
        self.scrolls = text_width > self.width

        letter_canvas = None
        letter_draw = None
        if leading_color is not None and label:
            letter_canvas = Image.new("1", (self.width, self.height), 0)
            letter_draw = ImageDraw.Draw(letter_canvas)

        def draw_label(x: float) -> None:
            if letter_draw is not None:
                letter, rest = label[0], label[1:]
                letter_draw.text((x, -1), letter, fill=1, font=self._font)
                letter_width = draw.textlength(letter, font=self._font)
                draw.text((x + letter_width, -1), rest, fill=1, font=self._font)
            else:
                draw.text((x, -1), label, fill=1, font=self._font)

        if self.scrolls:
            cycle_width = text_width + 8
            x = -(self._scroll_offset % cycle_width)
            draw_label(x)
            draw_label(x + cycle_width)
        else:
            x = (self.width - text_width) // 2
            draw_label(x)

        # Avoid Pillow's Image.__array_interface__, which goes through
        # Image.tobytes() and unnecessarily requires the optional ImageFile
        # module on the minimal Raspberry Pi installation.
        mask = np.asarray(list(canvas.get_flattened_data()), dtype=np.uint8)
        mask = mask.reshape(self.height, self.width) != 0
        ticker_rows = frame[-self.height :]
        ticker_rows[:] = 0
        ticker_rows[mask] = self.text_color

        if letter_canvas is not None:
            letter_mask = np.asarray(
                list(letter_canvas.get_flattened_data()), dtype=np.uint8
            )
            letter_mask = letter_mask.reshape(self.height, self.width) != 0
            ticker_rows[letter_mask] = leading_color
