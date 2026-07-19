import numpy as np

from games.base import Game


class BoidsGame(Game):
    """A flocking simulation sized for the LED matrix."""

    frame_delay_seconds = 0.05
    separation_radius = 4
    alignment_weight = 0.04
    cohesion_weight = 0.003
    separation_weight = 0.3
    minimum_speed = 0.4
    maximum_speed = 1.5

    def __init__(
        self,
        height: int,
        width: int,
        boid_count: int = 36,
        flock_count: int = 3,
    ) -> None:
        super().__init__(height, width)
        if not 1 <= flock_count <= boid_count:
            raise ValueError("flock_count must be between 1 and boid_count")
        self.boid_count = boid_count
        self.flock_count = flock_count
        self.flock_ids = np.arange(boid_count) % flock_count
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
        flock_centers = np.random.random((self.flock_count, 2)) * self._bounds
        self.positions = (
            flock_centers[self.flock_ids]
            + np.random.normal(0, 4, (self.boid_count, 2))
        ) % self._bounds

        flock_headings = np.random.uniform(0, 2 * np.pi, self.flock_count)
        angles = flock_headings[self.flock_ids] + np.random.normal(
            0, 0.25, self.boid_count
        )
        speeds = np.random.uniform(0.5, 1.25, self.boid_count)
        self.positions = self.positions.astype(np.float32)
        self.velocities = np.column_stack(
            (np.cos(angles) * speeds, np.sin(angles) * speeds)
        ).astype(np.float32)

    def advance(self) -> None:
        offsets = self.positions[np.newaxis, :, :] - self.positions[:, np.newaxis, :]
        offsets = (offsets + self._bounds / 2) % self._bounds - self._bounds / 2
        distance_squared = np.sum(offsets**2, axis=2)
        not_self = distance_squared > 0

        same_flock = self.flock_ids[:, np.newaxis] == self.flock_ids[np.newaxis, :]
        nearby = not_self & same_flock
        close = not_self & (distance_squared < self.separation_radius**2)

        alignment = self._masked_mean(
            np.broadcast_to(self.velocities, offsets.shape), nearby
        )
        has_neighbors = np.any(nearby, axis=1)
        alignment[has_neighbors] -= self.velocities[has_neighbors]
        cohesion = self._masked_mean(offsets, nearby)

        separation_weights = np.zeros_like(distance_squared)
        np.divide(1, distance_squared, out=separation_weights, where=close)
        separation = -np.sum(offsets * separation_weights[:, :, np.newaxis], axis=1)

        self.velocities += (
            alignment * self.alignment_weight
            + cohesion * self.cohesion_weight
            + separation * self.separation_weight
        )
        speed = np.linalg.norm(self.velocities, axis=1, keepdims=True)
        target_speed = np.clip(speed, self.minimum_speed, self.maximum_speed)
        self.velocities *= target_speed / np.maximum(speed, 0.001)
        self.positions = (self.positions + self.velocities) % self._bounds

    @staticmethod
    def _masked_mean(values: np.ndarray, mask: np.ndarray) -> np.ndarray:
        counts = np.sum(mask, axis=1, keepdims=True)
        totals = np.sum(values * mask[:, :, np.newaxis], axis=1)
        means = np.zeros_like(totals)
        np.divide(totals, counts, out=means, where=counts > 0)
        return means
