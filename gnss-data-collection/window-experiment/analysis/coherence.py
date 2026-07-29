#!/usr/bin/env python3
"""
coherence.py -- Phase 3 (issue #5): geometry / window coherence. THE HEADLINE.

Does gesture-classification accuracy degrade as satellite GEOMETRY decorrelates?
Arm 1 (this file): "different geometry, same day" — train on one window, test on
another within the same session; accuracy vs window separation (a proxy for
sidereal/geometry drift, same hardware). Run PER CHANNEL, because Phase 2 showed
the discriminative signal is CN0 *amplitude* (geometry-invariant), not carrier
phase — so the interpretation differs by channel:
  - CN0 accuracy FLAT vs drift  -> proximity/amplitude sensing (NOT the geometry thesis)
  - push-SD accuracy DECAYS vs drift (tracking κ) -> the geometry mechanism (but SD
    is marginal per Phase 1, so limited power)

Cross-window features use the satellites common to each (train, test) window pair
(15-min windows mostly overlap), onset-aligned within each window. Diagonal
(train==test) is skipped (that's the Phase-2 within-window baseline).

Usage:
  uv run window-experiment/analysis/coherence.py c1.1_day1        # per-channel ramp
  uv run window-experiment/analysis/coherence.py --best           # standard set -> results/
"""
import os
import sys
import json
import argparse
from collections import defaultdict

import numpy as np

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _d in ("lib", "analysis"):
    sys.path.insert(0, os.path.join(_ROOT, _d))
RESULTS = os.path.join(_ROOT, "results")

import dataset as ds
from alpha_study import build_channels, GESTURES
from separability import _stats
from onset_align import align_group, BASE, LEN, MAXLAG

from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.svm import SVC

CHANNELS = {"CN0": ("cn0",), "SD": ("sd",)}


def _build(session, gestures):
    recs = [r for r in ds.load_session(session) if r["gesture"] in gestures]
    built = {}
    for r in recs:
        b = build_channels(r)
        if b is not None and b["CN0cm"] is not None:
            built[r["rtcm_path"]] = b
    return [r for r in recs if r["rtcm_path"] in built], built


def _win(recs, w):
    return [r for r in recs if r["window"] == w]


def _win_sats(recs, built, w, key):
    caps = _win(recs, w)
    if not caps:
        return set()
    s = set(built[caps[0]["rtcm_path"]][key])
    for r in caps[1:]:
        s &= set(built[r["rtcm_path"]][key])
    return s


def _feat_window(recs, built, w, feats, sats, baseline=False):
    """Feature matrix for one window over an explicit sat list (so train/test
    windows share feature columns). Onset-aligned within the window.
    baseline=True uses the pre-onset segment [0:base] (gesture-free control)."""
    caps = _win(recs, w)
    paths = [r["rtcm_path"] for r in caps]
    Ncm = min(len(built[p]["CN0cm"]) for p in paths)
    base, L = BASE, min(LEN, Ncm - BASE - MAXLAG)
    if L >= 40:
        lags = dict(zip(paths, align_group([built[p]["CN0cm"][:Ncm] for p in paths], base=base, L=L)))
    else:
        base, L, lags = 0, Ncm, {p: 0 for p in paths}
    seg = lambda lag: (0, base) if baseline else (base + lag, L)
    X, y = [], []
    for r in caps:
        b, lag = built[r["rtcm_path"]], lags[r["rtcm_path"]]
        st, sl = seg(lag)
        feat = []
        if "cn0" in feats:
            for s in sats:
                feat += _stats(b["CN0ps"][s], st, sl)
            feat += _stats(b["CN0cm"], st, sl)
        if "sd" in feats:
            ref = max(sats, key=lambda k: b["elev"].get(k, -91))
            for s in sats:
                if s != ref:
                    feat += _stats(b["perdetr"][s] - b["perdetr"][ref], st, sl)
        X.append(feat)
        y.append(r["gesture"])
    return np.array(X), np.array(y)


