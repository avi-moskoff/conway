import logging

from runner import GameRunner


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    GameRunner().run()


if __name__ == "__main__":
    main()
