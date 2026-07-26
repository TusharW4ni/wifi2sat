#!/usr/bin/env python3
"""
onset_align.py -- remove free-hand gesture-onset jitter before comparison.

Free-hand, the gesture lands at a different instant in each 12 s recording
(measured jitter ~1-1.5 s). Sample-for-sample ("zero-lag") comparison then lines
a rep's gesture up against another rep's baseline, so the correlation collapses
to noise even when the gesture SHAPES agree -- this is the "alpha ~= 0" artifact
in README.md "Current status".

The hand moves once, so the timing offset is a SINGLE scalar per capture, shared
by every satellite (the per-satellite sign/shape differ via g_i, but the onset is
common). We recover it from the across-satellite motion-energy envelope
    E(t) = sqrt(mean_i s_i(t)^2)        s_i = single-diff + detrend (metres)
which is a positive transient at the gesture time regardless of per-sat sign.

Estimation is iterative template alignment ("Woody averaging"): align each
envelope to the pooled group template, rebuild the template, repeat. This pools
SNR across reps, so it locks onto the common onset even when a single capture's
envelope is noisy -- and, crucially, each capture's onset is estimated against
the GROUP, never against the specific partner it will later be correlated with.

Fold-in point: extract_signal_v2 -- align each capture to onset=0 (against a
stored per-gesture template) before extracting M / features, so every downstream
statistic sees time-aligned gestures.
"""
import numpy as np

# evaluation geometry on the 10 Hz relative grid (indices from capture start)
BASE = 20     # window start  = 2.0 s
LEN = 80      # window length = 8.0 s  -> covers 2.0 .. 10.0 s
MAXLAG = 18   # +-1.8 s onset search


def _z(a):
    a = a - a.mean()
    s = a.std()
    return a / s if s > 1e-12 else a * 0.0


def _seg(x, lag, base=BASE, L=LEN):
    """Length-L slice of x starting at base+lag (integer sample shift)."""
    return x[base + lag: base + lag + L]


def envelope(sd_by_sat, n):
    """Across-satellite motion-energy envelope from signed single-diff signals."""
    M = np.vstack([sd_by_sat[s][:n] for s in sd_by_sat])
    return np.sqrt(np.mean(M ** 2, axis=0))


def align_group(envs, maxlag=MAXLAG, iters=10, base=BASE, L=LEN):
    """Iterative template alignment. Returns an integer onset lag per envelope
    (median-centred so there is no global drift). envs: list of 1-D arrays.

    base/L size the evaluation window; defaults suit 120-epoch (RAWX) captures.
    For shorter captures (MSM ~115-118) pass a window that fits -- the search
    needs base >= maxlag and base + maxlag + L <= len(envelope)."""
    lags = [0] * len(envs)
    for _ in range(iters):
        tmpl = _z(np.mean([_z(_seg(e, lags[i], base, L)) for i, e in enumerate(envs)], axis=0))
        new = []
        for e in envs:
            best, bl = -2.0, 0
            for lag in range(-maxlag, maxlag + 1):
                c = float(np.mean(_z(_seg(e, lag, base, L)) * tmpl))
                if c > best:
                    best, bl = c, lag
            new.append(bl)
        # re-centre to kill global drift, then clamp so no lag leaves the search
        # band (an out-of-band lag would make _seg slice out of bounds -> ragged)
        med = int(np.median(new))
        new = [max(-maxlag, min(maxlag, x - med)) for x in new]
        if new == lags:
            break
        lags = new
    return lags


def aligned_corr(sdA, sdB, lagA, lagB, sats):
    """Mean over shared sats of the zero-lag correlation of two captures'
    signed single-diff signals, each pre-shifted by its own onset lag."""
    cs = []
    for s in sats:
        if s in sdA and s in sdB:
            a, b = _z(_seg(sdA[s], lagA)), _z(_seg(sdB[s], lagB))
            if a.std() and b.std() and len(a) == len(b):
                cs.append(float(np.mean(a * b)))
    return float(np.mean(cs)) if cs else None
