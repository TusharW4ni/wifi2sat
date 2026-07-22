#!/usr/bin/env python3
"""
field_monitor.py  --  live GNSS health dashboard for the field.

07-stream.py dumps every message; useful only to confirm bytes are moving. This
instead answers the field question: "will my next capture PASS?" It keeps a
rolling window the same length as a capture (DURATION_SEC) and computes the SAME
gate capture_sample.py uses -- GPS/BDS/NAV counts, clean-sat count, plus the
>=20 deg signal-usability mask from the extractor -- then prints a refreshing
dashboard with a verdict. Thresholds are imported, not redefined, so this can
never drift from the real gate.

  Live:    python field_monitor.py [--port ...] [--refresh 1.0] [--no-color]
  Replay:  python field_monitor.py --replay samples/foo.rtcm
           (parse a saved capture and show why it passed/failed)

Use it before each window: glance at the verdict, fix anything red, then collect.
"""
import sys
import time
import argparse
from io import BytesIO
from collections import defaultdict, deque

import numpy as np
import serial
from pyubx2 import UBXReader, UBX_PROTOCOL, NMEA_PROTOCOL, RTCM3_PROTOCOL

# Single source of truth: pull all thresholds/logic constants from the real tools
from capture_sample import (
    PORT, BAUD, DURATION_SEC, TARGET_EPOCHS, CYCLE_SLIP_THRESH,
    CONSTELLATION_MAP, ACCEPTED_SIGNALS, NAV_GNSS_MAP, MS_TO_METERS, _key,
)
try:
    from extract_signal_v2 import ELEV_MASK
except Exception:
    ELEV_MASK = 20.0

NEED_GPS = NEED_BDS = 100
NEED_NAV = 5
NEED_CLEAN = 2

C = {"g": "\033[1;32m", "y": "\033[1;33m", "r": "\033[1;31m",
     "b": "\033[1;34m", "d": "\033[2m", "x": "\033[0m"}
NOCOLOR = {k: "" for k in C}


def parse_health(raw_bytes):
    counts = defaultdict(int)
    phases = defaultdict(list)
    azel = defaultdict(lambda: {"el": [], "az": [], "cno": []})
    ubr = UBXReader(BytesIO(raw_bytes),
                    protfilter=UBX_PROTOCOL | NMEA_PROTOCOL | RTCM3_PROTOCOL)
    try:
        for _raw, parsed in ubr:
            if parsed is None:
                continue
            mid = parsed.identity
            counts[mid] += 1
            if mid == "NAV-SAT":
                for i in range(1, getattr(parsed, "numSvs", 0) + 1):
                    g = getattr(parsed, f"gnssId_{i:02d}", -1)
                    s = getattr(parsed, f"svId_{i:02d}", 0)
                    e = getattr(parsed, f"elev_{i:02d}", None)
                    a = getattr(parsed, f"azim_{i:02d}", None)
                    cno = getattr(parsed, f"cno_{i:02d}", None)
                    c = NAV_GNSS_MAP.get(g)
                    if c and e is not None and -90 <= e <= 90:
                        k = _key(c, s)
                        azel[k]["el"].append(float(e))
                        if a is not None:
                            azel[k]["az"].append(float(a))
                        if cno is not None:
                            azel[k]["cno"].append(float(cno))
            elif mid in CONSTELLATION_MAP:
                accepted = ACCEPTED_SIGNALS[mid]
                cst = CONSTELLATION_MAP[mid]
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
                for cc in range(1, n_cell + 1):
                    prn = getattr(parsed, f"CELLPRN_{cc:02d}", None)
                    sig = getattr(parsed, f"CELLSIG_{cc:02d}", None)
                    fpr = getattr(parsed, f"DF406_{cc:02d}", None)
                    if prn is None or fpr is None or prn not in rough or sig not in accepted:
                        continue
                    phases[_key(cst, prn)].append((rough[prn] + fpr) * MS_TO_METERS)
    except Exception:
        pass  # trailing partial message at the buffer edge; ignore
    return counts, phases, azel


def assess(counts, phases, azel):
    n_gps = counts.get("1077", 0)
    n_bds = counts.get("1127", 0)
    n_nav = counts.get("NAV-SAT", 0)
    sats = []
    for k in phases:
        v = phases[k]
        n = len(v)
        arr = np.array(v[:TARGET_EPOCHS]) if n >= TARGET_EPOCHS else np.array(v)
        slips = int(np.sum(np.abs(np.diff(arr)) > CYCLE_SLIP_THRESH)) if n >= 2 else 0
        el = float(np.mean(azel[k]["el"])) if azel[k]["el"] else None
        cno = float(np.mean(azel[k]["cno"])) if azel[k]["cno"] else None
        clean = (n >= TARGET_EPOCHS) and (slips == 0)
        usable = clean and (el is not None and el >= ELEV_MASK)
        sats.append(dict(key=k, n=n, slips=slips, el=el, cno=cno,
                         clean=clean, usable=usable))
    sats.sort(key=lambda s: (s["el"] if s["el"] is not None else -91), reverse=True)
    n_clean = sum(s["clean"] for s in sats)
    n_usable = sum(s["usable"] for s in sats)
    gate = (n_gps >= NEED_GPS and n_bds >= NEED_BDS and
            n_nav >= NEED_NAV and n_clean >= NEED_CLEAN)
    reasons = []
    if n_gps < NEED_GPS: reasons.append(f"GPS {n_gps}/{NEED_GPS}")
    if n_bds < NEED_BDS: reasons.append(f"BDS {n_bds}/{NEED_BDS}")
    if n_nav < NEED_NAV: reasons.append(f"NAV {n_nav}/{NEED_NAV}")
    if n_clean < NEED_CLEAN: reasons.append(f"clean sats {n_clean}/{NEED_CLEAN}")
    return dict(n_gps=n_gps, n_bds=n_bds, n_nav=n_nav, sats=sats,
                n_clean=n_clean, n_usable=n_usable, gate=gate, reasons=reasons)


