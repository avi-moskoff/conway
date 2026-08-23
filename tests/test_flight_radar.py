from threading import Event, Lock
from time import monotonic, sleep
import unittest
from unittest.mock import patch

import numpy as np

from air_traffic import AdsbLolError
from air_traffic.models import Aircraft, FlightRoute
from config import FlightRadarConfig
from games.flight_radar import FlightRadarGame
from transit.models import Train


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
        self.assertTrue(np.any(np.all(frame == (255, 255, 255), axis=2)))
        self.assertTrue(np.any(np.all(frame == self.game.airport_color, axis=2)))
        self.assertFalse(np.any(np.all(frame == (0, 192, 255), axis=2)))

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

        self.assertEqual(colors, {(0, 0, 0), self.game.featured_aircraft_color})

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
            with self.game._data_lock:
                self.game._trains = (
                    Train("1", "A", 0, 33.0, -111.98),
                    Train("2", "A", 1, 33.02, -112.0),
                )
                self.game._train_snapshot_time = monotonic()

            frame = self.game.frame

        self.assertTrue(
            np.any(np.all(frame == self.game.rail_line_colors["A"], axis=2))
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

    def test_stale_train_snapshot_hides_trains(self) -> None:
        with self.game._data_lock:
            self.game._trains = (Train("1", "A", 0, 33.0, -111.98),)
            self.game._train_snapshot_time = (
                monotonic() - self.game.stale_snapshot_seconds - 5
            )

        frame = self.game.frame

        self.assertFalse(
            np.any(np.all(frame == self.game.eastbound_train_color, axis=2))
        )

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
