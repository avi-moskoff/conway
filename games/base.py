from abc import ABC, abstractmethod

import numpy as np


class Game(ABC):
    """Interface implemented by every game the runner can host."""

    def __init__(self, height: int, width: int) -> None:
        self.height = height
        self.width = width

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
