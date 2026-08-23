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


def project_offset(
    east: float, north: float, radius_nm: float, width: int, height: int
) -> tuple[int, int]:
    """Project an east/north nautical-mile offset onto pixel coordinates.

    Does not check whether the offset falls within radius_nm; callers that
    need containment should use project_position or clip_segment_to_radius.
    """
    half_width = (width - 1) / 2
    half_height = (height - 1) / 2
    x = round(half_width + east / radius_nm * half_width)
    y = round(half_height - north / radius_nm * half_height)
    return min(width - 1, max(0, x)), min(height - 1, max(0, y))


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
    return project_offset(east, north, radius_nm, width, height)


def nearest_point_on_polyline(
    east: float, north: float, polyline: list[tuple[float, float]]
) -> tuple[float, float]:
    """Return the closest point on a connected polyline to an east/north offset."""
    best: tuple[float, float] | None = None
    best_distance_sq = float("inf")
    for (e1, n1), (e2, n2) in zip(polyline, polyline[1:]):
        dx, dy = e2 - e1, n2 - n1
        length_sq = dx * dx + dy * dy
        if length_sq == 0:
            t = 0.0
        else:
            t = max(0.0, min(1.0, ((east - e1) * dx + (north - n1) * dy) / length_sq))
        point = (e1 + dx * t, n1 + dy * t)
        distance_sq = (east - point[0]) ** 2 + (north - point[1]) ** 2
        if distance_sq < best_distance_sq:
            best_distance_sq = distance_sq
            best = point
    if best is None:
        return east, north
    return best


def clip_segment_to_radius(
    x1: float, y1: float, x2: float, y2: float, radius: float
) -> tuple[float, float, float, float] | None:
    """Clip a line segment to the disc of the given radius around the origin.

    Returns the clipped sub-segment's endpoints, or None if the segment
    doesn't intersect the disc at all.
    """
    dx, dy = x2 - x1, y2 - y1
    a = dx * dx + dy * dy
    if a == 0:
        return (x1, y1, x2, y2) if x1 * x1 + y1 * y1 <= radius * radius else None
    b = 2 * (x1 * dx + y1 * dy)
    c = x1 * x1 + y1 * y1 - radius * radius
    discriminant = b * b - 4 * a * c
    if discriminant < 0:
        return None
    sqrt_discriminant = discriminant**0.5
    t_start = max(0.0, (-b - sqrt_discriminant) / (2 * a))
    t_end = min(1.0, (-b + sqrt_discriminant) / (2 * a))
    if t_start > t_end:
        return None
    return (
        x1 + dx * t_start,
        y1 + dy * t_start,
        x1 + dx * t_end,
        y1 + dy * t_end,
    )
