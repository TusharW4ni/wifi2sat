#!/usr/bin/env python3
"""
preprocess.py -- Phase 0's one shared preprocessing pipeline (build once).

Turns raw captures (located via dataset.py) into a tidy per-capture FEATURE
OBJECT that every downstream phase (alpha study, classification, coherence)
consumes, so the SD / common-reference / onset / trajectory logic lives in ONE
place instead of being re-implemented in measure_alpha / cno_test / etc.

Pipeline (ANALYSIS_PLAN.md §2 Phase 0), reusing the validated primitives:
  - parse + DF407/locktime slip cleaning        geomlib.parse_{msm,rawx_ph}, clean_locktime
  - common-reference single-difference + detrend (fixes varying ref_sat)
  - across-satellite motion envelope + onset alignment   onset_align.align_group
  - CMR trajectory d(t)=pinv(G)S and g-vectors g_i=los_i-los_ref
  - per-sat CN0 (RAWX; MSM only if the stream carries DF408)

Per-capture feature object (see preprocess_group):
  {session,gesture,window,rep,observable, ref, sats, N, t,
   sd:{sat:array}, envelope, onset_lag, g:{sat:[e,n,u]}, cmr:3xN, cn0:{sat:array}|None}

Scope: the window-experiment geometry sessions (they carry meta sidecars, so
los_enu/elev and thus g/CMR are available). finesat captures have no geometry
sidecar and are handled by the finesat build scripts, not here.

CLI:  uv run window-experiment/analysis/preprocess.py <session>          # feature summary
      uv run window-experiment/analysis/preprocess.py --yield <session>  # DF407 vs passed_health yield
"""
import os
import sys
import json
import argparse
from collections import defaultdict

import numpy as np
from pyubx2 import UBXReader, UBX_PROTOCOL, NMEA_PROTOCOL, RTCM3_PROTOCOL

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # window-experiment
for _d in ("lib", "analysis"):
    sys.path.insert(0, os.path.join(_ROOT, _d))

import geomlib
import dataset as ds
from onset_align import envelope as _envelope, align_group, BASE, LEN, MAXLAG

FS = 10             # Hz
NREL_MAX = 120      # cap on relative epochs kept per capture (12 s @ 10 Hz)
ELEV_MASK = 20.0    # deg
# NB: MSM7 captures run 118 epochs, RAWX 120 -- the working length N is derived
# per group (min common epochs, capped at NREL_MAX), never hard-coded.


def _rel(ph, s, n):
    """First n epochs of sat s on the relative-time grid, or None if too short."""
    ep = ph.get(s)
    if not ep:
        return None
    ts = sorted(ep)
    return np.array([ep[t] for t in ts[:n]], float) if len(ts) >= n else None


def _parse_phase(cap):
    """(phase, locktime) dicts via the observable-correct geomlib primitive."""
    fn = geomlib.parse_msm if cap["source_key"] == "msm" else geomlib.parse_rawx_ph
    return fn(cap["rtcm_path"])


def clean_capture(cap, elev_mask=ELEV_MASK, gps_only=False):
    """Parse one capture and return its DF407/locktime-clean, elev-masked sat set
    plus geometry. Raises if the capture has no meta sidecar (no geometry)."""
    if not cap.get("meta_path"):
        raise ValueError(f"{cap['session']}/{cap['gesture']}: no meta sidecar -> "
                         "no geometry; preprocess covers window-experiment sessions only")
    ph, lk = _parse_phase(cap)
    los, elev, ref_meta = geomlib.load_meta(cap["rtcm_path"])
    clean = [k for k in geomlib.clean_locktime(ph, lk)
             if k in los and elev.get(k, -91) >= elev_mask]
    if gps_only:
        clean = [k for k in clean if k.startswith("GPS_")]
    return dict(ph=ph, lk=lk, los=los, elev=elev, clean=clean)


def common_context(caps, elev_mask=ELEV_MASK, gps_only=False):
    """Common locktime-clean sats + highest-elevation common reference across a
    group of captures (so every capture is single-differenced to the SAME ref --
    fixes the varying per-capture ref_sat). Returns (ref, sats, parsed_caps)."""
    parsed = [clean_capture(c, elev_mask, gps_only) for c in caps]
    sets = [set(p["clean"]) for p in parsed]
    common = set.intersection(*sets) if sets else set()
    if len(common) < 3:
        return None, None, parsed
    el0 = parsed[0]["elev"]
    ref = max(common, key=lambda k: el0.get(k, -91))
    return ref, sorted(common - {ref}), parsed


