# GNSS Carrier-Phase Gesture Recognition — Project Index

Master index for the project. Start here, then read in the order below.

> **📍 Latest checkpoint: [`docs/CHECKPOINT.md`](docs/CHECKPOINT.md)** (2026-07-23) —
> current state of everything: where all the data lives, the strand reorganization,
> the data/yield inventory, and the lead-in to the classification analysis. The
> code/file map in the sections below predates the role-based reorg (`lib/`,
> `capture/`, `analysis/`, `data/`) — see the checkpoint §1 for the current layout.

**One-line summary.** Recognize hand gestures from the carrier-phase perturbations a hand (acting as a multipath reflector) induces on GNSS signals from a fixed u-blox EVK-F9P antenna — and, as the immediate scientific target, measure the *geometry-decorrelation window* over which a gesture's signal stays reproducible as the satellite geometry drifts.

---

## Reading order

1. **`THEORY.md`** — the physics/math. Read this first; everything else serves it.
2. **`PROJECT_LOG.md`** — what was built and discovered (hardware, observable, the clean-satellite saga, data).
3. **This file (`README.md`)** — navigation, file map, and the **current status** (which is ahead of `PROJECT_LOG.md` on one point — see below).

---

## Documents

| doc | covers |
|---|---|
| `THEORY.md` | Signal model $s_i=\mathbf{g}_i\cdot\mathbf{d}$; correlation as an $M$-metric cosine, $M=\int\mathbf{d}\mathbf{d}^\top dt$; the decorrelation curvature $\kappa$ and its closed form; the headline result that **single-axis gestures are geometry-robust ($\kappa=0$) and multi-axis gestures decorrelate quadratically**; the window $\delta t_{\max}=\omega_{\text{LOS}}^{-1}\sqrt{2(1-r_{\min})/\kappa}$; the reproducibility floor $\alpha$; the sidereal repeat. |
| `PROJECT_LOG.md` | Receiver config and baud reasoning; the MSM-reconstruction trap and switch to RAWX; the extraction pipeline; the **clean-satellite saga** (50 m gate → false slips → lock-time detection) with the yield table (median 2 → 6 → 20); field tooling; the two data sessions; key empirical findings; next steps. |
| `README.md` | This index + current status. |

---

## Code — the pipeline

**Receiver configuration**
| file | role |
|---|---|
| `04-messages.py` | Enable RAWX (primary carrier phase) + SFRBX (ephemeris) + NAV-SAT + RTCM 1077/1127 (MSM7). Baud note: USB CDC is not baud-limited. |

**Observable & signal extraction**
| file | role |
|---|---|
| `parse_rawx.py` | RAWX → continuous carrier phase (m) via `cpMes × wavelength`; cycle slips from `locktime`/`cpValid`. Wavelength map for GPS L1, Galileo E1/E5a, BeiDou B1I/B2a. |
| `extract_signal_v2.py` | Single-difference (kills clock) + deg-2 detrend (kills range trend) + elevation mask + gesture-window detection. |
| `geomlib.py` | Geometry analysis: epoch-keyed MSM (`DF397+DF398+DF406`, `DF407` lock-time) and RAWX parsing; lock-time clean selection; trajectory recovery $D=G^{+}S$; structure matrix $M=DD^\top$. *(Restored this session; carries a caveat — see status.)* |
| `onset_align.py` | Onset aligner: estimates each capture's gesture-onset time (iterative template alignment — "Woody averaging" — on the across-satellite motion envelope) so free-hand timing jitter (~1–1.5 s) doesn't collapse zero-lag correlation. Fold-in point: `extract_signal_v2`, before $M$/feature extraction. *(Added 2026-07-15 — see status.)* |
| `measure_alpha.py` | Reproduce the reproducibility-floor (α) table from a reference session + its sidereal repeat: zero-lag / within-session / across-day, null-calibrated. |
| `common_mode_test.py` / `cno_test.py` | Observable diagnostics (`PROJECT_LOG §10`): where the hand's signal lives — SD vs common-mode phase (confounded with clock) vs **CN0** (clock-free; common-mode CN0 reproduces ~4× the phase pipeline). |

**Field collection tooling**
| file | role |
|---|---|
| `capture_sample.py` | One capture: record stream, write `.meta.json` sidecar (UTC instant, ref sat, per-sat LOS/elev), gate on counts + clean sats. |
| `run_session.py` | Timed multi-window driver: `--windows/--spacing` (reference) or `--targets` (repeat); incremental manifest; countdown as gesture cue. |
| `repeat_schedule.py` | Sidereal repeat-time calculator + Phase-3 offset-sweep generator. *(Known TODO: trim to one target per window.)* |
| `field_monitor.py` | Live TUI health dashboard (RAWX edition): gates on RAWX epochs + NAV-SAT + lock-time clean sats; MSM shown as secondary; hysteresis verdict. |

