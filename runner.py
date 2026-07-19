from collections.abc import Sequence
from signal import SIGTERM, signal
from threading import Event, Lock

import numpy as np
from gpiozero import Button, LED, RotaryEncoder

from display import MatrixDisplay
from games import BoidsGame, Game, GameOfLife


class GameRunner:
    """Runs one retained game state at a time."""

    HEIGHT = 64
    WIDTH = 64

    def __init__(self, games: Sequence[Game] | None = None) -> None:
        self._game_lock = Lock()
        self._stop_event = Event()
        self._games = (
            list(games)
            if games is not None
            else [
                GameOfLife(self.HEIGHT, self.WIDTH),
                BoidsGame(self.HEIGHT, self.WIDTH),
            ]
        )
        if not self._games:
            raise ValueError("At least one game is required")
        for game in self._games:
            self._validate_game(game)
        self._game_index = 0

        # GPIO devices must be initialized before the matrix.
        self._button_led_red = LED(15)
        self._reset_button_green = Button(14)
        self._game_encoder_yellow_white = RotaryEncoder(18, 19)
        self._button_led_red.on()
        self._reset_button_green.when_pressed = self.reset_current_game
        self._game_encoder_yellow_white.when_rotated_clockwise = self.next_game
        self._game_encoder_yellow_white.when_rotated_counter_clockwise = (
            self.previous_game
        )

        self.display = MatrixDisplay(self.HEIGHT, self.WIDTH)

    @property
    def game(self) -> Game:
        with self._game_lock:
            return self._games[self._game_index]

    def switch_game(self, game: Game) -> None:
        """Make an existing game state active without resetting it."""
        self._validate_game(game)
        with self._game_lock:
            try:
                self._game_index = self._games.index(game)
            except ValueError:
                self._games.append(game)
                self._game_index = len(self._games) - 1

    def next_game(self) -> None:
        with self._game_lock:
            self._game_index = (self._game_index + 1) % len(self._games)

    def previous_game(self) -> None:
        with self._game_lock:
            self._game_index = (self._game_index - 1) % len(self._games)

    def reset_current_game(self) -> None:
        with self._game_lock:
            self._games[self._game_index].reset()

    def _advance_if_current(self, game: Game) -> None:
        with self._game_lock:
            if game is self._games[self._game_index]:
                game.advance()

    def _current_frame(self) -> tuple[Game, np.ndarray]:
        with self._game_lock:
            game = self._games[self._game_index]
            return game, game.frame

    def _validate_game(self, game: Game) -> None:
        if (game.height, game.width) != (self.HEIGHT, self.WIDTH):
            raise ValueError(
                f"Game must be {self.HEIGHT}x{self.WIDTH}, "
                f"got {game.height}x{game.width}"
            )

    def stop(self, _signal_number: int, _frame: object) -> None:
        """Request a graceful stop from a process signal handler."""
        self._stop_event.set()

    def run(self) -> None:
        self._stop_event.clear()
        previous_sigterm_handler = signal(SIGTERM, self.stop)
        try:
            while not self._stop_event.is_set():
                game, frame = self._current_frame()
                self.display.show(frame)
                if self._stop_event.wait(game.frame_delay_seconds):
                    break
                self._advance_if_current(game)
        finally:
            try:
                try:
                    self.display.turn_off()
                finally:
                    self._button_led_red.off()
            finally:
                signal(SIGTERM, previous_sigterm_handler)
