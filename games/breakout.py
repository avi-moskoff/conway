import math
import random

import numpy as np

from games.base import Game


class BreakoutGame(Game):
    """Breakout: each encoder click slides the paddle PADDLE_STEP pixels.
    The ball waits on the paddle until the button launches it; while it
    waits, the knob aims the launch (an indicator shows the heading) and
    the paddle stays put. Once it's in play, the knob slides the paddle
    and the button restarts the game instead. Clearing every brick
    deals a fresh wall; losing all lives restarts.
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
    AIM_STEP_DEGREES = 5
    AIM_LIMIT_DEGREES = 70
    AIM_INDICATOR_LENGTH = 6
    BALL_SPEED = 1.0

    # One hue (amber, as in the AQI colormap) with lightness stepping down
    # the rows: the rows carry no meaning, so no categorical colors.
    _ROW_COLORS = (
        (255, 176, 0),
        (217, 150, 0),
        (178, 123, 0),
        (140, 97, 0),
        (102, 70, 0),
    )
    _PADDLE = (255, 255, 255)
    # Red is the design language's "look here first" signal - the ball is
    # what you're watching. (It's a moving pixel, so subpixel fringing
    # isn't a concern; the stationary life dots below are single-channel.)
    _BALL = (255, 0, 0)
    _LIFE = (0, 255, 0)
    _AIM = (90, 90, 90)

    def __init__(self, height: int, width: int) -> None:
        super().__init__(height, width)
        self.paddle_y = height - self.PADDLE_ROW_OFFSET
        self.waiting_to_serve = False
        self.aim_degrees = 0
        self.reset()

    def reset(self) -> None:
        if self.waiting_to_serve:
            self._launch()
            return
        self.lives = self.LIVES
        self._deal_bricks()
        self._serve()

    def _launch(self) -> None:
        self.waiting_to_serve = False
        angle = math.radians(self.aim_degrees)
        self.vx = self.BALL_SPEED * math.sin(angle)
        self.vy = -self.BALL_SPEED * math.cos(angle)

    def _deal_bricks(self) -> None:
        self.bricks = np.ones((self.BRICK_ROWS, self.BRICK_COLUMNS), dtype=bool)

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

    def advance(self) -> None:
        if self.waiting_to_serve:
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
            if self._brick_at(new_x, self.ball_y) is None and int(new_x) != int(
                self.ball_x
            ):
                # Came in sideways through a brick's flank.
                self.vx = -self.vx
            else:
                self.vy = -self.vy
            new_x, new_y = self.ball_x, self.ball_y
            if not self.bricks.any():
                self._deal_bricks()
                self._serve()
                return

        self.ball_x, self.ball_y = new_x, new_y

        if self.ball_y >= self.height:
            self.lives -= 1
            if self.lives <= 0:
                self.reset()
            else:
                self._serve()

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
            ] = self._ROW_COLORS[row % len(self._ROW_COLORS)]
        frame[
            self.paddle_y : self.paddle_y + 1,
            self.paddle_x : self.paddle_x + self.PADDLE_WIDTH,
        ] = self._PADDLE
        for life in range(self.lives):
            frame[1, 1 + life * 3] = self._LIFE
        if self.waiting_to_serve:
            angle = math.radians(self.aim_degrees)
            for step in range(2, self.AIM_INDICATOR_LENGTH + 2):
                x = int(self.ball_x + math.sin(angle) * step)
                y = int(self.ball_y - math.cos(angle) * step)
                if 0 <= x < self.width and 0 <= y < self.height:
                    frame[y, x] = self._AIM
        ball_x, ball_y = int(self.ball_x), int(self.ball_y)
        if 0 <= ball_x < self.width and 0 <= ball_y < self.height:
            frame[ball_y, ball_x] = self._BALL
        return frame
