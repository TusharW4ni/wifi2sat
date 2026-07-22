#!/usr/bin/env python3
import sys
import io
import time
import os
import json
import argparse
from datetime import datetime, timezone
from collections import defaultdict

import serial
import numpy as np
from pyubx2 import UBXReader, UBX_PROTOCOL, NMEA_PROTOCOL, RTCM3_PROTOCOL

# ── Config ──
PORT = "/dev/cu.usbmodem13301"
BAUD = 115200
DURATION_SEC = 30     # full breathing sample length
RATE_HZ = 10
TARGET_EPOCHS = 100   # epochs ANALYZED; capture runs longer (DURATION_SEC) for count headroom

START_SOUND = "/System/Library/Sounds/Glass.aiff"  # plays when the 30s recording begins
END_SOUND = "/System/Library/Sounds/Hero.aiff"      # plays once a sample passes health checks

SPEED_OF_LIGHT = 299_792_458.0
MS_TO_METERS = SPEED_OF_LIGHT / 1000.0

CYCLE_SLIP_THRESH = 50.0    # meters
MIN_REF_ELEV = 45           # degrees (soft threshold; still not enforced below)

CONSTELLATION_MAP = {"1077": "GPS", "1127": "BDS"}
ACCEPTED_SIGNALS  = {"1077": {"1C"}, "1127": {"2I", "1X"}}
NAV_GNSS_MAP      = {0: "GPS", 3: "BDS"}

SAMPLE_DIR = "../samples_breathing"
RTCM_DIR = os.path.join(SAMPLE_DIR, "rtcm")
JSON_DIR = os.path.join(SAMPLE_DIR, "json")

# ── Subject / geometry constants (edit these by hand per setup) ──
# in inches
DIST_FROM_RECEIVER = 29   # feet, subject distance from receiver
PERSON_HEIGHT = 69        # subject height
CHEST_HEIGHT = 53.75         # subject chest height off the ground
CHEST_WIDTH = 14.5          # subject chest width
ANGLE_FROM_EAST = 0      # degrees, subject angle from east


def fmt_num(n):
    """Drop a trailing '.0' for whole numbers, keep decimals otherwise."""
    return str(int(n)) if float(n) == int(n) else str(n)


def _key(constellation, prn):
    return f"{constellation}_{int(prn):03d}"


def format_condition_label(distance_val, angle_val):
    """Build the 'd..._h..._ch..._cw..._a...' sample label from the current
    distance/angle values plus the module-level height/chest constants."""
    return (f"d{fmt_num(distance_val)}_h{fmt_num(PERSON_HEIGHT)}"
            f"_ch{fmt_num(CHEST_HEIGHT)}_cw{fmt_num(CHEST_WIDTH)}"
            f"_a{fmt_num(angle_val)}")


def los_enu(el_deg, az_deg):
    """Line-of-sight unit vector in ENU from elevation/azimuth (degrees)."""
    el, az = np.deg2rad(el_deg), np.deg2rad(az_deg)
    return [float(np.cos(el) * np.sin(az)),
            float(np.cos(el) * np.cos(az)),
            float(np.sin(el))]


def parse_sample(buf):
    buf.seek(0)
    azel_acc = defaultdict(lambda: {"el": [], "az": []})
    phases = defaultdict(list)
    msg_counts = defaultdict(int)

    ubr = UBXReader(buf, protfilter=UBX_PROTOCOL | NMEA_PROTOCOL | RTCM3_PROTOCOL)
    for _raw, parsed in ubr:
        if parsed is None:
            continue
        mid = parsed.identity
        msg_counts[mid] += 1

        if mid == "NAV-SAT":
            for i in range(1, getattr(parsed, "numSvs", 0) + 1):
                g = getattr(parsed, f"gnssId_{i:02d}", -1)
                s = getattr(parsed, f"svId_{i:02d}", 0)
                e = getattr(parsed, f"elev_{i:02d}", None)
                a = getattr(parsed, f"azim_{i:02d}", None)
                c = NAV_GNSS_MAP.get(g)
                if c and e is not None and a is not None and -90 <= e <= 90:
                    k = _key(c, s)
                    azel_acc[k]["el"].append(float(e))
                    azel_acc[k]["az"].append(float(a))

        elif mid in CONSTELLATION_MAP:
            constellation = CONSTELLATION_MAP[mid]
            accepted = ACCEPTED_SIGNALS[mid]
            n_sat = getattr(parsed, "NSat", 0)
            n_cell = getattr(parsed, "NCell", 0)
            if n_sat == 0 or n_cell == 0:
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
                if prn is None or fpr is None or prn not in rough:
                    continue
                if sig not in accepted:
                    continue
                phases[_key(constellation, prn)].append(
                    (rough[prn] + fpr) * MS_TO_METERS
                )

    # Collapse the ~10 NAV-SAT epochs into one az/el per sat.
    # Azimuth uses a circular mean so a sat near the 0/360 seam
    # does not average to 180.
    elevations, azimuths = {}, {}
    for k, v in azel_acc.items():
        if not v["el"]:
            continue
        elevations[k] = float(np.mean(v["el"]))
        az = np.deg2rad(v["az"])
        azimuths[k] = float(np.rad2deg(np.arctan2(np.sin(az).mean(),
                                                  np.cos(az).mean())) % 360.0)

    return elevations, azimuths, dict(phases), dict(msg_counts)


