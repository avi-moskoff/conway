import json
from collections.abc import Callable, Iterable
from time import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from transit.models import StopArrival, Train

Transport = Callable[[Request, float], bytes]


class ValleyMetroError(RuntimeError):
    pass


def _default_transport(request: Request, timeout: float) -> bytes:
    with urlopen(request, timeout=timeout) as response:
        return response.read()


class ValleyMetroClient:
    """Small, dependency-free client for Valley Metro's Mecatran GTFS-realtime feeds."""

    def __init__(
        self,
        vehicles_url: str,
        trip_updates_url: str,
        api_key: str,
        timeout_seconds: float = 5.0,
        transport: Transport | None = None,
    ) -> None:
        self._vehicles_url = vehicles_url
        self._trip_updates_url = trip_updates_url
        self._api_key = api_key
        self._timeout_seconds = timeout_seconds
        self._transport = transport or _default_transport

    def active_trains(self, route_ids: Iterable[str]) -> tuple[Train, ...]:
        route_ids = frozenset(route_ids)
        payload = self._fetch(self._vehicles_url)
        entities = payload.get("entity", []) if isinstance(payload, dict) else []
        trains = []
        for entity in entities:
            train = self._parse_train(entity, route_ids)
            if train is not None:
                trains.append(train)
        return tuple(trains)

    def arrivals_for_stops(self, stop_ids: Iterable[str]) -> tuple[StopArrival, ...]:
        stop_ids = frozenset(stop_ids)
        if not stop_ids:
            return ()
        payload = self._fetch(self._trip_updates_url)
        entities = payload.get("entity", []) if isinstance(payload, dict) else []
        arrivals = []
        for entity in entities:
            arrivals.extend(self._parse_arrivals(entity, stop_ids))
        return tuple(arrivals)

    def _fetch(self, url: str) -> object:
        query = urlencode({"apiKey": self._api_key, "asJson": "true"})
        return self._request_json(Request(f"{url}?{query}"))

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
            # (0, 0) is "null island" - nowhere near Phoenix, and the feed
            # has been observed to emit it as a sentinel when a vehicle's
            # real fix isn't available rather than omitting the position.
            if latitude == 0.0 and longitude == 0.0:
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
        trip_id = trip.get("tripId") if isinstance(trip, dict) else None

        return Train(
            vehicle_id=str(vehicle_id or entity.get("id") or "unknown"),
            route_id=route_id,
            direction_id=direction_id,
            latitude=latitude,
            longitude=longitude,
            label=str(label) if label else None,
            seen_seconds=seen_seconds,
            trip_id=str(trip_id) if trip_id is not None else None,
        )

    @staticmethod
    def _parse_arrivals(entity: object, stop_ids: frozenset[str]) -> list[StopArrival]:
        if not isinstance(entity, dict):
            return []
        trip_update = entity.get("tripUpdate")
        if not isinstance(trip_update, dict):
            return []
        trip = trip_update.get("trip")
        if not isinstance(trip, dict):
            return []
        trip_id = trip.get("tripId")
        route_id = trip.get("routeId")
        if trip_id is None or route_id is None:
            return []
        try:
            direction_id = int(trip.get("directionId"))
        except (TypeError, ValueError):
            direction_id = None

        arrivals = []
        for update in trip_update.get("stopTimeUpdate") or []:
            if not isinstance(update, dict):
                continue
            stop_id = update.get("stopId")
            if stop_id not in stop_ids:
                continue
            arrival = update.get("arrival")
            if not isinstance(arrival, dict):
                continue
            try:
                arrival_epoch = float(arrival["time"])
            except (KeyError, TypeError, ValueError):
                continue
            arrivals.append(
                StopArrival(
                    trip_id=str(trip_id),
                    route_id=str(route_id),
                    direction_id=direction_id,
                    stop_id=str(stop_id),
                    arrival_epoch=arrival_epoch,
                )
            )
        return arrivals
