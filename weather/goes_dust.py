import io
import logging
import socket
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timedelta, timezone
from http.client import HTTPSConnection
from multiprocessing import get_context
from time import sleep
from urllib.error import HTTPError, URLError
from urllib.request import HTTPSHandler, Request, build_opener

import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)

Transport = Callable[[Request, float], bytes]
Decoder = Callable[[bytes], "np.ndarray | None"]


class GoesDustError(RuntimeError):
    pass


def _decode_jpeg(body: bytes) -> np.ndarray | None:
    """Decodes JPEG bytes to an RGB array. Runs inside an isolated worker
    process (see _decode_via_subprocess) - must stay a plain, picklable,
    module-level function with no dependency on any of this process's
    state, since the worker process doesn't share it.
    """
    try:
        with Image.open(io.BytesIO(body)) as image:
            return np.asarray(image.convert("RGB"))
    except Exception:
        return None


_decode_executor: ProcessPoolExecutor | None = None
_decode_timeout_seconds = 15.0


def warm_up_decode_executor() -> None:
    """Pre-creates the decode worker process. Call this once at startup,
    before constructing anything that touches RGBMatrix (real GPIO/PWM
    hardware) - see _decode_via_subprocess for why. Spawning after
    RGBMatrix has already altered this process breaks the fork()+exec()
    spawn itself (observed directly: consistent BrokenPipeError on every
    attempt once RGBMatrix is already constructed, not just decoding on a
    shared thread as originally found) - so the worker needs to already
    exist as an independent process before that happens, not be created
    lazily on first use the way the rest of this module's callers expect.
    Once spawned, it's a separate process/address space and is unaffected
    by whatever the parent does to itself afterward.
    """
    _decode_via_subprocess(b"")


def _decode_via_subprocess(body: bytes) -> np.ndarray | None:
    # See warm_up_decode_executor's docstring for why this needs to be
    # called before RGBMatrix is constructed, not lazily on first real use.
    global _decode_executor
    try:
        if _decode_executor is None:
            _decode_executor = ProcessPoolExecutor(
                max_workers=1, mp_context=get_context("spawn")
            )
        return _decode_executor.submit(_decode_jpeg, body).result(
            timeout=_decode_timeout_seconds
        )
    except Exception as error:
        logger.warning(
            "Dust decode worker error (%s: %s) - recreating worker process",
            type(error).__name__, error,
        )
        # Whatever failed - pool creation, a dead/broken worker, a timeout -
        # don't stay stuck with a broken singleton for the rest of this
        # process's lifetime. The next call gets a fresh pool.
        if _decode_executor is not None:
            _decode_executor.shutdown(wait=False, cancel_futures=True)
        _decode_executor = None
        return None


def _connect_ipv4_only(host: str, port: int, timeout: float | None) -> socket.socket:
    # Some networks resolve this CDN to an IPv6 address that's advertised
    # but doesn't actually route (observed directly: 100% ping loss to the
    # resolved AAAA record, while IPv4 works fine) - plain socket.create_
    # connection() would still try that broken address first. Restrict
    # getaddrinfo to AF_INET so this client only ever attempts IPv4.
    last_error: OSError | None = None
    for family, socktype, proto, _canonname, address in socket.getaddrinfo(
        host, port, socket.AF_INET, socket.SOCK_STREAM
    ):
        sock = socket.socket(family, socktype, proto)
        try:
            sock.settimeout(timeout)
            sock.connect(address)
            return sock
        except OSError as error:
            sock.close()
            last_error = error
    raise last_error or OSError(f"no IPv4 address found for {host}")


class _IPv4OnlyHTTPSConnection(HTTPSConnection):
    def connect(self) -> None:
        sock = _connect_ipv4_only(self.host, self.port, self.timeout)
        if self._tunnel_host:
            self.sock = sock
            self._tunnel()
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


class _IPv4OnlyHTTPSHandler(HTTPSHandler):
    def https_open(self, req):
        return self.do_open(_IPv4OnlyHTTPSConnection, req)


_ipv4_opener = build_opener(_IPv4OnlyHTTPSHandler)


def _default_transport(request: Request, timeout: float) -> bytes:
    with _ipv4_opener.open(request, timeout=timeout) as response:
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
    retries_per_timestamp = 3  # absorbs a brief connection hiccup, not just a bad timestamp
    retry_delay_seconds = 1.5

    def __init__(
        self,
        satellite: str = "GOES19",
        sector: str = "sr",
        band: str = "Dust",
        timeout_seconds: float = 10.0,
        transport: Transport | None = None,
        retry_delay_seconds: float | None = None,
        decode: Decoder | None = None,
    ) -> None:
        self._satellite = satellite
        self._sector = sector
        self._band = band
        self._timeout_seconds = timeout_seconds
        self._transport = transport or _default_transport
        self._decode = decode or _decode_via_subprocess
        if retry_delay_seconds is not None:
            self.retry_delay_seconds = retry_delay_seconds

    def latest_frame(self, now: datetime | None = None) -> tuple[np.ndarray, datetime] | None:
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
            frame = self._try_fetch(candidate)
            if frame is not None:
                return frame, candidate
            candidate -= timedelta(minutes=self.update_interval_minutes)
        return None

    def _try_fetch(self, timestamp: datetime) -> np.ndarray | None:
        # A 404 means this timestamp genuinely isn't published - retrying it
        # won't help, so fall straight back to an older one. Anything else
        # (a network error, or a fetched body that fails to decode) is
        # ordinary transient-failure territory - a brief connection hiccup,
        # not something wrong with this specific timestamp - so retry it a
        # couple times in place before giving up on it too.
        url = self._image_url(timestamp)
        request = Request(url)
        request.add_header("Accept", "image/jpeg")
        request.add_header("User-Agent", "conway-led-matrix/0.1")
        last_network_error: GoesDustError | None = None
        for attempt in range(self.retries_per_timestamp):
            if attempt:
                sleep(self.retry_delay_seconds)
            try:
                body = self._transport(request, self._timeout_seconds)
            except HTTPError as error:
                if error.code == 404:
                    logger.info("Dust fetch %s: 404 (not yet published)", timestamp)
                    return None
                logger.warning(
                    "Dust fetch %s attempt %d/%d: HTTP %d",
                    timestamp, attempt + 1, self.retries_per_timestamp, error.code,
                )
                last_network_error = GoesDustError(
                    f"NOAA STAR API returned HTTP {error.code}"
                )
                continue
            except (OSError, URLError) as error:
                logger.warning(
                    "Dust fetch %s attempt %d/%d: network error (%s: %s)",
                    timestamp, attempt + 1, self.retries_per_timestamp,
                    type(error).__name__, error,
                )
                last_network_error = GoesDustError("could not reach NOAA STAR API")
                continue
            decoded = self._decode(body)
            if decoded is not None:
                logger.info("Dust fetch %s: OK (%d bytes)", timestamp, len(body))
                return decoded
            logger.warning(
                "Dust fetch %s attempt %d/%d: %d bytes but failed to decode",
                timestamp, attempt + 1, self.retries_per_timestamp, len(body),
            )
            last_network_error = None
        if last_network_error is not None:
            raise last_network_error
        return None

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
