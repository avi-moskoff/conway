import unittest
from datetime import datetime, timezone

import numpy as np

from config import WeatherRadarConfig
from games.weather_radar import WeatherRadarGame, _classify_weather_error
from weather import (
    GoesDustApiError,
    GoesDustConnectionError,
    GoesDustRateLimitedError,
    OpenMeteoApiError,
    OpenMeteoConnectionError,
    OpenMeteoRateLimitedError,
)
from weather.models import AirQualitySample, WeatherSample


class FakeGoesDustClient:
    def __init__(self) -> None:
        self.error: Exception | None = None
        self.frame_time = datetime(2026, 8, 24, 3, 46, tzinfo=timezone.utc)
        self.sector_array = np.full((1200, 1200, 3), (120, 60, 10), dtype=np.uint8)

    def latest_frame(self):
        if self.error is not None:
            raise self.error
        return self.sector_array, self.frame_time


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
                cloud_cover_percent=0.0,
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
        self.dust_client = FakeGoesDustClient()
        self.config = WeatherRadarConfig(
            33.0,
            -112.0,
            radius_nm=15.0,
            poll_seconds=0.05,
            dust_radius_nm=40.0,
            dust_poll_seconds=0.05,
            landmarks=(("Test Peak", 33.08, -111.92),),
        )
        self.game = WeatherRadarGame(
            64, 64, self.config, client=self.client, dust_client=self.dust_client
        )

    def tearDown(self) -> None:
        self.game.close()

    def _seed(self) -> None:
        weather_samples = self.client.weather_for(self.game._query_points)
        self.game._store_conditions(weather_samples)
        aqi_samples = self.client.air_quality_for(self.game._query_points)
        self.game._store_aqi(aqi_samples)
        sector_array, frame_time = self.dust_client.latest_frame()
        self.game._store_dust(sector_array, frame_time)

    def test_frame_shape_and_dtype(self) -> None:
        self._seed()
        frame = self.game.frame
        self.assertEqual(frame.shape, (64, 64, 3))
        self.assertEqual(frame.dtype, np.uint8)

    def test_home_marker_and_landmark_render(self) -> None:
        self._seed()
        frame = self.game.frame
        underlying_field = self.game._conditions_field
        center_x, center_y = self.game.width // 2, self.game._radar_height // 2
        home_pixel = 255 - underlying_field[center_y, center_x]
        np.testing.assert_array_equal(frame[center_y, center_x], home_pixel)
        landmark_x, landmark_y = self.game._landmark_pixels[0]
        landmark_pixel = 255 - underlying_field[landmark_y, landmark_x]
        np.testing.assert_array_equal(frame[landmark_y, landmark_x], landmark_pixel)

    def test_cycle_view_steps_conditions_aqi_dust_and_wraps(self) -> None:
        # Mode switching moved from reset() to cycle_view() - the encoder's
        # job now, not the button's - see games.base.Game.cycle_view.
        self.assertEqual(
            self.game.display_modes[self.game._display_mode_index], "conditions"
        )
        self.game.cycle_view(1)
        self.assertEqual(self.game.display_modes[self.game._display_mode_index], "aqi")
        self.game.cycle_view(1)
        self.assertEqual(self.game.display_modes[self.game._display_mode_index], "dust")
        self.game.cycle_view(1)
        self.assertEqual(
            self.game.display_modes[self.game._display_mode_index], "conditions"
        )

    def test_cycle_view_steps_backward(self) -> None:
        self.game.cycle_view(-1)
        self.assertEqual(self.game.display_modes[self.game._display_mode_index], "dust")
        self.game.cycle_view(-1)
        self.assertEqual(self.game.display_modes[self.game._display_mode_index], "aqi")

    def test_cycle_view_wakes_only_the_poller_for_the_mode_switched_into(self) -> None:
        self.game._wake_event.clear()
        self.game._dust_wake_event.clear()

        self.game.cycle_view(1)  # conditions -> aqi
        self.assertTrue(self.game._wake_event.is_set())
        self.assertFalse(self.game._dust_wake_event.is_set())

        self.game._wake_event.clear()
        self.game.cycle_view(1)  # aqi -> dust
        self.assertFalse(self.game._wake_event.is_set())
        self.assertTrue(self.game._dust_wake_event.is_set())

        self.game._dust_wake_event.clear()
        self.game.cycle_view(1)  # dust -> conditions
        self.assertTrue(self.game._wake_event.is_set())
        self.assertFalse(self.game._dust_wake_event.is_set())

    def test_reset_wakes_the_active_modes_poller_without_changing_the_mode(
        self,
    ) -> None:
        # reset() is a pure force-refresh now - the button's one job
        # everywhere (see games.base.Game / runner.on_button_pressed).
        self.game.cycle_view(1)  # -> aqi
        self.game._wake_event.clear()
        self.game._dust_wake_event.clear()

        self.game.reset()

        self.assertEqual(self.game.display_modes[self.game._display_mode_index], "aqi")
        self.assertTrue(self.game._wake_event.is_set())
        self.assertFalse(self.game._dust_wake_event.is_set())

    def test_reset_resets_the_ticker_scroll(self) -> None:
        self.game._ticker._scroll_offset = 7
        self.game.reset()
        self.assertEqual(self.game._ticker._scroll_offset, 0)

    def test_backoff_starts_short_and_ramps_toward_the_poll_interval(self) -> None:
        base = self.game._config.dust_poll_seconds  # 0.05 in this test's config
        first = self.game._exponential_backoff_seconds(1, base)
        second = self.game._exponential_backoff_seconds(2, base)
        # Should ramp up, but never past the steady-state poll interval.
        self.assertLessEqual(first, base)
        self.assertLessEqual(second, base)
        self.assertLessEqual(first, second)

    def test_backoff_does_not_jump_straight_to_the_ceiling_on_first_failure(self) -> None:
        # Regression guard: with a multi-minute poll interval, the first
        # failure used to immediately hit the 5-minute ceiling, making a
        # one-off transient failure cost a full 5 minutes to recover from.
        first_failure_wait = self.game._exponential_backoff_seconds(1, 300.0)
        self.assertLess(first_failure_wait, 300.0)

    def test_no_data_shows_no_signal(self) -> None:
        self.game.frame
        self.assertEqual(self.game._ticker._last_label, "NO SIGNAL")

    def test_stale_data_shows_no_signal(self) -> None:
        self._seed()
        with self.game._data_lock:
            self.game._conditions_snapshot_time -= self.game.stale_snapshot_seconds + 1

        self.game.frame

        self.assertEqual(self.game._ticker._last_label, "NO SIGNAL")

    def test_conditions_ticker_shows_seeded_label(self) -> None:
        self._seed()
        self.game.frame
        self.assertEqual(self.game._ticker._last_label, "80F CLEAR")

    def test_aqi_ticker_shows_seeded_label(self) -> None:
        self._seed()
        self.game.cycle_view(1)  # -> aqi
        self.game.frame
        self.assertEqual(self.game._ticker._last_label, "AQI 25 GOOD")

    def test_dust_ticker_shows_seeded_label(self) -> None:
        self._seed()
        self.game.cycle_view(1)  # -> aqi
        self.game.cycle_view(1)  # -> dust
        self.game.frame
        self.assertEqual(self.game._ticker._last_label, "DUST 03:46Z")

    def test_dust_mode_renders_home_marker_and_landmark(self) -> None:
        self._seed()
        self.game.cycle_view(1)  # -> aqi
        self.game.cycle_view(1)  # -> dust
        frame = self.game.frame
        underlying_field = self.game._dust_field
        center_x, center_y = self.game.width // 2, self.game._radar_height // 2
        home_pixel = 255 - underlying_field[center_y, center_x]
        np.testing.assert_array_equal(frame[center_y, center_x], home_pixel)
        landmark_x, landmark_y = self.game._dust_landmark_pixels[0]
        landmark_pixel = 255 - underlying_field[landmark_y, landmark_x]
        np.testing.assert_array_equal(frame[landmark_y, landmark_x], landmark_pixel)

    def test_stale_dust_data_shows_no_signal(self) -> None:
        self._seed()
        self.game.cycle_view(1)  # -> aqi
        self.game.cycle_view(1)  # -> dust
        with self.game._data_lock:
            self.game._dust_snapshot_time -= self.game.stale_snapshot_seconds + 1

        self.game.frame

        self.assertEqual(self.game._ticker._last_label, "NO SIGNAL")

    def test_aqi_category_at_breakpoints(self) -> None:
        self.assertEqual(self.game._aqi_category(50), "GOOD")
        self.assertEqual(self.game._aqi_category(51), "MODERATE")
        self.assertEqual(self.game._aqi_category(100), "MODERATE")
        self.assertEqual(self.game._aqi_category(101), "USG")
        self.assertEqual(self.game._aqi_category(151), "UNHEALTHY")
        self.assertEqual(self.game._aqi_category(201), "V UNHEALTHY")
        self.assertEqual(self.game._aqi_category(301), "HAZARDOUS")

    def test_conditions_label_maps_weather_codes(self) -> None:
        clear = WeatherSample(33.0, -112.0, 75.0, 0.0, weather_code=0, cloud_cover_percent=0.0)
        rain = WeatherSample(33.0, -112.0, 60.0, 2.0, weather_code=63, cloud_cover_percent=0.0)
        storm = WeatherSample(33.0, -112.0, 68.0, 5.0, weather_code=95, cloud_cover_percent=0.0)
        self.assertEqual(self.game._conditions_label(clear), "75F CLEAR")
        self.assertEqual(self.game._conditions_label(rain), "60F RAIN")
        self.assertEqual(self.game._conditions_label(storm), "68F STORM")

    def test_colorize_field_matches_aqi_breakpoint_colors(self) -> None:
        # black -> amber -> white ramp (see aqi_stops_rgb); 0/100/500 line
        # up exactly with breakpoints, so the interpolated color should
        # equal that breakpoint's stop color exactly.
        field = np.array([0.0, 100.0, 500.0])
        colors = self.game._colorize_field(
            field, self.game.aqi_stops_t, self.game.aqi_stops_rgb
        )
        self.assertEqual(tuple(int(v) for v in colors[0]), (0, 0, 0))
        self.assertEqual(tuple(int(v) for v in colors[1]), (128, 96, 0))
        self.assertEqual(tuple(int(v) for v in colors[2]), (255, 255, 255))

    def test_conditions_are_black_when_clear_and_dry(self) -> None:
        colors = self.game._compose_conditions(np.array([0.0]), np.array([0.0]))
        self.assertEqual(tuple(int(v) for v in colors[0]), (0, 0, 0))

    def test_overcast_dry_sky_is_gray_with_no_blue_tint(self) -> None:
        colors = self.game._compose_conditions(np.array([100.0]), np.array([0.0]))
        self.assertEqual(
            tuple(int(v) for v in colors[0]), self.game.cloud_white
        )

    def test_heavy_rain_reaches_full_blue_whatever_the_cloud(self) -> None:
        cap = self.game.precipitation_cap_mm
        colors = self.game._compose_conditions(
            np.array([0.0, 100.0]), np.array([cap, cap])
        )
        for color in colors:
            self.assertEqual(
                tuple(int(v) for v in color), self.game.precipitation_blue
            )

    def test_light_rain_is_clearly_blue_not_near_black(self) -> None:
        colors = self.game._compose_conditions(np.array([0.0]), np.array([0.5]))
        self.assertGreaterEqual(int(colors[0][2]), 80)

    def test_rain_pushes_a_cloudy_pixel_from_gray_toward_blue(self) -> None:
        dry, wet = self.game._compose_conditions(
            np.array([100.0, 100.0]), np.array([0.0, 1.0])
        )
        self.assertLess(int(wet[0]), int(dry[0]))  # red drains away
        self.assertGreater(int(wet[2]), int(dry[2]))  # blue rises

    def test_error_shows_specific_reason_while_data_is_still_fresh(self) -> None:
        # A poll failure shouldn't blank out perfectly good cached data - it
        # should keep showing it, but say why the *next* refresh hasn't
        # happened yet (see _live_label and the design doc's Error &
        # degraded-state handling section).
        self._seed()
        with self.game._data_lock:
            self.game._conditions_error_kind = "no_internet"

        self.game.frame

        self.assertEqual(self.game._ticker._last_label, "NO INTERNET")

    def test_api_error_and_throttled_show_their_own_ticker_text(self) -> None:
        self._seed()
        for kind, expected in (("api_error", "API ERROR"), ("throttled", "THROTTLED")):
            with self.subTest(kind=kind):
                with self.game._data_lock:
                    self.game._conditions_error_kind = kind
                self.game.frame
                self.assertEqual(self.game._ticker._last_label, expected)

    def test_staleness_wins_over_a_specific_error_reason(self) -> None:
        # Once data is old enough to be "NO SIGNAL" outright, that's a
        # stronger and simpler signal than the failure category - see
        # _live_label.
        self._seed()
        with self.game._data_lock:
            self.game._conditions_error_kind = "throttled"
            self.game._conditions_snapshot_time -= self.game.stale_snapshot_seconds + 1

        self.game.frame

        self.assertEqual(self.game._ticker._last_label, "NO SIGNAL")

    def test_corner_marker_shows_for_an_error_and_clears_once_stale(self) -> None:
        self._seed()
        with self.game._data_lock:
            self.game._conditions_error_kind = "api_error"
        # Corner is black before the invert - see games.base.mark_error.
        self.assertEqual(tuple(self.game.frame[0, 0]), (255, 255, 255))

        with self.game._data_lock:
            self.game._conditions_snapshot_time -= self.game.stale_snapshot_seconds + 1
        # Once stale, "NO SIGNAL" already says something's wrong, so the
        # corner marker steps aside rather than doubling up.
        self.assertEqual(tuple(self.game.frame[0, 0]), (0, 0, 0))

    def test_classify_weather_error_sorts_each_clients_exceptions(self) -> None:
        cases = (
            (OpenMeteoConnectionError("x"), "no_internet"),
            (GoesDustConnectionError("x"), "no_internet"),
            (OpenMeteoRateLimitedError(30.0), "throttled"),
            (GoesDustRateLimitedError(30.0), "throttled"),
            (OpenMeteoApiError("x"), "api_error"),
            (GoesDustApiError("x"), "api_error"),
            (RuntimeError("no samples returned"), "api_error"),
        )
        for error, expected_kind in cases:
            with self.subTest(error=type(error).__name__):
                self.assertEqual(_classify_weather_error(error), expected_kind)


if __name__ == "__main__":
    unittest.main()
