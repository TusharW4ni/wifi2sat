# GNSS Carrier-Phase Gesture Pipeline — Project Log

A working record of everything built and discovered so far: the hardware configuration, the observable, the signal-processing pipeline, the field tooling, the data collected, and — most importantly — the chain of debugging findings that took clean-satellite yield from a useless median of 2 to a healthy 6 (recovered MSM) and 20 (RAWX).

**Companion document:** `THEORY.md` (the decorrelation derivation and the window result this pipeline is built to measure).

---

## 0. Goal and physical setup

Recognize hand gestures from the **carrier-phase** perturbations they induce on GNSS signals. A u-blox EVK-F9P drives a fixed antenna on a tripod; a hand moves in front of the antenna as a **multipath reflector** (the antenna does not move — same physical family as WiFi-CSI / Widar3.0 gesture sensing). The immediate scientific target is the **geometry-decorrelation window**: how long the satellite geometry stays consistent enough for a gesture's signal to remain reproducible (see `THEORY.md`).

Environment: M1 Mac, Python via `uv`, receiver on USB CDC (`/dev/cu.usbmodem*`).

---

## 1. Receiver configuration — `04-messages.py`

We output four message streams at 10 Hz over USB:

| message                                | purpose                                                                                                     |
| -------------------------------------- | ----------------------------------------------------------------------------------------------------------- |
| **UBX-RXM-RAWX**                       | primary observable — raw carrier phase `cpMes` (cycles), continuous, with `locktime` + `trkStat` slip flags |
| **UBX-RXM-SFRBX**                      | broadcast ephemeris — for precise satellite positions / LOS (NAV-SAT az/el is only 1° resolution)           |
| **UBX-NAV-SAT** (1 Hz)                 | quick az/el for the elevation mask                                                                          |
| **RTCM 1077 / 1127** (GPS/BeiDou MSM7) | retained: carries `DF407` lock-time, and lets RAWX cross-validate/recover the MSM-only data                 |

```python
# enable RAWX (primary carrier phase), 10 Hz
ser.write(UBXMessage("CFG","CFG-MSG",msgmode=SET, msgClass=0x02,msgID=0x15, rateUSB=1).serialize())
# enable SFRBX (ephemeris)
ser.write(UBXMessage("CFG","CFG-MSG",msgmode=SET, msgClass=0x02,msgID=0x13, rateUSB=1).serialize())
# keep NAV-SAT @1Hz, and RTCM 1077/1127 MSM7
```

**Baud note.** On USB CDC the `115200` setting is nominal — USB runs at native speed, so 10 Hz RAWX+MSM (~12 KB/s) is fine without any baud change. Only if the receiver were moved to the UART1 pins would 115200 overflow (~10 KB/s usable); raise to ≥230400 there.

---

## 2. The observable: why RAWX, and the MSM trap

### 2.1 What went wrong with MSM reconstruction

The first pipeline rebuilt carrier phase from RTCM MSM7 fields as `(DF398 + DF406) × c/1000` — rough range (293 m LSB) plus fine phase. This injected **periodic false cycle slips**. Tracing one satellite across epochs showed the mechanism: at a rough-range LSB boundary, `DF398` drops by exactly one LSB (~~293 m) while `DF406` wraps the other way (~~+236 m); combined correctly they nearly cancel, but the naïve sum leaves a ~−57 m step where the true motion is ~−28 m. That ~30–57 m step trips a 50 m slip gate. Because the receiver steers its clock at ~1 Hz (a common-mode jump on all satellites), these false steps recur periodically and on many satellites at once.

**Consequence:** the 50 m slip gate rejected good satellites, starving clean-sat yield to a **median of 2** — too few for the geometry framework (needs ≥3 non-coplanar).

### 2.2 The fix: RAWX `cpMes`

`UBX-RXM-RAWX` reports the accumulated carrier phase `cpMes` in **cycles**, continuous within a lock, with an explicit cycle-slip indicator. `cpMes × wavelength → meters` drops straight into the pipeline (the large integer-cycle ambiguity is constant while locked, so it cancels under differencing/detrend). No rough/fine recombination, no rollover rule.

### 2.3 `parse_rawx.py` — RAWX → continuous phase

```python
WAVELENGTH = { (0,0):C/1575.42e6,                 # GPS L1 C/A
               (2,0):C/1575.42e6, (2,4):C/1176.45e6,   # Galileo E1, E5a
               (3,0):C/1561.098e6, (3,7):C/1176.45e6 } # BeiDou B1I, B2a
# cpMes (cycles) * WAVELENGTH -> meters; slip = locktime reset OR cpValid clear
```

