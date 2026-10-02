# Conway

> Note on AI usage: This project was made for fun, and I used AI when I thought it would make the project more fun to do so.

A 64×64 HUB75 RGB LED matrix display for a Raspberry Pi. It started as a
Conway's Game of Life simulator, which is where the name comes from, and has
grown into a small ambient display: a rotary encoder flips between generative
animations and live views of what is happening around a configured home
location, including aircraft overhead, light-rail arrivals, weather, air
quality, and satellite dust imagery.

Press the rotary encoder in to open the screen switcher: a vertical list of
every screen, with the current one highlighted. Turn the encoder to move the
highlight and press it in again to switch to it, closing the switcher; the
button light blinks while the switcher is open. Each screen keeps its state
while it's inactive, so switching back resumes where it left off.

While the switcher is closed, the encoder and button instead act on the active
screen: turning the encoder cycles through that screen's own views for the two
live screens (see [Live views](#live-views) below) - the three animations have
only one view each, so rotating does nothing there. The button always means
the same thing everywhere: force-refresh what's showing - a fresh random start
for an animation, or an immediate retry of the current view's poll for a live
view - and it does nothing while the switcher is open. The button lights while
the program is running. When the program exits, it clears the matrix and turns
off the button light.

## Screens

The switcher lists the screens in the order given here. The two live
screens are added only when a home location is configured (see
[Configuration](#configuration)); without one, the display runs just the four
animations.

### Animations

- **Conway's Game of Life** starts from a random board that wraps at the edges.
  The button deals a new random board.
- **Langton's Ant** follows a cyan ant across a blank board, starting from the
  center. The button clears the board and returns the ant to the center.
- **Boids** is a flock of 36 white boids steering around eight red obstacle
  pixels. The button scatters a new flock and new obstacles.
- **Snake** is played on a wrapped 32x32 grid. Turning the knob turns the
  snake's head 90 degrees per click; the button restarts.

### Live views

The live screens are north-up maps centered on your home location, drawn above
an 8-pixel text ticker. Short labels stay centered and longer ones scroll. A
inverted pixel in the top-left corner (whatever color is there, flipped) means
the latest poll of the current view's data source failed, so what you see may
be out of date; the ticker names the failure on the weather views. A live screen
polls its data source only while it is selected.

**Flight radar** has three views, and the encoder cycles through them while it's the active screen:

- *Aircraft* shows nearby aircraft from [adsb.lol](https://adsb.lol/). The
  closest aircraft is red and the rest are green. Home is the center pixel,
  drawn by inverting whatever is under it, and an optional airport appears as
  a blue pixel. The ticker shows the
  closest aircraft's callsign and, when one is available, its estimated route
  (for example `ABC123 PHX>LAX`). It reads `CLEAR SKY` when nothing is in range
  and `NO SIGNAL` when the data is stale.
- *Westbound ETA* and *Eastbound ETA* show Valley Metro light rail. The A Line
  and Streetcar tracks are drawn in blue, with eastbound trains in green and
  westbound trains in yellow. The next train due at the A Line station nearest
  home is drawn white, and home itself is a fixed red center pixel on these two
  views. The ticker counts down to it (`W ETA 4M`, `E ETA <1M`,
  or `--` when no arrival is known). It reads `NO RAIL` when the feed is stale.
  The track and station data is hardcoded for Valley Metro's Phoenix-Tempe-Mesa
  service, so these views are only useful near it.

**Weather radar** also has three views, and the encoder cycles through them the same way:

- *Conditions* shows temperature and a cloud-and-rain field: black for clear
  sky up to gray for overcast, shifting toward blue as rainfall rises, with a
  ticker such as `72F CLEAR`.
- *Air quality* colors the map on the US AQI scale with a single amber hue,
  from black through amber to white, with a ticker such as `AQI 42 GOOD`.
- *Dust* is a live GOES satellite Dust RGB crop filtered down to one signal:
  pixels that match dust are magenta and everything else is black, for
  watching a dust storm or haboob approach. The ticker shows the image time in UTC (`DUST 18:31Z`).

The conditions and air-quality fields are interpolated from a small grid of
points around home, so they read as a continuous map at the same north-up scale
as the radar. Home and each configured landmark are single pixels drawn by
inverting the average color of their neighboring pixels (so a marker stays
visible whatever is underneath), falling back to white or black when that
inverse would be too close in brightness, as with mid-gray. Switching
weather views also nudges the poller for the view you switch into, so one that
is waiting out a retry backoff after a failure tries again immediately.

## Hardware

This project runs on:

- Raspberry Pi Zero 2 W
- Adafruit RGB Matrix Bonnet for Raspberry Pi
- 64×64 HUB75 RGB LED matrix
- Rotary encoder
- Illuminated push button
- A suitably rated 5 V supply for the matrix

GPIO numbers below use BCM numbering.

```text
┌───────────────────────────────┐
│ Raspberry Pi Zero 2 W         │
│ + RGB Matrix Bonnet           │
│                               │
│ GPIO 14 ── green wire ────────│── button switch ── GND
│ GPIO 15 ── red wire ──────────│── resistor ── button light ── GND
│ GPIO 18 ── yellow wire ───────│── Encoder A
│ GPIO 19 ── white wire ────────│── Encoder B
│ GPIO 25 ── ? wire ────────────│── Encoder push switch
│ GND ──────────────────────────│── Encoder common
│                               │
│ Bonnet HUB75 output ──────────│── HUB75 ribbon ── 64×64 matrix
│ Bonnet power input ◀──────────│── regulated 5 V matrix supply
└───────────────────────────────┘
```

Wire colors in this document identify the physical wiring, not the colors of
the components (the encoder push switch's wire color above is a placeholder -
fill in the actual color for your build). The button light needs an
appropriate current-limiting resistor unless one is built into the button. The
`gpiozero` inputs use pull-ups, so the button switch, encoder push switch, and
encoder common connect to ground.

### Important: solder the E-address jumper

**A 64×64 matrix requires the Bonnet's E-address jumper. The display will not
scan all 64 rows correctly unless this jumper is configured.**

On the underside of the Bonnet, bridge the center **E** pad to **8** with solder
for the 64×64 panels sold by Adafruit:

```text
Bonnet E-address pads

    [ 16 ] [ E ]═══[ 8 ]
                 solder
```

Some third-party panels use the `16` pad instead, so check the panel's
datasheet. See Adafruit's
[64×64 matrix setup instructions](https://learn.adafruit.com/adafruit-rgb-matrix-bonnet-for-raspberry-pi/matrix-setup)
and [Bonnet pinout](https://learn.adafruit.com/adafruit-rgb-matrix-bonnet-for-raspberry-pi/pinouts).

### GPIO 18 and matrix-driver mode

The yellow encoder wire uses GPIO 18. Install the RGB matrix driver using its
**convenience** option. The driver's quality option requires a connection
between GPIO 4 and GPIO 18 and therefore conflicts with the encoder wiring in
this project.

The panel flickers in this configuration. The planned fix - moving the encoder
off GPIO 18 and soldering the GPIO 4 to GPIO 18 jumper - is written up in
[docs/hardware-pwm-mod.md](docs/hardware-pwm-mod.md).

## Controls

| Control            | GPIO | Wire   | Action                                                      |
| ------------------ | ---: | ------ | ----------------------------------------------------------- |
| Button switch      |   14 | Green  | Force-refresh the active screen (new board, retry a poll)   |
| Button light       |   15 | Red    | Program-running indicator; blinks while the switcher is open |
| Encoder A          |   18 | Yellow | Cycle the active screen's views, or move the switcher's highlight |
| Encoder B          |   19 | White  | Cycle the active screen's views, or move the switcher's highlight |
| Encoder push switch|   25 | ?      | Open the switcher, or confirm the highlighted screen         |

## Software setup

The following packages were required on the working Raspberry Pi installation:

```sh
sudo apt update
sudo apt install \
    build-essential \
    cmake \
    git \
    python3-dev \
    cython3 \
    swig \
    libgraphicsmagick++-dev \
    libwebp-dev \
    liblgpio-dev
```

| Package                   | Purpose                                                  |
| ------------------------- | -------------------------------------------------------- |
| `build-essential`         | C/C++ compiler and linker                                |
| `cmake`                   | Builds the current `rpi-rgb-led-matrix` Python extension |
| `git`                     | Fetches the matrix driver from GitHub                    |
| `python3-dev`             | Python headers for native extension modules              |
| `cython3`                 | Native-extension build dependency                        |
| `swig`                    | Builds the Python `lgpio` bindings                       |
| `libgraphicsmagick++-dev` | Optional image-format support in the matrix driver       |
| `libwebp-dev`             | Optional WebP support                                    |
| `liblgpio-dev`            | Headers and library for the `lgpio` GPIO backend         |

The two image libraries are not required by the animations themselves, but
they were part of the known-working matrix-driver build.

### Python dependencies

With [uv](https://docs.astral.sh/uv/) installed, create the environment and
install the dependencies declared by this repository:

```sh
uv sync
```

The application uses NumPy, SciPy, Pillow, GPIO Zero, and the
`rpi-rgb-led-matrix` Python bindings. The matrix bindings are locked from their
GitHub repository under the package name `rgbmatrix`. The working Raspberry Pi
setup also used `lgpio` as GPIO Zero's pin backend; install its Python bindings
if they are not already available in the environment:

```sh
uv pip install lgpio
```

If the matrix binding needs to be rebuilt directly while troubleshooting, the
known-working command was:

```sh
uv pip install --no-build-isolation \
    git+https://github.com/hzeller/rpi-rgb-led-matrix
```

## Configuration

Settings come from environment variables. Under systemd they are read from
`/etc/conway.env`, which keeps your home coordinates out of the repository. For
example:

```text
CONWAY_HOME_LATITUDE=...
CONWAY_HOME_LONGITUDE=...
CONWAY_AIRPORT_LATITUDE=...
CONWAY_AIRPORT_LONGITUDE=...
CONWAY_WEATHER_LANDMARKS=Camelback Mountain:33.5205:-111.9648;South Mountain:33.3306:-112.0533
```

Setting the two home coordinates enables both live screens; setting only one
is an error. Everything else is optional and falls back to the default shown.

| Variable                                        | Default                  | Notes                                                                     |
| ----------------------------------------------- | ------------------------ | ------------------------------------------------------------------------- |
| `CONWAY_HOME_LATITUDE`, `CONWAY_HOME_LONGITUDE` | unset (live views off)   | Center of every live map.                                                 |
| `CONWAY_DISPLAY_ROTATION`                       | `180`                    | Degrees clockwise (`0`, `90`, `180`, `270`) applied to every screen.       |
| `CONWAY_LED_BRIGHTNESS`                         | `50`                     | Panel brightness (1-100). Lower it to test whether flicker is power sag.  |
| `CONWAY_LED_GPIO_SLOWDOWN`                      | `2`                      | Driver GPIO slowdown; raise for row glitches/ghosting.                    |
| `CONWAY_LED_PWM_BITS`                           | driver default (`11`)    | Color depth (1-11). `8`-`9` raises the refresh rate and can cut flicker.  |
| `CONWAY_LED_PWM_LSB_NANOSECONDS`                | driver default (`130`)   | Shortest PWM pulse; lower speeds up refresh.                              |
| `CONWAY_LED_PWM_DITHER_BITS`                    | driver default (`0`)     | Time-dithering bits; raise for smoother low-brightness color.             |
| `CONWAY_LED_LIMIT_REFRESH_HZ`                   | driver default (none)    | Cap the refresh rate for a steadier one.                                  |
| `CONWAY_LOG_LEVEL`                              | `INFO`                   | `DEBUG`, `INFO`, `WARNING`, and so on.                                    |
| `CONWAY_FLIGHT_RADIUS_NM`                       | `8`                      | Map radius for the aircraft and rail views (1-250).                       |
| `CONWAY_ADSB_POLL_SECONDS`                      | `15`                     | Aircraft poll interval (minimum 5).                                       |
| `CONWAY_AIRPORT_LATITUDE`, `CONWAY_AIRPORT_LONGITUDE` | unset              | Optional; set both. Marks an airport on the aircraft map.                 |
| `CONWAY_ADSB_API_URL`, `CONWAY_ADSB_API_KEY`    | `https://api.adsb.lol`, none | Point at another compatible endpoint.                                 |
| `CONWAY_RAIL_POLL_SECONDS`                      | `15`                     | Rail poll interval (minimum 5).                                           |
| `CONWAY_RAIL_API_URL`, `CONWAY_RAIL_TRIP_UPDATES_URL`, `CONWAY_RAIL_API_KEY` | Valley Metro's public feeds | Override the GTFS-realtime vehicle and trip-update feeds and key. |
| `CONWAY_WEATHER_RADIUS_NM`                      | `15`                     | Map radius for conditions and air quality (1-250).                        |
| `CONWAY_WEATHER_POLL_SECONDS`                   | `600`                    | Conditions and air-quality poll interval (minimum 60).                    |
| `CONWAY_WEATHER_LANDMARKS`                      | none                     | Semicolon-separated `Name:latitude:longitude` entries.                    |
| `CONWAY_DUST_RADIUS_NM`                         | `40`                     | Map radius for the dust view (1-250).                                     |
| `CONWAY_DUST_POLL_SECONDS`                      | `300`                    | Dust imagery poll interval (minimum 60).                                  |
| `CONWAY_DUST_SATELLITE`                         | `GOES19`                 | GOES satellite to fetch imagery from.                                     |

### Aircraft

The airport coordinates are optional. When present and within the displayed
radius, the airport appears as a blue pixel. Routes are inferred from callsigns
and shown only when adsb.lol has route data and marks it plausible.

The public [adsb.lol](https://adsb.lol/) service is used by default. Aircraft
positions come from community receivers, so coverage can vary. Origin and
destination labels are not broadcast by the aircraft and should be treated as
best-effort.

The radar makes no requests while another screen is selected. Its aircraft and
route caches live only in RAM, and neither coordinates nor aircraft history are
written to disk by the application.

### Rail

Train positions and arrivals come from Valley Metro's public GTFS-realtime
feeds. The default API key is the one Phoenix publishes in its open-data
catalog rather than a private credential; set `CONWAY_RAIL_API_KEY` to use your
own.

### Weather and dust

Weather and air-quality data come from the free
[Open-Meteo](https://open-meteo.com/) APIs, which need no API key.

The dust view uses a larger default radius (`CONWAY_DUST_RADIUS_NM`) than the
conditions and air-quality views: its source imagery is coarser (roughly 1.2-1.4
km per pixel near the US Southwest) than the interpolated Open-Meteo fields, so
a tighter radius would just look blocky. It's currently only calibrated for the
"Southern Rockies" region (Arizona and nearby) - see the comment above the
calibration constants in `weather/goes_dust.py` for how that calibration was
derived and how to redo it for a different area. `CONWAY_DUST_SATELLITE`
exists because GOES satellites occasionally get swapped out operationally
(GOES-19 itself only became "GOES-East" in April 2025); if NOAA ever retires
`GOES19` from that role, update this to whichever satellite replaces it and
re-derive the calibration the same way - normal satellite station-keeping
drift is far too small to matter, but an operational swap changes the image
source entirely.

### Logging

Routine successful API polls are logged only at `DEBUG`, so the default
`INFO` level records startup, screen changes, and failures without writing a
message every polling interval. Set `CONWAY_LOG_LEVEL=WARNING` for only
problems, or temporarily use `DEBUG` while troubleshooting. When running as a
service, these messages go to systemd-journald; inspect its current footprint
with `journalctl --disk-usage`.

## Running

Run the entry point with the permissions required by the RGB matrix driver:

```sh
sudo ./run.sh
```

The included `conway.service` and `run.sh` provide a systemd deployment for the
Raspberry Pi. Their paths currently assume the project is installed at
`/home/avi/conway`. The service uses `taskset` and `chrt`; both are supplied by
Debian's `util-linux` package and are normally installed already.

To start the service:

```sh
sudo systemctl start conway
```

To stop:

```sh
sudo systemctl stop conway
```

To restart:

```sh
sudo systemctl restart conway
```

After editing `/etc/conway.env` or the service file, reload systemd before
restarting:

```sh
sudo systemctl daemon-reload
sudo systemctl restart conway
```

## Project layout

- `main.py`, `runner.py`, `display.py`, `config.py`: the entry point, the runner
  that hosts one screen at a time and handles the encoder and button, the
  matrix output (including rotation), and environment-driven configuration.
- `games/`: one `Game` subclass per screen (`conway.py`, `langton.py`,
  `boids.py`, `flight_radar.py`, `weather_radar.py`).
- `air_traffic/`: the adsb.lol client and the map-projection math shared by the
  radar views.
- `transit/`: the Valley Metro GTFS-realtime client and static track and station
  data.
- `weather/`: the Open-Meteo and GOES dust clients.
- `tests/`: unit tests that stub out the GPIO and matrix hardware.

To add a screen, subclass `games.base.Game`: implement `frame`, `reset`, and
`advance`; set `menu_label` to how it should read in the switcher (8
characters or fewer - `games/menu.py`'s font doesn't scroll); and optionally
override `activate`, `deactivate`, and `close` for anything that polls a
network service, and `cycle_view` if the screen has more than one view.
Every game must be 64×64. Then register it in `GameRunner._default_games` in
`runner.py`.

Run the tests from the repository root with:

```sh
python -m unittest discover -s tests
```

## Data sources

This project displays live data from a few free, third-party APIs:

- Aircraft positions and routes from [adsb.lol](https://adsb.lol/), a
  community ADS-B aggregator.
- Valley Metro light rail and streetcar positions/arrivals from Phoenix's
  public [GTFS-RT open data](https://www.phoenixopendata.com/dataset/general-transit-feed-specification).
- Weather conditions and air quality from [Open-Meteo](https://open-meteo.com/),
  licensed under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).
  The weather-radar game samples a small grid of points around the configured
  home location and interpolates/color-maps them for the LED matrix, rather
  than displaying the raw values.
- GOES-19 Dust RGB satellite imagery from
  [NOAA/NESDIS/STAR](https://www.star.nesdis.noaa.gov/GOES/), whose sector
  JPEGs are published under [CC0-1.0](https://creativecommons.org/publicdomain/zero/1.0/)
  (declared in the image files' own embedded metadata). The dust view crops
  and reprojects a small region of that imagery around home for the LED
  matrix, rather than displaying the raw sector image.

## License

This project is available under the [MIT License](LICENSE).
