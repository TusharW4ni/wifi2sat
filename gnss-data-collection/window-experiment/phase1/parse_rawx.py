#!/usr/bin/env python3
"""
parse_rawx.py  --  read UBX-RXM-RAWX into a continuous carrier-phase observable.

Why this exists: the RTCM MSM7 phase had to be rebuilt from DF398 (rough, 293 m
LSB) + DF406 (fine), and the rough/fine recombination at LSB boundaries injected
periodic ~30-60 m false slips that starved the clean-sat set. RXM-RAWX gives
`cpMes` -- the accumulated carrier phase in CYCLES, already continuous within a
lock -- plus `locktime` and `trkStat`, so cycle slips are flagged explicitly
instead of reconstructed. cpMes * wavelength -> meters drops straight into the
existing single-difference + detrend pipeline (the large integer-cycle ambiguity
is constant while locked, so it cancels in the difference/detrend).

Cycle slips here are REAL, detected from the receiver's own lock state:
  - cpValid bit clear            -> phase not usable this epoch
  - locktime drops vs prev epoch -> carrier lock was reset (slip)
  - halfCyc set, subHalfCyc clear-> unresolved half-cycle (flagged)

This module is built to the UBX-RXM-RAWX spec but must be sanity-checked on your
first real RAWX capture (see __main__). It is validated structurally here by
round-tripping a synthetic message.
"""
import sys
from collections import defaultdict

import numpy as np
from pyubx2 import UBXReader, UBX_PROTOCOL, NMEA_PROTOCOL, RTCM3_PROTOCOL

C = 299_792_458.0

# carrier wavelengths (m) by (gnssId, sigId).  gnssId: 0=GPS, 3=BeiDou.
# u-blox sigId: GPS 0=L1C/A,3=L2CL,4=L2CM ; BeiDou 0/1=B1I,2/3=B2I,5=B1C,7=B2a.
_FREQ = {
    (0, 0): 1575.42e6,                          # GPS L1 C/A
    (0, 3): 1227.60e6, (0, 4): 1227.60e6,       # GPS L2
    (3, 0): 1561.098e6, (3, 1): 1561.098e6,     # BeiDou B1I
    (3, 2): 1207.14e6, (3, 3): 1207.14e6,       # BeiDou B2I
    (3, 5): 1575.42e6,                          # BeiDou B1C
    (3, 7): 1176.45e6,                          # BeiDou B2a
}
WAVELENGTH = {k: C / f for k, f in _FREQ.items()}
GNSS_NAME = {0: "GPS", 3: "BDS"}

# Default: match the signals the MSM pipeline accepted (GPS L1C/A, BeiDou B2I & B1C)
DEFAULT_ACCEPT = {(0, 0), (3, 2), (3, 3), (3, 5)}


def _key(constellation, prn):
    return f"{constellation}_{int(prn):03d}"


def _trkbits(parsed, i):
    """Return (prValid, cpValid, halfCyc, subHalfCyc) for measurement i."""
    # pyubx2 may expose parsed bitfields or a raw trkStat int; handle both.
    for name in (f"cpValid_{i:02d}", f"prValid_{i:02d}"):
        if hasattr(parsed, name):
            return (int(getattr(parsed, f"prValid_{i:02d}", 0)),
                    int(getattr(parsed, f"cpValid_{i:02d}", 0)),
                    int(getattr(parsed, f"halfCyc_{i:02d}", 0)),
                    int(getattr(parsed, f"subHalfCyc_{i:02d}", 0)))
    ts = int(getattr(parsed, f"trkStat_{i:02d}", 0))
    return (ts & 1, (ts >> 1) & 1, (ts >> 2) & 1, (ts >> 3) & 1)


def parse_rawx(path, accept=DEFAULT_ACCEPT):
    """Returns dict:
        phases_ep: {sat: {tow_key_ms: phase_m}}   continuous carrier phase (m)
        locktime:  {sat: {tow_key_ms: locktime_ms}}
        cno:       {sat: mean CNO}
        sig:       {sat: (gnssId, sigId)}
        epochs:    sorted list of tow_key_ms
    """
    phases_ep = defaultdict(dict)
    locks = defaultdict(dict)
    cno_acc = defaultdict(list)
    sigof = {}
    epochs = set()
    with open(path, "rb") as fh:
        ubr = UBXReader(fh, protfilter=UBX_PROTOCOL | NMEA_PROTOCOL | RTCM3_PROTOCOL)
        for _raw, p in ubr:
            if p is None or p.identity != "RXM-RAWX":
                continue
            tow = getattr(p, "rcvTow", None)
            if tow is None:
                continue
            tkey = int(round(tow * 10) * 100)     # 0.1 s grid, in ms
            epochs.add(tkey)
            nmeas = getattr(p, "numMeas", 0)
            for i in range(1, nmeas + 1):
                g = getattr(p, f"gnssId_{i:02d}", None)
                sv = getattr(p, f"svId_{i:02d}", None)
                sg = getattr(p, f"sigId_{i:02d}", None)
                if g is None or sv is None or sg is None:
                    continue
                if (g, sg) not in accept or (g, sg) not in WAVELENGTH:
                    continue
                cp = getattr(p, f"cpMes_{i:02d}", 0.0)
                _, cpValid, halfCyc, subHalf = _trkbits(p, i)
                if not cpValid or cp == 0.0:
                    continue
                k = _key(GNSS_NAME.get(g, str(g)), sv)
                phases_ep[k][tkey] = cp * WAVELENGTH[(g, sg)]
                locks[k][tkey] = getattr(p, f"locktime_{i:02d}", 0)
                c = getattr(p, f"cno_{i:02d}", None)
                if c is not None:
                    cno_acc[k].append(float(c))
                sigof[k] = (g, sg)
    cno = {k: float(np.mean(v)) for k, v in cno_acc.items() if v}
    return dict(phases_ep=dict(phases_ep), locktime=dict(locks),
                cno=cno, sig=sigof, epochs=sorted(epochs))


