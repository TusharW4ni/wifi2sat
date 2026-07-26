#!/usr/bin/env python3
"""
alpha_study.py -- Phase 1 (issue #3): the reproducibility-floor (alpha) study.
THE GATE. Downstream phases proceed per-channel only where alpha's CI clears null.

Generalizes measure_alpha / common_mode_test / cno_test (each RAWX/GPS-only,
push+star) into ONE bootstrapped study over sessions × observables × channels ×
all 5 gestures, each vs a matched null, with confidence intervals.

alpha = onset-aligned correlation between two reps of the SAME gesture at matched
geometry. Reported two honest ways (no shared-template inflation):
  within   -- split a session's reps into halves, aligned to INDEPENDENT templates
  across   -- two sessions (a sidereal-repeat pair), each aligned to its OWN template
NULL = same pipeline on DIFFERENT gestures (matched window) = the chance floor.

Channels (per capture), the five the plan calls for:
  SD      per-sat single-difference vs common ref, detrended (current pipeline)
  CM      across-sat mean of per-sat-detrended phase (where common-mode gesture lives)
  CMR     clock-separated recovery Shat_i = e_i·d(t) from [E|1]x=phi (keeps common-mode)
  CN0ps   per-sat detrended CN0 (dB-Hz) -- amplitude, immune to the clock confound
  CN0cm   across-sat mean CN0

Usage:
  uv run window-experiment/analysis/alpha_study.py c1.1_day1            # within-session
  uv run window-experiment/analysis/alpha_study.py ref_day1 repeat_day2 # across-day pair
  uv run window-experiment/analysis/alpha_study.py --all                # every session/pair -> results/
"""
import os
import sys
import json
import argparse
from collections import defaultdict

import numpy as np

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # window-experiment
for _d in ("lib", "analysis"):
    sys.path.insert(0, os.path.join(_ROOT, _d))
RESULTS = os.path.join(_ROOT, "results")

import geomlib
import dataset as ds
from preprocess import _parse_cno, NREL_MAX
from onset_align import envelope, align_group, aligned_corr, _z, _seg, BASE, LEN, MAXLAG

PERSAT = ("SD", "CMR", "CN0ps")     # channels that are {sat: signal}
SERIES = ("CM", "CN0cm")            # channels that are a single 1-D series
CHANNELS = PERSAT + SERIES
GESTURES = ("push", "pushpull", "triangle", "m", "star")


def _rel(ph, s, n):
    ep = ph.get(s)
    if not ep:
        return None
    ts = sorted(ep)
    return np.array([ep[t] for t in ts[:n]], float) if len(ts) >= n else None


def _detr(x):
    t = np.arange(len(x))
    return x - np.polyval(np.polyfit(t, x, 2), t)


def build_channels(cap, gps_only=True, elev_mask=20.0):
    """All five channels for one capture, or None if too few clean sats.
    Works for both observables (MSM via geomlib.parse_msm, RAWX via parse_rawx_ph)."""
    ph, lk = (geomlib.parse_msm if cap["source_key"] == "msm" else geomlib.parse_rawx_ph)(cap["rtcm_path"])
    los, el, _ = geomlib.load_meta(cap["rtcm_path"])
    clean = [k for k in geomlib.clean_locktime(ph, lk)
             if k in los and el.get(k, -91) >= elev_mask and (not gps_only or k.startswith("GPS_"))]
    N = min([NREL_MAX] + [len(ph[k]) for k in clean if ph.get(k)])
    rels = {k: _rel(ph, k, N) for k in clean}
    clean = [k for k in clean if rels[k] is not None]
    if len(clean) < 5:
        return None
    perdetr = {k: _detr(rels[k]) for k in clean}   # per-sat detrended abs phase
    CM = np.mean(np.vstack([perdetr[k] for k in clean]), axis=0)
    # clock-separated recovery: [E|1] x = PHI  ->  d = x[:3], Shat_i = e_i·d (keeps CM)
    E = np.vstack([los[k] for k in clean])
    PHI = np.vstack([perdetr[k] for k in clean])
    X = np.linalg.lstsq(np.hstack([E, np.ones((len(clean), 1))]), PHI, rcond=None)[0]
    Shat = E @ X[:3]
    CMR = {clean[i]: Shat[i] for i in range(len(clean))}
    # CN0 (both observables); align to the same N
    cno = _parse_cno(cap, N) or {}
    CN0cm = np.mean(np.vstack(list(cno.values())), axis=0) if cno else None
    # SD is NOT built here: it needs a COMMON reference across the captures being
    # compared (SD to different refs isn't the same observable). Detrend is linear,
    # so SD_k = perdetr_k - perdetr_ref exactly -> built per-comparison from perdetr.
    return dict(perdetr=perdetr, elev={k: el.get(k, -91) for k in clean},
                CM=CM, CMR=CMR, CN0ps=cno, CN0cm=CN0cm, N=N)


