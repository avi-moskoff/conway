import logging
import random
from math import cos, radians, sin
from threading import Event, Lock, Thread
from time import monotonic

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from air_traffic import AdsbLolClient, Aircraft, FlightRoute, RateLimitedError
from air_traffic.projection import offset_nautical_miles, project_position
from config import FlightRadarConfig
from games.base import Game

logger = logging.getLogger(__name__)


class FlightRadarGame(Game):
    """North-up view of live aircraft near the configured location."""

    frame_delay_seconds = 0.1
    ticker_height = 10
    maximum_position_age_seconds = 60.0
    stale_snapshot_seconds = 60.0
    route_ttl_seconds = 6 * 60 * 60
    missing_route_ttl_seconds = 15 * 60
    featured_aircraft_color = (255, 180, 0)
    other_aircraft_color = (255, 255, 255)
    airport_color = (0, 255, 0)

    def __init__(
        self,
        height: int,
        width: int,
        config: FlightRadarConfig,
        client: AdsbLolClient | None = None,
    ) -> None:
        super().__init__(height, width)
        self._config = config
        self._client = client or AdsbLolClient(
            config.api_url, api_key=config.api_key
        )
        self._data_lock = Lock()
        self._active_event = Event()
        self._wake_event = Event()
        self._stop_event = Event()
        self._worker: Thread | None = None
        self._aircraft: tuple[Aircraft, ...] = ()
        self._routes: dict[str, tuple[FlightRoute | None, float]] = {}
        self._snapshot_time: float | None = None
        self._has_error = False
        self._last_label = ""
        self._scroll_offset = 0
        self._ticker_scrolls = False
        self._font = ImageFont.load_default(size=10)

    def activate(self) -> None:
        if self._worker is None:
            self._worker = Thread(
                target=self._poll_loop, name="flight-radar-poller", daemon=True
            )
            self._worker.start()
        self._active_event.set()
        self._wake_event.set()
        logger.info("Flight radar polling activated")

    def deactivate(self) -> None:
        self._active_event.clear()
        self._wake_event.set()
        logger.info("Flight radar polling paused")

    def close(self) -> None:
        self._stop_event.set()
        self._active_event.set()
        self._wake_event.set()
        if self._worker is not None:
            self._worker.join(timeout=11.0)
        logger.info("Flight radar polling stopped")

    def reset(self) -> None:
        self._scroll_offset = 0
        self._wake_event.set()

    def advance(self) -> None:
        if self._ticker_scrolls:
            self._scroll_offset += 1

    @property
    def frame(self) -> np.ndarray:
        now = monotonic()
        with self._data_lock:
            aircraft = self._aircraft
            routes = dict(self._routes)
            snapshot_time = self._snapshot_time
            has_error = self._has_error

        stale = snapshot_time is None or now - snapshot_time > self.stale_snapshot_seconds
        radar_height = self.height - self.ticker_height - 1
        frame = np.zeros((self.height, self.width, 3), dtype=np.uint8)
        center_x, center_y = self.width // 2, radar_height // 2
        frame[center_y, center_x] = (0, 64, 255)
        self._draw_airport(frame, radar_height)

        visible: list[tuple[float, Aircraft, tuple[int, int]]] = []
        if not stale:
            elapsed = now - snapshot_time
            for plane in aircraft:
                if (
                    plane.on_ground
                    or plane.seen_seconds + elapsed > self.maximum_position_age_seconds
                ):
                    continue
                latitude, longitude = self._extrapolate(plane, elapsed)
                point = project_position(
                    latitude,
                    longitude,
                    self._config.home_latitude,
                    self._config.home_longitude,
                    self._config.radius_nm,
                    self.width,
                    radar_height,
                )
                if point is None:
                    continue
                east, north = offset_nautical_miles(
                    latitude,
                    longitude,
                    self._config.home_latitude,
                    self._config.home_longitude,
                )
                visible.append((east * east + north * north, plane, point))

        featured = min(visible, default=None, key=lambda item: item[0])
        for item in visible:
            x, y = item[2]
            frame[y, x] = self.other_aircraft_color
        if featured is not None:
            x, y = featured[2]
            frame[y, x] = self.featured_aircraft_color
        if stale:
            label = "NO SIGNAL"
        elif featured is None:
            label = "CLEAR SKY"
        else:
            plane = featured[1]
            cached = routes.get(plane.callsign or "")
            route_label = cached[0].label if cached and cached[0] else None
            label = f"{plane.label} {route_label}" if route_label else plane.label
        if has_error and not stale:
            frame[0, 0] = (255, 0, 0)
        self._draw_ticker(frame, label)
        return frame

    def _draw_airport(self, frame: np.ndarray, radar_height: int) -> None:
        latitude = self._config.airport_latitude
        longitude = self._config.airport_longitude
        if latitude is None or longitude is None:
            return
        point = project_position(
            latitude,
            longitude,
            self._config.home_latitude,
            self._config.home_longitude,
            self._config.radius_nm,
            self.width,
            radar_height,
        )
        if point is not None:
            x, y = point
            frame[y, x] = self.airport_color

    def _poll_loop(self) -> None:
        failures = 0
        while not self._stop_event.is_set():
            if not self._active_event.is_set():
                self._wake_event.wait()
                self._wake_event.clear()
                continue
            try:
                aircraft = self._client.nearby_aircraft(
                    self._config.home_latitude,
                    self._config.home_longitude,
                    self._config.radius_nm,
                )
                with self._data_lock:
                    self._aircraft = aircraft
                    self._snapshot_time = monotonic()
                    self._has_error = False
                logger.info("Flight radar received %d aircraft", len(aircraft))
                self._update_routes(aircraft)
                failures = 0
                wait_seconds = self._config.poll_seconds
            except RateLimitedError as error:
                failures += 1
                self._mark_error()
                logger.warning("Flight radar rate limited; backing off")
                wait_seconds = error.retry_after_seconds or max(
                    60.0, self._config.poll_seconds * 4
                )
            except Exception as error:
                failures += 1
                self._mark_error()
                logger.warning("Flight radar poll failed: %s", error)
                exponential = self._config.poll_seconds * (2 ** min(failures, 5))
                wait_seconds = min(5 * 60.0, exponential) * random.uniform(0.8, 1.2)
            self._wake_event.wait(wait_seconds)
            self._wake_event.clear()

    def _mark_error(self) -> None:
        with self._data_lock:
            self._has_error = True

    def _update_routes(self, aircraft: tuple[Aircraft, ...]) -> None:
        now = monotonic()
        with self._data_lock:
            self._routes = {
                callsign: cached
                for callsign, cached in self._routes.items()
                if cached[1] > now
            }
            eligible = [
                plane
                for plane in aircraft
                if plane.callsign
                and not plane.on_ground
                and plane.seen_seconds <= self.maximum_position_age_seconds
            ]
            closest = min(
                eligible,
                default=None,
                key=lambda plane: sum(
                    value * value
                    for value in offset_nautical_miles(
                        plane.latitude,
                        plane.longitude,
                        self._config.home_latitude,
                        self._config.home_longitude,
                    )
                ),
            )
            missing = (
                [closest]
                if closest is not None
                and (
                    closest.callsign not in self._routes
                    or self._routes[closest.callsign][1] <= now
                )
                else []
            )
        if not missing:
            return
        try:
            found = self._client.routes_for(missing)
        except Exception as error:
            logger.warning("Flight route lookup failed: %s", error)
            return
        logger.info(
            "Flight radar received routes for %d of %d aircraft",
            len(found),
            len(missing),
        )
        with self._data_lock:
            for plane in missing:
                callsign = plane.callsign
                if callsign is None:
                    continue
                route = found.get(callsign)
                if route is not None and route.plausible is not True:
                    route = None
                ttl = self.route_ttl_seconds if route else self.missing_route_ttl_seconds
                self._routes[callsign] = (route, now + ttl)

    def _extrapolate(self, plane: Aircraft, elapsed: float) -> tuple[float, float]:
        if plane.ground_speed_knots is None or plane.track_degrees is None:
            return plane.latitude, plane.longitude
        seconds = min(30.0, max(0.0, elapsed))
        distance_nm = plane.ground_speed_knots * seconds / 3600.0
        heading = radians(plane.track_degrees)
        north = distance_nm * cos(heading)
        east = distance_nm * sin(heading)
        latitude = plane.latitude + north / 60.0
        longitude_scale = 60.0 * cos(radians(self._config.home_latitude))
        longitude = plane.longitude + east / longitude_scale
        return latitude, longitude

    def _draw_ticker(self, frame: np.ndarray, label: str) -> None:
        if label != self._last_label:
            self._scroll_offset = 0
        self._last_label = label
        canvas = Image.new("RGB", (self.width, self.ticker_height), "black")
        draw = ImageDraw.Draw(canvas)
        text_width = int(draw.textlength(label, font=self._font))
        self._ticker_scrolls = text_width > self.width
        if self._ticker_scrolls:
            cycle_width = text_width + 8
            x = -(self._scroll_offset % cycle_width)
            draw.text(
                (x, -1), label, fill=self.featured_aircraft_color, font=self._font
            )
            draw.text(
                (x + cycle_width, -1),
                label,
                fill=self.featured_aircraft_color,
                font=self._font,
            )
        else:
            x = (self.width - text_width) // 2
            draw.text(
                (x, -1), label, fill=self.featured_aircraft_color, font=self._font
            )
        # Avoid Pillow's Image.__array_interface__, which goes through
        # Image.tobytes() and unnecessarily requires the optional ImageFile
        # module on the minimal Raspberry Pi installation.
        pixels = np.asarray(list(canvas.get_flattened_data()), dtype=np.uint8)
        frame[-self.ticker_height :] = pixels.reshape(
            self.ticker_height, self.width, 3
        )