def capture_single_sample(sample_label, current_idx, total_samples, port, no_elev=False):
    print(f"\n=======================================================")
    print(f"  Collecting Breathing Sample {current_idx} of {total_samples} : [{sample_label}]")
    print(f"=======================================================")

    # 1. Countdown to give the subject time to get into position/ready to breathe
    for i in range(3, 0, -1):
        print(f"Starting in {i}...")
        time.sleep(1)
    print("GO! Begin normal breathing now.")
    os.system(f"afplay {START_SOUND}")   # signals start of the 30s sample

    raw_buffer = io.BytesIO()

    try:
        with serial.Serial(port, BAUD, timeout=1) as ser:
            start_dt = datetime.now(timezone.utc)   # geometry is tied to capture instant
            start = time.time()
            while True:
                elapsed = time.time() - start
                if elapsed > DURATION_SEC:
                    break
                chunk = ser.read(ser.in_waiting or 1)
                if chunk:
                    raw_buffer.write(chunk)
                sys.stdout.write(f"\rRecording... {elapsed:.1f}s / {DURATION_SEC}s")
                sys.stdout.flush()
    except Exception as e:
        print(f"\nError opening serial port: {e}")
        time.sleep(2)
        return None

    raw_size_kb = raw_buffer.getbuffer().nbytes / 1024

    # 2. Parse
    elevations, azimuths, phases, msg_counts = parse_sample(raw_buffer)

    # 3. Health Check: Message Counts
    n_nav = msg_counts.get("NAV-SAT", 0)
    n_gps = msg_counts.get("1077", 0)
    n_bds = msg_counts.get("1127", 0)

    if no_elev:
        msg_counts_ok = (n_gps >= 100) and (n_bds >= 100)
    else:
        msg_counts_ok = (n_gps >= 100) and (n_bds >= 100) and (n_nav >= 5)

    # 3b. Health Check: Satellites & Cycle Slips
    good_sats = []
    for k in sorted(phases.keys()):
        n = len(phases[k])
        arr = np.array(phases[k][:TARGET_EPOCHS]) if n >= TARGET_EPOCHS else np.array(phases[k])
        slips = int(np.sum(np.abs(np.diff(arr)) > CYCLE_SLIP_THRESH)) if n >= 2 else 0
        elev = elevations.get(k, None)

        enough = n >= TARGET_EPOCHS
        clean = slips == 0
        if enough and clean:
            good_sats.append((k, elev if elev is not None else -91))

    if no_elev:
        # Sort primarily by constellation (GPS first, they start with 'G'), then PRN
        good_sats.sort(key=lambda x: x[0])
    else:
        # Sort by elevation (highest first)
        good_sats.sort(key=lambda x: x[1], reverse=True)

    n_good = len(good_sats)

    # Require strict message counts AND at least 2 clean satellites
    sample_healthy = msg_counts_ok and (n_good >= 2)

    # 4. Gatekeeper: Discard or Auto-Save
    if not sample_healthy:
        print(f"\nFAIL | Sample corrupted or too short. Discarding and retrying...")
        if no_elev:
            print(f"   Counts -> GPS 1077: {n_gps}/100 | BDS 1127: {n_bds}/100 | NAV-SAT: (Bypassed)")
        else:
            print(f"   Counts -> GPS 1077: {n_gps}/100 | BDS 1127: {n_bds}/100 | NAV-SAT: {n_nav}/5")
        print(f"   Usable Satellites -> {n_good} (Need >= 2)")
        time.sleep(2.5)  # Pause to read the error
        return None
    else:
        ref_key = good_sats[0][0]
        print(f"\nPASS | Ref: {ref_key} | {n_good - 1} target(s)")
        if no_elev:
            print(f"   Counts -> GPS: {n_gps} | BDS: {n_bds} | NAV: (Bypassed)")
        else:
            print(f"   Counts -> GPS: {n_gps} | BDS: {n_bds} | NAV: {n_nav}")

        # Auto-save healthy sample (UTC filename to avoid DST/timezone ambiguity
        # across week-apart sessions).
        os.makedirs(RTCM_DIR, exist_ok=True)
        os.makedirs(JSON_DIR, exist_ok=True)
        timestamp = start_dt.strftime("%y%m%d-%H%M%SZ")
        filename = f"{sample_label}-{timestamp}.rtcm"
        filepath = os.path.join(RTCM_DIR, filename)

        raw_buffer.seek(0)
        with open(filepath, "wb") as f:
            f.write(raw_buffer.read())

        # Sidecar metadata: capture instant + per-sat geometry, so downstream
        # analysis never has to re-parse the raw stream for geometry.
        good_set = {k for k, _ in good_sats}
        meta = {
            "label": sample_label,
            "capture_start_utc": start_dt.isoformat(),
            "rtcm_file": filename,
            "rate_hz": RATE_HZ,
            "duration_sec": DURATION_SEC,
            "ref_sat": ref_key,
            "satellites": {},
        }
        for k in sorted(elevations):
            if k not in azimuths:
                continue
            meta["satellites"][k] = {
                "elev_deg": round(elevations[k], 3),
                "azim_deg": round(azimuths[k], 3),
                "los_enu": [round(x, 6) for x in los_enu(elevations[k], azimuths[k])],
                "passed_health": k in good_set,
            }

        meta_filename = f"{sample_label}-{timestamp}.meta.json"
        meta_path = os.path.join(JSON_DIR, meta_filename)
        with open(meta_path, "w") as f:
            json.dump(meta, f, indent=2)

        os.system(f"afplay {END_SOUND}")   # signals end of sample: healthy capture saved
        print(f"Saved: {filename}  (+ {meta_filename})")
        time.sleep(1.5)  # Brief reset before next capture
        return filepath   # truthy on success; run_session uses this for the manifest


