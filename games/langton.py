from dataclasses import dataclass
from enum import Enum

import numpy as np

from games.base import Game


class Direction(Enum):
    UP = 0
    RIGHT = 1
    DOWN = 2
    LEFT = 3


@dataclass(slots=True)
class Ant:
    x_position: int
    y_position: int
    direction: Direction = Direction.UP


class Langton(Game):
    """Owns and evolves a Langton's Ant board."""

    frame_delay_seconds = 0.05
    _PALETTE = np.array([[0, 0, 0], [255, 255, 255]], dtype=np.uint8)

    def __init__(self, height: int, width: int) -> None:
        super().__init__(height, width)
        self.reset()

    @property
    def frame(self) -> np.ndarray:
        display_board = self._PALETTE[self.board]
        display_board[self.ant.y_position, self.ant.x_position] = [0, 255, 255]
        return display_board

    @staticmethod
    def progress_ant(ant: Ant, height: int, width: int) -> Ant:
        if ant.direction == Direction.UP:
            ant.y_position = (ant.y_position - 1) % height
        elif ant.direction == Direction.RIGHT:
            ant.x_position = (ant.x_position + 1) % width
        elif ant.direction == Direction.DOWN:
            ant.y_position = (ant.y_position + 1) % height
        else:
            ant.x_position = (ant.x_position - 1) % width
        return ant

    @classmethod
    def next_board(cls, board: np.ndarray, ant: Ant) -> tuple[np.ndarray, Ant]:
        ant.direction = Direction(
            (ant.direction.value + (1 if board[ant.y_position, ant.x_position] else -1))
            % len(Direction)
        )
        board[ant.y_position, ant.x_position] ^= 1
        ant = cls.progress_ant(ant, len(board), len(board[0]))
        return board, ant

    def reset(self) -> None:
        self.board = np.random.randint(0, 2, (self.height, self.width), dtype=np.uint8)

        self.ant = Ant(
            x_position=self.width // 2,
            y_position=self.height // 2,
        )

    def advance(self) -> None:
        self.board, self.ant = self.next_board(self.board, self.ant)
