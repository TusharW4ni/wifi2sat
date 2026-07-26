#!/usr/bin/env python3
"""
separability.py -- Phase 2 (issue #4): within-geometry gesture separability.

The first classification test. On the channels that passed Phase 1's gate
(CN0 primary, push-SD secondary), can gestures be told apart WITHIN A SINGLE
WINDOW (matched geometry — the easiest case)? If not even here, the geometry
question (Phase 3) is moot.

Features (per capture, within one session×window so the sat set + geometry are
fixed): onset-aligned summary stats [std, peak-to-peak, energy] of the detrended
CN0 of each common clean satellite, plus the same for the across-sat CN0 mean.
Optionally append push-SD stats. Onset lag from the CN0-common envelope.

Models: LDA / kNN / linear-SVM (standardized). Repeated stratified CV +
permutation null. Chance = 1/#classes (20% for 5-class, 50% for push-vs-star).

Usage:
  uv run window-experiment/analysis/separability.py c1.1_day1 0        # 5-class, window 0
  uv run window-experiment/analysis/separability.py ref_day1 0 --two   # push vs star
  uv run window-experiment/analysis/separability.py --best             # standard best-case set -> results/
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
from onset_align import align_group, _seg, BASE, LEN, MAXLAG

from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.discriminant_analysis import LinearDiscriminantAnalysis
from sklearn.neighbors import KNeighborsClassifier
from sklearn.svm import SVC
from sklearn.model_selection import RepeatedStratifiedKFold, cross_val_score, permutation_test_score


def _stats(x, lag, base, L):
    """Onset-aligned segment summary stats: std, peak-to-peak, energy."""
    s = _seg(x, lag, base, L)
    return [float(np.std(s)), float(np.ptp(s)), float(np.mean(s ** 2))]


def featurize(session, window, gestures=GESTURES, feats=("cn0",)):
    """Feature matrix X, labels y for one (session, window). Features are
    onset-aligned CN0 stats over the window's common clean-sat set."""
    recs = [r for r in ds.load_session(session)
            if r["window"] == window and r["gesture"] in gestures]
    built = {}
    for r in recs:
        b = build_channels(r)
        if b is not None and b["CN0cm"] is not None:
            built[r["rtcm_path"]] = b
    caps = [r for r in recs if r["rtcm_path"] in built]
    if len(caps) < 4:
        raise ValueError(f"{session} W{window}: only {len(caps)} usable captures")
    paths = [r["rtcm_path"] for r in caps]

    def _common(key):
        s = set(built[paths[0]][key])
        for p in paths[1:]:
            s &= set(built[p][key])
        return sorted(s)
    common = _common("CN0ps") if "cn0" in feats else []
    sdcommon = _common("perdetr") if "sd" in feats else []

    # onset lag from the CN0-common series (the strongest, most reproducible channel)
    Ncm = min(len(built[p]["CN0cm"]) for p in paths)
    base, L = BASE, min(LEN, Ncm - BASE - MAXLAG)
    if L >= 40:
        lags = dict(zip(paths, align_group([built[p]["CN0cm"][:Ncm] for p in paths], base=base, L=L)))
    else:
        base, L, lags = 0, Ncm, {p: 0 for p in paths}

    X, y = [], []
    for r in caps:
        b, lag = built[r["rtcm_path"]], lags[r["rtcm_path"]]
        feat = []
        if "cn0" in feats:
            for sat in common:
                feat += _stats(b["CN0ps"][sat], lag, base, L)
            feat += _stats(b["CN0cm"], lag, base, L)
        if "sd" in feats and sdcommon:
            ref = max(sdcommon, key=lambda k: b["elev"].get(k, -91))
            for sat in sdcommon:
                if sat != ref:
                    feat += _stats(b["perdetr"][sat] - b["perdetr"][ref], lag, base, L)
        X.append(feat)
        y.append(r["gesture"])
    return np.array(X), np.array(y), dict(feats=list(feats), n_common_cn0=len(common),
                                          n_common_sd=len(sdcommon), n_feat=len(X[0]))


def classify(X, y, n_perm=200, seed=0):
    models = {"LDA": LinearDiscriminantAnalysis(),
              "kNN": KNeighborsClassifier(n_neighbors=3),
              "linSVM": SVC(kernel="linear", C=1.0)}
    n_per_class = min(np.bincount([sorted(set(y)).index(v) for v in y]))
    k = int(min(5, n_per_class))
    cv = RepeatedStratifiedKFold(n_splits=k, n_repeats=20, random_state=seed)
    chance = 1.0 / len(set(y))
    out = {"n": len(y), "classes": [str(c) for c in sorted(set(y))],
           "chance": chance, "cv_splits": k, "models": {}}
    for name, m in models.items():
        pipe = make_pipeline(StandardScaler(), m)
        scores = cross_val_score(pipe, X, y, cv=cv)
        _, _, p = permutation_test_score(pipe, X, y, cv=cv, n_permutations=n_perm, random_state=seed)
        out["models"][name] = dict(acc=float(scores.mean()), lo=float(np.percentile(scores, 2.5)),
                                   hi=float(np.percentile(scores, 97.5)), p=float(p))
    return out


