#!/usr/bin/env python3
"""
Signal extraction for GNSS carrier-phase gesture sensing  (v2).

Rewritten after validating on real captures. Three things that the field data
forced and that the first version got wrong:

  1. CLEAN-SAT FILTER MUST BE INSIDE EXTRACTION.  A single satellite with a
     cycle slip (e.g. a ~300 km jump when its rough range crosses the 1 ms
     boundary, because DF397 is not used) detonates the common-mode signal --
     a 40,000 mm artifact was observed. The same >50 m slip gate the capture
     uses for ref selection has to gate the extraction set too.

  2. DO NOT HARDCODE THE GESTURE WINDOW.  Real gestures land at variable times
     (human reaction lag after "GO!" + serial latency); Push&Pull energy was
     seen at ~5-8.5 s, not the assumed 3-6 s. The active window is DETECTED
     from the common-mode envelope, not assumed. The geometric detrend is done
     over the FULL window (the mm-scale gesture is negligible against the
     km-scale range trend, so it does not bias the fit) -- which also removes
     the circular dependency of needing the window before detrending.

  3. GEOMETRY COMES FROM THE STREAM OR THE SIDECAR.  NAV-SAT (az/el) is present
     in every .rtcm, so geometry is recoverable even for old captures with no
     .meta.json. If a sidecar exists it is preferred (already averaged).

The differenced observable is psi_i = (e_i - e_ref) . d(t), so the geometry
vector that pairs with signal s_i in the Part-2 / M-matrix estimator is
    g_i = e_i - e_ref     (returned in `geom`).
"""
import sys
import json
import os
from collections import defaultdict

import numpy as np
from pyubx2 import UBXReader, UBX_PROTOCOL, NMEA_PROTOCOL, RTCM3_PROTOCOL

SPEED_OF_LIGHT = 299_792_458.0
MS_TO_METERS = SPEED_OF_LIGHT / 1000.0
CONSTELLATION_MAP = {"1077": "GPS", "1127": "BDS"}
ACCEPTED_SIGNALS = {"1077": {"1C"}, "1127": {"2I", "1X"}}
NAV_GNSS_MAP = {0: "GPS", 3: "BDS"}

CYCLE_SLIP_THRESH = 50.0   # meters; same gate as capture
TARGET_EPOCHS = 100
FS = 10


def _key(constellation, prn):
    return f"{constellation}_{int(prn):03d}"


def _los_enu(el_deg, az_deg):
    el, az = np.deg2rad(el_deg), np.deg2rad(az_deg)
    return np.array([np.cos(el) * np.sin(az),
                     np.cos(el) * np.cos(az),
                     np.sin(el)])


def load_sample(rtcm_path, meta_path="auto"):
    """Parse a saved capture. Returns (phases, los_enu_by_sat, elevations).

    phases:      {sat_key: [carrier phase in meters per epoch]}
    los_enu:     {sat_key: np.array([e,n,u])}  unit LOS vector
    elevations:  {sat_key: deg}
    Geometry is read from the .meta.json sidecar if present, else recovered
    from the NAV-SAT messages embedded in the raw stream.
    """
    if meta_path == "auto":
        cand = rtcm_path.rsplit(".", 1)[0] + ".meta.json"
        meta_path = cand if os.path.exists(cand) else None

    phases = defaultdict(list)
    azel = defaultdict(lambda: {"el": [], "az": []})

    with open(rtcm_path, "rb") as fh:
        ubr = UBXReader(fh, protfilter=UBX_PROTOCOL | NMEA_PROTOCOL | RTCM3_PROTOCOL)
        for _raw, parsed in ubr:
            if parsed is None:
                continue
            mid = parsed.identity

            if mid == "NAV-SAT" and meta_path is None:
                for i in range(1, getattr(parsed, "numSvs", 0) + 1):
                    g = getattr(parsed, f"gnssId_{i:02d}", -1)
                    s = getattr(parsed, f"svId_{i:02d}", 0)
                    e = getattr(parsed, f"elev_{i:02d}", None)
                    a = getattr(parsed, f"azim_{i:02d}", None)
                    c = NAV_GNSS_MAP.get(g)
                    if c and e is not None and a is not None and -90 <= e <= 90:
                        azel[_key(c, s)]["el"].append(float(e))
                        azel[_key(c, s)]["az"].append(float(a))

            elif mid in CONSTELLATION_MAP:
                accepted = ACCEPTED_SIGNALS[mid]
                constellation = CONSTELLATION_MAP[mid]
                n_sat = getattr(parsed, "NSat", 0)
                n_cell = getattr(parsed, "NCell", 0)
                if not n_sat or not n_cell:
                    continue
                rough = {}
                for s in range(1, n_sat + 1):
                    prn = getattr(parsed, f"PRN_{s:02d}", None)
                    rr = getattr(parsed, f"DF398_{s:02d}", None)
                    if prn is not None and rr is not None:
                        rough[prn] = rr
                for c in range(1, n_cell + 1):
                    prn = getattr(parsed, f"CELLPRN_{c:02d}", None)
                    sig = getattr(parsed, f"CELLSIG_{c:02d}", None)
                    fpr = getattr(parsed, f"DF406_{c:02d}", None)
                    if prn is None or fpr is None or prn not in rough or sig not in accepted:
                        continue
                    phases[_key(constellation, prn)].append((rough[prn] + fpr) * MS_TO_METERS)

    los, elev = {}, {}
    if meta_path is not None:
        with open(meta_path) as f:
            meta = json.load(f)
        for k, v in meta.get("satellites", {}).items():
            los[k] = np.array(v["los_enu"], float)
            elev[k] = v["elev_deg"]
    else:
        for k, v in azel.items():
            if not v["el"]:
                continue
            e = float(np.mean(v["el"]))
            az = np.deg2rad(v["az"])
            a = float(np.rad2deg(np.arctan2(np.sin(az).mean(), np.cos(az).mean())) % 360)
            los[k] = _los_enu(e, a)
            elev[k] = e

    return dict(phases), los, elev


