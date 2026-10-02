import unittest
from unittest.mock import patch

from PIL import Image

from games.breakout import BreakoutGame


class BreakoutTests(unittest.TestCase):
    def setUp(self) -> None:
        self.game = BreakoutGame(64, 64)

    def launch(self, vx: float, vy: float) -> None:
        self.game.waiting_to_serve = False
        self.game.vx, self.game.vy = vx, vy

    def test_knob_aims_launch_while_waiting(self) -> None:
        start = self.game.paddle_x
        self.game.cycle_view(1)
        self.game.cycle_view(1)
        self.assertEqual(self.game.paddle_x, start)
        self.assertEqual(self.game.aim_degrees, 2 * BreakoutGame.AIM_STEP_DEGREES)
        self.game.press_button()
        self.assertGreater(self.game.vx, 0)
        self.assertLess(self.game.vy, 0)

    def test_aim_clamps(self) -> None:
        for _ in range(100):
            self.game.cycle_view(-1)
        self.assertEqual(self.game.aim_degrees, -BreakoutGame.AIM_LIMIT_DEGREES)

    def test_knob_moves_paddle_and_clamps(self) -> None:
        self.game.press_button()
        start = self.game.paddle_x
        self.game.cycle_view(1)
        self.assertEqual(self.game.paddle_x, start + BreakoutGame.PADDLE_STEP)
        for _ in range(100):
            self.game.cycle_view(-1)
        self.assertEqual(self.game.paddle_x, 0)

    def test_ball_waits_until_button_launches_it(self) -> None:
        for _ in range(100):
            self.game.advance()
        self.assertEqual((self.game.vx, self.game.vy), (0.0, 0.0))
        self.game.press_button()
        self.assertLess(self.game.vy, 0)

    def test_button_pauses_and_resumes_while_ball_in_play(self) -> None:
        self.game.press_button()  # launch
        self.game.press_button()  # pause
        ball = (self.game.ball_x, self.game.ball_y)
        paddle = self.game.paddle_x
        self.game.advance()
        self.game.cycle_view(1)
        self.assertEqual((self.game.ball_x, self.game.ball_y), ball)
        self.assertEqual(self.game.paddle_x, paddle)
        self.game.press_button()
        self.game.advance()
        self.assertNotEqual((self.game.ball_x, self.game.ball_y), ball)

    def test_brick_hit_removes_brick_and_bounces(self) -> None:
        self.launch(0.0, -1.0)
        self.game.ball_x = 4.0
        self.game.ball_y = float(BreakoutGame.BRICK_TOP + 3 * 5)
        self.game.advance()
        self.assertEqual(int(self.game.bricks.sum()), 39)
        self.assertGreater(self.game.vy, 0)

    def test_side_hit_flips_horizontal_not_vertical(self) -> None:
        self.game.bricks[:] = False
        self.game.bricks[4, 0] = True  # keeps the wall from re-dealing
        self.game.bricks[1, 3] = True  # x 24..31, y 11..13
        self.launch(1.0, 0.0)
        self.game.ball_x, self.game.ball_y = 23.5, 12.0
        self.game.advance()
        self.assertFalse(self.game.bricks[1, 3])
        self.assertEqual((self.game.vx, self.game.vy), (-1.0, 0.0))

    def test_bottom_hit_flips_vertical_not_horizontal(self) -> None:
        self.game.bricks[:] = False
        self.game.bricks[0, 3] = True  # y 8..10
        self.game.bricks[0, 4] = True
        self.game.bricks[1, 3] = True
        self.game.bricks[1, 4] = True
        self.launch(0.3, -1.0)
        self.game.ball_x, self.game.ball_y = 26.0, 14.0
        for _ in range(8):
            self.game.advance()
            if self.game.bricks[1].sum() == 1:
                break
        self.assertFalse(self.game.bricks[1, 3])
        self.assertGreater(self.game.vy, 0)
        self.assertAlmostEqual(self.game.vx, 0.3)

    def test_lone_corner_hit_flips_both(self) -> None:
        self.game.bricks[:] = False
        self.game.bricks[4, 0] = True  # keeps the wall from re-dealing
        self.game.bricks[1, 3] = True
        self.launch(1.0, 1.0)
        self.game.ball_x, self.game.ball_y = 23.5, 10.5
        self.game.advance()
        self.assertEqual((self.game.vx, self.game.vy), (-1.0, -1.0))

    def test_ball_can_fly_above_the_wall_and_is_drawn_over_the_score(self) -> None:
        self.game.bricks[:] = False
        self.game.bricks[4, 0] = True
        self.launch(0.0, -1.0)
        self.game.ball_x, self.game.ball_y = 14.0, 9.0
        self.game.rows_cleared = 8
        for _ in range(5):
            self.game.advance()
        self.assertLess(self.game.ball_y, BreakoutGame.BRICK_TOP)
        frame = self.game.frame
        self.assertEqual(
            tuple(frame[int(self.game.ball_y), int(self.game.ball_x)]),
            BreakoutGame._BALL,
        )

    def test_paddle_bounces_ball_up(self) -> None:
        self.launch(0.0, 1.0)
        self.game.ball_x = self.game.paddle_x + 6.0
        self.game.ball_y = float(self.game.paddle_y - 1)
        self.game.advance()
        self.assertLess(self.game.vy, 0)

    def test_missing_costs_a_life_then_restarts(self) -> None:
        self.launch(0.0, 1.0)
        self.game.ball_x = 0.0
        self.game.paddle_x = 40
        self.game.ball_y = 62.5
        for _ in range(5):
            self.game.advance()
        self.assertEqual(self.game.lives, BreakoutGame.LIVES - 1)

    def test_clearing_a_row_drops_rows_above_and_adds_one_on_top(self) -> None:
        self.game.bricks[:] = False
        self.game.bricks[0, :] = True
        self.game.bricks[1, 5] = True
        self.game.bricks[2, 3] = True  # the last brick of row 2
        self.launch(0.0, -1.0)
        self.game.ball_x = 28.0
        self.game.ball_y = float(BreakoutGame.BRICK_TOP + 3 * 3 - 1)
        self.game.advance()
        bricks = self.game.bricks
        self.assertTrue(bricks[0].all())  # fresh top row
        self.assertTrue(bricks[1].all())  # old row 0, dropped
        self.assertEqual(list(bricks[2].nonzero()[0]), [5])  # old row 1
        self.assertFalse(bricks[3].any())  # unchanged below the cleared row
        self.assertEqual(self.game.rows_cleared, 1)
        original = BreakoutGame._ROW_COLORS
        self.assertEqual(
            self.game.row_colors, [original[2], original[0], original[1], *original[3:]]
        )

    def test_colors_travel_with_rows_and_reset_with_the_game(self) -> None:
        original = list(BreakoutGame._ROW_COLORS)
        self.game.bricks[:] = False
        self.game.bricks[4, 0] = True
        self.game.bricks[0, 0] = True
        self.launch(0.0, 1.0)
        self.game.ball_x, self.game.ball_y = 4.0, float(8 + 4 * 3 - 1)
        self.game.advance()
        # Bottom (blue) row cleared: blue is now on top, others shifted down.
        self.assertEqual(self.game.row_colors, [original[4], *original[:4]])
        self.game.reset()
        self.assertEqual(self.game.row_colors, original)

    def test_score_is_drawn_and_resets_with_the_game(self) -> None:
        blank = self.game.frame[0:8, 12:44].copy()
        self.game.rows_cleared = 7
        drawn = self.game.frame[0:8, 12:44]
        self.assertTrue((drawn != blank).any())
        self.game.reset()
        self.assertEqual(self.game.rows_cleared, 0)

    def test_frame_never_calls_pil_tobytes(self) -> None:
        # On the Pi, Image.tobytes() lazily imports PIL.ImageFile, which
        # fails after the matrix drops root privileges (see
        # games.ticker's note on avoiding __array_interface__).
        self.game.rows_cleared = 42
        with patch.object(Image.Image, "tobytes", side_effect=ImportError):
            self.assertEqual(self.game.frame.shape, (64, 64, 3))

    def test_menu_label_fits_the_switcher(self) -> None:
        # unscii-8 at 8px/char plus 1px padding each side: 7 chars max.
        self.assertLessEqual(len(BreakoutGame.menu_label), 7)

    def test_frame_shape(self) -> None:
        self.assertEqual(self.game.frame.shape, (64, 64, 3))


if __name__ == "__main__":
    unittest.main()
