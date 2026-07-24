# CLAUDE.md — orientation for this repo

GNSS carrier-phase human sensing: a fixed u-blox EVK-F9P antenna records high-rate
carrier phase; a hand moving nearby perturbs it (multipath), and we try to
recognize gestures from those perturbations. The immediate scientific target is
the **geometry-decorrelation window** — how long a gesture stays reproducible as
satellite geometry drifts. Based on the FineSat paper.

Everything lives under `gnss-data-collection/`.

## Read these first (in order)

1. **`gnss-data-collection/knowledge-base/`** — the "everything we know" reference
   (start at its `README.md`): signal model & theory, data inventory, the coherence
   experiment, data-quality traps, glossary.
2. **`gnss-data-collection/window-experiment/docs/ANALYSIS_PLAN.md`** — the staged,
   signal-first analysis plan. **The GitHub issues track this plan.**
3. **`gnss-data-collection/window-experiment/docs/CHECKPOINT.md`** — current state
   and exact data locations.
4. `window-experiment/docs/THEORY.md` (physics/math) and `PROJECT_LOG.md` (build
   history) for depth.

## Repo layout (strands)

```
gnss-data-collection/
├── knowledge-base/     consolidated reference docs
├── shared/             receiver setup + shared docs
├── finesat/            original gesture pipeline (capture → dataset → classify)
├── window-experiment/  geometry/window-coherence work — the active analysis
│   ├── docs/           THEORY, PROJECT_LOG, CHECKPOINT, ANALYSIS_PLAN
│   ├── lib/            geomlib.py, parse_rawx.py   (parsing/geometry primitives)
│   ├── capture/        on-receiver collection scripts
│   ├── analysis/       offline analysis (measure_alpha, common_mode_test, cno_test,
│   │                   onset_align, extract_signal_v2, compute_windows_manifest)
│   ├── data/samples/   all gesture sessions (flat) + per-session manifests
│   └── data/archive/   older/variant captures
└── breathing/          breathing-detection strand (not part of the current analysis)
```

## How to run

The Python project (with `uv`) is rooted at `gnss-data-collection/`
(`pyproject.toml` + `uv.lock`; deps include numpy/scipy/scikit-learn/xgboost/pyubx2).

```bash
cd gnss-data-collection
uv sync                                              # once — builds .venv from the lock
uv run window-experiment/analysis/measure_alpha.py   # run any analysis script
```

`uv run` also works from inside `window-experiment/` (e.g.
`uv run analysis/cno_test.py`) — it finds the project root automatically. Analysis
scripts resolve their data/import paths relative to their own location, so they run
from any working directory.

**Unified data access — use this instead of globbing files.** `window-experiment/lib/dataset.py`
is the one catalog + loader for *all* gesture data (window-experiment + finesat),
normalizing the three on-disk naming schemes behind one API:

```bash
uv run window-experiment/lib/dataset.py            # print the catalog (all sessions)
```
```python
import dataset as ds                    # from window-experiment/lib on sys.path
ds.catalog()                            # every session: observable, campaign, windows, …
ds.load_session("c3.2_day2")            # uniform per-capture records
ds.load(observable="RAWX")              # filtered; RAISES if a selection mixes MSM7+RAWX
ds.parse(cap, with_geometry=True)       # phases (+los/elev) via geomlib dispatch
```
Observable (MSM7/RAWX) is **detected from the data** (RXM-RAWX presence), not the
name/date. The loader enforces the no-silent-pool rule. Breathing data is a
separate task and is intentionally not in this catalog.

## Critical facts (don't relearn these the hard way)

- **Observable format is mixed** — never silently pool:
  - **MSM7-only** (phase reconstructed from `DF397+398+406`): `c1.1_day1`,
    `c3.2_day1`, `c3.2_day2`.
  - **RAWX + SFRBX** (clean `cpMes·λ` phase + lock-time + ephemeris — cleaner):
    `ref_day1`, `repeat_day2`, `c3.2_day3`.
- **Cycle slips:** gate on `DF407`/`locktime`, **not** the old 50 m distance gate
  (which produced false slips and starved clean-sat yield).
- **The gesture is NOT guaranteed in the nominal 3–6 s slice** — detect onset
  (`analysis/onset_align.py`); don't hardcode a window.
- **`ref_sat` varies across captures** — re-single-difference to a common reference.
- **Signal is marginal.** Free-hand phase reproduces weakly and only for push
  (α≈0.17–0.24; star≈noise); CN0 (amplitude) is the most reproducible channel; ~88%
  of energy is common-mode (clock/environment, not gesture). See ANALYSIS_PLAN §0.
- **Label typo — now normalized (2026-07-23):** all manifests use `triangle`
  consistently; the 96 duplicate `traingle_*` files were deleted. No shim needed.
  (Only excluded retry captures still carry the typo internally.)

## Workflow

- The work is tracked as **GitHub issues** (`gh issue list`), organized by the
  `analysis`, `data-quality`, and `phase-gate` labels. Each analysis issue maps to a
  phase in `ANALYSIS_PLAN.md` and notes its dependencies.
- Commit messages end with the project's Co-Authored-By trailer; branch off `main`
  for non-trivial work.
- **Keep docs accurate:** if you discover something written here or in the docs is
  stale/wrong, fix it (and sweep for the same error elsewhere) as part of your change.
