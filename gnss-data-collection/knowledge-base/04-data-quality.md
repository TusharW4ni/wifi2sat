# Data Quality, Constraints & Known Issues

The traps. Read before analyzing.

## Observable & reconstruction

- **Observable format is mixed across sessions** (do not silently pool):
  - **MSM7-only** (RTCM 1077 GPS + 1127 BeiDou, phase reconstructed from DF fields):
    `c1.1_day1`, `c3.2_day1`, `c3.2_day2`.
  - **RAWX + SFRBX** (clean `cpMes·λ` carrier phase + lock-time + ephemeris):
    `ref_day1`, `repeat_day2`, `c3.2_day3`.
  The RAWX sessions are the cleaner carrier-phase source; the MSM sessions need
  reconstruction and are the ones the slip-reconstruction caveats below apply to.
- **Naïve phase reconstruction injects false slips.** `(DF398 + DF406) × c/1000`
  steps at rough-range LSB boundaries trip the 50 m slip gate. The MSM phase
  *observable* is sound (0.05 mm RMS vs RAWX); the reconstruction + gate were the bug.
- **Use `DF407` lock-time for slips**, not a 50 m distance gate. The meta
  `passed_health` flags used the old gate and likely **undercount** clean sats.

## Timing & alignment

- **Gesture is NOT guaranteed in the nominal 3–6 s window.** Despite the capture
  prompt, the operator may act early/late. Detect onset; don't hardcode a slice.
  (`window-experiment/analysis/onset_align.py`.)
- **`ref_sat` varies across captures within a session** (e.g. c1.1 uses both
  `BDS_042` and `GPS_029` as reference). Single-differenced signals are therefore not
  directly comparable as stored — re-single-difference to a common reference.
- **Satellite sets differ across geometries.** Within a regime (15-min windows) they
  mostly overlap; across regimes (c1.1 vs c3.2) they're nearly disjoint, so
  per-satellite feature vectors can't be aligned across regimes.

## Labels & manifests

The four data-quality issues below were **reconciled on 2026-07-23** (see the cleanup
log at the bottom); the notes record both the historical trap and the resolution.

- **`traingle` vs `triangle`** typo — **resolved.** All six manifests now use
  `triangle` consistently (top-level `gestures` array, per-entry `gesture` field,
  the `rtcm`/`meta` filenames, and the internal `label`/`rtcm_file` of every
  referenced meta). The 96 leftover byte-identical `traingle_*` duplicate files were
  deleted. No loader shim is needed. *(Only unreferenced retry captures — see below —
  still carry the typo internally; they are excluded from all manifests.)*
- **`c3.2_day2` manifest `session` field** — **resolved.** Was `"s3.2_day2"`; fixed to
  `"c3.2_day2"` in commit `f235108` (2026-07-22).
- **On-disk data exceeded the manifests** — **reconciled.** Every manifest now
  references only files that exist (0 dangling refs) and the notable orphans were
  resolved: a complete **`c3.2_day2` W3** set (5 gestures × 6 reps, Jul-15 00:16–00:26,
  97 % ≥3-clean) was recovered into the manifest, and two `push→pushpull` split pairs
  (botched partial renames at `004423Z` / `234852Z`) were rejoined. Remaining
  unreferenced files (~34) are **irregular retry/warm-up takes** in `c3.2_day1` W0
  (no full gesture set — e.g. 0 `star` reps) plus one stray `c1.1_day1` W0 push rep;
  deliberately left out of the canonical set.
- **`s2.3_manifest.json` was deleted upstream** (day3 commit). The s2.3 breathing
  data files remain; only the manifest was removed. Honored in the merge.
- **June-26 `ref_day1` "duplicate"** — **not a duplicate.** The `ref_day1` in
  `data/samples/` (created 2026-07-14, **RAWX**) and the one archived under
  `data/archive/samples-not-rawx-but-good/` (created 2026-06-26, **MSM**) are
  *distinct sessions* with zero byte overlap that merely shared a name. The archive
  session was renamed to **`ref_jun26`** (manifest field + filename) to disambiguate.

## Salvage findings (archived micro-dirs) {#salvage}

Assessed the ad-hoc micro-collections against current knowledge:

| Dir | Verdict |
|---|---|
| `finesat/data/archive/samples-50-xgboost` | **Deleted** — 100% byte-duplicates of the Apr 30 evening set |
| `finesat/data/archive/samples-old` (2) | Kept — Apr 28 push, unique, clean (~13 sats) |
| `finesat/data/archive/samples-good-4-30-morning` (3) | Kept — Apr 30 AM push, unique, clean |
| `finesat/data/archive/samples-wo_sec` (5) | Kept — Apr 30 AM push, unique, clean |
| `window-experiment/data/archive/samples-not-rawx-but-good` (48) | Kept — **complete Jun 26 4-window push+star session** (session `ref_jun26`), MSM, good yield; usable as an extra window ramp |
| `window-experiment/data/archive/samples-old` (7) | Kept — fragmentary earlier Jun 26 W0 push+star; low value |

The 10 unique finesat push captures (Apr 28 + Apr 30 AM) are clean but push-only
with no sidereal-aligned repeats → useful only as extra push-class *training*
diversity, not for the coherence experiment.

## Cleanup already done (2026-07-22)

- Deleted `samples-50-xgboost` (50 dupes) and 3 redundant zip archives
  (`breathing_samples_s1.3.zip`, `ref_day1.zip`, `ref_day1.1.zip`) whose every file
  exists as loose committed data (~12 MB freed).
- Merged all branches into `main`, reorganized into strands, pushed.

## Data-quality reconciliation (2026-07-23)

Cleared the four `data-quality` issues (GH #7–#10):

- **Labels normalized** — completed the `traingle→triangle` fix left half-done in the
  manifests; deleted 96 byte-identical `traingle_*` duplicate files.
- **`c3.2_day2` W3 recovered** — a clean 30-capture window sitting unreferenced on
  disk was added to the manifest (day2 now W1/W2/**W3**); `compute_windows_manifest`
  now computes its drift over W1→W3.
- **Split pairs rejoined** — two `push→pushpull` half-renames repaired, eliminating
  the last 2 dangling manifest references (audit: 0 missing).
- **`ref_day1` name collision resolved** — archive session renamed `ref_jun26`.
- Remaining ~34 unreferenced files are irregular `c3.2_day1` W0 retries + 1 stray
  `c1.1_day1` push, intentionally excluded.

Audit end-state: 6 manifests, 948 referenced files, **0 referenced-but-missing**,
0 files referenced by >1 session.
