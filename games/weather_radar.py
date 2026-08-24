import logging
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
from weather import AirQualitySample, OpenMeteoClient, WeatherSample

logger = logging.getLogger(__name__)


class WeatherRadarGame(Game):
    """North-up map of weather conditions / air quality near the configured location."""

    frame_delay_seconds = 1.0
    ticker_height = 12
    stale_snapshot_seconds = 1800.0
    display_modes = ("conditions", "aqi")
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
    ) -> None:
        super().__init__(height, width)
        self._config = config
        self._client = client or OpenMeteoClient()
        self._radar_height = height - self.ticker_height - 1

        self._data_lock = Lock()
        self._active_event = Event()
        self._wake_event = Event()
        self._stop_event = Event()
        self._worker: Thread | None = None

        self._conditions_field: np.ndarray | None = None
        self._conditions_snapshot_time: float | None = None
        self._has_conditions_error = False
        self._home_weather_sample: WeatherSample | None = None

        self._aqi_field: np.ndarray | None = None
        self._aqi_snapshot_time: float | None = None
        self._has_aqi_error = False
        self._home_aqi_sample: AirQualitySample | None = None

        self._display_mode_index = 0
        self._last_label = ""
        self._scroll_offset = 0
        self._ticker_scrolls = False
        self._font = ImageFont.load_default(size=12)

        max_east, max_north = pixel_to_offset(
            self.width - 1, 0, config.radius_nm, self.width, self._radar_height
        )
        self._query_points = self._build_query_points(max_east, max_north)
        self._pixel_east, self._pixel_north = self._build_pixel_grid()
        self._landmark_pixels = self._build_landmark_pixels()

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

    def _build_pixel_grid(self) -> tuple[np.ndarray, np.ndarray]:
        grid_x, grid_y = np.meshgrid(np.arange(self.width), np.arange(self._radar_height))
        vectorized = np.vectorize(pixel_to_offset, otypes=[float, float])
        return vectorized(
            grid_x, grid_y, self._config.radius_nm, self.width, self._radar_height
        )

    def _build_landmark_pixels(self) -> tuple[tuple[int, int], ...]:
        points = (
            project_position(
                latitude,
                longitude,
                self._config.home_latitude,
                self._config.home_longitude,
                self._config.radius_nm,
                self.width,
                self._radar_height,
            )
            for _name, latitude, longitude in self._config.landmarks
        )
        return tuple(point for point in points if point is not None)

    def activate(self) -> None:
        if self._worker is None:
            self._worker = Thread(
                target=self._poll_loop, name="weather-radar-poller", daemon=True
            )
            self._worker.start()
        self._active_event.set()
        self._wake_event.set()
        logger.info("Weather radar polling activated")

    def deactivate(self) -> None:
        self._active_event.clear()
        self._wake_event.set()
        logger.info("Weather radar polling paused")

    def close(self) -> None:
        self._stop_event.set()
        self._active_event.set()
        self._wake_event.set()
        if self._worker is not None:
            self._worker.join(timeout=11.0)
        logger.info("Weather radar polling stopped")

    def reset(self) -> None:
        # Both modes' data are already fetched and cached every poll (see
        # _poll_loop), so switching modes only changes which cached field
        # is displayed - no fresh fetch is needed here.
        self._display_mode_index = (self._display_mode_index + 1) % len(
            self.display_modes
        )
        self._scroll_offset = 0

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

        frame = np.zeros((self.height, self.width, 3), dtype=np.uint8)

        if mode == "conditions":
            stale = self._is_stale(conditions_snapshot_time, now)
            if not stale and conditions_field is not None:
                frame[: self._radar_height] = conditions_field
            label = (
                "NO SIGNAL" if stale else self._conditions_label(home_weather_sample)
            )
            show_error = has_conditions_error and not stale
        else:
            stale = self._is_stale(aqi_snapshot_time, now)
            if not stale and aqi_field is not None:
                frame[: self._radar_height] = aqi_field
            label = "NO SIGNAL" if stale else self._aqi_label(home_aqi_sample)
            show_error = has_aqi_error and not stale

        for x, y in self._landmark_pixels:
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
        return min(5 * 60.0, base_poll_seconds * (2 ** min(failures, 5)))

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
