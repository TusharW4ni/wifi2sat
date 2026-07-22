# GNSS Data Collection

Human sensing (gesture recognition, breathing, geometry experiments) using GNSS
satellite carrier-phase measurements, based on the
[FineSat](shared/docs/FineSat_paper.pdf) paper. A u-blox EVK-F9P receiver captures
high-rate carrier-phase data from GPS and BeiDou satellites; subtle phase
perturbations caused by nearby human motion are isolated (inter-satellite
differencing + polynomial detrending) and used for classification — no Wi-Fi or
specialized hardware.

## Hardware

- **Receiver:** u-blox EVK-F9P
- **Connection:** USB serial at 115,200 baud
- **Serial Port:** `/dev/cu.usbmodem*` (macOS)

## Setup

```
uv sync
```

## Repository Structure

The repo is organized into **strands** — largely self-contained lines of work —
plus shared infrastructure. Each strand keeps its own code, data, and docs.

```
gnss-data-collection/
├── shared/                  Infrastructure used by all strands
│   ├── receiver-setup/      Sequential u-blox F9P configuration pipeline (01–07)
│   └── docs/                FineSat paper, setup notes
│
├── finesat/                 Original FineSat gesture pipeline
│   ├── scripts/             capture_sample*.py, build_*_dataset.py, test-poly.py
│   ├── notebooks/           SVM / XGBoost classifiers, exploration
│   ├── data/samples/        Raw .rtcm captures (Apr/May + jn18)
│   ├── data/archive/        Old/ad-hoc micro-collections (see salvage notes)
│   ├── datasets/            Built feature matrices (X/Y .npy)
│   ├── models/              Trained model weights (.pth)
│   └── docs/                Pipeline explanation
│
├── window-experiment/       Geometry/window-coherence experiment (self-contained)
│   ├── phase0/, phase1/      THEORY.md, PROJECT_LOG.md, capture + analysis code,
│   │                         c1.1 / c3.2 / ref session data + manifests
│
├── breathing/               Breathing-detection strand
│   ├── capture/             Breathing capture scripts
│   └── data/                Breathing sessions (json/ + rtcm/)
│
├── pyproject.toml, uv.lock  Project environment (uv)
└── README.md                (this file)
```

Each strand has (or will have) its own `README.md` with details:
- **[finesat/README.md](finesat/README.md)** — capture → dataset → classify pipeline
- **window-experiment/phase1/** — see `THEORY.md` and `PROJECT_LOG.md`

## Receiver Configuration (shared)

`shared/receiver-setup/` contains a sequential configuration pipeline that
prepares the u-blox F9P for data collection. Run all steps at once:

```
cd shared/receiver-setup && zsh setup.zsh
```

Or run each step individually with `uv run <script>`.

### Steps

**`01-reset.py`** — Cold start. Clears all battery-backed RAM (ephemeris, almanac, position, clock, oscillator calibration). The receiver starts fresh with no cached satellite data, so it needs ~30–60 s to reacquire satellites and compute a fix.

**`02-sample-rate.py`** — Sets the measurement rate to 100 ms (10 Hz). Every 100 ms the receiver produces a new set of RTCM and NAV-SAT messages. The time reference is aligned to GPS time.

**`03-port-config.py`** — Configures the USB port protocols. Input and output are set to UBX + RTCM. NMEA is disabled since we don't need human-readable position sentences.

**`04-messages.py`** — Enables the message types we need and disables everything else:
- **RTCM 1077** (GPS MSM7) — carrier phase observables from GPS satellites
- **RTCM 1127** (BeiDou MSM7) — carrier phase observables from BeiDou satellites
- **UBX-NAV-SAT** — satellite elevation/azimuth from the navigation engine

NMEA sentences (GGA, RMC, GSV, GSA) are explicitly disabled. RAWX is available but commented out.

**`05-save-config.py`** — Persists the current configuration to the receiver's flash memory so it survives power cycles.

**`06-check.py`** — Polls the receiver's RAM layer to verify measurement rate, baud rate, protocol masks, and message output rates match what we configured.

**`07-stream.py`** — Real-time monitoring utility. Streams and prints all parsed messages, useful for verifying output before starting data collection.