Validated by byte-level round-trip (synthetic RXM-RAWX frame → parse → correct meters, slip caught), then on **real captures**.

> **Field-mapping lesson (real data).** This receiver tracks **BeiDou as B1I (sigId 0) + B2a (sigId 7)**, _not_ B2I (sigId 2). RAWX also exposes **Galileo** (gnssId 2) and **GLONASS** (gnssId 6) — constellations MSM never carried. The initial accept-list dropped all BeiDou; widening it (and adding Galileo) is most of the yield jump. GLONASS is FDMA and needs a freqId-dependent wavelength (still to add).

---

## 3. Signal extraction — `extract_signal_v2.py`

The gesture signal is recovered exactly as the theory prescribes:

1. **Single-difference** each satellite against a reference → removes the receiver clock.
2. **Low-order detrend** (deg-2) over the window → removes the smooth geometric range trend.
3. **Elevation mask** ≥ 20° → drop refraction-heavy low satellites.
4. **Data-driven gesture-window detection** via the common-mode RMS envelope (gestures land at variable times ~5–8.5 s, not a hardcoded 3–6 s).

The differential geometry vector per satellite is $\mathbf{g}_i = \hat{\mathbf{e}}_i - \hat{\mathbf{e}}_{\text{ref}}$, taken from the meta sidecar or recovered from NAV-SAT.

**Validation that the observable is sound:** single-differenced + detrended **MSM matches RAWX to 0.05 mm RMS, correlation 1.0000** on paired evening data. The gesture signal was never corrupted by the MSM bug — only the slip _gate_ was.

---

## 4. Clean-satellite selection — the core saga

This is where most of the debugging effort went. The progression:

**(a) 50 m raw-phase gate — broken.** Fires on clock-steering common-mode and the MSM rough/fine boundary steps. Neither is a real slip; both cancel under single-difference. Yield: median 2.

**(b) Common-mode removal attempts — fragile.** Subtracting the per-epoch median of (2nd-differenced or detrended) phase to estimate the clock did not work reliably: with few mixed-constellation satellites the median is a poor clock estimate and absorbs the gesture itself. Recall vs truth ~25 %.

**(c) Smoothness threshold on single-differences — wrong criterion.** `max|Δ(SD)| ≤ thr` rejects satellites for _having signal_ (the gesture and noise), not for slipping. Also broke on index-based alignment when satellites drop in/out (index 50 of one sat ≠ index 50 of another) — must be **epoch-keyed**.

**(d) Lock-time — correct.** The receiver already tells us when it lost carrier lock:

- **RAWX:** `locktime` resets (and the `cpValid` bit). A decrease ⇒ cycle slip.
- **MSM7:** the same information is in **`DF407`** (phase lock-time indicator), present in the data all along.

```python
# clean satellite = full-length AND lock-time never decreases
ts = sorted(lock[sat])                              # epoch-keyed!
slip = any(lock[sat][ts[i]] < lock[sat][ts[i-1]] for i in range(1,len(ts)))
clean = (len(ts) >= 100) and not slip
```

Plus two refinements that matter on real data:

- **Longest slip-free segment** instead of all-or-nothing: a single early re-lock (e.g. at 0.9 s) shouldn't discard 110 good epochs.
- **One signal per satellite** (best CNO) so multi-signal tracking doesn't inflate counts — geometric diversity comes from distinct _satellites_, not distinct signals.

### 4.1 Result — yield by method

|                                                   | median clean sats | captures ≥3 | captures ≥8 |
| ------------------------------------------------- | ----------------- | ----------- | ----------- |
| 50 m gate (MSM)                                   | 2                 | 24/48       | 1/24        |
| **`DF407` lock-time (MSM, morning)**              | **6**             | 48/48       | 4/48        |
| **RAWX lock-time, multi-constellation (evening)** | **20**            | 24/24       | 24/24       |

`DF407` clean was **validated against RAWX truth at 86 % recall, 3 false positives** on paired evening captures — so the morning MSM-only session is genuinely recovered.

---

## 5. Field tooling

