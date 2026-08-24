import json
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from air_traffic.adsb_lol import AdsbLolClient, RateLimitedError
from air_traffic.projection import (
    clip_segment_to_radius,
    nearest_point_on_polyline,
    offset_nautical_miles,
    offset_to_latlon,
    pixel_to_offset,
    polyline_arc_length,
    project_offset,
    project_position,
)
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
        self.assertTrue(routes["TEST1"].plausible)
        self.assertFalse(routes["TEST2"].plausible)

    def test_parses_single_route_response(self) -> None:
        route = {
            "callsign": "TEST1",
            "_airport_codes_iata": "PHX-ORD",
            "plausible": True,
        }
        parsed = AdsbLolClient._parse_routes(route)
        self.assertEqual(parsed["TEST1"].label, "PHX>ORD")
        self.assertTrue(parsed["TEST1"].plausible)

    def test_preserves_intermediate_route_stops(self) -> None:
        route = {
            "callsign": "TEST1",
            "_airport_codes_iata": "LAX-PHX-LAX",
            "plausible": True,
        }

        parsed = AdsbLolClient._parse_routes(route)

        self.assertEqual(parsed["TEST1"].label, "LAX>PHX>LAX")

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

    def test_project_offset_matches_project_position(self) -> None:
        east, north = offset_nautical_miles(33.05, -111.9, 33.0, -112.0)
        self.assertEqual(
            project_offset(east, north, 10, 64, 55),
            project_position(33.05, -111.9, 33.0, -112.0, 10, 64, 55),
        )

    def test_short_axis_is_still_bounded_by_radius(self) -> None:
        # height=55 < width=64, so north/south is the short axis: it should
        # still cut off at exactly radius_nm, same as before this change.
        latitude, longitude = offset_to_latlon(0.0, 10.5, 33.0, -112.0)
        self.assertIsNone(
            project_position(latitude, longitude, 33.0, -112.0, 10, 64, 55)
        )

    def test_long_axis_reaches_farther_than_the_short_axis_radius(self) -> None:
        # East/west is the long axis for a 64x55 frame - at the same
        # angle-preserving pixels-per-nm scale as the short axis, it should
        # reach past radius_nm rather than stopping at it.
        latitude, longitude = offset_to_latlon(10.5, 0.0, 33.0, -112.0)
        self.assertIsNotNone(
            project_position(latitude, longitude, 33.0, -112.0, 10, 64, 55)
        )

    def test_diagonal_point_excluded_by_a_circle_is_visible_under_the_box(
        self,
    ) -> None:
        # 9nm east and 9nm north is outside a circle of radius 10
        # (9**2 + 9**2 > 10**2) but inside the box both axes now clip to.
        latitude, longitude = offset_to_latlon(9.0, 9.0, 33.0, -112.0)
        self.assertIsNotNone(
            project_position(latitude, longitude, 33.0, -112.0, 10, 64, 55)
        )


class OffsetToLatLonTests(unittest.TestCase):
    def test_round_trips_with_offset_nautical_miles(self) -> None:
        east, north = offset_nautical_miles(33.05, -111.9, 33.0, -112.0)
        latitude, longitude = offset_to_latlon(east, north, 33.0, -112.0)
        self.assertAlmostEqual(latitude, 33.05)
        self.assertAlmostEqual(longitude, -111.9)


class PixelToOffsetTests(unittest.TestCase):
    def test_round_trips_with_project_offset(self) -> None:
        east, north = 5.0, -3.0
        x, y = project_offset(east, north, 10, 64, 55)
        round_east, round_north = pixel_to_offset(x, y, 10, 64, 55)
        self.assertAlmostEqual(round_east, east, delta=0.5)
        self.assertAlmostEqual(round_north, north, delta=0.5)


class NearestPointOnPolylineTests(unittest.TestCase):
    def test_snaps_perpendicular_offset_onto_a_segment(self) -> None:
        polyline = [(0.0, 0.0), (10.0, 0.0)]
        self.assertEqual(nearest_point_on_polyline(4.0, 3.0, polyline), (4.0, 0.0))

    def test_clamps_to_nearest_endpoint_past_the_line(self) -> None:
        polyline = [(0.0, 0.0), (10.0, 0.0)]
        self.assertEqual(nearest_point_on_polyline(15.0, 2.0, polyline), (10.0, 0.0))

    def test_picks_the_closer_of_two_segments(self) -> None:
        polyline = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0)]
        self.assertEqual(nearest_point_on_polyline(9.0, 8.0, polyline), (10.0, 8.0))


class PolylineArcLengthTests(unittest.TestCase):
    def test_arc_length_along_a_single_segment(self) -> None:
        polyline = [(0.0, 0.0), (10.0, 0.0)]
        self.assertAlmostEqual(polyline_arc_length(4.0, 3.0, polyline), 4.0)

    def test_arc_length_accumulates_across_segments(self) -> None:
        polyline = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0)]
        self.assertAlmostEqual(polyline_arc_length(9.0, 8.0, polyline), 18.0)

    def test_arc_length_clamps_past_the_endpoint(self) -> None:
        polyline = [(0.0, 0.0), (10.0, 0.0)]
        self.assertAlmostEqual(polyline_arc_length(15.0, 2.0, polyline), 10.0)


class ClipSegmentToRadiusTests(unittest.TestCase):
    # A 21x21 frame gives half_width == half_height == 10, so scale == 1
    # and the box is exactly [-10, 10] on both axes - matching the old
    # circle-radius-10 tests for axis-aligned segments.
    def test_segment_entirely_inside_is_unchanged(self) -> None:
        self.assertEqual(
            clip_segment_to_radius(1.0, 1.0, 2.0, 2.0, 10.0, 21, 21),
            (1.0, 1.0, 2.0, 2.0),
        )

    def test_segment_entirely_outside_is_none(self) -> None:
        self.assertIsNone(
            clip_segment_to_radius(20.0, 20.0, 25.0, 25.0, 10.0, 21, 21)
        )

    def test_segment_crossing_boundary_is_clipped_to_radius(self) -> None:
        clipped = clip_segment_to_radius(0.0, 0.0, 20.0, 0.0, 10.0, 21, 21)
        self.assertEqual(clipped, (0.0, 0.0, 10.0, 0.0))

    def test_diagonal_segment_reaches_further_than_a_circle_would(self) -> None:
        # A circle of radius 10 would clip this diagonal at
        # (~7.07, ~7.07) (where x**2 + y**2 == 10**2); the box clips at
        # the corner (10, 10) instead.
        clipped = clip_segment_to_radius(0.0, 0.0, 20.0, 20.0, 10.0, 21, 21)
        self.assertEqual(clipped, (0.0, 0.0, 10.0, 10.0))

    def test_clip_reaches_farther_on_the_longer_axis(self) -> None:
        # width=64 > height=55, so east/west is the long axis: it should
        # clip past radius_nm=10 rather than stopping exactly at it.
        clipped = clip_segment_to_radius(0.0, 0.0, 20.0, 0.0, 10.0, 64, 55)
        self.assertEqual(clipped[:2], (0.0, 0.0))
        self.assertGreater(clipped[2], 10.0)
        self.assertEqual(clipped[3], 0.0)


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
