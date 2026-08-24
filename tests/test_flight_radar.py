from threading import Event, Lock
from time import monotonic, sleep, time
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image, ImageDraw

from air_traffic import AdsbLolError
from air_traffic.models import Aircraft, FlightRoute
from air_traffic.projection import offset_to_latlon, project_position
from config import FlightRadarConfig
from games.flight_radar import FlightRadarGame
from transit.models import StopArrival, Train


class FakeClient:
    def __init__(self) -> None:
        self.calls = 0
        self.called = Event()
        self._lock = Lock()
        self.routes = {}
        self.route_calls = 0
        self.route_error = None

    def nearby_aircraft(self, _latitude, _longitude, _radius):
        with self._lock:
            self.calls += 1
        self.called.set()
        return (
            Aircraft(
                icao_hex="abc123",
                callsign="TEST1",
                latitude=33.0,
                longitude=-112.0,
            ),
            Aircraft(
                icao_hex="def456",
                callsign="TEST2",
                latitude=33.0,
                longitude=-111.95,
            ),
        )

    def routes_for(self, _aircraft):
        self.route_calls += 1
        if self.route_error is not None:
            raise self.route_error
        return self.routes


class FakeRailClient:
    def __init__(self) -> None:
        self.calls = 0
        self.called = Event()
        self._lock = Lock()

    def active_trains(self, _route_ids):
        with self._lock:
            self.calls += 1
        self.called.set()
        return ()

    def arrivals_for_stops(self, _stop_ids):
        return ()


class FlightRadarGameTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = FakeClient()
        self.rail_client = FakeRailClient()
        self.game = FlightRadarGame(
            64,
            64,
            FlightRadarConfig(
                33.0,
                -112.0,
                poll_seconds=0.05,
                rail_poll_seconds=0.05,
                airport_latitude=33.05,
                airport_longitude=-112.0,
            ),
            client=self.client,
            rail_client=self.rail_client,
        )

    def tearDown(self) -> None:
        self.game.close()

    def test_renders_aircraft_and_home_marker(self) -> None:
        with self.game._data_lock:
            self.game._aircraft = self.client.nearby_aircraft(0, 0, 0)
            self.game._snapshot_time = monotonic()

        frame = self.game.frame

        self.assertEqual(frame.shape, (64, 64, 3))
        self.assertEqual(frame.dtype, np.uint8)
        self.assertTrue(
            np.any(np.all(frame == self.game.featured_aircraft_color, axis=2))
        )
        self.assertTrue(
            np.any(np.all(frame == self.game.other_aircraft_color, axis=2))
        )
        self.assertTrue(np.any(np.all(frame == self.game.airport_color, axis=2)))
        self.assertFalse(np.any(np.all(frame == (0, 192, 255), axis=2)))

    def test_diagonal_aircraft_excluded_by_the_old_circle_is_now_visible(self) -> None:
        # radius_nm defaults to 8; 7nm east and 7nm north is outside a
        # circle of that radius (7**2 + 7**2 > 8**2) but inside the box
        # both axes now clip to.
        latitude, longitude = offset_to_latlon(7.0, 7.0, 33.0, -112.0)
        with self.game._data_lock:
            self.game._aircraft = (
                Aircraft(
                    icao_hex="corner",
                    callsign="CORNER",
                    latitude=latitude,
                    longitude=longitude,
                ),
            )
            self.game._snapshot_time = monotonic()

        frame = self.game.frame

        self.assertTrue(
            np.any(np.all(frame == self.game.featured_aircraft_color, axis=2))
        )

    def test_long_axis_shows_aircraft_beyond_the_old_uniform_radius(self) -> None:
        # width=64 > radar_height=51, so east/west is the long axis: 9nm
        # due east is past radius_nm=8 (excluded under the old scaling,
        # which capped every axis at radius_nm) but within reach now that
        # the long axis extends proportionally farther at the same
        # angle-preserving pixels-per-nm scale as the short axis.
        latitude, longitude = offset_to_latlon(9.0, 0.0, 33.0, -112.0)
        with self.game._data_lock:
            self.game._aircraft = (
                Aircraft(
                    icao_hex="far-east",
                    callsign="FAREAST",
                    latitude=latitude,
                    longitude=longitude,
                ),
            )
            self.game._snapshot_time = monotonic()

        frame = self.game.frame

        self.assertTrue(
            np.any(np.all(frame == self.game.featured_aircraft_color, axis=2))
        )

    def test_train_near_corner_excluded_by_the_old_circle_is_now_visible(self) -> None:
        latitude, longitude = offset_to_latlon(7.0, 7.0, 33.0, -112.0)
        synthetic_line = {"A": ((33.0, -112.0), (latitude, longitude))}
        with patch("games.flight_radar.LINE_GEOMETRY", synthetic_line):
            self.game.reset()  # -> westbound_eta; rail only draws off aircraft mode
            with self.game._data_lock:
                self.game._trains = (Train("1", "A", 0, latitude, longitude),)
                self.game._train_snapshot_time = monotonic()

            frame = self.game.frame

        self.assertTrue(
            np.any(np.all(frame == self.game.eastbound_train_color, axis=2))
        )

    def test_aircraft_mode_hides_rail_and_trains(self) -> None:
        synthetic_line = {"A": ((33.0, -112.0), (33.0, -111.95))}
        with patch("games.flight_radar.LINE_GEOMETRY", synthetic_line):
            with self.game._data_lock:
                self.game._aircraft = self.client.nearby_aircraft(0, 0, 0)
                self.game._snapshot_time = monotonic()
                self.game._trains = (Train("1", "A", 0, 33.0, -111.98),)
                self.game._train_snapshot_time = monotonic()

            frame = self.game.frame

        self.assertFalse(np.any(np.all(frame == self.game.rail_line_color, axis=2)))
        self.assertFalse(
            np.any(np.all(frame == self.game.eastbound_train_color, axis=2))
        )

    def test_error_flag_only_reflects_the_active_modes_feed(self) -> None:
        # An ADS-B error shows in aircraft mode...
        with self.game._data_lock:
            self.game._has_error = True
            self.game._snapshot_time = monotonic()

        self.assertEqual(tuple(self.game.frame[0, 0]), self.game.error_color)

        # ...but not in a train mode, where it's irrelevant.
        self.game.reset()  # -> westbound_eta
        with self.game._data_lock:
            self.game._train_snapshot_time = monotonic()

        self.assertEqual(tuple(self.game.frame[0, 0]), (0, 0, 0))

        # And a rail error shows in that train mode...
        with self.game._data_lock:
            self.game._has_rail_error = True

        self.assertEqual(tuple(self.game.frame[0, 0]), self.game.error_color)

        # ...but not back in aircraft mode (whose own error was never set
        # here - it's still True from the first assertion above, so clear
        # it to isolate what this check is actually about: a rail error
        # shouldn't leak into aircraft mode's flag).
        with self.game._data_lock:
            self.game._has_error = False
        self.game.reset()
        self.game.reset()  # -> aircraft
        self.assertEqual(tuple(self.game.frame[0, 0]), (0, 0, 0))

    def test_train_mode_hides_aircraft_and_airport(self) -> None:
        # airport_color == home_color, so checking the frame for that color
        # can't tell the two apart; check the airport's own pixel instead.
        radar_height = self.game.height - self.game.ticker_height - 1
        airport_pixel = project_position(
            33.05, -112.0, 33.0, -112.0, self.game._config.radius_nm,
            self.game.width, radar_height,
        )

        self.game.reset()  # -> westbound_eta
        with self.game._data_lock:
            self.game._aircraft = self.client.nearby_aircraft(0, 0, 0)
            self.game._snapshot_time = monotonic()

        frame = self.game.frame
        radar = frame[: -self.game.ticker_height]

        # other_aircraft_color == ticker_text_color (both white), so check
        # only the radar area - the ticker legitimately renders white text.
        self.assertFalse(
            np.any(np.all(radar == self.game.other_aircraft_color, axis=2))
        )
        self.assertIsNotNone(airport_pixel)
        x, y = airport_pixel
        self.assertEqual(tuple(frame[y, x]), (0, 0, 0))

    def test_ticker_identifies_closest_aircraft_and_includes_route(self) -> None:
        with self.game._data_lock:
            self.game._aircraft = self.client.nearby_aircraft(0, 0, 0)
            self.game._routes = {
                "TEST1": (
                    FlightRoute("TEST1", "PHX", "SEA", plausible=True),
                    monotonic() + 60,
                )
            }
            self.game._snapshot_time = monotonic()

        self.game.frame

        self.assertEqual(self.game._last_label, "TEST1 PHX>SEA")

    def test_ticker_is_static(self) -> None:
        with self.game._data_lock:
            self.game._aircraft = self.client.nearby_aircraft(0, 0, 0)
            self.game._snapshot_time = monotonic()
        first_ticker = self.game.frame[-self.game.ticker_height :].copy()

        for _ in range(20):
            self.game.advance()

        second_ticker = self.game.frame[-self.game.ticker_height :]
        np.testing.assert_array_equal(first_ticker, second_ticker)

    def test_ticker_uses_only_hard_edged_colors(self) -> None:
        with self.game._data_lock:
            self.game._aircraft = self.client.nearby_aircraft(0, 0, 0)
            self.game._snapshot_time = monotonic()

        ticker = self.game.frame[-self.game.ticker_height :]
        colors = {tuple(color) for color in ticker.reshape(-1, 3)}

        self.assertEqual(colors, {(0, 0, 0), self.game.ticker_text_color})

    def test_ticker_colors_direction_letter_and_keeps_rest_white(self) -> None:
        frame = np.zeros((self.game.height, self.game.width, 3), dtype=np.uint8)
        self.game._draw_ticker(frame, "W ETA 8M", self.game.westbound_train_color)

        ticker = frame[-self.game.ticker_height :]
        colors = {tuple(color) for color in ticker.reshape(-1, 3)}
        self.assertEqual(
            colors,
            {(0, 0, 0), self.game.westbound_train_color, self.game.ticker_text_color},
        )
        letter_cols = np.argwhere(
            np.all(ticker == self.game.westbound_train_color, axis=2)
        )[:, 1]
        rest_cols = np.argwhere(
            np.all(ticker == self.game.ticker_text_color, axis=2)
        )[:, 1]
        self.assertLess(letter_cols.max(), rest_cols.min())

    def test_ticker_without_letter_color_stays_all_white(self) -> None:
        frame = np.zeros((self.game.height, self.game.width, 3), dtype=np.uint8)
        self.game._draw_ticker(frame, "CLEAR SKY")

        ticker = frame[-self.game.ticker_height :]
        colors = {tuple(color) for color in ticker.reshape(-1, 3)}
        self.assertEqual(colors, {(0, 0, 0), self.game.ticker_text_color})

    def test_long_ticker_scrolls(self) -> None:
        with self.game._data_lock:
            self.game._aircraft = self.client.nearby_aircraft(0, 0, 0)
            self.game._routes = {
                "TEST1": (
                    FlightRoute("TEST1", "PHX", "SEA", plausible=True),
                    monotonic() + 60,
                )
            }
            self.game._snapshot_time = monotonic()
        first_ticker = self.game.frame[-self.game.ticker_height :].copy()

        for _ in range(5):
            self.game.advance()

        second_ticker = self.game.frame[-self.game.ticker_height :]
        self.assertFalse(np.array_equal(first_ticker, second_ticker))

    def test_route_enrichment_keeps_only_plausible_routes(self) -> None:
        self.client.routes = {
            "TEST1": FlightRoute("TEST1", "PHX", "SEA", plausible=False)
        }

        self.game._update_routes(self.client.nearby_aircraft(0, 0, 0))

        cached_route, _expires = self.game._routes["TEST1"]
        self.assertIsNone(cached_route)

    def test_route_failure_has_a_cooldown(self) -> None:
        self.client.route_error = AdsbLolError("HTTP 500")
        aircraft = self.client.nearby_aircraft(0, 0, 0)

        self.game._update_routes(aircraft)
        self.game._update_routes(aircraft)

        self.assertEqual(self.client.route_calls, 1)

    def test_exponential_backoff_grows_with_consecutive_failures(self) -> None:
        # Jittered +/-20%, so compare non-overlapping ranges to be robust.
        first = self.game._exponential_backoff_seconds(1, 15.0)
        third = self.game._exponential_backoff_seconds(3, 15.0)

        self.assertLess(first, 15.0 * 2 * 1.2)
        self.assertGreater(third, 15.0 * 4)

    def test_exponential_backoff_caps_at_five_minutes(self) -> None:
        wait_seconds = self.game._exponential_backoff_seconds(20, 15.0)

        self.assertLessEqual(wait_seconds, 5 * 60.0 * 1.2)

    def test_rate_limited_wait_escalates_instead_of_trusting_a_short_retry_after(
        self,
    ) -> None:
        # A short Retry-After (as adsb.lol was observed sending repeatedly)
        # shouldn't be trusted literally on a second consecutive failure -
        # that's what produced a burst of retries a couple seconds apart.
        # Use a realistic poll_seconds; self.game's is shrunk for fast tests.
        game = FlightRadarGame(
            64, 64, FlightRadarConfig(33.0, -112.0, poll_seconds=15.0)
        )
        try:
            first_failure = game._rate_limited_wait_seconds(1, 2.0)
            third_failure = game._rate_limited_wait_seconds(3, 2.0)
        finally:
            game.close()

        self.assertGreater(first_failure, 2.0)
        self.assertGreater(third_failure, first_failure)

    def test_rate_limited_wait_still_honors_a_long_retry_after(self) -> None:
        wait_seconds = self.game._rate_limited_wait_seconds(1, 500.0)

        self.assertGreaterEqual(wait_seconds, 500.0)

    def test_polling_pauses_and_restarts_with_lifecycle(self) -> None:
        self.game.activate()
        self.assertTrue(self.client.called.wait(1))
        self.game.deactivate()
        sleep(0.1)
        calls_while_paused = self.client.calls
        sleep(0.15)
        self.assertEqual(self.client.calls, calls_while_paused)

        self.client.called.clear()
        self.game.activate()
        self.assertTrue(self.client.called.wait(1))
        self.assertGreater(self.client.calls, calls_while_paused)

    def test_renders_rail_line_and_trains(self) -> None:
        synthetic_line = {"A": ((33.0, -112.0), (33.0, -111.95))}
        with patch("games.flight_radar.LINE_GEOMETRY", synthetic_line):
            self.game.reset()  # -> westbound_eta; rail only draws off aircraft mode
            with self.game._data_lock:
                self.game._trains = (
                    Train("1", "A", 0, 33.0, -111.98),
                    Train("2", "A", 1, 33.02, -112.0),
                )
                self.game._train_snapshot_time = monotonic()

            frame = self.game.frame

        self.assertTrue(
            np.any(np.all(frame == self.game.rail_line_color, axis=2))
        )
        self.assertTrue(
            np.any(np.all(frame == self.game.eastbound_train_color, axis=2))
        )
        self.assertTrue(
            np.any(np.all(frame == self.game.westbound_train_color, axis=2))
        )

    def test_train_position_snaps_onto_its_line(self) -> None:
        synthetic_line = {"A": ((33.0, -112.0), (33.0, -111.9))}
        with patch("games.flight_radar.LINE_GEOMETRY", synthetic_line):
            self.game.reset()  # -> westbound_eta; rail only draws off aircraft mode
            with self.game._data_lock:
                # 1.2nm north of the (perfectly flat) line.
                self.game._trains = (Train("1", "A", 0, 33.02, -111.95),)
                self.game._train_snapshot_time = monotonic()

            frame = self.game.frame

        train_rows = np.argwhere(
            np.all(frame == self.game.eastbound_train_color, axis=2)
        )
        self.assertEqual(len(train_rows), 1)
        home_row = self.game.height - self.game.ticker_height - 1
        home_row //= 2
        self.assertEqual(train_rows[0][0], home_row)

    def test_draw_trains_extrapolates_by_fix_age_not_just_poll_elapsed(self) -> None:
        synthetic_line = {"A": ((33.0, -112.0), (33.0, -111.9))}
        with patch("games.flight_radar.LINE_GEOMETRY", synthetic_line):
            self.game.reset()  # -> westbound_eta; rail only draws off aircraft mode
            with self.game._data_lock:
                # Fix was already 5s old when we polled it; snapshot_time is
                # "now" so elapsed-since-poll is ~0. If extrapolation only
                # used elapsed-since-poll this train would appear frozen.
                self.game._trains = (
                    Train("1", "A", 0, 33.0, -112.0, seen_seconds=20.0),
                )
                self.game._train_velocities = {"1": (0.02, 0.0)}
                self.game._train_snapshot_time = monotonic()

            frame = self.game.frame

        train_pixels = np.argwhere(
            np.all(frame == self.game.eastbound_train_color, axis=2)
        )
        self.assertEqual(len(train_pixels), 1)
        home_col = self.game.width // 2
        self.assertGreater(train_pixels[0][1], home_col)

    def test_estimate_velocities_derives_speed_from_consecutive_fixes(self) -> None:
        old_poll_time = monotonic() - 10
        with self.game._data_lock:
            self.game._trains = (Train("1", "A", 0, 33.0, -112.0, seen_seconds=5.0),)
            self.game._train_snapshot_time = old_poll_time

        new_train = Train("1", "A", 0, 33.0, -111.99769, seen_seconds=2.0)
        velocities = self.game._estimate_velocities((new_train,), old_poll_time + 20)

        east_speed, north_speed = velocities["1"]
        self.assertAlmostEqual(north_speed, 0.0, places=4)
        self.assertGreater(east_speed, 0)
        self.assertLess(east_speed, self.game.max_train_speed_nm_per_second)

    def test_estimate_velocities_rejects_implausible_speed(self) -> None:
        old_poll_time = monotonic() - 10
        with self.game._data_lock:
            self.game._trains = (Train("1", "A", 0, 33.0, -112.0, seen_seconds=1.0),)
            self.game._train_snapshot_time = old_poll_time

        new_train = Train("1", "A", 0, 33.0, -111.9, seen_seconds=1.0)
        velocities = self.game._estimate_velocities((new_train,), old_poll_time + 11)

        self.assertNotIn("1", velocities)

    def test_estimate_velocities_ignores_trains_without_a_prior_poll(self) -> None:
        velocities = self.game._estimate_velocities(
            (Train("9", "A", 0, 33.0, -112.0),), monotonic()
        )

        self.assertEqual(velocities, {})

    def test_estimate_velocities_preserves_velocity_when_fix_is_unchanged(self) -> None:
        # The underlying feed often repeats the exact same fix across a poll
        # or two; a repeated fix shouldn't erase a previously good estimate.
        with self.game._data_lock:
            self.game._trains = (Train("1", "A", 0, 33.0, -112.0, seen_seconds=1.0),)
            self.game._train_snapshot_time = monotonic() - 30
            self.game._train_velocities = {"1": (0.004, 0.0)}

        # Same position, age simply grew by the elapsed time: no new fix.
        repeated = Train("1", "A", 0, 33.0, -112.0, seen_seconds=31.0)
        velocities = self.game._estimate_velocities((repeated,), monotonic())

        self.assertEqual(velocities["1"], (0.004, 0.0))

    def test_estimate_velocities_prunes_vehicles_no_longer_present(self) -> None:
        with self.game._data_lock:
            self.game._train_velocities = {"gone": (0.004, 0.0)}
            self.game._train_snapshot_time = monotonic()

        velocities = self.game._estimate_velocities((), monotonic())

        self.assertEqual(velocities, {})

    def test_stale_train_snapshot_hides_trains(self) -> None:
        self.game.reset()  # -> westbound_eta; rail only draws off aircraft mode
        with self.game._data_lock:
            self.game._trains = (Train("1", "A", 0, 33.0, -111.98),)
            self.game._train_snapshot_time = (
                monotonic() - self.game.stale_snapshot_seconds - 5
            )

        frame = self.game.frame

        self.assertFalse(
            np.any(np.all(frame == self.game.eastbound_train_color, axis=2))
        )

    def test_reset_cycles_display_mode_and_wraps(self) -> None:
        self.assertEqual(self.game.display_modes[self.game._display_mode_index], "aircraft")

        self.game.reset()
        self.assertEqual(
            self.game.display_modes[self.game._display_mode_index], "westbound_eta"
        )

        self.game.reset()
        self.assertEqual(
            self.game.display_modes[self.game._display_mode_index], "eastbound_eta"
        )

        self.game.reset()
        self.assertEqual(self.game.display_modes[self.game._display_mode_index], "aircraft")

    def test_next_arrival_picks_soonest_upcoming(self) -> None:
        stop_id = self.game._westbound_home_stop_id
        now = time()
        arrivals = (
            StopArrival("later", "A", 1, stop_id, now + 600),
            StopArrival("sooner", "A", 1, stop_id, now + 120),
            StopArrival("already-left", "A", 1, stop_id, now - 30),
        )

        selection = self.game._next_arrival(arrivals, "west")

        self.assertIsNotNone(selection)
        self.assertEqual(selection.trip_id, "sooner")

    def test_next_arrival_ignores_other_stops(self) -> None:
        now = time()
        arrivals = (StopArrival("wrong-stop", "A", 1, "not-home", now + 60),)

        selection = self.game._next_arrival(arrivals, "west")

        self.assertIsNone(selection)

    def test_train_eta_label_formatting(self) -> None:
        now = time()

        self.assertEqual(self.game._train_eta_label(None, "W"), "W ETA --")
        self.assertEqual(
            self.game._train_eta_label(StopArrival("1", "A", 1, "9036", now + 30), "W"),
            "W ETA <1M",
        )
        self.assertEqual(
            self.game._train_eta_label(StopArrival("1", "A", 1, "9036", now + 185), "W"),
            "W ETA 3M",
        )

    def test_train_eta_label_fits_without_scrolling(self) -> None:
        canvas = Image.new("1", (self.game.width, self.game.ticker_height), 0)
        draw = ImageDraw.Draw(canvas)
        now = time()

        for label in (
            self.game._train_eta_label(None, "W"),
            self.game._train_eta_label(StopArrival("1", "A", 1, "9036", now + 30), "W"),
            self.game._train_eta_label(StopArrival("1", "A", 1, "9036", now + 18 * 60), "W"),
            self.game._train_eta_label(StopArrival("1", "A", 0, "9008", now + 18 * 60), "E"),
        ):
            width = draw.textlength(label, font=self.game._font)
            self.assertLessEqual(width, self.game.width, label)

    def test_frame_highlights_selected_train_and_shows_eta_ticker(self) -> None:
        self.game.reset()  # -> westbound_eta
        stop_id = self.game._westbound_home_stop_id
        with self.game._data_lock:
            self.game._trains = (
                Train("W1", "A", 1, 33.0, -111.95, seen_seconds=0.0, trip_id="trip-1"),
            )
            self.game._train_snapshot_time = monotonic()
            self.game._arrivals = (
                StopArrival("trip-1", "A", 1, stop_id, time() + 300),
            )

        frame = self.game.frame
        radar = frame[: -self.game.ticker_height]

        self.assertTrue(
            np.any(np.all(frame == self.game.featured_aircraft_color, axis=2))
        )
        self.assertFalse(
            np.any(np.all(radar == self.game.westbound_train_color, axis=2))
        )
        self.assertIn("ETA", self.game._last_label)

    def test_frame_shows_eta_ticker_even_without_a_matched_vehicle(self) -> None:
        self.game.reset()  # -> westbound_eta
        stop_id = self.game._westbound_home_stop_id
        with self.game._data_lock:
            self.game._train_snapshot_time = monotonic()
            self.game._arrivals = (
                StopArrival("unseen-trip", "A", 1, stop_id, time() + 300),
            )

        self.game.frame

        self.assertEqual(self.game._last_label, "W ETA 5M")

    def test_rail_polling_pauses_and_restarts_with_lifecycle(self) -> None:
        self.game.activate()
        self.assertTrue(self.rail_client.called.wait(1))
        self.game.deactivate()
        sleep(0.1)
        calls_while_paused = self.rail_client.calls
        sleep(0.15)
        self.assertEqual(self.rail_client.calls, calls_while_paused)


if __name__ == "__main__":
    unittest.main()
