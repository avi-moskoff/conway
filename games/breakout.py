import math
import random

import numpy as np
from PIL import Image, ImageDraw

from games.base import Game, draw_pause_icon
from games.fonts import draw_text, ticker_font


class BreakoutGame(Game):
    """Breakout: each encoder click slides the paddle PADDLE_STEP pixels.
    The ball waits on the paddle until the button launches it; while it
    waits, the knob aims the launch (an indicator shows the heading) and
    the paddle stays put. Once it's in play, the knob slides the paddle
    and the button pauses and resumes. Clearing a whole row drops the rows
    above it down one, keeping their colors, and the cleared row's color
    becomes the fresh row on top, so the wall never runs out. Losing all lives restarts.
    """

    frame_delay_seconds = 0.03
    menu_label = "BRKOUT"
    BRICK_ROWS = 5
    BRICK_COLUMNS = 8
    BRICK_WIDTH = 8
    BRICK_HEIGHT = 3
    BRICK_TOP = 8
    PADDLE_WIDTH = 12
    PADDLE_STEP = 3
    PADDLE_ROW_OFFSET = 3  # rows up from the bottom edge
    LIVES = 3
    SCORE_X = 12  # just right of the lives dots
    SCORE_DIGITS = 4  # 8px each; more would reach the pause glyph
    AIM_STEP_DEGREES = 5
    AIM_LIMIT_DEGREES = 70
    AIM_INDICATOR_LENGTH = 6
    BALL_SPEED = 1.0

    _ROW_COLORS = (
        (255, 0, 0),
        (255, 128, 0),
        (255, 255, 0),
        (0, 255, 0),
        (0, 128, 255),
    )
    _PADDLE = (255, 255, 255)
    # Cyan, not red: the top brick row is red and would swallow the ball.
    # (It's a fast-moving pixel, so subpixel fringing isn't a concern; the
    # stationary life dots below are single-channel.)
    _BALL = (0, 255, 255)
    _LIFE = (0, 255, 0)
    _AIM = (90, 90, 90)
    # White. The ball can tunnel above the wall and fly through the score
    # strip; it's drawn last, so it covers a digit pixel or two briefly.
    _SCORE = (255, 255, 255)

    def __init__(self, height: int, width: int) -> None:
        super().__init__(height, width)
        self.paddle_y = height - self.PADDLE_ROW_OFFSET
        self.waiting_to_serve = False
        self.aim_degrees = 0
        self.paused = False
        self._score_mask_cache: tuple[str, np.ndarray] = ("", np.zeros((8, 0), bool))
        self.reset()

    def press_button(self) -> None:
        if self.waiting_to_serve:
            self._launch()
        else:
            self.paused = not self.paused

    def reset(self) -> None:
        self.paused = False
        self.rows_cleared = 0
        self.lives = self.LIVES
        self._deal_bricks()
        self._serve()

    def _launch(self) -> None:
        self.waiting_to_serve = False
        angle = math.radians(self.aim_degrees)
        self.vx = self.BALL_SPEED * math.sin(angle)
        self.vy = -self.BALL_SPEED * math.cos(angle)

    def _deal_bricks(self) -> None:
        self.row_colors = list(self._ROW_COLORS)
        self.bricks = np.ones((self.BRICK_ROWS, self.BRICK_COLUMNS), dtype=bool)

    def _drop_rows_above(self, cleared_row: int) -> None:
        """Remove an emptied row: everything above it drops one row and a
        fresh full row appears on top. The wall's bottom edge never moves
        lower than where it started, so this can't crowd the paddle.
        """
        self.rows_cleared += 1
        # Colors travel with their rows, so the cleared row's color is the
        # one the fresh top row takes.
        self.row_colors.insert(0, self.row_colors.pop(cleared_row))
        self.bricks[1 : cleared_row + 1] = self.bricks[:cleared_row].copy()
        self.bricks[0] = True

    def _serve(self) -> None:
        self.paddle_x = (self.width - self.PADDLE_WIDTH) // 2
        self.waiting_to_serve = True
        self.aim_degrees = 0
        self.vx = 0.0
        self.vy = 0.0
        self._park_ball()

    def _park_ball(self) -> None:
        self.ball_x = self.paddle_x + self.PADDLE_WIDTH / 2
        self.ball_y = float(self.paddle_y - 1)

    def cycle_view(self, direction: int) -> None:
        if self.paused:
            return
        if self.waiting_to_serve:
            self.aim_degrees = min(
                max(
                    self.aim_degrees + direction * self.AIM_STEP_DEGREES,
                    -self.AIM_LIMIT_DEGREES,
                ),
                self.AIM_LIMIT_DEGREES,
            )
            return
        self.paddle_x = min(
            max(self.paddle_x + direction * self.PADDLE_STEP, 0),
            self.width - self.PADDLE_WIDTH,
        )
        if self.waiting_to_serve:
            self._park_ball()

    def _brick_at(self, x: float, y: float) -> tuple[int, int] | None:
        row = (int(y) - self.BRICK_TOP) // self.BRICK_HEIGHT
        column = int(x) // self.BRICK_WIDTH
        if (
            int(y) >= self.BRICK_TOP
            and 0 <= row < self.BRICK_ROWS
            and 0 <= column < self.BRICK_COLUMNS
            and self.bricks[row, column]
        ):
            return row, column
        return None

    def _cell(self, x: float, y: float) -> tuple[int, int]:
        """(column, row) in brick units; may fall outside the wall."""
        return (
            int(x) // self.BRICK_WIDTH,
            (int(y) - self.BRICK_TOP) // self.BRICK_HEIGHT,
        )

    def _bounce_off(self, hit: tuple[int, int], new_x: float, new_y: float) -> None:
        """Reverse whichever velocity component pushed the ball into `hit`.
        Entering from the side flips vx, from above/below flips vy; a
        diagonal entry flips the axis blocked by a neighbouring brick, or
        both when the ball clipped a lone corner.
        """
        old_column, old_row = self._cell(self.ball_x, self.ball_y)
        new_column, new_row = hit[1], hit[0]
        crossed_x = new_column != old_column
        crossed_y = new_row != old_row
        if crossed_x and crossed_y:
            side_blocked = self._brick_at_cell(new_row=old_row, column=new_column)
            vertical_blocked = self._brick_at_cell(new_row=new_row, column=old_column)
            flip_x = side_blocked or not vertical_blocked
            flip_y = vertical_blocked or not side_blocked
        else:
            flip_x, flip_y = crossed_x, crossed_y
        if flip_x:
            self.vx = -self.vx
        if flip_y:
            self.vy = -self.vy

    def _brick_at_cell(self, new_row: int, column: int) -> bool:
        return (
            0 <= new_row < self.BRICK_ROWS
            and 0 <= column < self.BRICK_COLUMNS
            and bool(self.bricks[new_row, column])
        )

    def advance(self) -> None:
        if self.waiting_to_serve or self.paused:
            return

        new_x = self.ball_x + self.vx
        new_y = self.ball_y + self.vy

        if new_x < 0 or new_x >= self.width:
            self.vx = -self.vx
            new_x = self.ball_x + self.vx
        if new_y < 0:
            self.vy = -self.vy
            new_y = self.ball_y + self.vy

        if (
            self.vy > 0
            and int(new_y) >= self.paddle_y
            and self.paddle_x <= new_x < self.paddle_x + self.PADDLE_WIDTH
        ):
            # Steer by where the ball lands on the paddle.
            offset = (new_x - self.paddle_x) / self.PADDLE_WIDTH * 2 - 1
            angle = offset * math.radians(60)
            self.vx = self.BALL_SPEED * math.sin(angle)
            self.vy = -self.BALL_SPEED * math.cos(angle)
            new_x = self.ball_x + self.vx
            new_y = float(self.paddle_y - 1)

        hit = self._brick_at(new_x, new_y)
        if hit is not None:
            self.bricks[hit] = False
            self._bounce_off(hit, new_x, new_y)
            new_x, new_y = self.ball_x, self.ball_y
            if not self.bricks[hit[0]].any():
                self._drop_rows_above(hit[0])

        self.ball_x, self.ball_y = new_x, new_y

        if self.ball_y >= self.height:
            self.lives -= 1
            if self.lives <= 0:
                self.reset()
            else:
                self._serve()

    def _score_mask(self) -> np.ndarray:
        """The score as an 8 x (4 digits) boolean mask, cached per value."""
        text = str(self.rows_cleared % 10**self.SCORE_DIGITS)
        if self._score_mask_cache[0] != text:
            width = self.SCORE_DIGITS * 8
            canvas = Image.new("1", (width, 8), 0)
            draw_text(ImageDraw.Draw(canvas), (0, 0), text, ticker_font())
            # Same idiom as games.menu / games.ticker: np.asarray on a
            # 1-bit PIL image isn't reliable across Pillow versions.
            pixels = np.asarray(list(canvas.get_flattened_data()), dtype=np.uint8)
            self._score_mask_cache = (text, pixels.reshape(8, width).astype(bool))
        return self._score_mask_cache[1]

    def _draw_score(self, frame: np.ndarray) -> None:
        mask = self._score_mask()
        region = frame[0:8, self.SCORE_X : self.SCORE_X + mask.shape[1]]
        region[mask[:, : region.shape[1]]] = self._SCORE

    @property
    def frame(self) -> np.ndarray:
        frame = np.zeros((self.height, self.width, 3), dtype=np.uint8)
        for row, column in zip(*np.nonzero(self.bricks)):
            top = self.BRICK_TOP + row * self.BRICK_HEIGHT
            left = column * self.BRICK_WIDTH
            # Leave a one-pixel gutter so neighbouring bricks read apart.
            frame[
                top : top + self.BRICK_HEIGHT - 1,
                left : left + self.BRICK_WIDTH - 1,
            ] = self.row_colors[row]
        frame[
            self.paddle_y : self.paddle_y + 1,
            self.paddle_x : self.paddle_x + self.PADDLE_WIDTH,
        ] = self._PADDLE
        for life in range(self.lives):
            frame[3, 1 + life * 3] = self._LIFE
        self._draw_score(frame)
        if self.waiting_to_serve:
            angle = math.radians(self.aim_degrees)
            for step in range(2, self.AIM_INDICATOR_LENGTH + 2):
                x = int(self.ball_x + math.sin(angle) * step)
                y = int(self.ball_y - math.cos(angle) * step)
                if 0 <= x < self.width and 0 <= y < self.height:
                    frame[y, x] = self._AIM
        if self.paused:
            draw_pause_icon(frame)
        ball_x, ball_y = int(self.ball_x), int(self.ball_y)
        if 0 <= ball_x < self.width and 0 <= ball_y < self.height:
            frame[ball_y, ball_x] = self._BALL
        return frame
