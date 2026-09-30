from abc import ABC, abstractmethod

import numpy as np


class Game(ABC):
    """Interface implemented by every game the runner can host."""

    frame_delay_seconds = 1.0

    # The name shown for this screen in the switcher menu (see
    # games/menu.py). unscii-8 is monospace at 8px/char on a 64px-wide
    # display, so this must be 8 characters or fewer to render without
    # scrolling - the menu doesn't implement scrolling text, unlike the
    # ticker. Every concrete screen overrides this; there's no sensible
    # default.
    menu_label = "?"

    def __init__(self, height: int, width: int) -> None:
        self.height = height
        self.width = width

    def activate(self) -> None:
        """Make resources for this game active."""

    def deactivate(self) -> None:
        """Pause resources while preserving game state."""

    def close(self) -> None:
        """Release resources owned by this game."""

    @property
    @abstractmethod
    def frame(self) -> np.ndarray:
        """Return the current frame as an RGB array."""

    @abstractmethod
    def reset(self) -> None:
        """Reset the game to its initial state."""

    @abstractmethod
    def advance(self) -> None:
        """Advance the game by one frame."""

    def cycle_view(self, direction: int) -> None:
        """Switch to a sibling view within this screen, if it has more
        than one. `direction` is +1 or -1 (forward/backward).

        Driven by the encoder while the screen switcher is closed (see
        runner.py); most screens have only one view, so the default is a
        no-op. FlightRadarGame and WeatherRadarGame override this to step
        through their display_modes - the same cycling reset() used to do
        before the button became a pure force-refresh verb.
        """


def invert_pixel(frame: np.ndarray, x: int, y: int) -> None:
    """Mark a pixel by inverting whatever's already drawn there, in place.

    Used for anything that needs to read as a fixed marker regardless of
    the color field underneath it: the "self/home" marker (position varies
    by screen, usually centered) and the corner error/degraded-state
    indicator (see ERROR_PIXEL / mark_error below). A fixed color can wash
    out against a bright or similarly-colored field - AQI's white end and
    the dust product's blue/white base both do this - but a pixel's
    complement never can.
    """
    frame[y, x] = 255 - frame[y, x]


# Minimum brightness gap (0-255 luma) between a marker and its neighbors;
# below it the plain inverse is too close to read.
MARKER_MIN_CONTRAST = 100


def _luma(color: np.ndarray) -> float:
    return float(0.299 * color[0] + 0.587 * color[1] + 0.114 * color[2])


def invert_neighborhood(frame: np.ndarray, points: list[tuple[int, int]]) -> None:
    """Mark each of `points` with the inverse of the average of its
    neighboring pixels (the 8 around it, not the pixel itself), in place.

    For markers sitting on a continuous field - weather landmarks and home.
    The neighbors' average is what the eye compares the marker against,
    not the pixel's own color. But inversion alone fails on mid-gray, whose
    inverse is nearly the same gray, so when the inverse is within
    MARKER_MIN_CONTRAST of the average in brightness the marker falls back
    to whichever of black or white is farther from it. Every marker is
    computed from the frame as it was before any were drawn, so markers next
    to each other don't tint one another.
    """
    source = frame.copy()
    for x, y in points:
        window = source[max(y - 1, 0) : y + 2, max(x - 1, 0) : x + 2].reshape(-1, 3)
        # Drop the pixel itself from the window's average.
        total = window.sum(axis=0, dtype=np.int64) - source[y, x]
        average = np.rint(total / (len(window) - 1)).astype(np.uint8)
        marker = 255 - average
        if abs(_luma(marker) - _luma(average)) < MARKER_MIN_CONTRAST:
            marker = np.full(3, 0 if _luma(average) >= 128 else 255, dtype=np.uint8)
        frame[y, x] = marker


# Fixed location for the degraded-state indicator on every live screen.
# Position (corner vs. wherever self/home is drawn), not color, is what
# tells the two invert-markers apart - see invert_pixel and the palette
# notes in the design doc.
ERROR_PIXEL = (0, 0)


def mark_error(frame: np.ndarray) -> None:
    """Invert the fixed corner pixel to signal a degraded/error state.

    Never a fixed color (that would compete with red's one reserved
    meaning of "signal") and never anywhere but this corner (that would
    compete with self/home's use of the same invert technique).
    """
    x, y = ERROR_PIXEL
    invert_pixel(frame, x, y)
