import logging
import os

from runner import GameRunner


def main() -> None:
    log_level_name = os.getenv("CONWAY_LOG_LEVEL", "INFO").upper()
    log_level = getattr(logging, log_level_name, logging.INFO)
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    GameRunner().run()


if __name__ == "__main__":
    main()
