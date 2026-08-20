#!/usr/bin/env python3
import os
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

def process_file_finesat_by_satellite(filepath):
    """Like process_file_finesat, but keys features by actual satellite
    identity (PRN) instead of collapsing everything into a fixed 6-slot,
    elevation-ranked vector.

    Slot position isn't a stable channel across captures -- "slot 3" can be
    a different satellite every time depending on which ones pass the health
    check. Keying by PRN instead means every feature vector for "GPS_014"
    actually is GPS_014, so pooling/statistics per satellite are meaningful.
    Also means no zero-padding: a satellite just contributes a row when it's
    present in a capture, and no row when it isn't.

    Returns:
        dict {satellite_key: 13-element feature np.array} for this one file,
        or None if the file doesn't have at least 2 healthy satellites
        (mirrors the "corrupted file" check in process_file_finesat).
    """
    elevations, phases = parse_rtcm(filepath)

    good_sats = []
    for k in phases:
        arr = np.array(phases[k][:TARGET_EPOCHS])
        if len(arr) == TARGET_EPOCHS and int(np.sum(np.abs(np.diff(arr)) > CYCLE_SLIP_THRESH)) == 0:
            good_sats.append((k, elevations.get(k, -91)))

    good_sats.sort(key=lambda x: x[1], reverse=True)

    if len(good_sats) < 2:
        return None  # Corrupted file

    ref_key = good_sats[0][0]
    ref_signal = np.array(phases[ref_key][:TARGET_EPOCHS])
    t = np.linspace(0, 10, TARGET_EPOCHS)

    # Every other healthy satellite becomes a target -- no MAX_TARGET_SATS
    # cap here, since we're not building a fixed-size vector anymore.
    target_keys = [k for k, _ in good_sats[1:]]

    sat_features = {}
    for tgt_key in target_keys:
        tgt_signal = np.array(phases[tgt_key][:TARGET_EPOCHS])

        # Same FineSat math as process_file_finesat: difference against the
        # reference, then 3rd-order polyfit detrend.
        diff_signal = tgt_signal - ref_signal
        trend = np.polyval(np.polyfit(t, diff_signal, POLY_ORDER), t)
        finesat_signal = diff_signal - trend

        sat_features[tgt_key] = extract_13_features(finesat_signal)

    return sat_features


def build_finesat_dataset_by_satellite(filepaths, verbose=True):
    """Builds a per-satellite FineSat feature dataset.

    Args:
        filepaths: iterable of .rtcm file paths. Gesture label is taken from
            the filename, text before the first '-' (matches the
            "<label>-<timestamp>.rtcm" naming from capture_sample.py; note
            this differs from build_finesat_dataset's split('_'), which
            would truncate a label like "swipe_left" to just "swipe" -- if
            your filenames follow the capture_sample.py convention, this
            split('-') is the correct one).
        verbose: print progress/summary info.

    Returns:
        features: dict {satellite_key: np.array of shape (n_obs, 13)}
        labels:   dict {satellite_key: np.array of shape (n_obs,)} -- gesture
                  label for each row of the corresponding features array, in
                  the same order, so features[sat][i] <-> labels[sat][i].
                  Filter to one gesture with e.g.:
                      mask = labels["GPS_014"] == "push"
                      push_only = features["GPS_014"][mask]
    """
    filepaths = list(filepaths)

    raw_features = defaultdict(list)  # sat -> list of (13,) feature vectors
    raw_labels = defaultdict(list)    # sat -> list of label strings

    n_ok, n_skipped = 0, 0
    for f in filepaths:
        label = os.path.basename(f).split('-')[0]

        sat_features = process_file_finesat_by_satellite(f)
        if sat_features is None:
            n_skipped += 1
            if verbose:
                print(f"Skipping corrupted file: {f}")
            continue

        n_ok += 1
        for sat_key, feats in sat_features.items():
            raw_features[sat_key].append(feats)
            raw_labels[sat_key].append(label)

    features = {sat: np.array(v) for sat, v in raw_features.items()}
    labels = {sat: np.array(v) for sat, v in raw_labels.items()}

    if verbose:
        print(f"\nProcessed {n_ok} file(s), skipped {n_skipped} as corrupted.")
        print(f"Satellites observed: {len(features)}")
        for sat in sorted(features):
            print(f"  {sat}: {features[sat].shape[0]} samples "
                  f"({np.unique(labels[sat]).tolist()})")

    return features, labels


def build_finesat_dataset(filepaths, save=True, output_dir=".", verbose=True):
    """Builds the FineSat feature dataset from a list of RTCM file paths.

    Args:
        filepaths: Iterable of paths to .rtcm files to process. The label for
            each sample is derived from the filename, taking the text before
            the first '-' (e.g. "spoofed-run1.rtcm" -> label "spoofed").
        save: If True, saves the resulting arrays to disk as X_finesat.npy
            and Y_finesat.npy inside output_dir.
        output_dir: Directory to save the .npy files into (only used if
            save=True). Defaults to the current directory.
        verbose: If True, prints progress/summary information.

    Returns:
        A tuple (X, Y) of numpy arrays:
            X: shape (n_samples, MAX_TARGET_SATS * NUM_FEATURES) feature matrix
            Y: shape (n_samples,) array of string labels
    """
    filepaths = list(filepaths)

    X = []
    Y = []

    if verbose:
        print(f"Processing {len(filepaths)} files for FINESAT Pipeline...")

    for f in filepaths:
        label = os.path.basename(f).split('_')[0]

        features = process_file_finesat(f)
        if features is not None:
            X.append(features)
            Y.append(label)
        else:
            if verbose:
                print(f"Skipping corrupted file: {f}")

    X = np.array(X)
    Y = np.array(Y)

    if verbose:
        print(f"\nFineSat Dataset Built!")
        print(f"Feature Matrix (X) Shape: {X.shape}  -> ({len(X)} samples, {MAX_TARGET_SATS} sats * {NUM_FEATURES} features)")
        print(f"Labels Array (Y) Shape:   {Y.shape}")

    if save:
        x_path = os.path.join(output_dir, "X_finesat.npy")
        y_path = os.path.join(output_dir, "Y_finesat.npy")
        np.save(x_path, X)
        np.save(y_path, Y)
        if verbose:
            print(f"Saved as {x_path} and {y_path}")

    return X, Y