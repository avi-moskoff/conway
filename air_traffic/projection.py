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


def offset_to_latlon(
    east: float, north: float, home_latitude: float, home_longitude: float
) -> tuple[float, float]:
    """Return latitude/longitude for an east/north offset. Inverse of offset_nautical_miles."""
    latitude = home_latitude + north / 60.0
    longitude = home_longitude + east / (60.0 * cos(radians(home_latitude)))
    return latitude, longitude


def _pixel_scale(radius_nm: float, width: int, height: int) -> tuple[float, float, float]:
    """Return (half_width, half_height, pixels_per_nm) for a frame.

    radius_nm is the visible half-extent along the frame's shorter axis.
    pixels_per_nm is identical for both axes so real-world angles aren't
    distorted - the longer axis simply reaches farther in nm terms, at the
    same physical scale, rather than being independently stretched to fill
    its own half-dimension.
    """
    half_width = (width - 1) / 2
    half_height = (height - 1) / 2
    return half_width, half_height, min(half_width, half_height) / radius_nm


def project_offset(
    east: float, north: float, radius_nm: float, width: int, height: int
) -> tuple[int, int]:
    """Project an east/north nautical-mile offset onto pixel coordinates.

    Does not check whether the offset falls within the visible rectangle;
    callers that need containment should use project_position or
    clip_segment_to_radius.
    """
    half_width, half_height, scale = _pixel_scale(radius_nm, width, height)
    x = round(half_width + east * scale)
    y = round(half_height - north * scale)
    return min(width - 1, max(0, x)), min(height - 1, max(0, y))


def pixel_to_offset(
    x: float, y: float, radius_nm: float, width: int, height: int
) -> tuple[float, float]:
    """Return the east/north nautical-mile offset for a pixel coordinate.

    The exact arithmetic inverse of project_offset (ignoring the edge
    clamping project_offset applies on the way out).
    """
    half_width, half_height, scale = _pixel_scale(radius_nm, width, height)
    east = (x - half_width) / scale
    north = (half_height - y) / scale
    return east, north


def offset_within_frame(
    east: float, north: float, radius_nm: float, width: int, height: int
) -> bool:
    """Return whether an east/north offset falls within the visible rectangle."""
    half_width, half_height, scale = _pixel_scale(radius_nm, width, height)
    return abs(east) * scale <= half_width and abs(north) * scale <= half_height


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
    if not offset_within_frame(east, north, radius_nm, width, height):
        return None
    return project_offset(east, north, radius_nm, width, height)


def _project_onto_polyline(
    east: float, north: float, polyline: list[tuple[float, float]]
) -> tuple[tuple[float, float], float]:
    """Return the closest point on a polyline and its distance along the path from polyline[0]."""
    cumulative = 0.0
    best_point = (east, north)
    best_arc_length = 0.0
    best_distance_sq = float("inf")
    for (e1, n1), (e2, n2) in zip(polyline, polyline[1:]):
        dx, dy = e2 - e1, n2 - n1
        length_sq = dx * dx + dy * dy
        segment_length = length_sq**0.5
        if length_sq == 0:
            t = 0.0
        else:
            t = max(0.0, min(1.0, ((east - e1) * dx + (north - n1) * dy) / length_sq))
        point = (e1 + dx * t, n1 + dy * t)
        distance_sq = (east - point[0]) ** 2 + (north - point[1]) ** 2
        if distance_sq < best_distance_sq:
            best_distance_sq = distance_sq
            best_point = point
            best_arc_length = cumulative + segment_length * t
        cumulative += segment_length
    return best_point, best_arc_length


def nearest_point_on_polyline(
    east: float, north: float, polyline: list[tuple[float, float]]
) -> tuple[float, float]:
    """Return the closest point on a connected polyline to an east/north offset."""
    point, _ = _project_onto_polyline(east, north, polyline)
    return point


def polyline_arc_length(
    east: float, north: float, polyline: list[tuple[float, float]]
) -> float:
    """Return the distance along the polyline (from polyline[0]) to the point closest to (east, north)."""
    _, arc_length = _project_onto_polyline(east, north, polyline)
    return arc_length


def clip_segment_to_radius(
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    radius_nm: float,
    width: int,
    height: int,
) -> tuple[float, float, float, float] | None:
    """Clip a line segment to the visible rectangle for this radius/frame.

    radius_nm is the visible half-extent along the frame's shorter axis, so
    the box clipped to uses the same angle-preserving scale as
    project_offset: the long axis is clipped at its proportionally larger
    extent rather than radius_nm on both axes.

    Returns the clipped sub-segment's endpoints, or None if the segment
    doesn't intersect the visible rectangle at all.
    """
    half_width, half_height, scale = _pixel_scale(radius_nm, width, height)
    half_width_nm = half_width / scale
    half_height_nm = half_height / scale
    dx, dy = x2 - x1, y2 - y1
    t0, t1 = 0.0, 1.0
    for p, q in (
        (-dx, x1 + half_width_nm),
        (dx, half_width_nm - x1),
        (-dy, y1 + half_height_nm),
        (dy, half_height_nm - y1),
    ):
        if p == 0:
            if q < 0:
                return None
            continue
        r = q / p
        if p < 0:
            if r > t1:
                return None
            if r > t0:
                t0 = r
        else:
            if r < t0:
                return None
            if r < t1:
                t1 = r
    if t0 > t1:
        return None
    return (x1 + t0 * dx, y1 + t0 * dy, x1 + t1 * dx, y1 + t1 * dy)