def ramp(session, gestures=GESTURES, baseline=False):
    """Cross-window train→test accuracy per channel, all ordered window pairs.
    baseline=True runs the pre-onset (gesture-free) control."""
    recs, built = _build(session, gestures)
    windows = sorted({r["window"] for r in recs})
    chance = 1.0 / len(set(g for g in gestures))
    out = {"session": session, "windows": windows, "chance": chance,
           "baseline": baseline, "channels": {}}
    for chan, feats in CHANNELS.items():
        key = "CN0ps" if "cn0" in feats else "perdetr"
        pairs = []
        for wtr in windows:
            for wte in windows:
                if wtr == wte:
                    continue
                shared = sorted(_win_sats(recs, built, wtr, key) & _win_sats(recs, built, wte, key))
                if len(shared) < 3:
                    continue
                Xtr, ytr = _feat_window(recs, built, wtr, feats, shared, baseline)
                Xte, yte = _feat_window(recs, built, wte, feats, shared, baseline)
                if len(set(ytr)) < 2 or len(Xte) == 0:
                    continue
                pipe = make_pipeline(StandardScaler(), SVC(kernel="linear"))
                pipe.fit(Xtr, ytr)
                pairs.append(dict(train=wtr, test=wte, sep=abs(wtr - wte),
                                  acc=float(pipe.score(Xte, yte)),
                                  n_shared=len(shared), n_test=int(len(yte))))
        by_sep = defaultdict(list)
        for p in pairs:
            by_sep[p["sep"]].append(p["acc"])
        out["channels"][chan] = {
            "pairs": pairs,
            "by_sep": {str(s): float(np.mean(v)) for s, v in sorted(by_sep.items())},
        }
    return out


def _boot_acc_ci(correct, nboot=2000, seed=0):
    """Accuracy + 95% bootstrap CI from a boolean per-sample correctness array."""
    c = np.asarray(correct, float)
    if len(c) == 0:
        return dict(acc=float("nan"), lo=float("nan"), hi=float("nan"), n=0)
    rng = np.random.default_rng(seed)
    boot = c[rng.integers(0, len(c), size=(nboot, len(c)))].mean(axis=1)
    return dict(acc=float(c.mean()), lo=float(np.percentile(boot, 2.5)),
                hi=float(np.percentile(boot, 97.5)), n=int(len(c)))


def cross_day(train_sess, test_sess, gestures=GESTURES, baseline=False):
    """Arm 2: SAME geometry, DIFFERENT day. Train on one day's window, test on the
    other day's SAME window (sidereally aligned = same sky), per channel, with a
    bootstrap CI on the held-out day. Geometry is held fixed while time varies —
    the only design that dissociates geometry from the elapsed-time confound. The
    pre-onset baseline (baseline=True) is the control: gesture accuracy must beat
    both chance AND its own gesture-free baseline to count as real transfer."""
    otr, ote = ds.get_session(train_sess).observable, ds.get_session(test_sess).observable
    if otr != ote:
        raise ValueError(f"{train_sess}({otr}) vs {test_sess}({ote}) — won't cross MSM7/RAWX")
    recs_tr, built_tr = _build(train_sess, gestures)
    recs_te, built_te = _build(test_sess, gestures)
    wins = sorted({r["window"] for r in recs_tr} & {r["window"] for r in recs_te})
    out = {"train": train_sess, "test": test_sess, "observable": otr, "baseline": baseline,
           "chance": 1.0 / len(set(gestures)), "windows": {}}
    for w in wins:
        cell = {}
        for chan, feats in CHANNELS.items():
            key = "CN0ps" if "cn0" in feats else "perdetr"
            shared = sorted(_win_sats(recs_tr, built_tr, w, key) & _win_sats(recs_te, built_te, w, key))
            if len(shared) < 3:
                continue
            Xtr, ytr = _feat_window(recs_tr, built_tr, w, feats, shared, baseline)
            Xte, yte = _feat_window(recs_te, built_te, w, feats, shared, baseline)
            if len(set(ytr)) < 2 or len(yte) == 0:
                continue
            pipe = make_pipeline(StandardScaler(), SVC(kernel="linear"))
            pipe.fit(Xtr, ytr)
            cell[chan] = dict(**_boot_acc_ci(pipe.predict(Xte) == yte), n_shared=len(shared))
        if cell:
            out["windows"][str(w)] = cell
    return out


