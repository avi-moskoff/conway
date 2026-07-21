import unittest

import numpy as np

from games.langton import Ant, Direction, Langton


class LangtonTests(unittest.TestCase):
    def test_black_cell_turns_left_flips_and_moves(self) -> None:
        board = np.zeros((5, 7), dtype=np.uint8)
        ant = Ant(x_position=3, y_position=2)

        next_board, next_ant = Langton.next_board(board, ant)

        self.assertEqual(next_board[2, 3], 1)
        self.assertEqual(next_ant.direction, Direction.LEFT)
        self.assertEqual((next_ant.x_position, next_ant.y_position), (2, 2))

    def test_white_cell_turns_right_flips_and_moves(self) -> None:
        board = np.zeros((5, 7), dtype=np.uint8)
        board[2, 3] = 1
        ant = Ant(x_position=3, y_position=2)

        next_board, next_ant = Langton.next_board(board, ant)

        self.assertEqual(next_board[2, 3], 0)
        self.assertEqual(next_ant.direction, Direction.RIGHT)
        self.assertEqual((next_ant.x_position, next_ant.y_position), (4, 2))

    def test_movement_wraps_on_rectangular_board(self) -> None:
        ant = Ant(x_position=0, y_position=0, direction=Direction.LEFT)

        Langton.progress_ant(ant, height=5, width=7)

        self.assertEqual((ant.x_position, ant.y_position), (6, 0))

    def test_frame_draws_ant_without_changing_board(self) -> None:
        game = Langton(height=5, width=7)
        game.board.fill(0)

        frame = game.frame

        self.assertTrue(
            np.array_equal(
                frame[game.ant.y_position, game.ant.x_position],
                np.array([0, 255, 255], dtype=np.uint8),
            )
        )
        self.assertEqual(game.board[game.ant.y_position, game.ant.x_position], 0)


if __name__ == "__main__":
    unittest.main()
