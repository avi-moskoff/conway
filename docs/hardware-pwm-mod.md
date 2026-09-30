# Hardware PWM mod (fixing panel flicker)

Notes for finishing the flicker fix: solder a GPIO 4 -> GPIO 18 jumper on the
RGB Matrix Bonnet so the LED driver can use the Pi's hardware PWM for its
brightness timing, and move the rotary encoder's A wire off GPIO 18 to make
room for it.

Not started as of this writing. Everything below is prepared, not yet done or
tested on the hardware.

## Why

The panel (64x64, Pi Zero 2 W, Adafruit RGB Matrix Bonnet) flickers in rows,
worst on the dense weather screens. Without the jumper the driver times each
row's brightness in software, and any scheduling hiccup shows up as flicker.
The driver's "quality" mode uses the hardware PWM instead, but that needs
GPIO 4 (the Bonnet's output-enable line) tied to GPIO 18 (the PWM pin).

GPIO 18 is currently the encoder's A wire (yellow), which is why the driver
was installed in "convenience" mode (see the README).

## What has already been tried (no fix)

- `run.sh` no longer pins Python to core 3: it runs on cores 0,1 so the driver's
  isolated cores (`isolcpus=...,2,3`) are left alone.
- Onboard audio off: `dtparam=audio=off` in `/boot/firmware/config.txt`, and
  `snd_bcm2835` blacklisted (`lsmod | grep snd_bcm2835` prints nothing).
- The timing knobs in `display.py` (env vars in `/etc/conway.env`, see the
  README): brightness 30, PWM bits 8, GPIO slowdown 3. Flicker stayed bad with
  all of them, so it isn't power sag or refresh rate alone.
- Confirmed with `pinctrl` that GPIO 4 and 18 are **not** currently connected.

Possible extra experiments, if you want more before soldering: remove
`idle=poll` from `/boot/firmware/cmdline.txt`, and try
`CONWAY_LED_PWM_LSB_NANOSECONDS=100`.

## What you need

- Soldering iron, solder, a short piece of thin wire (about 2 cm, stripped).
- The Bonnet's labeled breakout pads along its top edge: `OE`(4), `CLK`(17),
  `18`, `27`, ..., then `25`, `MO`, `MI`, `CLK`, `CE0`, `CE1`, ... Look at the
  silkscreen; the GPIO number is printed above each pad.
- Free pads for the encoder: the SPI pads to the right of the orange wire
  (`MO`=10, `MI`=9, `CLK`=11, `CE0`=8, `CE1`=7). Nothing in this project uses
  them. Use **`CE0` (GPIO 8)**: it's three pads away from the orange GPIO 25
  wire, so a stray solder bridge is unlikely.

Power everything off and unplug both the Pi and the matrix supply first.

**Never have the jumper installed while the encoder A wire is still on GPIO 18.**
GPIO 4 is an output driving the panel's output-enable line; tied to an encoder
contact that shorts to ground it would fight it. That's why step 1 (move the
wire) comes before step 2 (jumper).

Also check `/boot/firmware/config.txt` for `dtoverlay=w1-gpio` (1-Wire).
Adafruit warns that 1-Wire interferes with the matrix, and its default pin is
GPIO 4. It shouldn't be enabled on this Pi, but confirm before soldering.

## Steps

1. **Move the yellow wire.** Desolder the yellow (Encoder A) wire from the
   `18` pad and resolder it to the `CE0` pad. The `18` pad sits between `17`
   and `27`; be careful not to bridge into `27` (matrix address line C) or
   `17` (matrix clock).
2. **Solder the jumper.** Run a short wire from the `4` (`OE`) pad to the `18`
   pad. It has to pass over the `17` pad without touching it (about two pad
   spacings, roughly 1 cm). Keep the wire tight to the board.
3. **Check for shorts before powering on.** With a multimeter on continuity,
   confirm: `4` <-> `18` beeps; `18` is *not* connected to `17`, `27` or GND;
   `CE0` is not connected to its neighbors or GPIO 25.
4. **Change the code** (see the next section).
5. **Test** (see Verify).

