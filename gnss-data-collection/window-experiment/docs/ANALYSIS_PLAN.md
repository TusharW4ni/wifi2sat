# Analysis Plan — GNSS Carrier-Phase Gesture Sensing

**Date:** 2026-07-23. Companion to `THEORY.md` (physics), `PROJECT_LOG.md` (build
history), `CHECKPOINT.md` (current state), and the repo
[`../../knowledge-base/`](../../knowledge-base/).

Guiding principle: **signal before inference.** Each phase has a decision gate; we
do not make a geometry or classification claim on a channel until that channel is
shown to carry reproducible signal above a matched null. Every reported number
carries a permutation/bootstrap confidence interval.

---

## 0. Empirical starting point (measured, not assumed)

Running the existing reproducibility apparatus (`measure_alpha.py`,
`common_mode_test.py`, `cno_test.py`) gives the ground truth the plan is built on.

### Observable type is not uniform

| Observable | Sessions |
|---|---|
| **MSM7 only** (reconstruct phase from `DF397+398+406`) | `c1.1_day1`, `c3.2_day1`, `c3.2_day2` |
| **RAWX + SFRBX** (clean `cpMes·λ` phase + lock-time + ephemeris) | `ref_day1`, `repeat_day2`, `c3.2_day3` |

### Reproducibility floor α (onset-aligned, GPS, `ref_day1`↔`repeat_day2`)

α = correlation of the *same gesture* with itself at matched geometry.

| Observable | push α | star α | null | reading |
|---|---|---|---|---|
| **SD phase** (LOS-differenced per-sat) | **0.17–0.24** | ~0.05 | −0.07 | push reproduces weakly; star ≈ noise |
| **CMR** (LOS-separated spatial gesture) | 0.07 | ~0.00 | ~0.00 | the geometrically-consistent gesture does **not** reproduce |
| **CM** (common-mode mean) | 0.52 | 0.63 | **0.20** | high, but star≥push & high null → clock/environment artifact, *not* gesture |
| **CN0 per-sat** (amplitude) | 0.18 | 0.10 | 0.00 | amplitude reproduces above null for both gestures |
| **CN0 common-mode** | **0.44** | 0.30 | −0.09 | most reproducible channel |

Plus: **~88 % of per-satellite signal energy is common-mode** (single-differencing
discards it).

### What this forces

1. Free-hand **phase** gesture signal is real but marginal, and only for **push**
   (single-axis). Star phase is noise. The push≫star ordering *is* the κ signature
   from `THEORY.md` — a genuine result, not a failure.
2. The bulk (common-mode) energy is dominated by clock/environment, not gesture
   (star≥push, null=0.20) — there is no "processing rescue" hiding there.
3. **CN0 (amplitude) is the most reproducible channel**, and unlike phase it carries
   star as well — amplitude sensing is less LOS-geometry-dependent.

The plan therefore leads with signal characterization, gates hard, and is explicit
about which channel/gesture each downstream claim is allowed to use.

### Cross-session confirmation — full α matrix (2026-07-24, Phase 1)

