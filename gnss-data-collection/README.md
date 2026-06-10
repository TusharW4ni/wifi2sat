# GNSS Data Collection

Gesture recognition using GNSS satellite carrier phase measurements, based on the [FineSat](FineSat_Enhancing_GNSS_Signals_for_High-precision_Sensing.pdf) paper. A u-blox EVK-F9P receiver captures high-rate carrier phase data from GPS and BeiDou satellites. The FineSat algorithm (inter-satellite differencing + polynomial detrending) isolates subtle phase perturbations caused by nearby human motion, enabling gesture classification without Wi-Fi or specialized hardware.

## Hardware

- **Receiver:** u-blox EVK-F9P
- **Connection:** USB serial at 115,200 baud
- **Serial Port:** `/dev/cu.usbmodem11301` (macOS)

## Setup

```
uv sync
```

## Pipeline Overview

```
1. Configure receiver          setup-receiver/setup.zsh
2. Collect gesture samples     capture_sample.py
3. Build feature datasets      build_finesat_dataset.py / build_raw_dataset.py
4. Train classifiers           (notebooks, not covered here)
```

## Receiver Configuration

The `setup-receiver/` directory contains a sequential configuration pipeline that prepares the u-blox F9P for data collection. Run all steps at once with:

```
cd setup-receiver && zsh setup.zsh
```

Or run each step individually with `uv run <script>`.

### Steps

**`01-reset.py`** — Cold start. Clears all battery-backed RAM (ephemeris, almanac, position, clock, oscillator calibration). The receiver starts fresh with no cached satellite data, which means it will need ~30-60 seconds to reacquire satellites and compute a position fix.

**`02-sample-rate.py`** — Sets the measurement rate to 100 ms (10 Hz). Every 100 ms the receiver produces a new set of RTCM and NAV-SAT messages. The time reference is aligned to GPS time.

**`03-port-config.py`** — Configures the USB port protocols. Input and output are set to UBX + RTCM. NMEA is disabled since we don't need human-readable position sentences.

**`04-messages.py`** — Enables the three message types we need and disables everything else:
- **RTCM 1077** (GPS MSM7) — carrier phase observables from GPS satellites
- **RTCM 1127** (BeiDou MSM7) — carrier phase observables from BeiDou satellites
- **UBX-NAV-SAT** — satellite elevation/azimuth data from the receiver's navigation engine

NMEA sentences (GGA, RMC, GSV, GSA) are explicitly disabled. RAWX is available but commented out.

**`05-save-config.py`** — Persists the current configuration to the receiver's flash memory so it survives power cycles.

**`06-check.py`** — Polls the receiver's RAM layer to verify that measurement rate, baud rate, protocol masks, and message output rates match what we configured.

**`07-stream.py`** — Real-time monitoring utility. Streams and prints all parsed messages from the receiver. Useful for verifying the receiver is outputting the expected messages before starting data collection.

## Data Collection

```
uv run capture_sample.py
```

`capture_sample.py` handles batch collection of gesture samples with built-in quality control. It prompts for a gesture label and sample count, then runs a capture-parse-validate loop for each sample.

### Capture Flow

1. **3-second countdown**, then the person performs the gesture between seconds 3 and 6 of a 10-second recording window
2. **Raw serial capture** — 10 seconds of bytes streamed into an in-memory buffer
3. **Parsing** — the buffer is parsed with `pyubx2.UBXReader` to extract:
   - NAV-SAT messages → satellite elevation angles
   - RTCM 1077/1127 messages → carrier phase measurements (coarse range `DF398` + fine phase `DF406`, combined and converted to meters)
4. **Health checks** — three tests gate whether the sample is saved or discarded:
   - **Message counts:** at least 100 GPS messages, 100 BeiDou messages, and 10 NAV-SAT messages
   - **Cycle slip detection:** no phase jumps exceeding 50 meters between consecutive epochs on any satellite
   - **Usable satellites:** at least 2 satellites with full epochs and no cycle slips
5. **Auto-save or retry** — passing samples are saved as `samples/<label>-<YYMMDD>-<HHMMSS>.rtcm`. Failing samples are discarded and the same sample index is retried.

### Flags

- `--port` — override the serial port (default: `/dev/cu.usbmodem11301`)
- `--no-elev` — bypass NAV-SAT elevation checks, useful if the receiver isn't outputting elevation data. Satellites are sorted by constellation/PRN instead of elevation.

## Samples

Collected data lives in `samples/`. Each file is a raw binary dump of the serial stream captured during a 10-second recording window. Filenames encode the gesture label and timestamp: `<gesture>-<YYMMDD>-<HHMMSS>.rtcm`.

Current gesture classes: push, pushpull, triangle, m, star.

## Dataset Building

Two scripts convert the raw `.rtcm` sample files into NumPy feature matrices for classification.

### `build_finesat_dataset.py`

Applies the FineSat signal enhancement before feature extraction:

1. Parse each `.rtcm` file for carrier phase time series and elevation data
2. Filter for satellites with 100 clean epochs (no cycle slips)
3. Select the highest-elevation satellite as the reference
4. For each target satellite (up to 6):
   - Compute difference: `diff = target_phase - reference_phase`
   - Fit 3rd-order polynomial: `trend = polyfit(t, diff, 3)`
   - Detrend: `finesat = diff - trend`
   - Extract 13 statistical features from the detrended signal
5. Output: `X_finesat.npy` (shape: samples x 78) and `Y_finesat.npy`

### `build_raw_dataset.py`

Baseline comparison without FineSat enhancement:

1. Same parsing and satellite selection as above
2. Computes inter-satellite difference (`target - reference`) but skips polynomial detrending
3. Extracts the same 13 features from the raw difference signal
4. Output: `X_raw.npy` and `Y_raw.npy`

### The 13 Features

Both scripts extract the same feature set per satellite pair: mean, variance, standard deviation, max, min, range, median, IQR, skewness, kurtosis, RMS, mean absolute deviation, and energy.

With up to 6 target satellites, each sample produces a 78-dimensional feature vector (6 x 13).

