from collections.abc import Callable, Sequence
import logging
import os
from signal import SIGTERM, signal
from threading import Event, Lock

import numpy as np
from gpiozero import Button, LED, RotaryEncoder

from config import FlightRadarConfig, WeatherRadarConfig
from display import MatrixDisplay
from games import (
    BoidsGame,
    BreakoutGame,
    FlightRadarGame,
    Game,
    GameOfLife,
    Langton,
    SnakeGame,
    WeatherRadarGame,
    boot_seed_frame,
)
from games.fonts import preload_fonts
from games.menu import ScreenMenu

logger = logging.getLogger(__name__)


class GameRunner:
    """Runs one retained game state at a time, with a switcher screen
    (see games.menu.ScreenMenu) for picking which one.
    """

    HEIGHT = 64
    WIDTH = 64

    def __init__(self, games: Sequence[Game] | None = None) -> None:
        self._game_lock = Lock()
        self._stop_event = Event()
        self._menu = ScreenMenu(self.HEIGHT, self.WIDTH)
        self._menu_open = False

        # GPIO devices are claimed first, ahead of both game construction
        # and the matrix - see the design doc's Boot sequence section on
        # why the LED's "process alive" signal is kept as prompt and as
        # separate from "booting"/"ready" as possible.
        self._button_led_red = LED(15)
        self._reset_button_green = Button(14, bounce_time=0.2)
        # A/B are deliberately given as (19, 18): with this encoder's
        # wiring, the natural (18, 19) order reported clockwise turns as
        # counter-clockwise. Swapping here makes gpiozero's "clockwise"
        # physically clockwise, so the callbacks below mean what they say.
        self._game_encoder_yellow_white = RotaryEncoder(19, 18)
        # The encoder's own integrated push switch, wired to its third pin
        # (GPIO 25) alongside the A/B pins above.
        # A short debounce: gpiozero's bounce_time is a glitch filter, so
        # any press shorter than it is dropped outright. 0.2 s swallowed
        # ordinary quick clicks on the encoder.
        self._encoder_push_button = Button(25, bounce_time=0.05)
        self._button_led_red.on()
        self._reset_button_green.when_pressed = self.on_button_pressed
        self._game_encoder_yellow_white.when_rotated_clockwise = (
            lambda: self.on_rotate(1)
        )
        self._game_encoder_yellow_white.when_rotated_counter_clockwise = (
            lambda: self.on_rotate(-1)
        )
        self._encoder_push_button.when_pressed = self.on_encoder_push

        using_default_games = games is None

        # Matrix construction comes right after GPIO claim, deliberately
        # ahead of game construction - the reverse of an earlier version
        # of this ordering. That earlier version worried that a screen
        # lit up before "everything" was ready would be a false signal,
        # but that conflated two different things: a *full* progress bar
        # (or the board starting to move) is a readiness claim, while a
        # *partial* bar is the opposite - an honest "not yet." Building
        # the matrix now, before the slow part (game construction -
        # WeatherRadarGame alone is real seconds of numpy work on a Pi
        # Zero 2 W), is what lets a real, incrementally-updated bar be
        # seen at all. See the design doc's Boot sequence section.
        # Fonts must be loaded (and cached) before the matrix exists:
        # RGBMatrix drops root privileges as soon as it's constructed, and
        # the unprivileged user it drops to can't read /home/avi. See
        # games.fonts.preload_fonts.
        preload_fonts()
        rotation = int(os.getenv("CONWAY_DISPLAY_ROTATION", "180"))
        self.display = MatrixDisplay(self.HEIGHT, self.WIDTH, rotation=rotation)

        if using_default_games:
            self._games = self._build_default_games_with_progress()
        else:
            self._games = list(games)
        if not self._games:
            raise ValueError("At least one game is required")
        for game in self._games:
            self._validate_game(game)
        logger.info(
            "Available games (%d): %s",
            len(self._games),
            ", ".join(type(game).__name__ for game in self._games),
        )
        self._game_index = 0
        self._running = False

    def _build_default_games_with_progress(self) -> list[Game]:
        """Builds the real default roster one game at a time, painting
        the boot progress bar after each one finishes - see the design
        doc's Boot sequence section. Game construction is the only part
        of boot with real, variable duration (WeatherRadarGame's grid
        precompute especially), so the bar now tracks it directly:
        total_stages is simply how many games are about to be built.
        _default_game_factories resolves which screens are configured
        (env lookups only, no real construction cost) before anything is
        actually built, so the true denominator is known up front rather
        than growing as games finish - the bar genuinely starts at 0/N,
        not at some fraction already claimed by stages nothing here can
        observe (matrix construction just above is the one such stage:
        it has to already be done for any of this to be paintable at
        all, so it isn't counted as a segment of its own).
        """
        factories = self._default_game_factories()
        total_stages = len(factories)
        games: list[Game] = []
        self.display.show(boot_seed_frame(self.HEIGHT, self.WIDTH, 0, total_stages))
        for factory in factories:
            games.append(factory())
            self.display.show(
                boot_seed_frame(self.HEIGHT, self.WIDTH, len(games), total_stages)
            )
        # The frames above are painted directly (no live GameOfLife board
        # exists yet to paint from), so the real instance's board needs
        # its own seed applied too, matching that final frame exactly -
        # this is what run() then paints as its very first loop frame.
        for game in games:
            if isinstance(game, GameOfLife):
                game.seed_boot_progress(total_stages, total_stages)
                break
        return games

    @property
    def game(self) -> Game:
        with self._game_lock:
            return self._games[self._game_index]

    def switch_game(self, game: Game) -> None:
        """Make an existing game state active without resetting it."""
        self._validate_game(game)
        with self._game_lock:
            old_game = self._games[self._game_index]
            try:
                self._game_index = self._games.index(game)
            except ValueError:
                self._games.append(game)
                self._game_index = len(self._games) - 1
            new_game = self._games[self._game_index]
            running = self._running
        self._transition(old_game, new_game, running)

    @staticmethod
    def _transition(old_game: Game, new_game: Game, running: bool) -> None:
        if running and old_game is not new_game:
            old_game.deactivate()
            new_game.activate()
            logger.info("Selected game: %s", type(new_game).__name__)

    def on_button_pressed(self) -> None:
        """Outside the switcher, the button force-refreshes whatever's on
        screen (games.base.Game.reset). While the switcher is open it means
        "select", exactly like pressing the encoder in again.
        """
        with self._game_lock:
            menu_open = self._menu_open
            game = self._games[self._game_index]
        if menu_open:
            self.on_encoder_push()
            return
        game.reset()

    def on_rotate(self, direction: int) -> None:
        """Rotating the encoder is context-dependent: while the switcher
        is open it moves the highlighted row; otherwise it cycles the
        active screen's own sibling views (games.base.Game.cycle_view).
        Switching screens is the switcher's job now, not a free rotation.
        """
        with self._game_lock:
            if self._menu_open:
                self._menu.move_selection(direction)
                return
            game = self._games[self._game_index]
        game.cycle_view(direction)

    def on_encoder_push(self) -> None:
        """Pressing the encoder in opens the switcher; pressing it again
        confirms the highlighted screen and closes it.
        """
        with self._game_lock:
            if self._menu_open:
                old_game = self._games[self._game_index]
                self._game_index = self._menu.selected_index
                new_game = self._games[self._game_index]
                running = self._running
                self._menu_open = False
                transition: tuple[Game, Game, bool] | None = (
                    old_game,
                    new_game,
                    running,
                )
            else:
                self._menu.open(self._menu_labels(), self._game_index)
                self._menu_open = True
                transition = None
        if transition is not None:
            self._transition(*transition)
        self._sync_led()

    def _menu_labels(self) -> tuple[str, ...]:
        return tuple(game.menu_label for game in self._games)

    def _sync_led(self) -> None:
        """The button light doubles as a menu-open indicator: solid while
        idle, blinking while the switcher is open.
        """
        if self._menu_open:
            self._button_led_red.blink()
        else:
            self._button_led_red.on()

    def _advance_if_current(self, game: Game) -> None:
        with self._game_lock:
            if game is self._games[self._game_index]:
                game.advance()

    def _current_frame(self) -> tuple[Game, np.ndarray]:
        with self._game_lock:
            game = self._games[self._game_index]
            frame = self._menu.frame if self._menu_open else game.frame
            return game, frame

    def _validate_game(self, game: Game) -> None:
        if (game.height, game.width) != (self.HEIGHT, self.WIDTH):
            raise ValueError(
                f"Game must be {self.HEIGHT}x{self.WIDTH}, "
                f"got {game.height}x{game.width}"
            )

    def _default_game_factories(self) -> list[Callable[[], Game]]:
        """Returns constructor thunks for the real default roster, in
        registration order, without calling any of them yet - see
        _build_default_games_with_progress, which needs the roster's
        true size before paying any construction cost.
        """
        factories: list[Callable[[], Game]] = [
            lambda: GameOfLife(self.HEIGHT, self.WIDTH),
            lambda: Langton(self.HEIGHT, self.WIDTH),
            lambda: BoidsGame(self.HEIGHT, self.WIDTH),
            lambda: SnakeGame(self.HEIGHT, self.WIDTH),
            lambda: BreakoutGame(self.HEIGHT, self.WIDTH),
        ]
        flight_config = FlightRadarConfig.from_environment()
        if flight_config is not None:
            factories.append(
                lambda: FlightRadarGame(self.HEIGHT, self.WIDTH, config=flight_config)
            )
        else:
            logger.info("Flight radar disabled: home coordinates are not configured")
        weather_config = WeatherRadarConfig.from_environment()
        if weather_config is not None:
            factories.append(
                lambda: WeatherRadarGame(self.HEIGHT, self.WIDTH, config=weather_config)
            )
        else:
            logger.info("Weather radar disabled: home coordinates are not configured")
        return factories

    def stop(self, _signal_number: int, _frame: object) -> None:
        """Request a graceful stop from a process signal handler."""
        self._stop_event.set()

    def run(self) -> None:
        self._stop_event.clear()
        previous_sigterm_handler = signal(SIGTERM, self.stop)
        try:
            with self._game_lock:
                self._running = True
                initial_game = self._games[self._game_index]
            initial_game.activate()
            logger.info("Selected game: %s", type(initial_game).__name__)
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
                try:
                    with self._game_lock:
                        self._running = False
                        active_game = self._games[self._game_index]
                    active_game.deactivate()
                    for game in self._games:
                        game.close()
                finally:
                    signal(SIGTERM, previous_sigterm_handler)