def _lags(built, group, channel, align=True):
    """Onset lags for a channel over a group, sized to the shortest capture.
    align=False forces zero-lag (onset alignment off) for the onset-help test."""
    if channel in SERIES:
        envs = [built[c][channel] for c in group if built[c][channel] is not None]
        keys = [c for c in group if built[c][channel] is not None]
    else:
        keys = [c for c in group if built[c][channel]]
        envs = [envelope(built[c][channel], built[c]["N"]) for c in keys]
    if not envs:
        return {}
    if not align:
        return {c: 0 for c in keys}
    N = min(len(e) for e in envs)
    L = min(LEN, N - BASE - MAXLAG)
    if L < 40:
        return {c: 0 for c in keys}          # too short to align -> zero lag
    return dict(zip(keys, align_group([e[:N] for e in envs], base=BASE, L=L)))


def _corr(built, a, b, channel, La, Lb):
    if channel in SERIES:
        x, y = built[a][channel], built[b][channel]
        if x is None or y is None:
            return None
        xa, yb = _z(_seg(x, La)), _z(_seg(y, Lb))
        return float(np.mean(xa * yb)) if xa.std() and yb.std() and len(xa) == len(yb) else None
    sats = [k for k in built[a][channel] if k in built[b][channel]]
    return aligned_corr(built[a][channel], built[b][channel], La, Lb, sats) if sats else None


def _pairs_corr(built, groupA, groupB, channel, cross, align=True):
    """Correlations for every cross-group pair (cross=True: A×B) or within-group
    pair (cross=False: unordered pairs of A), each capture pre-aligned within its
    own group and channel."""
    LA = _lags(built, groupA, channel, align)
    LB = _lags(built, groupB, channel, align) if cross else LA
    if cross:
        pairs = [(a, b) for a in groupA for b in groupB]
    else:
        pairs = [(groupA[i], groupA[j]) for i in range(len(groupA)) for j in range(i + 1, len(groupA))]
    out = []
    for a, b in pairs:
        if a not in LA or b not in LB:
            continue
        v = _corr(built, a, b, channel, LA[a], LB[b])
        if v is not None:
            out.append(v)
    return out


def _sd_pairs(built, A, B, cross, align=True):
    """SD correlations for A vs B using a COMMON reference (highest mean-elevation
    sat present in every capture). SD_k = perdetr_k - perdetr_ref (exact, since
    detrend is linear). Each group aligned independently, then pairs correlated."""
    grp = A + B
    if len(grp) < 2:
        return []
    common = set(built[grp[0]]["perdetr"])
    for c in grp[1:]:
        common &= set(built[c]["perdetr"])
    if len(common) < 3:
        return []
    ref = max(common, key=lambda k: np.mean([built[c]["elev"].get(k, -91) for c in grp]))
    sd = {c: {k: built[c]["perdetr"][k] - built[c]["perdetr"][ref]
              for k in built[c]["perdetr"] if k != ref} for c in grp}

    def lags(group):
        keys = [c for c in group if sd[c]]
        if not keys:
            return {}
        if not align:
            return {c: 0 for c in keys}
        N = min(built[c]["N"] for c in keys)
        L = min(LEN, N - BASE - MAXLAG)
        if L < 40:
            return {c: 0 for c in keys}
        return dict(zip(keys, align_group([envelope(sd[c], N) for c in keys], base=BASE, L=L)))

    LA, LB = lags(A), (lags(B) if cross else lags(A))
    pairs = ([(a, b) for a in A for b in B] if cross
             else [(A[i], A[j]) for i in range(len(A)) for j in range(i + 1, len(A))])
    out = []
    for a, b in pairs:
        if a not in LA or b not in LB:
            continue
        sats = [k for k in sd[a] if k in sd[b]]
        if sats:
            v = aligned_corr(sd[a], sd[b], LA[a], LB[b], sats)
            if v is not None:
                out.append(v)
    return out


def _corr_pairs(built, A, B, ch, cross, align=True):
    """Route SD through the common-reference path; other channels are ref-free."""
    return (_sd_pairs(built, A, B, cross, align) if ch == "SD"
            else _pairs_corr(built, A, B, ch, cross, align))


