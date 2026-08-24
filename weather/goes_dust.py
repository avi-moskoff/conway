import io
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from PIL import Image

Transport = Callable[[Request, float], bytes]


class GoesDustError(RuntimeError):
    pass


def _default_transport(request: Request, timeout: float) -> bytes:
    with urlopen(request, timeout=timeout) as response:
        return response.read()


# Calibration derived from NOAA's own lat/lon reference grid for the "sr"
# (Southern Rockies) sector:
# https://www.star.nesdis.noaa.gov/GOES/images/latlon/g19_sr_grid_1200x1200_white.gif
#
# That image is a 1200x1200 transparent overlay NOAA ships specifically so
# viewers can read lat/lon off the sector JPEGs; its gridlines are visibly
# slanted (the sector is still in GOES ABI's satellite-view projection, not
# a flat lat/lon grid). The two longitude gridlines (-115, -110 deg) and two
# latitude gridlines (30, 35 deg) bracketing the US Southwest were traced by
# nearest-neighbor pixel tracking down each line (clustering by row/column
# index alone breaks wherever lines cross or exit the frame), each fit as a
# local line, and intersected for the four corners below.
#
# This is only accurate near the region it was derived from (roughly
# Arizona/southern New Mexico) - a satellite swap (see WeatherRadarConfig's
# dust_satellite) or supporting a different sector needs these re-derived
# the same way, not assumed to still hold.
_CALIBRATION_LON_ORIGIN = -115.0
_CALIBRATION_LAT_ORIGIN = 30.0
_CALIBRATION_LON_STEP = 5.0
_CALIBRATION_LAT_STEP = 5.0
_CALIBRATION_CORNER_00 = (-4.4, 952.9)  # (lon=-115, lat=30)
_CALIBRATION_CORNER_10 = (328.8, 932.1)  # (lon=-110, lat=30)
_CALIBRATION_CORNER_01 = (189.2, 539.0)  # (lon=-115, lat=35)
_CALIBRATION_CORNER_11 = (503.3, 514.1)  # (lon=-110, lat=35)


def sector_pixel_for(latitude: float, longitude: float) -> tuple[float, float]:
    """Map a latitude/longitude to a pixel in the "sr" sector's 1200x1200 image.

    Bilinear interpolation (or extrapolation, for points outside the
    calibration quad) across the four corners derived above. Accurate near
    the region they were derived from; not a general-purpose GOES ABI
    fixed-grid projection.
    """
    frac_lon = (longitude - _CALIBRATION_LON_ORIGIN) / _CALIBRATION_LON_STEP
    frac_lat = (latitude - _CALIBRATION_LAT_ORIGIN) / _CALIBRATION_LAT_STEP
    x00, y00 = _CALIBRATION_CORNER_00
    x10, y10 = _CALIBRATION_CORNER_10
    x01, y01 = _CALIBRATION_CORNER_01
    x11, y11 = _CALIBRATION_CORNER_11
    bottom_x = x00 + frac_lon * (x10 - x00)
    bottom_y = y00 + frac_lon * (y10 - y00)
    top_x = x01 + frac_lon * (x11 - x01)
    top_y = y01 + frac_lon * (y11 - y01)
    x = bottom_x + frac_lat * (top_x - bottom_x)
    y = bottom_y + frac_lat * (top_y - bottom_y)
    return x, y


class GoesDustClient:
    """Fetches the latest NOAA STAR GOES Dust RGB sector image.

    No discovery endpoint exists for the latest available timestamp (unlike
    Open-Meteo or adsb.lol), so this probes: round now down to the nearest
    update interval and step backward until a frame is found or attempts
    run out, absorbing NOAA's publish latency.
    """

    image_size = 1200
    update_interval_minutes = 5
    max_lookback_attempts = 6  # ~30 minutes of publish-latency tolerance

    def __init__(
        self,
        satellite: str = "GOES19",
        sector: str = "sr",
        band: str = "Dust",
        timeout_seconds: float = 10.0,
        transport: Transport | None = None,
    ) -> None:
        self._satellite = satellite
        self._sector = sector
        self._band = band
        self._timeout_seconds = timeout_seconds
        self._transport = transport or _default_transport

    def latest_frame(self, now: datetime | None = None) -> tuple[bytes, datetime] | None:
        # NOAA publishes on a schedule offset by one minute from a clean
        # 5-minute grid (:01, :06, :11, ... not :00, :05, :10) - shift back
        # a minute before flooring to land on that schedule, then shift
        # forward again. Done via timedelta arithmetic (not just replacing
        # the minute field) so hour/day rollover near the top of the hour
        # is handled correctly.
        now = now or datetime.now(timezone.utc)
        shifted = now - timedelta(minutes=1)
        floored_minute = shifted.minute - shifted.minute % self.update_interval_minutes
        candidate = shifted.replace(minute=floored_minute, second=0, microsecond=0)
        candidate += timedelta(minutes=1)
        for _ in range(self.max_lookback_attempts):
            body = self._try_fetch(candidate)
            if body is not None:
                return body, candidate
            candidate -= timedelta(minutes=self.update_interval_minutes)
        return None

    def _try_fetch(self, timestamp: datetime) -> bytes | None:
        request = Request(self._image_url(timestamp))
        request.add_header("Accept", "image/jpeg")
        request.add_header("User-Agent", "conway-led-matrix/0.1")
        try:
            body = self._transport(request, self._timeout_seconds)
        except HTTPError as error:
            if error.code == 404:
                return None
            raise GoesDustError(f"NOAA STAR API returned HTTP {error.code}") from error
        except (OSError, URLError) as error:
            raise GoesDustError("could not reach NOAA STAR API") from error
        if not self._is_valid_image(body):
            # Observed in practice: the very freshest timestamp occasionally
            # comes back corrupted/truncated, seemingly a race with NOAA's
            # own publish process rather than anything on our end (a retry
            # moments later for the same timestamp succeeds fine). Treat it
            # like a 404 - this timestamp isn't usable yet - and fall back
            # to the next older one instead of surfacing a hard failure.
            return None
        return body

    @staticmethod
    def _is_valid_image(body: bytes) -> bool:
        try:
            with Image.open(io.BytesIO(body)) as image:
                image.verify()
            return True
        except Exception:
            return False

    def _image_url(self, timestamp: datetime) -> str:
        stamp = (
            f"{timestamp.year:04d}{timestamp.timetuple().tm_yday:03d}"
            f"{timestamp.hour:02d}{timestamp.minute:02d}"
        )
        filename = (
            f"{stamp}_{self._satellite}-ABI-{self._sector}-{self._band}-"
            f"{self.image_size}x{self.image_size}.jpg"
        )
        return (
            f"https://cdn.star.nesdis.noaa.gov/{self._satellite}/ABI/SECTOR/"
            f"{self._sector}/{self._band}/{filename}"
        )
