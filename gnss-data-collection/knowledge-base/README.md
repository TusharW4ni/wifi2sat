# Knowledge Base

Consolidated knowledge about this project — the GNSS carrier-phase human-sensing
work. This is the "everything we know" reference: what the signal is, what data
exists, what the experiments are, and where the traps are. It complements (does
not replace) the per-strand docs and the window-experiment's `THEORY.md` /
`PROJECT_LOG.md`.

> **Status:** current as of 2026-07-22. All branches merged, repo reorganized into
> strands, and pushed to `origin/main`.

## Contents

| Doc | What's in it |
|---|---|
| [01-signal-model.md](01-signal-model.md) | Hardware, MSM7 observables, DF fields, carrier-phase reconstruction, single-differencing, the geometry / κ decorrelation theory |
| [02-data-inventory.md](02-data-inventory.md) | Every dataset: the c-series geometry sessions, clean-sat yield map, breathing, FineSat, archives |
| [03-coherence-experiment.md](03-coherence-experiment.md) | The planned window/geometry-coherence classification experiment: design, forks, feasibility on current data |
| [04-data-quality.md](04-data-quality.md) | Known constraints and traps: MSM-only, gesture-window timing, ref-sat drift, label typos, salvage findings |
| [05-glossary.md](05-glossary.md) | Terms: sky regime, window, geometry, MSM7, single-difference, κ, etc. |

## The one-paragraph version

A fixed u-blox EVK-F9P antenna records high-rate (10 Hz) GNSS carrier phase from
GPS + BeiDou. A hand moving near the antenna acts as a moving multipath reflector,
perturbing the carrier phase on each satellite in proportion to the hand motion
projected onto that satellite's line-of-sight. Single-differencing against a
reference satellite removes the receiver clock; detrending removes the geometric
range trend; what's left is the gesture signal. Because satellite geometry drifts
continuously (and repeats each sidereal day), **the same gesture produces a
reproducible signal only within a limited time window** — the central research
question. Three strands of work explore this: **finesat** (gesture
classification), **window-experiment** (geometry-coherence theory + data), and
**breathing** (breathing detection).

## Repo strands (see top-level [README](../README.md))

- `shared/` — receiver setup, shared docs
- `finesat/` — original gesture pipeline (capture → dataset → classify)
- `window-experiment/` — geometry/window coherence theory + c-series data
- `breathing/` — breathing detection
