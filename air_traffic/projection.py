from math import cos, radians


def offset_nautical_miles(
    latitude: float,
    longitude: float,
    home_latitude: float,
    home_longitude: float,
) -> tuple[float, float]:
    """Return east and north offsets using a local equirectangular projection."""
    north = (latitude - home_latitude) * 60.0
    east = (longitude - home_longitude) * 60.0 * cos(radians(home_latitude))
    return east, north


def project_position(
    latitude: float,
    longitude: float,
    home_latitude: float,
    home_longitude: float,
    radius_nm: float,
    width: int,
    height: int,
) -> tuple[int, int] | None:
    east, north = offset_nautical_miles(
        latitude, longitude, home_latitude, home_longitude
    )
    if east * east + north * north > radius_nm * radius_nm:
        return None

    half_width = (width - 1) / 2
    half_height = (height - 1) / 2
    x = round(half_width + east / radius_nm * half_width)
    y = round(half_height - north / radius_nm * half_height)
    return min(width - 1, max(0, x)), min(height - 1, max(0, y))