Do steps 1-3 and the code change in the same sitting. With the jumper in and
the old mapping, or the new mapping and no jumper, the display shows nothing
or garbage.

## Code changes

`runner.py` (around line 51): the encoder's A pin moves from 18 to 8.
Keep the argument order, which is deliberately swapped so clockwise turns
report as clockwise:

```python
self._game_encoder_yellow_white = RotaryEncoder(19, 8)
```

`display.py`: switch to the mapping that drives output-enable from GPIO 18:

```python
options.hardware_mapping = "adafruit-hat-pwm"
```

`README.md`:
- In the wiring diagram and the Controls table, change Encoder A from GPIO 18
  to GPIO 8.
- Rewrite "GPIO 18 and matrix-driver mode": the GPIO 4 -> GPIO 18 jumper is
  now installed, the driver runs in quality (hardware PWM) mode, and onboard
  audio must stay disabled.

## Verify

Stop the service and check the jumper from software first:

```bash
sudo systemctl stop conway; sudo pinctrl set 18 ip pd; sudo pinctrl set 4 op dh; pinctrl get 4,18
```

GPIO 18 should now read `hi` (it read `lo` before the jumper). Reboot to reset
the pins, then start the service and look for:

- the panel comes up normally (a blank panel means the mapping and jumper
  disagree);
- flicker gone or much reduced on the weather screens;
- the encoder still turns the right way and its push switch and the button
  still work (the encoder A wire was moved).

If the encoder turns the wrong way, swap the arguments back to `(8, 19)`.

## If it doesn't work

- Panel blank or garbled: recheck the jumper with the multimeter; as a
  fallback set `hardware_mapping` back to `"adafruit-hat"` and the panel
  should work again as it does today (flicker included).
- Encoder dead: recheck the wire on `CE0` and the `RotaryEncoder(19, 8)` line.
- Still flickering after the mod: the timing knobs and `idle=poll` are worth
  another pass, with the hardware PWM now in place; power supply quality is
  the remaining suspect.

## Reversal

Remove the jumper, resolder the yellow wire to `18`, and revert the three code
changes above.

## What was verified against the docs (and what wasn't)

Checked against Adafruit's Bonnet pinout page and the driver's own
`README.md` and `wiring.md` (hzeller/rpi-rgb-led-matrix), on the day this was
written.

Confirmed:
- Hardware pulsing needs GPIO 4 and GPIO 18 connected on the Adafruit
  HAT/Bonnet, and the driver is then run with the `adafruit-hat-pwm` mapping.
- `adafruit-hat` and `adafruit-hat-pwm` use identical pin assignments. Color
  GPIO 5/13/6/12/16/23, clock 17, strobe 21, address 22/26/27/20/24, output
  enable 4.
- Adafruit lists these Bonnet pins as unused: SCL, SDA, RX, TX, 25, MOSI, MISO,
  SCLK, CE0, CE1, 19 (and 18 in "convenience" mode). So `CE0` (GPIO 8) is free
  for the encoder.
- The onboard audio conflict applies specifically to hardware pulsing, which is
  why audio must be off *after* this mod. The docs say to disable it in
  `config.txt` (`dtparam=audio=off`) and possibly blacklist `snd_bcm2835`.
- The driver docs recommend `isolcpus` on the last core for the refresh thread;
  the extra isolated core 2 in this Pi's cmdline is compatible with that.

Not confirmed:
- **Where on the Bonnet the 4 -> 18 connection is made.** Adafruit's text says
  only that a connection is needed (a jumper wire), and points to a photo. It
  documents no dedicated solder pads, so rely on the silkscreen labels and the
  multimeter checks above, not on this doc for the exact spot.
- That this fully fixes the flicker on a Pi Zero 2 W. It's the documented fix,
  not a guarantee.

Sources:
- https://learn.adafruit.com/adafruit-rgb-matrix-bonnet-for-raspberry-pi/pinouts
- https://learn.adafruit.com/adafruit-rgb-matrix-bonnet-for-raspberry-pi/matrix-setup
- https://github.com/hzeller/rpi-rgb-led-matrix (README.md, wiring.md)