The three ad-hoc scripts above are now generalized into one bootstrapped study,
`analysis/alpha_study.py` (per-cell 95% CI + pass/fail vs matched null, per
gesture × window = matched geometry), run over **all 6 active sessions** × 5
channels × 5 gestures → [`../results/alpha_matrix.json`](../results/alpha_matrix.json).
It reproduces the table above (push-SD across-day +0.14 vs measure_alpha's 0.17 —
the gap is alpha_study's 20° elevation mask) and extends the verdict:

- **CN0-common ✅ strongest** — clears null in nearly every session (0.2–0.74).
- **CN0-per-sat ✅** — broad (push, pushpull, m; some triangle/star).
- **SD-phase ✅ push only** — 0.13–0.23 across most sessions incl. across-day;
  marginal/absent for other gestures; near-null in c1.1 and weak-negative in
  c3.2_day2. (The c3.2_day2 −0.18 is per-window W1 −0.01 / W2 −0.22 / W3 +0.32 —
  small-N (3v3 split) noise around null in a marginal channel, **not** a W1
  artifact or real anti-correlation; the cell doesn't clear null. See #3.)
- **CMR ❌ / CM ❌** — at null bar scattered cells (c3.2_day1 push CMR +0.22,
  c3.2_day3 pushpull SD/CMR ~+0.4).

**Gate:** Phase 2/3 proceed on **CN0 (primary) + push-SD (secondary)**; CMR/CM
carry no reproducible free-hand signal. Amplitude (CN0) dominating over phase is
itself a caveat for the geometry thesis (Phase 3).

---

## 1. Data → role assignment (all relevant data)

| Dataset | Observable | Role |
|---|---|---|
| `ref_day1` ↔ `repeat_day2` (push+star, 4-window, 100 % yield, consecutive days) | RAWX | **Primary testbed** — cleanest cross-day same-geometry pair + within-day ramp |
| `c3.2` W2 (day1/2/3, 5 gestures) | MSM → day3 RAWX | **3-timepoint cross-day** series (Jul 1 / 15 / 22), multi-week |
| `c1.1_day1` (5 gestures, 4 windows, 100 % yield) | MSM | **Within-day geometry ramp**, 5-class |
| `c3.2_day1` (5 gestures) | MSM | Cross-regime partner to `c1.1`; window ramp (uneven yield) |
| `archive/samples-not-rawx-but-good` (Jun 26, push+star, 4-window) | MSM | Extra window ramp / MSM-vs-RAWX control |
| finesat Apr/May/jn18 | MSM | Training diversity only (no window control) — **not** for coherence claims |

---

## 2. Phases

### Phase 0 — Shared infrastructure (build once)
Reuse/extend `geomlib`, `onset_align`, `extract_signal_v2`, `compute_windows_manifest`,
`parse_rawx`. One preprocessing pipeline emitting a tidy per-capture feature object.
- **Unified loader** → carrier phase (RAWX `cpMes·λ`; else MSM `DF397+398+406`), CN0,
  per-sat `los_enu`/elev, `DF407`/`locktime` slip flags.
- **`DF407`/lock-time cleaning** (not the 50 m gate); report improved yield vs the meta
  `passed_health` floor (may rescue `c3.2` W1 / day3-W2).
- **Common-reference single-differencing** (fixes the varying `ref_sat`).
- **Onset alignment** as a standard step (`onset_align.align_group`).
- Output per capture: {SD phase, CN0, CMR trajectory, g-vectors, onset lag}.

*Gate: none — foundation.*

### Phase 1 — Signal characterization (the α study) ← the gate
Generalize the three α scripts into one bootstrapped study over **all** sessions ×
observables (SD, CM, CMR, CN0-per-sat, CN0-CM) × gestures, each vs its matched null,
with CIs.
- Which observable maximizes α? (hypothesis: CN0 > SD-phase ≫ CMR.)
- Does α survive across-day (geometry-matched)? Does onset alignment help? RAWX vs
  MSM difference (`c1.1`/`c3.2` vs `ref`/`repeat`)?
- **Deliverable:** an α matrix with CIs selecting the observable(s) and gestures that
  carry signal.
- **Gate:** proceed per-channel only where the α CI is clear of null. Current
  evidence: push-SD-phase ✓, CN0 ✓; star-phase ✗; CMR ✗.

### Phase 2 — Within-geometry separability (classification baseline)
On the passing channels, classify gestures **within a single window** (best case:
`c1.1` W0, `ref` windows). Features from SD-phase + CN0; simple models
(LDA / kNN / linear-SVM); repeated stratified CV; permutation null; chance = 20 %
(5-class) or 50 % (push-vs-star).
- **Deliverable:** best-case accuracy + confusion matrix, CI'd.
- **Gate:** if within-window is at chance on all channels, the geometry question is
  moot for that data → go to escalation.

### Phase 3 — Geometry / window coherence ← the headline (gated on 1 & 2)
The 2×2, run **only** on channels that passed:
- **Different geometry, same day:** train `c1.1` W0 → test W1/W2/W3; accuracy and r vs
  sidereal separation (pure geometry drift, same hardware).
- **Same geometry, different day:** `ref`↔`repeat` (push+star, RAWX) and `c3.2` W2
  (3 timepoints, 5-class). Does aligned geometry hold accuracy across days/weeks?
- **Cross-regime:** `c1.1` vs `c3.2` — requires Phase 4 trajectory (disjoint satellites).
- Tie ML accuracy to the physical r(Δθ) and to κ; **per-gesture breakdown** (does push
  survive where star does not — the κ prediction, which α already hints at).
- **Deliverable:** accuracy-vs-drift curves + within/cross/cross-day/cross-regime table
  + the accuracy↔α↔κ correspondence.

### Phase 4 — Trajectory inversion & κ (mechanistic confirmation)
`d(t)=pinv(G)·S` (`geomlib`, verified on synthetic ground truth). Compute `M=DDᵀ`, κ per
gesture; test the theory's push < triangle/m < star ordering. Provides the
geometry-invariant features for the cross-regime arm of Phase 3.
- **Caveat baked in:** CMR α≈0 (§0) means real-data trajectories may be noise. Phase 4
  validity is itself gated on Phase 1's CMR result. If CMR stays ≈0, report κ from
  synthetic + nominal gesture shapes only, and say so explicitly.

---

## 3. Cross-cutting discipline
Permutation nulls everywhere; bootstrap CIs; onset alignment with **independent**
templates (no shared-template inflation — the existing code already does this right);
one signal per satellite; report N; RAWX and MSM never silently pooled.

## 4. Risks, pivots, escalation
- **Primary risk (live):** free-hand phase α is marginal. Pivot order: SD-phase (push)
  → CN0. If all gesture channels are too weak for Phase 3, the deliverable becomes a
  rigorous characterization of *why* free-hand GNSS gesture sensing is signal-limited,
  and the CN0 regime where it is not — itself a real result.
- **Escalation (out of analysis scope):** the fix for α≈0 named in `THEORY.md` /
  `geomlib.py` is **mechanical gesture reproduction** to raise the reproducibility
  floor. If Phase 1–3 confirm free-hand phase is too weak, the recommendation is a
  mechanical-rig data collection — to be flagged, not silently accepted.

## 5. Sequencing

```
P0 (infra) ──► P1 (α study, GATE) ──► P2 (within-geometry) ──► P3 (coherence) ──► P4 (κ)
```

P0 → P1 first; everything downstream is gated on the Phase 1 α matrix.
