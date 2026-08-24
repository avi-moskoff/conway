import unittest

import numpy as np

from config import WeatherRadarConfig
from games.weather_radar import WeatherRadarGame
from weather.models import AirQualitySample, WeatherSample


class FakeOpenMeteoClient:
    def __init__(self) -> None:
        self.weather_samples: tuple[WeatherSample, ...] = ()
        self.aqi_samples: tuple[AirQualitySample, ...] = ()
        self.weather_error: Exception | None = None
        self.aqi_error: Exception | None = None

    def weather_for(self, points):
        if self.weather_error is not None:
            raise self.weather_error
        if self.weather_samples:
            return self.weather_samples
        return tuple(
            WeatherSample(
                latitude=lat,
                longitude=lon,
                temperature_f=80.0,
                precipitation_mm=0.0,
                weather_code=0,
            )
            for lat, lon in points
        )

    def air_quality_for(self, points):
        if self.aqi_error is not None:
            raise self.aqi_error
        if self.aqi_samples:
            return self.aqi_samples
        return tuple(
            AirQualitySample(latitude=lat, longitude=lon, us_aqi=25.0)
            for lat, lon in points
        )


class WeatherRadarGameTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = FakeOpenMeteoClient()
        self.config = WeatherRadarConfig(
            33.0,
            -112.0,
            radius_nm=15.0,
            poll_seconds=0.05,
            landmarks=(("Test Peak", 33.08, -111.92),),
        )
        self.game = WeatherRadarGame(64, 64, self.config, client=self.client)

    def tearDown(self) -> None:
        self.game.close()

    def _seed(self) -> None:
        weather_samples = self.client.weather_for(self.game._query_points)
        self.game._store_conditions(weather_samples)
        aqi_samples = self.client.air_quality_for(self.game._query_points)
        self.game._store_aqi(aqi_samples)

    def test_frame_shape_and_dtype(self) -> None:
        self._seed()
        frame = self.game.frame
        self.assertEqual(frame.shape, (64, 64, 3))
        self.assertEqual(frame.dtype, np.uint8)

    def test_home_marker_and_landmark_render(self) -> None:
        self._seed()
        frame = self.game.frame
        self.assertTrue(np.any(np.all(frame == self.game.home_color, axis=2)))
        self.assertTrue(np.any(np.all(frame == self.game.landmark_color, axis=2)))

    def test_reset_cycles_conditions_and_aqi_and_wraps(self) -> None:
        self.assertEqual(
            self.game.display_modes[self.game._display_mode_index], "conditions"
        )
        self.game.reset()
        self.assertEqual(self.game.display_modes[self.game._display_mode_index], "aqi")
        self.game.reset()
        self.assertEqual(
            self.game.display_modes[self.game._display_mode_index], "conditions"
        )

    def test_no_data_shows_no_signal(self) -> None:
        self.game.frame
        self.assertEqual(self.game._last_label, "NO SIGNAL")

    def test_stale_data_shows_no_signal(self) -> None:
        self._seed()
        with self.game._data_lock:
            self.game._conditions_snapshot_time -= self.game.stale_snapshot_seconds + 1

        self.game.frame

        self.assertEqual(self.game._last_label, "NO SIGNAL")

    def test_conditions_ticker_shows_seeded_label(self) -> None:
        self._seed()
        self.game.frame
        self.assertEqual(self.game._last_label, "80F CLEAR")

    def test_aqi_ticker_shows_seeded_label(self) -> None:
        self._seed()
        self.game.reset()  # -> aqi
        self.game.frame
        self.assertEqual(self.game._last_label, "AQI 25 GOOD")

    def test_aqi_category_at_breakpoints(self) -> None:
        self.assertEqual(self.game._aqi_category(50), "GOOD")
        self.assertEqual(self.game._aqi_category(51), "MODERATE")
        self.assertEqual(self.game._aqi_category(100), "MODERATE")
        self.assertEqual(self.game._aqi_category(101), "USG")
        self.assertEqual(self.game._aqi_category(151), "UNHEALTHY")
        self.assertEqual(self.game._aqi_category(201), "V UNHEALTHY")
        self.assertEqual(self.game._aqi_category(301), "HAZARDOUS")

    def test_conditions_label_maps_weather_codes(self) -> None:
        clear = WeatherSample(33.0, -112.0, 75.0, 0.0, weather_code=0)
        rain = WeatherSample(33.0, -112.0, 60.0, 2.0, weather_code=63)
        storm = WeatherSample(33.0, -112.0, 68.0, 5.0, weather_code=95)
        self.assertEqual(self.game._conditions_label(clear), "75F CLEAR")
        self.assertEqual(self.game._conditions_label(rain), "60F RAIN")
        self.assertEqual(self.game._conditions_label(storm), "68F STORM")

    def test_colorize_field_matches_aqi_breakpoint_colors(self) -> None:
        field = np.array([0.0, 100.0, 500.0])
        colors = self.game._colorize_field(
            field, self.game.aqi_stops_t, self.game.aqi_stops_rgb
        )
        self.assertEqual(tuple(int(v) for v in colors[0]), (0, 228, 0))
        self.assertEqual(tuple(int(v) for v in colors[1]), (255, 126, 0))
        self.assertEqual(tuple(int(v) for v in colors[2]), (126, 0, 35))

    def test_colorize_field_matches_precipitation_ramp_colors(self) -> None:
        field = np.array([0.0, self.game.precipitation_cap_mm])
        colors = self.game._colorize_field(
            field, self.game.precipitation_stops_t, self.game.precipitation_stops_rgb
        )
        self.assertEqual(tuple(int(v) for v in colors[0]), (0, 0, 0))
        self.assertEqual(tuple(int(v) for v in colors[1]), (255, 255, 255))


if __name__ == "__main__":
    unittest.main()
