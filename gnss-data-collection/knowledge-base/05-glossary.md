# Glossary

**Carrier phase** — the phase of the GNSS carrier wave, measured in cycles/meters.
Millimeter-sensitive, which is why nearby hand motion is detectable.

**Sky regime** — a wholesale satellite configuration tied to time of day. Captures
at very different sidereal times see different satellites at different angles =
different regimes. (Our term; coarser than a "window".)

**Window** — a 15-minute-spaced collection slot within a session. Each ≈ 7° of LOS
rotation — a small, real geometry change. Indexed W0, W1, W2, W3.

**Geometry** — the satellite configuration determining the LOS vectors `ê_i` (hence
the sensitivity vectors `g_i`). Repeats each sidereal day; drifts continuously.

**Sidereal day** — ~23h 56m 4s, the period over which the satellite geometry
repeats. Cross-day sessions are collected ~4 min earlier each day to hit the same
geometry ("sidereally aligned").

**Line-of-sight (LOS) vector `ê_i`** — unit vector from antenna to satellite *i*.
Stored per satellite as `los_enu` in the meta sidecars.

**Sensitivity / differential LOS vector `g_i`** — `(2π/λ)(ê_i − ê_ref)`; how a hand
displacement maps to phase change on satellite *i* after single-differencing.

**Single-differencing** — subtracting a reference satellite's phase to cancel the
receiver clock. Requires a `ref_sat` (which varies across our captures).

**Detrending** — removing a low-order polynomial (2nd/3rd order) over the window to
strip the smooth geometric range trend, leaving the gesture signal.

**Structure matrix `M`** — `∫ d(t) d(t)ᵀ dt`, the 3×3 scatter matrix of the gesture
trajectory. Encodes gesture *shape*; source of the curvature κ.

**κ (curvature)** — dimensionless quantity governing how fast a gesture's signal
decorrelates with geometry drift. κ→0 for single-axis gestures (robust); larger for
multi-axis gestures (decorrelate quadratically).

**MSM7** — RTCM Multiple Signal Message type 7, full-resolution GNSS observables.
`1077` = GPS, `1127` = BeiDou. The only observable format in our data.

**RAWX** — UBX-RXM-RAWX, u-blox raw carrier-phase message (with `locktime`/slip
flags, all constellations). **Not present** in our captures — MSM7 only.

**DF398 / DF406 / DF407** — RTCM MSM data fields: rough range (mod 1 ms, ~293 m
LSB) / fine phase-range / phase lock-time indicator. `DF407` is the correct
cycle-slip detector.

**Cycle slip** — a discontinuity in carrier-phase tracking (lost lock). Detected by
a `DF407` lock-time decrease; the old 50 m distance gate produced false positives.

**Clean satellite** — one with a full set of epochs and no cycle slip over the
window. ≥3 non-coplanar clean sats are needed to invert for the 3-D trajectory.

**Trajectory inversion** — solving `s_i(t) = g_i · d(t)` (least squares over clean
sats) to recover the geometry-invariant 3-D hand trajectory `d(t)`.

**c-series / s-series** — session naming. `cN.M_dayK` = gesture geometry sessions
(c1.1, c3.2…); `sN.M` = breathing sessions. Window suffix `_W0..W3`, timestamp `Z` (UTC).

**Gesture classes** — push, pushpull, triangle, m, star (c-series). push is
single-axis (κ→0); star is multi-axis (high κ).

**Strand** — a largely self-contained line of work in this repo: `finesat`,
`window-experiment`, `breathing`, plus `shared` infrastructure.
