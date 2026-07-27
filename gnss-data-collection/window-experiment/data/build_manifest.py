#!/usr/bin/env python3
"""
build_manifest.py

Builds a manifest JSON file from a directory of per-sample .meta.json files
produced during a data-collection session (e.g. RTCM/GNSS gesture capture).

This is a *post-hoc* reconstruction of the manifest that run_session.py writes
live during capture (samples/<session>_manifest.json). The target_utc logic
below mirrors run_session.py's build_windows() / collect_one() exactly:

    A session doesn't necessarily start capturing at window_index 0 -- a
    resumed or repeat-day session (e.g. a "day3" that only recaptures
    window_index 2-3 of a larger multi-day protocol) starts its own
    target_utc schedule at whichever window_index it captures first, not at
    window_index 0. That first window_index is base_window_index: it
    defaults to the smallest window_index found among the loaded samples,
    or can be set explicitly with --start_window (e.g. if that first
    window's own sample files happen to be missing from --input_dir).
    Both modes below key off base_window_index, not the raw window_index.

    "spaced" mode (default):
        start = --start if given, else --created_utc
        target_utc(window_index) = start + timedelta(
            minutes = (window_index - base_window_index) * spacing)
        (spacing defaults to 15.0, same default as run_session.py's --spacing)

    "targets" mode (--targets targets.json given):
        target_utc(window_index) = targets.json["targets"][window_index - base_window_index]["target_utc"]
        (the targets list itself is indexed from 0, exactly like
        `for i, t in enumerate(tg)` in run_session.py's build_windows();
        base_window_index maps that 0 back onto the real first window_index)

Each sample's meta.json is expected to contain (at minimum):
    {
        "capture_start_utc": "<ISO8601 timestamp>",
        "rtcm_file": "<gesture>_W<window>-<YYMMDD>-<HHMMSS>Z.rtcm",
        ...
    }

The corresponding meta filename follows the same stem, e.g.:
    <gesture>_W<window>-<YYMMDD>-<HHMMSS>Z.meta.json
    <gesture>_W<window>-<YYMMDD>-<HHMMSS>Z_meta.json   (also accepted)

Usage:
    python build_manifest.py \
        --session_id c1.1_day1 \
        --created_utc 2026-06-29T16:46:25.965367+00:00 \
        --gestures push,pushpull,triangle,m,star \
        --reps 6 \
        --mode spaced \
        --input_dir /path/to/meta_files \
        --output manifest.json

    # non-default spacing, or a target-anchor different from --created_utc:
    python build_manifest.py ... --spacing 15 --start 2026-06-29T16:46:25.965367+00:00

    # targets mode (repeat day), reusing the same targets.json fed to run_session.py:
    python build_manifest.py ... --mode targets --targets targets.json

Rep numbering:
    Within a given (gesture, window_index) group, samples are sorted by their
    actual capture timestamp (parsed from the filename, falling back to
    capture_start_utc in the meta file). The earliest sample becomes rep 1,
    the next rep 2, and so on -- this matches the order run_session.py itself
    captured them in (nested loop: window -> gesture -> rep 1..N, strictly
    increasing in time).
"""

import argparse
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path


# Matches: <gesture>_W<window>-<YYMMDD>-<HHMMSS>Z(.meta.json | _meta.json)
FILENAME_RE = re.compile(
    r"^(?P<gesture>[A-Za-z0-9]+)_W(?P<window>\d+)-"
    r"(?P<yymmdd>\d{6})-(?P<hhmmss>\d{6})Z"
    r"(?:\.meta\.json|_meta\.json)$"
)


# --- copied verbatim from run_session.py, so timestamp parsing behaves
#     identically (tolerant of "Z" suffix and naive datetimes) ---
def _now():
    return datetime.now(timezone.utc)