| script                 | role                                                                                                                                                             |
| ---------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `capture_sample.py`    | one capture: records the stream, writes a `.meta.json` sidecar (UTC instant, ref sat, per-sat LOS/elev), gates on message counts + clean sats, UTC filenames     |
| `run_session.py`       | timed multi-window driver: `--windows/--spacing` for reference collection, `--targets` for repeat days; incremental manifest; 3-2-1 countdown as the gesture cue |
| `repeat_schedule.py`   | sidereal repeat-time calculator + Phase-3 offset-sweep generator (ε = 0, ±3, ±5, ±8, ±12, ±20 min); `--mode gps                                                  | gps+bds`; emits `targets.json` |
| `field_monitor.py`     | live TUI capture-health dashboard                                                                                                                                |
| `parse_rawx.py`        | RAWX → continuous phase + slip flags (§2.3)                                                                                                                      |
| `extract_signal_v2.py` | single-diff + detrend + window detection (§3)                                                                                                                    |
| `onset_align.py`       | onset aligner (§9): per-capture gesture-onset estimate via iterative template alignment on the across-satellite motion envelope; removes ~1–1.5 s free-hand timing jitter |
| `measure_alpha.py`     | reproduce the §9 α table (zero-lag / within-session / across-day, null-calibrated) from a reference session + its sidereal repeat                                             |
| `common_mode_test.py`  | §10.1: SD vs common-mode vs clock-separated phase reproducibility (shows the gesture is common-mode but clock-confounded)                                                     |
| `cno_test.py`          | §10.2: CN0 (per-sat + common-mode) reproducibility — the clock-free observable that reproduces ~4× the phase pipeline                                                         |

### 5.1 `field_monitor.py` (RAWX edition)

Live dashboard rebuilt around RAWX. Gates on **RXM-RAWX** epochs (≥100), **NAV-SAT** (≥5), and **clean sats** (≥2) from `cpMes`-continuity + `locktime`; shows **MSM 1077/1127** as a secondary "flowing/check" line (kept for recovery). Per-satellite table (PRN, signal, elevation, CNO, epochs, slip, clean/usable), an epoch-aligned common-mode **motion RMS** (mm) sanity check, and a 5-tick hysteresis verdict (`WOULD PASS / PASS-THIN / UNSTABLE / WOULD FAIL`). Validated end-to-end on a synthetic RAWX+NAV-SAT stream (including an injected mid-window slip, correctly flagged).

### 5.2 Repeat geometry (`repeat_schedule.py`)

Implements the sidereal recurrence from `THEORY.md §7`: GPS at 1 sidereal day, GPS+BeiDou at 7. _Known issue:_ it currently emits per-rep targets (≈528), but Phase 3 needs **one target per window** swept over the offset set — to be trimmed before the repeat day.

---

## 6. Data collected

| session                  | when (UTC)   | captures               | observable         | windows                      | clean (median)            |
| ------------------------ | ------------ | ---------------------- | ------------------ | ---------------------------- | ------------------------- |
| **morning** `ref_day1`   | ~15:00–15:55 | 48 (push,star × 6 × 4) | MSM7 only          | W0–W3 (4)                    | 6 (recovered via `DF407`) |
| **evening** `ref_day1.1` | ~21:16–21:34 | 24 (push,star × 6 × 2) | RAWX+SFRBX+MSM+NAV | W0–W1 (2, interrupted at W2) | 20 (RAWX)                 |

Both are now usable. Morning gives the full 4-window spread the experiment was designed around (GPS+BeiDou, ceiling ~8–10 clean); evening is richer per capture (GPS+Gal+BDS+GLONASS) but only 2 windows. They cross-validate.