**Legacy diagnostic plots** (from earlier sessions, kept for reference): `auto_window.png`, `gps_window.png`, `diag_signals.png`.

---

## Data collected

| session | when (UTC) | captures | observable | windows | clean sats (median) |
|---|---|---|---|---|---|
| morning `ref_day1` | ~15:00–15:55 | 48 (push,star × 6 × 4) | MSM7 only | W0–W3 (4) | 6 (recovered via `DF407`) |
| evening `ref_day1.1` | ~21:16–21:34 | 24 (push,star × 6 × 2) | RAWX+SFRBX+MSM+NAV | W0–W1 (2) | 20 (RAWX) |

Collection design: 4 windows × 15-min spacing × 2 gestures × 6 reps. 15 min is the *spacing between* windows (so the ±5–8 min usable windows don't overlap on the repeat day), not the duration.

---

## Current status (up to date — supersedes `PROJECT_LOG.md §7` on α)

### Update 2026-07-15 — GPS sidereal repeat + onset-aligned α

Collected a fresh full 4-window RAWX reference on **07/14** (`ref_day1`, push,star × 6 × 4, median 24 clean sats / 8 GPS) and its **GPS 1-sidereal-day repeat on 07/15** (`repeat_day2`, same design). This is the Phase-3 $\varepsilon=0$ point — same sky, one day later — and it moves three things:

- **Geometry repeat confirmed (LOS + signal).** All four windows saw the *identical* set of GPS PRNs on both days; differential LOS agreed to **≤ 1°** (= NAV-SAT's 1° az/el quantization floor — W3 literally 0°); matched captures are separated by **86164.1 s = one sidereal day to ~0.05 s**. The GPS-only, next-day repeat formula ($T - 3\text{m }56\text{s}$) is empirically validated.
- **The "flat envelope / α≈0" was substantially a *timing* artifact.** Free-hand, the gesture onset lands at a different instant each rep (measured jitter **~1–1.5 s**), so sample-for-sample correlation lines a gesture up against another rep's baseline → ≈ 0. New `onset_align.py` estimates each capture's onset independently (template alignment) and removes it.
- **Honest α is real but low** (onset-aligned, *independent* per-day/per-gesture templates, no per-pair peeking; null-calibrated):

  | pair set (Δθ≈0) | push | star | null (push×star) |
  |---|---|---|---|
  | zero-lag (naive) | 0.12 | 0.02 | — |
  | onset-aligned, **within-session** (honest) | **0.24** | 0.04 | — |
  | onset-aligned, **across-day** (sidereal repeat, honest) | **0.17** | 0.07 | **−0.07** |

  So: **push carries a genuine reproducible signal** (+0.24 above the null), **star barely** (+0.13), and — the clean result — **across-day keeps most of the within-session correlation** (push 0.17 vs 0.24; null −0.07), i.e. a full-sidereal-day matched-geometry repeat preserves ~70% of the reproducible signal. **The geometry repeat is validated at the signal level.** (Reproduce: `uv run analysis/measure_alpha.py` from `window-experiment/`.)

- **Correction / caveat.** Onset alignment is a worthwhile pipeline fix (a real ~1 s jitter, and it roughly doubles within-session correlation), but it does **not** rescue free-hand reproducibility to κ-measurable levels — honest α stays far below the ~0.85 ceiling, and star is near noise. The **mechanical-reproduction requirement stands.** (Intermediate per-pair *best-lag* α ≈ 0.39 for push, reported mid-analysis, was inflated by per-pair lag-fishing against a 0.14 null; the honest independent-template number is ~0.17. The *effect size above null* is stable across methods: push ≈ +0.24, star ≈ +0.13.)

### Update 2026-07-16 — where the signal lives: CN0 beats single-differenced phase

Ran the common-mode test (the README's long-standing open question) and a follow-on CN0 test, both on existing data (`common_mode_test.py`, `cno_test.py`; full detail in `PROJECT_LOG §10`).

- **The low α is partly *processing*, not just physics.** **88%** of the per-satellite phase signal is common-mode, and single-differencing throws it away. The common-mode phase reproduces ~5× better than the single-differenced residual and is gesture-specific.
- **…but common-mode *phase* is unrecoverable with one antenna** — a hand that perturbs all satellites equally is mathematically indistinguishable from the receiver clock (the clock-separating regression fails, doing *worse* than SD). Removing the clock removes the gesture. Would need a **reference antenna** (dual-antenna common-clock), not a mechanical rig.
- **CN0 (signal strength) is the free win.** It has no clock term, so the common-mode survives: **common-mode CN0 reproduces at 0.44 (push) / 0.30 (star) — ~4× the phase-SD pipeline — with a clean null (−0.09).** The hand's effect is dominantly broadband/common-mode (near-field antenna power perturbation, ~2.4 dB-Hz), not directional multipath. **This is a software-only observable upgrade on existing hardware** — the most promising lever for the free-hand classifier.

*Remaining free-hand ceiling:* α ≈ 0.44 is still below ~0.85, so CN0 improves the SNR a lot but doesn't by itself make the *geometric* window measurable — that still needs reproducible gestures.

### Prior status (pre-07/15 geometry analysis)

**Done and solid:**
- Full pipeline (config, capture, extract, monitor, scheduler) built and validated.
- Observable settled: RAWX `cpMes` primary; single-diff + detrend matches RAWX to **0.05 mm**.
- Clean-satellite starvation **solved** — lock-time detection (`DF407`/`locktime`) took the median from 2 → 6 (MSM, 86% recall vs RAWX truth) → 20 (RAWX). Morning MSM-only session recovered.
- Trajectory-recovery method **validated on synthetic ground truth** (known 1D/2D/3D gestures recover with the correct rank).

**The blocking finding (this session's geometry analysis):**
- Computed over the gesture window on lock-time-clean data, the **reproducibility floor α ≈ 0.00–0.06** for both gestures, both sessions — *not* the provisional 0.6 in `PROJECT_LOG.md §7` (that earlier number was an artifact of correlating over the full window, where a common residual trend inflated it).
- Confirmed by direct inspection: two reps of the same gesture, same satellite, time-aligned, **do not resemble each other** (corr ≈ −0.3 to +0.1); the single-differenced envelope is **flat** (no localised gesture event at the cue time).
- Structure metrics (real, but describing non-reproducible signal): only ~51% of the signal is hand translation; recovered $M$ is rank-1 for **both** push and star; the two gestures are statistically indistinguishable.
- **Consequence:** $M$, $\kappa$, and $\delta t_{\max}$ **cannot be honestly extracted** — there is no reproducible signal whose geometric decorrelation could be measured. The `THEORY.md` derivation is still correct; the precondition it flags (§6: $\alpha$ near the noise ceiling) is not met.

**Open question to resolve next:**
- Is the hand's signal largely **common-mode** across satellites (and therefore cancelled by single-differencing)? If so, this is a processing fix, not a dead end. This is the first diagnostic to run.

---

## Next steps (in order)

1. **Adopt CN0 as an observable** — build CN0 features (per-sat + across-sat common-mode) into the dataset/classifier path. It reproduces ~4× the phase-SD pipeline with a clean null, and it's free (software-only, existing hardware). This is the highest-value lever for the free-hand product. *(Common-mode test — the old open question — is done; see `PROJECT_LOG §10`.)*
2. **Fold `onset_align.py` into `extract_signal_v2`** — align every capture to onset=0 before feature extraction, so all downstream stats see time-aligned gestures. Cheap (module exists), lifts the whole pipeline.
3. **Phase-3 repeat-offset sweep** — the geometry repeat is *validated* (07/15), so this is unblocked: revisit at $T+T_{\text{sid}}+\varepsilon$ for a spread of $\varepsilon$ to trace $r(\Delta\theta)$ vs the predicted $1-\tfrac12\kappa\Delta\theta^2$ (needs `repeat_schedule.py` trimmed to one target per window; `targets_repeat_0715.json` is the $\varepsilon=0$ template).
4. **Higher α, if the geometric window is wanted** — either **mechanical reproduction** (isolates $\kappa$; the only route to a clean $M/\kappa/\delta t_{\max}$) or a **reference antenna** (recovers the common-mode *phase* that a single antenna can't separate from the clock — see `PROJECT_LOG §10.1`).
5. **Pipeline hardening** — fold both lock-time detectors into the extractor/monitor as durable code; add GLONASS (freqId wavelength); decode SFRBX for sub-degree LOS.

---

## Provenance note

`THEORY.md` needs no change (the math holds — and its §6 prediction that free-hand α sits below the noise ceiling is now confirmed with a real number). `PROJECT_LOG.md §7`'s "provisional α ≈ 0.6" is superseded: the honest, onset-aligned, null-calibrated floor is **α ≈ 0.17 (push) / ≈ 0.05 (star)** at matched geometry (07/15 update above). The earlier "α ≈ 0" was the *zero-lag* view (real, but a timing artifact); the earlier "α ≈ 0.6" was full-window trend inflation — the truth is between, and low. Onset alignment (not the common-mode test) turned out to be the processing lever; the common-mode test is still worth running.
