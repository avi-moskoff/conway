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

        return cls(
            home_latitude=latitude,
            home_longitude=longitude,
            airport_latitude=airport_latitude,
            airport_longitude=airport_longitude,
            radius_nm=radius,
            poll_seconds=poll_seconds,
            api_url=os.getenv("CONWAY_ADSB_API_URL", "https://api.adsb.lol"),
            api_key=os.getenv("CONWAY_ADSB_API_KEY") or None,
        )