**Collection design (from `THEORY.md`):** 4 windows × 15-min spacing × 2 gestures × 6 reps. 15 min is the _spacing between_ windows (chosen so the ±5–8 min usable windows don't overlap on the repeat day), not the duration; geometry drift _within_ a collection block is negligible (~0.2 % decorrelation).

---

## 7. Key empirical findings

1. **The observable was always fine.** SD+detrend MSM = RAWX to 0.05 mm. The MSM "corruption" was entirely a slip-_gate_ artifact (clock steering + rough/fine boundary steps, both common-mode).
2. **Clean-sat starvation was a detection bug, not a data problem.** Switching the slip criterion to lock-time (`DF407` for MSM, `locktime` for RAWX) took the median from 2 → 6 (MSM) and → 20 (RAWX multi-constellation).
3. **Reproducibility floor** — ~~provisional $\alpha \approx 0.6$~~ **superseded by §9** (2026-07-15): the honest, onset-aligned, null-calibrated floor is $\alpha \approx 0.17$ (push) / $\approx 0.05$ (star) at matched geometry. Still well below the ~0.85 ceiling, so the conclusion holds — the _geometric_ window needs mechanically reproduced gestures to isolate κ (see `THEORY.md §6`).
4. **Geometry rate** $\omega_{\text{LOS}} \approx 0.45^{\circ}/$min, tightly clustered across elevations.
5. **Receiver specifics:** BeiDou = B1I/B2a; Galileo + GLONASS available via RAWX; receiver steers its clock at ~1 Hz; NAV-SAT az/el is only 1° resolution (motivating SFRBX).

---

## 8. Current status and next steps

**Done:** Phase 0 pipeline (capture, extract, monitor); Phase 1 reference collection (both sessions); sidereal scheduler; RAWX config + parser; monitor RAWX rebuild; clean-sat starvation diagnosed and fixed for both observables; morning MSM-only data recovered and validated against RAWX truth.

**Next, in order:**

1. **Run the geometry analysis** on both sessions — compute the empirical $M$, the curvature $\kappa$, the floor $\alpha$ with real statistics, and the predicted $\delta t_{\max}$ for push vs star (`THEORY.md §3–5`). This is the result the pipeline was built for, now unblocked by the clean-sat fix.
2. **Fold both slip detectors into durable code** — `DF407` lock-time in the MSM/extractor path, RAWX `locktime` in the RAWX path — and remove the 50 m heuristic everywhere. Add the longest-slip-free-segment and one-signal-per-satellite logic to `parse_rawx.py`; add GLONASS via freqId wavelength.
3. **Decode SFRBX ephemeris** for sub-degree LOS (NAV-SAT's 1° az/el is coarse for the few-degree Δθ the window experiment measures).
4. **Phase 3 — repeat-offset sweep** (`THEORY.md §7`) to _measure_ $r(\Delta\theta)$ directly and compare to the predicted $1-\tfrac12\kappa\Delta\theta^2$. Trim `repeat_schedule.py` to one target per window first.
5. **Mechanical reproduction** to push $\alpha$ toward the noise ceiling and isolate the geometric κ from free-hand irreproducibility.

---

## 9. GPS sidereal repeat + onset alignment (2026-07-15)

Collected a fresh full 4-window RAWX reference on **07/14** (`samples/ref_day1`, push,star × 6 × 4; median **24** clean sats, **8** GPS) and its **GPS 1-sidereal-day repeat on 07/15** (`samples/repeat_day2`, same design; 48/48 captures, RAWX in every file). Matched pairs are the Phase-3 $\varepsilon=0$ point — same sky, one day later.

**9.1 Geometry repeat — confirmed.** For every window the two days saw the _identical_ set of GPS PRNs; differential LOS agreed to **≤ 1°** (= NAV-SAT's 1° az/el quantization; W3 = 0°); matched captures are separated by **86164.1 s = one sidereal day to ~0.05 s**. The GPS-only next-day formula $T - 3\text{m }56\text{s}$ (one sidereal day) is validated. `targets_repeat_0715.json` holds the four repeat instants.

**9.2 The α≈0 "flat envelope" was largely a timing artifact.** Free-hand, the gesture onset lands at a different instant in each 12 s recording — measured jitter **~1–1.5 s** (per-rep envelope peaks spread 1.5 s). Sample-for-sample ("zero-lag") correlation then lines a rep's gesture up against another rep's baseline → ≈ 0. `onset_align.py` recovers the per-capture onset by iterative template alignment ("Woody averaging") on the across-satellite motion envelope $E(t)=\sqrt{\langle s_i(t)^2\rangle_i}$ (the hand moves once → a single onset shared by all satellites).

**9.3 Honest α** (onset-aligned, _independent_ templates so no per-pair peeking; null = different gestures, matched geometry, same statistic):

| pair set (Δθ≈0), GPS only | push | star | null |
| --- | --- | --- | --- |
| zero-lag (naive) | 0.12 | 0.02 | — |
| onset-aligned, within-session (honest, split templates) | **0.24** | 0.04 | — |
| onset-aligned, across-day (sidereal repeat, honest) | **0.17** | 0.07 | **−0.07** |

(Reproduce: `uv run measure_alpha.py`.)

- **push carries a genuine reproducible component** (+0.24 above null); **star barely** (+0.13) — consistent with `THEORY.md §4` (single-axis reproduces; multi-axis doesn't).
- **across-day keeps most of the within-session correlation** (push 0.17 vs 0.24; null −0.07 — ~70% retained) → the full-sidereal-day matched-geometry repeat preserves the reproducible signal. **The repeat is validated at the signal level**, not just LOS.
- **Caveat / correction:** onset alignment is a real fix (~1 s jitter; roughly doubles within-session correlation) but does **not** rescue free-hand reproducibility to κ-measurable levels — honest α stays far below ~0.85, star near noise. **Mechanical reproduction still required.** A mid-analysis _per-pair best-lag_ figure (push α≈0.39) was inflated by lag-fishing against a 0.14 null; the honest independent-template value is ~0.17. The _effect size above null_ is stable across methods (push ≈ +0.24, star ≈ +0.13).

**9.4 Fold-in TODO.** `onset_align.py` is a standalone module; wire it into `extract_signal_v2` (align each capture to onset=0 against a stored per-gesture template before $M$/feature extraction) so every downstream statistic — and any future classifier — sees time-aligned gestures.

*(Bug fixed this session: `align_group`'s per-iteration median re-centring could push a lag outside the ±MAXLAG search band, so `_seg` sliced out of bounds and produced a ragged template. Clamped after centring. The §9.3 α numbers are unchanged — a length guard had masked it — but `common_mode_test.py`'s CM alignment tripped it.)*

---

## 10. Where does the hand's signal live? Common-mode vs CN0 (2026-07-15/16)

The §9 result — honest free-hand α ≈ 0.17 (push) — begged the question the README flagged: is the low α *physics* (weak/irreproducible signal) or *processing* (we're discarding the signal)? Two tests, both on existing data, both GPS-only, onset-aligned, null-calibrated (`common_mode_test.py`, `cno_test.py`).

**10.1 Common-mode phase test — the gesture is being discarded, but it's clock-confounded.** Reproducibility of three phase observables within a window:

| phase observable | push α | star α | null |
| --- | --- | --- | --- |
| SD (current: $\phi_i-\phi_{\text{ref}}$, detrended) | 0.12 | 0.04 | −0.04 |
| CM (across-sat mean) | **0.52** | **0.63** | 0.20 |
| CMR (clock-separated recovery $[E\,|\,\mathbf 1]$) | 0.07 | −0.00 | −0.01 |

- **88%** of the per-satellite (detrended) phase signal is common across satellites. Single-differencing discards it.
- The common-mode phase (CM) reproduces **~5× better than SD** and is gesture-specific (push 0.52 vs 0.20 null → +0.32 excess). Clock can't explain it (clock isn't reproducible across independent reps). **So the gesture signal isn't absent — SD averages it away.**
- **But it's unrecoverable with one antenna.** A hand that perturbs every satellite equally has the *same signature as the receiver clock* — both common-mode. The clock-augmented regression (CMR) confirms it: it dumps the common-mode gesture into the clock term and does *worse* than SD (0.07). The ill-conditioning is physical — all satellites are above the horizon, so the "up"/common direction ≈ the clock column. **Removing the clock removes the gesture.** No single-antenna software fix.

**10.2 CN0 test — a clock-free observable that works.** Signal strength (carrier-to-noise, dB-Hz) has *no clock term*, so the common-mode survives:

| CN0 observable | push α | star α | null |
| --- | --- | --- | --- |
| CN0 per-satellite | 0.18 | 0.10 | 0.00 |
| **CN0 common-mode** (across-sat mean) | **0.44** | **0.30** | **−0.09** |

- **CN0 common-mode reproduces at 0.44 (push) / 0.30 (star), ~4× the phase-SD pipeline, with a clean null (−0.09)** — the reproducibility is genuinely gesture-specific, not a systematic. Typical gesture-time swing ~2.4 dB-Hz; averaging over ~8 GPS sats beats down the ~1 dB CN0 quantization.
- The hand's effect is dominantly **broadband / common-mode** (per-sat CN0 only 0.18; common-mode 0.44) — consistent with a near-field antenna power perturbation, not directional multipath. Same picture as the phase common-mode.

**10.3 Coherent story + recommendation.** The hand's dominant effect on a single fixed GNSS antenna is a **common-mode (broadband) perturbation** of both phase and power. In *phase* it is confounded with the receiver clock, so single-differencing kills it → the low SD α. In *CN0* there is no clock, so it survives → **CN0 common-mode is the best observable found, and it is software-only on existing hardware.** Still free-hand-limited (0.44 < ~0.85 ceiling), but ~4× the phase pipeline and a clean null.

**Next:** (a) build CN0 (per-sat + common-mode) features into the dataset/classifier path — this is the free SNR upgrade; (b) if phase common-mode is ever wanted, it needs a **reference antenna** (dual-antenna common-clock → between-antenna difference removes the clock while keeping the hand signal) — hardware, but not a mechanical rig.
