import os

import numpy as np
from PIL import Image
from rgbmatrix import RGBMatrix, RGBMatrixOptions


# Panel-timing knobs, tunable from the environment so flicker can be worked
# on the Pi without a redeploy. Each is only applied when set; unset leaves
# the value below (or the driver's own default).
_TIMING_OPTIONS = (
    ("CONWAY_LED_BRIGHTNESS", "brightness"),
    ("CONWAY_LED_GPIO_SLOWDOWN", "gpio_slowdown"),
    ("CONWAY_LED_PWM_BITS", "pwm_bits"),
    ("CONWAY_LED_PWM_LSB_NANOSECONDS", "pwm_lsb_nanoseconds"),
    ("CONWAY_LED_PWM_DITHER_BITS", "pwm_dither_bits"),
    ("CONWAY_LED_LIMIT_REFRESH_HZ", "limit_refresh_rate_hz"),
)


def _apply_timing_overrides(options) -> None:
    for variable, attribute in _TIMING_OPTIONS:
        text = os.getenv(variable)
        if text is None:
            continue
        try:
            setattr(options, attribute, int(text))
        except ValueError as error:
            raise ValueError(f"{variable} must be an integer, got {text!r}") from error


class MatrixDisplay:
    """Sends RGB frames to the LED matrix."""

    def __init__(self, height: int, width: int, rotation: int = 180) -> None:
        if rotation % 90 != 0:
            raise ValueError("rotation must be a multiple of 90 degrees")
        # np.rot90's positive k rotates counter-clockwise, so negate to make
        # positive `rotation` degrees mean clockwise, matching how someone
        # would describe rotating the physical panel.
        self._rotation_quarters = -(rotation // 90) % 4

        options = RGBMatrixOptions()
        options.rows = height
        options.cols = width
        options.chain_length = 1
        options.hardware_mapping = "adafruit-hat"
        options.brightness = 50
        options.gpio_slowdown = 2
        _apply_timing_overrides(options)

        self._matrix = RGBMatrix(options=options)
        self._canvas = self._matrix.CreateFrameCanvas()

    def show(self, frame: np.ndarray) -> None:
        if self._rotation_quarters:
            frame = np.rot90(frame, k=self._rotation_quarters)
        image = Image.fromarray(frame, mode="RGB")
        self._canvas.SetImage(image)
        self._canvas = self._matrix.SwapOnVSync(self._canvas)

    def turn_off(self) -> None:
        """Clear the visible matrix."""
        self._canvas.Clear()
        self._canvas = self._matrix.SwapOnVSync(self._canvas)
