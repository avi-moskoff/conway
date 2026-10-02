from contextlib import contextmanager
import sys
from types import ModuleType
import unittest
from unittest.mock import patch

import numpy as np

from games.base import Game
from games.conway import GameOfLife, boot_seed_board, boot_seed_frame


class FakeDevice:
    def __init__(self, *args, **_kwargs) -> None:
        self.args = args
        self.is_on = False
        self.is_blinking = False

    def on(self) -> None:
        self.is_on = True
        self.is_blinking = False

    def off(self) -> None:
        self.is_on = False
        self.is_blinking = False

    def blink(self, *_args, **_kwargs) -> None:
        # Real gpiozero blinking happens on a background thread; the fake
        # only needs to record that blinking was requested, not animate.
        self.is_blinking = True


class FakeDisplay:
    def __init__(self, _height, _width, rotation: int = 90) -> None:
        # What was already cached the moment the "matrix" came into
        # existence - the real RGBMatrix drops root here, after which
        # uncached fonts can no longer be read (see preload_fonts).
        from games import fonts

        self.fonts_cached_at_init = set(fonts._cache)
        self.frames = 0
        self.shown_frames: list = []
        self.is_off = False
        self.on_show = lambda: None

    def show(self, frame) -> None:
        self.frames += 1
        self.shown_frames.append(frame)
        self.on_show()

    def turn_off(self) -> None:
        self.is_off = True


class LifecycleGame(Game):
    frame_delay_seconds = 0

    def __init__(self) -> None:
        super().__init__(64, 64)
        self.activations = 0
        self.deactivations = 0
        self.closes = 0

    @property
    def frame(self) -> np.ndarray:
        return np.zeros((64, 64, 3), dtype=np.uint8)

    def activate(self) -> None:
        self.activations += 1

    def deactivate(self) -> None:
        self.deactivations += 1

    def close(self) -> None:
        self.closes += 1

    def reset(self) -> None:
        pass

    def advance(self) -> None:
        pass


class RecordingGame(Game):
    """A game that records what the runner does to it, for the
    interaction-model tests below - reset() and cycle_view() calls in
    particular, since those are exactly what on_button_pressed and
    on_rotate are responsible for routing.
    """

    frame_delay_seconds = 0

    def __init__(self, label: str) -> None:
        super().__init__(64, 64)
        self.menu_label = label
        self.reset_calls = 0
        self.cycle_calls: list[int] = []
        self.activations = 0
        self.deactivations = 0

    @property
    def frame(self) -> np.ndarray:
        return np.zeros((64, 64, 3), dtype=np.uint8)

    def activate(self) -> None:
        self.activations += 1

    def deactivate(self) -> None:
        self.deactivations += 1

    def reset(self) -> None:
        self.reset_calls += 1

    def advance(self) -> None:
        pass

    def cycle_view(self, direction: int) -> None:
        self.cycle_calls.append(direction)


@contextmanager
def patched_runner(games):
    gpiozero = ModuleType("gpiozero")
    gpiozero.Button = FakeDevice
    gpiozero.LED = FakeDevice
    gpiozero.RotaryEncoder = FakeDevice
    display = ModuleType("display")
    display.MatrixDisplay = FakeDisplay
    with patch.dict(sys.modules, {"gpiozero": gpiozero, "display": display}):
        sys.modules.pop("runner", None)
        from runner import GameRunner

        yield GameRunner(games)


class RunnerLifecycleTests(unittest.TestCase):
    def test_switch_and_shutdown_run_all_lifecycle_cleanup(self) -> None:
        first, second = LifecycleGame(), LifecycleGame()
        with patched_runner([first, second]) as runner:

            def switch_then_stop() -> None:
                if runner.display.frames == 1:
                    runner.switch_game(second)
                else:
                    runner.stop(0, None)

            runner.display.on_show = switch_then_stop
            runner.run()

            self.assertEqual((first.activations, first.deactivations), (1, 1))
            self.assertEqual((second.activations, second.deactivations), (1, 1))
            self.assertEqual((first.closes, second.closes), (1, 1))
            self.assertTrue(runner.display.is_off)
            self.assertFalse(runner._button_led_red.is_on)


