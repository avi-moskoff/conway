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


if __name__ == "__main__":
    unittest.main()