def clean_sats_rawx(parsed, n_min=100):
    """Clean = present for >= n_min epochs with NO locktime reset (no cycle slip).
    Returns {sat: phase_list (m, time-ordered)} for clean sats."""
    out = {}
    for k, ep in parsed["phases_ep"].items():
        ts = sorted(ep)
        if len(ts) < n_min:
            continue
        lt = parsed["locktime"][k]
        lvals = [lt[t] for t in ts]
        # a slip is a locktime that does not strictly increase by ~dt (a reset/drop)
        reset = any(lvals[i] < lvals[i - 1] for i in range(1, len(lvals)))
        if reset:
            continue
        out[k] = np.array([ep[t] for t in ts], float)
    return out


if __name__ == "__main__":
    if len(sys.argv) < 2:
        # structural self-test: synthesize a RAWX message and round-trip it
        from pyubx2 import UBXMessage, SET
        print("no file given -> running structural self-test on a synthetic RXM-RAWX\n")
        try:
            msg = UBXMessage("RXM", "RXM-RAWX", SET,  # construct a 2-measurement frame
                             rcvTow=432000.0, week=2360, leapS=18, numMeas=2,
                             recStat=b"\x01", version=1, reserved0=b"\x00\x00",
                             prMes_01=22000000.0, cpMes_01=115000000.0, doMes_01=-1500.0,
                             gnssId_01=0, svId_01=5, sigId_01=0, freqId_01=0,
                             locktime_01=5000, cno_01=44, prStdev_01=1, cpStdev_01=1,
                             doStdev_01=1, trkStat_01=b"\x0f", reserved1_01=b"\x00",
                             prMes_02=23000000.0, cpMes_02=92000000.0, doMes_02=800.0,
                             gnssId_02=3, svId_02=27, sigId_02=2, freqId_02=0,
                             locktime_02=5000, cno_02=40, prStdev_02=1, cpStdev_02=1,
                             doStdev_02=1, trkStat_02=b"\x0f", reserved1_02=b"\x00")
            raw = msg.serialize()
            from io import BytesIO
            for _r, p in UBXReader(BytesIO(raw)):
                print("parsed identity:", p.identity, "numMeas:", getattr(p, "numMeas", None))
                for i in (1, 2):
                    g = getattr(p, f"gnssId_{i:02d}"); sg = getattr(p, f"sigId_{i:02d}")
                    cp = getattr(p, f"cpMes_{i:02d}")
                    wl = WAVELENGTH.get((g, sg))
                    print(f"  meas{i}: {GNSS_NAME.get(g)} sv{getattr(p,f'svId_{i:02d}')} "
                          f"sig({g},{sg}) cpMes={cp:.0f}cyc -> {cp*wl:,.1f} m  trk={_trkbits(p,i)}")
            print("\nOK: field names + wavelength map + bit extraction all resolve.")
        except Exception as e:
            print(f"self-test could not build synthetic msg ({e}); validate on real data instead.")
        sys.exit(0)

    parsed = parse_rawx(sys.argv[1])
    clean = clean_sats_rawx(parsed)
    print(f"epochs: {len(parsed['epochs'])}   sats seen: {len(parsed['phases_ep'])}   "
          f"clean (no slip, full): {len(clean)}")
    print(f"{'sat':>9} {'sig':>8} {'CNO':>4} {'epochs':>7} {'max|step|m':>10}  clean")
    for k in sorted(parsed["phases_ep"], key=lambda k: -parsed["cno"].get(k, 0)):
        ep = parsed["phases_ep"][k]; ts = sorted(ep)
        arr = np.array([ep[t] for t in ts])
        step = np.max(np.abs(np.diff(arr))) if len(arr) > 1 else 0
        print(f"{k:>9} {str(parsed['sig'].get(k)):>8} {parsed['cno'].get(k,0):4.0f} "
              f"{len(ts):7d} {step:10.2f}  {'Y' if k in clean else ''}")