class ButtonAndEncoderRoutingTests(unittest.TestCase):
    """The button and encoder's meaning now depends on whether the
    switcher is open (see runner.on_button_pressed / on_rotate /
    on_encoder_push) - these confirm each side of that split.
    """

    def test_button_resets_the_active_game_when_the_menu_is_closed(self) -> None:
        game = RecordingGame("ONE")
        with patched_runner([game]) as runner:
            runner.on_button_pressed()
            self.assertEqual(game.reset_calls, 1)

    def test_button_selects_the_highlighted_screen_while_the_menu_is_open(
        self,
    ) -> None:
        first, second = RecordingGame("ONE"), RecordingGame("TWO")
        with patched_runner([first, second]) as runner:
            runner._running = True
            runner.on_encoder_push()  # open the switcher
            runner.on_rotate(1)
            runner.on_button_pressed()
            self.assertFalse(runner._menu_open)
            self.assertEqual(runner._game_index, 1)
            self.assertEqual(second.activations, 1)
            self.assertEqual(first.reset_calls, 0)
            self.assertEqual(second.reset_calls, 0)

    def test_rotating_cycles_the_active_games_own_views_when_menu_is_closed(
        self,
    ) -> None:
        game = RecordingGame("ONE")
        with patched_runner([game]) as runner:
            runner.on_rotate(1)
            runner.on_rotate(-1)
            self.assertEqual(game.cycle_calls, [1, -1])

    def test_rotating_moves_the_highlight_instead_of_cycling_views_when_menu_is_open(
        self,
    ) -> None:
        first, second = RecordingGame("ONE"), RecordingGame("TWO")
        with patched_runner([first, second]) as runner:
            runner.on_encoder_push()  # open the switcher, highlighting "ONE"
            runner.on_rotate(1)
            self.assertEqual(first.cycle_calls, [])
            self.assertEqual(second.cycle_calls, [])
            self.assertEqual(runner._menu.selected_index, 1)


class SwitcherTests(unittest.TestCase):
    def test_first_push_opens_the_switcher_on_the_active_screen_and_blinks_the_led(
        self,
    ) -> None:
        first, second = RecordingGame("ONE"), RecordingGame("TWO")
        with patched_runner([first, second]) as runner:
            runner.on_encoder_push()
            self.assertTrue(runner._menu_open)
            self.assertEqual(runner._menu.labels, ("ONE", "TWO"))
            self.assertEqual(runner._menu.selected_index, 0)
            self.assertTrue(runner._button_led_red.is_blinking)

    def test_second_push_confirms_the_highlighted_screen_and_stops_blinking(
        self,
    ) -> None:
        first, second = RecordingGame("ONE"), RecordingGame("TWO")
        with patched_runner([first, second]) as runner:
            runner._running = True
            runner.on_encoder_push()
            runner.on_rotate(1)
            runner.on_encoder_push()
            self.assertFalse(runner._menu_open)
            self.assertIs(runner.game, second)
            self.assertFalse(runner._button_led_red.is_blinking)
            self.assertTrue(runner._button_led_red.is_on)

    def test_confirming_the_already_active_screen_does_not_deactivate_it(
        self,
    ) -> None:
        first, second = RecordingGame("ONE"), RecordingGame("TWO")
        with patched_runner([first, second]) as runner:
            runner._running = True
            runner.on_encoder_push()
            runner.on_encoder_push()  # confirm without moving the highlight
            self.assertIs(runner.game, first)
            self.assertEqual(first.deactivations, 0)
            self.assertEqual(first.activations, 0)

    def test_confirming_a_different_screen_transitions_lifecycle(self) -> None:
        first, second = RecordingGame("ONE"), RecordingGame("TWO")
        with patched_runner([first, second]) as runner:
            runner._running = True
            runner.on_encoder_push()
            runner.on_rotate(1)
            runner.on_encoder_push()
            self.assertEqual(first.deactivations, 1)
            self.assertEqual(second.activations, 1)

    def test_menu_highlight_wraps_around_the_screen_list(self) -> None:
        first, second = RecordingGame("ONE"), RecordingGame("TWO")
        with patched_runner([first, second]) as runner:
            runner.on_encoder_push()
            runner.on_rotate(-1)
            self.assertEqual(runner._menu.selected_index, 1)

    def test_encoder_pins_are_swapped_so_clockwise_is_clockwise(self) -> None:
        games = [RecordingGame("ONE"), RecordingGame("TWO")]
        with patched_runner(games) as runner:
            encoder = runner._game_encoder_yellow_white
            self.assertEqual(encoder.args, (19, 18))
            encoder.when_rotated_clockwise()
            encoder.when_rotated_counter_clockwise()
            self.assertEqual(games[0].cycle_calls, [1, -1])


