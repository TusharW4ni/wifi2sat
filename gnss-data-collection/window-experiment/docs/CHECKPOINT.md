# Window-Experiment Checkpoint — 2026-07-23

A snapshot of everything done and known so far, and the launch point into the
classification analysis. Read alongside `THEORY.md` (the physics) and
`PROJECT_LOG.md` (the build/discovery history). Repo-wide reference lives in
[`../../knowledge-base/`](../../knowledge-base/).

---

## 0. Where is the data? (quick answer)

All of Sreehari's (and the team's) captures are on `main`, organized by strand.
Post-reorganization locations:

| Data | Location | What |
|---|---|---|
| **Geometry gesture sessions** | `window-experiment/data/samples/` | c1.1, c3.2 day1/2/3, ref_day1, repeat_day2 — **flat** dir; each `<session>_manifest.json` maps its files |
| **Archived / older window captures** | `window-experiment/data/archive/` | Jun-26 `ref_jun26*` family: `samples-not-rawx-but-good`=`ref_jun26` (48, MSM), `samples-not-07-14`=`ref_jun26_pm` (24, RAWX), `samples-old`=`ref_jun26_frag` (7, MSM) |
| **Breathing sessions** | `breathing/data/` | `rtcm/` + `json/` (s1.3.x Jul 9, s3.3 Jul 22); manifests alongside |
| **FineSat gesture captures** | `finesat/data/samples/` | Apr/May flat + `jn18L1/L2/L3` (Jun 18) |
| **FineSat archived micro-sets** | `finesat/data/archive/` | early Apr 28 / Apr 30-morning push captures |

The geometry data files are `.rtcm` (raw stream) + `.meta.json` (per-sat sidecar
with `los_enu`, elev/azim, `ref_sat`, `passed_health`). Scripts read them via the
manifests; **filenames encode gesture+window+timestamp, not session** — the
manifest is the file→session map.

---

## 1. What happened this session (repo consolidation)

The repo was scattered across four divergent branches. It is now unified:

1. **Merged all branches into `main`** — `casmp-updated` (c-series + breathing +
   day3) and the orphan `new-samples-jn1826` (jn18). All content preserved
   (verified by blob-hash). Branches still exist on origin (Sreehari commits to
   `casmp-updated`).
2. **Brought in day3** — `c3.2_day3` (W2/W3) + `s3.3` breathing; honored the
   upstream deletion of `s2.3_manifest.json` (data kept).
3. **Reorganized into strands** — `shared/ · finesat/ · window-experiment/ ·
   breathing/`, each self-contained; scripts made `__file__`-relative.
4. **Cleaned up** — deleted 50 duplicate xgboost samples + 3 redundant zip
   archives (~12 MB); nothing unique lost.
5. **Reorganized this strand** (window-experiment) by role: `docs/ lib/ capture/
   analysis/ data/ logs/ legacy/`. Flattened the redundant `phase1/` nesting;
   fixed all data-path and cross-module-import breakage; verified modules compile,
   import from any CWD, and `analysis/cno_test.py` runs end-to-end.
6. **Wrote the repo knowledge base** — `../../knowledge-base/`.

### This strand's layout now

```
window-experiment/
├── README.md            project index (reading order, status)
├── docs/                THEORY.md · THEORY.pdf · PROJECT_LOG.md · CHECKPOINT.md (this)
├── lib/                 geomlib.py · parse_rawx.py   (parsing/geometry primitives)
├── capture/             capture_sample · run_session · repeat_schedule ·
│                        field_monitor + targets/
├── analysis/            compute_windows_manifest · extract_signal_v2 · onset_align ·
│                        measure_alpha · common_mode_test · cno_test
├── data/                samples/ (flat, all sessions + manifests) · archive/
├── logs/                terminal-output captures
└── legacy/phase0/       vestigial early code
```

---

## 2. Data inventory & clean-sat yield (for analysis)

Observable format is **mixed** (do not pool): `c1.1_day1`, `c3.2_day1`,
`c3.2_day2` are **MSM7-only** (RTCM 1077 GPS + 1127 BeiDou, phase reconstructed
from DF fields); `ref_day1`, `repeat_day2`, `c3.2_day3` also carry **RAWX + SFRBX**
(clean carrier phase + lock-time + ephemeris — the cleaner source). 6 reps/gesture
= 30/full window (c-series); 3 reps = 12/window (ref/repeat). Yield = % of captures
with ≥3 clean satellites (from meta
`passed_health`, which used the old 50 m gate → a **floor**; `DF407` lock-time can
raise it).

