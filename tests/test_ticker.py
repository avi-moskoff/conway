import unittest

import numpy as np

from games.ticker import Ticker


def _ink_rows(frame: np.ndarray, x_slice: slice) -> tuple[int, int]:
    rows = np.flatnonzero(frame[:, x_slice].any(axis=(1, 2)))
    return int(rows[0]), int(rows[-1])


class TickerBaselineTests(unittest.TestCase):
    def _draw(self, label: str, leading_color=None) -> np.ndarray:
        ticker = Ticker(64, 8, (255, 255, 255))
        frame = np.zeros((8, 64, 3), dtype=np.uint8)
        ticker.draw(frame, label, leading_color)
        return frame

    def test_leading_letter_shares_a_baseline_with_the_rest_of_the_label(
        self,
    ) -> None:
        # "W ETA 5M" is 8 glyphs = 64px, so glyph N spans x = 8N..8N+7.
        frame = self._draw("W ETA 5M", leading_color=(0, 255, 0))
        letter = _ink_rows(frame, slice(0, 8))
        rest = _ink_rows(frame, slice(16, 64))
        self.assertEqual(letter, rest)
        self.assertEqual(letter, (0, 6))

    def test_e_letter_matches_too(self) -> None:
        frame = self._draw("E ETA 5M", leading_color=(0, 0, 255))
        self.assertEqual(_ink_rows(frame, slice(0, 8)), _ink_rows(frame, slice(16, 64)))

    def test_labels_with_and_without_spaces_sit_on_the_same_rows(self) -> None:
        # Guards the Pillow quirk draw_text works around: a space in the
        # string used to shift the whole line down a pixel.
        with_space = self._draw("AB CD")
        without_space = self._draw("ABCD")
        self.assertEqual(
            _ink_rows(with_space, slice(0, 64)), _ink_rows(without_space, slice(0, 64))
        )

    def test_flight_radar_ticker_lines_keep_their_full_capitals(self) -> None:
        frame = self._draw("72F CLOUDY")
        self.assertEqual(_ink_rows(frame, slice(0, 64)), (0, 6))

    def test_letter_spacing_is_one_character_cell_wide(self) -> None:
        # No gaps wider than the glyph advance (8px): "ETA" letters sit in
        # adjacent 8px cells, so no run of blank columns inside the word
        # can be wider than one cell's own padding.
        frame = self._draw("ETA")
        columns = frame[:, :, 0].any(axis=0)
        ink = np.flatnonzero(columns)
        width = ink[-1] - ink[0] + 1
        self.assertLessEqual(width, 3 * 8)

    def test_leading_letter_is_followed_at_one_cell_not_more(self) -> None:
        plain = self._draw("WETA")
        tinted = self._draw("WETA", leading_color=(0, 255, 0))
        self.assertTrue(np.array_equal(plain.any(axis=2), tinted.any(axis=2)))

    def test_a_space_that_measures_wide_does_not_widen_word_gaps(self) -> None:
        # Regression for the Pi, where a measured space came back much
        # wider than a letter. Layout must ignore the space's own width.
        from unittest.mock import patch

        from PIL import ImageDraw

        real = ImageDraw.ImageDraw.textlength

        def wide_space(self, text, *args, **kwargs):
            return 24.0 if text == " " else real(self, text, *args, **kwargs)

        normal = self._draw("W ETA 5M", leading_color=(0, 255, 0))
        with patch.object(ImageDraw.ImageDraw, "textlength", wide_space):
            skewed = self._draw("W ETA 5M", leading_color=(0, 255, 0))
        self.assertTrue(np.array_equal(normal, skewed))

    def test_screens_put_the_ticker_text_at_the_bottom_of_the_panel(self) -> None:
        from games.flight_radar import FlightRadarGame
        from games.weather_radar import WeatherRadarGame

        for game_class in (FlightRadarGame, WeatherRadarGame):
            self.assertEqual(game_class.ticker_height, 8)
        frame = self._draw("HELLO")
        # 7px capitals in the top 7 of the ticker's 8 rows: with the ticker
        # in the bottom 8 rows of a 64px frame, text ends on row 62,
        # leaving one blank row of margin at the very bottom.
        rows = np.flatnonzero(frame.any(axis=(1, 2)))
        self.assertEqual((int(rows[0]), int(rows[-1])), (0, 6))


if __name__ == "__main__":
    unittest.main()
