import unittest

from games.fonts import ticker_font  # noqa: F401  (fonts must import cleanly)
from games.menu import ROW_HEIGHT, TEXT_PADDING, ScreenMenu


class MenuPaddingTests(unittest.TestCase):
    def test_selected_row_leaves_a_pixel_of_border_around_the_text(self) -> None:
        menu = ScreenMenu(64, 64)
        menu.open(("LIFE", "ANT", "WEATHER"), 1)
        frame = menu.frame[:, :, 0]
        top = ROW_HEIGHT
        row = frame[top : top + ROW_HEIGHT]
        # The bar is lit; text pixels are the dark ones inside it. None of
        # them may sit on the bar's outer edge.
        text = row == 0
        self.assertTrue(text.any())
        self.assertFalse(text[:TEXT_PADDING].any(), "text touches the top edge")
        self.assertFalse(text[-TEXT_PADDING:].any(), "text touches the bottom edge")
        self.assertFalse(text[:, :TEXT_PADDING].any(), "text touches the left edge")

    def test_longest_label_fits_with_padding_on_both_sides(self) -> None:
        menu = ScreenMenu(64, 64)
        menu.open(("WEATHER",), 0)
        frame = menu.frame[:, :, 0]
        text = frame[:ROW_HEIGHT] == 0
        self.assertFalse(text[:, -TEXT_PADDING:].any())


if __name__ == "__main__":
    unittest.main()
