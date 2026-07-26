#!/usr/bin/env python3
"""
build_manifest.py

Builds a manifest JSON file from a directory of per-sample .meta.json files
produced during a data-collection session (e.g. RTCM/GNSS gesture capture).

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

Rep numbering:
    Within a given (gesture, window_index) group, samples are sorted by their
    actual capture timestamp (parsed from the filename, falling back to
    capture_start_utc in the meta file). The earliest sample becomes rep 1,
    the next rep 2, and so on.

target_utc:
    target_utc = start_utc + timedelta(minutes = i * 15)
    where start_utc is the --created_utc value (or, if not given, the
    capture_start_utc of the very first sample encountered), and i is the
    window_index of the group (0-indexed).
"""

import argparse
import json
import re
from datetime import datetime, timedelta
from pathlib import Path


# Matches: <gesture>_W<window>-<YYMMDD>-<HHMMSS>Z(.meta.json | _meta.json)
FILENAME_RE = re.compile(
    r"^(?P<gesture>[A-Za-z0-9]+)_W(?P<window>\d+)-"
    r"(?P<yymmdd>\d{6})-(?P<hhmmss>\d{6})Z"
    r"(?:\.meta\.json|_meta\.json)$"
)


def parse_args():
    p = argparse.ArgumentParser(description="Build a session manifest from meta.json sample files.")
    p.add_argument("--session_id", required=True, help="Session identifier, e.g. c1.1_day1")
    p.add_argument("--created_utc", required=True,
                    help="ISO8601 UTC timestamp used as the manifest's created_utc / start_utc anchor")
    p.add_argument("--gestures", required=True,
                    help="Comma-separated list of gestures, e.g. push,pushpull,triangle,m,star")
    p.add_argument("--reps", required=True, type=int, help="Number of reps expected per gesture/window")
    p.add_argument("--mode", required=True, help="Collection mode, e.g. spaced")
    p.add_argument("--input_dir", default=".", help="Directory containing the *.meta.json sample files")
    p.add_argument("--output", default="manifest.json", help="Path to write the resulting manifest JSON")
    return p.parse_args()


def parse_filename_timestamp(yymmdd: str, hhmmss: str) -> datetime:
    """Parse the YYMMDD-HHMMSS embedded in the filename as a UTC datetime."""
    dt = datetime.strptime(yymmdd + hhmmss, "%y%m%d%H%M%S")
    return dt.replace(tzinfo=__import__("datetime").timezone.utc)


def load_samples(input_dir: Path):
    """Find and parse all meta.json sample files in input_dir."""
    samples = []
    for path in sorted(input_dir.iterdir()):
        if not path.is_file():
            continue
        m = FILENAME_RE.match(path.name)
        if not m:
            continue

        with open(path, "r") as f:
            meta = json.load(f)

        gesture = m.group("gesture")
        window_index = int(m.group("window"))
        file_ts = parse_filename_timestamp(m.group("yymmdd"), m.group("hhmmss"))

        # actual_utc: prefer capture_start_utc from the meta file itself,
        # fall back to the timestamp parsed from the filename.
        actual_utc_str = meta.get("capture_start_utc")
        if actual_utc_str:
            actual_utc = datetime.fromisoformat(actual_utc_str)
        else:
            actual_utc = file_ts

        rtcm_name = meta.get("rtcm_file", path.stem.split(".meta")[0].split("_meta")[0] + ".rtcm")
        # Normalize meta filename to the .meta.json convention for the manifest entry
        meta_name = f"{gesture}_W{window_index}-{m.group('yymmdd')}-{m.group('hhmmss')}Z.meta.json"

        samples.append({
            "gesture": gesture,
            "window_index": window_index,
            "actual_utc": actual_utc,
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


def compute_target_utc(start_utc: datetime, window_index: int) -> datetime:
    return start_utc + timedelta(minutes=window_index * 15)


def main():
    args = parse_args()
    input_dir = Path(args.input_dir)
    start_utc = datetime.fromisoformat(args.created_utc)
    gestures = [g.strip() for g in args.gestures.split(",") if g.strip()]

    samples = load_samples(input_dir)
    if not samples:
        raise SystemExit(f"No matching *.meta.json sample files found in {input_dir}")

    entries = assign_reps(samples)

    # Sort entries for output: by gesture order given, then window_index, then rep
    gesture_order = {g: idx for idx, g in enumerate(gestures)}
    entries.sort(key=lambda e: (
        e["window_index"],
        gesture_order.get(e["gesture"], len(gesture_order)),
        e["rep"],
    ))

    manifest_entries = []
    for e in entries:
        target_utc = compute_target_utc(start_utc, e["window_index"])
        manifest_entries.append({
            "gesture": e["gesture"],
            "window_index": e["window_index"],
            "rep": e["rep"],
            "target_utc": target_utc.isoformat(),
            "actual_utc": e["actual_utc"].isoformat(),
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
