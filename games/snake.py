import random

import numpy as np

from games.base import Game, draw_pause_icon
from games.fonts import stamp_game_over

# Grid steps as (dx, dy), in clockwise order so a +1 knob click is a right
# turn: UP -> RIGHT -> DOWN -> LEFT.
_HEADINGS = ((0, -1), (1, 0), (0, 1), (-1, 0))


class SnakeGame(Game):
    """Snake on a walled grid of CELL_SIZE-pixel cells, steered by the
    encoder: each click turns the head 90 degrees (clockwise for
    clockwise). Hitting a wall or yourself ends the game: the snake blinks
    where it died, then GAME OVER and the number of foods eaten are held
    until the button starts a new game. Otherwise the button pauses and
    resumes.
    """

    frame_delay_seconds = 0.15
    menu_label = "SNAKE"
    CELL_SIZE = 2
    START_LENGTH = 3
    # How many frames the dead snake blinks (in its own colors - red is
    # reserved for signal, never failure) before the game-over screen.
    GAME_OVER_FRAMES = 12

    _BODY = (0, 200, 0)
    _HEAD = (0, 255, 255)
    _FOOD = (255, 0, 0)

    def __init__(self, height: int, width: int) -> None:
        super().__init__(height, width)
        self.rows = height // self.CELL_SIZE
        self.columns = width // self.CELL_SIZE
        self.reset()

    def reset(self) -> None:
        row, column = self.rows // 2, self.columns // 2
        # Head first. Starts heading right with two body cells trailing.
        self.snake = [(column - i, row) for i in range(self.START_LENGTH)]
        self.heading = 1
        self.food = self._place_food()
        self.alive = True
        self.paused = False
        self._dead_frames = 0

    def _place_food(self) -> tuple[int, int] | None:
        occupied = set(self.snake)
        free = [
            (x, y)
            for y in range(self.rows)
            for x in range(self.columns)
            if (x, y) not in occupied
        ]
        return random.choice(free) if free else None

    def press_button(self) -> None:
        if self.alive:
            self.paused = not self.paused
        else:
            self.reset()

    def cycle_view(self, direction: int) -> None:
        if self.alive and not self.paused:
            self.heading = (self.heading + direction) % len(_HEADINGS)

    def advance(self) -> None:
        if self.paused:
            return
        if not self.alive:
            self._dead_frames = min(self._dead_frames + 1, self.GAME_OVER_FRAMES)
            return

        dx, dy = _HEADINGS[self.heading]
        head_x, head_y = self.snake[0]
        new_head = (head_x + dx, head_y + dy)
        if not (0 <= new_head[0] < self.columns and 0 <= new_head[1] < self.rows):
            self.alive = False
            return
        eating = new_head == self.food
        # The tail cell is vacated this frame unless we're growing.
        body = self.snake if eating else self.snake[:-1]
        if new_head in body:
            self.alive = False
            return
        self.snake.insert(0, new_head)
        if eating:
            self.food = self._place_food()
            if self.food is None:
                self.alive = False
        else:
            self.snake.pop()

    @property
    def frame(self) -> np.ndarray:
        if not self.alive and self._dead_frames >= self.GAME_OVER_FRAMES:
            frame = np.zeros((self.height, self.width, 3), dtype=np.uint8)
            stamp_game_over(frame, len(self.snake) - self.START_LENGTH)
            return frame
        cells = np.zeros((self.rows, self.columns, 3), dtype=np.uint8)
        if self.food is not None:
            x, y = self.food
            cells[y, x] = self._FOOD
        flash_off = not self.alive and (self._dead_frames // 2) % 2 == 1
        if not flash_off:
            for x, y in self.snake[1:]:
                cells[y, x] = self._BODY
            x, y = self.snake[0]
            cells[y, x] = self._HEAD
        frame = np.repeat(
            np.repeat(cells, self.CELL_SIZE, axis=0), self.CELL_SIZE, axis=1
        )
        if self.paused:
            draw_pause_icon(frame)
        return frame
