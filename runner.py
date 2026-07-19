from threading import Lock
from time import sleep

from gpiozero import Button, LED

from display import MatrixDisplay
from games import Game, GameOfLife


class GameRunner:
    """Runs one game state at a time and allows it to be replaced."""

    HEIGHT = 64
    WIDTH = 64
    FRAME_DELAY_SECONDS = 1

    def __init__(self, game: Game | None = None) -> None:
        self._game_lock = Lock()
        self._game = game or GameOfLife(self.HEIGHT, self.WIDTH)
        self._validate_game(self._game)

        # GPIO devices must be initialized before the matrix.
        self._status_led = LED(15)
        self._reset_button = Button(14)
        self._status_led.on()
        self._reset_button.when_pressed = self.reset_current_game

        self.display = MatrixDisplay(self.HEIGHT, self.WIDTH)

    @property
    def game(self) -> Game:
        with self._game_lock:
            return self._game

    def switch_game(self, game: Game) -> None:
        """Make an existing game state active without resetting it."""
        self._validate_game(game)
        with self._game_lock:
            self._game = game

    def reset_current_game(self) -> None:
        with self._game_lock:
            self._game.reset()

    def _advance_if_current(self, game: Game) -> None:
        with self._game_lock:
            if game is self._game:
                game.advance()

    def _validate_game(self, game: Game) -> None:
        if (game.height, game.width) != (self.HEIGHT, self.WIDTH):
            raise ValueError(
                f"Game must be {self.HEIGHT}x{self.WIDTH}, "
                f"got {game.height}x{game.width}"
            )

    def run(self) -> None:
        try:
            while True:
                game = self.game
                self.display.show(game.frame)
                sleep(self.FRAME_DELAY_SECONDS)
                self._advance_if_current(game)
        finally:
            try:
                self.display.turn_off()
            finally:
                self._status_led.off()
