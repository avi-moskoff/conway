import json
from collections.abc import Callable, Iterable
from math import ceil
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from air_traffic.models import Aircraft, FlightRoute

Transport = Callable[[Request, float], bytes]


class AdsbLolError(RuntimeError):
    pass


class RateLimitedError(AdsbLolError):
    def __init__(self, retry_after_seconds: float | None = None) -> None:
        super().__init__("adsb.lol rate limit reached")
        self.retry_after_seconds = retry_after_seconds


def _default_transport(request: Request, timeout: float) -> bytes:
    with urlopen(request, timeout=timeout) as response:
        return response.read()


class AdsbLolClient:
    """Small, dependency-free client for the public adsb.lol API."""

    def __init__(
        self,
        base_url: str = "https://api.adsb.lol",
        api_key: str | None = None,
        timeout_seconds: float = 5.0,
        transport: Transport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._timeout_seconds = timeout_seconds
        self._transport = transport or _default_transport

    def nearby_aircraft(
        self, latitude: float, longitude: float, radius_nm: float
    ) -> tuple[Aircraft, ...]:
        path = f"/v2/lat/{latitude:.6f}/lon/{longitude:.6f}/dist/{ceil(radius_nm)}"
        payload = self._request_json(Request(self._base_url + path))
        records = payload.get("ac", []) if isinstance(payload, dict) else []
        aircraft = []
        for record in records:
            parsed = self._parse_aircraft(record)
            if parsed is not None:
                aircraft.append(parsed)
        return tuple(aircraft)

    def routes_for(self, aircraft: Iterable[Aircraft]) -> dict[str, FlightRoute]:
        planes_by_callsign = {
            plane.callsign: {
                "callsign": plane.callsign,
                "lat": plane.latitude,
                "lng": plane.longitude,
            }
            for plane in aircraft
            if plane.callsign
        }
        planes = list(planes_by_callsign.values())
        if not planes:
            return {}
        if len(planes) == 1:
            plane = planes[0]
            callsign = quote(str(plane["callsign"]), safe="")
            path = (
                f"/api/0/route/{callsign}/"
                f"{plane['lat']:.6f}/{plane['lng']:.6f}"
            )
            payload = self._request_json(Request(self._base_url + path))
            return self._parse_routes(payload)
        routes = {}
        for start in range(0, len(planes), 100):
            body = json.dumps({"planes": planes[start : start + 100]}).encode()
            request = Request(
                self._base_url + "/api/0/routeset",
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            payload = self._request_json(request, allow_empty=True)
            routes.update(self._parse_routes(payload))
        return routes

    def _request_json(self, request: Request, allow_empty: bool = False) -> object:
        request.add_header("Accept", "application/json")
        request.add_header("User-Agent", "conway-led-matrix/0.1")
        if self._api_key:
            request.add_header("Authorization", f"Bearer {self._api_key}")
        try:
            body = self._transport(request, self._timeout_seconds)
        except HTTPError as error:
            if error.code == 429:
                value = error.headers.get("Retry-After")
                try:
                    retry_after = float(value) if value else None
                except ValueError:
                    retry_after = None
                raise RateLimitedError(retry_after) from error
            raise AdsbLolError(f"adsb.lol returned HTTP {error.code}") from error
        except (OSError, URLError) as error:
            raise AdsbLolError("could not reach adsb.lol") from error

        if not body and allow_empty:
            return None
        try:
            return json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise AdsbLolError("adsb.lol returned malformed JSON") from error

    @staticmethod
    def _parse_aircraft(record: object) -> Aircraft | None:
        if not isinstance(record, dict):
            return None
        try:
            latitude = float(record["lat"])
            longitude = float(record["lon"])
            if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
                return None
        except (KeyError, TypeError, ValueError):
            return None

        altitude_value = record.get("alt_baro")
        if altitude_value is None:
            altitude_value = record.get("alt_geom")
        on_ground = altitude_value == "ground"
        try:
            altitude = None if on_ground or altitude_value is None else int(altitude_value)
        except (TypeError, ValueError):
            altitude = None

        def optional_float(name: str) -> float | None:
            try:
                value = record.get(name)
                return None if value is None else float(value)
            except (TypeError, ValueError):
                return None

        def clean_text(name: str) -> str | None:
            value = record.get(name)
            text = str(value).strip() if value is not None else ""
            return text or None

        return Aircraft(
            icao_hex=clean_text("hex") or "unknown",
            latitude=latitude,
            longitude=longitude,
            callsign=clean_text("flight"),
            track_degrees=optional_float("track"),
            ground_speed_knots=optional_float("gs"),
            altitude_feet=altitude,
            on_ground=on_ground,
            seen_seconds=optional_float("seen_pos") or 0.0,
            registration=clean_text("r"),
            aircraft_type=clean_text("t"),
        )

    @staticmethod
    def _parse_routes(payload: object) -> dict[str, FlightRoute]:
        if payload is None:
            return {}
        if isinstance(payload, dict):
            nested_routes = payload.get("routes")
            records = nested_routes if isinstance(nested_routes, list) else [payload]
        else:
            records = payload
        if not isinstance(records, list):
            return {}
        routes = {}
        for record in records:
            if not isinstance(record, dict):
                continue
            callsign = str(record.get("callsign") or record.get("flight") or "").strip()
            airport_codes = record.get("_airport_codes_iata")
            if not airport_codes or airport_codes == "unknown":
                airport_codes = record.get("airport_codes")
            codes = tuple(
                code.strip()
                for code in str(airport_codes or "").split("-")
                if code.strip()
            )
            origin = record.get("origin") or record.get("from")
            destination = record.get("destination") or record.get("to")
            if len(codes) >= 2:
                origin, destination = codes[0], codes[-1]
            if callsign and (origin or destination):
                plausible_value = record.get("plausible")
                routes[callsign] = FlightRoute(
                    callsign=callsign,
                    origin=str(origin).strip() if origin else None,
                    destination=str(destination).strip() if destination else None,
                    plausible=(
                        bool(plausible_value)
                        if plausible_value is not None
                        else None
                    ),
                    via=codes[1:-1],
                )
        return routes
