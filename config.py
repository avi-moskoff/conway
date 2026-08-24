import os
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class FlightRadarConfig:
    home_latitude: float
    home_longitude: float
    radius_nm: float = 8.0
    poll_seconds: float = 15.0
    api_url: str = "https://api.adsb.lol"
    api_key: str | None = None
    airport_latitude: float | None = None
    airport_longitude: float | None = None
    rail_api_url: str = "https://mna.mecatran.com/utw/ws/gtfsfeed/vehicles/valleymetro"
    rail_trip_updates_url: str = "https://mna.mecatran.com/utw/ws/gtfsfeed/realtime/valleymetro"
    # Published in Phoenix's public open-data catalog for its GTFS-RT listings,
    # not a private credential: https://www.phoenixopendata.com/dataset/general-transit-feed-specification
    rail_api_key: str = "4f22263f69671d7f49726c3011333e527368211f"
    rail_poll_seconds: float = 15.0

    @classmethod
    def from_environment(cls) -> "FlightRadarConfig | None":
        latitude_text = os.getenv("CONWAY_HOME_LATITUDE")
        longitude_text = os.getenv("CONWAY_HOME_LONGITUDE")
        airport_latitude_text = os.getenv("CONWAY_AIRPORT_LATITUDE")
        airport_longitude_text = os.getenv("CONWAY_AIRPORT_LONGITUDE")
        if latitude_text is None and longitude_text is None:
            return None
        if latitude_text is None or longitude_text is None:
            raise ValueError("Both CONWAY_HOME_LATITUDE and CONWAY_HOME_LONGITUDE are required")
        if (airport_latitude_text is None) != (airport_longitude_text is None):
            raise ValueError(
                "Both CONWAY_AIRPORT_LATITUDE and CONWAY_AIRPORT_LONGITUDE are required"
            )

        try:
            latitude = float(latitude_text)
            longitude = float(longitude_text)
            airport_latitude = (
                float(airport_latitude_text)
                if airport_latitude_text is not None
                else None
            )
            airport_longitude = (
                float(airport_longitude_text)
                if airport_longitude_text is not None
                else None
            )
            radius = float(os.getenv("CONWAY_FLIGHT_RADIUS_NM", "8"))
            poll_seconds = float(os.getenv("CONWAY_ADSB_POLL_SECONDS", "15"))
            rail_poll_seconds = float(os.getenv("CONWAY_RAIL_POLL_SECONDS", "15"))
        except ValueError as error:
            raise ValueError("Flight radar configuration must contain numbers") from error
        if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
            raise ValueError("Flight radar coordinates are out of range")
        if airport_latitude is not None and not -90 <= airport_latitude <= 90:
            raise ValueError("Airport latitude is out of range")
        if airport_longitude is not None and not -180 <= airport_longitude <= 180:
            raise ValueError("Airport longitude is out of range")
        if not 1 <= radius <= 250:
            raise ValueError("CONWAY_FLIGHT_RADIUS_NM must be between 1 and 250")
        if poll_seconds < 5:
            raise ValueError("CONWAY_ADSB_POLL_SECONDS must be at least 5")
        if rail_poll_seconds < 5:
            raise ValueError("CONWAY_RAIL_POLL_SECONDS must be at least 5")

        return cls(
            home_latitude=latitude,
            home_longitude=longitude,
            airport_latitude=airport_latitude,
            airport_longitude=airport_longitude,
            radius_nm=radius,
            poll_seconds=poll_seconds,
            api_url=os.getenv("CONWAY_ADSB_API_URL", "https://api.adsb.lol"),
            api_key=os.getenv("CONWAY_ADSB_API_KEY") or None,
            rail_api_url=os.getenv(
                "CONWAY_RAIL_API_URL",
                "https://mna.mecatran.com/utw/ws/gtfsfeed/vehicles/valleymetro",
            ),
            rail_trip_updates_url=os.getenv(
                "CONWAY_RAIL_TRIP_UPDATES_URL",
                "https://mna.mecatran.com/utw/ws/gtfsfeed/realtime/valleymetro",
            ),
            rail_api_key=os.getenv(
                "CONWAY_RAIL_API_KEY", "4f22263f69671d7f49726c3011333e527368211f"
            ),
            rail_poll_seconds=rail_poll_seconds,
        )


@dataclass(frozen=True, slots=True)
class WeatherRadarConfig:
    home_latitude: float
    home_longitude: float
    radius_nm: float = 15.0
    poll_seconds: float = 600.0
    landmarks: tuple[tuple[str, float, float], ...] = ()

    @classmethod
    def from_environment(cls) -> "WeatherRadarConfig | None":
        latitude_text = os.getenv("CONWAY_HOME_LATITUDE")
        longitude_text = os.getenv("CONWAY_HOME_LONGITUDE")
        if latitude_text is None and longitude_text is None:
            return None
        if latitude_text is None or longitude_text is None:
            raise ValueError("Both CONWAY_HOME_LATITUDE and CONWAY_HOME_LONGITUDE are required")

        try:
            latitude = float(latitude_text)
            longitude = float(longitude_text)
            radius = float(os.getenv("CONWAY_WEATHER_RADIUS_NM", "15"))
            poll_seconds = float(os.getenv("CONWAY_WEATHER_POLL_SECONDS", "600"))
        except ValueError as error:
            raise ValueError("Weather radar configuration must contain numbers") from error
        if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
            raise ValueError("Weather radar coordinates are out of range")
        if not 1 <= radius <= 250:
            raise ValueError("CONWAY_WEATHER_RADIUS_NM must be between 1 and 250")
        if poll_seconds < 60:
            raise ValueError("CONWAY_WEATHER_POLL_SECONDS must be at least 60")

        return cls(
            home_latitude=latitude,
            home_longitude=longitude,
            radius_nm=radius,
            poll_seconds=poll_seconds,
            landmarks=cls._parse_landmarks(os.getenv("CONWAY_WEATHER_LANDMARKS", "")),
        )

    @staticmethod
    def _parse_landmarks(text: str) -> tuple[tuple[str, float, float], ...]:
        landmarks = []
        for entry in text.split(";"):
            entry = entry.strip()
            if not entry:
                continue
            parts = entry.split(":")
            if len(parts) != 3:
                raise ValueError(
                    'CONWAY_WEATHER_LANDMARKS entries must look like "Name:lat:lon"'
                )
            name, latitude_text, longitude_text = parts
            try:
                latitude = float(latitude_text)
                longitude = float(longitude_text)
            except ValueError as error:
                raise ValueError(
                    "CONWAY_WEATHER_LANDMARKS coordinates must be numbers"
                ) from error
            if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
                raise ValueError("CONWAY_WEATHER_LANDMARKS coordinates are out of range")
            landmarks.append((name.strip(), latitude, longitude))
        return tuple(landmarks)