def _ci(vals, nboot=2000):
    """Median + 95% bootstrap CI of a correlation list (empty -> nan). Seeded for
    reproducibility."""
    if not vals:
        return dict(median=float("nan"), lo=float("nan"), hi=float("nan"), n=0)
    a = np.array(vals, float)
    rng = np.random.default_rng(0)
    meds = np.median(a[rng.integers(0, len(a), size=(nboot, len(a)))], axis=1)
    return dict(median=float(np.median(a)), lo=float(np.percentile(meds, 2.5)),
                hi=float(np.percentile(meds, 97.5)), n=len(a))


def _build_index(sessions, gestures, gps_only):
    """Parse + build every capture ONCE. Returns (built, idx, observable), where
    idx is session -> gesture -> window -> [rtcm_path]."""
    recs = {s: ds.load_session(s) for s in sessions}
    obs = {ds.get_session(s).observable for s in sessions}
    if len(obs) > 1:
        raise ValueError(f"sessions span observables {obs} -- alpha must not pool MSM7+RAWX")
    idx = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    built = {}
    for s in sessions:
        for r in recs[s]:
            if r["gesture"] not in gestures:
                continue
            b = build_channels(r, gps_only=gps_only)
            if b is not None:
                built[r["rtcm_path"]] = b
                idx[s][r["gesture"]][r["window"]].append(r["rtcm_path"])
    return built, idx, obs.pop()


def _matrix(built, idx, sessions, gestures, align=True):
    """Channels dict {ch:{gesture:{alpha,null,passed}}} from a prebuilt index.
    Grouping is per (gesture, WINDOW) → matched geometry, pooled over windows.
    align=False forces zero-lag (onset alignment off) — for the onset-help test."""
    cross = len(sessions) == 2
    s0 = sessions[0]

    def alpha_pairs(gA, gB, ch):
        vals = []
        if cross:
            s1 = sessions[1]
            for w in set(idx[s0][gA]) & set(idx[s1][gB]):
                A, B = idx[s0][gA][w], idx[s1][gB][w]
                if A and B:
                    vals += _corr_pairs(built, A, B, ch, cross=True, align=align)
        else:
            for w in (set(idx[s0][gA]) & set(idx[s0][gB])) if gA != gB else idx[s0][gA]:
                if gA == gB:                              # split-half, independent templates
                    p = idx[s0][gA][w]
                    h = len(p) // 2
                    if h >= 1 and len(p) - h >= 1:
                        vals += _corr_pairs(built, p[:h], p[h:], ch, cross=True, align=align)
                else:                                     # null: different gestures, same window
                    A, B = idx[s0][gA][w], idx[s0][gB][w]
                    if A and B:
                        vals += _corr_pairs(built, A, B, ch, cross=True, align=align)
        return vals

    channels = {}
    for ch in CHANNELS:
        channels[ch] = {}
        for g in gestures:
            alpha = alpha_pairs(g, g, ch)
            null = []
            for g2 in gestures:
                if g2 != g:
                    null += alpha_pairs(g, g2, ch)
            aci, nci = _ci(alpha), _ci(null)
            passed = aci["n"] > 0 and nci["n"] > 0 and aci["lo"] > nci["hi"]
            channels[ch][g] = dict(alpha=aci, null=nci, passed=bool(passed))
    return channels


def study(sessions, gestures=GESTURES, gps_only=True):
    """alpha matrix for one session (within-session split-half) or a two-session
    sidereal pair (across-day). Returns {mode, sessions, observable, channels}."""
    built, idx, obs = _build_index(sessions, gestures, gps_only)
    return {"mode": "across-day" if len(sessions) == 2 else "within-session",
            "sessions": sessions, "observable": obs,
            "channels": _matrix(built, idx, sessions, gestures, align=True)}


def onset_help(sessions, gps_only=True):
    """Secondary #1: does onset alignment help? Median α over gestures with
    alignment ON vs OFF (zero-lag), per channel, from a single build."""
    built, idx, obs = _build_index(sessions, GESTURES, gps_only)
    on = _matrix(built, idx, sessions, GESTURES, align=True)
    off = _matrix(built, idx, sessions, GESTURES, align=False)
    rows = {}
    for ch in CHANNELS:
        av = [on[ch][g]["alpha"]["median"] for g in GESTURES if on[ch][g]["alpha"]["n"]]
        zv = [off[ch][g]["alpha"]["median"] for g in GESTURES if off[ch][g]["alpha"]["n"]]
        if av and zv:
            rows[ch] = dict(aligned=float(np.median(av)), zerolag=float(np.median(zv)))
    return dict(mode="across-day" if len(sessions) == 2 else "within-session",
                sessions=sessions, observable=obs, onset_help=rows)


