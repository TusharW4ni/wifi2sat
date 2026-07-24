# Signal Model & Theory

## Hardware & stream

- **Receiver:** u-blox EVK-F9P, fixed antenna, USB serial @ 115,200 baud.
- **Rate:** 10 Hz (100 ms measurement interval).
- **What we record** (see `shared/receiver-setup/`):
  - **RTCM 1077** — GPS MSM7 carrier-phase observables
  - **RTCM 1127** — BeiDou MSM7 carrier-phase observables
  - **UBX-NAV-SAT** — per-satellite elevation/azimuth (1° resolution)
  - **UBX-RXM-RAWX** + **UBX-RXM-SFRBX** — present in the *later* sessions (clean
    `cpMes·λ` carrier phase + lock-time + broadcast ephemeris)
  - NMEA (GNVTG/GNGLL) position/velocity is sometimes present but unused

> **Critical fact:** the observable format is **not uniform across sessions**.
> - **MSM7-only** (GPS + BeiDou, phase reconstructed from DF fields): `c1.1_day1`,
>   `c3.2_day1`, `c3.2_day2`.
> - **RAWX + SFRBX** (clean carrier phase + lock-time + ephemeris): `ref_day1`,
>   `repeat_day2`, `c3.2_day3`.
>
> See [04-data-quality.md](04-data-quality.md). Never silently pool RAWX and MSM.

## The observable

To leading order, the multipath-induced carrier-phase perturbation on satellite *i* is

```
φ_i(t) ≈ (2π/λ) · ê_i · d(t)  +  c(t)   +  ρ_i(t)  +  noise
                                 clock     range trend
```

where `d(t)` is the hand displacement (the gesture), `ê_i` the line-of-sight unit
vector to satellite *i*, `λ` the carrier wavelength.

- **Single-difference** vs a reference satellite removes the receiver clock `c(t)`.
- **Detrend** (2nd/3rd-order polynomial over the window) removes the smooth range trend `ρ_i(t)`.

What remains is the gesture signal:

```
s_i(t) = g_i · d(t),      g_i = (2π/λ)(ê_i − ê_ref)
```

`g_i` is the **differential LOS sensitivity vector**. All geometry enters through these.

## MSM7 carrier-phase reconstruction (from RTCM)

Carrier phase is rebuilt from MSM7 fields per satellite/signal cell:

| Field | Meaning |
|---|---|
| `DF397` | rough range, integer ms |
| `DF398` | rough range, mod 1 ms (≈293 m LSB) |
| `DF405` | extended fine phase-range |
| `DF406` | fine phase-range |
| `DF407` | **phase lock-time indicator** — the correct cycle-slip detector |

The current scripts reconstruct phase as `(DF398 + DF406) × c/1000`. **Caveat**
(from `window-experiment/docs/PROJECT_LOG.md`): this naïve rough+fine sum injects
periodic **false cycle slips** at LSB boundaries, which the old 50 m slip gate then
rejected — starving clean-sat yield to a median of ~2. The fix is to gate on
**`DF407` lock-time decreases** instead of a distance threshold. The MSM phase
*observable itself is sound* (matches RAWX to 0.05 mm RMS); only the reconstruction
and the gate were buggy.

## Geometry decorrelation & the curvature κ

Perform the *same* gesture at two times separated by Δt. The LOS rotates
(`g_i^A → g_i^B`), so the signal reproducibility is the generalized cosine in the
metric of the gesture's **structure matrix** `M = ∫ d(t) d(t)ᵀ dt`:

```
r = (g_Aᵀ M g_B) / (√(g_Aᵀ M g_A) · √(g_Bᵀ M g_B))
```

A small-drift expansion gives a decorrelation governed by a single dimensionless
**curvature κ** that depends on the *shape* of the gesture:

- **Single-axis gestures** (e.g. push) → κ → 0 → geometrically **robust**.
- **Multi-axis gestures** (e.g. star) → decorrelate **quadratically** with drift.

This is the theoretical basis for the coherence experiment
([03-coherence-experiment.md](03-coherence-experiment.md)) and predicts that
cross-geometry classification should fail in a **gesture-shape-dependent** way, not
uniformly. Full derivation: `window-experiment/docs/THEORY.md`.

**Model caveat (empirical):** the pure LOS-projection model explained ~69 % of the
push variance but only ~39 % of the star variance — real specular reflection and
antenna phase-center effects mean this is first-order, not exact.

## g-vectors are available in the data

Each capture's `.meta.json` sidecar (c-series sessions) already contains, per
satellite: `los_enu` (ê_i in ENU), `elev_deg`, `azim_deg`, `ref_sat`, and a
`passed_health` flag. So `g_i` can be formed **without** re-deriving geometry from
NAV-SAT — important for the trajectory-inversion arm of the experiment.
