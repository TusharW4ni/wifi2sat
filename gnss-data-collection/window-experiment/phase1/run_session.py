#!/usr/bin/env python3
"""
run_session.py  --  Phase 1 (reference) and Phase 3 (repeat) collection driver.

Phase 1 is a TIMED session: several collection windows spaced in time, each with
a few reps of each gesture, all tagged so Phase 2/3 can match reference<->repeat
unambiguously. Doing this by hand over an hour invites mislabeled files and
missed windows; this wraps capture_sample.capture_single_sample with scheduling
and writes a single manifest.

Two ways to specify WHEN to collect:
  (a) evenly spaced windows starting now (or at --start):
        --windows 4 --spacing 15            (4 windows, 15 min apart)
  (b) explicit target times from repeat_schedule.py (use this on the repeat day):
        --targets targets.json

Gestures should be MECHANICALLY REPRODUCED (rail / sled / actuator). The 3-2-1
countdown printed by capture is your actuator-trigger cue: fire the gesture so it
lands a second or two after "GO!". (Timing need not be perfect -- the extractor
detects the actual gesture window -- but the actuator must produce the SAME d(t)
each time, which is the whole point of Phase 1.)

Output: samples/<session>_manifest.json, the input to repeat_schedule.py and the
Phase 2 analyzer.
"""
import os
import sys
import json
import time
import argparse
from datetime import datetime, timezone, timedelta

from capture_sample import capture_single_sample, SAMPLE_DIR, PORT


def _now():
    return datetime.now(timezone.utc)


def _parse_iso(s):
    dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def wait_until(target_dt):
    while True:
        rem = (target_dt - _now()).total_seconds()
        if rem <= 0:
            return
        sys.stdout.write(f"\r  waiting for {target_dt.strftime('%H:%M:%S')}Z "
                         f"-- {rem:6.0f}s   ")
        sys.stdout.flush()
        time.sleep(min(rem, 1.0))


def _read_meta_time(rtcm_path):
    mp = rtcm_path.rsplit(".", 1)[0] + ".meta.json"
    try:
        with open(mp) as f:
            return json.load(f).get("capture_start_utc"), mp
    except Exception:
        return None, None


def collect_one(gesture, window_idx, rep, target_utc, port, no_elev):
    """Capture a single rep, retrying until healthy. Returns a manifest entry."""
    label = f"{gesture}_W{window_idx}"
    path = None
    while not path:
        path = capture_single_sample(label, rep, rep, port, no_elev)  # retries on None
    actual_utc, meta_path = _read_meta_time(path)
    return {
        "gesture": gesture,
        "window_index": window_idx,
        "rep": rep,
        "target_utc": target_utc.isoformat() if target_utc else None,
        "actual_utc": actual_utc,
        "rtcm": os.path.basename(path),
        "meta": os.path.basename(meta_path) if meta_path else None,
    }


def build_windows(args):
    """Return list of (window_index, target_dt or None, [gestures])."""
    if args.targets:
        with open(args.targets) as f:
            tg = json.load(f)["targets"]
        # one window per target time; gestures from --gestures
        return [(i, _parse_iso(t["target_utc"]), args.gestures)
                for i, t in enumerate(tg)]
    start = _parse_iso(args.start) if args.start else _now()
    return [(i, start + timedelta(minutes=i * args.spacing), args.gestures)
            for i in range(args.windows)]


def main():
    ap = argparse.ArgumentParser(description="Timed GNSS gesture collection session.")
    ap.add_argument("--session", required=True, help="session name (manifest prefix)")
    ap.add_argument("--gestures", required=True,
                    help="comma-separated, e.g. push,star")
    ap.add_argument("--reps", type=int, default=5, help="reps per gesture per window")
    ap.add_argument("--windows", type=int, default=4, help="(spaced mode) number of windows")
    ap.add_argument("--spacing", type=float, default=15.0, help="(spaced mode) minutes apart")
    ap.add_argument("--start", help="(spaced mode) ISO UTC start; default now")
    ap.add_argument("--targets", help="(repeat mode) targets.json from repeat_schedule.py")
    ap.add_argument("--port", default=PORT)
    ap.add_argument("--no-elev", action="store_true")
    args = ap.parse_args()
    args.gestures = [g.strip() for g in args.gestures.split(",") if g.strip()]

    windows = build_windows(args)
    os.makedirs(SAMPLE_DIR, exist_ok=True)
    manifest = {
        "session": args.session,
        "created_utc": _now().isoformat(),
        "gestures": args.gestures,
        "reps": args.reps,
        "mode": "targets" if args.targets else "spaced",
        "entries": [],
    }
    man_path = os.path.join(SAMPLE_DIR, f"{args.session}_manifest.json")

    print(f"Session '{args.session}': {len(windows)} window(s), "
          f"gestures={args.gestures}, reps={args.reps}")
    for w_idx, target, gestures in windows:
        print(f"\n=== Window {w_idx} "
              f"@ {target.strftime('%H:%M:%S')+'Z' if target else 'now'} ===")
        if target:
            wait_until(target)
            print()
        for g in gestures:
            for r in range(1, args.reps + 1):
                entry = collect_one(g, w_idx, r, target, args.port, args.no_elev)
                manifest["entries"].append(entry)
                # write incrementally so a crash mid-session doesn't lose the log
                with open(man_path, "w") as f:
                    json.dump(manifest, f, indent=2)

    print(f"\nDone. {len(manifest['entries'])} samples -> {man_path}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nSession interrupted. Manifest holds everything captured so far.")
        sys.exit(0)