def confusion(X, y, seed=0):
    """Leave-one-out confusion for the best-CV model (LDA), labels sorted."""
    from sklearn.model_selection import cross_val_predict, LeaveOneOut
    labels = [str(c) for c in sorted(set(y))]
    pipe = make_pipeline(StandardScaler(), LinearDiscriminantAnalysis())
    pred = cross_val_predict(pipe, X, y, cv=LeaveOneOut())
    M = np.zeros((len(labels), len(labels)), int)
    for t, p in zip(y, pred):
        M[labels.index(t)][labels.index(p)] += 1
    return labels, M


def run(session, window, two=False):
    gestures = ("push", "star") if two else GESTURES
    X, y, info = featurize(session, window, gestures=gestures,
                           feats=("cn0", "sd") if two else ("cn0",))
    res = classify(X, y)
    labels, M = confusion(X, y)
    print(f"\n{session} W{window}  ({len(res['classes'])}-class: {res['classes']})  "
          f"n={res['n']}, features={info['n_feat']} ({info['n_common_cn0']} common CN0 sats), "
          f"chance={res['chance']:.0%}")
    print(f"  {'model':8}{'acc':>8}{'95% CI':>16}{'perm-p':>9}")
    for name, d in res["models"].items():
        print(f"  {name:8}{d['acc']:>8.0%}   [{d['lo']:.0%}, {d['hi']:.0%}]{d['p']:>9.3f}")
    print(f"  confusion (rows=true, cols=pred, LDA LOO): {labels}")
    for i, lab in enumerate(labels):
        print(f"    {lab:9}{M[i]}")
    return dict(session=session, window=window, **res,
                confusion=dict(labels=labels, matrix=M.tolist()), features=info)


def ablate(session, window, gestures=GESTURES):
    """SD-vs-CN0 feature ablation: is the classifier riding on amplitude (CN0) or
    the geometry-dependent phase (SD)? linSVM accuracy per feature set."""
    out = {}
    for name, feats in (("CN0-only", ("cn0",)), ("SD-only", ("sd",)), ("CN0+SD", ("cn0", "sd"))):
        try:
            X, y, info = featurize(session, window, gestures=gestures, feats=feats)
            r = classify(X, y, n_perm=100)
            m = r["models"]["linSVM"]
            out[name] = dict(acc=m["acc"], lo=m["lo"], hi=m["hi"], p=m["p"],
                             n_feat=info["n_feat"], chance=r["chance"])
        except Exception as e:
            out[name] = dict(error=str(e))
    return out


def main():
    ap = argparse.ArgumentParser(description="Phase 2 within-window gesture separability")
    ap.add_argument("session", nargs="?", default="c1.1_day1")
    ap.add_argument("window", nargs="?", type=int, default=0)
    ap.add_argument("--two", action="store_true", help="push-vs-star (2-class) + append SD features")
    ap.add_argument("--best", action="store_true", help="standard best-case set -> results/separability.json")
    ap.add_argument("--ablate", action="store_true",
                    help="SD-vs-CN0 feature ablation on c1.1 W0/W1 -> results/separability_ablation.json")
    a = ap.parse_args()
    if a.ablate:
        out = {}
        for s, w in (("c1.1_day1", 0), ("c1.1_day1", 1)):
            res = ablate(s, w)
            out[f"{s}_W{w}"] = res
            print(f"\n{s} W{w}  (5-class, chance 20%) -- linSVM accuracy by feature set:")
            print(f"  {'features':10}{'acc':>7}{'95% CI':>15}{'perm-p':>9}{'n_feat':>8}")
            for name, d in res.items():
                if "error" in d:
                    print(f"  {name:10} error: {d['error']}")
                else:
                    print(f"  {name:10}{d['acc']:>7.0%}   [{d['lo']:.0%}, {d['hi']:.0%}]{d['p']:>9.3f}{d['n_feat']:>8}")
        os.makedirs(RESULTS, exist_ok=True)
        json.dump(out, open(os.path.join(RESULTS, "separability_ablation.json"), "w"), indent=2)
        print(f"\nwrote {os.path.join(RESULTS, 'separability_ablation.json')}")
        return
    if a.best:
        jobs = [("c1.1_day1", 0, False), ("c1.1_day1", 1, False),
                ("ref_day1", 0, True), ("repeat_day2", 0, True)]
        out = []
        for s, w, two in jobs:
            try:
                out.append(run(s, w, two=two))
            except Exception as e:
                print(f"skip {s} W{w}: {e}")
        os.makedirs(RESULTS, exist_ok=True)
        json.dump(out, open(os.path.join(RESULTS, "separability.json"), "w"), indent=2)
        print(f"\nwrote {os.path.join(RESULTS, 'separability.json')}")
    else:
        run(a.session, a.window, two=a.two)


if __name__ == "__main__":
    main()
