"""Diagnostic: which display pixels does the dust filter light up, and why?

Run on the Pi (it needs network access to NOAA and your CONWAY_* env):

    set -a; . /etc/conway.env; set +a
    .venv/bin/python tools/dust_diag.py

Fetches the latest real GOES dust frame, runs the game's own sampling and
filter, and prints each magenta display pixel with the raw source color
and HSV that passed the threshold. Not part of the running program.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from config import WeatherRadarConfig
from games.weather_radar import WeatherRadarGame
from weather.goes_dust import (
    DUST_HUE_MAX_DEGREES,
    DUST_HUE_MIN_DEGREES,
    DUST_MATCH_RGB,
    DUST_SATURATION_MIN,
    DUST_VALUE_MIN,
    GoesDustClient,
    _rgb_to_hsv,
)


def main() -> None:
    config = WeatherRadarConfig.from_environment()
    if config is None:
        sys.exit("CONWAY_HOME_LATITUDE / CONWAY_HOME_LONGITUDE not set")
    game = WeatherRadarGame(64, 64, config)
    result = GoesDustClient(satellite=config.dust_satellite).latest_frame()
    if result is None:
        sys.exit("no dust frame available")
    sector, frame_time = result
    game._store_dust(sector, frame_time)
    print(f"frame {frame_time:%Y-%m-%d %H:%MZ}, "
          f"band hue {DUST_HUE_MIN_DEGREES:.0f}-{DUST_HUE_MAX_DEGREES:.0f}, "
          f"sat>={DUST_SATURATION_MIN}, val>={DUST_VALUE_MIN}")

    radar = game._dust_field[: game._radar_height]
    ys, xs = np.nonzero(np.all(radar == DUST_MATCH_RGB, axis=-1))
    print(f"{len(xs)} magenta display pixels")
    size = sector.shape[0]
    sx = np.clip(np.rint(game._dust_sector_x).astype(int), 0, size - 1)
    sy = np.clip(np.rint(game._dust_sector_y).astype(int), 0, size - 1)
    for x, y in zip(xs, ys):
        rgb = sector[sy[y, x], sx[y, x]]
        hue, sat, val = _rgb_to_hsv(rgb[None, :])
        print(f"  display ({x:2d},{y:2d}) <- sector ({sx[y, x]},{sy[y, x]}) "
              f"rgb {tuple(int(c) for c in rgb)} "
              f"hue {hue[0]:.0f} sat {sat[0]:.2f} val {val[0]:.2f}")
    print("home:", (game.width // 2, game._radar_height // 2),
          "landmarks:", game._dust_landmark_pixels)


if __name__ == "__main__":
    main()