def main():
    parser = argparse.ArgumentParser(description="High-Speed Batch Capture GNSS Breathing Samples.")
    parser.add_argument("--port", default=PORT, help=f"Serial port (default: {PORT})")
    parser.add_argument("--no-elev", action="store_true", help="Bypass NAV-SAT elevation check if receiver isn't sending it.")
    args = parser.parse_args()

    distance_raw = input(f"Enter distance from receiver in feet [{DIST_FROM_RECEIVER}]: ").strip()
    angle_raw = input(f"Enter angle from east in degrees [{ANGLE_FROM_EAST}]: ").strip()

    try:
        distance_val = float(distance_raw) if distance_raw else float(DIST_FROM_RECEIVER)
        angle_val = float(angle_raw) if angle_raw else float(ANGLE_FROM_EAST)
    except ValueError:
        print("Error: Distance and angle must be numeric.")
        sys.exit(1)

    sample_label = format_condition_label(distance_val, angle_val)

    try:
        total_samples = int(input("How many samples do you want to collect? "))
    except ValueError:
        print("Please enter a valid number.")
        sys.exit(1)

    current_idx = 1
    while current_idx <= total_samples:
        # If capture returns True, we move to the next. If False, we retry the current index.
        success = capture_single_sample(sample_label, current_idx, total_samples, args.port, args.no_elev)
        if success:
            current_idx += 1

    print(f"\nCollected {total_samples} breathing samples for '{sample_label}'.")
    print(f"RTCM files: {os.path.abspath(RTCM_DIR)}")
    print(f"Metadata:   {os.path.abspath(JSON_DIR)}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nCollection interrupted by user. Exiting safely.")
        sys.exit(0)
