#!/usr/bin/env python3
"""
Common-mode test: is the gesture living in the across-satellite-average signal
that single-differencing (SD) discards?

Three observables, same reps, same onset alignment, same null:
  SD   -- current pipeline: phi_i - phi_ref, detrended  (removes clock AND any
          common-mode gesture)
  CM   -- across-satellite MEAN of per-sat-detrended phase (clock + common-mode
          gesture); if the gesture is common-mode it lives here
  CMR  -- clock-separated recovery: per epoch solve [E | 1]·x = phi~ , where E is
          the absolute-LOS matrix and the "1" column absorbs the clock; the
          reconstructed per-sat gesture Shat_i = e_i·d(t) KEEPS the common-mode
          part (unlike SD). This is the "proper" common-mode-aware observable.

If CM or CMR reproduce (across reps) much better than SD -> the gesture is
common-mode and SD is throwing it away (a processing fix, revisit alpha).
If all three are low/near-null -> not hiding in common-mode; free-hand signal is
genuinely low-SNR (confirms the earlier conclusion, no processing rescue).
"""
import os, json, sys
import numpy as np
from collections import defaultdict

# Make sibling code dirs importable and locate the data dir, regardless of CWD
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _d in ("lib", "capture", "analysis"):
    sys.path.insert(0, os.path.join(_ROOT, _d))
SAMPLES = os.path.join(_ROOT, "data", "samples")

from geomlib import parse_rawx_ph, clean_locktime
from onset_align import envelope, align_group, aligned_corr, _z, _seg

NREL = 120


def _rel(ph, s):
    ep = ph.get(s)
    if not ep: return None
    ts = sorted(ep)
    return np.array([ep[t] for t in ts[:NREL]], float) if len(ts) >= NREL else None


def _detr(x):
    t = np.arange(len(x))
    return x - np.polyval(np.polyfit(t, x, 2), t)


def mi(m):
    d = json.load(open(os.path.join(SAMPLES, m)))
    return {(e['gesture'], e['window_index'], e['rep']): os.path.join(SAMPLES, e['rtcm']) for e in d['entries']}


def meta_los_elev(rtcm):
    m = json.load(open(rtcm.replace('.rtcm', '.meta.json')))
    los = {k: np.array(v['los_enu'], float) for k, v in m['satellites'].items() if k.startswith('GPS_')}
    el = {k: v['elev_deg'] for k, v in m['satellites'].items() if k.startswith('GPS_')}
    return los, el


def build(rtcm):
    """Return SD dict, CMR dict (per-sat), CM series, and common-mode energy frac."""
    ph = parse_rawx_ph(rtcm)[0]
    los, el = meta_los_elev(rtcm)
    clean = [k for k in clean_locktime(*parse_rawx_ph(rtcm)) if k.startswith('GPS_') and k in los]
    # full-length only
    rels = {k: _rel(ph, k) for k in clean}
    clean = [k for k in clean if rels[k] is not None]
    if len(clean) < 5:
        return None
    ref = max(clean, key=lambda k: el.get(k, -91))
    perdetr = {k: _detr(rels[k]) for k in clean}
    # SD (current pipeline)
    SD = {k: _detr(rels[k] - rels[ref]) for k in clean if k != ref}
    # CM = across-sat mean of per-sat-detrended phase
    CM = np.mean(np.vstack([perdetr[k] for k in clean]), axis=0)
    # clock-separated recovery
    E = np.vstack([los[k] for k in clean])            # n x 3
    A = np.hstack([E, np.ones((len(clean), 1))])      # n x 4
    PHI = np.vstack([perdetr[k] for k in clean])      # n x T
    X = np.linalg.lstsq(A, PHI, rcond=None)[0]        # 4 x T
    d = X[:3]                                         # 3 x T  (trajectory, clock removed)
    Shat = E @ d                                      # n x T  (per-sat gesture, common-mode kept)
    CMR = {clean[i]: Shat[i] for i in range(len(clean))}
    # common-mode energy fraction of the per-sat signal (what SD discards)
    cm_frac = len(clean) * np.sum(CM ** 2) / np.sum(PHI ** 2)
    return SD, CMR, CM, cm_frac


def cm_corr(cmA, cmB, lagA, lagB):
    a, b = _z(_seg(cmA, lagA)), _z(_seg(cmB, lagB))
    return float(np.mean(a * b)) if a.std() and b.std() else None


