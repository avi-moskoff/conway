"""The screen switcher: a vertical list of every screen's menu_label,
opened and closed by pressing the encoder in (see runner.py).

Not a Game: GameRunner drives it directly from the push/rotate handlers
instead of the usual activate/advance/reset cycle, and it holds no state
of its own beyond which row is currently highlighted.
"""

import numpy as np
from PIL import Image, ImageDraw

from games.fonts import ticker_font

# unscii-8's native row height, one label per row. At most five screens
# exist today (three animations, two live views), well within the eight
# rows that fit an 8px row height on a 64px-tall display - so this class
# doesn't implement scrolling. If the roster ever grows past that, this
# will need it.
ROW_HEIGHT = 8

TEXT_COLOR = (255, 255, 255)


class ScreenMenu:
    """Renders `labels` as a top-to-bottom list, with `selected_index`
    drawn highlighted: background and text inverted, the same "mark it by
    inverting" convention games.base.invert_pixel uses for the self/home
    and error pixels elsewhere.
    """

    def __init__(self, height: int, width: int) -> None:
        self.height = height
        self.width = width
        self._font = ticker_font()
        self.labels: tuple[str, ...] = ()
        self.selected_index = 0

    def open(self, labels: tuple[str, ...], selected_index: int) -> None:
        """Show the menu with `labels`, highlighting `selected_index`
        (normally whichever screen is currently active)."""
        self.labels = labels
        self.selected_index = selected_index % len(labels) if labels else 0

    def move_selection(self, direction: int) -> None:
        """Move the highlight by +1/-1, wrapping. A no-op with nothing
        open."""
        if not self.labels:
            return
        self.selected_index = (self.selected_index + direction) % len(self.labels)

    @property
    def frame(self) -> np.ndarray:
        frame = np.zeros((self.height, self.width, 3), dtype=np.uint8)
        canvas = Image.new("1", (self.width, self.height), 0)
        draw = ImageDraw.Draw(canvas)
        for index, label in enumerate(self.labels):
            y = index * ROW_HEIGHT
            if y >= self.height:
                break
            # The -1 y-offset matches Ticker.draw's - a baseline quirk of
            # this font at this size, not something specific to the ticker.
            draw.text((0, y - 1), label, fill=1, font=self._font)

        # Same Pillow-tobytes-avoidance workaround as Ticker.draw.
        mask = np.asarray(list(canvas.get_flattened_data()), dtype=np.uint8)
        mask = mask.reshape(self.height, self.width) != 0
        frame[mask] = TEXT_COLOR

        selected_y = self.selected_index * ROW_HEIGHT
        if self.labels and selected_y < self.height:
            row = frame[selected_y : selected_y + ROW_HEIGHT]
            row[:] = 255 - row

        return frame
