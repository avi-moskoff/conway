# Conway LED Matrix

> Note on AI usage: This project was made for fun, and I used AI when I thought it would make the project more fun to do so.

An interactive animation runner for a 64×64 HUB75 RGB LED matrix. It currently
includes:

- Conway's Game of Life
- A boids flocking simulation
- An optional live aircraft radar powered by adsb.lol

Turn the rotary encoder to switch games. Each game keeps its state while it is
inactive, so switching back resumes where it left off. Press the illuminated
button to reset the active game. The button lights while the program is running.
When the program exits, it clears the matrix and turns off the button light.

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
│ GND ──────────────────────────│── Encoder common
│                               │
│ Bonnet HUB75 output ──────────│── HUB75 ribbon ── 64×64 matrix
│ Bonnet power input ◀──────────│── regulated 5 V matrix supply
└───────────────────────────────┘
```

Wire colors in this document identify the physical wiring, not the colors of
the components. The button light needs an appropriate current-limiting resistor
unless one is built into the button. The `gpiozero` inputs use pull-ups, so the
button switch and encoder common connect to ground.

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

## Controls

| Control       | GPIO | Wire   | Action                    |
| ------------- | ---: | ------ | ------------------------- |
| Button switch |   14 | Green  | Reset the active game     |
| Button light  |   15 | Red    | Program-running indicator |
| Encoder A     |   18 | Yellow | Select a game             |
| Encoder B     |   19 | White  | Select a game             |

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

### Running

The flight-radar game is included when both home coordinates are configured.
Keep them outside the repository by putting them in `/etc/conway.env`:

```text
CONWAY_HOME_LATITUDE=...
CONWAY_HOME_LONGITUDE=...
CONWAY_FLIGHT_RADIUS_NM=8
CONWAY_ADSB_POLL_SECONDS=15
```

The optional settings `CONWAY_ADSB_API_URL` and `CONWAY_ADSB_API_KEY` make it
possible to switch to another compatible endpoint later. The public
[adsb.lol](https://adsb.lol/) service is used by default. Aircraft positions
come from community receivers, so coverage can vary. Origin and destination
labels are inferred from callsigns when route data is available; they are not
broadcast by the aircraft and should be treated as best-effort.

The radar makes no requests while another game is selected. Its aircraft and
route caches live only in RAM, and neither coordinates nor aircraft history are
written to disk by the application.

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

## License

This project is available under the [MIT License](LICENSE).
