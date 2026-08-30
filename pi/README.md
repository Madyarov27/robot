# Pi Zero 2 W bring-up

## Before you leave the house

Make sure the box says **Zero 2 W**, not **Zero W**. The original is a
single-core ARM11 and none of the performance work in this repo applies to it.

## Flashing (do this before touching the robot)

Raspberry Pi Imager → **Raspberry Pi OS Lite (64-bit)**. Not the desktop image:
512 MB of RAM does not want a GUI, and the robot has no screen.

Then open the **gear / "Edit settings"** panel *before* writing, and set:

- hostname `robot` (so `ssh robot@robot.local` works)
- username + password (note them; there is no default login any more)
- **Wi-Fi SSID, password, and country** — 2.4 GHz only, the Zero 2 W has no 5 GHz
- locale / timezone
- **Services → Enable SSH** (password authentication is fine to start)

Skipping this panel is the single most common reason a headless Pi never appears
on the network.

## First boot

```bash
ssh robot@robot.local          # give it ~60 s after power-on
git clone <your repo> ~/robot
cd ~/robot

bash pi/setup.sh                      # Zero 2 W with I2S mic + amp
ROBOT_AUDIO=usb bash pi/setup.sh      # Pi 3/4 with USB mic + 3.5 mm jack

sudo reboot
```

`setup.sh` is idempotent — re-run it whenever you add hardware.

## What setup.sh does, and why

| step | why |
|---|---|
| `python3-picamera2` from **apt** | it is not installable from pip |
| venv with `--system-site-packages` | otherwise the venv cannot see picamera2 |
| swap raised to 512 MB | 512 MB RAM is not enough for some pip builds |
| `dtoverlay=googlevoicehat-soundcard` | serves the INMP441 mic **and** MAX98357A amp on one I2S bus |
| skipped when `ROBOT_AUDIO=usb` | a Pi 3/4 with a USB mic and the 3.5 mm jack needs no overlay at all |
| `requirements-pi.txt`, not `requirements.txt` | no pygame (no screen), no opencv (huge; picamera2 replaces it) |
| `ROBOT_FACE=console` in `.env` | there is no window to draw on |

## Verify in this order

Each step is independent, so a failure tells you exactly what is wrong.

```bash
arecord -l                        # mic detected?
aplay -l                          # amp detected?
arecord -D plughw:0 -d 3 t.wav && aplay -D plughw:0 t.wav
libcamera-hello --list-cameras    # camera detected?

.venv/bin/python check_audio.py   # note device indices, put them in .env
.venv/bin/python check_api.py key
.venv/bin/python -m robot.loop
```

## Run at boot

```bash
sudo systemctl enable --now robot
journalctl -u robot -f
```

## Wiring

I2S is a shared bus — mic and amp use the same clock and data-in/data-out lines.

| signal | Pi pin (BCM) | INMP441 mic | MAX98357A amp |
|---|---|---|---|
| BCLK | GPIO18 (pin 12) | SCK | BCLK |
| LRCLK / WS | GPIO19 (pin 35) | WS | LRC |
| data in | GPIO20 (pin 38) | SD | — |
| data out | GPIO21 (pin 40) | — | DIN |
| 3V3 | pin 1 / 17 | VDD | VIN |
| GND | pin 6 / 9 | GND, L/R | GND |

Tie the mic's L/R pin to GND (left channel) so the driver sees mono on a known side.

## Gotchas that cost a second trip to the store

- The camera connector is the **narrow 22-pin** type. A standard 15-pin ribbon
  will not fit — you need the Zero-specific cable.
- Power is **micro-USB**, not USB-C, and the port nearer the middle is the power
  one. The outer port is USB OTG.
- Video out is **mini-HDMI**.
- The board ships with **no headers soldered**.
