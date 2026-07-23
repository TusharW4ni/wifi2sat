# Data Quality, Constraints & Known Issues

The traps. Read before analyzing.

## Observable & reconstruction

- **Observable format is mixed across sessions** (do not silently pool):
  - **MSM7-only** (RTCM 1077 GPS + 1127 BeiDou, phase reconstructed from DF fields):
    `c1.1_day1`, `c3.2_day1`, `c3.2_day2`.
  - **RAWX + SFRBX** (clean `cpMes·λ` carrier phase + lock-time + ephemeris):
    `ref_day1`, `repeat_day2`, `c3.2_day3`.
  The RAWX sessions are the cleaner carrier-phase source; the MSM sessions need
  reconstruction and are the ones the slip-reconstruction caveats below apply to.
- **Naïve phase reconstruction injects false slips.** `(DF398 + DF406) × c/1000`
  steps at rough-range LSB boundaries trip the 50 m slip gate. The MSM phase
  *observable* is sound (0.05 mm RMS vs RAWX); the reconstruction + gate were the bug.
- **Use `DF407` lock-time for slips**, not a 50 m distance gate. The meta
  `passed_health` flags used the old gate and likely **undercount** clean sats.

## Timing & alignment

- **Gesture is NOT guaranteed in the nominal 3–6 s window.** Despite the capture
  prompt, the operator may act early/late. Detect onset; don't hardcode a slice.
  (`window-experiment/phase1/onset_align.py`.)
- **`ref_sat` varies across captures within a session** (e.g. c1.1 uses both
  `BDS_042` and `GPS_029` as reference). Single-differenced signals are therefore not
  directly comparable as stored — re-single-difference to a common reference.
- **Satellite sets differ across geometries.** Within a regime (15-min windows) they
  mostly overlap; across regimes (c1.1 vs c3.2) they're nearly disjoint, so
  per-satellite feature vectors can't be aligned across regimes.

## Labels & manifests

- **`traingle` vs `triangle`** typo: c1.1 and c3.2_day1 use `traingle`; c3.2_day2/day3
  use corrected `triangle`. Normalize before cross-day matching.
- **`c3.2_day2` manifest `session` field says `"s3.2_day2"`** (s, not c) — cosmetic
  metadata inconsistency.
- **On-disk data can exceed a manifest** — e.g. day2 had extra Jul-15 files beyond
  what the manifest listed at write time. Trust the files, cross-check the manifest.
- **`s2.3_manifest.json` was deleted upstream** (day3 commit). The s2.3 breathing
  data files remain; only the manifest was removed. Honored in the merge.
- Possible **cross-directory duplication** of the June 26 `ref_day1` session between
  `phase1/samples/` and `phase1/samples-not-rawx-but-good/` — worth reconciling.

## Salvage findings (archived micro-dirs) {#salvage}

Assessed the ad-hoc micro-collections against current knowledge:

| Dir | Verdict |
|---|---|
| `finesat/data/archive/samples-50-xgboost` | **Deleted** — 100% byte-duplicates of the Apr 30 evening set |
| `finesat/data/archive/samples-old` (2) | Kept — Apr 28 push, unique, clean (~13 sats) |
| `finesat/data/archive/samples-good-4-30-morning` (3) | Kept — Apr 30 AM push, unique, clean |
| `finesat/data/archive/samples-wo_sec` (5) | Kept — Apr 30 AM push, unique, clean |
| `window-experiment/phase1/samples-not-rawx-but-good` (48) | Kept — **complete Jun 26 4-window push+star session**, MSM, good yield; usable as an extra window ramp |
| `window-experiment/phase1/samples-old` (7) | Kept — fragmentary earlier Jun 26 W0 push+star; low value |

The 10 unique finesat push captures (Apr 28 + Apr 30 AM) are clean but push-only
with no sidereal-aligned repeats → useful only as extra push-class *training*
diversity, not for the coherence experiment.

## Cleanup already done (2026-07-22)

- Deleted `samples-50-xgboost` (50 dupes) and 3 redundant zip archives
  (`breathing_samples_s1.3.zip`, `ref_day1.zip`, `ref_day1.1.zip`) whose every file
  exists as loose committed data (~12 MB freed).
- Merged all branches into `main`, reorganized into strands, pushed.
