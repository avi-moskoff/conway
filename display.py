import numpy as np
from PIL import Image
from rgbmatrix import RGBMatrix, RGBMatrixOptions


class MatrixDisplay:
    """Sends RGB frames to the LED matrix."""

    def __init__(self, height: int, width: int) -> None:
        options = RGBMatrixOptions()
        options.rows = height
        options.cols = width
        options.chain_length = 1
        options.hardware_mapping = "adafruit-hat"
        options.brightness = 50
        options.gpio_slowdown = 2

        self._matrix = RGBMatrix(options=options)
        self._canvas = self._matrix.CreateFrameCanvas()

    def show(self, frame: np.ndarray) -> None:
        image = Image.fromarray(frame, mode="RGB")
        self._canvas.SetImage(image)
        self._canvas = self._matrix.SwapOnVSync(self._canvas)

    def turn_off(self) -> None:
        """Clear the visible matrix."""
        self._canvas.Clear()
        self._canvas = self._matrix.SwapOnVSync(self._canvas)