def rawx_vs_msm():
    """Secondary #2: aggregate the saved α matrix into median within-session α per
    channel, MSM7 vs RAWX (all gestures pooled). Needs results/alpha_matrix.json."""
    matrix = json.load(open(os.path.join(RESULTS, "alpha_matrix.json")))
    agg = {ch: {"MSM7": [], "RAWX": []} for ch in CHANNELS}
    for res in matrix:
        if res["mode"] != "within-session":     # don't double-count the across-day pair
            continue
        for ch in CHANNELS:
            for d in res["channels"][ch].values():
                if d["alpha"]["n"]:
                    agg[ch][res["observable"]].append(d["alpha"]["median"])
    return {ch: {o: (float(np.median(v)) if v else None) for o, v in d.items()}
            for ch, d in agg.items()}


def _cell(d):
    a = d["alpha"]
    val = f"{a['median']:+.2f}" if a["n"] else "-"
    return f"{val + ('*' if d['passed'] else ''):>11}"


def _print(res):
    print(f"\nα study [{res['mode']}]  {' <-> '.join(res['sessions'])}  ({res['observable']})")
    print(f"  {'channel':7}" + "".join(f"{g:>11}" for g in GESTURES) + f"{'null':>10}")
    for ch in CHANNELS:
        nulls = [res["channels"][ch][g]["null"]["median"]
                 for g in GESTURES if res["channels"][ch][g]["null"]["n"]]
        row = f"  {ch:7}" + "".join(_cell(res["channels"][ch][g]) for g in GESTURES)
        row += f"{(f'{np.median(nulls):+.2f}' if nulls else '-'):>10}"
        print(row)
    print("  (* = α 95% CI lower bound clears the null CI upper bound → channel passes for that gesture)")


def main():
    ap = argparse.ArgumentParser(description="Phase 1 alpha study (the gate)")
    ap.add_argument("sessions", nargs="*", default=["c1.1_day1"],
                    help="one session (within-split) or two (across-day pair)")
    ap.add_argument("--all", action="store_true", help="run the standard set -> results/alpha_matrix.json")
    ap.add_argument("--secondaries", action="store_true",
                    help="onset-help + RAWX-vs-MSM diagnostics -> results/alpha_secondaries.json")
    ap.add_argument("--all-constellations", action="store_true", help="don't restrict to GPS")
    a = ap.parse_args()
    gps = not a.all_constellations

    if a.secondaries:
        # onset-help on a representative MSM 5-gesture session + the RAWX pair
        oh_jobs = [["c3.2_day1"], ["ref_day1", "repeat_day2"]]
        oh = []
        print("=== Secondary 1: onset-alignment help (median α over gestures) ===")
        for j in oh_jobs:
            r = onset_help(j, gps_only=gps)
            oh.append(r)
            print(f"\n[{r['mode']}] {' <-> '.join(j)} ({r['observable']})")
            print(f"  {'channel':8}{'aligned':>9}{'zero-lag':>10}{'Δ':>8}")
            for ch, d in r["onset_help"].items():
                print(f"  {ch:8}{d['aligned']:>9.3f}{d['zerolag']:>10.3f}{d['aligned']-d['zerolag']:>+8.3f}")
        print("\n=== Secondary 2: RAWX vs MSM7 (median within-session α per channel) ===")
        rvm = rawx_vs_msm()
        print(f"  {'channel':8}{'MSM7':>9}{'RAWX':>9}")
        for ch, d in rvm.items():
            fmt = lambda x: f"{x:>9.3f}" if x is not None else f"{'-':>9}"
            print(f"  {ch:8}{fmt(d['MSM7'])}{fmt(d['RAWX'])}")
        os.makedirs(RESULTS, exist_ok=True)
        path = os.path.join(RESULTS, "alpha_secondaries.json")
        json.dump(dict(onset_help=oh, rawx_vs_msm=rvm), open(path, "w"), indent=2)
        print(f"\nwrote {path}")
        return

    if a.all:
        jobs = [["c1.1_day1"], ["c3.2_day1"], ["c3.2_day2"], ["c3.2_day3"],
                ["ref_day1"], ["repeat_day2"],
                ["ref_day1", "repeat_day2"]]      # the cleanest across-day pair
        matrix = []
        for j in jobs:
            try:
                r = study(j, gps_only=gps)
                matrix.append(r)
                _print(r)
            except ValueError as e:
                print(f"skip {j}: {e}")
        os.makedirs(RESULTS, exist_ok=True)
        path = os.path.join(RESULTS, "alpha_matrix.json")
        json.dump(matrix, open(path, "w"), indent=2)
        print(f"\nwrote {path}")
    else:
        _print(study(a.sessions, gps_only=gps))


if __name__ == "__main__":
    main()
