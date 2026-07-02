# BassHabitatController

Python-based tortoise habitat controller for Raspberry Pi 4.

## Features

* **Lighting control** – `HabitatControl.py` drives smart plugs (UVB, basking,
  CHE heater) based on local sunrise/sunset to maintain healthy photoperiods.
* **Pan/tilt tracker** – camera-based tortoise detection keeps the Arducam
  IMX477 centred on the tortoise using two 28BYJ-48 steppers, and logs a 2-D
  path/heatmap of movement through the L-shaped enclosure.

---

## Pan/Tilt Tracker

### Hardware

| Component | Details |
|-----------|---------|
| Controller | Raspberry Pi 4 |
| Camera | Arducam IMX477 Pi HQ Camera |
| Pan motor | 28BYJ-48 5V stepper + ULN2003 driver board |
| Tilt motor | 28BYJ-48 5V stepper + ULN2003 driver board |
| Power | 5V 3A for Pi + 5V 500 mA for both motors |

### Default Wiring (BCM pin numbers)

| Signal | BCM pin | Physical pin |
|--------|---------|--------------|
| **Pan** IN1 | GPIO **17** | 11 |
| **Pan** IN2 | GPIO **18** | 12 |
| **Pan** IN3 | GPIO **27** | 13 |
| **Pan** IN4 | GPIO **22** | 15 |
| **Tilt** IN1 | GPIO **23** | 16 |
| **Tilt** IN2 | GPIO **24** | 18 |
| **Tilt** IN3 | GPIO **25** | 22 |
| **Tilt** IN4 | GPIO **4**  | 7  |
| GND | Any GND pin | 6, 9, 14, 20 … |
| 5V motor supply | External 5V rail | – |

> **Note:** Connect the ULN2003 `VCC` to an **external 5V supply**, not the
> Pi's 5V pin. The Pi's 5V pin cannot safely source 500 mA per motor.
> Connect GNDs together.

All pins are safe, common GPIO outputs on Pi 4 that avoid hardware-special
functions (SPI, I2C, UART, hardware PWM). Override any pin in `config.json`.

---

### File Structure

```
BassHabitatController/
├── HabitatControl.py        # Existing lighting controller
├── run_tracker.py           # Tracking loop entrypoint
├── calibrate.py             # Interactive calibration CLI
├── config.json              # Your working config (created from template)
├── config_template.json     # Reference config with all options documented
├── requirements.txt
├── logs/
│   ├── track_log.csv        # Timestamped position log
│   ├── path_plot.png        # Tortoise path through enclosure
│   └── heatmap.png          # Occupancy heatmap
└── pantilt/
    ├── __init__.py
    ├── _gpio_mock.py        # RPi.GPIO stub for non-Pi development
    ├── config.py            # Config load/save
    ├── stepper.py           # 28BYJ-48 half-step driver
    ├── pantilt_controller.py# Deadband + rate-limited PT control
    ├── tracker.py           # OpenCV MOG2 tortoise detector
    └── mapper.py            # Coordinate mapping, CSV log, plot generation
```

---

### Installation (Raspberry Pi 4)

```bash
# 1. Update system packages
sudo apt update && sudo apt upgrade -y

# 2. Install system-level OpenCV + GPIO (faster than pip on Pi)
sudo apt install -y python3-opencv python3-rpi.gpio python3-numpy python3-matplotlib

# 3. (Optional) Install scipy for smoothed heatmaps
sudo apt install -y python3-scipy

# 4. Clone the repository
git clone https://github.com/MGVdec2000/BassHabitatController.git
cd BassHabitatController

# 5. (Optional) Install remaining Python packages via pip
pip3 install -r requirements.txt

# 6. Copy the config template and edit as needed
cp config_template.json config.json
```

> If you prefer a virtual environment:
> ```bash
> python3 -m venv .venv && source .venv/bin/activate
> pip install -r requirements.txt
> pip install RPi.GPIO       # Pi only
> ```

---

### Quick Start

#### 1 – Calibration (run once, or after changing hardware)

```bash
python3 calibrate.py
```

The interactive menu guides you through:

1. **Jog motors** – use arrow keys or WASD to move the camera head; press
   `+`/`-` to change step size, `0` to reset position counters, `q` to exit.
2. **Set centre** – jog to the centre of the enclosure view, then choose
   option 2 to record that as home (step 0, 0).
3. **Set axis directions** – if a motor runs backwards, flip its direction
   here (stored in config).
4. **Set travel limits** – jog to each physical end-stop for both axes; the
   step counts are saved as software limits so the motors never crash.
5. **Set step scaling** – enter measured steps/degree or accept the 28BYJ-48
   theoretical default (11.38 steps/degree).
6. **Set mapping parameters** – camera FOV, mount height, and position used
   to convert step angles to enclosure coordinates.
7. **Save** – writes everything to `config.json`.

