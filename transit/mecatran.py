import json
from collections.abc import Callable, Iterable
from time import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from transit.models import Train

Transport = Callable[[Request, float], bytes]


class ValleyMetroError(RuntimeError):
    pass


def _default_transport(request: Request, timeout: float) -> bytes:
    with urlopen(request, timeout=timeout) as response:
        return response.read()


class ValleyMetroClient:
    """Small, dependency-free client for Valley Metro's Mecatran GTFS-realtime feed."""

    def __init__(
        self,
        url: str,
        api_key: str,
        timeout_seconds: float = 5.0,
        transport: Transport | None = None,
    ) -> None:
        self._url = url
        self._api_key = api_key
        self._timeout_seconds = timeout_seconds
        self._transport = transport or _default_transport

    def active_trains(self, route_ids: Iterable[str]) -> tuple[Train, ...]:
        route_ids = frozenset(route_ids)
        query = urlencode({"apiKey": self._api_key, "asJson": "true"})
        payload = self._request_json(Request(f"{self._url}?{query}"))
        entities = payload.get("entity", []) if isinstance(payload, dict) else []
        trains = []
        for entity in entities:
            train = self._parse_train(entity, route_ids)
            if train is not None:
                trains.append(train)
        return tuple(trains)

    def _request_json(self, request: Request) -> object:
        request.add_header("Accept", "application/json")
        request.add_header("User-Agent", "conway-led-matrix/0.1")
        try:
            body = self._transport(request, self._timeout_seconds)
        except HTTPError as error:
            raise ValleyMetroError(
                f"Valley Metro API returned HTTP {error.code}"
            ) from error
        except (OSError, URLError) as error:
            raise ValleyMetroError("could not reach Valley Metro API") from error
        try:
            return json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise ValleyMetroError("Valley Metro API returned malformed JSON") from error

    @staticmethod
    def _parse_train(entity: object, route_ids: frozenset[str]) -> Train | None:
        if not isinstance(entity, dict):
            return None
        vehicle = entity.get("vehicle")
        if not isinstance(vehicle, dict):
            return None
        trip = vehicle.get("trip")
        route_id = trip.get("routeId") if isinstance(trip, dict) else None
        if route_id not in route_ids:
            return None
        position = vehicle.get("position")
        if not isinstance(position, dict):
            return None
        try:
            latitude = float(position["latitude"])
            longitude = float(position["longitude"])
            if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
                return None
        except (KeyError, TypeError, ValueError):
            return None

        try:
            direction_id = int(trip.get("directionId"))
        except (TypeError, ValueError):
            direction_id = None

        try:
            seen_seconds = max(0.0, time() - float(vehicle.get("timestamp")))
        except (TypeError, ValueError):
            seen_seconds = 0.0

        info = vehicle.get("vehicle")
        vehicle_id = info.get("id") if isinstance(info, dict) else None
        label = info.get("label") if isinstance(info, dict) else None

        return Train(
            vehicle_id=str(vehicle_id or entity.get("id") or "unknown"),
            route_id=route_id,
            direction_id=direction_id,
            latitude=latitude,
            longitude=longitude,
            label=str(label) if label else None,
            seen_seconds=seen_seconds,
        )
