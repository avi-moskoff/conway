import argparse
import numpy as np
import random


def get_next_board(board: np.ndarray) -> np.ndarray:
    return board


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--height", type=int, default=64, help="The height of the board"
    )
    parser.add_argument("-width", type=int, default=64, help="The width of the board")
    parser.add_argument(
        "--debug",
        type=bool,
        default=False,
        help="If true, will output to console. If false, will output to RGB matrix",
    )

    args = parser.parse_args()
    height = args.height
    width = args.width

    board = np.array(
        [[random.randint(0, 1) for _ in range(width)] for _ in range(height)]
    )

    if args.debug:
        print("Hello, world!")


if __name__ == "__main__":
    main()
