"""Static Valley Metro rail geometry and per-route direction semantics.

Point lists are simplified vertices (Ramer-Douglas-Peucker, ~0.02nm
tolerance) of the track alignment from Valley Metro's published GTFS static
feed: https://www.phoenixopendata.com/dataset/general-transit-feed-specification
"""

RAIL_LINE_A: tuple[tuple[float, float], ...] = (
    (33.44706, -112.07442),
    (33.44629, -112.06788),
    (33.44714, -112.06539),
    (33.44717, -112.02845),
    (33.44822, -112.02481),
    (33.44815, -111.98663),
    (33.44515, -111.96013),
    (33.44427, -111.95809),
    (33.44080, -111.95482),
    (33.43932, -111.94880),
    (33.43665, -111.94466),
    (33.43466, -111.94376),
    (33.42877, -111.94344),
    (33.42787, -111.94288),
    (33.42739, -111.93924),
    (33.42293, -111.92942),
    (33.41476, -111.92002),
    (33.41532, -111.79074),
)

STREETCAR_LINE: tuple[tuple[float, float], ...] = (
    (33.42935, -111.93268),
    (33.43064, -111.93653),
    (33.42976, -111.93891),
    (33.42926, -111.94273),
    (33.42813, -111.94252),
    (33.42667, -111.94338),
    (33.42456, -111.94338),
    (33.42195, -111.94239),
    (33.42180, -111.94004),
    (33.41700, -111.93998),
    (33.41552, -111.93922),
    (33.41462, -111.93712),
    (33.41470, -111.91698),
)

LINE_GEOMETRY: dict[str, tuple[tuple[float, float], ...]] = {
    "A": RAIL_LINE_A,
    "S": STREETCAR_LINE,
}

# Valley Metro's own GTFS direction labels are East/West for the A Line,
# which map directly. The Streetcar's labels are North/South, but its local
# track trends diagonally: direction_id 1 (labeled "South") actually runs
# toward the line's east end, and 0 (labeled "North") toward its west end.
DIRECTION_BY_ROUTE_AND_ID: dict[str, dict[int, str]] = {
    "A": {0: "east", 1: "west"},
    "S": {0: "west", 1: "east"},
}
