#!/usr/bin/env python3
"""
geomlib.py -- geometry-analysis library for the GNSS gesture window experiment.

Provides, for both observables:
  - epoch-keyed carrier phase in metres (MSM: DF397+DF398+DF406 ; RAWX: cpMes*lambda)
  - lock-time cycle-slip detection (MSM: DF407 ; RAWX: locktime) -- the correct,
    receiver-reported slip flag, NOT the 50 m heuristic
  - single-difference + detrend signal extraction
  - trajectory recovery d(t)=pinv(G)S and the structure matrix M = D D^T

IMPORTANT CAVEATS (see README.md "Current status"):
  - The envelope-based gesture-window detector below is UNRELIABLE on the current
    free-hand data: the single-differenced envelope is nearly flat (no localised
    gesture event), so it latches onto the largest noise excursion. Any M / kappa /
    dt_max computed downstream is therefore fitting non-reproducible fluctuation,
    NOT a stable gesture, until the reproducibility floor alpha is raised
    (mechanical reproduction) and/or the common-mode question is resolved.
  - The synthetic-ground-truth check (1D/2D/3D gestures through real geometry)
    confirms the *inversion* is correct; the problem is in the *data* (alpha~0),
    not this code.
"""

import json
import numpy as np
from collections import defaultdict
from pyubx2 import UBXReader, UBX_PROTOCOL, NMEA_PROTOCOL, RTCM3_PROTOCOL
from parse_rawx import _trkbits

C = 299_792_458.0
# RAWX carrier wavelengths by (gnssId, sigId): GPS L1, Galileo E1/E5a, BeiDou B1I/B2a
WL_RAWX = {
    (0, 0): C / 1575.42e6,
    (2, 0): C / 1575.42e6,
    (2, 4): C / 1176.45e6,
    (3, 0): C / 1561.098e6,
    (3, 7): C / 1176.45e6,
}
GN = {0: "GPS", 2: "GAL", 3: "BDS"}


def parse_msm(path):
    """Epoch-keyed phase (m) + DF407 lock time, GPS(1077)+BeiDou(1127).
    BeiDou epoch (BDT) shifted +14 s so the receiver-clock common-mode aligns."""
    ph = defaultdict(dict)
    lk = defaultdict(dict)
    SIG = {"1077": ("GPS", 0), "1127": ("BDS", 140)}  # name, 0.1s tkey offset
    with open(path, "rb") as fh:
        for _r, p in UBXReader(
            fh, protfilter=UBX_PROTOCOL | NMEA_PROTOCOL | RTCM3_PROTOCOL
        ):
            if p is None or p.identity not in SIG:
                continue
            nm, off = SIG[p.identity]
            tow = getattr(p, "DF004", None)
            if tow is None:
                continue
            tk = int(round(tow / 100.0)) + off
            ns = getattr(p, "NSat", 0)
            nc = getattr(p, "NCell", 0)
            rough = {}
            for s in range(1, ns + 1):
                prn = getattr(p, f"PRN_{s:02d}", None)
                d398 = getattr(p, f"DF398_{s:02d}", None)
                d397 = getattr(p, f"DF397_{s:02d}", None)
                if prn is not None and d398 is not None:
                    rough[int(prn)] = (d397 or 0, d398)
            for cc in range(1, nc + 1):
                prn = getattr(p, f"CELLPRN_{cc:02d}", None)
                d406 = getattr(p, f"DF406_{cc:02d}", None)
                d407 = getattr(p, f"DF407_{cc:02d}", None)
                if prn is not None and int(prn) in rough and d406 is not None:
                    a, b = rough[int(prn)]
                    k = f"{nm}_{int(prn):03d}"
                    ph[k][tk] = (a + b + d406) * C / 1000.0
                    if d407 is not None:
                        lk[k][tk] = d407
    return dict(ph), dict(lk)