def _print_crossday(out):
    tag = " [PRE-ONSET BASELINE]" if out.get("baseline") else ""
    print(f"\nArm 2 cross-day transfer{tag} — train {out['train']} → test {out['test']} "
          f"({out['observable']}, chance {out['chance']:.0%})")
    print(f"  {'window':7}{'channel':8}{'test acc':>10}{'95% CI':>16}{'n':>5}")
    for w, cell in sorted(out["windows"].items()):
        for chan, d in cell.items():
            print(f"  W{w:<6}{chan:8}{d['acc']:>10.0%}   [{d['lo']:.0%}, {d['hi']:.0%}]{d['n']:>5}")


def _print(out):
    tag = " [PRE-ONSET BASELINE control]" if out.get("baseline") else ""
    print(f"\nPhase 3 arm-1 coherence ramp — {out['session']}{tag}  "
          f"(cross-window train→test, chance {out['chance']:.0%})")
    seps = sorted({int(s) for ch in out["channels"].values() for s in ch["by_sep"]})
    print(f"  {'channel':7}" + "".join(f"{'sep '+str(s):>9}" for s in seps))
    for chan, d in out["channels"].items():
        row = f"  {chan:7}"
        for s in seps:
            v = d["by_sep"].get(str(s))
            row += f"{(f'{v:.0%}' if v is not None else '-'):>9}"
        print(row)
    print("  (mean cross-window test accuracy by |train−test window| = geometry-drift proxy)")


def main():
    ap = argparse.ArgumentParser(description="Phase 3: window coherence (arm 1) + cross-day transfer (arm 2)")
    ap.add_argument("session", nargs="?", default="c1.1_day1")
    ap.add_argument("--best", action="store_true", help="arm 1 ramp: c1.1_day1 (+ c3.2_day1) -> results/coherence_ramp.json")
    ap.add_argument("--crossday", action="store_true",
                    help="arm 2: same-geometry/different-day transfer + baseline -> results/coherence_crossday.json")
    ap.add_argument("--baseline", action="store_true",
                    help="pre-onset (gesture-free) control: reproduces the decay? -> time/env confound")
    a = ap.parse_args()
    if a.crossday:
        # (train, test, gestures): c3.2 day1->day2 (5-class, MSM); ref->repeat (push+star, RAWX)
        jobs = [("c3.2_day1", "c3.2_day2", GESTURES),
                ("ref_day1", "repeat_day2", ("push", "star"))]
        out = []
        for tr, te, gests in jobs:
            for bl in (False, True):          # gesture + pre-onset baseline control
                try:
                    r = cross_day(tr, te, gestures=gests, baseline=bl)
                    out.append(r)
                    _print_crossday(r)
                except Exception as e:
                    print(f"skip {tr}->{te} baseline={bl}: {e}")
        os.makedirs(RESULTS, exist_ok=True)
        json.dump(out, open(os.path.join(RESULTS, "coherence_crossday.json"), "w"), indent=2)
        print(f"\nwrote {os.path.join(RESULTS, 'coherence_crossday.json')}")
        return
    if a.best:
        out = []
        for s in ("c1.1_day1", "c3.2_day1"):
            for bl in (False, True):          # gesture window + pre-onset control side by side
                try:
                    r = ramp(s, baseline=bl)
                    out.append(r)
                    _print(r)
                except Exception as e:
                    print(f"skip {s} baseline={bl}: {e}")
        os.makedirs(RESULTS, exist_ok=True)
        json.dump(out, open(os.path.join(RESULTS, "coherence_ramp.json"), "w"), indent=2)
        print(f"\nwrote {os.path.join(RESULTS, 'coherence_ramp.json')}")
    else:
        _print(ramp(a.session, baseline=a.baseline))


if __name__ == "__main__":
    main()
