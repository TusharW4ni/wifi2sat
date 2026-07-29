# Findings — GNSS carrier-phase gesture sensing (Phases 0–3)

Honest end-to-end summary of the window/coherence analysis as of 2026-07-24.
Companion to `ANALYSIS_PLAN.md` (the plan), `CHECKPOINT.md` (running state), and
the per-phase GitHub issues (#2–#5). Bottom line up front, evidence below.

## Bottom line

On the **free-hand** data collected so far, the project's core thesis — that a hand
perturbs GNSS **carrier phase** in a **geometry-dependent** way that supports gesture
recognition and a geometry-decorrelation window — is **not demonstrable**, for three
compounding reasons:

1. **Phase doesn't reproduce.** Carrier-phase channels (single-difference, CMR) sit
   at the null across sessions (α ≈ 0; push-SD reaches only ~0.14–0.24). The
   geometry-carrying observable is too weak to build on.
2. **The only reproducible signal is amplitude (CN0), not phase** — and CN0 is a
   broadly non-directional proximity/shadowing effect, not the phase-trajectory
   mechanism the theory (κ) is written for.
3. **Classification is confounded with acquisition time, and doesn't transfer.**
   Gestures are recorded in contiguous per-gesture time-blocks, so within-window
   accuracy is inflated by environmental drift; and at matched geometry the signal
   does not survive to another day.

Net: there is a **real but modest, non-reproducible, amplitude-based** effect — not
the carrier-phase-geometry result the project set out to demonstrate. **The unlock
is re-collection, not more analysis** (see Recommendations).

## Evidence by phase

**Phase 0 (infra).** `lib/dataset.py` + `analysis/preprocess.py`: unified loader
(observable auto-detected, MSM7/RAWX never silently pooled), DF407/locktime slip
cleaning (rescues clean-sat yield, e.g. c3.2_day1 W1 13 %→100 %), common-reference
single-differencing, onset alignment, and a per-capture feature object {SD, CM, CMR,
CN0, g-vectors, onset lag}. Sound and reused by all later phases.

**Phase 1 — reproducibility (α), the gate (#3).** `alpha_study.py`, all sessions ×
5 channels × gestures, matched null, bootstrap CIs.
- **CN0-common** most reproducible (0.2–0.74), observable-independent; **CN0-per-sat**
  broad. **push-SD** passes for push only (0.13–0.23). **CMR / CM** at null.
- Onset alignment helps only where signal exists; RAWX gives cleaner phase than MSM.
- Verdict: build on CN0 (primary) + push-SD (secondary). *Already a warning sign —
  the reproducible channel is amplitude, not the geometry-dependent phase.*

**Phase 2 — within-window separability (#4).** `separability.py`.
- c1.1_day1 W0/W1 5-class (chance 20 %) → linSVM 64/69 %, p=0.005.
- **Ablation:** CN0-only ≈ CN0+SD ≫ **SD-only (at chance)** → the signal is CN0
  amplitude, not phase.
- **Acquisition-time confound (found in review):** the pre-onset, gesture-free
  baseline classifies at **42 %** (chance 20 %) — so ~2/3 of the "64 %" is
  time/environment leakage; genuine gesture increment ≈ 22 pp.

**Phase 3 — geometry / window coherence, the headline (#5).** `coherence.py`.
- **Arm 1 (different geometry, same day):** CN0 accuracy appears to decay with
  window separation — **but window ≡ elapsed-time ≡ geometry-drift are collinear**,
  and the gesture-free baseline **reproduces the decay**. So it is a time/environment
  effect, **not attributable to geometry**.
- **Arm 2 (same geometry, different day) — the decisive test:** train one day → test
  the other day's same (sidereally-aligned) window. **Accuracy does not transfer:**
  c3.2 day1→day2 5-class collapses to ≈ chance (W2 CN0 33 % vs baseline 30 %; W3 at
  chance; SD at chance); ref→repeat is tiny-N noise with baselines as high as the
  "signal". So the within-session accuracy was largely per-session/environmental —
  **no transferable, geometry-locked gesture fingerprint is demonstrable.**

## Caveats (honest bounds)

- **Small N** throughout (≤6 reps/gesture/window; cross-day tests n=6–30). A small
  real transferable effect cannot be *excluded* — only that none is demonstrable.
- Conclusions are about *this free-hand dataset*, not the physical hypothesis in
  principle. The κ mechanism is verified on synthetic ground truth (`geomlib`); the
  problem is the data's reproducibility floor, not the math.
- The amplitude (CN0) effect is real within a session — it's the *transfer* and the
  *phase/geometry attribution* that fail.

## Recommendations (the critical path is data, not analysis)

1. **Re-collect with interleaved gesture order** — randomize gesture order within each
   window so gesture label is no longer confounded with recording time. This alone
   makes Phase 2/3 interpretable.
2. **Mechanically reproduce gestures** (issue #11) to raise the phase reproducibility
   floor α — the only way to test the carrier-phase-geometry thesis at all.
3. With clean data, re-run the existing pipeline unchanged (Phases 1–3 are built and
   validated) and add: CV-internal onset/sat-selection (remove the minor leakage),
   and the κ per-gesture breakdown on the phase channel (push robust vs star).
4. If phase α stays ≈ 0 even mechanically, the honest scientific result is that a
   single fixed antenna senses the hand via **broadband amplitude/proximity**, not
   carrier-phase geometry — publishable as such, and a different (simpler) sensor
   story than the FineSat premise.