#### 2 – Run the tracker

```bash
# Headless (recommended for Pi running without a display)
python3 run_tracker.py

# With live preview window (requires display / VNC)
python3 run_tracker.py --show

# Use an alternate config file
python3 run_tracker.py --config /home/pi/my_config.json
```

Press **Ctrl-C** to stop.  Logs and plots are saved to `logs/` on exit.

---

### Enclosure Coordinate System

```
        Y (inches)
        ▲
        │  ╔═══════╗
   96"  │  ║       ║
        │  ║ leg 1 ║  ← 25" wide, 96" tall (8 ft)
        │  ║       ║
   25"  │  ╠═══════╬═══════════════════╗
    0"  │  ╚═══════╩═══════════════════╝
        └──────────────────────────────────► X (inches)
           0"    25"                    85"
                         leg 2 (60" long, 25" tall, 5 ft)
```

Origin (0, 0) is at the inside corner of the L.  Any logged point outside the
L-shape is marked invalid in the CSV but still written for diagnostics.

---

### Log Format

`logs/track_log.csv`:

| Column | Description |
|--------|-------------|
| `timestamp` | ISO-8601 local time |
| `x_in` | Estimated X position in enclosure (inches) |
| `y_in` | Estimated Y position in enclosure (inches) |
| `pan_steps` | Cumulative pan half-steps from calibrated centre |
| `tilt_steps` | Cumulative tilt half-steps from calibrated centre |
| `confidence` | Detection confidence (0–1); blank if no detection |

### Generated Plots

* **`logs/path_plot.png`** – Blue line tracing the tortoise's path overlaid on
  the L-shaped enclosure outline.  Green dot = start, red dot = last position.
* **`logs/heatmap.png`** – Heat-colour grid showing how much time the tortoise
  spent in each part of the enclosure (Gaussian-smoothed if scipy is present).

---

### Configuration Reference (`config.json`)

Key settings (see `config_template.json` for the full list):

| Key | Default | Description |
|-----|---------|-------------|
| `pan.pins` | `[17,18,27,22]` | BCM GPIO for ULN2003 IN1–IN4 |
| `pan.min_steps` / `max_steps` | `-400` / `400` | Software travel limits |
| `pan.direction` | `1` | `1` or `-1` to flip motor sense |
| `pan.steps_per_degree` | `11.38` | Half-steps per degree of rotation |
| `tilt.*` | (same as pan) | Same settings for tilt axis |
| `camera.index` | `0` | V4L2 device index (`/dev/video0`) |
| `tracking.deadband_px` | `20` | Pixel dead-zone to prevent jitter |
| `tracking.max_step_per_frame` | `8` | Rate limit (steps/frame/axis) |
| `tracking.confidence_threshold` | `0.3` | Minimum blob size to act on |
| `mapping.camera_height_in` | `36` | Camera height above enclosure floor |
| `mapping.pan_fov_deg` | `62.2` | IMX477 horizontal field of view |

---

### Troubleshooting

#### Tortoise not detected / missed detections

* The MOG2 background model needs ~30 frames to initialise.  Allow 2–3 seconds
  after launch before detections appear.
* If the tortoise is always stationary, decrease `tracking.confidence_threshold`
  down to 0.1 to catch smaller motion blobs.
* Bright reflections, cage mesh shadows, or substrate texture can confuse the
  background subtractor.  Try adjusting ambient lighting to reduce contrast.

#### Motor jitter / hunting

* Increase `tracking.deadband_px` (e.g. 30–40) to widen the no-move zone.
* Reduce `tracking.max_step_per_frame` (e.g. 4) to slow down corrections.

#### Step loss / position drift

* The 28BYJ-48 is an open-loop motor; missed steps accumulate.  If the camera
  drifts over time, re-run `calibrate.py` and reset the centre.
* Reduce step speed: increase `StepperMotor._DEFAULT_STEP_DELAY` in
  `pantilt/stepper.py` (default 2 ms).  Try 3–4 ms if loads are heavy.

#### Camera not opening

* Check `camera.index` in `config.json` – run `v4l2-ctl --list-devices` on the
  Pi to confirm the correct device number.
* For Arducam IMX477 you may need the `libcamera` stack:
  ```bash
  sudo apt install -y python3-libcamera python3-picamera2
  ```
  Then set `camera.index` to the correct `/dev/videoN` number shown by
  `v4l2-ctl`.

#### GPIO / permission errors

```bash
sudo adduser $USER gpio   # add your user to the gpio group
# then log out and back in, or: newgrp gpio
```

#### ImportError: No module named 'RPi.GPIO'

This is expected on non-Pi machines.  The tracker and calibration tool fall back
to the built-in GPIO mock automatically.  If you are **on** a Pi:

```bash
sudo apt install python3-rpi.gpio
# or
pip3 install RPi.GPIO
```
