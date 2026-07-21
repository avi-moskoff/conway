import numpy as np
from scipy.signal import convolve2d

from games.base import Game


class GameOfLife(Game):
    """Owns and evolves a Conway's Game of Life board."""

    frame_delay_seconds = 0.05
    _NEIGHBOR_KERNEL = np.array([[1, 1, 1], [1, 0, 1], [1, 1, 1]], dtype=np.uint8)
    _PALETTE = np.array([[0, 0, 0], [255, 255, 255]], dtype=np.uint8)

    def __init__(self, height: int, width: int) -> None:
        super().__init__(height, width)
        self.reset()

    @property
    def frame(self) -> np.ndarray:
        return self._PALETTE[self.board]

    @classmethod
    def next_board(cls, board: np.ndarray) -> np.ndarray:
        neighbors = convolve2d(
            board, cls._NEIGHBOR_KERNEL, mode="same", boundary="wrap"
        )
        return (
            ((board == 1) & ((neighbors == 2) | (neighbors == 3)))
            | ((board == 0) & (neighbors == 3))
        ).astype(int)

    def reset(self) -> None:
        self.board = np.random.randint(0, 2, (self.height, self.width), dtype=np.uint8)

    def advance(self) -> None:
        self.board = self.next_board(self.board)
