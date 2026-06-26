#!/usr/bin/env python3
"""
repeat_schedule.py  --  when does the same sky come back?

GPS (and BeiDou MEO) ground tracks repeat on the SIDEREAL day, not the solar
day. So a session captured at time T reappears with the same geometry at
T + k * (sidereal day), which in wall-clock lands ~3m56s earlier each solar day.

  GPS-only  (fast iteration):  k = 1 sidereal day  -> next day, ~3m56s earlier
  GPS+BeiDou (MEO):            k = 7 sidereal days -> ~7 solar days - 27m31s

This script reads a Phase 1 reference session (the manifest written by
run_session.py, or a single UTC time) and prints, for each reference capture,
the repeat instant plus the Phase 3 offset sweep (collect at the repeat time
+/- a few minutes to trace r_AB(dt) and find dt_max). It can also emit a
targets.json that run_session.py consumes directly on the repeat day.

Note: 86164.0905 s is the MEAN sidereal day. The true GPS repeat drifts a few
seconds/day from this due to orbital maintenance, which is exactly why Phase 3
sweeps offsets rather than trusting a single instant.
"""
import sys
import json
import argparse
from datetime import datetime, timedelta, timezone

SIDEREAL_DAY_SEC = 86164.0905
MODE_DAYS = {"gps": 1, "gps+bds": 7, "bds": 7}
DEFAULT_OFFSETS_MIN = [0, 3, -3, 5, -5, 8, -8, 12, -12, 20, -20]


def repeat_time(ref_dt, sidereal_days):
    return ref_dt + timedelta(seconds=sidereal_days * SIDEREAL_DAY_SEC)


def offset_sweep(center_dt, offsets_min=DEFAULT_OFFSETS_MIN):
    pairs = [(o, center_dt + timedelta(minutes=o)) for o in sorted(offsets_min)]
    return pairs


def _parse_iso(s):
    dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def reference_times(args):
    """Return list of (label, ref_dt). From a manifest, or a single --time."""
    if args.manifest:
        with open(args.manifest) as f:
            man = json.load(f)
        out = []
        for e in man["entries"]:
            t = e.get("actual_utc") or e.get("target_utc")
            lbl = f"{e['gesture']}_W{e['window_index']}_r{e['rep']}"
            out.append((lbl, _parse_iso(t)))
        return out
    if args.time:
        return [("ref", _parse_iso(args.time))]
    raise SystemExit("provide --manifest or --time")


def main():
    ap = argparse.ArgumentParser(description="Compute geometry-repeat times.")
    ap.add_argument("--manifest", help="Phase 1 session manifest (run_session.py)")
    ap.add_argument("--time", help="single reference time, ISO UTC (e.g. 2026-05-15T08:32:52Z)")
    ap.add_argument("--mode", choices=list(MODE_DAYS), default="gps",
                    help="gps=1 sidereal day (fast); gps+bds=7 (default: gps)")
    ap.add_argument("--days", type=int, default=None,
                    help="override: number of sidereal days ahead")
    ap.add_argument("--no-sweep", action="store_true", help="print only the center repeat time")
    ap.add_argument("--emit", help="write targets.json for run_session.py --targets")
    args = ap.parse_args()

    sdays = args.days if args.days is not None else MODE_DAYS[args.mode]
    refs = reference_times(args)

    print(f"mode={args.mode}  sidereal_days={sdays}  "
          f"(shift {sdays*SIDEREAL_DAY_SEC/86400:.4f} solar days)\n")

    emit = []
    for lbl, ref_dt in refs:
        center = repeat_time(ref_dt, sdays)
        solar_delta = (center - ref_dt).total_seconds() - sdays * 86400
        print(f"[{lbl}]  ref {ref_dt.strftime('%Y-%m-%d %H:%M:%S')}Z  ->  "
              f"repeat {center.strftime('%Y-%m-%d %H:%M:%S')}Z  "
              f"(wall-clock {solar_delta/60:+.2f} min vs same time {sdays} days on)")
        if args.no_sweep:
            emit.append({"label": lbl, "offset_min": 0,
                         "target_utc": center.isoformat()})
            continue
        for off, t in offset_sweep(center):
            print(f"      e={off:+3d} min  ->  {t.strftime('%H:%M:%S')}Z")
            emit.append({"label": lbl, "offset_min": off,
                         "target_utc": t.isoformat()})
        print()

    if args.emit:
        with open(args.emit, "w") as f:
            json.dump({"created_utc": datetime.now(timezone.utc).isoformat(),
                       "mode": args.mode, "sidereal_days": sdays,
                       "targets": emit}, f, indent=2)
        print(f"wrote {len(emit)} targets -> {args.emit}")


if __name__ == "__main__":
    main()
