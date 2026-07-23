#!/usr/bin/env python3
"""
measure_alpha.py -- reproduce the onset-aligned reproducibility-floor (alpha)
measurement of PROJECT_LOG.md §9, GPS only, from a reference session and its
sidereal repeat.

alpha = r(dtheta≈0): correlation between two repetitions of the SAME gesture at
matched geometry. We report it three ways to separate timing jitter and
shared-template inflation from the real signal:

  zero-lag                 -- naive, no alignment (the README "alpha≈0" view)
  within-session (split)   -- onset-aligned, two halves aligned to INDEPENDENT
                              templates then cross-correlated (no shared-template
                              inflation) -- honest same-session floor
  across-day               -- onset-aligned, each day aligned to its OWN template
                              then day1×day2 correlated -- honest sidereal-repeat
                              floor; equals within-session iff the day gap is free

Plus a NULL (different gestures, matched geometry, same pipeline) = chance floor.

Usage:  uv run measure_alpha.py            # defaults to ref_day1 <-> repeat_day2
        uv run measure_alpha.py --ref ref_day1 --rep repeat_day2
"""
import argparse
import os, sys
import json
import numpy as np
from collections import defaultdict

# Make sibling code dirs importable and locate the data dir, regardless of CWD
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _d in ("lib", "capture", "analysis"):
    sys.path.insert(0, os.path.join(_ROOT, _d))
SAMPLES = os.path.join(_ROOT, "data", "samples")

from geomlib import parse_rawx_ph, clean_locktime
from onset_align import envelope, align_group, aligned_corr

NREL = 120  # relative epochs kept per capture (12 s @ 10 Hz)


def _rel(ph, s):
    ep = ph.get(s)
    if not ep:
        return None
    ts = sorted(ep)
    return np.array([ep[t] for t in ts[:NREL]], float) if len(ts) >= NREL else None


def _sd(ph, s, ref):
    """single-difference vs ref + deg-2 detrend, on the relative-time grid."""
    a, b = _rel(ph, s), _rel(ph, ref)
    if a is None or b is None:
        return None
    n = min(len(a), len(b))
    x = a[:n] - b[:n]
    t = np.arange(n)
    return x - np.polyval(np.polyfit(t, x, 2), t)


def _manifest(name):
    m = json.load(open(os.path.join(SAMPLES, f"{name}_manifest.json")))
    return {(e["gesture"], e["window_index"], e["rep"]): os.path.join(SAMPLES, e["rtcm"])
            for e in m["entries"]}


def _elev_gps(rtcm):
    m = json.load(open(rtcm.replace(".rtcm", ".meta.json")))
    return {k: v["elev_deg"] for k, v in m["satellites"].items() if k.startswith("GPS_")}


def _ctx(caps):
    """common lock-time-clean GPS sats + highest-elev reference across a set."""
    loaded = {c: parse_rawx_ph(c) for c in caps}
    sets = [set(k for k in clean_locktime(*loaded[c]) if k.startswith("GPS_")) for c in caps]
    common = set.intersection(*sets) if sets else set()
    if len(common) < 3:
        return None, None
    ref = max(common, key=lambda k: _elev_gps(caps[0]).get(k, -91))
    return ref, sorted(common - {ref})


def _prep(caps, ref, tg):
    sds, envs = [], []
    for c in caps:
        ph = parse_rawx_ph(c)[0]
        d = {s: _sd(ph, s, ref) for s in tg if _sd(ph, s, ref) is not None}
        sds.append(d)
        envs.append(envelope(d, NREL))
    return sds, envs


def main():
    ap = argparse.ArgumentParser(description="onset-aligned alpha (GPS, matched geometry)")
    ap.add_argument("--ref", default="ref_day1")
    ap.add_argument("--rep", default="repeat_day2")
    args = ap.parse_args()
    dref, drep = _manifest(args.ref), _manifest(args.rep)

    R = defaultdict(lambda: defaultdict(list))
    for g in ("push", "star"):
        for w in range(4):
            c1 = [dref[(g, w, r)] for r in range(1, 7) if (g, w, r) in dref]
            c2 = [drep[(g, w, r)] for r in range(1, 7) if (g, w, r) in drep]
            ref, tg = _ctx(c1 + c2)
            if ref is None:
                continue
            sd1, env1 = _prep(c1, ref, tg)
            sd2, env2 = _prep(c2, ref, tg)

            # zero-lag (no alignment) across-day
            for i, di in enumerate(sd1):
                for j, dj in enumerate(sd2):
                    v = aligned_corr(di, dj, 0, 0, tg)
                    if v is not None:
                        R[g]["zerolag"].append(v)

            # across-day, onset-aligned with INDEPENDENT per-day templates
            L1, L2 = align_group(env1), align_group(env2)
            for i, di in enumerate(sd1):
                for j, dj in enumerate(sd2):
                    v = aligned_corr(di, dj, L1[i], L2[j], tg)
                    if v is not None:
                        R[g]["across"].append(v)

            # within-session, split into halves with INDEPENDENT templates
            for sds, envs in ((sd1, env1), (sd2, env2)):
                A, B = [0, 1, 2], [3, 4, 5]
                if len(sds) < 6:
                    continue
                LA = align_group([envs[i] for i in A])
                LB = align_group([envs[i] for i in B])
                for ia, i in enumerate(A):
                    for ib, j in enumerate(B):
                        v = aligned_corr(sds[i], sds[j], LA[ia], LB[ib], tg)
                        if v is not None:
                            R[g]["within_split"].append(v)

    # NULL: different gestures, matched window, independent per-gesture templates
    null = []
    for w in range(4):
        cp = [dref[("push", w, r)] for r in range(1, 7) if ("push", w, r) in dref]
        cs = [drep[("star", w, r)] for r in range(1, 7) if ("star", w, r) in drep]
        ref, tg = _ctx(cp + cs)
        if ref is None:
            continue
        sdp, envp = _prep(cp, ref, tg)
        sds, envs = _prep(cs, ref, tg)
        Lp, Ls = align_group(envp), align_group(envs)
        for i, di in enumerate(sdp):
            for j, dj in enumerate(sds):
                v = aligned_corr(di, dj, Lp[i], Ls[j], tg)
                if v is not None:
                    null.append(v)

    print(f"alpha (GPS, Δθ≈0)   {args.ref} <-> {args.rep}\n")
    print(f"  {'pair set':34}{'push':>8}{'star':>8}")
    for label, key in (("zero-lag (naive)", "zerolag"),
                       ("onset-aligned, within-session", "within_split"),
                       ("onset-aligned, across-day", "across")):
        p = np.median(R["push"][key]) if R["push"][key] else float("nan")
        s = np.median(R["star"][key]) if R["star"][key] else float("nan")
        print(f"  {label:34}{p:>8.3f}{s:>8.3f}")
    print(f"\n  NULL (push×star, aligned)          median r = {np.median(null):+.3f}  (N={len(null)})")


if __name__ == "__main__":
    main()
