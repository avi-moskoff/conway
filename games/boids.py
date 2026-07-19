import numpy as np

from games.base import Game


class BoidsGame(Game):
    """A flocking simulation sized for the LED matrix."""

    frame_delay_seconds = 0.05

    def __init__(self, height: int, width: int, boid_count: int = 36) -> None:
        super().__init__(height, width)
        self.boid_count = boid_count
        self._bounds = np.array([width, height], dtype=np.float32)
        self.positions = np.empty((boid_count, 2), dtype=np.float32)
        self.velocities = np.empty((boid_count, 2), dtype=np.float32)
        self.reset()

    @property
    def frame(self) -> np.ndarray:
        frame = np.zeros((self.height, self.width, 3), dtype=np.uint8)
        pixel_bounds = self._bounds.astype(int)
        heads = np.rint(self.positions).astype(int) % pixel_bounds

        frame[heads[:, 1], heads[:, 0]] = (255, 255, 255)
        return frame

    def reset(self) -> None:
        self.positions = (np.random.random((self.boid_count, 2)) * self._bounds).astype(
            np.float32
        )
        angles = np.random.uniform(0, 2 * np.pi, self.boid_count)
        speeds = np.random.uniform(0.5, 1.25, self.boid_count)
        self.velocities = np.column_stack(
            (np.cos(angles) * speeds, np.sin(angles) * speeds)
        ).astype(np.float32)

    def advance(self) -> None:
        offsets = self.positions[np.newaxis, :, :] - self.positions[:, np.newaxis, :]
        offsets = (offsets + self._bounds / 2) % self._bounds - self._bounds / 2
        distance_squared = np.sum(offsets**2, axis=2)
        not_self = distance_squared > 0

        nearby = not_self & (distance_squared < 9**2)
        close = not_self & (distance_squared < 3**2)

        alignment = self._masked_mean(
            np.broadcast_to(self.velocities, offsets.shape), nearby
        )
        has_neighbors = np.any(nearby, axis=1)
        alignment[has_neighbors] -= self.velocities[has_neighbors]
        cohesion = self._masked_mean(offsets, nearby)

        separation_weights = np.zeros_like(distance_squared)
        np.divide(1, distance_squared, out=separation_weights, where=close)
        separation = -np.sum(offsets * separation_weights[:, :, np.newaxis], axis=1)

        self.velocities += alignment * 0.05 + cohesion * 0.008 + separation * 0.2
        speed = np.linalg.norm(self.velocities, axis=1, keepdims=True)
        self.velocities *= np.minimum(1, 1.5 / np.maximum(speed, 0.001))
        self.positions = (self.positions + self.velocities) % self._bounds

    @staticmethod
    def _masked_mean(values: np.ndarray, mask: np.ndarray) -> np.ndarray:
        counts = np.sum(mask, axis=1, keepdims=True)
        totals = np.sum(values * mask[:, :, np.newaxis], axis=1)
        means = np.zeros_like(totals)
        np.divide(totals, counts, out=means, where=counts > 0)
        return means