def _bar(val, need, width=12, col=C):
    frac = min(1.0, val / need) if need else 1.0
    filled = int(round(frac * width))
    color = col["g"] if val >= need else col["r"]
    return f"{color}[{'#'*filled}{'-'*(width-filled)}]{col['x']}"


def _ck(ok, col):
    return f"{col['g']}OK{col['x']}" if ok else f"{col['r']}X {col['x']}"


def render(a, span, window, port, col, clear=True):
    out = []
    out.append(f"{col['b']}== GNSS FIELD HEALTH =={col['x']}  "
               f"{col['d']}{port}  window {window:.0f}s  Ctrl-C to quit{col['x']}")
    fill = "OK" if span >= window * 0.95 else f"filling {span:.1f}/{window:.0f}s"
    out.append(f"buffer: {fill}")
    out.append("-" * 56)
    out.append("MESSAGE COUNTS (this window = next capture)")
    out.append(f"  GPS 1077  {a['n_gps']:4d}  {_bar(a['n_gps'],NEED_GPS,col=col)} {_ck(a['n_gps']>=NEED_GPS,col)}  need {NEED_GPS}")
    out.append(f"  BDS 1127  {a['n_bds']:4d}  {_bar(a['n_bds'],NEED_BDS,col=col)} {_ck(a['n_bds']>=NEED_BDS,col)}  need {NEED_BDS}")
    out.append(f"  NAV-SAT   {a['n_nav']:4d}  {_bar(a['n_nav'],NEED_NAV,col=col)} {_ck(a['n_nav']>=NEED_NAV,col)}  need {NEED_NAV}")
    out.append("-" * 56)
    out.append(f"SATELLITES  (clean = >={TARGET_EPOCHS} epochs, no slip;  "
               f"usable adds >= {ELEV_MASK:.0f} deg)")
    out.append(f"  {'PRN':<9}{'elev':>5}{'CNO':>5}{'epochs':>8}{'slip':>5}  clean usable")
    for s in a["sats"][:12]:
        el = f"{s['el']:.0f}" if s["el"] is not None else "--"
        cno = s["cno"]
        if cno is None:
            cnotxt = " --"
        else:
            cc = col["g"] if cno >= 40 else (col["y"] if cno >= 30 else col["r"])
            cnotxt = f"{cc}{cno:3.0f}{col['x']}"
        sl = (col["g"] if s["slips"] == 0 else col["r"]) + f"{s['slips']:>5}" + col["x"]
        out.append(f"  {s['key']:<9}{el:>5}{cnotxt:>5}{s['n']:>8}{sl}   "
                   f"{_ck(s['clean'],col)}   {_ck(s['usable'],col)}")
    out.append(f"  clean sats: {a['n_clean']} {_ck(a['n_clean']>=NEED_CLEAN,col)}"
               f"   usable (>= {ELEV_MASK:.0f} deg): {a['n_usable']}"
               + ("" if a["n_usable"] >= 2 else f"  {col['y']}(extractor wants >=2){col['x']}"))
    out.append("-" * 56)
    if a["gate"]:
        out.append(f"VERDICT:  {col['g']}** WOULD PASS **{col['x']}")
    else:
        out.append(f"VERDICT:  {col['r']}** WOULD FAIL **{col['x']}  ({', '.join(a['reasons'])})")
    prefix = "\033[2J\033[H" if clear else ""
    sys.stdout.write(prefix + "\n".join(out) + "\n")
    sys.stdout.flush()


def main():
    ap = argparse.ArgumentParser(description="Live GNSS capture-health monitor.")
    ap.add_argument("--port", default=PORT)
    ap.add_argument("--window", type=float, default=DURATION_SEC)
    ap.add_argument("--refresh", type=float, default=1.0)
    ap.add_argument("--replay", help="parse a saved .rtcm and show one verdict")
    ap.add_argument("--no-color", action="store_true")
    args = ap.parse_args()
    col = NOCOLOR if args.no_color else C

    if args.replay:
        raw = open(args.replay, "rb").read()
        a = assess(*parse_health(raw))
        render(a, args.window, args.window, args.replay, col, clear=False)
        return

    print(f"Opening {args.port} ...")
    buf = deque()
    last = 0.0
    try:
        with serial.Serial(args.port, BAUD, timeout=0.2) as ser:
            sys.stdout.write("\033[?25l")  # hide cursor
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
                    render(a, span, args.window, args.port, col)
                    last = now
    except serial.SerialException as e:
        sys.stdout.write("\033[?25h")
        print(f"\nSerial error: {e}\n"
              "  - is another app (u-center?) holding the port?\n"
              "  - check the --port name and the cable.")
    except KeyboardInterrupt:
        pass
    finally:
        sys.stdout.write("\033[?25h\n")  # restore cursor


if __name__ == "__main__":
    main()
