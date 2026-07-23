#!/usr/bin/env python3
"""
field_monitor.py  --  live GNSS health dashboard (RAWX edition).

Now that RXM-RAWX is the primary observable, the gate is built on RAWX, not the
MSM reconstruction (whose rough/fine recombination injected false slips and
starved the clean-sat count to ~2). Clean satellites here come from cpMes
continuity + locktime/cpValid -- real lock state, not a 50 m heuristic -- so the
clean count should reflect what the analysis will actually get. MSM (1077/1127)
and NAV-SAT are shown as secondary: MSM is kept for recovery/calibration,
NAV-SAT supplies az/el for the elevation mask.

  Live:    python field_monitor.py [--port ...] [--refresh 1.0] [--no-color]
  Replay:  python field_monitor.py --replay samples/foo.rtcm
"""
import os
import sys
import time
import argparse
from io import BytesIO
from collections import defaultdict, deque

import numpy as np
import serial
from pyubx2 import UBXReader, UBX_PROTOCOL, NMEA_PROTOCOL, RTCM3_PROTOCOL

# Make sibling code dirs importable regardless of CWD
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _d in ("lib", "capture", "analysis"):
    sys.path.insert(0, os.path.join(_ROOT, _d))

from capture_sample import PORT, BAUD, DURATION_SEC, TARGET_EPOCHS, NAV_GNSS_MAP, _key
from parse_rawx import WAVELENGTH, GNSS_NAME, DEFAULT_ACCEPT, _trkbits
try:
    from extract_signal_v2 import ELEV_MASK
except Exception:
    ELEV_MASK = 20.0

NEED_RAWX = 100      # RAWX epochs over the window (== capture)
NEED_NAV = 5
NEED_CLEAN = 2

C = {"g": "\033[1;32m", "y": "\033[1;33m", "r": "\033[1;31m",
     "b": "\033[1;34m", "d": "\033[2m", "x": "\033[0m"}
NOCOLOR = {k: "" for k in C}


def parse_health(raw_bytes):
    counts = defaultdict(int)
    rawx_ep = defaultdict(dict)      # sat -> {tkey_ms: phase_m}
    rawx_lock = defaultdict(dict)    # sat -> {tkey_ms: locktime}
    rawx_cno = defaultdict(list)
    rawx_sig = {}
    azel = defaultdict(lambda: {"el": [], "cno": []})
    ubr = UBXReader(BytesIO(raw_bytes),
                    protfilter=UBX_PROTOCOL | NMEA_PROTOCOL | RTCM3_PROTOCOL)
    try:
        for _raw, p in ubr:
            if p is None:
                continue
            mid = p.identity
            counts[mid] += 1
            if mid == "RXM-RAWX":
                tow = getattr(p, "rcvTow", None)
                if tow is None:
                    continue
                tkey = int(round(tow * 10) * 100)
                for i in range(1, getattr(p, "numMeas", 0) + 1):
                    g = getattr(p, f"gnssId_{i:02d}", None)
                    sv = getattr(p, f"svId_{i:02d}", None)
                    sg = getattr(p, f"sigId_{i:02d}", None)
                    if g is None or sv is None or sg is None:
                        continue
                    if (g, sg) not in DEFAULT_ACCEPT or (g, sg) not in WAVELENGTH:
                        continue
                    cp = getattr(p, f"cpMes_{i:02d}", 0.0)
                    _, cpValid, _, _ = _trkbits(p, i)
                    if not cpValid or cp == 0.0:
                        continue
                    k = _key(GNSS_NAME.get(g, str(g)), sv)
                    rawx_ep[k][tkey] = cp * WAVELENGTH[(g, sg)]
                    rawx_lock[k][tkey] = getattr(p, f"locktime_{i:02d}", 0)
                    c = getattr(p, f"cno_{i:02d}", None)
                    if c is not None:
                        rawx_cno[k].append(float(c))
                    rawx_sig[k] = (g, sg)
            elif mid == "NAV-SAT":
                for i in range(1, getattr(p, "numSvs", 0) + 1):
                    g = getattr(p, f"gnssId_{i:02d}", -1)
                    s = getattr(p, f"svId_{i:02d}", 0)
                    e = getattr(p, f"elev_{i:02d}", None)
                    cn = getattr(p, f"cno_{i:02d}", None)
                    c = NAV_GNSS_MAP.get(g)
                    if c and e is not None and -90 <= e <= 90:
                        kk = _key(c, s)
                        azel[kk]["el"].append(float(e))
                        if cn is not None:
                            azel[kk]["cno"].append(float(cn))
    except Exception:
        pass
    elev = {k: float(np.mean(v["el"])) for k, v in azel.items() if v["el"]}
    return counts, dict(rawx_ep), dict(rawx_lock), rawx_cno, rawx_sig, elev


