import io
import unittest
from datetime import datetime, timezone
from urllib.error import HTTPError
from urllib.request import Request

import numpy as np
from PIL import Image

from weather.goes_dust import (
    DUST_BACKDROP_RGB,
    DUST_MATCH_RGB,
    GoesDustApiError,
    GoesDustClient,
    GoesDustConnectionError,
    GoesDustError,
    GoesDustRateLimitedError,
    _decode_via_subprocess,
    apply_dust_filter,
    sector_pixel_for,
)

# Transport-level fakes just need distinguishable byte markers - decoding
# itself is faked separately via `decode=`, so these don't need to be real
# JPEG bytes.
_GOOD_BYTES = b"good-image-bytes"
_BAD_BYTES = b"\xff\xd8\xff\xe0not actually a complete jpeg"
_DECODED_ARRAY = np.zeros((4, 4, 3), dtype=np.uint8)


def _fake_decode(body: bytes) -> np.ndarray | None:
    return _DECODED_ARRAY if body == _GOOD_BYTES else None


class GoesDustClientTests(unittest.TestCase):
    def test_aligns_to_noaas_one_minute_offset_schedule(self) -> None:
        requested_urls = []

        def transport(request: Request, _timeout: float) -> bytes:
            requested_urls.append(request.full_url)
            return _GOOD_BYTES

        client = GoesDustClient(
            transport=transport, decode=_fake_decode, retry_delay_seconds=0
        )
        # 03:53 should probe the most recent published minute (:51), not a
        # naive floor-to-5 (:50) - NOAA's grid is offset by one minute.
        now = datetime(2026, 8, 24, 3, 53, 16, tzinfo=timezone.utc)

        frame, frame_time = client.latest_frame(now=now)

        np.testing.assert_array_equal(frame, _DECODED_ARRAY)
        self.assertEqual(frame_time, datetime(2026, 8, 24, 3, 51, tzinfo=timezone.utc))
        self.assertIn("20262360351_GOES19-ABI-sr-Dust-1200x1200.jpg", requested_urls[0])

    def test_steps_backward_through_404s_until_a_frame_is_found(self) -> None:
        available_timestamp = "20262360341"
        requested_urls = []

        def transport(request: Request, _timeout: float) -> bytes:
            requested_urls.append(request.full_url)
            if available_timestamp in request.full_url:
                return _GOOD_BYTES
            raise HTTPError(request.full_url, 404, "not found", {}, None)

        client = GoesDustClient(
            transport=transport, decode=_fake_decode, retry_delay_seconds=0
        )
        now = datetime(2026, 8, 24, 3, 53, 16, tzinfo=timezone.utc)

        frame, frame_time = client.latest_frame(now=now)

        np.testing.assert_array_equal(frame, _DECODED_ARRAY)
        self.assertEqual(frame_time, datetime(2026, 8, 24, 3, 41, tzinfo=timezone.utc))
        # 51, 46, 41 - three probes, stopping at the first hit.
        self.assertEqual(len(requested_urls), 3)

    def test_retries_a_corrupted_timestamp_before_falling_back(self) -> None:
        # Observed in practice against the real NOAA CDN: a timestamp can
        # come back as a genuine HTTP 200 with a truncated or otherwise
        # undecodable body - looked like a brief connection hiccup, since
        # retrying the exact same request moments later succeeded. The
        # client should retry a few times in place before giving up on that
        # timestamp and falling back to an older one.
        requested_urls = []

        def transport(request: Request, _timeout: float) -> bytes:
            requested_urls.append(request.full_url)
            if "20262360351" in request.full_url:
                return _BAD_BYTES
            return _GOOD_BYTES

        client = GoesDustClient(
            transport=transport, decode=_fake_decode, retry_delay_seconds=0
        )
        now = datetime(2026, 8, 24, 3, 53, 16, tzinfo=timezone.utc)

        frame, frame_time = client.latest_frame(now=now)

        np.testing.assert_array_equal(frame, _DECODED_ARRAY)
        self.assertEqual(frame_time, datetime(2026, 8, 24, 3, 46, tzinfo=timezone.utc))
        # 3 retries on the corrupted :51 timestamp, then 1 successful try on :46.
        self.assertEqual(len(requested_urls), client.retries_per_timestamp + 1)

    def test_recovers_from_a_transient_network_error_on_retry(self) -> None:
        attempts = []

        def transport(request: Request, _timeout: float) -> bytes:
            attempts.append(request.full_url)
            if len(attempts) == 1:
                raise HTTPError(request.full_url, 503, "temporarily unavailable", {}, None)
            return _GOOD_BYTES

        client = GoesDustClient(
            transport=transport, decode=_fake_decode, retry_delay_seconds=0
        )
        now = datetime(2026, 8, 24, 3, 53, 16, tzinfo=timezone.utc)

        frame, frame_time = client.latest_frame(now=now)

        self.assertIsNotNone(frame)
        self.assertEqual(frame_time, datetime(2026, 8, 24, 3, 51, tzinfo=timezone.utc))
        self.assertEqual(len(attempts), 2)

    def test_gives_up_after_the_lookback_window_is_exhausted(self) -> None:
        def transport(request: Request, _timeout: float) -> bytes:
            raise HTTPError(request.full_url, 404, "not found", {}, None)

        client = GoesDustClient(
            transport=transport, decode=_fake_decode, retry_delay_seconds=0
        )
        now = datetime(2026, 8, 24, 3, 53, 16, tzinfo=timezone.utc)

        self.assertIsNone(client.latest_frame(now=now))

    def test_404_is_not_retried_and_falls_back_immediately(self) -> None:
        requested_urls = []

        def transport(request: Request, _timeout: float) -> bytes:
            requested_urls.append(request.full_url)
            if "20262360351" in request.full_url:
                raise HTTPError(request.full_url, 404, "not found", {}, None)
            return _GOOD_BYTES

        client = GoesDustClient(
            transport=transport, decode=_fake_decode, retry_delay_seconds=0
        )
        now = datetime(2026, 8, 24, 3, 53, 16, tzinfo=timezone.utc)

        frame, frame_time = client.latest_frame(now=now)

        np.testing.assert_array_equal(frame, _DECODED_ARRAY)
        self.assertEqual(frame_time, datetime(2026, 8, 24, 3, 46, tzinfo=timezone.utc))
        # A 404 means "not published" - no point retrying it, straight to :46.
        self.assertEqual(len(requested_urls), 2)

    def test_non_404_http_error_raises_after_retries_are_exhausted(self) -> None:
        calls = []

        def transport(request: Request, _timeout: float) -> bytes:
            calls.append(request.full_url)
            raise HTTPError(request.full_url, 500, "server error", {}, None)

        client = GoesDustClient(
            transport=transport, decode=_fake_decode, retry_delay_seconds=0
        )
        now = datetime(2026, 8, 24, 3, 53, 16, tzinfo=timezone.utc)

        with self.assertRaises(GoesDustError):
            client.latest_frame(now=now)
        self.assertEqual(len(calls), client.retries_per_timestamp)

    def test_non_404_http_error_is_specifically_an_api_error(self) -> None:
        # Distinguishing connection/API/rate-limit failures is what lets
        # WeatherRadarGame show a specific ticker reason instead of a bare
        # "NO SIGNAL" - see the design doc's Error & degraded-state
        # handling section.
        def transport(request: Request, _timeout: float) -> bytes:
            raise HTTPError(request.full_url, 500, "server error", {}, None)

        client = GoesDustClient(
            transport=transport, decode=_fake_decode, retry_delay_seconds=0
        )
        now = datetime(2026, 8, 24, 3, 53, 16, tzinfo=timezone.utc)

        with self.assertRaises(GoesDustApiError):
            client.latest_frame(now=now)

    def test_429_raises_rate_limited_error_with_retry_after(self) -> None:
        def transport(request: Request, _timeout: float) -> bytes:
            raise HTTPError(
                request.full_url, 429, "too many requests", {"Retry-After": "45"}, None
            )

        client = GoesDustClient(
            transport=transport, decode=_fake_decode, retry_delay_seconds=0
        )
        now = datetime(2026, 8, 24, 3, 53, 16, tzinfo=timezone.utc)

        with self.assertRaises(GoesDustRateLimitedError) as context:
            client.latest_frame(now=now)
        self.assertEqual(context.exception.retry_after_seconds, 45.0)

    def test_connection_failure_raises_connection_error(self) -> None:
        def transport(_request: Request, _timeout: float) -> bytes:
            raise OSError("network unreachable")

        client = GoesDustClient(
            transport=transport, decode=_fake_decode, retry_delay_seconds=0
        )
        now = datetime(2026, 8, 24, 3, 53, 16, tzinfo=timezone.utc)

        with self.assertRaises(GoesDustConnectionError):
            client.latest_frame(now=now)


