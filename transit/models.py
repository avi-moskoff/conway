from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Train:
    vehicle_id: str
    route_id: str
    direction_id: int | None
    latitude: float
    longitude: float
    label: str | None = None
    seen_seconds: float = 0.0
    trip_id: str | None = None


@dataclass(frozen=True, slots=True)
class StopArrival:
    trip_id: str
    route_id: str
    direction_id: int | None
    stop_id: str
    arrival_epoch: float
