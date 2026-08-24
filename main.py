import logging
import os

from config import WeatherRadarConfig
from runner import GameRunner
from weather.goes_dust import warm_up_decode_executor


def main() -> None:
    log_level_name = os.getenv("CONWAY_LOG_LEVEL", "INFO").upper()
    log_level = getattr(logging, log_level_name, logging.INFO)
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    # Must happen before GameRunner() - which constructs the RGBMatrix
    # hardware connection - see warm_up_decode_executor's docstring.
    if WeatherRadarConfig.from_environment() is not None:
        warm_up_decode_executor()
    GameRunner().run()


if __name__ == "__main__":
    main()
