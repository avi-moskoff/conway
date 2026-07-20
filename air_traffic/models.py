from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Aircraft:
    icao_hex: str
    latitude: float
    longitude: float
    callsign: str | None = None
    track_degrees: float | None = None
    ground_speed_knots: float | None = None
    altitude_feet: int | None = None
    on_ground: bool = False
    seen_seconds: float = 0.0
    registration: str | None = None
    aircraft_type: str | None = None

    @property
    def label(self) -> str:
        return self.callsign or self.registration or self.aircraft_type or self.icao_hex


@dataclass(frozen=True, slots=True)
class FlightRoute:
    callsign: str
    origin: str | None = None
    destination: str | None = None
    plausible: bool | None = None

    @property
    def label(self) -> str | None:
        if self.origin and self.destination:
            return f"{self.origin}>{self.destination}"
        return self.origin or self.destination
