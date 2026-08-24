from games.base import Game
from games.boids import BoidsGame
from games.conway import GameOfLife
from games.flight_radar import FlightRadarGame
from games.langton import Langton
from games.weather_radar import WeatherRadarGame

__all__ = [
    "BoidsGame",
    "FlightRadarGame",
    "Game",
    "GameOfLife",
    "Langton",
    "WeatherRadarGame",
]