class BootScreenTests(unittest.TestCase):
    # With the environment cleared, the real default roster is exactly
    # four games (GameOfLife, Langton, BoidsGame, SnakeGame) - flight/weather need
    # CONWAY_HOME_LATITUDE/LONGITUDE, which are unset. See
    # runner.GameRunner._default_game_factories.
    DEFAULT_ROSTER_SIZE = 4

    def test_the_default_roster_boots_into_the_fully_progressed_conway_seed(
        self,
    ) -> None:
        # See games.conway.GameOfLife.seed_boot_progress and the design
        # doc's Boot sequence section: by the time games are built, every
        # game has actually been constructed, so the board they end up
        # holding should already show the seed at full progress (N/N for
        # this roster), not random.
        with patch.dict("os.environ", {}, clear=True):
            with patched_runner(None) as runner:
                life = runner.game
                self.assertIsInstance(life, GameOfLife)
                expected = boot_seed_board(
                    64, 64, self.DEFAULT_ROSTER_SIZE, self.DEFAULT_ROSTER_SIZE
                )
                np.testing.assert_array_equal(life.board, expected)

    def test_the_default_roster_paints_the_bar_climbing_from_zero_as_each_game_builds(
        self,
    ) -> None:
        # The matrix is constructed - and painted - before game
        # construction even starts (see
        # runner.GameRunner._build_default_games_with_progress), and the
        # bar's denominator is now how many games are actually being
        # built, not a fixed stage count - so the very first frame should
        # be 0/N (no games built yet), climbing by one full segment each
        # time a game finishes, ending at N/N once the roster's complete.
        with patch.dict("os.environ", {}, clear=True):
            with patched_runner(None) as runner:
                total = self.DEFAULT_ROSTER_SIZE
                expected_frames = [
                    boot_seed_frame(64, 64, completed, total)
                    for completed in range(total + 1)
                ]
                self.assertEqual(len(runner.display.shown_frames), len(expected_frames))
                for shown, expected in zip(
                    runner.display.shown_frames, expected_frames
                ):
                    np.testing.assert_array_equal(shown, expected)

    def test_every_font_is_cached_before_the_matrix_is_constructed(self) -> None:
        # Regression: RGBMatrix drops root privileges when constructed, so
        # a font first loaded after that fails with "cannot open resource"
        # on real hardware. Clear the cache so this can't pass just
        # because an earlier test already loaded the fonts.
        from games import fonts

        fonts._cache.clear()
        with patch.dict("os.environ", {}, clear=True):
            with patched_runner(None) as runner:
                self.assertEqual(
                    runner.display.fonts_cached_at_init,
                    {"unscii-8.ttf:8", "unscii-16.ttf:16"},
                )

    def test_a_caller_supplied_roster_is_left_alone(self) -> None:
        # The boot seed is specifically for the real default roster - a
        # test (or any other caller) that hands GameRunner its own games
        # shouldn't have them silently rewritten.
        life = GameOfLife(64, 64)
        life.reset()
        original_board = life.board.copy()
        with patched_runner([life]) as runner:
            np.testing.assert_array_equal(runner.game.board, original_board)
            # No boot frame should be painted for a caller-supplied
            # roster either - the matrix's only frame by this point
            # should be whatever the run loop paints, and __init__ never
            # calls display.show() for a non-default roster.
            self.assertEqual(runner.display.shown_frames, [])


if __name__ == "__main__":
    unittest.main()
