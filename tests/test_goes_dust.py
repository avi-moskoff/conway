import io
import unittest
from datetime import datetime, timezone
from urllib.error import HTTPError
from urllib.request import Request

from PIL import Image

from weather.goes_dust import GoesDustClient, GoesDustError, sector_pixel_for


def _valid_image_bytes() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (4, 4), (10, 20, 30)).save(buffer, format="JPEG")
    return buffer.getvalue()


class GoesDustClientTests(unittest.TestCase):
    def test_aligns_to_noaas_one_minute_offset_schedule(self) -> None:
        requested_urls = []
        valid_bytes = _valid_image_bytes()

        def transport(request: Request, _timeout: float) -> bytes:
            requested_urls.append(request.full_url)
            return valid_bytes

        client = GoesDustClient(transport=transport, retry_delay_seconds=0)
        # 03:53 should probe the most recent published minute (:51), not a
        # naive floor-to-5 (:50) - NOAA's grid is offset by one minute.
        now = datetime(2026, 8, 24, 3, 53, 16, tzinfo=timezone.utc)

        body, frame_time = client.latest_frame(now=now)

        self.assertEqual(body, valid_bytes)
        self.assertEqual(frame_time, datetime(2026, 8, 24, 3, 51, tzinfo=timezone.utc))
        self.assertIn("20262360351_GOES19-ABI-sr-Dust-1200x1200.jpg", requested_urls[0])

    def test_steps_backward_through_404s_until_a_frame_is_found(self) -> None:
        available_timestamp = "20262360341"
        requested_urls = []
        valid_bytes = _valid_image_bytes()

        def transport(request: Request, _timeout: float) -> bytes:
            requested_urls.append(request.full_url)
            if available_timestamp in request.full_url:
                return valid_bytes
            raise HTTPError(request.full_url, 404, "not found", {}, None)

        client = GoesDustClient(transport=transport, retry_delay_seconds=0)
        now = datetime(2026, 8, 24, 3, 53, 16, tzinfo=timezone.utc)

        body, frame_time = client.latest_frame(now=now)

        self.assertEqual(body, valid_bytes)
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
        valid_bytes = _valid_image_bytes()
        requested_urls = []

        def transport(request: Request, _timeout: float) -> bytes:
            requested_urls.append(request.full_url)
            if "20262360351" in request.full_url:
                return b"\xff\xd8\xff\xe0not actually a complete jpeg"
            return valid_bytes

        client = GoesDustClient(transport=transport, retry_delay_seconds=0)
        now = datetime(2026, 8, 24, 3, 53, 16, tzinfo=timezone.utc)

        body, frame_time = client.latest_frame(now=now)

        self.assertEqual(body, valid_bytes)
        self.assertEqual(frame_time, datetime(2026, 8, 24, 3, 46, tzinfo=timezone.utc))
        # 3 retries on the corrupted :51 timestamp, then 1 successful try on :46.
        self.assertEqual(len(requested_urls), client.retries_per_timestamp + 1)

    def test_recovers_from_a_transient_network_error_on_retry(self) -> None:
        attempts = []

        def transport(request: Request, _timeout: float) -> bytes:
            attempts.append(request.full_url)
            if len(attempts) == 1:
                raise HTTPError(request.full_url, 503, "temporarily unavailable", {}, None)
            return _valid_image_bytes()

        client = GoesDustClient(transport=transport, retry_delay_seconds=0)
        now = datetime(2026, 8, 24, 3, 53, 16, tzinfo=timezone.utc)

        body, frame_time = client.latest_frame(now=now)

        self.assertIsNotNone(body)
        self.assertEqual(frame_time, datetime(2026, 8, 24, 3, 51, tzinfo=timezone.utc))
        self.assertEqual(len(attempts), 2)

    def test_gives_up_after_the_lookback_window_is_exhausted(self) -> None:
        def transport(request: Request, _timeout: float) -> bytes:
            raise HTTPError(request.full_url, 404, "not found", {}, None)

        client = GoesDustClient(transport=transport, retry_delay_seconds=0)
        now = datetime(2026, 8, 24, 3, 53, 16, tzinfo=timezone.utc)

        self.assertIsNone(client.latest_frame(now=now))

    def test_404_is_not_retried_and_falls_back_immediately(self) -> None:
        requested_urls = []
        valid_bytes = _valid_image_bytes()

        def transport(request: Request, _timeout: float) -> bytes:
            requested_urls.append(request.full_url)
            if "20262360351" in request.full_url:
                raise HTTPError(request.full_url, 404, "not found", {}, None)
            return valid_bytes

        client = GoesDustClient(transport=transport, retry_delay_seconds=0)
        now = datetime(2026, 8, 24, 3, 53, 16, tzinfo=timezone.utc)

        body, frame_time = client.latest_frame(now=now)

        self.assertEqual(body, valid_bytes)
        self.assertEqual(frame_time, datetime(2026, 8, 24, 3, 46, tzinfo=timezone.utc))
        # A 404 means "not published" - no point retrying it, straight to :46.
        self.assertEqual(len(requested_urls), 2)

    def test_non_404_http_error_raises_after_retries_are_exhausted(self) -> None:
        calls = []

        def transport(request: Request, _timeout: float) -> bytes:
            calls.append(request.full_url)
            raise HTTPError(request.full_url, 500, "server error", {}, None)

        client = GoesDustClient(transport=transport, retry_delay_seconds=0)
        now = datetime(2026, 8, 24, 3, 53, 16, tzinfo=timezone.utc)

        with self.assertRaises(GoesDustError):
            client.latest_frame(now=now)
        self.assertEqual(len(calls), client.retries_per_timestamp)


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
