import random

import numpy as np

from games.base import Game

# Grid steps as (dx, dy), in clockwise order so a +1 knob click is a right
# turn: UP -> RIGHT -> DOWN -> LEFT.
_HEADINGS = ((0, -1), (1, 0), (0, 1), (-1, 0))


class SnakeGame(Game):
    """Snake on a wrapped grid of CELL_SIZE-pixel cells, steered by the
    encoder: each click turns the head 90 degrees (clockwise for
    clockwise). The button restarts.
    """

    frame_delay_seconds = 0.15
    menu_label = "SNAKE"
    CELL_SIZE = 2
    # How many frames the dead snake flashes before a fresh game starts.
    GAME_OVER_FRAMES = 12

    _BODY = (0, 200, 0)
    _HEAD = (0, 255, 255)
    _FOOD = (255, 0, 0)
    _DEAD = (255, 0, 0)

    def __init__(self, height: int, width: int) -> None:
        super().__init__(height, width)
        self.rows = height // self.CELL_SIZE
        self.columns = width // self.CELL_SIZE
        self.reset()

    def reset(self) -> None:
        row, column = self.rows // 2, self.columns // 2
        # Head first. Starts heading right with two body cells trailing.
        self.snake = [(column - i, row) for i in range(3)]
        self.heading = 1
        self._moved_heading = 1
        self.food = self._place_food()
        self.alive = True
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

    def cycle_view(self, direction: int) -> None:
        if self.alive:
            self.heading = (self.heading + direction) % len(_HEADINGS)

    def advance(self) -> None:
        if not self.alive:
            self._dead_frames += 1
            if self._dead_frames >= self.GAME_OVER_FRAMES:
                self.reset()
            return

        # Turning twice between frames could point straight back into the
        # neck; ignore a heading that reverses the last move.
        if (self.heading - self._moved_heading) % len(_HEADINGS) == 2:
            self.heading = self._moved_heading
        dx, dy = _HEADINGS[self.heading]
        head_x, head_y = self.snake[0]
        new_head = ((head_x + dx) % self.columns, (head_y + dy) % self.rows)
        eating = new_head == self.food
        # The tail cell is vacated this frame unless we're growing.
        body = self.snake if eating else self.snake[:-1]
        if new_head in body:
            self.alive = False
            return
        self._moved_heading = self.heading
        self.snake.insert(0, new_head)
        if eating:
            self.food = self._place_food()
            if self.food is None:
                self.alive = False
        else:
            self.snake.pop()

    @property
    def frame(self) -> np.ndarray:
        cells = np.zeros((self.rows, self.columns, 3), dtype=np.uint8)
        if self.food is not None:
            x, y = self.food
            cells[y, x] = self._FOOD
        flash_off = not self.alive and (self._dead_frames // 2) % 2 == 1
        if not flash_off:
            body = self._BODY if self.alive else self._DEAD
            for x, y in self.snake[1:]:
                cells[y, x] = body
            x, y = self.snake[0]
            cells[y, x] = self._HEAD if self.alive else self._DEAD
        return np.repeat(np.repeat(cells, self.CELL_SIZE, axis=0), self.CELL_SIZE, axis=1)
