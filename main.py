import numpy as np

from display import MatrixDisplay
from games import Game, GameOfLife
from runner import GameRunner


def get_next_board(board: np.ndarray) -> np.ndarray:
    """Return the next board generation (backward-compatible helper)."""
    return GameOfLife.next_board(board)


def main() -> None:
    GameRunner().run()


if __name__ == "__main__":
    main()
