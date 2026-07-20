import json
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from air_traffic.adsb_lol import AdsbLolClient, RateLimitedError
from air_traffic.projection import project_position
from config import FlightRadarConfig


class AdsbLolClientTests(unittest.TestCase):
    def test_parses_complete_and_ground_aircraft(self) -> None:
        response = {
            "ac": [
                {
                    "hex": "abc123",
                    "flight": " TEST1 ",
                    "lat": 33.1,
                    "lon": -112.1,
                    "alt_baro": 12000,
                    "gs": 250.5,
                    "track": 90,
                    "seen_pos": 1.2,
                    "r": "N123AB",
                    "t": "A320",
                },
                {
                    "hex": "def456",
                    "lat": 33.2,
                    "lon": -112.2,
                    "alt_baro": "ground",
                },
                {"hex": "no-position"},
            ]
        }
        client = AdsbLolClient(
            transport=lambda _request, _timeout: json.dumps(response).encode()
        )

        aircraft = client.nearby_aircraft(33.0, -112.0, 8)

        self.assertEqual(len(aircraft), 2)
        self.assertEqual(aircraft[0].callsign, "TEST1")
        self.assertEqual(aircraft[0].altitude_feet, 12000)
        self.assertTrue(aircraft[1].on_ground)
        self.assertIsNone(aircraft[1].altitude_feet)

    def test_empty_route_response_is_not_an_error(self) -> None:
        client = AdsbLolClient(transport=lambda _request, _timeout: b"")
        self.assertEqual(client.routes_for([]), {})

    def test_parses_plausible_and_estimated_routes(self) -> None:
        response = [
            {
                "callsign": "TEST1",
                "_airport_codes_iata": "PHX-SEA",
                "airport_codes": "KPHX-KSEA",
                "plausible": True,
            },
            {
                "callsign": "TEST2",
                "_airport_codes_iata": "LAX-JFK",
                "plausible": False,
            },
        ]
        client = AdsbLolClient(
            transport=lambda _request, _timeout: json.dumps(response).encode()
        )
        aircraft = AdsbLolClient._parse_aircraft(
            {"hex": "abc", "flight": "TEST1", "lat": 33, "lon": -112}
        )

        routes = client.routes_for([aircraft])

        self.assertEqual(routes["TEST1"].label, "PHX>SEA")
        self.assertEqual(routes["TEST2"].label, "LAX>JFK")

    def test_rate_limit_exposes_retry_after(self) -> None:
        def rate_limited(_request, _timeout):
            raise HTTPError("url", 429, "slow down", {"Retry-After": "42"}, None)

        client = AdsbLolClient(transport=rate_limited)
        with self.assertRaises(RateLimitedError) as raised:
            client.nearby_aircraft(33.0, -112.0, 8)
        self.assertEqual(raised.exception.retry_after_seconds, 42)


class ProjectionTests(unittest.TestCase):
    def test_center_and_cardinal_directions(self) -> None:
        center = project_position(33.0, -112.0, 33.0, -112.0, 10, 64, 55)
        north = project_position(33.1, -112.0, 33.0, -112.0, 10, 64, 55)
        east = project_position(33.0, -111.9, 33.0, -112.0, 10, 64, 55)

        self.assertEqual(center, (32, 27))
        self.assertLess(north[1], center[1])
        self.assertGreater(east[0], center[0])

    def test_position_outside_radius_is_hidden(self) -> None:
        self.assertIsNone(
            project_position(34.0, -112.0, 33.0, -112.0, 8, 64, 55)
        )


class ConfigurationTests(unittest.TestCase):
    def test_mode_is_disabled_without_coordinates(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            self.assertIsNone(FlightRadarConfig.from_environment())

    def test_requires_both_coordinates(self) -> None:
        with patch.dict("os.environ", {"CONWAY_HOME_LATITUDE": "33"}, clear=True):
            with self.assertRaises(ValueError):
                FlightRadarConfig.from_environment()

    def test_requires_both_optional_airport_coordinates(self) -> None:
        environment = {
            "CONWAY_HOME_LATITUDE": "33",
            "CONWAY_HOME_LONGITUDE": "-112",
            "CONWAY_AIRPORT_LATITUDE": "33.4",
        }
        with patch.dict("os.environ", environment, clear=True):
            with self.assertRaises(ValueError):
                FlightRadarConfig.from_environment()


if __name__ == "__main__":
    unittest.main()
