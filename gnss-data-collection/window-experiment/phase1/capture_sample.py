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
PORT = "/dev/cu.usbmodem11301"
BAUD = 115200
DURATION_SEC = 12
RATE_HZ = 10
TARGET_EPOCHS = 100   # epochs ANALYZED; capture runs longer (DURATION_SEC) for count headroom

SPEED_OF_LIGHT = 299_792_458.0
MS_TO_METERS = SPEED_OF_LIGHT / 1000.0

CYCLE_SLIP_THRESH = 50.0    # meters
MIN_REF_ELEV = 45           # degrees (soft threshold; still not enforced below)

CONSTELLATION_MAP = {"1077": "GPS", "1127": "BDS"}
ACCEPTED_SIGNALS  = {"1077": {"1C"}, "1127": {"2I", "1X"}}
NAV_GNSS_MAP      = {0: "GPS", 3: "BDS"}

SAMPLE_DIR = "samples"


def _key(constellation, prn):
    return f"{constellation}_{int(prn):03d}"


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
    print(f"  Collecting Sample {current_idx} of {total_samples} : [{sample_label}]")
    print(f"=======================================================")

    # 1. Capture
    for i in range(3, 0, -1):
        print(f"Starting in {i}...")
        time.sleep(1)
    print("GO! (Perform gesture between seconds 3 and 6)")

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
        os.makedirs(SAMPLE_DIR, exist_ok=True)
        timestamp = start_dt.strftime("%y%m%d-%H%M%SZ")
        filename = f"{sample_label}-{timestamp}.rtcm"
        filepath = os.path.join(SAMPLE_DIR, filename)

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

        meta_path = filepath.rsplit(".", 1)[0] + ".meta.json"
        with open(meta_path, "w") as f:
            json.dump(meta, f, indent=2)

        print(f"Saved: {filename}  (+ {os.path.basename(meta_path)})")
        time.sleep(1.5)  # Brief reset before next capture
        return filepath   # truthy on success; run_session uses this for the manifest


def main():
    parser = argparse.ArgumentParser(description="High-Speed Batch Capture GNSS samples.")
    parser.add_argument("--port", default=PORT, help=f"Serial port (default: {PORT})")
    parser.add_argument("--no-elev", action="store_true", help="Bypass NAV-SAT elevation check if receiver isn't sending it.")
    args = parser.parse_args()

    sample_label = input("Enter gesture label (e.g., 'push', 'swipe_left'): ").strip()
    if not sample_label:
        print("Error: Label cannot be empty.")
        sys.exit(1)

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

    print(f"\nCollected {total_samples} samples for '{sample_label}'.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nCollection interrupted by user. Exiting safely.")
        sys.exit(0)
