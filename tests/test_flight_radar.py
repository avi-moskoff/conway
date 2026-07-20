from threading import Event, Lock
from time import monotonic, sleep
import unittest

import numpy as np

from air_traffic.models import Aircraft
from config import FlightRadarConfig
from games.flight_radar import FlightRadarGame


class FakeClient:
    def __init__(self) -> None:
        self.calls = 0
        self.called = Event()
        self._lock = Lock()

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
                track_degrees=90,
                ground_speed_knots=200,
            ),
        )

    def routes_for(self, _aircraft):
        return {}


class FlightRadarGameTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = FakeClient()
        self.game = FlightRadarGame(
            64,
            64,
            FlightRadarConfig(33.0, -112.0, poll_seconds=0.05),
            client=self.client,
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
        self.assertTrue(np.any(np.all(frame == (255, 255, 255), axis=2)))
        self.assertTrue(np.any(np.all(frame == (0, 192, 255), axis=2)))

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


if __name__ == "__main__":
    unittest.main()
