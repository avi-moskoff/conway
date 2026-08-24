import logging
from datetime import datetime
from threading import Event, Lock, Thread
from time import monotonic

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from air_traffic.projection import (
    offset_nautical_miles,
    offset_to_latlon,
    pixel_to_offset,
    project_position,
)
from config import WeatherRadarConfig
from games.base import Game
from weather import (
    AirQualitySample,
    GoesDustClient,
    OpenMeteoClient,
    WeatherSample,
    sector_pixel_for,
)

logger = logging.getLogger(__name__)


class WeatherRadarGame(Game):
    """North-up map of weather conditions / air quality near the configured location."""

    # Nothing else about this game changes between polls (no extrapolated
    # motion like flight radar's aircraft), but the ticker still needs a
    # fast tick to scroll smoothly - match flight radar's cadence rather
    # than a slower delay that would make long labels crawl.
    frame_delay_seconds = 0.1
    ticker_height = 12
    stale_snapshot_seconds = 1800.0
    display_modes = ("conditions", "aqi", "dust")
    grid_size = 5

    home_color = (255, 0, 255)
    landmark_color = (90, 90, 90)
    error_color = (255, 0, 0)
    ticker_text_color = (255, 255, 255)

    precipitation_cap_mm = 4.0
    precipitation_stops_t = (0.0, precipitation_cap_mm / 2, precipitation_cap_mm)
    precipitation_stops_rgb = ((0, 0, 0), (0, 80, 255), (255, 255, 255))

    # EPA US AQI category breakpoints, used as gradient anchors so the
    # field shades smoothly between categories rather than banding hard.
    aqi_stops_t = (0.0, 50.0, 100.0, 150.0, 200.0, 300.0, 500.0)
    aqi_stops_rgb = (
        (0, 228, 0),
        (255, 255, 0),
        (255, 126, 0),
        (255, 0, 0),
        (143, 63, 151),
        (126, 0, 35),
        (126, 0, 35),
    )

    weather_code_labels = {
        0: "CLEAR",
        1: "CLEAR",
        2: "CLOUDY",
        3: "CLOUDY",
        45: "FOG",
        48: "FOG",
        51: "DRIZZLE",
        53: "DRIZZLE",
        55: "DRIZZLE",
        56: "DRIZZLE",
        57: "DRIZZLE",
        61: "RAIN",
        63: "RAIN",
        65: "RAIN",
        66: "RAIN",
        67: "RAIN",
        71: "SNOW",
        73: "SNOW",
        75: "SNOW",
        77: "SNOW",
        80: "SHOWERS",
        81: "SHOWERS",
        82: "SHOWERS",
        85: "SNOW",
        86: "SNOW",
        95: "STORM",
        96: "STORM",
        99: "STORM",
    }

    def __init__(
        self,
        height: int,
        width: int,
        config: WeatherRadarConfig,
        client: OpenMeteoClient | None = None,
        dust_client: GoesDustClient | None = None,
    ) -> None:
        super().__init__(height, width)
        self._config = config
        self._client = client or OpenMeteoClient()
        self._dust_client = dust_client or GoesDustClient(satellite=config.dust_satellite)
        self._radar_height = height - self.ticker_height - 1

        self._data_lock = Lock()
        self._active_event = Event()
        self._wake_event = Event()
        self._dust_wake_event = Event()
        self._stop_event = Event()
        self._worker: Thread | None = None
        self._dust_worker: Thread | None = None

        self._conditions_field: np.ndarray | None = None
        self._conditions_snapshot_time: float | None = None
        self._has_conditions_error = False
        self._home_weather_sample: WeatherSample | None = None

        self._aqi_field: np.ndarray | None = None
        self._aqi_snapshot_time: float | None = None
        self._has_aqi_error = False
        self._home_aqi_sample: AirQualitySample | None = None

        self._dust_field: np.ndarray | None = None
        self._dust_snapshot_time: float | None = None
        self._has_dust_error = False
        self._dust_frame_time: datetime | None = None

        self._display_mode_index = 0
        self._last_label = ""
        self._scroll_offset = 0
        self._ticker_scrolls = False
        self._font = ImageFont.load_default(size=12)

        max_east, max_north = pixel_to_offset(
            self.width - 1, 0, config.radius_nm, self.width, self._radar_height
        )
        self._query_points = self._build_query_points(max_east, max_north)
        self._pixel_east, self._pixel_north = self._build_pixel_grid(config.radius_nm)
        self._landmark_pixels = self._build_landmark_pixels(config.radius_nm)

        dust_pixel_east, dust_pixel_north = self._build_pixel_grid(config.dust_radius_nm)
        self._dust_landmark_pixels = self._build_landmark_pixels(config.dust_radius_nm)
        self._dust_sector_x, self._dust_sector_y = self._build_dust_sector_pixels(
            dust_pixel_east, dust_pixel_north
        )

    def _build_query_points(
        self, max_east: float, max_north: float
    ) -> tuple[tuple[float, float], ...]:
        east_steps = np.linspace(-max_east, max_east, self.grid_size)
        north_steps = np.linspace(-max_north, max_north, self.grid_size)
        return tuple(
            offset_to_latlon(
                float(east),
                float(north),
                self._config.home_latitude,
                self._config.home_longitude,
            )
            for north in north_steps
            for east in east_steps
        )

    def _build_pixel_grid(self, radius_nm: float) -> tuple[np.ndarray, np.ndarray]:
        grid_x, grid_y = np.meshgrid(np.arange(self.width), np.arange(self._radar_height))
        vectorized = np.vectorize(pixel_to_offset, otypes=[float, float])
        return vectorized(grid_x, grid_y, radius_nm, self.width, self._radar_height)

    def _build_landmark_pixels(self, radius_nm: float) -> tuple[tuple[int, int], ...]:
        points = (
            project_position(
                latitude,
                longitude,
                self._config.home_latitude,
                self._config.home_longitude,
                radius_nm,
                self.width,
                self._radar_height,
            )
            for _name, latitude, longitude in self._config.landmarks
        )
        return tuple(point for point in points if point is not None)

    def _build_dust_sector_pixels(
        self, pixel_east: np.ndarray, pixel_north: np.ndarray
    ) -> tuple[np.ndarray, np.ndarray]:
        """Precompute, once, which NOAA sector-image pixel each display pixel samples.

        Static for the life of the game (depends only on home location and
        dust_radius_nm, both fixed), so this runs once here rather than
        once per dust poll.
        """
        vectorized_latlon = np.vectorize(offset_to_latlon, otypes=[float, float])
        latitude, longitude = vectorized_latlon(
            pixel_east, pixel_north, self._config.home_latitude, self._config.home_longitude
        )
        vectorized_sector = np.vectorize(sector_pixel_for, otypes=[float, float])
        return vectorized_sector(latitude, longitude)

    def activate(self) -> None:
        if self._worker is None:
            self._worker = Thread(
                target=self._poll_loop, name="weather-radar-poller", daemon=True
            )
            self._worker.start()
        if self._dust_worker is None:
            self._dust_worker = Thread(
                target=self._dust_poll_loop, name="weather-radar-dust-poller", daemon=True
            )
            self._dust_worker.start()
        self._active_event.set()
        self._wake_event.set()
        self._dust_wake_event.set()
        logger.info("Weather radar polling activated")

    def deactivate(self) -> None:
        self._active_event.clear()
        self._wake_event.set()
        self._dust_wake_event.set()
        logger.info("Weather radar polling paused")

    def close(self) -> None:
        self._stop_event.set()
        self._active_event.set()
        self._wake_event.set()
        self._dust_wake_event.set()
        if self._worker is not None:
            self._worker.join(timeout=11.0)
        if self._dust_worker is not None:
            self._dust_worker.join(timeout=11.0)
        logger.info("Weather radar polling stopped")

    def reset(self) -> None:
        self._display_mode_index = (self._display_mode_index + 1) % len(
            self.display_modes
        )
        self._scroll_offset = 0
        # Data is already fetched and cached continuously regardless of
        # which mode is displayed, so this isn't required for switching -
        # but nudging the poller for the mode just switched into gives the
        # button a useful second job: force an immediate retry there rather
        # than waiting out a backoff after a transient failure. Only that
        # one poller, not both - no reason to hit the AQI/conditions API
        # when switching into dust mode, or vice versa.
        mode = self.display_modes[self._display_mode_index]
        if mode == "dust":
            self._dust_wake_event.set()
        else:
            self._wake_event.set()

    def advance(self) -> None:
        if self._ticker_scrolls:
            self._scroll_offset += 1

    @property
    def frame(self) -> np.ndarray:
        now = monotonic()
        with self._data_lock:
            mode = self.display_modes[self._display_mode_index]
            conditions_field = self._conditions_field
            conditions_snapshot_time = self._conditions_snapshot_time
            has_conditions_error = self._has_conditions_error
            home_weather_sample = self._home_weather_sample
            aqi_field = self._aqi_field
            aqi_snapshot_time = self._aqi_snapshot_time
            has_aqi_error = self._has_aqi_error
            home_aqi_sample = self._home_aqi_sample
            dust_field = self._dust_field
            dust_snapshot_time = self._dust_snapshot_time
            has_dust_error = self._has_dust_error
            dust_frame_time = self._dust_frame_time

        frame = np.zeros((self.height, self.width, 3), dtype=np.uint8)

        if mode == "conditions":
            stale = self._is_stale(conditions_snapshot_time, now)
            if not stale and conditions_field is not None:
                frame[: self._radar_height] = conditions_field
            label = (
                "NO SIGNAL" if stale else self._conditions_label(home_weather_sample)
            )
            show_error = has_conditions_error and not stale
            landmark_pixels = self._landmark_pixels
        elif mode == "aqi":
            stale = self._is_stale(aqi_snapshot_time, now)
            if not stale and aqi_field is not None:
                frame[: self._radar_height] = aqi_field
            label = "NO SIGNAL" if stale else self._aqi_label(home_aqi_sample)
            show_error = has_aqi_error and not stale
            landmark_pixels = self._landmark_pixels
        else:
            stale = self._is_stale(dust_snapshot_time, now)
            if not stale and dust_field is not None:
                frame[: self._radar_height] = dust_field
            label = "NO SIGNAL" if stale else self._dust_label(dust_frame_time)
            show_error = has_dust_error and not stale
            landmark_pixels = self._dust_landmark_pixels

        for x, y in landmark_pixels:
            frame[y, x] = self.landmark_color
        center_x, center_y = self.width // 2, self._radar_height // 2
        frame[center_y, center_x] = self.home_color
        if show_error:
            frame[0, 0] = self.error_color
        self._draw_ticker(frame, label)
        return frame

    def _is_stale(self, snapshot_time: float | None, now: float) -> bool:
        return snapshot_time is None or now - snapshot_time > self.stale_snapshot_seconds

    def _conditions_label(self, sample: WeatherSample | None) -> str:
        if sample is None:
            return "NO SIGNAL"
        condition = self.weather_code_labels.get(sample.weather_code, "UNKNOWN")
        return f"{round(sample.temperature_f)}F {condition}"

    def _aqi_label(self, sample: AirQualitySample | None) -> str:
        if sample is None:
            return "NO SIGNAL"
        return f"AQI {round(sample.us_aqi)} {self._aqi_category(sample.us_aqi)}"

    def _dust_label(self, frame_time: datetime | None) -> str:
        if frame_time is None:
            return "NO SIGNAL"
        return f"DUST {frame_time:%H:%M}Z"

    @staticmethod
    def _aqi_category(value: float) -> str:
        if value <= 50:
            return "GOOD"
        if value <= 100:
            return "MODERATE"
        if value <= 150:
            return "USG"
        if value <= 200:
            return "UNHEALTHY"
        if value <= 300:
            return "V UNHEALTHY"
        return "HAZARDOUS"

    def _poll_loop(self) -> None:
        failures = 0
        while not self._stop_event.is_set():
            if not self._active_event.is_set():
                self._wake_event.wait()
                self._wake_event.clear()
                continue
            had_error = False
            try:
                samples = self._client.weather_for(self._query_points)
                if not samples:
                    raise RuntimeError("no weather samples returned")
                self._store_conditions(samples)
            except Exception as error:
                had_error = True
                with self._data_lock:
                    self._has_conditions_error = True
                logger.warning("Weather radar conditions poll failed: %s", error)
            try:
                samples = self._client.air_quality_for(self._query_points)
                if not samples:
                    raise RuntimeError("no air quality samples returned")
                self._store_aqi(samples)
            except Exception as error:
                had_error = True
                with self._data_lock:
                    self._has_aqi_error = True
                logger.warning("Weather radar AQI poll failed: %s", error)
            failures = failures + 1 if had_error else 0
            wait_seconds = (
                self._exponential_backoff_seconds(failures, self._config.poll_seconds)
                if had_error
                else self._config.poll_seconds
            )
            self._wake_event.wait(wait_seconds)
            self._wake_event.clear()

    @staticmethod
    def _exponential_backoff_seconds(failures: int, base_poll_seconds: float) -> float:
        # Starts small regardless of the steady-state poll interval (which
        # for this game runs 5-10 minutes) so a transient failure recovers
        # in seconds rather than waiting out the full normal cadence, then
        # ramps up toward it rather than retrying forever at high frequency.
        retry_start_seconds = 15.0
        ceiling = min(5 * 60.0, base_poll_seconds)
        return min(ceiling, retry_start_seconds * (2 ** min(failures, 6)))

    def _dust_poll_loop(self) -> None:
        failures = 0
        while not self._stop_event.is_set():
            if not self._active_event.is_set():
                self._dust_wake_event.wait()
                self._dust_wake_event.clear()
                continue
            try:
                result = self._dust_client.latest_frame()
                if result is None:
                    raise RuntimeError("no dust frame available")
                sector_array, frame_time = result
                self._store_dust(sector_array, frame_time)
                failures = 0
                wait_seconds = self._config.dust_poll_seconds
            except Exception as error:
                failures += 1
                with self._data_lock:
                    self._has_dust_error = True
                logger.warning("Weather radar dust poll failed: %s", error)
                wait_seconds = self._exponential_backoff_seconds(
                    failures, self._config.dust_poll_seconds
                )
            self._dust_wake_event.wait(wait_seconds)
            self._dust_wake_event.clear()

    def _store_dust(self, sector_array: np.ndarray, frame_time: datetime) -> None:
        size = sector_array.shape[0]
        x = np.clip(np.rint(self._dust_sector_x).astype(int), 0, size - 1)
        y = np.clip(np.rint(self._dust_sector_y).astype(int), 0, size - 1)
        field = sector_array[y, x]
        with self._data_lock:
            self._dust_field = field
            self._dust_snapshot_time = monotonic()
            self._dust_frame_time = frame_time
            self._has_dust_error = False

    def _store_conditions(self, samples: tuple[WeatherSample, ...]) -> None:
        easts, norths = self._offsets_for_samples(samples)
        values = np.array([sample.precipitation_mm for sample in samples])
        field = self._colorize_field(
            self._idw(easts, norths, values),
            self.precipitation_stops_t,
            self.precipitation_stops_rgb,
        )
        closest = samples[int(np.argmin(easts * easts + norths * norths))]
        with self._data_lock:
            self._conditions_field = field
            self._conditions_snapshot_time = monotonic()
            self._home_weather_sample = closest
            self._has_conditions_error = False

    def _store_aqi(self, samples: tuple[AirQualitySample, ...]) -> None:
        easts, norths = self._offsets_for_samples(samples)
        values = np.array([sample.us_aqi for sample in samples])
        field = self._colorize_field(
            self._idw(easts, norths, values), self.aqi_stops_t, self.aqi_stops_rgb
        )
        closest = samples[int(np.argmin(easts * easts + norths * norths))]
        with self._data_lock:
            self._aqi_field = field
            self._aqi_snapshot_time = monotonic()
            self._home_aqi_sample = closest
            self._has_aqi_error = False

    def _offsets_for_samples(self, samples) -> tuple[np.ndarray, np.ndarray]:
        home_latitude = self._config.home_latitude
        home_longitude = self._config.home_longitude
        offsets = [
            offset_nautical_miles(
                sample.latitude, sample.longitude, home_latitude, home_longitude
            )
            for sample in samples
        ]
        easts = np.array([east for east, _north in offsets])
        norths = np.array([north for _east, north in offsets])
        return easts, norths

    def _idw(
        self, sample_east: np.ndarray, sample_north: np.ndarray, values: np.ndarray
    ) -> np.ndarray:
        diff_east = self._pixel_east[..., np.newaxis] - sample_east
        diff_north = self._pixel_north[..., np.newaxis] - sample_north
        distance_sq = diff_east * diff_east + diff_north * diff_north
        weights = 1.0 / (distance_sq + 1e-6)
        return np.sum(weights * values, axis=-1) / np.sum(weights, axis=-1)

    @staticmethod
    def _colorize_field(
        field: np.ndarray,
        stops_t: tuple[float, ...],
        stops_rgb: tuple[tuple[int, int, int], ...],
    ) -> np.ndarray:
        channels = [
            np.interp(field, stops_t, [color[channel] for color in stops_rgb])
            for channel in range(3)
        ]
        return np.stack(channels, axis=-1).astype(np.uint8)

    def _draw_ticker(self, frame: np.ndarray, label: str) -> None:
        if label != self._last_label:
            self._scroll_offset = 0
        self._last_label = label
        canvas = Image.new("1", (self.width, self.ticker_height), 0)
        draw = ImageDraw.Draw(canvas)
        text_width = int(draw.textlength(label, font=self._font))
        self._ticker_scrolls = text_width > self.width

        if self._ticker_scrolls:
            cycle_width = text_width + 8
            x = -(self._scroll_offset % cycle_width)
            draw.text((x, -1), label, fill=1, font=self._font)
            draw.text((x + cycle_width, -1), label, fill=1, font=self._font)
        else:
            x = (self.width - text_width) // 2
            draw.text((x, -1), label, fill=1, font=self._font)

        # Avoid Pillow's Image.__array_interface__, which goes through
        # Image.tobytes() and unnecessarily requires the optional ImageFile
        # module on the minimal Raspberry Pi installation.
        mask = np.asarray(list(canvas.get_flattened_data()), dtype=np.uint8)
        mask = mask.reshape(self.ticker_height, self.width) != 0
        ticker = frame[-self.ticker_height :]
        ticker[:] = 0
        ticker[mask] = self.ticker_text_color
