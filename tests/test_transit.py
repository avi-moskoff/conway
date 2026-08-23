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
        self.assertAlmostEqual(train.seen_seconds, 5, delta=1)

    def test_ignores_malformed_entities(self) -> None:
        response = {"entity": [{"vehicle": {"trip": {"routeId": "A"}}}, "not-a-dict", {}]}
        client = ValleyMetroClient(
            "https://example.test/vehicles",
            "key",
            transport=lambda _request, _timeout: json.dumps(response).encode(),
        )

        trains = client.active_trains({"A"})

        self.assertEqual(trains, ())

    def test_http_error_raises_valley_metro_error(self) -> None:
        def failing_transport(_request, _timeout):
            raise HTTPError("url", 500, "server error", {}, None)

        client = ValleyMetroClient(
            "https://example.test/vehicles", "key", transport=failing_transport
        )

        with self.assertRaises(ValleyMetroError):
            client.active_trains({"A"})


if __name__ == "__main__":
    unittest.main()
