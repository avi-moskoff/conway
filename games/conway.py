import numpy as np
from PIL import Image, ImageDraw
from scipy.signal import convolve2d

from games.base import Game
from games.fonts import boot_font

# The word shown as the very first board (see boot_seed_board) - pure
# identity, not a claim that Life represents every screen this project
# now has. See the design doc's Boot sequence section.
BOOT_TEXT = "CONWAY"

# A generic default for total_stages, used by boot_seed_board/
# boot_seed_frame/seed_boot_progress below when a caller (tests, mostly)
# doesn't care about the real per-boot count. runner.GameRunner computes
# its own total_stages at boot time instead - one per game actually
# being built - rather than using this; see the design doc's Boot
# sequence "Scaling rule".
BOOT_STAGE_COUNT = 4

# Native glyph height of unscii-16 (see games.fonts.boot_font) and the gap
# before the progress bar row beneath the word.
_BOOT_TEXT_HEIGHT = 16
_BOOT_BAR_GAP = 2
_BOOT_BAR_HEIGHT = 1


def boot_seed_board(
    height: int, width: int, completed_stages: int, total_stages: int = BOOT_STAGE_COUNT
) -> np.ndarray:
    """Builds the very-first-boot board: BOOT_TEXT in unscii-16, with a
    progress-bar row of live cells beneath it, filled in proportion to
    completed_stages/total_stages.

    Returns a plain 0/1 board, the same shape reset()/advance() use -
    there's no separate overlay system (see the design doc's Boot
    sequence), so once this is shown it dissolves under ordinary Game of
    Life rules exactly like any other board. The bar's full length is the
    word's own pixel width, so the word doubles as the bar's ruler and
    needs no separate outline.
    """
    canvas = Image.new("1", (width, height), 0)
    draw = ImageDraw.Draw(canvas)
    font = boot_font()
    text_width = draw.textlength(BOOT_TEXT, font=font)
    block_height = _BOOT_TEXT_HEIGHT + _BOOT_BAR_GAP + _BOOT_BAR_HEIGHT
    top = (height - block_height) // 2
    left = int((width - text_width) // 2)
    draw.text((left, top), BOOT_TEXT, fill=1, font=font)

    board = np.asarray(list(canvas.get_flattened_data()), dtype=np.uint8)
    board = board.reshape(height, width)

    fraction = 0.0 if total_stages <= 0 else completed_stages / total_stages
    fraction = max(0.0, min(1.0, fraction))
    bar_width = round(text_width * fraction)
    if bar_width > 0:
        bar_top = top + _BOOT_TEXT_HEIGHT + _BOOT_BAR_GAP
        board[bar_top : bar_top + _BOOT_BAR_HEIGHT, left : left + bar_width] = 1
    return board


class GameOfLife(Game):
    """Owns and evolves a Conway's Game of Life board."""

    frame_delay_seconds = 0.1
    menu_label = "LIFE"
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

    def seed_boot_progress(
        self, completed_stages: int, total_stages: int = BOOT_STAGE_COUNT
    ) -> None:
        """Replace the board with the boot bitmap at a given progress
        level (see boot_seed_board). Used once, by GameRunner, for the
        very first board the very first time the program starts; an
        ordinary reset (the button, or any later restart) still goes
        through reset() and gets a random board as always.
        """
        self.board = boot_seed_board(
            self.height, self.width, completed_stages, total_stages
        )


def boot_seed_frame(
    height: int, width: int, completed_stages: int, total_stages: int = BOOT_STAGE_COUNT
) -> np.ndarray:
    """RGB frame for boot_seed_board, ready to hand straight to
    MatrixDisplay.show(). Exists so GameRunner can paint the boot screen
    the moment the matrix is constructed, before any GameOfLife instance
    exists yet to own a board of its own - see the design doc's Boot
    sequence section: the matrix is built right after GPIO claim, ahead
    of the games, specifically so this can happen.
    """
    board = boot_seed_board(height, width, completed_stages, total_stages)
    return GameOfLife._PALETTE[board]
