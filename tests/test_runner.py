import sys
from types import ModuleType
import unittest
from unittest.mock import patch

import numpy as np

from games.base import Game


class FakeDevice:
    def __init__(self, *_args) -> None:
        self.is_on = False

    def on(self) -> None:
        self.is_on = True

    def off(self) -> None:
        self.is_on = False


class FakeDisplay:
    def __init__(self, _height, _width) -> None:
        self.frames = 0
        self.is_off = False
        self.on_show = lambda: None

    def show(self, _frame) -> None:
        self.frames += 1
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


class RunnerLifecycleTests(unittest.TestCase):
    def test_switch_and_shutdown_run_all_lifecycle_cleanup(self) -> None:
        gpiozero = ModuleType("gpiozero")
        gpiozero.Button = FakeDevice
        gpiozero.LED = FakeDevice
        gpiozero.RotaryEncoder = FakeDevice
        display = ModuleType("display")
        display.MatrixDisplay = FakeDisplay
        with patch.dict(sys.modules, {"gpiozero": gpiozero, "display": display}):
            sys.modules.pop("runner", None)
            from runner import GameRunner

            first, second = LifecycleGame(), LifecycleGame()
            runner = GameRunner([first, second])

            def switch_then_stop() -> None:
                if runner.display.frames == 1:
                    runner.next_game()
                else:
                    runner.stop(0, None)

            runner.display.on_show = switch_then_stop
            runner.run()

        self.assertEqual((first.activations, first.deactivations), (1, 1))
        self.assertEqual((second.activations, second.deactivations), (1, 1))
        self.assertEqual((first.closes, second.closes), (1, 1))
        self.assertTrue(runner.display.is_off)
        self.assertFalse(runner._button_led_red.is_on)


if __name__ == "__main__":
    unittest.main()