def _clean_sats(phases, n=TARGET_EPOCHS):
    """Full-length sats with no cycle slip over the first n epochs."""
    out = []
    for k, v in phases.items():
        if len(v) < n:
            continue
        arr = np.asarray(v[:n], float)
        if np.max(np.abs(np.diff(arr))) <= CYCLE_SLIP_THRESH:
            out.append(k)
    return out


def extract_signal(phases, ref_key=None, elevations=None, los=None,
                   fs=FS, n_epochs=TARGET_EPOCHS, trend_deg=2):
    """Single-difference + full-window detrend on the CLEAN sat set.

    ref_key:    reference sat. If None, the highest-elevation clean sat is used
                (needs `elevations`). For cross-session work, pass the SAME
                ref_key every session so e_ref repeats.
    returns dict:
        signals:  {sat_key: s_i}  zero-mean gesture signal (m), len N
        t:        time axis (s), len N
        envelope: common-mode RMS across sats (m), len N
        ref:      ref sat key used
        geom:     {sat_key: g_i = e_i - e_ref}  (only if `los` given)
    """
    clean = _clean_sats(phases, n_epochs)
    if len(clean) < 2:
        raise ValueError(f"need >=2 clean sats, got {len(clean)}")

    if ref_key is None:
        if elevations is None:
            raise ValueError("pass ref_key or elevations to pick a reference")
        ref_key = max(clean, key=lambda k: elevations.get(k, -91))
    elif ref_key not in clean:
        raise ValueError(f"ref {ref_key} is not a clean full-length sat this session")

    N = min(n_epochs, min(len(phases[k]) for k in clean))
    t = np.arange(N) / fs
    refa = np.asarray(phases[ref_key][:N], float)

    signals = {}
    for k in clean:
        if k == ref_key:
            continue
        sd = np.asarray(phases[k][:N], float) - refa     # kills receiver clock
        c = np.polyfit(t, sd, trend_deg)                 # kills geometric range trend
        signals[k] = sd - np.polyval(c, t)               # gesture residual

    S = np.vstack([signals[k] for k in signals])
    envelope = np.sqrt((S ** 2).mean(axis=0))

    out = {"signals": signals, "t": t, "envelope": envelope, "ref": ref_key}
    if los is not None and ref_key in los:
        out["geom"] = {k: (los[k] - los[ref_key]) for k in signals if k in los}
    return out


def detect_window(envelope, t, k=4.0, min_dur=0.5, pad=0.3):
    """Largest contiguous span of the common-mode envelope above a robust
    threshold. Returns (t_start, t_end) in seconds, or None.

    Heuristic, not sacred -- tune k for your SNR. For the M-matrix you can skip
    a hard window entirely and weight by (envelope - baseline)^2 instead.
    """
    base = np.percentile(envelope, 20)
    mad = np.median(np.abs(envelope - np.median(envelope))) + 1e-12
    thr = base + k * mad
    active = envelope > thr

    runs, i, n = [], 0, len(active)
    while i < n:
        if active[i]:
            j = i
            while j < n and active[j]:
                j += 1
            runs.append((i, j))
            i = j
        else:
            i += 1
    if not runs:
        return None
    i0, j0 = max(runs, key=lambda r: r[1] - r[0])
    t0 = max(t[0], t[i0] - pad)
    t1 = min(t[-1], t[j0 - 1] + pad)
    return (t0, t1) if (t1 - t0) >= min_dur else None


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python extract_signal_v2.py <sample.rtcm>")
        sys.exit(1)
    phases, los, elev = load_sample(sys.argv[1])
    res = extract_signal(phases, elevations=elev, los=los)
    win = detect_window(res["envelope"], res["t"])
    print(f"ref {res['ref']} @ {elev[res['ref']]:.0f} deg   clean sats: {len(res['signals'])}")
    print(f"detected gesture window: "
          f"{('%.1f-%.1fs' % win) if win else 'none'}")
    print(f"{'sat':>9} {'elev':>5} {'pk-pk(mm)':>9}   g_i = e_i - e_ref (ENU)")
    for k in sorted(res["signals"]):
        s = res["signals"][k]
        g = res.get("geom", {}).get(k)
        gtxt = ("[" + ", ".join(f"{x:+.3f}" for x in g) + "]") if g is not None else "(no geom)"
        print(f"{k:>9} {elev.get(k,-91):5.0f} {1000*np.ptp(s):9.2f}   {gtxt}")