| Session | Date (UTC) | Gestures | Windows: n (%≥3 clean) |
|---|---|---|---|
| `c1.1_day1` | Jun 29 16:40 | 5 | W0–W3: 30 each, **all 100%** |
| `c3.2_day1` | Jul 1 00:25 | 5 | W0:30(70%) W1:30(13%) W2:30(100%) W3:18(67%) |
| `c3.2_day2` | Jul 14 23:46 | 5 | W1:30(48%) W2:30(100%) W3:30(97%) |
| `c3.2_day3` | Jul 21 23:40 | 5 | W2:30(53%) W3:30(100%) |
| `ref_day1` | Jul 14 22:17 | push,star | W0–W3: 12 each, **all 100%** |
| `repeat_day2` | Jul 15 22:09 | push,star | W0–W3: 12 each, **all 100%** |

### The cross-day, same-geometry sets (the point of the experiment)

Sessions collected at the **sidereally-aligned** clock time reproduce the same
geometry at the same window index.

- **★ c3.2 W2 — 3 timepoints** (Jul 1 / 15 / 22), 30 samples each, all 5 gestures.
  day1 & day2 100% clean; day3 ~53%. Best multi-week same-geometry series.
- **★ ref_day1 ↔ repeat_day2 — full W0–W3 ramp on consecutive days** (Jul 14/15),
  push+star only, **100% yield throughout**. Cleanest cross-day pair, 2 gestures.
- c3.2 W3 — **3 timepoints** (day1 + day2 + day3) after the day2-W3 recovery
  (2026-07-23); day2 W3 is 97% clean. c3.2 W1 — starved (13%/48%), avoid.

### The within-day, different-geometry ramps (same hardware, geometry drifts)

- **c1.1_day1 W0→W1→W2→W3** — 15-min steps, 100% yield, 5 gestures. Flagship for
  "different geometry, same day."
- `ref_day1` and `repeat_day2` are each also a 4-window ramp (push+star).

---

## 3. The analysis this leads into

Full design in [`../../knowledge-base/03-coherence-experiment.md`](../../knowledge-base/03-coherence-experiment.md).
In brief — test that **geometry/window coherence matters** for classification:

- **2×2 design** decoupling geometry from time (same/diff geometry × same/diff day)
  so a cross-geometry accuracy drop is attributable to *geometry*, not day/hardware.
- **Fork (a):** start geometry-naive (per-sat single-differenced, detrended phase),
  then add the geometry-invariant trajectory `d(t)=pinv(G)·S` "fix" arm (required
  for cross-regime, where satellite sets are disjoint). g-vectors are free from the
  `los_enu` sidecars.
- **Fork (b):** report aggregate accuracy **and** the per-gesture breakdown,
  checking the κ prediction (push robust → star collapses).

**First experiments the data cleanly supports:**
1. c1.1_day1 within-day window ramp — accuracy vs sidereal separation.
2. c3.2 W2 3-timepoint + ref↔repeat cross-day pairs — does aligned geometry hold
   accuracy across weeks?

---

## 4. Constraints & traps (must honor in the pipeline)

- **Mixed observable** — MSM sessions: reconstruct phase from DF397/398 + DF405/406;
  RAWX sessions (`ref_day1`, `repeat_day2`, `c3.2_day3`): use `cpMes·λ` directly. Gate
  slips on **`DF407`/`locktime`**, not the buggy 50 m distance gate.
- **Gesture is NOT guaranteed in the nominal 3–6 s slice** — detect onset
  (`analysis/onset_align.py`), don't hardcode a window.
- **`ref_sat` varies across captures** — re-single-difference to a common reference.
- **Satellite correspondence**: cross-regime the visible PRNs differ → per-sat
  feature vectors can't align → that's why the trajectory arm is needed there.
- **Label typo**: normalized 2026-07-23 — all manifests now use `triangle`
  consistently; 96 duplicate `traingle_*` files removed. No longer a live trap.
- **Small N** (~6 reps/gesture/window) — simple classifiers, repeated stratified CV,
  permutation tests, chance = 20%.
- **Known model caveat** (`geomlib.py` header, `THEORY.md`): on current free-hand
  data the single-differenced envelope is nearly flat (reproducibility floor α≈0);
  the inversion is verified correct on synthetic ground truth, but κ/dt_max from
  real data are not yet trustworthy until α is raised (mechanical reproduction) or
  the common-mode question is resolved. **This is the open scientific risk.**

---

## 5. Status line

Data merged, reorganized, cleaned, pushed. Structure verified runnable. **Data-quality
issues (#7–#10) reconciled 2026-07-23** — labels normalized, c3.2_day2 W3 recovered,
split pairs repaired, `ref_jun26` disambiguated; audit shows 0 dangling manifest refs.
Ready to build the classification pipeline (Exp 1: c1.1 within-day ramp) as the next step.