def _parse_cno(cap, n):
    """Per-sat detrended CN0 (dB-Hz) over the first n epochs. RAWX: UBX cno field;
    MSM: DF408 per cell if present. Returns {sat: array(len n)} or None if the
    stream carries no usable CN0."""
    raw = defaultdict(lambda: defaultdict(dict))       # sat -> sigkey -> {tk: cno}
    is_rawx = cap["source_key"] == "rawx"
    with open(cap["rtcm_path"], "rb") as fh:
        for _r, p in UBXReader(fh, protfilter=UBX_PROTOCOL | NMEA_PROTOCOL | RTCM3_PROTOCOL):
            if p is None:
                continue
            if is_rawx and p.identity == "RXM-RAWX":
                tow = getattr(p, "rcvTow", None)
                if tow is None:
                    continue
                tk = int(round(tow * 10))
                for i in range(1, getattr(p, "numMeas", 0) + 1):
                    g = getattr(p, f"gnssId_{i:02d}", None)
                    sv = getattr(p, f"svId_{i:02d}", None)
                    sg = getattr(p, f"sigId_{i:02d}", None)
                    c = getattr(p, f"cno_{i:02d}", None)
                    if (g, sg) in geomlib.WL_RAWX and c:
                        raw[f"{geomlib.GN[g]}_{sv:03d}"][(g, sg)][tk] = float(c)
            elif (not is_rawx) and p.identity in ("1077", "1127"):
                nm = {"1077": "GPS", "1127": "BDS"}[p.identity]
                tow = getattr(p, "DF004", None)
                if tow is None:
                    continue
                tk = int(round(tow / 100.0))
                for cc in range(1, getattr(p, "NCell", 0) + 1):
                    prn = getattr(p, f"CELLPRN_{cc:02d}", None)
                    cnr = getattr(p, f"DF408_{cc:02d}", None)   # MSM7 CNR (dB-Hz), if present
                    if prn is not None and cnr:
                        raw[f"{nm}_{int(prn):03d}"]["msm"][tk] = float(cnr)
    out = {}
    for k, sigs in raw.items():
        best = max(sigs, key=lambda s: np.mean(list(sigs[s].values())))
        series = sigs[best]
        ts = sorted(series)
        if len(ts) >= n:
            r = np.array([series[t] for t in ts[:n]], float)
            t = np.arange(len(r))
            out[k] = r - np.polyval(np.polyfit(t, r, 2), t)
    return out or None


def preprocess_group(caps, ref=None, sats=None, onset=True,
                     elev_mask=ELEV_MASK, gps_only=False, cn0=True):
    """Preprocess a group of captures (e.g. all reps of one gesture×window) to a
    common reference. Returns {ref, sats, features:[feature-object,...]}.

    Pass an explicit ref+sats to reuse the SAME reference across groups/sessions
    (cross-day work); otherwise a common context is derived from this group."""
    if ref is None or sats is None:
        ref, sats, parsed = common_context(caps, elev_mask, gps_only)
        if ref is None:
            raise ValueError("fewer than 3 common locktime-clean sats across the group")
    else:
        parsed = [clean_capture(c, elev_mask, gps_only) for c in caps]

    # working length: min common epochs over ref+sats across every capture, capped
    lens = [len(pc["ph"][s]) for pc in parsed for s in [ref] + sats if pc["ph"].get(s)]
    N = min([NREL_MAX] + lens)

    feats, envs = [], []
    for cap, pc in zip(caps, parsed):
        ph, los = pc["ph"], pc["los"]
        refa = _rel(ph, ref, N)
        sd = {}
        if refa is not None:
            for s in sats:
                a = _rel(ph, s, N)
                if a is None:
                    continue
                x = a - refa
                t = np.arange(len(x))
                sd[s] = x - np.polyval(np.polyfit(t, x, 2), t)   # common-ref SD + detrend
        used = [s for s in sats if s in sd]
        env = _envelope(sd, N) if used else None
        g = {s: los[s] - los[ref] for s in used if s in los and ref in los}
        cmr = None
        if len(used) >= 3:
            S = np.vstack([sd[s] for s in used])
            G = np.vstack([g[s] for s in used])
            cmr = np.linalg.pinv(G) @ S                          # CMR trajectory d(t)
        feats.append(dict(
            session=cap["session"], gesture=cap["gesture"], window=cap["window"],
            rep=cap["rep"], observable=cap["observable"], ref=ref, sats=used, N=N,
            t=np.arange(N) / FS, sd=sd, envelope=env, onset_lag=None, g=g, cmr=cmr,
            cn0=_parse_cno(cap, N) if cn0 else None,
        ))
        envs.append(env)

    # onset alignment: size the search window to the working length N (the
    # default 118-sample window is calibrated for 120-epoch RAWX; MSM runs ~115).
    onset_len = min(LEN, N - BASE - MAXLAG)      # BASE(20) >= MAXLAG(18) already holds
    onset_win = (BASE, onset_len) if onset_len >= 40 else None
    if onset and onset_win and envs and all(e is not None for e in envs):
        for f, lag in zip(feats, align_group(envs, base=BASE, L=onset_len)):
            f["onset_lag"] = lag
    return dict(ref=ref, sats=sats, N=N, onset_win=onset_win, features=feats)