class DecodeViaSubprocessTests(unittest.TestCase):
    # Exercises the real default decode path (an actual worker subprocess),
    # not the injected fake used above - this is the whole point of the
    # fix (see the module comment on _decode_via_subprocess for why it
    # exists), so it needs its own coverage against real Pillow-encoded
    # bytes, even though spawning a process makes it much slower than the
    # rest of this file.
    def test_decodes_a_real_jpeg(self) -> None:
        buffer = io.BytesIO()
        Image.new("RGB", (4, 4), (10, 20, 30)).save(buffer, format="JPEG")

        frame = _decode_via_subprocess(buffer.getvalue())

        self.assertIsNotNone(frame)
        self.assertEqual(frame.shape, (4, 4, 3))

    def test_returns_none_for_undecodable_bytes(self) -> None:
        self.assertIsNone(_decode_via_subprocess(_BAD_BYTES))


class SectorPixelForTests(unittest.TestCase):
    def test_reproduces_the_calibration_corners(self) -> None:
        corners = {
            (30.0, -115.0): (-4.4, 952.9),
            (30.0, -110.0): (328.8, 932.1),
            (35.0, -115.0): (189.2, 539.0),
            (35.0, -110.0): (503.3, 514.1),
        }
        for (latitude, longitude), expected in corners.items():
            with self.subTest(latitude=latitude, longitude=longitude):
                x, y = sector_pixel_for(latitude, longitude)
                self.assertAlmostEqual(x, expected[0], places=3)
                self.assertAlmostEqual(y, expected[1], places=3)


