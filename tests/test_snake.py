import unittest

from games.snake import SnakeGame


class SnakeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.game = SnakeGame(64, 64)
        self.game.food = (0, 0)

    def test_moves_forward(self) -> None:
        head = self.game.snake[0]
        self.game.advance()
        self.assertEqual(self.game.snake[0], (head[0] + 1, head[1]))
        self.assertEqual(len(self.game.snake), 3)

    def test_knob_turns_head_ninety_degrees(self) -> None:
        head = self.game.snake[0]
        self.game.cycle_view(1)
        self.game.advance()
        self.assertEqual(self.game.snake[0], (head[0], head[1] + 1))
        self.game.cycle_view(-1)
        self.game.advance()
        self.assertEqual(self.game.snake[0][0], head[0] + 1)

    def test_double_turn_reverses_into_neck_and_dies(self) -> None:
        self.game.cycle_view(1)
        self.game.cycle_view(1)
        self.game.advance()
        self.assertFalse(self.game.alive)

    def test_wall_ends_game(self) -> None:
        self.game.snake = [(self.game.columns - 1, 5), (self.game.columns - 2, 5)]
        self.game.advance()
        self.assertFalse(self.game.alive)

    def test_speed_is_constant_when_eating(self) -> None:
        delay = self.game.frame_delay_seconds
        x, y = self.game.snake[0]
        self.game.food = (x + 1, y)
        self.game.advance()
        self.assertEqual(self.game.frame_delay_seconds, delay)

    def test_eating_grows(self) -> None:
        x, y = self.game.snake[0]
        self.game.food = (x + 1, y)
        self.game.advance()
        self.assertEqual(len(self.game.snake), 4)
        self.assertNotEqual(self.game.food, (x + 1, y))

    def test_self_collision_ends_then_restarts(self) -> None:
        self.game.snake = [(5, 5), (5, 6), (4, 6), (4, 5), (4, 4), (5, 4)]
        self.game.heading = 0
        self.game.cycle_view(-1)  # face left into (4, 5)
        self.game.advance()
        self.assertFalse(self.game.alive)
        for _ in range(SnakeGame.GAME_OVER_FRAMES):
            self.game.advance()
        self.assertTrue(self.game.alive)

    def test_button_pauses_and_resumes(self) -> None:
        head = self.game.snake[0]
        self.game.press_button()
        self.game.cycle_view(1)
        self.game.advance()
        self.assertEqual(self.game.snake[0], head)
        self.game.press_button()
        self.game.advance()
        self.assertEqual(self.game.snake[0], (head[0] + 1, head[1]))

    def test_button_restarts_once_dead(self) -> None:
        self.game.alive = False
        self.game.press_button()
        self.assertTrue(self.game.alive)

    def test_menu_label_fits_the_switcher(self) -> None:
        self.assertLessEqual(len(SnakeGame.menu_label), 7)

    def test_frame_shape(self) -> None:
        self.assertEqual(self.game.frame.shape, (64, 64, 3))


if __name__ == "__main__":
    unittest.main()
