import unittest
from datetime import datetime, timezone
from urllib.error import HTTPError
from urllib.request import Request

from weather.goes_dust import GoesDustClient, GoesDustError, sector_pixel_for


class GoesDustClientTests(unittest.TestCase):
    def test_aligns_to_noaas_one_minute_offset_schedule(self) -> None:
        requested_urls = []

        def transport(request: Request, _timeout: float) -> bytes:
            requested_urls.append(request.full_url)
            return b"fake-jpeg-bytes"

        client = GoesDustClient(transport=transport)
        # 03:53 should probe the most recent published minute (:51), not a
        # naive floor-to-5 (:50) - NOAA's grid is offset by one minute.
        now = datetime(2026, 8, 24, 3, 53, 16, tzinfo=timezone.utc)

        body, frame_time = client.latest_frame(now=now)

        self.assertEqual(body, b"fake-jpeg-bytes")
        self.assertEqual(frame_time, datetime(2026, 8, 24, 3, 51, tzinfo=timezone.utc))
        self.assertIn("20262360351_GOES19-ABI-sr-Dust-1200x1200.jpg", requested_urls[0])

    def test_steps_backward_through_404s_until_a_frame_is_found(self) -> None:
        available_timestamp = "20262360341"
        requested_urls = []

        def transport(request: Request, _timeout: float) -> bytes:
            requested_urls.append(request.full_url)
            if available_timestamp in request.full_url:
                return b"fake-jpeg-bytes"
            raise HTTPError(request.full_url, 404, "not found", {}, None)

        client = GoesDustClient(transport=transport)
        now = datetime(2026, 8, 24, 3, 53, 16, tzinfo=timezone.utc)

        body, frame_time = client.latest_frame(now=now)

        self.assertEqual(body, b"fake-jpeg-bytes")
        self.assertEqual(frame_time, datetime(2026, 8, 24, 3, 41, tzinfo=timezone.utc))
        # 51, 46, 41 - three probes, stopping at the first hit.
        self.assertEqual(len(requested_urls), 3)

    def test_gives_up_after_the_lookback_window_is_exhausted(self) -> None:
        def transport(request: Request, _timeout: float) -> bytes:
            raise HTTPError(request.full_url, 404, "not found", {}, None)

        client = GoesDustClient(transport=transport)
        now = datetime(2026, 8, 24, 3, 53, 16, tzinfo=timezone.utc)

        self.assertIsNone(client.latest_frame(now=now))

    def test_non_404_http_error_raises_immediately_without_further_probing(self) -> None:
        calls = []

        def transport(request: Request, _timeout: float) -> bytes:
            calls.append(request.full_url)
            raise HTTPError(request.full_url, 500, "server error", {}, None)

        client = GoesDustClient(transport=transport)
        now = datetime(2026, 8, 24, 3, 53, 16, tzinfo=timezone.utc)

        with self.assertRaises(GoesDustError):
            client.latest_frame(now=now)
        self.assertEqual(len(calls), 1)


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