def motion_rms_mm(phases_ep, sats):
    clean = [s["key"] for s in sats if s["clean"]]
    if len(clean) < 2:
        return None
    ref = max((s for s in sats if s["clean"]),
              key=lambda s: (s["el"] if s["el"] is not None else -91))["key"]
    ref_ep = phases_ep.get(ref, {})
    series = []
    for k in clean:
        if k == ref:
            continue
        ek = phases_ep.get(k, {})
        if len(set(ref_ep) & set(ek)) >= 50:
            series.append(ek)
    if not series:
        return None
    common = sorted(set(ref_ep).intersection(*[set(ek) for ek in series]))
    if len(common) < 50:
        return None
    t = (np.array(common) - common[0]) / 1000.0
    resid = []
    for ek in series:
        sd = np.array([ek[e] - ref_ep[e] for e in common], float)
        resid.append(sd - np.polyval(np.polyfit(t, sd, 2), t))
    env = np.sqrt(np.mean(np.vstack(resid) ** 2, axis=0))
    return float(np.median(env) * 1000.0)


def assess(counts, rawx_ep, rawx_lock, rawx_cno, rawx_sig, elev):
    n_rawx = counts.get("RXM-RAWX", 0)
    n_nav = counts.get("NAV-SAT", 0)
    n_1077 = counts.get("1077", 0)
    n_1127 = counts.get("1127", 0)
    sats = []
    for k, ep in rawx_ep.items():
        ts = sorted(ep)
        n = len(ts)
        lt = [rawx_lock[k][t] for t in ts]
        slip = any(lt[i] < lt[i - 1] for i in range(1, len(lt)))
        el = elev.get(k)
        cno = float(np.mean(rawx_cno[k])) if rawx_cno.get(k) else None
        clean = (n >= TARGET_EPOCHS) and (not slip)
        usable = clean and (el is not None and el >= ELEV_MASK)
        sats.append(dict(key=k, n=n, slip=slip, el=el, cno=cno, clean=clean,
                         usable=usable, sig=rawx_sig.get(k)))
    sats.sort(key=lambda s: (s["el"] if s["el"] is not None else -91), reverse=True)
    n_clean = sum(s["clean"] for s in sats)
    n_usable = sum(s["usable"] for s in sats)
    motion = motion_rms_mm(rawx_ep, sats)
    gate = (n_rawx >= NEED_RAWX and n_nav >= NEED_NAV and n_clean >= NEED_CLEAN)
    thin = gate and (n_usable <= NEED_CLEAN + 1 or n_clean <= NEED_CLEAN + 1
                     or n_rawx < NEED_RAWX + 10 or n_nav < NEED_NAV + 3)
    reasons = []
    if n_rawx < NEED_RAWX: reasons.append(f"RAWX {n_rawx}/{NEED_RAWX}")
    if n_nav < NEED_NAV: reasons.append(f"NAV {n_nav}/{NEED_NAV}")
    if n_clean < NEED_CLEAN: reasons.append(f"clean {n_clean}/{NEED_CLEAN}")
    return dict(n_rawx=n_rawx, n_nav=n_nav, n_1077=n_1077, n_1127=n_1127, sats=sats,
                n_clean=n_clean, n_usable=n_usable, gate=gate, reasons=reasons,
                thin=thin, motion=motion)


def _bar(val, need, width=12, col=C):
    f = min(1.0, val / need) if need else 1.0
    fill = int(round(f * width))
    color = col["g"] if val >= need else col["r"]
    return f"{color}[{'#'*fill}{'-'*(width-fill)}]{col['x']}"


def _ck(ok, col):
    return f"{col['g']}OK{col['x']}" if ok else f"{col['r']}X {col['x']}"


def verdict_state(history, a):
    h = list(history) or [a["gate"]]
    n = len(h); n_pass = sum(h); cur = h[-1]
    if n_pass == n and not a["thin"]:
        return "** WOULD PASS **", "g"
    if n_pass == n and a["thin"]:
        return "** PASS - THIN **", "y"
    if n_pass == 0:
        return "** WOULD FAIL **", "r"
    if (not cur) and n_pass <= n // 2:
        return "** WOULD FAIL **", "r"
    return "** UNSTABLE **", "y"


def _history_strip(history, col):
    blocks = [f"{(col['g'] if ok else col['r'])}#{col['x']}" if col is C else ("P" if ok else "F")
              for ok in history]
    return "".join(blocks) + col["d"] + "." * (5 - len(history)) + col["x"]


