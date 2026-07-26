# Window / Geometry-Coherence Experiment (planned)

## Goal & hypothesis

Show that **geometry (window) coherence matters** for gesture classification:
when train/test samples share the same satellite geometry, accuracy is high; across
different geometries it drops — ideally rank-ordered by gesture curvature κ (push
robust, star collapses). This operationalizes the decorrelation theory
([01-signal-model.md](01-signal-model.md)).

## Why the naïve split is not enough

"Train within a geometry vs across geometries" confounds *geometry* with *day /
hardware / satellite-set / gesture-execution drift*. A cross-geometry accuracy drop
could just be "models don't transfer across days."

## The fix: decouple geometry from time (2×2)

|  | Same day | Different day |
|---|---|---|
| **Same geometry** | within-window CV | **c3.2 W2: Jul 1 / 15 / 22** (sidereally aligned) |
| **Different geometry** | **c1.1_day1: W0 vs W1 vs W2 vs W3** (15 min apart, same hardware) | c1.1 vs c3.2 |

- **Different geometry, same day** (c1.1 windows): only the sky changed → an accuracy drop here is *purely geometric*.
- **Same geometry, different day** (c3.2 W2, 3 weeks span): time changed maximally, geometry held → if accuracy *holds*, recency/hardware isn't the driver.

## Flagship experiments the data supports

1. **c1.1_day1 within-day window ramp** — train on W0, test W0→W3; plot accuracy vs
   sidereal separation. 100% clean yield, same session. The cleanest one-variable result.
2. **c3.2 W2 cross-day series** — Jul 1 / 15 / 22, sidereally aligned. Does aligned
   geometry hold accuracy across weeks? (day1/day2 100% yield; day3 ~53%.)
3. **c1.1 ↔ c3.2 cross-regime** — disjoint satellite sets, so per-satellite features
   can't align → **requires the trajectory-inversion representation** (below).
4. **ref_day1** — a second within-day 4-window ramp (push+star), 100% yield.

## The two design forks (both chosen: "do both")

**Fork (a) — problem, then fix:**
- *Option 1 (problem):* classify on the geometry-**naive** signal (per-satellite
  single-differenced, detrended phase). Expect within-geometry high, cross-geometry low.
- *Option 2 (fix):* classify on the recovered 3-D hand trajectory `d(t)` obtained by
  inverting the g-matrix. Geometry-**invariant** (common ENU antenna frame) → the
  cross-geometry drop should *disappear*. This is a manipulation check that turns the
  result causal, and it is **required** for the cross-regime comparison.

**Fork (b) — aggregate AND per-gesture κ:** report overall accuracy *and* break the
cross-geometry drop down by gesture. The strong, hard-to-fake signature is
push > triangle/m > star, matching κ.

## Feasibility on current data

| Component | Feasible? | Where |
|---|---|---|
| Option 1, across-window | ✅ high | c1.1 ramp, ref_day1 |
| Fork (b) per-gesture | ✅ high | free once predictions exist |
| Option 1, across-regime | ⚠️ weak alone | needs option 2 (sat sets disjoint) |
| Option 2 (trajectory inversion) | ✅ where ≥3 clean sats | c1.1 (all), c3.2 W2 (day1/2); g-vectors free from meta `los_enu` |
| Per-gesture **κ from data** | ✅ (same inversion gate) | κ from `M = ∫ d dᵀ dt` of recovered trajectory |

**Gates:** the inversion needs ≥3 non-coplanar clean sats. Yield is good for c1.1 and
c3.2 W2 day1/day2; marginal for c3.2 W1 and day3 W2. Health can likely be improved by
re-gating on `DF407` lock-time instead of the old 50 m gate.

## Constraints to honor in the pipeline

- **Do not assume the gesture is in a fixed 3–6 s slice** — detect onset (see
  `window-experiment/analysis/onset_align.py`).
- **Re-single-difference to a common reference** — `ref_sat` varies across captures.
- **Handle satellite correspondence** — cross-geometry the visible PRNs differ; a
  PRN-indexed feature vector misaligns (a trivial cause of the drop, not the geometric one).
- **Small N** (~6 reps/gesture/window) — use simple classifiers, repeated stratified
  CV, permutation tests, report mean±std vs 20% chance.
- **Labels are already normalized** — all manifests use `triangle` (fixed
  2026-07-23); no per-loader shim needed.

## Aside: the jn18 / early ad-hoc data

The jn18 (Jun 18) and Apr/May captures were collected with **no window control**. A
sidereal analysis found only one accidental same-geometry pair (Apr 30 ↔ jn18-L1,
~1 min drift, coincidental). These are usable as extra training diversity but not for
the controlled coherence experiment.