if __name__ == "__main__":
    unittest.main()


class ApplyDustFilterTests(unittest.TestCase):
    def test_bright_magenta_dust_signature_is_matched(self) -> None:
        # Pure magenta: hue 300, saturation 1, value 1 - squarely inside
        # the dust band described by the CIRA/RAMMB and EUMETrain guides.
        pixel = np.array([[[255, 0, 255]]], dtype=np.uint8)
        result = apply_dust_filter(pixel)
        self.assertEqual(tuple(result[0, 0]), DUST_MATCH_RGB)

    def test_muted_plum_dust_signature_is_matched(self) -> None:
        # hue ~285, saturation ~0.57, value ~0.55 - the guides' "low-level
        # dust plumes have a purple/plum color" description, deliberately
        # less saturated/bright than pure magenta.
        pixel = np.array([[[120, 60, 140]]], dtype=np.uint8)
        result = apply_dust_filter(pixel)
        self.assertEqual(tuple(result[0, 0]), DUST_MATCH_RGB)

    def test_blue_violet_airmass_wash_is_not_matched(self) -> None:
        # Median pixel from a real evening GOES-19 frame over Phoenix: cool,
        # moist background (hue ~231), no plume. Must not read as dust.
        pixel = np.array([[[129, 119, 218]]], dtype=np.uint8)
        result = apply_dust_filter(pixel)
        self.assertEqual(tuple(result[0, 0]), DUST_BACKDROP_RGB)

    def test_hue_floor_separates_violet_from_plum(self) -> None:
        # hue ~260 (violet, saturated) is excluded; hue ~285 plum is not.
        violet = np.array([[[110, 60, 200]]], dtype=np.uint8)
        self.assertEqual(tuple(apply_dust_filter(violet)[0, 0]), DUST_BACKDROP_RGB)

    def test_cloud_green_is_not_matched(self) -> None:
        # Mid-level thin cloud, per the guides, reads as green - nowhere
        # near the purple/plum-to-pink/magenta dust band.
        pixel = np.array([[[0, 255, 0]]], dtype=np.uint8)
        result = apply_dust_filter(pixel)
        self.assertEqual(tuple(result[0, 0]), DUST_BACKDROP_RGB)

    def test_desert_surface_light_blue_is_not_matched(self) -> None:
        pixel = np.array([[[100, 180, 255]]], dtype=np.uint8)
        result = apply_dust_filter(pixel)
        self.assertEqual(tuple(result[0, 0]), DUST_BACKDROP_RGB)

    def test_washed_out_gray_cloud_is_excluded_by_the_saturation_floor(self) -> None:
        # Hue could fall inside the dust band by chance even for a
        # near-gray pixel; low saturation should rule it out regardless.
        pixel = np.array([[[210, 200, 215]]], dtype=np.uint8)
        result = apply_dust_filter(pixel)
        self.assertEqual(tuple(result[0, 0]), DUST_BACKDROP_RGB)

    def test_near_black_high_cloud_is_excluded_by_the_value_floor(self) -> None:
        pixel = np.array([[[10, 2, 12]]], dtype=np.uint8)
        result = apply_dust_filter(pixel)
        self.assertEqual(tuple(result[0, 0]), DUST_BACKDROP_RGB)

    def test_handles_a_full_size_grid_without_error(self) -> None:
        grid = np.random.default_rng(0).integers(0, 256, (51, 64, 3), dtype=np.uint8)
        result = apply_dust_filter(grid)
        self.assertEqual(result.shape, grid.shape)
        self.assertEqual(result.dtype, grid.dtype)