def _parse_iso(s):
    dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def parse_args():
    p = argparse.ArgumentParser(description="Build a session manifest from meta.json sample files.")
    p.add_argument("--session_id", required=True, help="Session identifier, e.g. c1.1_day1")
    p.add_argument("--created_utc", required=True,
                    help="ISO8601 UTC timestamp for the manifest's created_utc field, and "
                         "(unless --start is given) the target_utc anchor for "
                         "window_index=base_window_index")
    p.add_argument("--gestures", required=True,
                    help="Comma-separated list of gestures, e.g. push,pushpull,triangle,m,star")
    p.add_argument("--reps", required=True, type=int, help="Number of reps expected per gesture/window")
    p.add_argument("--mode", required=True, help="Collection mode, e.g. spaced or targets")
    p.add_argument("--input_dir", default=".", help="Directory containing the *.meta.json sample files")
    p.add_argument("--output", default="manifest.json", help="Path to write the resulting manifest JSON")

    # --- target_utc controls, mirroring run_session.py's own flags/defaults ---
    p.add_argument("--spacing", type=float, default=15.0,
                    help="(spaced mode) minutes between window targets -- same default as "
                         "run_session.py's --spacing")
    p.add_argument("--start", default=None,
                    help="(spaced mode) ISO UTC anchor for window_index=base_window_index's "
                         "target_utc. run_session.py defaults this to 'now' live; for a "
                         "post-hoc rebuild, it defaults to --created_utc instead if not given "
                         "explicitly")
    p.add_argument("--start_window", type=int, default=None,
                    help="window_index of the first window captured in this session/batch. "
                         "Both modes anchor their target_utc schedule here rather than at "
                         "window_index=0, since a resumed/repeat-day session can start at any "
                         "window_index. Defaults to the smallest window_index found among the "
                         "loaded samples; pass this explicitly only if that first window's "
                         "sample files aren't present in --input_dir")
    p.add_argument("--targets", default=None,
                    help="(targets mode) path to the same targets.json passed to run_session.py's "
                         "--targets. If given, target_utc for window_index i is read directly from "
                         "targets['targets'][i - base_window_index]['target_utc'] instead of "
                         "computed from spacing")
    return p.parse_args()


def parse_filename_timestamp(yymmdd: str, hhmmss: str) -> datetime:
    """Parse the YYMMDD-HHMMSS embedded in the filename as a UTC datetime."""
    dt = datetime.strptime(yymmdd + hhmmss, "%y%m%d%H%M%S")
    return dt.replace(tzinfo=timezone.utc)


def load_samples(input_dir: Path, session_id : str):
    """Find and parse all meta.json sample files in input_dir."""
    samples = []
    skipped = 0
    for path in sorted(input_dir.iterdir()):
        if not path.is_file():
            continue
        m = FILENAME_RE.match(path.name)
        if not m:
            continue

        with open(path, "r") as f:
            meta = json.load(f)

        meta_session_id = meta.get("session_id", meta.get("session"))
        if meta_session_id != session_id:
            skipped += 1
            continue

        gesture = m.group("gesture")
        window_index = int(m.group("window"))
        file_ts = parse_filename_timestamp(m.group("yymmdd"), m.group("hhmmss"))

        # actual_utc: passed through verbatim from capture_start_utc, exactly like
        # run_session.py's _read_meta_time() does (no reparsing/reformatting).
        # Falls back to the filename-derived timestamp if the field is missing.
        actual_utc_str = meta.get("capture_start_utc") or file_ts.isoformat()

        rtcm_name = meta.get("rtcm_file", path.stem.split(".meta")[0].split("_meta")[0] + ".rtcm")
        # Normalize meta filename to the .meta.json convention for the manifest entry
        meta_name = f"{gesture}_W{window_index}-{m.group('yymmdd')}-{m.group('hhmmss')}Z.meta.json"

        samples.append({
            "gesture": gesture,
            "window_index": window_index,
            "actual_utc": actual_utc_str,
            "rtcm": rtcm_name,
            "meta": meta_name,
            "sort_ts": file_ts,  # used purely for ordering
        })
    return samples


def assign_reps(samples):
    """Within each (gesture, window_index) group, sort by timestamp and assign rep numbers 1..N."""
    groups = {}
    for s in samples:
        key = (s["gesture"], s["window_index"])
        groups.setdefault(key, []).append(s)

    entries = []
    for key, group in groups.items():
        group.sort(key=lambda s: s["sort_ts"])
        for i, s in enumerate(group, start=1):
            s["rep"] = i
            entries.append(s)
    return entries