def render(a, span, window, port, col, history, clear=True):
    o = []
    o.append(f"{col['b']}== GNSS FIELD HEALTH (RAWX) =={col['x']}  "
             f"{col['d']}{port}  window {window:.0f}s{col['x']}")
    o.append("buffer: " + ("OK" if span >= window * 0.95 else f"filling {span:.1f}/{window:.0f}s"))
    o.append("-" * 60)
    o.append("MESSAGE COUNTS (this window = next capture)")
    o.append(f"  RXM-RAWX  {a['n_rawx']:4d}  {_bar(a['n_rawx'],NEED_RAWX,col=col)} "
             f"{_ck(a['n_rawx']>=NEED_RAWX,col)}  need {NEED_RAWX}  {col['d']}(primary){col['x']}")
    o.append(f"  NAV-SAT   {a['n_nav']:4d}  {_bar(a['n_nav'],NEED_NAV,col=col)} "
             f"{_ck(a['n_nav']>=NEED_NAV,col)}  need {NEED_NAV}")
    msm_ok = a['n_1077'] > 0 and a['n_1127'] > 0
    mc = col['g'] if msm_ok else col['y']
    o.append(f"  MSM 1077/1127  {a['n_1077']}/{a['n_1127']}  {mc}{'flowing' if msm_ok else 'check'}"
             f"{col['x']}  {col['d']}(kept for recovery){col['x']}")
    o.append("-" * 60)
    o.append(f"SATELLITES from RAWX  (clean = >={TARGET_EPOCHS} epochs, no locktime slip; "
             f"usable adds >= {ELEV_MASK:.0f} deg)")
    o.append(f"  {'PRN':<9}{'sig':>7}{'elev':>5}{'CNO':>5}{'epochs':>8}{'slip':>6}  clean usable")
    for s in a["sats"][:14]:
        el = f"{s['el']:.0f}" if s["el"] is not None else "--"
        cno = s["cno"]
        if cno is None:
            cnotxt = " --"
        else:
            cc = col["g"] if cno >= 40 else (col["y"] if cno >= 30 else col["r"])
            cnotxt = f"{cc}{cno:3.0f}{col['x']}"
        sl = (col["r"] + "SLIP" + col["x"]) if s["slip"] else (col["g"] + " ok " + col["x"])
        sig = str(s["sig"]) if s["sig"] else "--"
        o.append(f"  {s['key']:<9}{sig:>7}{el:>5}{cnotxt:>5}{s['n']:>8}{sl:>6}   "
                 f"{_ck(s['clean'],col)}   {_ck(s['usable'],col)}")
    o.append(f"  clean: {a['n_clean']} {_ck(a['n_clean']>=NEED_CLEAN,col)}   "
             f"usable (>= {ELEV_MASK:.0f} deg): {a['n_usable']}"
             + ("" if a["n_usable"] >= 2 else f"  {col['y']}(extractor wants >=2){col['x']}"))
    if a["motion"] is not None:
        m = a["motion"]
        mcl = col["g"] if m < 6 else (col["y"] if m < 12 else col["r"])
        note = "" if m < 6 else (f"  {col['y']}(elevated; only valid hand-at-rest){col['x']}"
                                 if m < 12 else f"  {col['r']}(high - check tripod/cable){col['x']}")
        o.append(f"  antenna motion (RMS): {mcl}{m:.1f} mm{col['x']}{note}")
    o.append("-" * 60)
    state, scol = verdict_state(history, a)
    tail = f"  ({', '.join(a['reasons'])})" if (a["reasons"] and scol == "r") else ""
    o.append(f"VERDICT:  {col[scol]}{state}{col['x']}{tail}")
    o.append(f"  recent:  {_history_strip(history, col)}   {col['d']}(newest right){col['x']}")
    sys.stdout.write(("\033[2J\033[H" if clear else "") + "\n".join(o) + "\n")
    sys.stdout.flush()


def main():
    ap = argparse.ArgumentParser(description="Live GNSS capture-health monitor (RAWX).")
    ap.add_argument("--port", default=PORT)
    ap.add_argument("--window", type=float, default=DURATION_SEC)
    ap.add_argument("--refresh", type=float, default=1.0)
    ap.add_argument("--replay", help="parse a saved capture and show one verdict")
    ap.add_argument("--no-color", action="store_true")
    args = ap.parse_args()
    col = NOCOLOR if args.no_color else C

    if args.replay:
        raw = open(args.replay, "rb").read()
        a = assess(*parse_health(raw))
        render(a, args.window, args.window, args.replay, col, deque([a["gate"]]), clear=False)
        return

    print(f"Opening {args.port} ...")
    buf = deque(); history = deque(maxlen=5); last = 0.0
    try:
        with serial.Serial(args.port, BAUD, timeout=0.2) as ser:
            sys.stdout.write("\033[?25l")
            while True:
                chunk = ser.read(ser.in_waiting or 1)
                now = time.time()
                if chunk:
                    buf.append((now, chunk))
                while buf and now - buf[0][0] > args.window:
                    buf.popleft()
                if now - last >= args.refresh:
                    raw = b"".join(c for _, c in buf)
                    span = (now - buf[0][0]) if buf else 0.0
                    a = assess(*parse_health(raw))
                    history.append(a["gate"])
                    render(a, span, args.window, args.port, col, history)
                    last = now
    except serial.SerialException as e:
        sys.stdout.write("\033[?25h")
        print(f"\nSerial error: {e}\n  - another app holding the port? check --port and cable.")
    except KeyboardInterrupt:
        pass
    finally:
        sys.stdout.write("\033[?25h\n")


if __name__ == "__main__":
    main()
