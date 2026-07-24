# Data Inventory

All data is on `main` under the four strands. Observable format is **mixed**:
`c1.1_day1`, `c3.2_day1`, `c3.2_day2` are **MSM7-only** (GPS + BeiDou, phase
reconstructed from DF fields); `ref_day1`, `repeat_day2`, `c3.2_day3` also carry
**RAWX + SFRBX** (clean carrier phase + lock-time + ephemeris). Gesture set
(c-series): push, pushpull, triangle, m, star — 6 reps each = 30 samples per full
window.

## Key concept: geometry granularity

- **Sky regime** (coarse): the satellite constellation depends on time of day and
  repeats each **sidereal day (~23h 56m)**. Captures hours apart in sidereal time
  see a wholly different sky = different regime.
- **Window** (fine): 15-min steps within a session; each ≈ 7° of LOS rotation, a
  small-but-real geometry change.

Cross-day sessions are collected at the **sidereally-aligned** clock time (each day
~4 min earlier) so the *same window index* reproduces the *same geometry*.

## Window-experiment: c-series gesture sessions (`window-experiment/data/samples/`)

| Session | Date (UTC) | Sidereal TOD | Windows present | Notes |
|---|---|---|---|---|
| `c1.1_day1` | Jun 29 16:40 | ~04:3x | W0,W1,W2,W3 (30 each) | **Flagship** — 100% clean yield all windows |
| `c3.2_day1` | Jul 1 00:25 | ~12:4x | W0,W1,W2 (30), W3 (18) | evening sky |
| `c3.2_day2` | Jul 14–15 | ~12:4x | W1,W2,W3 (30 each) | W1 starved; W3 recovered 2026-07-23 (97%) |
| `c3.2_day3` | Jul 22 23:40 | ~12:4x | W2,W3 (30 each) | day3 |
| `ref_day1` | Jul 14 22:17 | (aligned pair) | W0–W3 (12 each) | RAWX; push+star only, 100% yield |
| `repeat_day2` | Jul 15 22:09 | (aligned pair) | W0–W3 (12 each) | RAWX; push+star only, 100%; sidereal repeat of `ref_day1` |

An earlier **Jun 26** push+star session also exists but is archived, not in
`samples/`: `data/archive/samples-not-rawx-but-good/` (session `ref_jun26`, MSM,
W0–W3 ×12, good yield) — a *distinct* session that formerly shared the `ref_day1`
name (see [04-data-quality.md](04-data-quality.md)). A fragmentary earlier Jun 26 W0
set is in `data/archive/samples-old/`.

### c3.2 cross-day coverage (the sidereal-aligned repeats)

| Window | Timepoints | Value |
|---|---|---|
| W0 | day1 only | single-shot |
| W1 | day1 + day2 | **both starved** (13% / 48% ≥3 clean) — avoid for inversion |
| **W2** | **day1 + day2 + day3** (Jul 1 / 15 / 22) | **★ best cross-day series — 3 timepoints, 90 samples** |
| W3 | day1 + day2 + day3 | **3 timepoints** after the day2-W3 recovery (2026-07-23) |

## Clean-sat yield map (from meta `passed_health`; a floor — DF407 can raise it)

| Session / window | median clean sats | % captures ≥3 |
|---|---|---|
| c1.1 W0–W3 | 4–6 | **100%** |
| c3.2_day1 W2 | 11 | 100% |
| c3.2_day1 W0 / W3 | 3 / 11 | 70% / 67% |
| c3.2_day1 W1 | 2 | **13%** |
| c3.2_day2 W1 / W2 / W3 | 2 / 10 / 10 | 48% / 100% / 97% |
| c3.2_day3 W2 / W3 | 3 / 4 | 53% / 100% |
| ref_day1 / repeat_day2 W0–W3 | 5–6 | 100% |

≥3 non-coplanar clean satellites are needed to invert for the 3-D hand trajectory.

## Breathing (`breathing/data/`)

Sessions `s1.3`, `s1.3.2`, `s1.3.3`, `s1.3.4` (Jul 9, ~20 each), `s3.3` (Jul 22, 20).
Filenames encode rig geometry (`d`, `h`, `ch`, `cw`, `a` = angle). `s2.3_manifest.json`
was deleted upstream (data files remain; only the manifest was removed). Data split
into `json/` (meta) and `rtcm/`.

## FineSat gesture pipeline (`finesat/`)

- `data/samples/` — Apr 30, May 15, May 26 (evening, flat) + jn18L1/L2/L3 (Jun 18)
  raw `.rtcm`. Gesture classes: push, pushpull, triangle, m, star.
- `data/archive/` — unique early/morning captures (see [04-data-quality.md](04-data-quality.md#salvage)):
  `samples-old` (Apr 28 push ×2), `samples-good-4-30-morning` (Apr 30 AM push ×3),
  `samples-wo_sec` (Apr 30 AM push ×5). Clean but push-only, no aligned repeats.
- `datasets/` — built feature matrices `X/Y_{finesat,raw}.npy` (samples × 78).
- `models/` — trained weights `*.pth`.
- `notebooks/` — SVM / XGBoost classifiers + exploration.

## jn18 sessions (`finesat/data/samples/jn18L{1,2,3}/`)

Jun 18, three locations (L1/L2/L3), gestures push/pushpull/triangle/m/star, ~2–3
reps each. Ad-hoc timing (no sidereal window control) — see the geometry analysis
in [03-coherence-experiment.md](03-coherence-experiment.md).