def parse_rawx_ph(path):
    """Epoch-keyed cpMes*lambda (m) + locktime, best-CNO signal per satellite,
    GPS + Galileo + BeiDou."""
    raw = defaultdict(lambda: defaultdict(dict))
    lkr = defaultdict(lambda: defaultdict(dict))
    cno = defaultdict(lambda: defaultdict(list))
    with open(path, "rb") as fh:
        for _r, p in UBXReader(
            fh, protfilter=UBX_PROTOCOL | NMEA_PROTOCOL | RTCM3_PROTOCOL
        ):
            if p is None or p.identity != "RXM-RAWX":
                continue
            tow = getattr(p, "rcvTow", None)
            if tow is None:
                continue
            tk = int(round(tow * 10))
            for i in range(1, getattr(p, "numMeas", 0) + 1):
                g = getattr(p, f"gnssId_{i:02d}", None)
                sv = getattr(p, f"svId_{i:02d}", None)
                sg = getattr(p, f"sigId_{i:02d}", None)
                if (g, sg) not in WL_RAWX:
                    continue
                _, cpv, _, _ = _trkbits(p, i)
                cp = getattr(p, f"cpMes_{i:02d}", 0.0)
                if not cpv or cp == 0:
                    continue
                k = f"{GN[g]}_{sv:03d}"
                raw[k][(g, sg)][tk] = cp * WL_RAWX[(g, sg)]
                lkr[k][(g, sg)][tk] = getattr(p, f"locktime_{i:02d}", 0)
                cno[k][(g, sg)].append(getattr(p, f"cno_{i:02d}", 0))
    ph = {}
    lk = {}
    for k, sigs in raw.items():
        best = max(sigs, key=lambda s: np.mean(cno[k][s]))  # one signal per sat
        ph[k] = sigs[best]
        lk[k] = lkr[k][best]
    return ph, lk


def clean_locktime(ph, lk, nmin=100):
    """Clean satellite = present for >= nmin epochs with a strictly non-decreasing
    lock time (no cycle slip). Validated vs RAWX truth at 86% recall for MSM DF407."""
    out = []
    for k, ep in ph.items():
        ts = sorted(ep)
        if len(ts) < nmin:
            continue
        lt = [lk.get(k, {}).get(t) for t in ts]
        if any(x is None for x in lt):
            continue
        if any(lt[i] < lt[i - 1] for i in range(1, len(lt))):
            continue
        out.append(k)
    return out


def load_meta(path):
    """Return (los_enu per sat, elevation per sat, ref_sat) from the .meta.json sidecar."""
    m = json.load(open(path.replace(".rtcm", ".meta.json")))
    los = {k: np.array(v["los_enu"], float) for k, v in m["satellites"].items()}
    el = {k: v["elev_deg"] for k, v in m["satellites"].items()}
    return los, el, m["ref_sat"]


def detrend(x, t, deg=2):
    return x - np.polyval(np.polyfit(t, x, deg), t)


def analyze_capture(path, source, elev_mask=20.0):
    """Recover trajectory + structure matrix for one capture.
    Returns dict(n_clean, condG, sv, M_eig, var_exp, ...) or None if too few clean sats.
    source in {'msm','rawx'}.  NB: see module caveat about gesture-window reliability."""
    ph, lk = parse_msm(path) if source == "msm" else parse_rawx_ph(path)
    los, el, _ = load_meta(path)
    clean = [
        k for k in clean_locktime(ph, lk) if el.get(k, -91) >= elev_mask and k in los
    ]
    if len(clean) < 5:
        return None
    ref = max(clean, key=lambda k: el[k])
    others = [k for k in clean if k != ref]
    common = set(ph[ref])
    for k in others:
        common &= set(ph[k])
    common = sorted(common)
    if len(common) < 100:
        return None
    t = (np.array(common) - common[0]) / 10.0
    S = []
    G = []
    for k in others:
        s = np.array([ph[k][tt] - ph[ref][tt] for tt in common])
        S.append(detrend(s, t))
        G.append(los[k] - los[ref])
    S = np.vstack(S)
    G = np.vstack(G)
    env = np.sqrt(np.mean(S**2, axis=0))
    pk = np.argmax(env)
    idx = np.where(env >= 0.25 * env[pk])[0]
    lo, hi = max(idx.min(), 0), min(idx.max() + 1, len(t))
    if hi - lo < 15:
        lo, hi = max(pk - 25, 0), min(pk + 25, len(t))
    Sg = S[:, lo:hi]
    sv = np.linalg.svd(Sg, compute_uv=False)
    sv = sv / sv[0]
    Drec = np.linalg.pinv(G) @ Sg
    Shat = G @ Drec
    var_exp = 1 - np.sum((Sg - Shat) ** 2) / np.sum(Sg**2)
    M = Drec @ Drec.T
    ev = np.linalg.eigvalsh(M)[::-1]
    return dict(
        n_clean=len(clean),
        condG=float(np.linalg.cond(G)),
        sv=sv[:4],
        M_eig=ev / ev[0],
        var_exp=float(var_exp),
        gest_win=(lo, hi, len(t)),
        ref=ref,
    )
