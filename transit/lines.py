"""Static Valley Metro rail geometry and per-route direction semantics.

Point lists are simplified vertices (Ramer-Douglas-Peucker, ~0.02nm
tolerance) of the track alignment from Valley Metro's published GTFS static
feed: https://www.phoenixopendata.com/dataset/general-transit-feed-specification
"""

from air_traffic.projection import offset_nautical_miles

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

# A Line station platforms: (stop_id, direction_id, latitude, longitude, name).
# One row per directional platform, from the same GTFS static feed as above
# (stops.txt / stop_times.txt / trips.txt). Two stops share a name where
# east/west platforms sit at the same station. The line's two termini
# (Gilbert Rd/Main St) are omitted: trains reverse there, so a single
# platform serves both directions and can't be assigned one cleanly.
A_LINE_STATIONS: tuple[tuple[str, int, float, float, str], ...] = (
    ("9000", 0, 33.447199, -112.055664, "12th St/Jefferson"),
    ("9002", 0, 33.447229, -112.029262, "24th St/Jefferson"),
    ("9003", 0, 33.448102, -111.999879, "38th St/Washington"),
    ("9004", 0, 33.446274, -112.069297, "3rd St/Jefferson"),
    ("9005", 0, 33.448168, -111.987980, "44th St/Washington"),
    ("9008", 0, 33.438047, -111.946605, "Center Pkwy/Washington"),
    ("9010", 0, 33.414759, -111.916899, "Dorsey Ln/Apache Blvd"),
    ("9014", 0, 33.414727, -111.908268, "McClintock Dr/Apache Blvd"),
    ("9016", 0, 33.427452, -111.940697, "Mill Ave/3rd St"),
    ("9019", 0, 33.414821, -111.888114, "Price-101/Apache Blvd"),
    ("9020", 0, 33.442008, -111.956107, "Priest Dr/Washington St"),
    ("9022", 0, 33.414783, -111.900799, "Smith-Martin/Apache Blvd"),
    ("9023", 0, 33.414855, -111.870907, "Sycamore/Main St"),
    ("9025", 0, 33.420732, -111.926970, "University Dr/Rural Rd"),
    ("9027", 0, 33.426069, -111.935961, "Veterans Way/College Ave"),
    ("9126", 0, 33.414940, -111.855564, "Alma School/Main St"),
    ("9353", 0, 33.415103, -111.839073, "Country Club/Main St"),
    ("9499", 0, 33.415096, -111.830654, "Center/Main St"),
    ("9508", 0, 33.415066, -111.822135, "Mesa Dr/Main St"),
    ("9765", 0, 33.446946, -111.975231, "50th St/Washington St"),
    ("9794", 0, 33.447106, -112.074424, "Downtown Phx Hub/Jefferson St"),
    ("9028", 1, 33.448248, -112.057179, "12th St/Washington"),
    ("9030", 1, 33.448192, -112.029285, "24th St/Washington"),
    ("9031", 1, 33.448102, -111.999879, "38th St/Washington"),
    ("9032", 1, 33.448352, -112.070595, "3rd St/Washington"),
    ("9033", 1, 33.448168, -111.987980, "44th St/Washington"),
    ("9036", 1, 33.438047, -111.946605, "Center Pkwy/Washington"),
    ("9038", 1, 33.414759, -111.916899, "Dorsey Ln/Apache Blvd"),
    ("9041", 1, 33.414727, -111.908268, "McClintock Dr/Apache Blvd"),
    ("9043", 1, 33.427559, -111.940700, "Mill Ave/3rd St"),
    ("9046", 1, 33.414821, -111.888114, "Price-101/Apache Blvd"),
    ("9047", 1, 33.442008, -111.956107, "Priest Dr/Washington St"),
    ("9049", 1, 33.414783, -111.900799, "Smith-Martin/Apache Blvd"),
    ("9050", 1, 33.414855, -111.870907, "Sycamore/Main St"),
    ("9052", 1, 33.420815, -111.926894, "University Dr/Rural Rd"),
    ("9054", 1, 33.426134, -111.935939, "Veterans Way/College Ave"),
    ("9055", 1, 33.448890, -112.073866, "Washington/Central Ave"),
    ("9125", 1, 33.414940, -111.855564, "Alma School/Main St"),
    ("9347", 1, 33.415103, -111.839073, "Country Club/Main St"),
    ("9498", 1, 33.415096, -111.830654, "Center/Main St"),
    ("9502", 1, 33.415066, -111.822135, "Mesa Dr/Main St"),
    ("9764", 1, 33.447034, -111.975307, "50th St/Washington St"),
    ("9795", 1, 33.448331, -112.074447, "Downtown Phx Hub/Washington St"),
)


def nearest_station_stop_id(
    home_latitude: float, home_longitude: float, direction_id: int
) -> str | None:
    """Return the A Line platform stop_id closest to home for a given direction."""
    best_stop_id: str | None = None
    best_distance_sq = float("inf")
    for stop_id, station_direction_id, latitude, longitude, _name in A_LINE_STATIONS:
        if station_direction_id != direction_id:
            continue
        east, north = offset_nautical_miles(
            latitude, longitude, home_latitude, home_longitude
        )
        distance_sq = east * east + north * north
        if distance_sq < best_distance_sq:
            best_distance_sq = distance_sq
            best_stop_id = stop_id
    return best_stop_id
