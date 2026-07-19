import numpy as np
from rgbmatrix import RGBMatrix, RGBMatrixOptions
from time import sleep
from scipy.signal import convolve2d
from PIL import Image
from gpiozero import LED, Button


def get_next_board(board: np.ndarray) -> np.ndarray:
    kernel = np.array([[1, 1, 1], [1, 0, 1], [1, 1, 1]])

    neighbors = convolve2d(board, kernel, mode="same", boundary="wrap")
    return (
        ((board == 1) & ((neighbors == 2) | (neighbors == 3)))
        | ((board == 0) & (neighbors == 3))
    ).astype(int)


def main():
    height = 64
    width = 64
    options = RGBMatrixOptions()
    options.rows = height
    options.cols = width
    options.chain_length = 1
    options.hardware_mapping = "adafruit-hat"
    options.brightness = 50
    options.gpio_slowdown = 2

    # Must be initialized BEFORE the matrix
    button_led_red = LED(15)
    button_led_red.on()
    button_green = Button(14)

    board = np.array([[]])

    def reset_board():
        nonlocal board
        board = np.random.randint(0, 2, (height, width), dtype=np.uint8)

    reset_board()
    button_green.when_pressed = reset_board

    matrix = RGBMatrix(options=options)
    canvas = matrix.CreateFrameCanvas()

    palette = np.array([[0, 0, 0], [255, 255, 255]], dtype=np.uint8)

    try:
        while True:
            rgb = palette[board.astype(np.uint8)]
            img = Image.fromarray(rgb, mode="RGB")
            canvas.SetImage(img)
            canvas = matrix.SwapOnVSync(canvas)
            sleep(1)
            board = get_next_board(board)
    finally:
        button_led_red.off()


if __name__ == "__main__":
    main()