d14, d15 = mi('ref_day1_manifest.json'), mi('repeat_day2_manifest.json')

def alpha_for(pairs_caps, cross_caps=None):
    """pairs_caps: list of rtcm -> all within-group pairs. cross_caps set -> cross pairs (null)."""
    built = {c: build(c) for c in set(pairs_caps + (cross_caps or []))}
    built = {c: b for c, b in built.items() if b is not None}
    def grp(caps):
        return [c for c in caps if c in built]
    G = grp(pairs_caps)
    # align each observable within the group
    def lags(kind):
        if kind == 'CM':
            envs = [built[c][2] for c in G]
        else:
            idx = {'SD': 0, 'CMR': 1}[kind]
            envs = [envelope(built[c][idx], NREL) for c in G]
        return dict(zip(G, align_group(envs)))
    LSD, LCMR, LCM = lags('SD'), lags('CMR'), lags('CM')
    out = defaultdict(list)
    pairset = ([(G[i], G[j]) for i in range(len(G)) for j in range(i+1, len(G))]
               if cross_caps is None
               else [(a, b) for a in grp(pairs_caps) for b in grp(cross_caps)])
    if cross_caps is not None:
        Lc = {'SD': None, 'CMR': None, 'CM': None}
        # align cross group on its own
        Gc = grp(cross_caps)
        LSD2 = dict(zip(Gc, align_group([envelope(built[c][0], NREL) for c in Gc])))
        LCMR2 = dict(zip(Gc, align_group([envelope(built[c][1], NREL) for c in Gc])))
        LCM2 = dict(zip(Gc, align_group([built[c][2] for c in Gc])))
    for a, b in pairset:
        Lb_sd = LSD if cross_caps is None else LSD2
        Lb_cmr = LCMR if cross_caps is None else LCMR2
        Lb_cm = LCM if cross_caps is None else LCM2
        sats = [k for k in built[a][0] if k in built[b][0]]
        if sats:
            v = aligned_corr(built[a][0], built[b][0], LSD[a], Lb_sd[b], sats)
            if v is not None: out['SD'].append(v)
        sats = [k for k in built[a][1] if k in built[b][1]]
        if sats:
            v = aligned_corr(built[a][1], built[b][1], LCMR[a], Lb_cmr[b], sats)
            if v is not None: out['CMR'].append(v)
        v = cm_corr(built[a][2], built[b][2], LCM[a], Lb_cm[b])
        if v is not None: out['CM'].append(v)
    return out, [built[c][3] for c in G]


agg = defaultdict(lambda: defaultdict(list))
cmfrac = []
for g in ('push', 'star'):
    for w in range(4):
        caps = [d14[(g, w, r)] for r in range(1, 7) if (g, w, r) in d14] + \
               [d15[(g, w, r)] for r in range(1, 7) if (g, w, r) in d15]
        out, fr = alpha_for(caps)
        for k in ('SD', 'CMR', 'CM'):
            agg[g][k] += out[k]
        cmfrac += fr

# null: push vs star, matched window
nullagg = defaultdict(list)
for w in range(4):
    cp = [d14[('push', w, r)] for r in range(1, 7) if ('push', w, r) in d14] + \
         [d15[('push', w, r)] for r in range(1, 7) if ('push', w, r) in d15]
    cs = [d14[('star', w, r)] for r in range(1, 7) if ('star', w, r) in d14] + \
         [d15[('star', w, r)] for r in range(1, 7) if ('star', w, r) in d15]
    out, _ = alpha_for(cp, cross_caps=cs)
    for k in ('SD', 'CMR', 'CM'):
        nullagg[k] += out[k]

print("Reproducibility (within-window, onset-aligned) by observable:\n")
print(f"  {'observable':6}{'push α':>9}{'star α':>9}{'null':>9}")
labels = {'SD': 'SD', 'CMR': 'CMR', 'CM': 'CM'}
for k in ('SD', 'CM', 'CMR'):
    p = np.median(agg['push'][k]); s = np.median(agg['star'][k]); n = np.median(nullagg[k])
    print(f"  {labels[k]:6}{p:>9.3f}{s:>9.3f}{n:>9.3f}")
print(f"\n  common-mode energy fraction of per-sat signal (median): {np.median(cmfrac):.2f}")
print("  (fraction of the raw per-satellite signal that is common across sats -> discarded by SD)")
