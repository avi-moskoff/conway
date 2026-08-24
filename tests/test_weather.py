import json
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from config import WeatherRadarConfig
from weather.open_meteo import OpenMeteoClient, OpenMeteoError


class OpenMeteoClientWeatherTests(unittest.TestCase):
    def test_parses_multi_point_response(self) -> None:
        response = [
            {
                "latitude": 33.4,
                "longitude": -112.0,
                "current": {
                    "temperature_2m": 101.2,
                    "precipitation": 0.0,
                    "weather_code": 0,
                },
            },
            {
                "latitude": 33.5,
                "longitude": -111.9,
                "current": {
                    "temperature_2m": 98.5,
                    "precipitation": 1.2,
                    "weather_code": 61,
                },
            },
        ]
        client = OpenMeteoClient(
            transport=lambda _request, _timeout: json.dumps(response).encode()
        )

        samples = client.weather_for([(33.4, -112.0), (33.5, -111.9)])

        self.assertEqual(len(samples), 2)
        self.assertEqual(samples[0].temperature_f, 101.2)
        self.assertEqual(samples[1].weather_code, 61)

    def test_single_point_response_is_not_wrapped_in_a_list(self) -> None:
        response = {
            "latitude": 33.4,
            "longitude": -112.0,
            "current": {
                "temperature_2m": 101.2,
                "precipitation": 0.0,
                "weather_code": 0,
            },
        }
        client = OpenMeteoClient(
            transport=lambda _request, _timeout: json.dumps(response).encode()
        )

        samples = client.weather_for([(33.4, -112.0)])

        self.assertEqual(len(samples), 1)
        self.assertEqual(samples[0].temperature_f, 101.2)

    def test_no_points_makes_no_request(self) -> None:
        def transport(_request, _timeout):
            raise AssertionError("should not be called")

        client = OpenMeteoClient(transport=transport)
        self.assertEqual(client.weather_for([]), ())

    def test_malformed_records_are_skipped(self) -> None:
        response = [
            {"latitude": 33.4, "longitude": -112.0, "current": {}},
            {
                "latitude": 33.5,
                "longitude": -111.9,
                "current": {
                    "temperature_2m": 98.5,
                    "precipitation": 1.2,
                    "weather_code": 61,
                },
            },
        ]
        client = OpenMeteoClient(
            transport=lambda _request, _timeout: json.dumps(response).encode()
        )

        samples = client.weather_for([(33.4, -112.0), (33.5, -111.9)])

        self.assertEqual(len(samples), 1)
        self.assertEqual(samples[0].latitude, 33.5)

    def test_http_error_raises_open_meteo_error(self) -> None:
        def failing_transport(_request, _timeout):
            raise HTTPError("url", 500, "server error", {}, None)

        client = OpenMeteoClient(transport=failing_transport)
        with self.assertRaises(OpenMeteoError):
            client.weather_for([(33.4, -112.0)])


class OpenMeteoClientAirQualityTests(unittest.TestCase):
    def test_parses_multi_point_response(self) -> None:
        response = [
            {"latitude": 33.4, "longitude": -112.0, "current": {"us_aqi": 42}},
            {"latitude": 33.5, "longitude": -111.9, "current": {"us_aqi": 155}},
        ]
        client = OpenMeteoClient(
            transport=lambda _request, _timeout: json.dumps(response).encode()
        )

        samples = client.air_quality_for([(33.4, -112.0), (33.5, -111.9)])

        self.assertEqual(len(samples), 2)
        self.assertEqual(samples[0].us_aqi, 42)
        self.assertEqual(samples[1].us_aqi, 155)


class WeatherRadarConfigTests(unittest.TestCase):
    def test_disabled_without_coordinates(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            self.assertIsNone(WeatherRadarConfig.from_environment())

    def test_requires_both_coordinates(self) -> None:
        with patch.dict("os.environ", {"CONWAY_HOME_LATITUDE": "33"}, clear=True):
            with self.assertRaises(ValueError):
                WeatherRadarConfig.from_environment()

    def test_uses_defaults_when_only_home_is_set(self) -> None:
        environment = {
            "CONWAY_HOME_LATITUDE": "33.0",
            "CONWAY_HOME_LONGITUDE": "-112.0",
        }
        with patch.dict("os.environ", environment, clear=True):
            config = WeatherRadarConfig.from_environment()

        self.assertEqual(config.radius_nm, 15.0)
        self.assertEqual(config.poll_seconds, 600.0)
        self.assertEqual(config.landmarks, ())

    def test_parses_landmarks(self) -> None:
        environment = {
            "CONWAY_HOME_LATITUDE": "33.0",
            "CONWAY_HOME_LONGITUDE": "-112.0",
            "CONWAY_WEATHER_LANDMARKS": (
                "Camelback:33.52:-111.96;South Mountain:33.33:-112.05"
            ),
        }
        with patch.dict("os.environ", environment, clear=True):
            config = WeatherRadarConfig.from_environment()

        self.assertEqual(
            config.landmarks,
            (("Camelback", 33.52, -111.96), ("South Mountain", 33.33, -112.05)),
        )

    def test_rejects_malformed_landmark_entry(self) -> None:
        environment = {
            "CONWAY_HOME_LATITUDE": "33.0",
            "CONWAY_HOME_LONGITUDE": "-112.0",
            "CONWAY_WEATHER_LANDMARKS": "Camelback:33.52",
        }
        with patch.dict("os.environ", environment, clear=True):
            with self.assertRaises(ValueError):
                WeatherRadarConfig.from_environment()


if __name__ == "__main__":
    unittest.main()
