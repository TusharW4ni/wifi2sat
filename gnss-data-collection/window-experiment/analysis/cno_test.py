#!/usr/bin/env python3
"""
CN0 observable test: does the hand's effect show up in per-satellite signal
STRENGTH (carrier-to-noise, dB-Hz)? CN0 is immune to the receiver-clock confound
that traps the common-mode phase, so if the hand modulates received power this is
a clock-free, software-only observable.

Two forms, same onset-alignment + null as everything else, GPS only:
  CN0 per-sat  -- detrended per-satellite CN0 (directional shadowing)
  CN0 common   -- across-satellite mean detrended CN0 (broadband block/reflect)
Also reports the typical gesture-time CN0 swing (dB) as an SNR gauge.
"""
import os, json, sys
import numpy as np
from collections import defaultdict

# Make sibling code dirs importable and locate the data dir, regardless of CWD
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _d in ("lib", "capture", "analysis"):
    sys.path.insert(0, os.path.join(_ROOT, _d))
SAMPLES = os.path.join(_ROOT, "data", "samples")

from pyubx2 import UBXReader, UBX_PROTOCOL, NMEA_PROTOCOL, RTCM3_PROTOCOL
from geomlib import WL_RAWX
from onset_align import align_group, envelope, aligned_corr, _z, _seg

NREL = 120


def parse_cno(path):
    raw = defaultdict(lambda: defaultdict(dict))
    with open(path, 'rb') as fh:
        for _r, p in UBXReader(fh, protfilter=UBX_PROTOCOL | NMEA_PROTOCOL | RTCM3_PROTOCOL):
            if p is None or p.identity != 'RXM-RAWX':
                continue
            tow = getattr(p, 'rcvTow', None)
            if tow is None:
                continue
            tk = int(round(tow * 10))
            for i in range(1, getattr(p, 'numMeas', 0) + 1):
                g = getattr(p, f'gnssId_{i:02d}', None)
                sv = getattr(p, f'svId_{i:02d}', None)
                sg = getattr(p, f'sigId_{i:02d}', None)
                if g != 0 or (g, sg) not in WL_RAWX:   # GPS only
                    continue
                cno = getattr(p, f'cno_{i:02d}', None)
                if cno is None:
                    continue
                raw[f'GPS_{sv:03d}'][(g, sg)][tk] = float(cno)
    out = {}
    for k, sigs in raw.items():
        best = max(sigs, key=lambda s: np.mean(list(sigs[s].values())))
        out[k] = sigs[best]
    return out


def _rel(series):
    ts = sorted(series)
    return np.array([series[t] for t in ts[:NREL]], float) if len(ts) >= NREL else None


def _detr(x):
    t = np.arange(len(x))
    return x - np.polyval(np.polyfit(t, x, 2), t)


def build(rtcm):
    cno = parse_cno(rtcm)
    sd = {}
    for k, s in cno.items():
        r = _rel(s)
        if r is not None:
            sd[k] = _detr(r)
    if len(sd) < 5:
        return None
    cm = np.mean(np.vstack([sd[k] for k in sd]), axis=0)
    swing = np.median([np.percentile(sd[k], 95) - np.percentile(sd[k], 5) for k in sd])
    return sd, cm, swing


def mi(m):
    d = json.load(open(os.path.join(SAMPLES, m)))
    return {(e['gesture'], e['window_index'], e['rep']): os.path.join(SAMPLES, e['rtcm']) for e in d['entries']}


def cm_corr(a, b, la, lb):
    x, y = _z(_seg(a, la)), _z(_seg(b, lb))
    return float(np.mean(x * y)) if x.std() and y.std() else None


d14, d15 = mi('ref_day1_manifest.json'), mi('repeat_day2_manifest.json')


def run(caps, cross=None):
    built = {c: build(c) for c in set(caps + (cross or []))}
    built = {c: b for c, b in built.items() if b is not None}
    G = [c for c in caps if c in built]
    Lp = dict(zip(G, align_group([envelope(built[c][0], NREL) for c in G])))
    Lc = dict(zip(G, align_group([built[c][1] for c in G])))
    if cross is not None:
        Gc = [c for c in cross if c in built]
        Lp2 = dict(zip(Gc, align_group([envelope(built[c][0], NREL) for c in Gc])))
        Lc2 = dict(zip(Gc, align_group([built[c][1] for c in Gc])))
        pairs = [(a, b) for a in G for b in Gc]
    else:
        Lp2, Lc2 = Lp, Lc
        pairs = [(G[i], G[j]) for i in range(len(G)) for j in range(i + 1, len(G))]
    out = defaultdict(list)
    for a, b in pairs:
        sats = [k for k in built[a][0] if k in built[b][0]]
        if sats:
            v = aligned_corr(built[a][0], built[b][0], Lp[a], Lp2[b], sats)
            if v is not None:
                out['persat'].append(v)
        v = cm_corr(built[a][1], built[b][1], Lc[a], Lc2[b])
        if v is not None:
            out['common'].append(v)
    return out, [built[c][2] for c in G]


agg = defaultdict(lambda: defaultdict(list)); swings = []
for g in ('push', 'star'):
    for w in range(4):
        caps = [d14[(g, w, r)] for r in range(1, 7) if (g, w, r) in d14] + \
               [d15[(g, w, r)] for r in range(1, 7) if (g, w, r) in d15]
        out, sw = run(caps)
        for k in ('persat', 'common'):
            agg[g][k] += out[k]
        swings += sw
nullagg = defaultdict(list)
for w in range(4):
    cp = [d14[('push', w, r)] for r in range(1, 7) if ('push', w, r) in d14] + \
         [d15[('push', w, r)] for r in range(1, 7) if ('push', w, r) in d15]
    cs = [d14[('star', w, r)] for r in range(1, 7) if ('star', w, r) in d14] + \
         [d15[('star', w, r)] for r in range(1, 7) if ('star', w, r) in d15]
    out, _ = run(cp, cross=cs)
    for k in ('persat', 'common'):
        nullagg[k] += out[k]

print("CN0 reproducibility (within-window, onset-aligned), GPS only:\n")
print(f"  {'observable':16}{'push α':>9}{'star α':>9}{'null':>9}")
for k, lab in (('persat', 'CN0 per-sat'), ('common', 'CN0 common-mode')):
    print(f"  {lab:16}{np.median(agg['push'][k]):>9.3f}{np.median(agg['star'][k]):>9.3f}{np.median(nullagg[k]):>9.3f}")
print(f"\n  typical gesture-time CN0 swing (median 5-95 pct, detrended): {np.median(swings):.1f} dB-Hz")