def build_target_lookup(args, base_window_index):
    """
    Returns a function window_index -> datetime, mirroring run_session.py's
    build_windows() exactly:
        - targets mode:  target_utc = targets["targets"][window_index - base_window_index]["target_utc"]
        - spaced mode:   target_utc = start + timedelta(minutes=(window_index - base_window_index) * spacing)

    base_window_index is the window_index of the first window captured in
    this session/batch (see --start_window / main()'s auto-detection). A
    session's target_utc schedule always starts counting from whichever
    window_index it captures first, not from window_index=0 -- so the raw
    window_index has to be rebased before it's used in either formula.
    """
    if args.targets:
        with open(args.targets) as f:
            tg = json.load(f)["targets"]
        targets_by_index = {base_window_index + i: _parse_iso(t["target_utc"]) for i, t in enumerate(tg)}

        def lookup(window_index):
            if window_index not in targets_by_index:
                lo, hi = base_window_index, base_window_index + len(targets_by_index) - 1
                raise SystemExit(
                    f"--targets file has no entry for window_index={window_index} "
                    f"(only {len(targets_by_index)} targets present, covering "
                    f"window_index {lo}..{hi} given base_window_index={base_window_index})"
                )
            return targets_by_index[window_index]

        return lookup

    # spaced mode: same fallback chain as run_session.py's
    # `start = _parse_iso(args.start) if args.start else _now()`, substituting
    # --created_utc for the live _now() call since this is a post-hoc rebuild.
    start = _parse_iso(args.start) if args.start else _parse_iso(args.created_utc)
    spacing = args.spacing

    def lookup(window_index):
        return start + timedelta(minutes=(window_index - base_window_index) * spacing)

    return lookup


def main():
    args = parse_args()
    input_dir = Path(args.input_dir)
    gestures = [g.strip() for g in args.gestures.split(",") if g.strip()]

    if args.targets and args.mode != "targets":
        print(f"Warning: --targets was given but --mode is '{args.mode}' (expected 'targets')")
    if args.mode == "targets" and not args.targets:
        print("Warning: --mode is 'targets' but no --targets file was given; "
              "falling back to the spaced formula (start + (window_index - "
              "base_window_index) * spacing) for target_utc")

    samples = load_samples(input_dir, args.session_id)
    if not samples:
        raise SystemExit(f"No matching *.meta.json sample files found in {input_dir}")

    entries = assign_reps(samples)

    # base_window_index anchors the target_utc schedule at the first window_index
    # actually captured in this session/batch (see build_target_lookup / module
    # docstring) -- auto-detected from the loaded samples unless --start_window
    # overrides it.
    observed_min_window = min(e["window_index"] for e in entries)
    if args.start_window is not None:
        base_window_index = args.start_window
        if base_window_index > observed_min_window:
            print(f"Warning: --start_window={base_window_index} is greater than the smallest "
                  f"window_index found in the samples ({observed_min_window}); target_utc for "
                  f"that window will fall before --start")
    else:
        base_window_index = observed_min_window

    target_utc_for_window = build_target_lookup(args, base_window_index)

    # Sort entries for output: by window_index, then gesture order given, then rep
    gesture_order = {g: idx for idx, g in enumerate(gestures)}
    entries.sort(key=lambda e: (
        e["window_index"],
        gesture_order.get(e["gesture"], len(gesture_order)),
        e["rep"],
    ))

    manifest_entries = []
    for e in entries:
        target_utc = target_utc_for_window(e["window_index"])
        manifest_entries.append({
            "gesture": e["gesture"],
            "window_index": e["window_index"],
            "rep": e["rep"],
            "target_utc": target_utc.isoformat(),
            "actual_utc": e["actual_utc"],
            "rtcm": e["rtcm"],
            "meta": e["meta"],
        })

    manifest = {
        "session": args.session_id,
        "created_utc": args.created_utc,
        "gestures": gestures,
        "reps": args.reps,
        "mode": args.mode,
        "entries": manifest_entries,
    }

    with open(args.output, "w") as f:
        json.dump(manifest, f, indent=2)

    print(f"Wrote manifest with {len(manifest_entries)} entries to {args.output}")


if __name__ == "__main__":
    main()
