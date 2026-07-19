import numpy as np

from games.base import Game


class BoidsGame(Game):
    """A flocking simulation sized for the LED matrix."""

    frame_delay_seconds = 0.05
    perception_radius = 9
    separation_radius = 4
    alignment_weight = 0.04
    cohesion_weight = 0.003
    separation_weight = 0.3
    obstacle_avoidance_radius = 8
    obstacle_avoidance_weight = 0.8
    obstacle_lookahead_frames = 4
    obstacle_count = 8
    minimum_speed = 0.4
    maximum_speed = 1.5

    def __init__(self, height: int, width: int, boid_count: int = 36) -> None:
        super().__init__(height, width)
        self.boid_count = boid_count
        self._bounds = np.array([width, height], dtype=np.float32)
        self.obstacles = np.empty((self.obstacle_count, 2), dtype=np.float32)
        self.positions = np.empty((boid_count, 2), dtype=np.float32)
        self.velocities = np.empty((boid_count, 2), dtype=np.float32)
        self.reset()

    @property
    def frame(self) -> np.ndarray:
        frame = np.zeros((self.height, self.width, 3), dtype=np.uint8)
        pixel_bounds = self._bounds.astype(int)
        heads = np.rint(self.positions).astype(int) % pixel_bounds
        obstacles = np.rint(self.obstacles).astype(int) % pixel_bounds

        frame[heads[:, 1], heads[:, 0]] = (255, 255, 255)
        frame[obstacles[:, 1], obstacles[:, 0]] = (255, 0, 0)
        return frame

    def reset(self) -> None:
        self.obstacles = self._random_obstacles()
        self.positions = (
            np.random.random((self.boid_count, 2)) * self._bounds
        ).astype(np.float32)
        angles = np.random.uniform(0, 2 * np.pi, self.boid_count)
        speeds = np.random.uniform(0.5, 1.25, self.boid_count)
        self.velocities = np.column_stack(
            (np.cos(angles) * speeds, np.sin(angles) * speeds)
        ).astype(np.float32)

    def _random_obstacles(self) -> np.ndarray:
        pixel_count = self.height * self.width
        if self.obstacle_count > pixel_count:
            raise ValueError("obstacle_count cannot exceed the number of pixels")

        pixels = np.random.choice(pixel_count, self.obstacle_count, replace=False)
        return np.column_stack((pixels % self.width, pixels // self.width)).astype(
            np.float32
        )

    def advance(self) -> None:
        offsets = self.positions[np.newaxis, :, :] - self.positions[:, np.newaxis, :]
        offsets = (offsets + self._bounds / 2) % self._bounds - self._bounds / 2
        distance_squared = np.sum(offsets**2, axis=2)
        not_self = distance_squared > 0

        nearby = not_self & (distance_squared < self.perception_radius**2)
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

        predicted_positions = (
            self.positions + self.velocities * self.obstacle_lookahead_frames
        ) % self._bounds
        obstacle_offsets = (
            self.obstacles[np.newaxis, :, :] - predicted_positions[:, np.newaxis, :]
        )
        obstacle_offsets = (
            obstacle_offsets + self._bounds / 2
        ) % self._bounds - self._bounds / 2
        obstacle_distance_squared = np.sum(obstacle_offsets**2, axis=2)
        near_obstacle = (
            (obstacle_distance_squared > 0)
            & (obstacle_distance_squared < self.obstacle_avoidance_radius**2)
        )
        obstacle_weights = np.zeros_like(obstacle_distance_squared)
        np.divide(
            1,
            obstacle_distance_squared,
            out=obstacle_weights,
            where=near_obstacle,
        )
        obstacle_avoidance = -np.sum(
            obstacle_offsets * obstacle_weights[:, :, np.newaxis], axis=1
        )

        self.velocities += (
            alignment * self.alignment_weight
            + cohesion * self.cohesion_weight
            + separation * self.separation_weight
            + obstacle_avoidance * self.obstacle_avoidance_weight
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
