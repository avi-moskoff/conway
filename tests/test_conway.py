import unittest

import numpy as np
from PIL import Image, ImageDraw

from games.conway import (
    BOOT_STAGE_COUNT,
    BOOT_TEXT,
    GameOfLife,
    boot_seed_board,
    boot_seed_frame,
)
from games.fonts import boot_font


def _text_pixel_width() -> int:
    canvas = Image.new("1", (1, 1), 0)
    draw = ImageDraw.Draw(canvas)
    return round(draw.textlength(BOOT_TEXT, font=boot_font()))


class BootSeedBoardTests(unittest.TestCase):
    def test_shape_and_dtype_match_an_ordinary_board(self) -> None:
        board = boot_seed_board(64, 64, 0, BOOT_STAGE_COUNT)
        self.assertEqual(board.shape, (64, 64))
        self.assertEqual(board.dtype, np.uint8)
        self.assertTrue(set(np.unique(board)) <= {0, 1})

    def test_zero_progress_draws_the_word_with_no_bar(self) -> None:
        board = boot_seed_board(64, 64, 0, BOOT_STAGE_COUNT)
        text_only = boot_seed_board(64, 64, -1, BOOT_STAGE_COUNT)
        # Nothing before the word's own row range should ever be lit at
        # zero progress - i.e. the live cells are exactly the word, same
        # as clamping to "less than zero" progress.
        np.testing.assert_array_equal(board, text_only)
        self.assertGreater(board.sum(), 0)

    def test_full_progress_bar_spans_the_words_own_pixel_width(self) -> None:
        board = boot_seed_board(64, 64, BOOT_STAGE_COUNT, BOOT_STAGE_COUNT)
        zero = boot_seed_board(64, 64, 0, BOOT_STAGE_COUNT)
        bar_only = board.astype(int) - zero.astype(int)
        bar_rows = np.argwhere(bar_only.any(axis=1))
        self.assertEqual(len(bar_rows), 1, "bar should be exactly one row tall")
        bar_row = bar_only[bar_rows[0, 0]]
        self.assertEqual(bar_row.sum(), _text_pixel_width())

    def test_bar_width_scales_linearly_with_progress(self) -> None:
        text_width = _text_pixel_width()
        half = boot_seed_board(64, 64, BOOT_STAGE_COUNT // 2, BOOT_STAGE_COUNT)
        zero = boot_seed_board(64, 64, 0, BOOT_STAGE_COUNT)
        bar_only = half.astype(int) - zero.astype(int)
        self.assertEqual(bar_only.sum(), round(text_width * 0.5))

    def test_progress_outside_zero_to_total_is_clamped(self) -> None:
        over = boot_seed_board(64, 64, BOOT_STAGE_COUNT * 10, BOOT_STAGE_COUNT)
        full = boot_seed_board(64, 64, BOOT_STAGE_COUNT, BOOT_STAGE_COUNT)
        np.testing.assert_array_equal(over, full)

    def test_bar_sits_directly_beneath_the_words_own_drawing_box(self) -> None:
        # The bar starts at the same x origin the word was drawn from, not
        # necessarily the leftmost *inked* pixel - a font can have a
        # pixel or two of left-side bearing before a glyph's own ink
        # starts, same as the top-of-line padding seen in the row range
        # (see the vertical centering above).
        text_width = _text_pixel_width()
        expected_left = (64 - text_width) // 2
        full = boot_seed_board(64, 64, BOOT_STAGE_COUNT, BOOT_STAGE_COUNT)
        zero = boot_seed_board(64, 64, 0, BOOT_STAGE_COUNT)
        bar_only = full.astype(int) - zero.astype(int)
        bar_cols = np.argwhere(bar_only.any(axis=0))
        self.assertEqual(bar_cols.min(), expected_left)

    def test_next_board_accepts_the_boot_seed_without_error(self) -> None:
        # Smoke test: the boot bitmap has to be a legitimate generation
        # zero, not just something that happens to render - see
        # GameOfLife.seed_boot_progress.
        board = boot_seed_board(64, 64, BOOT_STAGE_COUNT, BOOT_STAGE_COUNT)
        next_board = GameOfLife.next_board(board)
        self.assertEqual(next_board.shape, board.shape)


class BootSeedFrameTests(unittest.TestCase):
    def test_matches_the_board_run_through_game_of_lifes_own_palette(self) -> None:
        # boot_seed_frame exists purely so GameRunner can paint the boot
        # screen before any GameOfLife instance exists (see runner.py's
        # __init__) - it has to stay pixel-identical to what a real
        # instance would show once seeded, or the frame the matrix shows
        # first would visibly jump when the real seed takes over.
        for completed in (0, 1, 3, BOOT_STAGE_COUNT):
            board = boot_seed_board(64, 64, completed, BOOT_STAGE_COUNT)
            expected = GameOfLife._PALETTE[board]
            frame = boot_seed_frame(64, 64, completed, BOOT_STAGE_COUNT)
            np.testing.assert_array_equal(frame, expected)

    def test_shape_and_dtype_are_display_ready(self) -> None:
        frame = boot_seed_frame(64, 64, 2, BOOT_STAGE_COUNT)
        self.assertEqual(frame.shape, (64, 64, 3))
        self.assertEqual(frame.dtype, np.uint8)


class GameOfLifeBootSeedTests(unittest.TestCase):
    def test_seed_boot_progress_matches_the_pure_function(self) -> None:
        game = GameOfLife(64, 64)
        game.seed_boot_progress(2, BOOT_STAGE_COUNT)
        expected = boot_seed_board(64, 64, 2, BOOT_STAGE_COUNT)
        np.testing.assert_array_equal(game.board, expected)

    def test_an_ordinary_reset_after_boot_seeding_is_random_again(self) -> None:
        game = GameOfLife(64, 64)
        game.seed_boot_progress(BOOT_STAGE_COUNT, BOOT_STAGE_COUNT)
        game.reset()
        # A random board of this size essentially never matches the boot
        # bitmap exactly - this just confirms reset() isn't somehow still
        # returning the seed.
        seeded = boot_seed_board(64, 64, BOOT_STAGE_COUNT, BOOT_STAGE_COUNT)
        self.assertFalse(np.array_equal(game.board, seeded))


if __name__ == "__main__":
    unittest.main()