def yield_report(session, elev_mask=ELEV_MASK):
    """Per-window clean-sat yield under the DF407/locktime gate vs the meta
    `passed_health` floor (the old 50 m gate). Shows the rescue Phase 0 buys."""
    recs = ds.load_session(session)
    by_w = defaultdict(list)
    for r in recs:
        by_w[r["window"]].append(r)
    print(f"clean-sat yield (>=3 clean) -- {session}   [locktime/DF407 vs passed_health floor]")
    print(f"  {'window':<8}{'n':>4}{'passed_health':>16}{'DF407/locktime':>18}")
    for w in sorted(by_w, key=lambda x: (x is None, x)):
        rs = by_w[w]
        ph_ok = lt_ok = 0
        for r in rs:
            meta = json.load(open(r["meta_path"]))
            sats = meta.get("satellites", {})
            ph_ok += sum(1 for v in sats.values() if v.get("passed_health")) >= 3
            pc = clean_capture(r, elev_mask=0.0)     # no elev mask -> compare gates fairly
            lt_ok += len(pc["clean"]) >= 3
        n = len(rs)
        print(f"  W{str(w):<7}{n:>4}{f'{100*ph_ok/n:.0f}%':>16}{f'{100*lt_ok/n:.0f}%':>18}")


def _summary(session):
    recs = ds.load_session(session)
    # group by (gesture, window); preprocess the first non-trivial group as a demo
    groups = defaultdict(list)
    for r in recs:
        groups[(r["gesture"], r["window"])].append(r)
    print(f"preprocess feature objects -- {session}  ({len(groups)} gesture×window groups)\n")
    print(f"  {'gesture':<9}{'win':>4}{'reps':>5}{'ref':>10}{'sats':>5}{'N':>5}{'onset(lags)':>26}{'cmr':>6}{'cn0':>5}")
    for (g, w), caps in sorted(groups.items(), key=lambda kv: (str(kv[0][1]), kv[0][0])):
        try:
            out = preprocess_group(caps)
        except ValueError as e:
            print(f"  {g:<9}{str(w):>4}{len(caps):>5}   -- skipped: {e}")
            continue
        f0 = out["features"][0]
        lags = [f["onset_lag"] for f in out["features"]]
        print(f"  {g:<9}{str(w):>4}{len(caps):>5}{out['ref']:>10}{len(out['sats']):>5}{out['N']:>5}"
              f"{str(lags):>26}{('Y' if f0['cmr'] is not None else '-'):>6}"
              f"{('Y' if f0['cn0'] else '-'):>5}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Phase 0 preprocessing pipeline")
    ap.add_argument("session", nargs="?", default="c1.1_day1")
    ap.add_argument("--yield", dest="do_yield", action="store_true",
                    help="print DF407 vs passed_health clean-sat yield instead")
    a = ap.parse_args()
    (yield_report if a.do_yield else _summary)(a.session)
