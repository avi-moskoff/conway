from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class WeatherSample:
    latitude: float
    longitude: float
    temperature_f: float
    precipitation_mm: float
    weather_code: int


@dataclass(frozen=True, slots=True)
class AirQualitySample:
    latitude: float
    longitude: float
    us_aqi: float
