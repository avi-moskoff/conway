import numpy as np
import random
from rgbmatrix import RGBMatrix, RGBMatrixOptions
import argparse
from time import sleep
from scipy.signal import convolve2d
from PIL import Image


def get_next_board(board: np.ndarray) -> np.ndarray:
    kernel = np.array([[1, 1, 1], [1, 0, 1], [1, 1, 1]])

    neighbors = convolve2d(board, kernel, mode="same", boundary="wrap")
    return (
        ((board == 1) & ((neighbors == 2) | (neighbors == 3)))
        | ((board == 0) & (neighbors == 3))
    ).astype(int)


def main():
    # parser = argparse.ArgumentParser()
    # parser.add_argument('-m', '--multiplex', type=int)
    # args = parser.parse_args()
    height = 64
    width = 64
    options = RGBMatrixOptions()
    options.rows = height
    options.cols = width
    options.chain_length = 1
    options.hardware_mapping = "adafruit-hat"
    options.brightness = 50
    options.gpio_slowdown = 2
    matrix = RGBMatrix(options=options)

    canvas = matrix.CreateFrameCanvas()

    board = np.array(
        [[random.randint(0, 1) for _ in range(width)] for _ in range(height)]
    )
    palette = np.array([[0, 0, 0], [255, 255, 255]], dtype=np.uint8)

    while True:
        rgb = palette[board.astype(np.uint8)]
        img = Image.fromarray(rgb, mode="RGB")
        canvas.SetImage(img)
        canvas = matrix.SwapOnVSync(canvas)
        sleep(1)
        board = get_next_board(board)


if __name__ == "__main__":
    main()
