#!/usr/bin/env python3
"""
run_breathing_session.py  --  Phase 1 (reference) and Phase 3 (repeat) collection driver.

Phase 1 is a TIMED session: several collection windows spaced in time, each with
a few reps at a fixed distance/angle from the receiver, all tagged so Phase 2/3
can match reference<->repeat unambiguously. Doing this by hand over an hour
invites mislabeled files and missed windows; this wraps
capture_breathing_sample.capture_single_sample with scheduling and writes a
single manifest.

Two ways to specify WHEN to collect:
  (a) evenly spaced windows starting now (or at --start):
        --windows 4 --spacing 15            (4 windows, 15 min apart)
  (b) explicit target times from repeat_schedule.py (use this on the repeat day):
        --targets targets.json

The subject sits at a FIXED distance and angle from the receiver for the whole
session (set via --dist / --angle). The 3-2-1 countdown printed by capture is
your cue: begin normal breathing right at "GO!", when the Glass sound plays.
Hold position/breathing for the full 30s sample -- the Hero sound marks a
healthy sample was captured and saved.

Output: samples_breathing/<session>_manifest.json, the input to
repeat_schedule.py and the Phase 2 analyzer.
"""
import os
import sys
import json
import time
import argparse
from datetime import datetime, timezone, timedelta

from capture_breathing_sample import (
    capture_single_sample, SAMPLE_DIR, RTCM_DIR, JSON_DIR, PORT, fmt_num,
    DIST_FROM_RECEIVER, PERSON_HEIGHT, CHEST_HEIGHT, CHEST_WIDTH, ANGLE_FROM_EAST,
)


def _now():
    return datetime.now(timezone.utc)


def build_condition(dist, angle):
    """The 'd..._h..._ch..._cw..._a...' portion of the filename, using the
    current distance/angle plus the height/chest constants from
    capture_breathing_sample.py."""
    return (f"d{fmt_num(dist)}_h{fmt_num(PERSON_HEIGHT)}"
            f"_ch{fmt_num(CHEST_HEIGHT)}_cw{fmt_num(CHEST_WIDTH)}"
            f"_a{fmt_num(angle)}")


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
    meta_filename = os.path.basename(rtcm_path).rsplit(".", 1)[0] + ".meta.json"
    mp = os.path.join(JSON_DIR, meta_filename)
    try:
        with open(mp) as f:
            return json.load(f).get("capture_start_utc"), mp
    except Exception:
        return None, None


def collect_one(session, condition, window_idx, rep, target_utc, port, no_elev):
    """Capture a single rep, retrying until healthy. Returns a manifest entry."""
    tag = f"{session}_W{window_idx}_{condition}"
    path = None
    while not path:
        path = capture_single_sample(tag, rep, rep, port, no_elev) # retries on None

    actual_utc, meta_path = _read_meta_time(path)
    return {
        "session": session,
        "condition": condition,
        "window_index": window_idx,
        "rep": rep,
        "target_utc": target_utc.isoformat() if target_utc else None,
        "actual_utc": actual_utc,
        "rtcm": os.path.basename(path),
        "meta": os.path.basename(meta_path) if meta_path else None,
    }


def build_windows(args):
    """Return list of (window_index, target_dt or None)."""
    if args.targets:
        with open(args.targets) as f:
            tg = json.load(f)["targets"]
        # one window per target time
        return [(i, _parse_iso(t["target_utc"])) for i, t in enumerate(tg)]
    start = _parse_iso(args.start) if args.start else _now()
    return [(i, start + timedelta(minutes=i * args.spacing))
            for i in range(args.windows)]


def main():
    ap = argparse.ArgumentParser(description="Timed GNSS breathing collection session.")
    ap.add_argument("--session", required=True, help="session name (manifest prefix)")
    ap.add_argument("--dist", type=float, default=DIST_FROM_RECEIVER,
                    help=f"distance from receiver, in feet (default: {DIST_FROM_RECEIVER}, "
                         "from capture_breathing_sample.py)")
    ap.add_argument("--angle", type=float, default=ANGLE_FROM_EAST,
                    help=f"angle from east, in degrees (default: {ANGLE_FROM_EAST}, "
                         "from capture_breathing_sample.py)")
    ap.add_argument("--reps", type=int, default=20, help="reps per window")
    ap.add_argument("--windows", type=int, default=1, help="(spaced mode) number of windows")
    ap.add_argument("--spacing", type=float, default=15.0, help="(spaced mode) minutes apart")
    ap.add_argument("--start", help="(spaced mode) ISO UTC start; default now")
    ap.add_argument("--targets", help="(repeat mode) targets.json from repeat_schedule.py")
    ap.add_argument("--port", default=PORT)
    ap.add_argument("--no-elev", action="store_true")
    args = ap.parse_args()

    condition = build_condition(args.dist, args.angle)

    windows = build_windows(args)
    os.makedirs(SAMPLE_DIR, exist_ok=True)
    os.makedirs(RTCM_DIR, exist_ok=True)
    os.makedirs(JSON_DIR, exist_ok=True)
    manifest = {
        "session": args.session,
        "created_utc": _now().isoformat(),
        "distance_ft": args.dist,
        "angle_deg": args.angle,
        "person_height": PERSON_HEIGHT,
        "chest_height": CHEST_HEIGHT,
        "chest_width": CHEST_WIDTH,
        "condition": condition,
        "reps": args.reps,
        "mode": "targets" if args.targets else "spaced",
        "entries": [],
    }
    man_path = os.path.join(SAMPLE_DIR, f"{args.session}_manifest.json")

    print(f"Session '{args.session}': {len(windows)} window(s), "
          f"condition={condition}, reps={args.reps}")
    for w_idx, target in windows:
        print(f"\n=== Window {w_idx} "
              f"@ {target.strftime('%H:%M:%S')+'Z' if target else 'now'} ===")
        if target:
            wait_until(target)
            print()
        for r in range(1, args.reps + 1):
            entry = collect_one(args.session, condition, w_idx, r, target, args.port, args.no_elev)
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
