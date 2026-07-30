# Session handoff — window experiment, Phases 0–3 + review (July 2026)

Read this + `FINDINGS.md` + `CHECKPOINT.md` first when picking this up.

## TL;DR
- **Analysis Phases 0–3 are DONE.** The project's carrier-phase-geometry thesis is
  **unsupported on the free-hand data** — the reproducible signal is broadband
  **CN0 amplitude**, it's ~⅔ acquisition-time confound within a session, and it
  **does not transfer across days** at matched geometry. Full write-up: `FINDINGS.md`.
- **Work on branch `phase3-working` (commit `2677475`, local-only). The pipeline
  RUNS there.** Do **not** build on `main` — it's currently broken (see Gotchas).
- The real next step is **re-collection, not more analysis** (interleave gesture
  order + mechanically-reproduced gestures, issue #11).

## What was accomplished this session
1. **Data-quality cleanup** (#7–#10 closed): labels normalized (`traingle`→`triangle`,
   96 dup files removed), `c3.2_day2` W3 recovered into its manifest, two `push→pushpull`
   split-pairs fixed, archive `ref_day1`↔`ref_jun26` name collision resolved.
2. **Phase 0** (#2): `lib/dataset.py` (unified catalog + loader; observable
   auto-detected from RXM-RAWX; guard against silently pooling MSM7+RAWX) and
   `analysis/preprocess.py` (per-capture feature object: DF407/locktime slip
   cleaning, common-reference single-difference, onset alignment, CMR trajectory,
   CN0). DF407 gate rescued clean-sat yield (c3.2_day1 W1 **13%→100%**).
3. **Phase 1 — α study** (#3, the gate): `analysis/alpha_study.py`. Reproducibility
   α over 5 channels × 6 sessions × gestures, matched null, bootstrap CIs. Verdict:
   **CN0 reproduces (up to 0.73); carrier phase SD/CMR/CM sit at the null.**
4. **Phase 2 — separability** (#4): `analysis/separability.py`. Within-window 5-class
   ≈64% (chance 20%). Ablation → the signal is **entirely CN0 amplitude, SD at chance**.
   Pre-onset `--baseline` control → ~⅔ of the accuracy is **acquisition-time leakage**.
5. **Phase 3 — coherence** (#5, headline): `analysis/coherence.py`. Arm 1 (within-day
   window ramp) is **confounded** (gesture-free baseline reproduces the decay; window
   ≡ time ≡ drift collinear). Arm 2 (same geometry, **different day**) is the decisive
   test and is **NEGATIVE** — no cross-day transfer above baseline/chance.
6. **Review + verification**: an adversarial review agent found the acquisition-time
   confound (I verified it + built the `--baseline` controls). A 6-agent verification
   workflow re-derived every load-bearing claim → **6/6 SUPPORTED, high confidence**
   (with honest refinements: SD is chiefly-not-solely push; arm-1 baseline is
   above-chance more than it matches the decay; CN0 is the most *consistently*
   reproducible channel).
7. **HTML report artifact**: https://claude.ai/code/artifact/422bd68c-1123-41f1-999e-22307b82456e
8. Docs: `FINDINGS.md` (conclusion), `CHECKPOINT.md`, `ANALYSIS_PLAN.md` §0,
   `PROJECT_LOG.md` §11–12, and the knowledge-base data-quality docs updated.

## Issues
- **Closed:** #2, #3, #4, #5 (analysis phases), #7–#10 (data-quality).
- **Open:** #6 (Phase 4 — trajectory inversion & κ; **blocked** — needs phase α,
  which is ≈0), #11 (mechanical gesture rig — the real unlock).

## ⚠ Gotchas / traps (critical for the next session)
1. **`main` (8b7e50b) pipeline is BROKEN.** Two committed data defects, both from a
   teammate's `refactor/data-pipeline` PRs merged after our work:
   (a) `data/archive/manifest-old/` duplicates the active manifests → the
   no-pool/collision guard in `dataset.catalog()` raises → **every analysis script
   crashes before running**; (b) `c1.1_day1_manifest.json`'s `rtcm` fields point to
   deleted `traingle_*.rtcm` files (48 dangling refs; re-broke the label
   normalization). **Use `phase3-working` (clean) until this is fixed/coordinated.**
2. **Acquisition-time confound** — the big scientific trap. Gestures were recorded in
   contiguous per-gesture time-blocks, so gesture label ≡ recording time. Always run
   the `--baseline` (pre-onset, gesture-free) control alongside any accuracy. Future
   captures **must interleave gesture order** within a window.
3. **Never pool MSM7 + RAWX** observables (the loader guards this; don't override
   without reason).
4. **Small N** (≤6 reps/gesture/window) — every accuracy/α has wide CIs; the
   direction, not the exact %, is load-bearing.

## Branch state
```
phase3-working   2677475   ← current; OUR Phase 0–3 work; clean data; pipeline RUNS; local-only
main             8b7e50b   ← teammate PRs + BROKEN pipeline; untouched this session
phase3-coherence 8b7e50b   ← stale (the rebased/broken version; origin gone); safe to delete
```

## Suggested next steps
- Coordinate the `main` breakage fix with whoever owns `refactor/data-pipeline`
  (skip the `manifest-old` backup dir in the catalog scan; re-normalize the c1.1
  manifest `rtcm` fields to `triangle_`).
- Decide whether to push `phase3-working` to a remote home and/or delete the stale
  `phase3-coherence`.
- Science: the analysis is complete and validated for this dataset — prioritize
  **re-collection** (interleaved gestures + mechanical rig) over more analysis.
