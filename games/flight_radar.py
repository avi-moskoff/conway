import logging
import random
from math import cos, radians, sin
from threading import Event, Lock, Thread
from time import monotonic
from time import time as wall_clock_time

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from air_traffic import AdsbLolClient, Aircraft, FlightRoute, RateLimitedError
from air_traffic.projection import (
    clip_segment_to_radius,
    nearest_point_on_polyline,
    offset_nautical_miles,
    project_offset,
    project_position,
)
from config import FlightRadarConfig
from games.base import Game
from transit import (
    DIRECTION_BY_ROUTE_AND_ID,
    LINE_GEOMETRY,
    StopArrival,
    Train,
    ValleyMetroClient,
    nearest_station_stop_id,
)

logger = logging.getLogger(__name__)


class FlightRadarGame(Game):
    """North-up view of live aircraft near the configured location."""

    frame_delay_seconds = 0.1
    ticker_height = 12
    maximum_position_age_seconds = 60.0
    rail_maximum_position_age_seconds = 90.0
    rail_extrapolation_cap_seconds = 20.0
    max_train_speed_nm_per_second = 0.015  # ~62mph, well above the ~40mph top speed
    stale_snapshot_seconds = 60.0
    display_modes = ("aircraft", "westbound_eta", "eastbound_eta")
    route_ttl_seconds = 6 * 60 * 60
    missing_route_ttl_seconds = 15 * 60
    failed_route_ttl_seconds = 5 * 60
    # Aircraft mode and rail modes never draw at the same time (see frame),
    # so within a mode there's only ever a handful of categories that need
    # to be distinct from each other, not from every color in the whole app.
    featured_aircraft_color = (255, 0, 0)
    airport_color = (255, 0, 0)
    home_color = (255, 0, 0)
    error_color = (255, 0, 0)
    other_aircraft_color = (255, 255, 255)
    eastbound_train_color = (0, 255, 0)
    westbound_train_color = (255, 230, 0)
    rail_line_color = (0, 0, 255)
    ticker_text_color = (255, 255, 255)

    def __init__(
        self,
        height: int,
        width: int,
        config: FlightRadarConfig,
        client: AdsbLolClient | None = None,
        rail_client: ValleyMetroClient | None = None,
    ) -> None:
        super().__init__(height, width)
        self._config = config
        self._client = client or AdsbLolClient(
            config.api_url, api_key=config.api_key
        )
        self._rail_client = rail_client or ValleyMetroClient(
            config.rail_api_url, config.rail_trip_updates_url, config.rail_api_key
        )
        self._eastbound_home_stop_id = nearest_station_stop_id(
            config.home_latitude, config.home_longitude, 0
        )
        self._westbound_home_stop_id = nearest_station_stop_id(
            config.home_latitude, config.home_longitude, 1
        )
        self._data_lock = Lock()
        self._active_event = Event()
        self._wake_event = Event()
        self._rail_wake_event = Event()
        self._stop_event = Event()
        self._worker: Thread | None = None
        self._rail_worker: Thread | None = None
        self._aircraft: tuple[Aircraft, ...] = ()
        self._routes: dict[str, tuple[FlightRoute | None, float]] = {}
        self._snapshot_time: float | None = None
        self._has_error = False
        self._trains: tuple[Train, ...] = ()
        self._train_velocities: dict[str, tuple[float, float]] = {}
        self._train_snapshot_time: float | None = None
        self._arrivals: tuple[StopArrival, ...] = ()
        self._has_rail_error = False
        self._last_label = ""
        self._scroll_offset = 0
        self._ticker_scrolls = False
        self._display_mode_index = 0
        self._font = ImageFont.load_default(size=12)

    def activate(self) -> None:
        if self._worker is None:
            self._worker = Thread(
                target=self._poll_loop, name="flight-radar-poller", daemon=True
            )
            self._worker.start()
        if self._rail_worker is None:
            self._rail_worker = Thread(
                target=self._rail_poll_loop,
                name="flight-radar-rail-poller",
                daemon=True,
            )
            self._rail_worker.start()
        self._active_event.set()
        self._wake_event.set()
        self._rail_wake_event.set()
        logger.info("Flight radar polling activated")

    def deactivate(self) -> None:
        self._active_event.clear()
        self._wake_event.set()
        self._rail_wake_event.set()
        logger.info("Flight radar polling paused")

    def close(self) -> None:
        self._stop_event.set()
        self._active_event.set()
        self._wake_event.set()
        self._rail_wake_event.set()
        if self._worker is not None:
            self._worker.join(timeout=11.0)
        if self._rail_worker is not None:
            self._rail_worker.join(timeout=11.0)
        logger.info("Flight radar polling stopped")

    def reset(self) -> None:
        self._display_mode_index = (self._display_mode_index + 1) % len(
            self.display_modes
        )
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
            trains = self._trains
            train_velocities = self._train_velocities
            train_snapshot_time = self._train_snapshot_time
            arrivals = self._arrivals
            has_rail_error = self._has_rail_error

        stale = snapshot_time is None or now - snapshot_time > self.stale_snapshot_seconds
        rail_stale = (
            train_snapshot_time is None
            or now - train_snapshot_time > self.stale_snapshot_seconds
        )
        mode = self.display_modes[self._display_mode_index]

        radar_height = self.height - self.ticker_height - 1
        frame = np.zeros((self.height, self.width, 3), dtype=np.uint8)
        center_x, center_y = self.width // 2, radar_height // 2

        arrival_selection: StopArrival | None = None
        matched_train: Train | None = None
        if mode != "aircraft" and not rail_stale:
            direction = "west" if mode == "westbound_eta" else "east"
            arrival_selection = self._next_arrival(arrivals, direction)
            if arrival_selection is not None:
                matched_train = next(
                    (t for t in trains if t.trip_id == arrival_selection.trip_id), None
                )
        highlighted_vehicle_id = (
            matched_train.vehicle_id if matched_train is not None else None
        )

        # Aircraft and rail traffic are never drawn together - keeping each
        # mode to its own set of colors means nothing needs to be distinct
        # from a category that isn't even on screen. Home is drawn after the
        # line/airport (home is often right on the A Line, and the line's
        # mask-based fill would otherwise paint over it) but before trains,
        # so a train can still cover it if exactly coincident.
        if mode == "aircraft":
            self._draw_airport(frame, radar_height)
            frame[center_y, center_x] = self.home_color
        else:
            self._draw_rail_lines(frame, radar_height)
            frame[center_y, center_x] = self.home_color
            self._draw_trains(
                frame,
                radar_height,
                trains,
                train_velocities,
                train_snapshot_time,
                now,
                highlighted_vehicle_id,
            )

        visible: list[tuple[float, Aircraft, tuple[int, int]]] = []
        if mode == "aircraft" and not stale:
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

        letter_color = None
        if mode == "aircraft":
            if stale:
                label = "NO SIGNAL"
            elif featured is None:
                label = "CLEAR SKY"
            else:
                plane = featured[1]
                cached = routes.get(plane.callsign or "")
                route_label = cached[0].label if cached and cached[0] else None
                label = f"{plane.label} {route_label}" if route_label else plane.label
        else:
            direction_letter = "W" if mode == "westbound_eta" else "E"
            if rail_stale:
                label = "NO RAIL"
            else:
                label = self._train_eta_label(arrival_selection, direction_letter)
                letter_color = (
                    self.westbound_train_color
                    if mode == "westbound_eta"
                    else self.eastbound_train_color
                )

        if (has_error or has_rail_error) and not stale:
            frame[0, 0] = self.error_color
        self._draw_ticker(frame, label, letter_color)
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

    def _draw_rail_lines(self, frame: np.ndarray, radar_height: int) -> None:
        radius_nm = self._config.radius_nm
        # Home is rarely exactly on a track's latitude/longitude, so the
        # visible radius (a circle in real-world terms) doesn't reach the
        # rectangular frame's corners - clipping tracks to the true radius
        # can cut a line off well short of the edge. Clip to a wider radius
        # instead (a corner is at most radius_nm * sqrt(2) away) and keep
        # projecting at the real radius_nm, so project_offset's existing
        # clamp pins the line at the frame edge rather than mid-frame. Trains
        # and everything else still only render within the true radius.
        clip_radius_nm = radius_nm * 1.5
        canvas = Image.new("1", (self.width, radar_height), 0)
        draw = ImageDraw.Draw(canvas)
        drawn = False
        for points in LINE_GEOMETRY.values():
            offsets = [
                offset_nautical_miles(
                    latitude,
                    longitude,
                    self._config.home_latitude,
                    self._config.home_longitude,
                )
                for latitude, longitude in points
            ]
            for (east1, north1), (east2, north2) in zip(offsets, offsets[1:]):
                clipped = clip_segment_to_radius(
                    east1, north1, east2, north2, clip_radius_nm
                )
                if clipped is None:
                    continue
                ce1, cn1, ce2, cn2 = clipped
                start = project_offset(ce1, cn1, radius_nm, self.width, radar_height)
                end = project_offset(ce2, cn2, radius_nm, self.width, radar_height)
                draw.line([start, end], fill=1)
                drawn = True
        if not drawn:
            return
        mask = np.asarray(list(canvas.get_flattened_data()), dtype=np.uint8)
        mask = mask.reshape(radar_height, self.width) != 0
        frame[:radar_height][mask] = self.rail_line_color

    def _draw_trains(
        self,
        frame: np.ndarray,
        radar_height: int,
        trains: tuple[Train, ...],
        velocities: dict[str, tuple[float, float]],
        snapshot_time: float | None,
        now: float,
        highlighted_vehicle_id: str | None = None,
    ) -> None:
        if snapshot_time is None or now - snapshot_time > self.stale_snapshot_seconds:
            return
        elapsed = now - snapshot_time
        radius_nm = self._config.radius_nm
        line_offsets = {
            route_id: [
                offset_nautical_miles(
                    latitude,
                    longitude,
                    self._config.home_latitude,
                    self._config.home_longitude,
                )
                for latitude, longitude in points
            ]
            for route_id, points in LINE_GEOMETRY.items()
        }
        for train in trains:
            if train.seen_seconds + elapsed > self.rail_maximum_position_age_seconds:
                continue
            direction = DIRECTION_BY_ROUTE_AND_ID.get(train.route_id, {}).get(
                train.direction_id
            )
            if direction is None:
                continue
            east, north = offset_nautical_miles(
                train.latitude,
                train.longitude,
                self._config.home_latitude,
                self._config.home_longitude,
            )
            # Extrapolate from how old this specific fix actually is (age at
            # fetch time plus time since we fetched it), not from our poll
            # cadence. A fix that's been sitting unchanged across several
            # polls still ages continuously this way instead of freezing and
            # then jumping once a genuinely new fix finally arrives. Capped
            # so a long gap without a new fix can't extrapolate indefinitely.
            fix_age = min(
                self.rail_extrapolation_cap_seconds, train.seen_seconds + elapsed
            )
            east_speed, north_speed = velocities.get(train.vehicle_id, (0.0, 0.0))
            east += east_speed * fix_age
            north += north_speed * fix_age
            if east * east + north * north > radius_nm * radius_nm:
                continue
            offsets = line_offsets.get(train.route_id)
            if offsets:
                # Live GPS positions rarely land exactly on our simplified
                # track geometry; snapping keeps trains visually on the line.
                east, north = nearest_point_on_polyline(east, north, offsets)
            x, y = project_offset(east, north, radius_nm, self.width, radar_height)
            if train.vehicle_id == highlighted_vehicle_id:
                frame[y, x] = self.featured_aircraft_color
            else:
                frame[y, x] = (
                    self.eastbound_train_color
                    if direction == "east"
                    else self.westbound_train_color
                )

    def _next_arrival(
        self, arrivals: tuple[StopArrival, ...], direction: str
    ) -> StopArrival | None:
        """Pick the soonest not-yet-arrived StopArrival at home's A Line platform.

        This is Valley Metro's own predicted arrival time for that specific
        stop (schedule plus live delay), not something we derive from
        position or speed - so a train stopped at a station doesn't produce
        a misleadingly large ETA the way distance/speed extrapolation would.
        """
        stop_id = (
            self._eastbound_home_stop_id
            if direction == "east"
            else self._westbound_home_stop_id
        )
        if stop_id is None:
            return None
        now = wall_clock_time()
        candidates = [
            arrival
            for arrival in arrivals
            if arrival.stop_id == stop_id and arrival.arrival_epoch >= now
        ]
        return min(candidates, default=None, key=lambda arrival: arrival.arrival_epoch)

    def _train_eta_label(
        self, arrival: StopArrival | None, direction_letter: str
    ) -> str:
        if arrival is None:
            return f"{direction_letter} ETA --"
        eta_seconds = max(0.0, arrival.arrival_epoch - wall_clock_time())
        if eta_seconds < 60:
            return f"{direction_letter} ETA <1M"
        return f"{direction_letter} ETA {round(eta_seconds / 60)}M"

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
                logger.debug("Flight radar received %d aircraft", len(aircraft))
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

    def _rail_poll_loop(self) -> None:
        failures = 0
        while not self._stop_event.is_set():
            if not self._active_event.is_set():
                self._rail_wake_event.wait()
                self._rail_wake_event.clear()
                continue
            try:
                trains = self._rail_client.active_trains(LINE_GEOMETRY)
                home_stop_ids = {
                    stop_id
                    for stop_id in (
                        self._eastbound_home_stop_id,
                        self._westbound_home_stop_id,
                    )
                    if stop_id is not None
                }
                arrivals = self._rail_client.arrivals_for_stops(home_stop_ids)
                poll_time = monotonic()
                with self._data_lock:
                    self._train_velocities = self._estimate_velocities(trains, poll_time)
                    self._trains = trains
                    self._train_snapshot_time = poll_time
                    self._arrivals = arrivals
                    self._has_rail_error = False
                logger.debug(
                    "Valley Metro poll received %d trains, %d arrivals",
                    len(trains),
                    len(arrivals),
                )
                failures = 0
                wait_seconds = self._config.rail_poll_seconds
            except Exception as error:
                failures += 1
                self._mark_rail_error()
                logger.warning("Valley Metro poll failed: %s", error)
                exponential = self._config.rail_poll_seconds * (2 ** min(failures, 5))
                wait_seconds = min(5 * 60.0, exponential) * random.uniform(0.8, 1.2)
            self._rail_wake_event.wait(wait_seconds)
            self._rail_wake_event.clear()

    def _mark_rail_error(self) -> None:
        with self._data_lock:
            self._has_rail_error = True

    def _estimate_velocities(
        self, new_trains: tuple[Train, ...], poll_time: float
    ) -> dict[str, tuple[float, float]]:
        """Derive per-train velocity from consecutive GPS fixes.

        Must be called with _data_lock held and before self._trains /
        self._train_snapshot_time are overwritten with new_trains / poll_time,
        since it diffs against that previous snapshot. Valley Metro's feed
        doesn't report speed, so this is the only source of motion we have.

        The underlying feed only actually refreshes a given vehicle's fix
        every ~15-20s, so plenty of polls see the exact same fix repeated.
        When that happens we keep the previously estimated velocity rather
        than dropping it - otherwise a vehicle would visibly freeze on every
        poll that didn't happen to catch a new fix, then jump once one
        finally arrived. Vehicles no longer present are pruned.
        """
        previous_by_id = {train.vehicle_id: train for train in self._trains}
        previous_poll_time = self._train_snapshot_time
        current_ids = {train.vehicle_id for train in new_trains}
        velocities: dict[str, tuple[float, float]] = {
            vehicle_id: velocity
            for vehicle_id, velocity in self._train_velocities.items()
            if vehicle_id in current_ids
        }
        if previous_poll_time is None:
            return velocities
        for train in new_trains:
            previous = previous_by_id.get(train.vehicle_id)
            if previous is None:
                continue
            old_fix_age = previous.seen_seconds + (poll_time - previous_poll_time)
            time_between_fixes = old_fix_age - train.seen_seconds
            if time_between_fixes < 1.0:
                continue
            new_east, new_north = offset_nautical_miles(
                train.latitude,
                train.longitude,
                self._config.home_latitude,
                self._config.home_longitude,
            )
            old_east, old_north = offset_nautical_miles(
                previous.latitude,
                previous.longitude,
                self._config.home_latitude,
                self._config.home_longitude,
            )
            east_speed = (new_east - old_east) / time_between_fixes
            north_speed = (new_north - old_north) / time_between_fixes
            if (east_speed**2 + north_speed**2) > self.max_train_speed_nm_per_second**2:
                continue
            velocities[train.vehicle_id] = (east_speed, north_speed)
        return velocities

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
        except RateLimitedError as error:
            retry_after = error.retry_after_seconds or self.failed_route_ttl_seconds
            self._cache_route_failure(missing, now + retry_after)
            logger.warning(
                "Flight route lookup rate limited; retrying in %.0f seconds",
                retry_after,
            )
            return
        except Exception as error:
            self._cache_route_failure(
                missing, now + self.failed_route_ttl_seconds
            )
            logger.warning(
                "Flight route lookup failed: %s; retrying in %.0f seconds",
                error,
                self.failed_route_ttl_seconds,
            )
            return
        logger.debug(
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

    def _cache_route_failure(
        self, aircraft: list[Aircraft], expires_at: float
    ) -> None:
        with self._data_lock:
            for plane in aircraft:
                if plane.callsign:
                    self._routes[plane.callsign] = (None, expires_at)

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

    def _draw_ticker(
        self,
        frame: np.ndarray,
        label: str,
        letter_color: tuple[int, int, int] | None = None,
    ) -> None:
        if label != self._last_label:
            self._scroll_offset = 0
        self._last_label = label
        canvas = Image.new("1", (self.width, self.ticker_height), 0)
        draw = ImageDraw.Draw(canvas)
        text_width = int(draw.textlength(label, font=self._font))
        self._ticker_scrolls = text_width > self.width

        # letter_color acts as a direction legend: the first character (e.g.
        # "W"/"E") is drawn on its own canvas so it can be colored to match
        # that direction's train color, while the rest stays the usual color.
        letter_canvas = None
        letter_draw = None
        if letter_color is not None and label:
            letter_canvas = Image.new("1", (self.width, self.ticker_height), 0)
            letter_draw = ImageDraw.Draw(letter_canvas)

        def draw_label(x: float) -> None:
            if letter_draw is not None:
                letter, rest = label[0], label[1:]
                letter_draw.text((x, -1), letter, fill=1, font=self._font)
                letter_width = draw.textlength(letter, font=self._font)
                draw.text((x + letter_width, -1), rest, fill=1, font=self._font)
            else:
                draw.text((x, -1), label, fill=1, font=self._font)

        if self._ticker_scrolls:
            cycle_width = text_width + 8
            x = -(self._scroll_offset % cycle_width)
            draw_label(x)
            draw_label(x + cycle_width)
        else:
            x = (self.width - text_width) // 2
            draw_label(x)
        # Avoid Pillow's Image.__array_interface__, which goes through
        # Image.tobytes() and unnecessarily requires the optional ImageFile
        # module on the minimal Raspberry Pi installation.
        mask = np.asarray(list(canvas.get_flattened_data()), dtype=np.uint8)
        mask = mask.reshape(self.ticker_height, self.width) != 0
        ticker = frame[-self.ticker_height :]
        ticker[:] = 0
        ticker[mask] = self.ticker_text_color
        if letter_canvas is not None:
            letter_mask = np.asarray(
                list(letter_canvas.get_flattened_data()), dtype=np.uint8
            )
            letter_mask = letter_mask.reshape(self.ticker_height, self.width) != 0
            ticker[letter_mask] = letter_color
