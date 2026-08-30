#!/usr/bin/env bash
# Provision a Raspberry Pi Zero 2 W for the robot. Safe to re-run.
#
#   ssh robot@robot.local
#   git clone <your repo> ~/robot && cd ~/robot && bash pi/setup.sh
set -euo pipefail

CONFIG=/boot/firmware/config.txt      # Bookworm; older images use /boot/config.txt
[ -f "$CONFIG" ] || CONFIG=/boot/config.txt
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

say() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }

say "Checking board"
if ! grep -q "Zero 2" /proc/device-tree/model 2>/dev/null; then
  echo "WARNING: this does not look like a Pi Zero 2 W:"
  tr -d '\0' < /proc/device-tree/model; echo
fi

say "System packages"
sudo apt-get update
# python3-picamera2 is apt-only; libportaudio2 is what sounddevice binds to.
sudo apt-get install -y --no-install-recommends \
  python3-venv python3-pip python3-numpy python3-picamera2 \
  libportaudio2 libopenblas0 alsa-utils git

say "Swap (512 MB RAM needs help during pip installs)"
if [ -f /etc/dphys-swapfile ]; then
  sudo sed -i 's/^CONF_SWAPSIZE=.*/CONF_SWAPSIZE=512/' /etc/dphys-swapfile
  sudo systemctl restart dphys-swapfile || true
fi

say "Enabling interfaces"
add_line() { grep -qxF "$1" "$CONFIG" || echo "$1" | sudo tee -a "$CONFIG" >/dev/null; }
add_line "dtparam=spi=on"        # round display
add_line "dtparam=i2c_arm=on"    # IMU, ToF sensor
add_line "camera_auto_detect=1"

# ROBOT_AUDIO=i2s   INMP441 mic + MAX98357A amp on the GPIO header (Zero 2 W).
# ROBOT_AUDIO=usb   USB mic and/or the 3.5 mm jack (Pi 3 / Pi 4) — no overlay,
#                   ALSA finds the devices on its own.
AUDIO="${ROBOT_AUDIO:-i2s}"
if [ "$AUDIO" = "i2s" ]; then
  echo "  audio: I2S (set ROBOT_AUDIO=usb to skip these overlays)"
  add_line "dtparam=i2s=on"
  # One overlay serves both the INMP441 mic and the MAX98357A amp on the same
  # I2S bus. For the amp alone, 'dtoverlay=hifiberry-dac' is the alternative.
  add_line "dtoverlay=googlevoicehat-soundcard"
else
  echo "  audio: USB / 3.5 mm jack — no I2S overlay added"
fi

say "Python environment"
# --system-site-packages is required: picamera2 is installed by apt, not pip,
# and an isolated venv cannot see it.
[ -d "$REPO/.venv" ] || python3 -m venv --system-site-packages "$REPO/.venv"
"$REPO/.venv/bin/pip" install --upgrade pip
"$REPO/.venv/bin/pip" install -r "$REPO/requirements-pi.txt"

say "Environment file"
if [ ! -f "$REPO/.env" ]; then
  cp "$REPO/.env.example" "$REPO/.env"
  echo "Created .env — put your OPENAI_API_KEY in it."
fi
# The robot has no screen; the console face is the only sane default.
grep -q '^ROBOT_FACE=' "$REPO/.env" || echo "ROBOT_FACE=console" >> "$REPO/.env"

say "systemd service"
sudo cp "$REPO/pi/robot.service" /etc/systemd/system/robot.service
sudo sed -i "s|__REPO__|$REPO|g; s|__USER__|$USER|g" /etc/systemd/system/robot.service
sudo systemctl daemon-reload
echo "  enable at boot with: sudo systemctl enable --now robot"

say "Done — REBOOT for the overlays to take effect"
cat <<'EOF'

After rebooting, verify in this order:

  arecord -l                       # your mic should appear as a card
  aplay -l                         # your output should appear too
  arecord -D plughw:0 -d 3 t.wav   # record 3 seconds
  aplay -D plughw:0 t.wav          # play it back
  libcamera-hello --list-cameras   # camera detected?

  .venv/bin/python check_audio.py  # note the device indices it prints,
                                   # then set ROBOT_INPUT_DEVICE / ROBOT_OUTPUT_DEVICE in .env
  .venv/bin/python check_api.py key
  .venv/bin/python -m robot.loop

EOF
