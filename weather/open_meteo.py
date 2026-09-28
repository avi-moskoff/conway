import json
from collections.abc import Callable, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from weather.models import AirQualitySample, WeatherSample

Transport = Callable[[Request, float], bytes]


class OpenMeteoError(RuntimeError):
    pass


class OpenMeteoConnectionError(OpenMeteoError):
    """The request never got a response at all - DNS, timeout, connection
    refused. Distinct from OpenMeteoApiError so callers can tell "no
    internet" apart from "the service is up but unhappy" - see the design
    doc's Error & degraded-state handling section.
    """


class OpenMeteoApiError(OpenMeteoError):
    """Open-Meteo was reachable but returned an error response or a body
    that couldn't be parsed."""


class OpenMeteoRateLimitedError(OpenMeteoApiError):
    def __init__(self, retry_after_seconds: float | None = None) -> None:
        super().__init__("Open-Meteo rate limit reached")
        self.retry_after_seconds = retry_after_seconds


def _default_transport(request: Request, timeout: float) -> bytes:
    with urlopen(request, timeout=timeout) as response:
        return response.read()


class OpenMeteoClient:
    """Small, dependency-free client for the free, keyless Open-Meteo APIs.

    Each sample carries the latitude/longitude the API actually reports for
    it (the underlying model grid can shift a request slightly), so callers
    should locate results using each sample's own coordinates rather than
    assuming they line up positionally with the requested points.
    """

    def __init__(
        self,
        weather_url: str = "https://api.open-meteo.com/v1/forecast",
        air_quality_url: str = "https://air-quality-api.open-meteo.com/v1/air-quality",
        timeout_seconds: float = 5.0,
        transport: Transport | None = None,
    ) -> None:
        self._weather_url = weather_url
        self._air_quality_url = air_quality_url
        self._timeout_seconds = timeout_seconds
        self._transport = transport or _default_transport

    def weather_for(
        self, points: Sequence[tuple[float, float]]
    ) -> tuple[WeatherSample, ...]:
        if not points:
            return ()
        payload = self._fetch(
            self._weather_url,
            points,
            {
                "current": "temperature_2m,precipitation,weather_code",
                "temperature_unit": "fahrenheit",
            },
        )
        samples = (self._parse_weather(record) for record in payload)
        return tuple(sample for sample in samples if sample is not None)

    def air_quality_for(
        self, points: Sequence[tuple[float, float]]
    ) -> tuple[AirQualitySample, ...]:
        if not points:
            return ()
        payload = self._fetch(
            self._air_quality_url, points, {"current": "us_aqi"}
        )
        samples = (self._parse_air_quality(record) for record in payload)
        return tuple(sample for sample in samples if sample is not None)

    def _fetch(
        self,
        base_url: str,
        points: Sequence[tuple[float, float]],
        extra_params: dict[str, str],
    ) -> list[object]:
        params = {
            "latitude": ",".join(f"{latitude:.6f}" for latitude, _longitude in points),
            "longitude": ",".join(
                f"{longitude:.6f}" for _latitude, longitude in points
            ),
            **extra_params,
        }
        payload = self._request_json(Request(f"{base_url}?{urlencode(params)}"))
        if len(points) == 1:
            return [payload]
        return payload if isinstance(payload, list) else []

    def _request_json(self, request: Request) -> object:
        try:
            body = self._transport(request, self._timeout_seconds)
        except HTTPError as error:
            if error.code == 429:
                value = error.headers.get("Retry-After")
                try:
                    retry_after = float(value) if value else None
                except ValueError:
                    retry_after = None
                raise OpenMeteoRateLimitedError(retry_after) from error
            raise OpenMeteoApiError(
                f"Open-Meteo API returned HTTP {error.code}"
            ) from error
        except (OSError, URLError) as error:
            raise OpenMeteoConnectionError("could not reach Open-Meteo API") from error
        try:
            return json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise OpenMeteoApiError("Open-Meteo API returned malformed JSON") from error

    @staticmethod
    def _parse_weather(record: object) -> WeatherSample | None:
        if not isinstance(record, dict):
            return None
        current = record.get("current")
        if not isinstance(current, dict):
            return None
        try:
            return WeatherSample(
                latitude=float(record["latitude"]),
                longitude=float(record["longitude"]),
                temperature_f=float(current["temperature_2m"]),
                precipitation_mm=float(current["precipitation"]),
                weather_code=int(current["weather_code"]),
            )
        except (KeyError, TypeError, ValueError):
            return None

    @staticmethod
    def _parse_air_quality(record: object) -> AirQualitySample | None:
        if not isinstance(record, dict):
            return None
        current = record.get("current")
        if not isinstance(current, dict):
            return None
        try:
            return AirQualitySample(
                latitude=float(record["latitude"]),
                longitude=float(record["longitude"]),
                us_aqi=float(current["us_aqi"]),
            )
        except (KeyError, TypeError, ValueError):
            return None
