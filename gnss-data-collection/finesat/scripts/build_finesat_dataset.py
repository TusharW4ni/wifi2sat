#!/usr/bin/env python3
import os
import glob
import numpy as np
from scipy import stats
from pyubx2 import UBXReader
from collections import defaultdict
import warnings

try:
    from numpy.exceptions import RankWarning
except ImportError:
    from numpy import RankWarning

# Suppress polyfit rank warnings
warnings.simplefilter('ignore', RankWarning)

# ── Config ──
TARGET_EPOCHS = 100
CYCLE_SLIP_THRESH = 50.0
MS_TO_METERS = 299_792_458.0 / 1000.0
MAX_TARGET_SATS = 6
NUM_FEATURES = 13
POLY_ORDER = 3  # The FineSat Magic Number
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SAMPLE_DIR = os.path.join(SCRIPT_DIR, "..", "data", "samples")
DATASET_DIR = os.path.join(SCRIPT_DIR, "..", "datasets")

CONSTELLATION_MAP = {"1077": "GPS", "1127": "BDS"}
ACCEPTED_SIGNALS  = {"1077": {"1C"}, "1127": {"2I", "1X"}}
NAV_GNSS_MAP      = {0: "GPS", 3: "BDS"}

def _key(constellation, prn):
    return f"{constellation}_{int(prn):03d}"

def extract_13_features(signal):
    """Calculates 13 statistical features from a 1D time-series signal."""
    if len(signal) == 0:
        return np.zeros(NUM_FEATURES)
        
    mean = np.mean(signal)
    var = np.var(signal)
    std = np.std(signal)
    max_val = np.max(signal)
    min_val = np.min(signal)
    ptp_range = max_val - min_val
    median = np.median(signal)
    iqr = np.percentile(signal, 75) - np.percentile(signal, 25)
    skew = stats.skew(signal) if var > 1e-10 else 0.0
    kurtosis = stats.kurtosis(signal) if var > 1e-10 else 0.0
    rms = np.sqrt(np.mean(signal**2))
    mad = np.mean(np.abs(signal - mean))
    energy = np.sum(signal**2)
    
    return np.array([mean, var, std, max_val, min_val, ptp_range, 
                     median, iqr, skew, kurtosis, rms, mad, energy])

def parse_rtcm(filepath):
    """Parses a single RTCM file into elevations and phase arrays."""
    with open(filepath, "rb") as f:
        elevations = {}
        phases = defaultdict(list)
        ubr = UBXReader(f)
        
        for _raw, parsed in ubr:
            if parsed is None: continue
            mid = parsed.identity
            
            if mid == "NAV-SAT":
                for i in range(1, getattr(parsed, "numSvs", 0) + 1):
                    g, s = getattr(parsed, f"gnssId_{i:02d}", -1), getattr(parsed, f"svId_{i:02d}", 0)
                    e = getattr(parsed, f"elev_{i:02d}", -91)
                    if NAV_GNSS_MAP.get(g) and e != -91:
                        elevations[_key(NAV_GNSS_MAP[g], s)] = e
                        
            elif mid in CONSTELLATION_MAP:
                n_sat, n_cell = getattr(parsed, "NSat", 0), getattr(parsed, "NCell", 0)
                if n_sat == 0 or n_cell == 0: continue
                
                rough = {getattr(parsed, f"PRN_{s:02d}"): getattr(parsed, f"DF398_{s:02d}") 
                         for s in range(1, n_sat + 1) if getattr(parsed, f"PRN_{s:02d}", None)}
                         
                for c in range(1, n_cell + 1):
                    prn, sig, fpr = getattr(parsed, f"CELLPRN_{c:02d}", None), getattr(parsed, f"CELLSIG_{c:02d}", None), getattr(parsed, f"DF406_{c:02d}", None)
                    if prn and fpr and prn in rough and sig in ACCEPTED_SIGNALS[mid]:
                        phases[_key(CONSTELLATION_MAP[mid], prn)].append((rough[prn] + fpr) * MS_TO_METERS)
                        
    return elevations, dict(phases)

def process_file_finesat(filepath):
    """Processes a file using the FineSat polynomial detrending (N=6 format)."""
    elevations, phases = parse_rtcm(filepath)
    
    # 1. Filter healthy satellites
    good_sats = []
    for k in phases:
        arr = np.array(phases[k][:TARGET_EPOCHS])
        if len(arr) == TARGET_EPOCHS and int(np.sum(np.abs(np.diff(arr)) > CYCLE_SLIP_THRESH)) == 0:
            good_sats.append((k, elevations.get(k, -91)))
            
    good_sats.sort(key=lambda x: x[1], reverse=True)
    
    if len(good_sats) < 2:
        return None # Corrupted file
        
    ref_key = good_sats[0][0]
    ref_signal = np.array(phases[ref_key][:TARGET_EPOCHS])
    t = np.linspace(0, 10, TARGET_EPOCHS)
    
    # 2. Get Targets (up to 6)
    target_keys = [k for k, _ in good_sats[1:MAX_TARGET_SATS + 1]]
    
    # 3. Extract features for N=6 slots
    sample_features = []
    for i in range(MAX_TARGET_SATS):
        if i < len(target_keys):
            tgt_signal = np.array(phases[target_keys[i]][:TARGET_EPOCHS])
            
            # FINESAT MATH: Difference, then 3rd-order Polyfit Detrending
            diff_signal = tgt_signal - ref_signal
            trend = np.polyval(np.polyfit(t, diff_signal, POLY_ORDER), t)
            finesat_signal = diff_signal - trend
            
            features = extract_13_features(finesat_signal)
        else:
            # Zero-padding for missing satellites
            features = np.zeros(NUM_FEATURES)
            
        sample_features.extend(features)
        
    return np.array(sample_features)

def main():
    files = glob.glob(os.path.join(SAMPLE_DIR, "*.rtcm"))
    
    X = []
    Y = []
    
    print(f"Processing {len(files)} files for FINESAT Pipeline...")
    
    for f in files:
        label = os.path.basename(f).split('-')[0]
        
        features = process_file_finesat(f)
        if features is not None:
            X.append(features)
            Y.append(label)
        else:
            print(f"Skipping corrupted file: {f}")
            
    X = np.array(X)
    Y = np.array(Y)
    
    print(f"\nFineSat Dataset Built!")
    print(f"Feature Matrix (X) Shape: {X.shape}  -> ({len(X)} samples, {MAX_TARGET_SATS} sats * {NUM_FEATURES} features)")
    print(f"Labels Array (Y) Shape:   {Y.shape}")
    
    os.makedirs(DATASET_DIR, exist_ok=True)
    np.save(os.path.join(DATASET_DIR, "X_finesat.npy"), X)
    np.save(os.path.join(DATASET_DIR, "Y_finesat.npy"), Y)
    print("Saved as X_finesat.npy and Y_finesat.npy")

if __name__ == "__main__":
    main()