#!/usr/bin/env python3
"""
compute_windows_dynamic.py

Scans the samples directory for manifest files. Dynamically identifies the
first and last collection windows for each gesture to compute the most
accurate geometric drift direction, and evaluates the decorrelation time limits.
"""

import os
import io
import sys
import json
import glob
import numpy as np

# Make sibling code dirs importable regardless of CWD
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _d in ("lib", "capture", "analysis"):
    sys.path.insert(0, os.path.join(_ROOT, _d))

# Import the parser from your existing script
from capture_sample import parse_sample, RATE_HZ

# --- Configuration ---
SAMPLE_DIR = os.path.join(_ROOT, "data", "samples")
GESTURE_START_SEC = 3.0
GESTURE_END_SEC = 6.0
R_MIN = 0.95  # Minimum acceptable correlation threshold
OMEGA_LOS = 0.45 / 60.0  # degrees per second (approx 0.45 deg/min)
OMEGA_LOS_RAD = np.deg2rad(OMEGA_LOS)


def detrend_signal(phase_array, rate_hz, start_sec, end_sec):
    """Isolates the gesture by subtracting a 2nd-order polynomial trend."""
    start_idx = int(start_sec * rate_hz)
    end_idx = int(end_sec * rate_hz)

    if len(phase_array) < end_idx:
        return None

    y = np.array(phase_array[start_idx:end_idx])
    t = np.arange(len(y)) / rate_hz

    coefs = np.polyfit(t, y, 2)
    trend = np.polyval(coefs, t)

    return y - trend


def get_true_drift_vector(g_A, g_B):
    """Calculates the true in-plane perpendicular drift vector."""
    g_A = np.array(g_A)
    g_B = np.array(g_B)

    delta_g = g_B - g_A
    g_perp = delta_g - np.dot(delta_g, g_A) * g_A

    norm = np.linalg.norm(g_perp)
    if norm < 1e-9:
        return None

    return g_perp / norm


def load_meta(meta_filename):
    path = os.path.join(SAMPLE_DIR, meta_filename)
    if not os.path.exists(path):
        return None
    with open(path, 'r') as f:
        return json.load(f)


def process_manifest(manifest_path):
    with open(manifest_path, 'r') as f:
        manifest = json.load(f)

    # Group entries by Gesture -> Window -> Reps
    data_map = {}
    for entry in manifest.get("entries", []):
        g = entry["gesture"]
        w = entry["window_index"]
        if g not in data_map:
            data_map[g] = {}
        if w not in data_map[g]:
            data_map[g][w] = []
        data_map[g][w].append(entry)

    print("\n" + "#" * 70)
    print(f" PROCESSING SESSION: {manifest.get('session')} | File: {os.path.basename(manifest_path)}")
    print("#" * 70)

    for gesture, windows in data_map.items():
        print(f"\n--- GESTURE: {gesture.upper()} ---")

        # Dynamically find available windows
        avail_windows = sorted(windows.keys())

        if len(avail_windows) < 2:
            print(
                f"  -> Skipping: Found only {len(avail_windows)} window(s). Need at least 2 to calculate true physical drift.")
            continue

        w_ref_idx = avail_windows[0]
        w_drift_idx = avail_windows[-1]

        print(f"  -> Using Window {w_ref_idx} for 3D structure, and Window {w_drift_idx} to calculate drift.")

        w_ref_entries = windows[w_ref_idx]
        w_drift_entries = windows[w_drift_idx]

        # 1. Gather true drift vectors across the widest available time gap
        meta_ref_rep1 = load_meta(w_ref_entries[0]["meta"])
        meta_drift_rep1 = load_meta(w_drift_entries[0]["meta"])

        if not meta_ref_rep1 or not meta_drift_rep1:
            print("  -> Skipping: Missing meta files for drift calculation.")
            continue

        sats_ref = meta_ref_rep1.get("satellites", {})
        sats_drift = meta_drift_rep1.get("satellites", {})

        true_g_perps = {}
        for sat, info_ref in sats_ref.items():
            if sat in sats_drift and info_ref.get("passed_health"):
                g_A = info_ref["los_enu"]
                g_B = sats_drift[sat]["los_enu"]
                g_perp = get_true_drift_vector(g_A, g_B)
                if g_perp is not None:
                    true_g_perps[sat] = g_perp

        # 2. Build the Averaged Structure Matrix (M) from the Reference Window
        M_matrices = []
        for rep_entry in w_ref_entries:
            meta = load_meta(rep_entry["meta"])
            rtcm_path = os.path.join(SAMPLE_DIR, rep_entry["rtcm"])

            if not meta or not os.path.exists(rtcm_path):
                continue

            with open(rtcm_path, "rb") as f:
                buf = io.BytesIO(f.read())
            _, _, phases, _ = parse_sample(buf)

            healthy_sats = [k for k, v in meta["satellites"].items() if v.get("passed_health")]
            G_list, s_list = [], []

            for sat in healthy_sats:
                if sat not in phases:
                    continue
                s_i = detrend_signal(phases[sat], RATE_HZ, GESTURE_START_SEC, GESTURE_END_SEC)
                if s_i is not None:
                    G_list.append(meta["satellites"][sat]["los_enu"])
                    s_list.append(s_i)

            if len(G_list) >= 3:
                G = np.array(G_list)
                S = np.array(s_list)
                d = np.linalg.pinv(G) @ S
                dt = 1.0 / RATE_HZ
                M_rep = (d @ d.T) * dt
                M_matrices.append(M_rep)

        if not M_matrices:
            print("  -> Failed to compute structure matrix M. Check raw data health.")
            continue

        M_avg = np.mean(M_matrices, axis=0)
        print(f"  -> Built averaged Structure Matrix (M) from {len(M_matrices)} reps.")

        # 3. Calculate Decorrelation and Time Window
        print(f"\n  {'Satellite':<10} | {'Elev(°)':<8} | {'Kappa':<10} | {'Max Window (min)':<15}")
        print("-" * 55)

        for sat, info_ref in sats_ref.items():
            if sat not in true_g_perps:
                continue

            g_A = np.array(info_ref["los_enu"])
            g_perp = true_g_perps[sat]
            elev = info_ref["elev_deg"]

            a = g_A.T @ M_avg @ g_A
            b = g_A.T @ M_avg @ g_perp
            c = g_perp.T @ M_avg @ g_perp

            if a < 1e-12:
                kappa = np.inf
                dt_max_min = 0.0
            else:
                kappa = (c * a - b ** 2) / (a ** 2)

                if kappa <= 0:
                    dt_max_min = float('inf')
                else:
                    dt_max_sec = (1.0 / OMEGA_LOS_RAD) * np.sqrt((2 * (1 - R_MIN)) / kappa)
                    dt_max_min = dt_max_sec / 60.0

            window_str = f"{dt_max_min:.2f}" if dt_max_min != float('inf') else "Infinite (1D)"
            print(f"  {sat:<10} | {elev:<8.1f} | {kappa:<10.4f} | {window_str}")


def main():
    manifest_files = glob.glob(os.path.join(SAMPLE_DIR, "*_manifest.json"))

    if not manifest_files:
        print(f"Error: No manifest files found in '{SAMPLE_DIR}' directory.")
        return

    print(f"Found {len(manifest_files)} manifest(s). Starting batch process...")

    for manifest in sorted(manifest_files):
        process_manifest(manifest)


if __name__ == "__main__":
    main()