import json
import time
import unittest
from urllib.error import HTTPError

from transit.mecatran import ValleyMetroClient, ValleyMetroError


class ValleyMetroClientTests(unittest.TestCase):
    def test_parses_and_filters_by_route(self) -> None:
        now = time.time()
        response = {
            "header": {"gtfsRealtimeVersion": "2.0"},
            "entity": [
                {
                    "id": "RTVP:T:1",
                    "vehicle": {
                        "trip": {"tripId": "1", "routeId": "A", "directionId": 0},
                        "position": {"latitude": 33.44, "longitude": -111.96},
                        "timestamp": str(int(now - 5)),
                        "vehicle": {"id": "120", "label": "Downtown Phoenix Hub"},
                    },
                },
                {
                    "id": "RTVP:T:2",
                    "vehicle": {
                        "trip": {"tripId": "2", "routeId": "72", "directionId": 1},
                        "position": {"latitude": 33.4, "longitude": -111.9},
                        "timestamp": str(int(now)),
                        "vehicle": {"id": "9", "label": "Bus"},
                    },
                },
                {"id": "RTVP:V:3", "vehicle": {"position": {"latitude": 33.4, "longitude": -111.9}}},
            ],
        }
        client = ValleyMetroClient(
            "https://example.test/vehicles",
            "https://example.test/realtime",
            "key",
            transport=lambda _request, _timeout: json.dumps(response).encode(),
        )

        trains = client.active_trains({"A", "S"})

        self.assertEqual(len(trains), 1)
        train = trains[0]
        self.assertEqual(train.route_id, "A")
        self.assertEqual(train.direction_id, 0)
        self.assertEqual(train.vehicle_id, "120")
        self.assertEqual(train.label, "Downtown Phoenix Hub")
        self.assertEqual(train.trip_id, "1")
        self.assertAlmostEqual(train.seen_seconds, 5, delta=1)

    def test_ignores_malformed_entities(self) -> None:
        response = {"entity": [{"vehicle": {"trip": {"routeId": "A"}}}, "not-a-dict", {}]}
        client = ValleyMetroClient(
            "https://example.test/vehicles",
            "https://example.test/realtime",
            "key",
            transport=lambda _request, _timeout: json.dumps(response).encode(),
        )

        trains = client.active_trains({"A"})

        self.assertEqual(trains, ())

    def test_rejects_null_island_as_a_missing_fix(self) -> None:
        # Observed live: the feed occasionally emits (0, 0) - thousands of
        # miles from Phoenix - in place of a vehicle's real position.
        response = {
            "entity": [
                {
                    "id": "RTVP:T:1",
                    "vehicle": {
                        "trip": {"tripId": "1", "routeId": "A", "directionId": 0},
                        "position": {"latitude": 0.0, "longitude": 0.0},
                        "timestamp": str(int(time.time())),
                        "vehicle": {"id": "130", "label": "Downtown Phoenix Hub"},
                    },
                }
            ]
        }
        client = ValleyMetroClient(
            "https://example.test/vehicles",
            "https://example.test/realtime",
            "key",
            transport=lambda _request, _timeout: json.dumps(response).encode(),
        )

        trains = client.active_trains({"A"})

        self.assertEqual(trains, ())

    def test_rejects_any_fix_outside_the_service_area(self) -> None:
        # A position doesn't have to be exactly (0, 0) to be bogus - any fix
        # far outside greater Phoenix is equally not a real Valley Metro
        # vehicle location.
        response = {
            "entity": [
                {
                    "id": "RTVP:T:1",
                    "vehicle": {
                        "trip": {"tripId": "1", "routeId": "A", "directionId": 0},
                        "position": {"latitude": 40.7128, "longitude": -74.006},
                        "timestamp": str(int(time.time())),
                        "vehicle": {"id": "130", "label": "Downtown Phoenix Hub"},
                    },
                }
            ]
        }
        client = ValleyMetroClient(
            "https://example.test/vehicles",
            "https://example.test/realtime",
            "key",
            transport=lambda _request, _timeout: json.dumps(response).encode(),
        )

        trains = client.active_trains({"A"})

        self.assertEqual(trains, ())

    def test_http_error_raises_valley_metro_error(self) -> None:
        def failing_transport(_request, _timeout):
            raise HTTPError("url", 500, "server error", {}, None)

        client = ValleyMetroClient(
            "https://example.test/vehicles",
            "https://example.test/realtime",
            "key",
            transport=failing_transport,
        )

        with self.assertRaises(ValleyMetroError):
            client.active_trains({"A"})

    def test_parses_arrivals_for_requested_stops(self) -> None:
        response = {
            "header": {"gtfsRealtimeVersion": "2.0"},
            "entity": [
                {
                    "id": "RT|1|1",
                    "tripUpdate": {
                        "trip": {"tripId": "1", "routeId": "A", "directionId": 0},
                        "stopTimeUpdate": [
                            {"stopId": "1111", "arrival": {"time": "1000", "delay": 0}},
                            {"stopId": "9008", "arrival": {"time": "2000", "delay": 60}},
                        ],
                    },
                },
                {
                    "id": "RT|2|2",
                    "tripUpdate": {
                        "trip": {"tripId": "2", "routeId": "A", "directionId": 1},
                        "stopTimeUpdate": [
                            {"stopId": "9036", "arrival": {"time": "1500", "delay": 0}},
                        ],
                    },
                },
                {
                    "id": "RT|3|3",
                    "tripUpdate": {
                        "trip": {"tripId": "3", "routeId": "72"},
                        "stopTimeUpdate": [
                            {"stopId": "9008", "arrival": {"time": "999", "delay": 0}},
                        ],
                    },
                },
            ],
        }
        client = ValleyMetroClient(
            "https://example.test/vehicles",
            "https://example.test/realtime",
            "key",
            transport=lambda _request, _timeout: json.dumps(response).encode(),
        )

        arrivals = client.arrivals_for_stops({"9008", "9036"})

        self.assertEqual(len(arrivals), 3)
        by_trip = {arrival.trip_id: arrival for arrival in arrivals}
        self.assertEqual(by_trip["1"].stop_id, "9008")
        self.assertEqual(by_trip["1"].arrival_epoch, 2000.0)
        self.assertEqual(by_trip["2"].stop_id, "9036")
        self.assertEqual(by_trip["3"].route_id, "72")

    def test_arrivals_skips_canceled_trips(self) -> None:
        response = {
            "entity": [
                {
                    "id": "RT|1|1",
                    "tripUpdate": {
                        "trip": {
                            "tripId": "1",
                            "routeId": "A",
                            "directionId": 0,
                            "scheduleRelationship": "CANCELED",
                        },
                        "stopTimeUpdate": [
                            {"stopId": "9008", "arrival": {"time": "2000", "delay": 0}},
                        ],
                    },
                },
            ],
        }
        client = ValleyMetroClient(
            "https://example.test/vehicles",
            "https://example.test/realtime",
            "key",
            transport=lambda _request, _timeout: json.dumps(response).encode(),
        )

        arrivals = client.arrivals_for_stops({"9008"})

        self.assertEqual(arrivals, ())

    def test_arrivals_for_no_stops_skips_request(self) -> None:
        def unexpected_transport(_request, _timeout):
            raise AssertionError("should not have made a request")

        client = ValleyMetroClient(
            "https://example.test/vehicles",
            "https://example.test/realtime",
            "key",
            transport=unexpected_transport,
        )

        self.assertEqual(client.arrivals_for_stops(()), ())


if __name__ == "__main__":
    unittest.main()
