# FineSat strand

The original FineSat gesture pipeline: capture raw carrier-phase samples, build
feature datasets, and train classifiers. See the top-level
[README](../README.md) for repo-wide context and receiver setup.

```
finesat/
├── scripts/     capture + dataset-building code
├── notebooks/   classifiers (SVM, XGBoost) and exploration
├── data/
│   ├── samples/   raw .rtcm captures (Apr/May 2026 + jn18)
│   └── archive/   old/ad-hoc micro-collections
├── datasets/    built feature matrices (X/Y .npy)
├── models/      trained weights (.pth)
└── docs/        capture_sample_explanation.md
```

All scripts resolve their data paths relative to their own location, so they can
be run from any working directory (e.g. `uv run finesat/scripts/build_raw_dataset.py`).

## Data Collection

```
uv run finesat/scripts/capture_sample.py
```

`capture_sample.py` runs an **interleaved** capture loop — each cycle collects one
of push → pushpull → triangle → m → star (with audio cues), retrying any sample
that fails quality control. For flexible single-gesture / arbitrary-count
collection, use `capture_sample_single.py` instead.

### Capture Flow

1. **3-second countdown**, then the person performs the gesture between seconds 3 and 6 of a 10-second recording window. (Note: in practice the gesture is not guaranteed to land exactly in 3–6 s — analysis should detect onset rather than assume a fixed slice.)
2. **Raw serial capture** — 10 seconds of bytes streamed into an in-memory buffer
3. **Parsing** — the buffer is parsed with `pyubx2.UBXReader` to extract:
   - NAV-SAT messages → satellite elevation angles
   - RTCM 1077/1127 messages → carrier phase (coarse range `DF398` + fine phase `DF406`, combined and converted to meters)
4. **Health checks** — three tests gate whether a sample is saved:
   - **Message counts:** ≥100 GPS, ≥100 BeiDou, ≥10 NAV-SAT messages
   - **Cycle slip detection:** no phase jumps exceeding 50 m between consecutive epochs on any satellite
   - **Usable satellites:** ≥2 satellites with full epochs and no cycle slips
5. **Auto-save or retry** — passing samples are saved to `data/samples/<...>/<label>-<YYMMDD>-<HHMMSS>.rtcm`; failing samples are discarded and retried.

### Flags

- `--port` — override the serial port
- `--no-elev` — bypass NAV-SAT elevation checks (satellites sorted by constellation/PRN instead of elevation)

## Samples

Raw captures live in `data/samples/`. Each file is a raw binary dump of the serial
stream over a 10-second window. Filenames encode gesture + timestamp:
`<gesture>-<YYMMDD>-<HHMMSS>.rtcm`. Current gesture classes: push, pushpull,
triangle, m, star.

## Dataset Building

Two scripts convert raw `.rtcm` files into NumPy feature matrices (written to
`datasets/`).

### `build_finesat_dataset.py`

Applies FineSat signal enhancement before feature extraction:

1. Parse each `.rtcm` for carrier-phase time series and elevation
2. Filter for satellites with 100 clean epochs (no cycle slips)
3. Select the highest-elevation satellite as reference
4. For each target satellite (up to 6): compute `diff = target − reference`, fit a 3rd-order polynomial trend, detrend (`finesat = diff − trend`), extract 13 statistical features
5. Output: `datasets/X_finesat.npy` (samples × 78) and `datasets/Y_finesat.npy`

### `build_raw_dataset.py`

Baseline without FineSat enhancement: same parsing and satellite selection, computes
the inter-satellite difference but **skips** polynomial detrending, extracts the same
13 features. Output: `datasets/X_raw.npy`, `datasets/Y_raw.npy`.

### The 13 Features

Per satellite pair: mean, variance, standard deviation, max, min, range, median,
IQR, skewness, kurtosis, RMS, mean absolute deviation, and energy. With up to 6
target satellites, each sample yields a 78-dimensional vector (6 × 13).
